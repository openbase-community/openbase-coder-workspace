import unittest
from finish import native_release_ready


class TeardownReadinessTests(unittest.TestCase):
    def test_delayed_duplicate_receipt_is_not_a_new_completion_requirement(self):
        receipt = dict(source='ios', event='safe_to_unmute', unix_ms=1,
            diagnostic_message='received voice lifecycle event',
            metadata={'event':'safe_to_unmute','packet_id':'packet-1'})
        rows = [receipt, dict(source='ios', event='applied mute state', unix_ms=2,
            metadata={'microphone_enabled':True}), {**receipt, 'unix_ms':3}]
        self.assertTrue(native_release_ready(rows,'ios'))

    def test_previous_call_completion_cannot_release_a_new_call(self):
        rows = [dict(source='android', event='voice lifecycle received', unix_ms=1,
            metadata={'event':'safe_to_unmute','disposition':'accepted'}),
            dict(source='android', event='call state changed', unix_ms=2, metadata={'connected':True}),
            dict(source='android', event='applied mute state', unix_ms=3, metadata={'microphone_enabled':True})]
        self.assertFalse(native_release_ready(rows, 'android'))

    def test_same_epoch_delayed_audio_finished_cannot_regress_release(self):
        receipt = dict(source='ios', event='safe_to_unmute', unix_ms=1,
            diagnostic_message='received voice lifecycle event', metadata={'event':'safe_to_unmute',
                'delivery_id':'delivery-1','created_at_unix_ms':'1000','packet_id':'safe'})
        rows = [receipt, dict(source='ios', event='applied mute state', unix_ms=2,
            metadata={'microphone_enabled':True}), dict(source='ios', event='agent_audio_finished',unix_ms=3,
            diagnostic_message='received voice lifecycle event', metadata={'event':'agent_audio_finished',
                'delivery_id':'delivery-1','created_at_unix_ms':'1000','packet_id':'finished'})]
        self.assertTrue(native_release_ready(rows,'ios'))
        rows[-1]['metadata']['delivery_id']='delivery-2'
        self.assertFalse(native_release_ready(rows,'ios'))

    def test_pending_steer_blocks_teardown_after_an_older_cancelled_release(self):
        rows = [dict(source='ios', event='safe_to_unmute', unix_ms=1,
            diagnostic_message='received voice lifecycle event', metadata={'event': 'safe_to_unmute'}),
            dict(source='ios', event='applied mute state', unix_ms=2, metadata={'microphone_enabled': True})]
        self.assertTrue(native_release_ready(rows, 'ios'))
        rows.append(dict(source='ios', event='safe_to_mute_user', unix_ms=3,
            diagnostic_message='received voice lifecycle event', metadata={'event': 'safe_to_mute_user'}))
        self.assertFalse(native_release_ready(rows, 'ios'))

    def test_stale_release_and_unacknowledged_unmute_cannot_finish(self):
        rows = [dict(source='android', event='applied mute state', unix_ms=1, metadata={'microphone_enabled': True}),
            dict(source='android', event='voice lifecycle received', unix_ms=2,
                metadata={'event': 'safe_to_unmute', 'disposition': 'stale'})]
        self.assertFalse(native_release_ready(rows, 'android'))
        rows[-1]['metadata']['disposition'] = 'accepted'
        self.assertFalse(native_release_ready(rows, 'android'))
