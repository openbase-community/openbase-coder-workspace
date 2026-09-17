import unittest
try:
    import numpy as np
    from acoustic_alignment import match
except ModuleNotFoundError as error:
    if error.name not in ('numpy','scipy','scipy.signal'):
        raise
    raise unittest.SkipTest('Run with uv --with scipy for acoustic alignment tests')


class AcousticAlignmentTests(unittest.TestCase):
    def test_recovers_delayed_stimulus_despite_gain_polarity_and_room_noise(self):
        rng = np.random.default_rng(42)
        reference = rng.normal(size=12000)
        room = rng.normal(scale=.02,size=16000)
        room[713:713+len(reference)] -= reference*.3
        found = match(reference,room)
        self.assertEqual(found['offset_samples'],713)
        self.assertGreater(found['normalized_correlation'],.99)

    def test_unrelated_room_audio_has_no_trusted_match(self):
        rng = np.random.default_rng(17)
        found = match(rng.normal(size=12000),rng.normal(size=16000))
        self.assertLess(found['normalized_correlation'],.2)

    def test_missing_reference_audio_cannot_establish_boundary(self):
        self.assertIsNone(match(np.zeros(100),np.ones(200)))
        self.assertIsNone(match(np.ones(200),np.ones(100)))
