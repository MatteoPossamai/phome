#!/usr/bin/env python3
"""Reload provisioned Grafana resources without exposing credentials in argv."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shlex
from urllib.request import Request, urlopen


def main():
    root = Path(os.environ.get('PHOME_DIR', str(Path.home() / 'phome')))
    values = {}
    for line in (root / 'data/grafana.env').read_text().splitlines():
        if line.strip() and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values[key] = shlex.split(value)[0]
    credentials = ('admin:' + values['PHOME_GRAFANA_PASSWORD']).encode()
    auth = 'Basic ' + base64.b64encode(credentials).decode()
    state_path = root / 'data/grafana-provisioning-state.json'
    try:
        state = json.loads(state_path.read_text())
    except (OSError, ValueError):
        state = {}
    for resource in ('datasources', 'dashboards'):
        digest = hashlib.sha256()
        # Dashboard JSON is already polled by Grafana; only provider YAML needs
        # the admin reload endpoint. Never rebuild unchanged data sources.
        directory = root / 'config/grafana/provisioning' / resource
        for path in sorted(directory.rglob('*')):
            if path.is_file() and path.suffix in ('.yaml', '.yml', '.json'):
                digest.update(str(path.relative_to(directory)).encode())
                digest.update(b'\0' + path.read_bytes() + b'\0')
        fingerprint = digest.hexdigest()
        if state.get(resource) == fingerprint:
            print(resource + ': unchanged; skipped')
            continue
        request = Request('http://' + values['PHOME_TAILSCALE_IP'] +
                          ':3000/api/admin/provisioning/' + resource + '/reload',
                          data=b'', headers={'Authorization': auth}, method='POST')
        with urlopen(request, timeout=15) as response:
            print(resource + ': HTTP ' + str(response.status))
        state[resource] = fingerprint
        temporary = state_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(state))
        temporary.replace(state_path)


if __name__ == '__main__':
    main()
