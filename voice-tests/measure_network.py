#!/usr/bin/env python3
"""Measure the guest network sequentially before starting acoustic coverage."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def complete(row):
    metrics = row.get('metrics') or {}
    return (row.get('ssh_exit_code') == 0 and row.get('probe_exit_code') == 0
        and 200 <= (metrics.get('http_code') or 0) < 300
        and metrics.get('size_' + row['direction']) == row['requested_bytes'])


def retryable(row):
    return (row.get('ssh_timed_out', False) or row.get('ssh_exit_code') == 255
        or row.get('probe_exit_code') in (5, 6, 7, 28, 35, 52, 55, 56))


def attempt(vm, program, direction, size, number, timeout, directory):
    row = {'direction': direction, 'requested_bytes': size, 'attempt': number,
        'host_started_unix_ms': time.time_ns() / 1e6}
    try:
        result = subprocess.run([str(ROOT / 'install-tests/electron-macos/guest-automate.sh'), 'ssh', vm,
            '~/Developer/openbase-coder-workspace/.venv/bin/python -c ' + shlex.quote(program)],
            text=True, capture_output=True, timeout=timeout + 15)
    except subprocess.TimeoutExpired:
        # A read-only probe may repeat; preserve the failed observation first.
        return {**row, 'host_finished_unix_ms': time.time_ns() / 1e6,
            'ssh_exit_code': None, 'ssh_timed_out': True,
            'finding': 'Guest probe deadline; this attempt is unmeasured'}
    row.update(host_finished_unix_ms=time.time_ns() / 1e6, ssh_exit_code=result.returncode)
    if result.returncode:
        row['finding'] = 'Guest probe transport failed; this attempt is unmeasured'
        error = result.stderr
    else:
        probe = json.loads(result.stdout)
        curl = probe.get('curl') or {}
        row.update(probe_exit_code=probe['exit_code'], metrics={key: curl.get(key) for key in
            ('size_download', 'size_upload', 'speed_download', 'speed_upload', 'time_connect',
                'time_appconnect', 'time_starttransfer', 'time_total', 'http_code')})
        error = probe.get('stderr', '')
    if error:
        name = f'measurement-{direction}-attempt-{number}-stderr.txt'
        (directory / name).write_text(error)
        row['private_stderr_file'] = name
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vm')
    parser.add_argument('directory', type=Path)
    parser.add_argument("--download-bytes", type=int, default=1000000)
    parser.add_argument("--upload-bytes", type=int, default=1000000)
    parser.add_argument('--attempts', type=int, default=3)
    parser.add_argument('--probe-timeout-s', type=int, default=45)
    args = parser.parse_args()
    if not all(10000 <= size <= 10000000 for size in (args.download_bytes, args.upload_bytes)):
        raise ValueError("Probe sizes must be between ten thousand and ten million bytes")
    if not 1 <= args.attempts <= 3 or not 1 <= args.probe_timeout_s <= 120:
        raise ValueError('Use one to three attempts with a bounded probe deadline')
    args.directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for direction, size in (('download', args.download_bytes), ('upload', args.upload_bytes)):
        endpoint = 'https://speed.cloudflare.com/' + ('__down?bytes=' + str(size) if direction == 'download' else '__up')
        command = ['curl', '--silent', '--show-error', '--fail', '--max-time', str(args.probe_timeout_s), '--output', '/dev/null',
            '--write-out', '%{json}', endpoint]
        if direction == 'upload':
            command += ['--data-binary', '@-']
        # The guest generates a non-sensitive upload body; it never reads personal files.
        program = ('import subprocess,json\n'
            f'r=subprocess.run({command!r}, input=' + (f'bytes({size})' if direction == 'upload' else 'None') + ',capture_output=True)\n'
            'print(json.dumps({"exit_code":r.returncode,"curl":json.loads(r.stdout) if r.stdout else None,"stderr":r.stderr.decode()}))')
        for number in range(1, args.attempts + 1):
            row = attempt(args.vm, program, direction, size, number, args.probe_timeout_s, args.directory)
            row['complete_requested_transfer'] = complete(row)
            rows.append(row)
            path = args.directory / 'throughput-measurements.json'
            path.write_text(json.dumps({'vm':args.vm,'completed_at':datetime.now(timezone.utc).isoformat(),
                'probes':rows,'limitation':'Every attempted HTTP probe is retained, including failures. Effective rates include connection and server response time; they are not pure wire bandwidth. Packet loss and phone Wi-Fi are unmeasured. Finish every probe before acoustic input.'},indent=2)+'\n')
            print(json.dumps(row), flush=True)
            if row['complete_requested_transfer']:
                break
            if not retryable(row) or number == args.attempts:
                raise RuntimeError('Network measurement failed; retain evidence and do not claim both directions were measured')
            time.sleep(.5)


if __name__ == '__main__':
    main()
