import tempfile
from pathlib import Path
import unittest
import wave
from segment_fixture import synthesize_fixture


class SegmentFixtureTests(unittest.TestCase):
    def test_pause_is_sample_exact_and_speech_is_retained(self):
        def synthesize(text, path):
            with wave.open(str(path), "wb") as wav:
                wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                wav.writeframes(b"\x01\x01" * 2400)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.wav"
            parts = synthesize_fixture({"text": "First. Correction.", "segments": [
                {"text": "First.", "gap_after_s": 1.8}, {"text": "Correction."}]}, path, synthesize)
            with wave.open(str(path)) as wav:
                frames = wav.readframes(wav.getnframes())
            self.assertEqual(len(frames) // 2, 48000)
            self.assertEqual(frames[4800:91200], bytes(86400))
            self.assertEqual(frames[91200:], b"\x01\x01" * 2400)
            self.assertEqual(parts[1]["start_s"], 1.9)
            self.assertEqual(parts[0]["gap_after_s"], 1.8)

    def test_expected_text_cannot_disagree_with_played_fragments(self):
        with self.assertRaises(ValueError):
            synthesize_fixture({"text": "Expected", "segments": [{"text": "Different"}]}, Path("unused"), None)
