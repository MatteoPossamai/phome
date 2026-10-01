#!/usr/bin/env python3
"""Keep the Debian services alive with one supervisor and bounded logs."""
import importlib.util
import faulthandler
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import subprocess
import threading

ROOT = Path.home() / 'phome'
STOP = threading.Event()
LOCK = threading.Lock()
PROCESSES = {}


def logger(name):
    directory = ROOT / 'data/logs' / name
    directory.mkdir(parents=True, exist_ok=True)
    result = logging.getLogger(name)
    result.setLevel(logging.INFO)
    result.propagate = False
    handler = RotatingFileHandler(directory / 'current', maxBytes=1_000_000, backupCount=5)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    result.addHandler(handler)
    return result


def service(name):
    log = logger(name)
    while not STOP.is_set():
        try:
            with LOCK:
                if STOP.is_set():
                    return
                process = subprocess.Popen(['sh', str(ROOT / 'scripts' / ('run-' + name))],
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           text=True, start_new_session=True)
                PROCESSES[name] = process
            log.info('Started PID %s', process.pid)
            with process.stdout:
                for line in process.stdout:
                    log.info('%s', line.rstrip())
            code = process.wait()
            log.warning('Exited with code %s', code)
        except OSError:
            log.exception('Could not start service')
        finally:
            with LOCK:
                PROCESSES.pop(name, None)
        STOP.wait(5)


def collect():
    log = logger('phone-collector')
    spec = importlib.util.spec_from_file_location('collector', ROOT / 'scripts/collect-phone-metrics.py')
    collector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(collector)
    logging.getLogger().addHandler(log.handlers[0])
    while not STOP.is_set():
        try:
            collector.main(STOP)
        except Exception:
            log.exception('Collector failed; retrying')
            STOP.wait(5)


def main():
    (ROOT / 'data').mkdir(parents=True, exist_ok=True)
    debug = (ROOT / 'data/supervisor-debug.log').open('a')
    faulthandler.register(signal.SIGUSR1, file=debug, all_threads=True)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: STOP.set())
    spec = importlib.util.spec_from_file_location('scheduler', ROOT / 'scripts/scheduler.py')
    scheduler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scheduler)
    threads = [threading.Thread(target=collect, daemon=True),
               threading.Thread(target=scheduler.main, args=(ROOT, STOP, logger('scheduler')), daemon=True)]
    threads += [threading.Thread(target=service, args=(name,), daemon=True)
                for name in ('phone-exporter', 'prometheus', 'grafana')]
    for thread in threads:
        thread.start()
    STOP.wait()
    with LOCK:
        processes = list(PROCESSES.values())
    for process in processes:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for process in processes:
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
    for thread in threads:
        thread.join(timeout=25)


if __name__ == '__main__':
    main()
