import unittest
from worker_events import watchdog_event, worker_event


class WorkerTimingTests(unittest.TestCase):
    def test_watchdog_cause_retains_original_millisecond_timestamp(self):
        record = watchdog_event("INFO 2026-09-17 12:30:00,370 service livekit_pool_watchdog bounce reason=idle_recycle services=('livekit-agent',)")
        self.assertEqual(record['timestamp'], '2026-09-17T12:30:00.370000+00:00')
        self.assertIn('reason=idle_recycle', record['message'])

    def test_unrelated_service_payload_is_not_exported(self):
        self.assertIsNone(watchdog_event('INFO 2026-09-17 12:30:00,370 service Authorization=private-value'))
        self.assertIsNone(worker_event({'timestamp':'date', 'message':'signaling credentials private-value'}))

    def test_worker_transition_discards_nested_credentials(self):
        record = worker_event({'timestamp':'2026-09-17T12:30:00.380213+00:00',
            'message':'draining worker', 'configuration':{'password':'private-value'}})
        self.assertEqual(record, {'timestamp':'2026-09-17T12:30:00.380213+00:00',
            'message':'dispatch_timing stage=voice_worker_drain_started'})
