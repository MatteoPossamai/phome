#!/usr/bin/env python3
"""Interval jobs inside the supervisor: hot reload, no overlapping runs, timeouts."""
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import threading
import time


def load_jobs(path):
    jobs = json.loads(path.read_text())['jobs']
    if not isinstance(jobs, list) or len(jobs) > 32:
        raise ValueError('jobs must be a list of at most 32 jobs')
    names = set()
    for job in jobs:
        name = job['name']
        if not isinstance(name, str) or not re.fullmatch(r'[a-zA-Z0-9_-]+', name) or name in names:
            raise ValueError('Job names must be unique letters, numbers, underscores or hyphens')
        names.add(name)
        for key in ('every_seconds', 'timeout_seconds'):
            value = job[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(key + ' must be a positive finite number')
        if not isinstance(job['command'], str) or not job['command'].strip():
            raise ValueError('command must be a nonempty Bash command')
    return jobs


def run_job(job, root, stop, log):
    env = dict(os.environ, PHOME_DIR=str(root))
    log.info('Starting job %s', job['name'])
    # Capture to disk, then log only the tail: verbose commands cannot fill RAM.
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(['bash', '-c', job['command']], cwd=root, env=env,
                                   stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.monotonic() + job['timeout_seconds']
        cancelled = False
        while process.poll() is None:
            if stop.is_set() or time.monotonic() >= deadline:
                cancelled = True
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                break
            stop.wait(.2)
        if cancelled:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        code = process.wait()
        # Also clean up background descendants left by a completed shell.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        size = output.seek(0, 2)
        output.seek(max(0, size - 8192))
        tail = output.read().decode(errors='replace').strip()
        if tail:
            log.info('Job %s output: %s', job['name'], tail)
        log.log(30 if cancelled or code else 20, 'Job %s finished: exit=%s cancelled=%s',
                job['name'], code, cancelled)
        return code


def main(root, stop, log):
    path = root / 'config/scheduler.json'
    active, jobs, due = {}, {}, {}
    loaded = None
    last_error = None
    while not stop.is_set():
        try:
            contents = path.read_text()
            if contents != loaded:
                parsed = load_jobs(path)
                now = time.monotonic()
                updated = {job['name']: job for job in parsed}
                due = {name: due[name] if jobs.get(name) == job and name in due
                       else now + job['every_seconds'] for name, job in updated.items()}
                jobs = updated
                loaded = contents
                last_error = None
                log.info('Loaded %s scheduled jobs', len(jobs))
        except (OSError, ValueError, KeyError, TypeError) as error:
            if str(error) != last_error:
                log.error('Invalid scheduler config; keeping last valid jobs: %s', error)
                last_error = str(error)
        now = time.monotonic()
        for name, job in jobs.items():
            if now >= due[name] and (name not in active or not active[name].is_alive()):
                def execute(job=job):
                    try:
                        run_job(job, root, stop, log)
                    except Exception:
                        log.exception('Job %s failed', job['name'])
                active[name] = threading.Thread(target=execute, daemon=True)
                active[name].start()
                due[name] = now + job['every_seconds']
        # Retain running removed jobs until finished so same-name re-adds cannot overlap.
        active = {name: thread for name, thread in active.items() if thread.is_alive()}
        stop.wait(.5)
    for thread in active.values():
        thread.join(timeout=5)
