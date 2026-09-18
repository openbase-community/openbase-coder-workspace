import json
from pathlib import Path
import tempfile
import unittest
from secondary_evidence import secondary_readings


class SecondaryEvidenceTests(unittest.TestCase):
    def test_empty_and_gain_adjusted_attempts_are_not_merged_or_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            empty = {'provider':'Deepgram','words':[],'clip_start_s':130}
            gain = {'provider':'Deepgram','analysis_gain_db':20,
                    'words':[{'text':'complete','start':144000,'end':144400}]}
            (path/'secondary-transcript.json').write_text(json.dumps(empty))
            (path/'secondary-gain-transcript.json').write_text(json.dumps(gain))
            attempts, words = secondary_readings(path)
            self.assertEqual(len(attempts),2)
            self.assertEqual(words[0]['start'],144000)
            self.assertEqual(words[0]['analysis_label'],'DG +20 dB')
            self.assertEqual(json.loads((path/'secondary-transcript.json').read_text()),empty)
