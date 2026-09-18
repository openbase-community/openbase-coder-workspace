#!/usr/bin/env python3
"""Collect observed filesystem and dispatch calls from bounded guest SDK logs."""
import argparse
from datetime import datetime
import inspect
import json
from pathlib import Path
import shlex

from evidence import merge_jsonl
from guest import read_guest


def tool_events(log, thread):
    rows = []
    for line in log.splitlines():
        if not line.startswith('[') or '] ' not in line:
            continue
        stamp, body = line[1:].split('] ', 1)
        try:
            record = json.loads(body)
            unix_ms = datetime.fromisoformat(stamp.replace('Z', '+00:00')).timestamp() * 1000
        except (ValueError, json.JSONDecodeError):
            # Bounded tails may begin inside a record; plain diagnostic lines
            # are not SDK messages. Neither is evidence of a tool invocation.
            continue
        if not isinstance(record, dict) or not isinstance(record.get('content'), list):
            continue
        for block in record['content']:
            if not isinstance(block, dict) or not isinstance(block.get('name'), str) or 'input' not in block:
                continue
            rows.append({'source': 'server', 'unix_ms': unix_ms,
                'event': 'observed ' + block['name'], 'metadata': {
                    'source_thread': thread, 'tool_use_id': block.get('id'),
                    'parent_tool_use_id': record.get('parent_tool_use_id'),
                    'arguments': block['input'],
                    'timing_basis': 'SDK tool invocation, not result or remote acceptance'}})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vm')
    parser.add_argument('directory', type=Path, help='Private ignored report directory; arguments can contain private data')
    args = parser.parse_args()
    program = 'import json,sqlite3\nfrom pathlib import Path\nfrom datetime import datetime\n' + inspect.getsource(tool_events)
    program += '''
db=sqlite3.connect('file:'+str(Path.home()/'.local/share/super-agents-claude-code/state.sqlite3')+'?mode=ro',uri=True)
events=[]
for name,log_path in db.execute('select name,log_path from sessions'):
 if not log_path: continue
 path=Path(log_path)
 if not path.is_file(): continue
 with path.open('rb') as stream:
  stream.seek(max(0,path.stat().st_size-4000000))
  events.extend(tool_events(stream.read().decode(errors='replace'),name))
print(json.dumps(events))
'''
    root = Path(__file__).resolve().parents[1]
    rows = json.loads(read_guest(root/'install-tests/electron-macos/guest-automate.sh', args.vm,
        'python3 -c ' + shlex.quote(program)))
    args.directory.mkdir(parents=True, exist_ok=True)
    merge_jsonl(args.directory/'backend-tools.jsonl', ''.join(json.dumps(row)+'\n' for row in rows))
    print(json.dumps({'observed_calls_in_checkpoint': len(rows),
        'tools': sorted({row['event'].removeprefix('observed ') for row in rows}),
        'limitation': 'Last 4 MB per SDK log; collect and merge checkpoints. Zero observed calls is not proof that no earlier call occurred.'}))


if __name__ == '__main__':
    main()
