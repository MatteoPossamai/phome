"""Exercise real exporter responses, including stopped-collector detection."""
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

spec = importlib.util.spec_from_file_location('exporter', Path(__file__).parents[1] / 'scripts/phone-exporter.py')
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


class ExporterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        exporter.SNAPSHOT = Path(cls.temp.name) / 'snapshot.json'
        cls.server = exporter.ThreadingHTTPServer(('127.0.0.1', 0), exporter.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/metrics'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def snapshot(self, age):
        exporter.SNAPSHOT.write_text(json.dumps([
            dict(name='phome_snapshot_timestamp_seconds', value=time.time() - age,
                 help='Snapshot time.', type='gauge', labels={}),
            dict(name='phome_battery_percent', value=72, help='Battery percentage.', type='gauge', labels={}),
            dict(name='phome_source_available', value=0, help='Source availability.', type='gauge', labels={'source': 'network'}),
        ]))

    def test_live_snapshot_and_explicit_unavailable_source(self):
        self.snapshot(1)
        with urlopen(self.url) as response:
            self.assertIn('text/plain', response.headers['Content-Type'])
            body = response.read().decode()
        self.assertIn('phome_battery_percent 72\n', body)
        self.assertIn('phome_source_available{source="network"} 0\n', body)
        self.assertNotIn('phome_network_receive_bytes_total', body)

    def test_stopped_collector_is_not_reported_as_healthy(self):
        self.snapshot(120)
        with self.assertRaises(HTTPError) as error:
            urlopen(self.url)
        self.assertEqual(error.exception.code, 503)
        error.exception.close()

    def test_corrupt_snapshot_is_not_reported_as_healthy(self):
        exporter.SNAPSHOT.write_text('unfinished JSON')
        with self.assertRaises(HTTPError) as error:
            urlopen(self.url)
        self.assertEqual(error.exception.code, 503)
        error.exception.close()


if __name__ == '__main__':
    unittest.main()
