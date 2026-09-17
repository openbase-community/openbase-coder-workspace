#!/usr/bin/env python3
"""Require fresh listening and native release evidence before voice-test teardown."""
import argparse
import json
from pathlib import Path
import time
from readiness import ios_ready, android_ready
from timeline import events


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
    args = parser.parse_args()
    fresh = 0 <= time.time() - args.snapshot.stat().st_mtime <= 1.5
    listening = {'ios': ios_ready, 'android': android_ready}[args.platform](args.snapshot.read_text())
    released = native_release_ready(events(args.directory), args.platform)
    proof = {'observed_at_unix_ms': time.time_ns() / 1e6, 'fresh_listening': fresh and listening,
        'native_release_acknowledged': released, 'allow_teardown': fresh and listening and released,
        'limitation': 'A future announcement can race this observation; preserve teardown timestamps and room evidence.'}
    (args.directory / 'teardown-readiness.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof))
    if not proof['allow_teardown']:
        raise RuntimeError('Do not end the call: fresh listening and native completion evidence are required')


if __name__ == '__main__':
    main()
