"""Extract room lifecycle facts without exporting LiveKit signaling secrets."""
import json
import re


MESSAGES = frozenset(("participant closing", "closing room", "room closed", "closing idle room", "resuming RTC session", "starting RTC session"))
FIELDS = frozenset(("room", "roomID", "participantID", "reason"))


def room_event(line):
    parts = line.split("\t")
    if len(parts) != 6 or parts[4] not in MESSAGES:
        return None
    if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+Z", parts[0]):
        return None
    try:
        metadata = json.loads(parts[5])
    except json.JSONDecodeError:
        return None
    if not isinstance(metadata, dict):
        return None
    kept = {}
    for key in FIELDS:
        value = metadata.get(key)
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_. -]{1,160}", value):
            kept[key] = value
    return {"timestamp": parts[0], "event": "observed livekit_room " + parts[4], "metadata": kept}


def label_case_rooms(rows):
    """Keep unrelated room history searchable without depicting it as this call."""
    names = set()
    for row in rows:
        if row.get('source') == 'host' and row.get('event') == 'announcement_command_end':
            names.update(re.findall(r'Announcer message sent to (room-[A-Za-z0-9-]+)\.', row.get('receipt', '')))
        if row.get('source') in ('ios', 'android'):
            metadata = row.get('metadata', {})
            name = metadata.get('current_room_name') or metadata.get('room_name')
            if name:
                names.add(name)
    for row in rows:
        if row.get('event', '').startswith('observed livekit_room'):
            name = row.get('metadata', {}).get('room')
            row['case_room_scope'] = 'current_call' if name in names else (
                'unrelated_room' if name and names else 'unattributed_room')
    return names
