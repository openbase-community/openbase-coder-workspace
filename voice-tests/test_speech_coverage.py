import unittest
from speech_coverage import coverage


class SpeechCoverageTests(unittest.TestCase):
    def test_terminal_marker_does_not_hide_missing_middle(self):
        words=[{'text':w,'start':i*100,'end':i*100+90} for i,w in enumerate('first garden slate complete second boat velvet complete'.split())]
        probes=[{'thread':'a','text':'first garden turtle slate complete','terminal_phrase':'slate complete'},
            {'thread':'b','text':'second boat velvet complete','terminal_phrase':'velvet complete'}]
        rs=coverage(probes,words,0)
        self.assertEqual(rs[0]['coverage_percent'],80)
        self.assertEqual(rs[0]['alignment'][2]['asr_start_ms'],None)
        self.assertEqual(rs[1]['coverage_percent'],100)

    def test_missing_terminal_marker_is_insufficient_evidence(self):
        r=coverage([{'thread':'a','text':'first garden complete','terminal_phrase':'garden complete'}],[],0)[0]
        self.assertEqual(r['status'],'terminal_marker_not_observed')
        self.assertIsNone(r['coverage_percent'])
