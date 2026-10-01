#!/usr/bin/env python3
"""Serve cached Android snapshots from Debian; no dependencies outside stdlib."""
import json
import math
from pathlib import Path
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SNAPSHOT = Path('/opt/phome/data/phone-metrics.json')


def render(metrics):
    lines, described = [], set()
    for metric in metrics:
        name = metric['name']
        if name not in described:
            lines.extend([f"# HELP {name} {metric['help']}", f"# TYPE {name} {metric['type']}"])
            described.add(name)
        labels = metric['labels']
        suffix = '{' + ','.join(f'{key}={json.dumps(str(value))}' for key, value in sorted(labels.items())) + '}' if labels else ''
        lines.append(f"{name}{suffix} {metric['value']}")
    return '\n'.join(lines) + '\n'


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/metrics':
            self.send_error(404)
            return
        try:
            metrics = json.loads(SNAPSHOT.read_text())
            timestamp = next(m['value'] for m in metrics if m['name'] == 'phome_snapshot_timestamp_seconds')
            age = time.time() - timestamp
            if not math.isfinite(age) or not 0 <= age <= 90:
                raise ValueError('Android snapshot is stale')
            body = render(metrics).encode()
        except (OSError, ValueError, KeyError, StopIteration) as error:
            self.send_error(503, str(error))
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; version=0.0.4; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        if len(args) > 1 and str(args[1]) != '200':
            super().log_message(format, *args)


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 9101), Handler).serve_forever()
