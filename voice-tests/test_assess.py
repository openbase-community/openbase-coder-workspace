import unittest
from assess import assess


class AcousticAssessmentTests(unittest.TestCase):
    def rows(self, gap, clock=30):
        return [dict(source='host', event='playback_process_end', capture_relative_s=10),
            dict(source='ios', event='applied mute state', capture_relative_s=11,
                metadata={'microphone_enabled': False}),
            dict(source='ios', event='applied mute state', capture_relative_s=20 + gap,
                metadata={'microphone_enabled': True}, clock_uncertainty_ms=clock)]

    def words(self, end=20000):
        return [dict(text='Velvet', start=end-900, end=end-600),
            dict(text='orchard', start=end-600, end=end-300), dict(text='complete.', start=end-300, end=end)]

    def test_prompt_marker_cannot_satisfy_response_completion(self):
        result = assess(self.rows(1), self.words(8000), 'velvet orchard complete')
        self.assertEqual(result['status'], 'terminal_marker_not_observed')

    def test_uncertainty_prevents_false_pass_or_false_failure(self):
        self.assertEqual(assess(self.rows(.2), self.words(), 'velvet orchard complete')['status'],
            'complete_marker_unmute_boundary_uncertain')
        self.assertEqual(assess(self.rows(.9), self.words(), 'velvet orchard complete')['status'],
            'complete_marker_and_protected_unmute_observed')
        self.assertEqual(assess(self.rows(-.7), self.words(), 'velvet orchard complete')['status'],
            'premature_unmute_candidate_requires_waveform_review')

    def test_uncalibrated_clock_does_not_satisfy_timing(self):
        rows = self.rows(1)
        del rows[-1]['clock_uncertainty_ms']
        self.assertEqual(assess(rows, self.words(), 'velvet orchard complete')['status'],
            'complete_marker_unmute_clock_uncalibrated')
