"""Whitelist voice worker restarts without exporting service log payloads."""
from datetime import datetime, timezone
import re


def worker_event(record):
    stages = {'draining worker': 'voice_worker_drain_started',
        'exiting forcefully': 'voice_worker_force_exit',
        'starting worker': 'voice_worker_started'}
    stage = stages.get(record.get('message'))
    if stage is None or not record.get('timestamp'):
        return None
    return {'timestamp': record['timestamp'], 'message': 'dispatch_timing stage=' + stage}


def watchdog_event(line):
    match = re.search(r'INFO (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3}) \S+ '
        r'livekit_pool_watchdog bounce reason=(idle_recycle|stale_pool_signature(?:_escalated)?)\b', line)
    if match is None:
        return None
    timestamp = datetime.strptime(match[1], '%Y-%m-%d %H:%M:%S,%f').replace(tzinfo=timezone.utc)
    return {'timestamp': timestamp.isoformat(),
        'message': 'dispatch_timing stage=voice_worker_recycle reason=' + match[2]}
