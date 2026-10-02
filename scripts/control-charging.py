#!/usr/bin/env python3
"""Termux: one bounded battery/plug check, invoked by the existing scheduler."""
import argparse
import fcntl
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time

ROOT = Path(os.environ.get('PHOME_DIR', str(Path.home() / 'phome')))
PORT = 38899


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value) + '\n')
    temporary.replace(path)


def validate_config(config):
    if not isinstance(config, dict):
        raise ValueError('Charging settings must be a JSON object')
    for key in ('low_percent', 'high_percent', 'max_snapshot_age_seconds'):
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('Invalid charging setting: ' + key)
    if not 0 <= config['low_percent'] < config['high_percent'] <= 100:
        raise ValueError('Require 0 <= low_percent < high_percent <= 100')
    if not 0 < config['max_snapshot_age_seconds'] <= 90:
        raise ValueError('Snapshot age must be in (0, 90] seconds')
    return config


def battery_percent(path, max_age, now=None):
    now = time.time() if now is None else now
    metrics = json.loads(path.read_text())
    values = {item['name']: item['value'] for item in metrics}
    timestamp = values['phome_snapshot_timestamp_seconds']
    percent = values['phome_battery_percent']
    for value in (timestamp, percent):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('Invalid battery snapshot')
    if not 0 <= now - timestamp <= max_age or not 0 <= percent <= 100:
        raise ValueError('Stale or invalid battery snapshot')
    if not any(item['name'] == 'phome_source_available' and
               item.get('labels', {}).get('source') == 'battery' and item['value'] == 1
               for item in metrics):
        raise ValueError('Battery source unavailable')
    return percent


def desired_state(percent, current, config):
    if percent <= config['low_percent']:
        return True
    if percent >= config['high_percent']:
        return False
    return current


def live_battery_percent():
    result = subprocess.run(['termux-battery-status'], capture_output=True,
                            text=True, check=True, timeout=8)
    battery = json.loads(result.stdout)
    value = battery['percentage']
    if (battery.get('present') is False or isinstance(value, bool)
            or not isinstance(value, (int, float)) or not math.isfinite(value)
            or not 0 <= value <= 100):
        raise ValueError('Invalid direct battery reading')
    return value


def cycle_target(root, mac, percent, current, config):
    """Persist the charge cycle separately from temporary safety overrides."""
    path = root / 'data/charging-cycle.json'
    previous = None
    try:
        previous = json.loads(path.read_text())
    except (OSError, ValueError):
        pass
    latched = current
    if (isinstance(previous, dict) and previous.get('mac') == mac
            and isinstance(previous.get('desired_on'), bool)):
        latched = previous['desired_on']
    target = desired_state(percent, latched, config)
    record = {'mac': mac, 'desired_on': target}
    if record != previous:
        atomic_json(path, record)
    return target


