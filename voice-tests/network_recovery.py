#!/usr/bin/env python3
"""Record an owned-network restore relative to recorder readiness."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import time


def ready_event(path):
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            # The recorder may still be appending this line.
            continue
        if row.get('event') == 'recorder_ready':
            return row
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vm')
    parser.add_argument('network_directory', type=Path)
    parser.add_argument('capture_directory', type=Path)
    parser.add_argument('--after-recorder-s', type=float, required=True)
    args = parser.parse_args()
    if not 0 <= args.after_recorder_s <= 1800:
        raise ValueError('Recovery offset must be zero to thirty minutes')
    state = json.loads((args.network_directory/'network-state.json').read_text())
    if state['vm'] != args.vm or state.get('restored_at'):
        raise ValueError('Require the active owned profile for this VM')
    events = args.capture_directory/'host-events.jsonl'
    deadline = time.monotonic() + 90
    while (ready := ready_event(events)) is None:
        if time.monotonic() > deadline:
            raise RuntimeError('Recorder did not start; guest rollback remains armed')
        time.sleep(.25)
    if time.time()*1000-ready['unix_ms'] > 90000:
        raise ValueError('Refuse a stale recording; arm beside a new capture')
    target = ready['unix_ms']/1000 + args.after_recorder_s
    fallback = datetime.fromisoformat(state['applied_at']).timestamp() + state['profile']['safety_seconds']
    if target >= fallback:
        raise ValueError('Schedule recovery before the independent guest rollback')
    while (remaining := target-time.time()) > 0:
        time.sleep(min(20, remaining))
    before = time.time_ns()/1e6
    result = subprocess.run(['python3', str(Path(__file__).with_name('network.py')),
        'restore', args.vm, str(args.network_directory)], capture_output=True, text=True, timeout=180)
    proof = {'source':'host', 'event':'scheduled_network_restore', 'unix_ms':before,
        'completed_unix_ms':time.time_ns()/1e6,
        'configured_after_recorder_s':args.after_recorder_s, 'exit_code':result.returncode}
    with events.open('a') as output:
        output.write(json.dumps(proof)+'\n')
    (args.capture_directory/'network-restore-timer.json').write_text(json.dumps(proof, indent=2)+'\n')
    print(result.stdout[-1000:])
    (args.capture_directory/'network-recovery-stderr.txt').write_text(result.stderr[-2000:])
    if result.returncode:
        raise RuntimeError('Restore failed; inspect the independent guest rollback')


if __name__ == '__main__':
    main()
