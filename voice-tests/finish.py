#!/usr/bin/env python3
"""Require fresh listening and native release evidence before voice-test teardown."""
import argparse
import json
from pathlib import Path
import time
import shlex
from readiness import ios_ready, android_ready
from timeline import events
from guest import read_guest


def pending_backend_work(vm):
    program = """import glob,json,sqlite3
from pathlib import Path
stores=glob.glob(str(Path.home())+'/.local/share/super-agents-*/state.sqlite3')
if len(stores)!=1: raise RuntimeError('Expected exactly one dedicated fixture backend store')
db=sqlite3.connect('file:'+stores[0]+'?mode=ro',uri=True)
rows=db.execute("select s.name,t.id,t.status from turns t join sessions s on s.id=t.session_id where t.status in ('running','waiting','queued','starting')").fetchall()
print(json.dumps([{'thread':r[0],'turn_id':r[1],'status':r[2]} for r in rows]))
"""
    root = Path(__file__).resolve().parents[1]
    return json.loads(read_guest(root/'install-tests/electron-macos/guest-automate.sh',vm,
        '~/Developer/openbase-coder-workspace/.venv/bin/python -c '+shlex.quote(program)))


def native_release_ready(rows, platform):
    native = [r for r in rows if r['source'] == platform]
    lifecycle = [r for r in native if r.get('diagnostic_message', r['event']) in
        ('received voice lifecycle event', 'voice lifecycle received')
        and r.get('metadata', {}).get('disposition', 'accepted') == 'accepted']
    mics = [r for r in native if r['event'] == 'applied mute state']
    if not lifecycle or not mics:
        return False
    latest = lifecycle[-1]
    connections = [r for r in native if r['event'] in ('call state changed', 'LiveKit room connection state changed')]
    if connections:
        connection = connections[-1]
        metadata = connection.get('metadata', {})
        if (metadata.get('connected') is False or metadata.get('to') != '.connected'
            and connection['event'] == 'LiveKit room connection state changed'
            or connection['unix_ms'] > latest['unix_ms']):
            return False
    return (latest['metadata'].get('event', latest['event']) == 'safe_to_unmute'
        and str(mics[-1].get('metadata', {}).get('microphone_enabled')).lower() == 'true'
        and mics[-1]['unix_ms'] >= latest['unix_ms'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('--platform', choices=('ios', 'android'), required=True)
    parser.add_argument('--vm', required=True, help='Require the dedicated fixture backend and background agents to be idle')
    args = parser.parse_args()
    pending = pending_backend_work(args.vm)
    fresh = 0 <= time.time() - args.snapshot.stat().st_mtime <= 1.5
    listening = {'ios': ios_ready, 'android': android_ready}[args.platform](args.snapshot.read_text())
    released = native_release_ready(events(args.directory), args.platform)
    proof = {'observed_at_unix_ms': time.time_ns() / 1e6, 'fresh_listening': fresh and listening,
        'native_release_acknowledged': released, 'pending_backend_work':pending,
        'allow_teardown': fresh and listening and released and not pending,
        'limitation': 'A future announcement can race this observation; preserve teardown timestamps and room evidence.'}
    (args.directory / 'teardown-readiness.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof))
    if not proof['allow_teardown']:
        raise RuntimeError('Do not end the call: fresh listening, native completion, and an idle fixture backend are required')


if __name__ == '__main__':
    main()
