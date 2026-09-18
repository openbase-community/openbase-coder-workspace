import struct
import unittest
from audio_gain import pcm16_gain


class AudioGainTests(unittest.TestCase):
    def test_gain_preserves_frame_count_sign_and_original_bytes(self):
        original = struct.pack('<hhh', -100, 0, 100)
        adjusted, clipped = pcm16_gain(original, 20)
        self.assertEqual(struct.unpack('<hhh', adjusted), (-1000, 0, 1000))
        self.assertEqual(len(adjusted), len(original))
        self.assertEqual(original, struct.pack('<hhh', -100, 0, 100))
        self.assertEqual(clipped, 0)

    def test_clipping_is_bounded_and_counted(self):
        adjusted, clipped = pcm16_gain(struct.pack('<hh', -20000, 20000), 20)
        self.assertEqual(struct.unpack('<hh', adjusted), (-32768, 32767))
        self.assertEqual(clipped, 2)

    def test_zero_gain_is_identical_and_partial_samples_rejected(self):
        original = struct.pack('<hh', -32768, 32767)
        self.assertEqual(pcm16_gain(original, 0), (original, 0))
        with self.assertRaises(ValueError):
            pcm16_gain(b'partial', 20)
