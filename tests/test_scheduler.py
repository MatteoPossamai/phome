import importlib.util
import json
import logging
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('scheduler', Path(__file__).parents[1] / 'scripts/scheduler.py')
scheduler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scheduler)


class SchedulerTests(unittest.TestCase):
    def test_slow_job_does_not_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config').mkdir()
            (root / 'config/scheduler.json').write_text(json.dumps({'jobs': [
                {'name': 'slow', 'command': 'true', 'every_seconds': .1, 'timeout_seconds': 3}]}))
            stop = threading.Event()
            running, maximum, count = 0, 0, 0
            def slow_job(*args):
                nonlocal running, maximum, count
                running += 1
                count += 1
                maximum = max(maximum, running)
                stop.wait(.8)
                running -= 1
            with patch.object(scheduler, 'run_job', slow_job):
                thread = threading.Thread(target=scheduler.main, args=(root, stop, logging.getLogger('test')))
                thread.start()
                time.sleep(2.2)
                stop.set()
                thread.join(timeout=5)
            self.assertGreaterEqual(count, 2)
            self.assertEqual(maximum, 1)
            self.assertFalse(thread.is_alive())

    def test_timeout_kills_job(self):
        with tempfile.TemporaryDirectory() as directory:
            start = time.monotonic()
            code = scheduler.run_job({'name': 'hang', 'command': 'sleep 20', 'timeout_seconds': .1},
                                     Path(directory), threading.Event(), logging.getLogger('test'))
            self.assertNotEqual(code, 0)
            self.assertLess(time.monotonic() - start, 5)

    def test_hot_reload_invalid_config_and_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config').mkdir()
            path = root / 'config/scheduler.json'
            def write(command):
                path.write_text(json.dumps({'jobs': [{'name': 'test', 'command': command,
                                                     'every_seconds': .1, 'timeout_seconds': 2}]}))
            def wait_file(name):
                deadline = time.monotonic() + 5
                while not (root / name).exists():
                    if time.monotonic() > deadline:
                        self.fail(name + ' was not created')
                    time.sleep(.02)
            write('echo yes > first')
            stop = threading.Event()
            thread = threading.Thread(target=scheduler.main, args=(root, stop, logging.getLogger('test')))
            thread.start()
            try:
                wait_file('first')
                path.write_text('{invalid')
                (root / 'first').unlink()
                wait_file('first')  # previous valid schedule continues
                write('echo yes > second')
                wait_file('second')
            finally:
                stop.set()
                thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

    def test_duplicate_names_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'jobs.json'
            job = {'name': 'same', 'command': 'true', 'every_seconds': 1, 'timeout_seconds': 1}
            path.write_text(json.dumps({'jobs': [job, job]}))
            with self.assertRaises(ValueError):
                scheduler.load_jobs(path)


if __name__ == '__main__':
    unittest.main()
