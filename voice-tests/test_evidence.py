import json
from pathlib import Path
import tempfile
import unittest
from evidence import merge_jsonl


class CheckpointEvidenceTests(unittest.TestCase):
    def test_later_tail_keeps_old_beginning_and_distinct_equal_time_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'timing.jsonl'
            old={'timestamp':'2026-09-17T11:00:00Z','metadata':{'roomID':'old'}}
            new={'timestamp':'2026-09-17T11:00:00Z','metadata':{'roomID':'new'}}
            merge_jsonl(p,json.dumps(old)+'\n')
            merge_jsonl(p,'partial tail\n'+json.dumps(old)+'\n'+json.dumps(new)+'\n')
            rows=[json.loads(line) for line in p.read_text().splitlines()]
            self.assertEqual(len(rows),2)
            self.assertEqual({r['metadata']['roomID'] for r in rows},{'old','new'})
