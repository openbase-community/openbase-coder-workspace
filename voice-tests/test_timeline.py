import json
from pathlib import Path
import tempfile
import unittest

from timeline import device_clock_bounds, events, phone_clock_bounds, unix_ms


class TimingEvidenceTests(unittest.TestCase):
    def test_direct_clock_brackets_do_not_assume_symmetric_delay(self):
        samples = [{"source": "android", "device_unix_ms": 1120,
            "host_before_unix_ms": 1000, "host_after_unix_ms": 1050}]
        bound = device_clock_bounds(samples)["android"]
        self.assertEqual(bound["offset_ms"], 95.5)
        self.assertEqual(bound["uncertainty_ms"], 25.5)
        samples.append({"source": "android", "device_unix_ms": 5000,
            "host_before_unix_ms": 1000, "host_after_unix_ms": 1050})
        with self.assertRaises(ValueError):
            device_clock_bounds(samples)

    def test_native_precision_and_timezone_are_preserved(self):
        self.assertAlmostEqual(unix_ms("2026-09-17T04:39:12.786Z") % 1000, 786, places=2)
        with self.assertRaises(ValueError):
            unix_ms("2026-09-17T04:39:12.786")

    def test_asymmetric_round_trip_bounds_device_clock(self):
        rows = [
            {"source": "ios", "event": "received app control command", "unix_ms": 1120,
             "timestamp_resolution_ms": 1, "metadata": {"command_id": "one"}},
            {"source": "server", "event": "ios_control_round_trip", "unix_ms": 1050,
             "metadata": {"command_id": "one", "delivered": "True", "server_sent_unix_ms": "1000", "server_ack_unix_ms": "1050"}},
        ]
        bounds = phone_clock_bounds(rows)
        self.assertEqual(bounds["lower_ms"], 70)
        self.assertEqual(bounds["upper_ms"], 121)
        # The known 100 ms offset lies inside the interval despite asymmetric delay.
        self.assertLessEqual(bounds["lower_ms"], 100)
        self.assertGreaterEqual(bounds["upper_ms"], 100)
        rows[1]["metadata"]["delivered"] = "False"
        self.assertIsNone(phone_clock_bounds(rows))

    def test_duplicate_uploads_and_partial_log_tail_do_not_duplicate_events(self):
        with tempfile.TemporaryDirectory() as temp:
            entry = {"timestamp": "2026-09-17T04:39:12Z", "message": "applied mute state", "metadata": {"muted": "true"}}
            line = json.dumps({"entry": entry}) + "\n"
            Path(temp, "ios.jsonl").write_text('truncated record\n' + line + line)
            rows = events(Path(temp))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["timestamp_resolution_ms"], 1000)


if __name__ == "__main__":
    unittest.main()
