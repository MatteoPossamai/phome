import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location('reload_grafana', Path(__file__).parents[1] / 'scripts/reload-grafana.py')
reload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reload)


class ReloadTests(unittest.TestCase):
    def setup_root(self, directory):
        root = Path(directory)
        (root / 'data').mkdir()
        (root / 'data/grafana.env').write_text("PHOME_TAILSCALE_IP='100.64.0.1'\nPHOME_GRAFANA_PASSWORD='test-only'\n")
        for resource in ('datasources', 'dashboards'):
            path = root / 'config/grafana/provisioning' / resource
            path.mkdir(parents=True)
            (path / 'config.yml').write_text('apiVersion: 1\n')
        return root

    def test_unchanged_files_skip_reload_and_changed_source_reloads_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.setup_root(directory)
            response = MagicMock()
            response.__enter__.return_value.status = 200
            with patch.dict(os.environ, PHOME_DIR=directory), patch.object(reload, 'urlopen', return_value=response) as request, contextlib.redirect_stdout(io.StringIO()):
                reload.main()
                self.assertEqual(request.call_count, 2)
                reload.main()
                self.assertEqual(request.call_count, 2)
                (root / 'config/grafana/provisioning/datasources/config.yml').write_text('apiVersion: 1\n# changed\n')
                reload.main()
                self.assertEqual(request.call_count, 3)
                self.assertIn('/datasources/reload', request.call_args.args[0].full_url)

    def test_failed_reload_is_not_recorded_as_applied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.setup_root(directory)
            with patch.dict(os.environ, PHOME_DIR=directory), patch.object(reload, 'urlopen', side_effect=OSError('unavailable')):
                with self.assertRaises(OSError):
                    reload.main()
            self.assertFalse((root / 'data/grafana-provisioning-state.json').exists())


if __name__ == '__main__':
    unittest.main()
