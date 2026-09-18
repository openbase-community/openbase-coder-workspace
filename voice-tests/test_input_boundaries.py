import unittest
from input_boundaries import assess_input


class InputBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.alignment={'index':0,'trusted':True,'signal_start_s':2,'signal_end_s':8}

    def mute(self, when, enabled=False, error=50):
        return {'source':'ios','event':'applied mute state','capture_relative_s':when,
                'clock_uncertainty_ms':error,'metadata':{'microphone_enabled':enabled}}

    def test_detects_mute_during_the_input_including_a_pause(self):
        result=assess_input(self.alignment,[self.mute(1,True),self.mute(5)])
        self.assertEqual(result['status'],'mute_before_input_end_candidate')
        self.assertLess(result['gap_upper_ms'],0)

    def test_retains_uncertainty_and_missing_clock(self):
        result=assess_input(self.alignment,[self.mute(8.02)])
        self.assertEqual(result['status'],'boundary_uncertain')
        row=self.mute(9);row.pop('clock_uncertainty_ms')
        self.assertEqual(assess_input(self.alignment,[row])['status'],'native_clock_uncalibrated')

    def test_does_not_borrow_next_inputs_mute_or_trust_bad_alignment(self):
        next_input={'source':'host','event':'playback_process_start','capture_relative_s':10}
        self.assertEqual(assess_input(self.alignment,[next_input,self.mute(12)])['status'],'native_mute_not_observed')
        self.assertEqual(assess_input({**self.alignment,'trusted':False},[self.mute(9)])['status'],'untrusted_acoustic_alignment')

    def test_prior_muted_mic_is_not_mistaken_for_safe_input(self):
        self.assertEqual(assess_input(self.alignment,[self.mute(1),self.mute(9)])['status'],
                         'input_started_with_last_acknowledged_mic_disabled')

    def test_later_unrelated_announcement_cannot_fill_a_journal_gap(self):
        result=assess_input(self.alignment,[self.mute(1,True),self.mute(90)])
        self.assertEqual(result['status'],'native_mute_not_observed')
        self.assertEqual(result['mute_observation_deadline_s'],38)
