import json
import unittest
from room_events import room_event


class RoomEventTests(unittest.TestCase):
    def test_room_close_retains_cause_and_id_but_no_signal_credentials(self):
        payload = {"roomID": "RM_example", "reason": "IDLE_TIMEOUT", "signal": {"password": "private"}, "token": "private", "error": "private"}
        line = "2026-09-17T11:16:12.704Z\tINFO\tlivekit.room\trtc/room.go:822\tclosing room\t" + json.dumps(payload)
        row = room_event(line)
        self.assertEqual(row['metadata'], {'roomID': 'RM_example', 'reason': 'IDLE_TIMEOUT'})
        self.assertNotIn('private', json.dumps(row))

    def test_unknown_debug_and_partial_lines_are_not_exported(self):
        self.assertIsNone(room_event('partial bounded tail'))
        self.assertIsNone(room_event('2026-09-17T11:16:12.704Z\tDEBUG\tlivekit\trtc.go:1\tsignal message\t{"token":"private"}'))
