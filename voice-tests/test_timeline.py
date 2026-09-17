import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from timeline import device_clock_bounds, events, phone_clock_bounds, unix_ms
from clock_probe import calibration_from_samples
from clock_probe import ClockTransportError, sample_vm_clock


class TimingEvidenceTests(unittest.TestCase):
    def test_backend_tool_observation_retains_its_actual_clock_and_thread(self):
        with tempfile.TemporaryDirectory() as temp:
            row={'source':'server','unix_ms':1250,'event':'observed super_agents_start_turn',
                'metadata':{'thread':'demo','timing_basis':'Local adapter observation'}}
            Path(temp,'backend-tools.jsonl').write_text(json.dumps(row)+'\n')
            self.assertEqual(events(Path(temp)),[row])

    def test_untrusted_acoustic_match_is_not_rendered_as_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp)
            (directory/'capture-clock.json').write_text(json.dumps({'first_sample_unix_ms':1000}))
            (directory/'acoustic-alignment.json').write_text(json.dumps({
                'display_allowance_ms':10,'limitation':'Not calibrated',
                'stimuli':[{'index':0,'trusted':False,'signal_start_s':1}]}))
            self.assertEqual(events(directory),[])

    def test_registered_transcript_preserves_spaces_and_quoted_words(self):
        with tempfile.TemporaryDirectory() as temp:
            text = "Speak the exact words dual garden component."
            record = {'timestamp':'2026-09-17T06:31:03.392Z',
                'message':'dispatch_timing stage=stt_final_transcript text_excerpt='+repr(text)}
            Path(temp,'server.log').write_text(json.dumps(record)+'\n')
            rows = events(Path(temp))
            self.assertEqual(rows[0]['metadata']['text_excerpt'],text)

    def test_clock_transport_retry_preserves_failed_observation(self):
        failure = {'ssh_exit_code':255,'authentication_rejected':True}
        samples = [{'lower_ms':0,'upper_ms':1}]
        with patch('clock_probe._sample_vm_clock_once', side_effect=[ClockTransportError(failure), samples]) as probe:
            result = sample_vm_clock('helper','fixture')
        self.assertEqual(probe.call_count,2)
        self.assertEqual(result[0]['startup_retry_events'],[failure])

    def test_clock_program_error_is_not_retried(self):
        with patch('clock_probe._sample_vm_clock_once', side_effect=RuntimeError('bad clock program')) as probe:
            with self.assertRaises(RuntimeError):
                sample_vm_clock('helper','fixture')
        self.assertEqual(probe.call_count,1)

    def test_phone_clock_drift_uses_envelope_and_excludes_old_probes(self):
        samples = [dict(source='android', device_unix_ms=1005, host_before_unix_ms=1000,
            host_after_unix_ms=1002), dict(source='android', device_unix_ms=7997,
            host_before_unix_ms=8000, host_after_unix_ms=8002)]
        bound = device_clock_bounds(samples)['android']
        self.assertEqual(bound['offset_ms'], .5)
        self.assertEqual(bound['uncertainty_ms'], 5.5)
        recent = device_clock_bounds(samples, window=(7000, 9000))['android']
        self.assertEqual(recent['offset_ms'], -3.5)
        self.assertEqual(recent['uncertainty_ms'], 1.5)

    def test_clock_envelope_keeps_drift_between_probe_batches(self):
        samples = [
            {"lower_ms": 4, "upper_ms": 6, "host_before_ms": 1000, "host_after_ms": 1002},
            {"lower_ms": 4.5, "upper_ms": 5.5, "host_before_ms": 1003, "host_after_ms": 1004},
            {"lower_ms": -4, "upper_ms": -2, "host_before_ms": 8000, "host_after_ms": 8002},
        ]
        bound = calibration_from_samples(samples)["server"]
        self.assertEqual(bound["offset_ms"], .75)
        self.assertEqual(bound["uncertainty_ms"], 4.75)

    def test_clock_jump_inside_probe_batch_is_rejected(self):
        samples = [
            {"lower_ms": 4, "upper_ms": 6, "host_before_ms": 1000, "host_after_ms": 1002},
            {"lower_ms": 9, "upper_ms": 11, "host_before_ms": 1003, "host_after_ms": 1004},
        ]
        with self.assertRaises(ValueError):
            calibration_from_samples(samples)

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
