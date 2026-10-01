#!/usr/bin/env python3
"""Termux: report monitoring process trees using real Android /proc memory."""
from pathlib import Path


def fields(path):
    values = {}
    for line in path.read_text().splitlines():
        key, _, value = line.partition(':')
        values[key] = value.strip()
    return values


def main():
    processes = {}
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit():
            continue
        try:
            status = fields(directory / 'status')
            argv = (directory / 'cmdline').read_bytes().decode(errors='replace').split('\0')
            if not argv[0]:
                continue
            try:
                memory = fields(directory / 'smaps_rollup')
            except OSError:
                memory = {}
            processes[int(directory.name)] = {
                'parent': int(status['PPid']), 'argv': argv,
                'rss': int(memory.get('Rss', status.get('VmRSS', '0 kB')).split()[0]),
                'pss': int(memory['Pss'].split()[0]) if 'Pss' in memory else None}
        except (OSError, ValueError, KeyError):
            continue
    supervisors = [pid for pid, p in processes.items()
                   if any(arg.endswith('/scripts/monitoring-supervisor.py') for arg in p['argv'])]
    if len(supervisors) != 1:
        raise SystemExit('Expected one monitoring supervisor; found ' + str(len(supervisors)))
    supervisor = supervisors[0]

    def descendants(pid):
        result = {pid}
        pending = [pid]
        while pending:
            parent = pending.pop()
            children = [child for child, p in processes.items() if p['parent'] == parent]
            result.update(children)
            pending.extend(children)
        return result

    all_pids = descendants(supervisor)
    groups = {'Supervisor / scheduled jobs': set(all_pids)}
    for pid, p in processes.items():
        if p['parent'] != supervisor:
            continue
        tree = descendants(pid)
        commands = [processes[child]['argv'] for child in tree]
        name = None
        if any(Path(args[0]).name == 'grafana' for args in commands):
            name = 'Grafana + plugins + PRoot'
        elif any(Path(args[0]).name == 'prometheus' for args in commands):
            name = 'Prometheus + PRoot'
        elif any(any(arg.endswith('/scripts/phone-exporter.py') for arg in args) for args in commands):
            name = 'Python exporter + PRoot'
        if name:
            groups.setdefault(name, set()).update(tree)
            groups['Supervisor / scheduled jobs'].difference_update(tree)
    print(f'{"Component":35} {"PIDs":>4} {"PSS MiB":>10} {"RSS MiB":>10}')
    for name, pids in list(groups.items()) + [('TOTAL', all_pids)]:
        pss = sum(processes[pid]['pss'] or 0 for pid in pids)
        complete = all(processes[pid]['pss'] is not None for pid in pids)
        pss_text = f'{pss / 1024:.1f}' if complete else 'unavailable'
        rss = sum(processes[pid]['rss'] for pid in pids) / 1024
        print(f'{name:35} {len(pids):4} {pss_text:>10} {rss:10.1f}')
    memory = fields(Path('/proc/meminfo'))
    for key in ('MemTotal', 'MemAvailable', 'Cached'):
        print(f'{key}: {int(memory[key].split()[0]) / 1024:.1f} MiB')
    print('PSS divides shared pages between processes; RSS can double-count them.')
    print('This is a point-in-time reading, not peak usage. Run in Termux, outside Debian.')


if __name__ == '__main__':
    main()
