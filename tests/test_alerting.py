import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

source = Path(__file__).parents[1] / 'scripts/configure-telegram.py'
spec = importlib.util.spec_from_file_location('telegram_setup', source)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class AlertingTests(unittest.TestCase):
    def test_alertmanager_log_redacts_url_and_bare_token(self):
        spec = importlib.util.spec_from_file_location('supervisor', source.parent / 'monitoring-supervisor.py')
        supervisor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(supervisor)
        token = '123456789:' + 'x' * 35
        line = 'request https://api.telegram.org/bot' + token + '/sendMessage failed: ' + token
        result = supervisor.redact_alertmanager(line)
        self.assertNotIn(token, result)
        self.assertEqual(result.count('[REDACTED]'), 2)

    def test_render_private_files_and_never_embed_token(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config').mkdir()
            template = source.parents[1] / 'config/alertmanager.json'
            (root / 'config/alertmanager.json').write_text(template.read_text())
            path = setup.render(root)
            self.assertEqual(json.loads(path.read_text())['route']['receiver'], 'unconfigured')
            token = '123456789:' + 'x' * 35
            setup.private_write(root / 'data/telegram/bot-token', token)
            setup.private_write(root / 'data/telegram/chat.json', '{"chat_id": 12345}')
            path = setup.render(root)
            self.assertNotIn(token, path.read_text())
            config = json.loads(path.read_text())
            receiver = config['receivers'][0]['telegram_configs'][0]
            self.assertTrue(receiver['send_resolved'])
            self.assertEqual(receiver['chat_id'], 12345)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            stamp = path.stat().st_mtime_ns
            setup.render(root)
            self.assertEqual(path.stat().st_mtime_ns, stamp)
            setup.private_write(root / 'data/telegram/chat.json', '{"chat_id": true}')
            with self.assertRaises(ValueError):
                setup.render(root)

    def test_network_errors_do_not_disclose_secret_url(self):
        token = '123456789:' + 'x' * 35
        for error in [urllib.error.URLError('https://api.telegram.org/bot' + token),
                      urllib.error.HTTPError('https://api.telegram.org/bot' + token, 401, token, {}, None)]:
            with patch.object(setup.urllib.request, 'urlopen', side_effect=error):
                with self.assertRaises(ValueError) as raised:
                    setup.telegram(token, 'getMe')
                self.assertNotIn(token, str(raised.exception))
