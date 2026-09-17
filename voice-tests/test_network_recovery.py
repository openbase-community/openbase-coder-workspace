import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import network_recovery


class ScheduledRecoveryTests(unittest.TestCase):
    def test_incomplete_append_does_not_hide_recorder_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'events.jsonl'
            ready = {'event':'recorder_ready', 'unix_ms':1234}
            path.write_text(json.dumps(ready)+'\n{"event":')
            self.assertEqual(network_recovery.ready_event(path), ready)

    def test_old_capture_cannot_restore_an_active_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'network-state.json').write_text(json.dumps({'vm':'test-vm'}))
            (root/'host-events.jsonl').write_text(json.dumps({
                'event':'recorder_ready', 'unix_ms':(time.time()-100)*1000})+'\n')
            arguments = ['network_recovery.py','test-vm',str(root),str(root),'--after-recorder-s','230']
            with patch('sys.argv',arguments), patch.object(network_recovery.subprocess,'run') as restore:
                with self.assertRaisesRegex(ValueError,'stale recording'):
                    network_recovery.main()
                restore.assert_not_called()
