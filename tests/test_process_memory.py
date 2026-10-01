import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('collector', Path(__file__).parents[1] / 'scripts/collect-phone-metrics.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


class ProcessMemoryTests(unittest.TestCase):
    def test_aggregates_services_and_excludes_unrelated_or_unreadable_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def process(pid, argv, pss, rss):
                path = root / str(pid)
                path.mkdir()
                (path / 'cmdline').write_bytes(('\0'.join(argv) + '\0').encode())
                (path / 'smaps_rollup').write_text(f'rollup\nPss: {pss} kB\nRss: {rss} kB\n')
                return path
            process(1, ['/usr/bin/prometheus'], 10, 20)
            process(2, ['/usr/bin/prometheus'], 30, 40)
            process(3, ['python', '/home/phome/scripts/monitoring-supervisor.py'], 5, 8)
            process(4, ['bash', '-c', 'prometheus'], 99, 99)
            unreadable = process(5, ['/usr/bin/grafana'], 100, 100)
            (unreadable / 'smaps_rollup').unlink()
            values = collector.process_memory(root)
            self.assertEqual(values['prometheus'], {'pss': 40*1024, 'rss': 60*1024})
            self.assertEqual(values['supervisor']['pss'], 5*1024)
            self.assertEqual(set(values), {'prometheus', 'supervisor'})


if __name__ == '__main__':
    unittest.main()
