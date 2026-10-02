"""Verify crash recovery and that shutdown leaves no running service children."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


class SupervisorTests(unittest.TestCase):
    def test_service_crash_is_restarted_and_shutdown_stops_children(self):
        source = Path(__file__).parents[1] / 'scripts/monitoring-supervisor.py'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / 'scripts'
            scripts.mkdir()
            (scripts / 'scheduler.py').write_text('def main(root, stop, log):\n    stop.wait()\n')
            (scripts / 'collect-phone-metrics.py').write_text('def main(stop):\n    stop.wait()\n')
            helper = root / 'child.py'
            helper.write_text('''import os, signal, sys, time
from pathlib import Path
path = Path(sys.argv[1])
path.write_text(str(os.getpid()))
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
while True:
    time.sleep(1)
''')
            for name in ('prometheus', 'grafana', 'phone-exporter', 'alertmanager'):
                (scripts / ('run-' + name)).write_text(f'exec "{sys.executable}" "{helper}" "{root / (name + ".pid")}"\n')
            bootstrap = ('import importlib.util, pathlib; '
                         f's=importlib.util.spec_from_file_location("supervisor", {str(source)!r}); '
                         'm=importlib.util.module_from_spec(s); s.loader.exec_module(m); '
                         f'm.ROOT=pathlib.Path({directory!r}); m.main()')
            supervisor = subprocess.Popen([sys.executable, '-c', bootstrap])
            children = set()

            def wait_pid(name, previous=None):
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    try:
                        pid = int((root / (name + '.pid')).read_text())
                        if pid != previous:
                            children.add(pid)
                            return pid
                    except (OSError, ValueError):
                        pass
                    time.sleep(.05)
                self.fail('Service did not start/restart: ' + name)

            try:
                for name in ('prometheus', 'grafana', 'phone-exporter', 'alertmanager'):
                    wait_pid(name)
                first = wait_pid('grafana')
                os.kill(first, signal.SIGTERM)
                wait_pid('grafana', first)
                supervisor.terminate()
                self.assertEqual(supervisor.wait(timeout=30), 0)
                for pid in children:
                    with self.assertRaises(ProcessLookupError):
                        os.kill(pid, 0)
            finally:
                if supervisor.poll() is None:
                    supervisor.terminate()
                    supervisor.wait(timeout=30)


if __name__ == '__main__':
    unittest.main()
