#!/usr/bin/env python3
"""Collect real Android host values in Termux, atomically shared with Debian."""
import json
import logging
import math
import os
from pathlib import Path
import subprocess
import threading
import time

ROOT = Path(os.environ.get('PHOME_DIR', str(Path.home() / 'phome')))


def charging_metrics(root=ROOT, now=None):
    """Expose controller health; old successful checks must not look healthy."""
    now = time.time() if now is None else now
    try:
        device = json.loads((root / 'data/charging-device.json').read_text())
        enabled = device.get('enabled') is True
    except (OSError, ValueError, AttributeError):
        enabled = False
    values = {'charging_control_enabled': int(enabled)}
    if not enabled:
        return values
    values['charging_control_ok'] = 0
    try:
        status = json.loads((root / 'data/charging-status.json').read_text())
        timestamp = status['checked_at']
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
            return values
        values['charging_control_timestamp_seconds'] = timestamp
        fresh = 0 <= now - timestamp <= 90
        # Manual status reads do not replace evidence of the automatic controller.
        values['charging_control_ok'] = int(fresh and status.get('ok') is True and status.get('action') == 'auto')
        if fresh and isinstance(status.get('plug_on'), bool):
            values['charging_plug_on'] = int(status['plug_on'])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return values


def process_memory(proc=Path('/proc')):
    """Resident memory of monitoring processes, measured outside PRoot."""
    groups = {}
    for path in proc.iterdir():
        if not path.name.isdigit():
            continue
        try:
            if path.stat().st_uid != os.getuid():
                continue
            argv = (path / 'cmdline').read_bytes().decode(errors='replace').split('\0')
            executable = Path(argv[0]).name
            if executable == 'grafana':
                name = 'grafana'
            elif executable.startswith('gpx_'):
                name = 'grafana-plugin'
            elif executable == 'prometheus':
                name = 'prometheus'
            elif executable == 'proot':
                name = 'proot'
            elif any(arg.endswith('/scripts/monitoring-supervisor.py') for arg in argv):
                name = 'supervisor'
            elif any(arg.endswith('/scripts/phone-exporter.py') for arg in argv):
                name = 'exporter'
            else:
                continue
            values = {}
            for line in (path / 'smaps_rollup').read_text().splitlines()[1:]:
                key, rest = line.split(':', 1)
                values[key] = int(rest.split()[0]) * 1024
            total = groups.setdefault(name, {'rss': 0, 'pss': 0})
            total['rss'] += values['Rss']
            total['pss'] += values['Pss']
        except (OSError, ValueError, KeyError, IndexError):
            continue
    return groups


def collect():
    metrics = []

    def add(name, value, help_text, labels=None, kind='gauge'):
        if isinstance(value, (int, float)) and math.isfinite(value):
            metrics.append(dict(name='phome_' + name, value=value,
                                help=help_text, labels=labels or {}, type=kind))

    def source(name, ok):
        add('source_available', int(ok), 'Whether an Android metric source is readable.', {'source': name})

    for name, value in charging_metrics().items():
        add(name, value, 'Smart-plug charging controller ' + name.removeprefix('charging_').replace('_', ' ') + '.')
    add('snapshot_timestamp_seconds', time.time(), 'Time this host snapshot was collected.')
    add('uptime_seconds', time.clock_gettime(time.CLOCK_BOOTTIME), 'Android elapsed time since boot including sleep.')
    add('cpu_logical_count', os.cpu_count() or 1, 'Number of logical CPUs.')
    try:
        result = subprocess.run(['termux-battery-status'], capture_output=True, text=True, timeout=20, check=True)
        battery = json.loads(result.stdout)
        add('battery_percent', float(battery['percentage']), 'Battery charge percentage.')
        add('battery_temperature_celsius', float(battery['temperature']), 'Battery temperature in Celsius.')
        add('battery_voltage_volts', float(battery['voltage']) / 1000, 'Battery voltage in volts.')
        add('battery_plugged', int(battery.get('plugged', 'UNPLUGGED') != 'UNPLUGGED'), 'Whether the phone is connected to external power.')
        add('battery_charging', int(battery.get('status') == 'CHARGING'), 'Whether Android reports charging.')
        source('battery', True)
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
        logging.warning('Battery unavailable: %s', error)
        source('battery', False)
    try:
        memory = {}
        for line in Path('/proc/meminfo').read_text().splitlines():
            key, rest = line.split(':', 1)
            memory[key] = int(rest.split()[0]) * 1024
        for key, name in [('MemTotal', 'total'), ('MemAvailable', 'available'), ('MemFree', 'free'), ('Cached', 'cached')]:
            if key in memory:
                add('memory_' + name + '_bytes', memory[key], 'Android host memory ' + name + ' in bytes.')
        source('memory', True)
    except (OSError, ValueError):
        source('memory', False)
    try:
        groups = process_memory()
        for service, values in groups.items():
            for kind, value in values.items():
                add('process_memory_' + kind + '_bytes', value,
                    'Resident monitoring process memory; PSS apportions shared pages.',
                    {'service': service})
        source('process_memory', bool(groups))
    except OSError:
        source('process_memory', False)
    try:
        disk = os.statvfs(ROOT)
        for name, value in [('size', disk.f_blocks), ('free', disk.f_bfree), ('available', disk.f_bavail), ('used', disk.f_blocks - disk.f_bfree)]:
            add('storage_' + name + '_bytes', value * disk.f_frsize, 'Termux data filesystem ' + name + ' in bytes.')
        source('storage', True)
    except OSError:
        source('storage', False)
    frequencies = 0
    for cpu in range(os.cpu_count() or 1):
        try:
            value = int(Path(f'/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_cur_freq').read_text())
            add('cpu_frequency_hertz', value * 1000, 'Reported CPU frequency; not CPU utilization.', {'cpu': str(cpu)})
            frequencies += 1
        except (OSError, ValueError):
            pass
    source('cpu_frequency', frequencies > 0)
    try:
        modes = ['user', 'nice', 'system', 'idle', 'iowait', 'irq', 'softirq', 'steal']
        for line in Path('/proc/stat').read_text().splitlines():
            fields = line.split()
            if fields and fields[0].startswith('cpu') and fields[0] != 'cpu':
                for mode, ticks in zip(modes, fields[1:]):
                    add('cpu_seconds_total', int(ticks) / os.sysconf('SC_CLK_TCK'), 'CPU time by mode.', {'cpu': fields[0][3:], 'mode': mode}, 'counter')
        source('cpu_usage', True)
    except (OSError, ValueError):
        source('cpu_usage', False)
    try:
        for line in Path('/proc/net/dev').read_text().splitlines()[2:]:
            interface, values = line.split(':', 1)
            fields = values.split()
            for direction, index in [('receive', 0), ('transmit', 8)]:
                add('network_' + direction + '_bytes_total', int(fields[index]), 'Network bytes by interface.', {'interface': interface.strip()}, 'counter')
        source('network', True)
    except (OSError, ValueError, IndexError):
        source('network', False)
    return metrics


def main(stop=None):
    stop = stop or threading.Event()
    output = ROOT / 'data/phone-metrics.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    while not stop.is_set():
        started = time.monotonic()
        temporary = output.with_suffix('.tmp')
        temporary.write_text(json.dumps(collect()))
        temporary.replace(output)
        stop.wait(max(1, 5 - (time.monotonic() - started)))


if __name__ == '__main__':
    main()