class Plug:
    def __init__(self, mac, address, broadcast):
        if not isinstance(mac, str) or not re.fullmatch(r'[0-9a-fA-F]{12}', mac):
            raise ValueError('Device MAC must be 12 hex digits')
        self.mac = mac.lower()
        self.address = str(ipaddress.IPv4Address(address))
        self.broadcast = str(ipaddress.IPv4Address(broadcast))

    def request(self, method, params=None):
        # Connected UDP filters replies to this address; each call has its own socket.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(1)
            sock.connect((self.address, PORT))
            message = json.dumps({'method': method, 'params': params or {}},
                                 separators=(',', ':')).encode()
            for _ in range(2):
                sock.send(message)
                deadline = time.monotonic() + 1
                while time.monotonic() < deadline:
                    sock.settimeout(max(.001, deadline - time.monotonic()))
                    try:
                        response = json.loads(sock.recv(8192))
                    except socket.timeout:
                        break
                    except (ValueError, UnicodeError):
                        continue
                    if not isinstance(response, dict) or response.get('method') != method:
                        continue
                    if 'error' in response:
                        error = response['error']
                        code = error.get('code') if isinstance(error, dict) else 'unknown'
                        raise RuntimeError(f'WiZ rejected {method} (code {code}); check local-control security settings')
                    result = response.get('result')
                    if isinstance(result, dict):
                        return result
            raise TimeoutError('WiZ request timed out: ' + method)

    def discover(self):
        # Only accept the configured identity, never the first discovered device.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(b'{"method":"getSystemConfig","params":{}}', (self.broadcast, PORT))
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                sock.settimeout(max(.001, deadline - time.monotonic()))
                try:
                    data, address = sock.recvfrom(8192)
                    response = json.loads(data)
                    result = response.get('result', {})
                    if (address[1] == PORT and response.get('method') == 'getSystemConfig'
                            and result.get('mac', '').lower() == self.mac
                            and 'SOCKET' in result.get('moduleName', '')):
                        self.address = address[0]
                        return
                except socket.timeout:
                    break
                except (ValueError, UnicodeError, AttributeError):
                    continue
        raise TimeoutError('Configured WiZ socket not discovered')

    def state(self):
        result = self.request('getPilot')
        if not isinstance(result.get('mac'), str) or result['mac'].lower() != self.mac:
            raise ValueError('WiZ identity mismatch; refusing to control this address')
        if not isinstance(result.get('state'), bool):
            raise ValueError('Invalid WiZ state')
        return result['state']

    def connect(self):
        try:
            return self.state()
        except (OSError, ValueError):
            self.discover()
            return self.state()

    def set_state(self, target):
        # The ack is insufficient: independently read back state after switching.
        result = self.request('setPilot', {'state': target})
        if result.get('success') is not True:
            raise RuntimeError('WiZ did not acknowledge switching')
        time.sleep(.6)
        if self.state() != target:
            raise RuntimeError('WiZ state verification failed')


def run(root=ROOT, action='auto'):
    device_path = root / 'data/charging-device.json'
    if not device_path.exists():
        print('Charging not configured; no plug commands sent')
        return 0
    device = json.loads(device_path.read_text())
    if not isinstance(device, dict):
        raise ValueError('Device settings must be a JSON object')
    if device.get('enabled') is not True:
        print('Charging disabled; no plug commands sent')
        return 0
    config = validate_config(json.loads((root / 'config/charging.json').read_text()))
    status_path = root / 'data/charging-status.json'
    status = {'checked_at': time.time(), 'ok': False, 'action': action,
              'battery_percent': None, 'plug_on': None, 'switched': False}
    try:
        plug = Plug(device['mac'], device['ip'], device['broadcast'])
        current = plug.connect()
        status.update(ip=plug.address, plug_on=current)
        if device['ip'] != plug.address:
            device['ip'] = plug.address
            atomic_json(device_path, device)
        battery_error = None
        if action == 'status':
            target = current
        elif action == 'on':
            target = True
        else:
            try:
                percent = battery_percent(root / 'data/phone-metrics.json',
                                          config['max_snapshot_age_seconds'])
                status['battery_source'] = 'snapshot'
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                status['snapshot_error'] = str(error)
                try:
                    percent = live_battery_percent()
                    status['battery_source'] = 'termux-api'
                except (OSError, ValueError, KeyError, TypeError, AttributeError,
                        subprocess.SubprocessError) as direct_error:
                    battery_error = 'Battery unavailable from snapshot and direct API; requesting power ON: ' + str(direct_error)
            if battery_error:
                # Do not change cycle memory when power is a safety override.
                target = True
            else:
                status['battery_percent'] = percent
                target = cycle_target(root, plug.mac, percent, current, config)
        status['desired_on'] = target
        if target != current:
            plug.set_state(target)
            status.update(plug_on=target, switched=True)
        if battery_error:
            raise RuntimeError(battery_error)
        status['ok'] = True
        return_code = 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        status['error'] = str(error)
        return_code = 1
    atomic_json(status_path, status)
    print(json.dumps(status))
    return return_code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--action', choices=('auto', 'status', 'on'), default='auto')
    args = parser.parse_args()
    (ROOT / 'data').mkdir(parents=True, exist_ok=True)
    # Also prevent overlap between scheduler and manual commands.
    with (ROOT / 'data/charging.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another charging check is running')
            return 0
        try:
            return run(action=args.action)
        except (OSError, ValueError, KeyError, TypeError) as error:
            print('Charging configuration error: ' + str(error), file=sys.stderr)
            return 1


if __name__ == '__main__':
    sys.exit(main())
