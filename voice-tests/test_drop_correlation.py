import unittest

from drop_correlation import ios_speech_windows, suspected_drops


def ios_callback(unix_ms, above):
    return {"source": "ios", "diagnostic_message": "local audio capture callback",
            "unix_ms": unix_ms, "metadata": {"above_threshold": "true" if above else "false"}}


def gap(unix_ms, gap_ms, stream_id="stt-1"):
    return {"source": "server", "event": "stt_audio_gap", "unix_ms": unix_ms,
            "metadata": {"gap_ms": str(gap_ms), "stream_id": stream_id}}


def transcript(unix_ms, excerpt):
    return {"source": "server", "event": "stt_final_transcript", "unix_ms": unix_ms,
            "metadata": {"text_excerpt": excerpt, "text_hash": "h"}}


class SpeechWindowTests(unittest.TestCase):
    def test_open_and_close_window(self):
        rows = [ios_callback(1000, True), ios_callback(1500, True), ios_callback(2000, False)]
        self.assertEqual(ios_speech_windows(rows), [(1000, 1500)])

    def test_unclosed_window_ends_at_last_active(self):
        rows = [ios_callback(1000, True), ios_callback(1800, True)]
        self.assertEqual(ios_speech_windows(rows), [(1000, 1800)])


class DropCorrelationTests(unittest.TestCase):
    def test_gap_over_speech_is_flagged(self):
        rows = [
            ios_callback(10_000, True), ios_callback(10_500, True), ios_callback(11_500, False),
            transcript(9_000, "before the roam"),
            gap(11_000, 900),  # gap spans 10_100..11_000, overlapping the speech window
            transcript(12_000, "after the roam"),
        ]
        drops = suspected_drops(rows, tolerance_ms=200)
        self.assertEqual(len(drops), 1)
        drop = drops[0]
        self.assertGreater(drop["speech_overlap_ms"], 0)
        self.assertEqual(drop["prior_transcript"]["text_excerpt"], "before the roam")
        self.assertEqual(drop["next_transcript"]["text_excerpt"], "after the roam")

    def test_gap_without_speech_is_ignored(self):
        # Gap while the mic was silent -> not a dropped utterance (e.g. idle).
        rows = [ios_callback(10_000, False), gap(20_000, 900)]
        self.assertEqual(suspected_drops(rows, tolerance_ms=200), [])

    def test_speech_without_gap_is_ignored(self):
        rows = [ios_callback(10_000, True), ios_callback(10_500, False)]
        self.assertEqual(suspected_drops(rows), [])


if __name__ == "__main__":
    unittest.main()
