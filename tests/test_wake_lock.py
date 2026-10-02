import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class WakeLockTests(unittest.TestCase):
    def test_guard_paths(self):
        source = (Path(__file__).parents[1] / 'scripts/ensure-wake-lock').read_text()
        cases = [('missing', '', True), ('short', '3m59s', False),
                 ('aged', '4m0s', True), ('older', '12m0s', True),
                 ('hour', '1h1m', True), ('day', '1d2h', True),
                 ('no-permission', '', True), ('rejected', '', True)]
        for name, age, renew in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                held = "Wake Locks: size=1\n  PARTIAL_WAKE_LOCK 'termux:service-wakelock' ACQ=-" + age + '\n\n'
                initial = held if age else 'Wake Locks: size=0\n\n'
                if name == 'no-permission':
                    initial = 'Permission denied\n'
                (root / 'state').write_text(initial)
                (root / 'restored').write_text("Wake Locks: size=1\n  PARTIAL_WAKE_LOCK 'termux:service-wakelock' ACQ=-1s\n\n")
                scripts = {
                    'fake-dumpsys': 'cat "$TEST_ROOT/state"',
                    'termux-wake-unlock': 'echo unlock >> "$TEST_ROOT/calls"',
                    'termux-wake-lock': 'echo lock >> "$TEST_ROOT/calls"\n' +
                        ('true' if name == 'rejected' else 'cp "$TEST_ROOT/restored" "$TEST_ROOT/state"'),
                    'sleep': 'true',
                }
                for command, body in scripts.items():
                    path = root / command
                    path.write_text('#!/bin/sh\n' + body + '\n')
                    path.chmod(0o700)
                path = root / 'guard'
                path.write_text(source.replace('/system/bin/dumpsys power', 'fake-dumpsys power'))
                result = subprocess.run(['sh', str(path)], env=dict(os.environ, TEST_ROOT=directory,
                    PATH=directory + ':' + os.environ['PATH']), capture_output=True, text=True)
                self.assertEqual(result.returncode, 1 if name == 'rejected' else 0, result.stderr)
                calls = (root / 'calls').read_text().splitlines() if (root / 'calls').exists() else []
                self.assertEqual('lock' in calls, renew)
                self.assertEqual('unlock' in calls, renew and name != 'no-permission')


if __name__ == '__main__':
    unittest.main()
