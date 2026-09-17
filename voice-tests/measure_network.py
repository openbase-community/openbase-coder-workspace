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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vm')
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for direction, size in (('download', 1000000), ('upload', 1000000)):
        endpoint = 'https://speed.cloudflare.com/' + ('__down?bytes=' + str(size) if direction == 'download' else '__up')
        command = ['curl', '--silent', '--show-error', '--fail', '--max-time', '45', '--output', '/dev/null',
            '--write-out', '%{json}', endpoint]
        if direction == 'upload':
            command += ['--data-binary', '@-']
        # The guest generates a non-sensitive upload body; it never reads personal files.
        program = ('import subprocess,json\n'
            f'r=subprocess.run({command!r}, input=' + (f'bytes({size})' if direction == 'upload' else 'None') + ',capture_output=True)\n'
            'print(json.dumps({"exit_code":r.returncode,"curl":json.loads(r.stdout) if r.stdout else None,"stderr":r.stderr.decode()}))')
        started = time.time_ns() / 1e6
        result = subprocess.run([str(ROOT / 'install-tests/electron-macos/guest-automate.sh'), 'ssh', args.vm,
            '~/Developer/openbase-coder-workspace/.venv/bin/python -c ' + shlex.quote(program)],
            text=True, capture_output=True, timeout=60)
        row = {'direction': direction, 'requested_bytes': size, 'host_started_unix_ms': started,
            'host_finished_unix_ms': time.time_ns() / 1e6, 'ssh_exit_code': result.returncode}
        if result.returncode:
            row['finding'] = 'Guest probe transport failed; this direction is unmeasured'
        else:
            probe = json.loads(result.stdout)
            # Keep measured timings/rates, not service URLs or environment information.
            curl = probe.get('curl') or {}
            row.update(probe_exit_code=probe['exit_code'], metrics={key:curl.get(key) for key in
                ('size_download','size_upload','speed_download','speed_upload','time_connect','time_appconnect','time_starttransfer','time_total','http_code')})
        rows.append(row)
        path = args.directory / 'throughput-measurements.json'
        path.write_text(json.dumps({'vm':args.vm,'completed_at':datetime.now(timezone.utc).isoformat(),
            'probes':rows,'limitation':'Effective HTTP rates include connection and server response time; they are not a pure wire-bandwidth measurement. They do not measure packet loss or phone Wi-Fi. Finish all probes before acoustic input.'},indent=2)+'\n')
        print(json.dumps(row), flush=True)
        if result.returncode or probe['exit_code']:
            raise RuntimeError('Network measurement failed; retain evidence and do not claim both directions were measured')


if __name__ == '__main__':
    main()
