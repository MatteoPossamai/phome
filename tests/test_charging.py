import importlib.util
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('charging', Path(__file__).parents[1] / 'scripts/control-charging.py')
charging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(charging)
collector_spec = importlib.util.spec_from_file_location('charging_collector', Path(__file__).parents[1] / 'scripts/collect-phone-metrics.py')
collector = importlib.util.module_from_spec(collector_spec)
collector_spec.loader.exec_module(collector)
CONFIG = {'low_percent': 40, 'high_percent': 80, 'max_snapshot_age_seconds': 60}
MAC = 'aabbccddeeff'


class ChargingTests(unittest.TestCase):
    def snapshot(self, root, percent=70, timestamp=None, available=1):
        (root / 'data/phone-metrics.json').write_text(json.dumps([
            {'name': 'phome_snapshot_timestamp_seconds', 'value': time.time() if timestamp is None else timestamp},
            {'name': 'phome_battery_percent', 'value': percent},
            {'name': 'phome_source_available', 'value': available, 'labels': {'source': 'battery'}},
        ]))

    def setup_root(self, directory):
        root = Path(directory)
        (root / 'data').mkdir()
        (root / 'config').mkdir()
        (root / 'config/charging.json').write_text(json.dumps(CONFIG))
        (root / 'data/charging-device.json').write_text(json.dumps(
            {'enabled': True, 'mac': MAC, 'ip': '192.0.2.1', 'broadcast': '192.0.2.255'}))
        return root

    def test_thresholds_and_band_preserve_both_states(self):
        for current in (True, False):
            for percent, expected in ((0, True), (39, True), (40, True), (41, current),
                                      (79, current), (80, False), (81, False), (100, False)):
                self.assertEqual(charging.desired_state(percent, current, CONFIG), expected)

    def test_health_metrics_reject_old_or_failed_controller(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.setup_root(directory)
            path = root / 'data/charging-status.json'
            for change, expected in (({}, 1), ({'checked_at': 0}, 0), ({'ok': False}, 0),
                                     ({'action': 'status'}, 0), ({'checked_at': float('nan')}, 0)):
                path.write_text(json.dumps({'checked_at': 100, 'ok': True, 'action': 'auto', 'plug_on': False} | change))
                values = collector.charging_metrics(root, now=120)
                self.assertEqual(values['charging_control_ok'], expected)
                if change.get('checked_at') == 0:
                    self.assertNotIn('charging_plug_on', values)
            path.write_text('null')
            self.assertEqual(collector.charging_metrics(root, now=120)['charging_control_ok'], 0)

    def test_reject_invalid_configuration(self):
        for change in ({'low_percent': 80}, {'high_percent': 101}, {'low_percent': -1},
                       {'high_percent': float('nan')}, {'low_percent': True},
                       {'max_snapshot_age_seconds': 91}):
            with self.assertRaises(ValueError):
                charging.validate_config(CONFIG | change)

    def test_reject_stale_missing_failed_future_and_invalid_battery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.setup_root(directory)
            for args in ({'timestamp': time.time() - 61}, {'timestamp': time.time() + 10},
                         {'available': 0}, {'percent': 101}, {'percent': float('nan')},
                         {'percent': True}):
                self.snapshot(root, **args)
                with self.assertRaises(ValueError):
                    charging.battery_percent(root / 'data/phone-metrics.json', 60)
            self.snapshot(root, percent=73)
            self.assertEqual(charging.battery_percent(root / 'data/phone-metrics.json', 60), 73)
            (root / 'data/phone-metrics.json').write_text('[]')
            with self.assertRaises(KeyError):
                charging.battery_percent(root / 'data/phone-metrics.json', 60)

    def test_stale_battery_turns_on_and_reports_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.setup_root(directory)
            self.snapshot(root, timestamp=time.time() - 61)
            with patch.object(charging.Plug, 'connect', return_value=False), \
                    patch.object(charging.Plug, 'set_state') as switch:
                self.assertEqual(charging.run(root), 1)
                switch.assert_called_once_with(True)
            status = json.loads((root / 'data/charging-status.json').read_text())
            self.assertFalse(status['ok'])
            self.assertTrue(status['plug_on'])

    def test_corrupt_nested_battery_source_requests_power_on(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.setup_root(directory)
            self.snapshot(root)
            path = root / 'data/phone-metrics.json'
            metrics = json.loads(path.read_text())
            metrics[-1]['labels'] = None
            path.write_text(json.dumps(metrics))
            with patch.object(charging.Plug, 'connect', return_value=False), \
                    patch.object(charging.Plug, 'set_state') as switch:
                self.assertEqual(charging.run(root), 1)
                switch.assert_called_once_with(True)

    def test_disabled_or_unconfigured_never_contacts_plug(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.setup_root(directory)
            path = root / 'data/charging-device.json'
            path.write_text('{"enabled":false}')
            with patch.object(charging.Plug, 'connect') as connect:
                self.assertEqual(charging.run(root), 0)
                path.unlink()
                self.assertEqual(charging.run(root), 0)
                connect.assert_not_called()

    def test_failed_switch_is_not_recorded_as_success_and_retries_next_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.setup_root(directory)
            self.snapshot(root, percent=35)
            with patch.object(charging.Plug, 'connect', return_value=False), \
                    patch.object(charging.Plug, 'set_state', side_effect=[RuntimeError('rejected'), None]) as switch:
                self.assertEqual(charging.run(root), 1)
                self.assertFalse(json.loads((root / 'data/charging-status.json').read_text())['ok'])
                self.assertEqual(charging.run(root), 0)
                self.assertEqual(switch.call_count, 2)

    def test_restart_reads_actual_state_and_recovers_changed_ip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.setup_root(directory)
            self.snapshot(root)
            def connect(plug):
                plug.address = '192.0.2.2'
                return False
            with patch.object(charging.Plug, 'connect', connect), patch.object(charging.Plug, 'set_state') as switch:
                self.assertEqual(charging.run(root), 0)
                switch.assert_not_called()
            self.assertEqual(json.loads((root / 'data/charging-device.json').read_text())['ip'], '192.0.2.2')

    def test_stale_snapshot_direct_read_does_not_start_charging_at_79(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.setup_root(directory)
            self.snapshot(root, timestamp=time.time()-120)
            with patch.object(charging.Plug, 'connect', return_value=False), \
                    patch.object(charging, 'live_battery_percent', return_value=79), \
                    patch.object(charging.Plug, 'set_state') as switch:
                self.assertEqual(charging.run(root), 0)
                switch.assert_not_called()
            status = json.loads((root / 'data/charging-status.json').read_text())
            self.assertEqual(status['battery_source'], 'termux-api')
            self.assertEqual(status['battery_percent'], 79)

    def test_safety_override_does_not_latch_charging_on_until_80(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.setup_root(directory)
            self.snapshot(root, percent=80)
            with patch.object(charging.Plug, 'connect', return_value=False):
                self.assertEqual(charging.run(root), 0)
            self.snapshot(root, timestamp=time.time()-120)
            with patch.object(charging.Plug, 'connect', return_value=False), \
                    patch.object(charging, 'live_battery_percent', side_effect=TimeoutError('API failed')), \
                    patch.object(charging.Plug, 'set_state') as switch:
                self.assertEqual(charging.run(root), 1)
                switch.assert_called_once_with(True)
            self.snapshot(root, percent=79)
            with patch.object(charging.Plug, 'connect', return_value=True), \
                    patch.object(charging.Plug, 'set_state') as switch:
                self.assertEqual(charging.run(root), 0)
                switch.assert_called_once_with(False)
            self.assertFalse(json.loads((root / 'data/charging-cycle.json').read_text())['desired_on'])

    def test_cycle_persists_until_both_thresholds_despite_external_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.setup_root(directory)
            for percent, current, expected in ((80,True,False),(79,True,False),(41,True,False),
                                               (40,False,True),(41,False,True),(79,False,True),(80,True,False)):
                self.snapshot(root, percent=percent)
                with patch.object(charging.Plug, 'connect', return_value=current), \
                        patch.object(charging.Plug, 'set_state') as switch:
                    self.assertEqual(charging.run(root), 0)
                    switch.assert_called_once_with(expected)

    def test_direct_battery_validation_and_timeout(self):
        for value in (True,-1,101,float('nan')):
            with patch.object(charging.subprocess, 'run', return_value=type('Result',(),{'stdout':json.dumps({'percentage':value})})()):
                with self.assertRaises(ValueError):
                    charging.live_battery_percent()
        with patch.object(charging.subprocess, 'run', return_value=type('Result',(),{'stdout':'{"percentage":39}'})()) as call:
            self.assertEqual(charging.live_battery_percent(),39)
            self.assertEqual(call.call_args.kwargs['timeout'],8)

    def test_identity_mismatch_refuses_switch_and_forces_discovery(self):
        plug = charging.Plug(MAC, '192.0.2.1', '192.0.2.255')
        with patch.object(plug, 'request', return_value={'mac': '000000000000', 'state': True}), \
                patch.object(plug, 'discover', side_effect=TimeoutError('not found')) as discover:
            with self.assertRaises(TimeoutError):
                plug.connect()
            discover.assert_called_once()

    def test_switch_requires_ack_and_readback(self):
        plug = charging.Plug(MAC, '192.0.2.1', '192.0.2.255')
        with patch.object(plug, 'request', return_value={'success': True}), \
                patch.object(plug, 'state', return_value=False), patch.object(charging.time, 'sleep'):
            with self.assertRaises(RuntimeError):
                plug.set_state(True)
        with patch.object(plug, 'request', return_value={'success': False}):
            with self.assertRaises(RuntimeError):
                plug.set_state(True)

    def test_udp_retries_dropped_packet_and_ignores_malformed_reply(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            server.bind(('127.0.0.1', 0))
            server.settimeout(4)
            errors = []
            def respond():
                try:
                    server.recvfrom(8192)  # drop first request
                    _, address = server.recvfrom(8192)
                    server.sendto(b'not json', address)
                    server.sendto(json.dumps({'method': 'getPilot', 'result':
                                             {'mac': MAC, 'state': True}}).encode(), address)
                except Exception as error:
                    errors.append(error)
            thread = threading.Thread(target=respond)
            thread.start()
            try:
                with patch.object(charging, 'PORT', server.getsockname()[1]):
                    self.assertTrue(charging.Plug(MAC, '127.0.0.1', '127.255.255.255').state())
            finally:
                thread.join(timeout=5)
            self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
