import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import congestion_capture


class CongestionPreflightTests(unittest.TestCase):
    def test_failed_apply_prevents_measurement(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(congestion_capture,'step',side_effect=subprocess.CalledProcessError(255,['apply'])) as step:
            with self.assertRaises(subprocess.CalledProcessError):
                congestion_capture.network_preflight('fixture',Path(tmp),[])
            self.assertEqual(step.call_count,1)

    def test_restore_or_wrong_owner_prevents_measurement(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'network-state.json').write_text(json.dumps({'vm':'other'}))
            with patch.object(congestion_capture,'step') as step:
                with self.assertRaises(ValueError):congestion_capture.network_preflight('fixture',p,[])
                self.assertEqual(step.call_count,1)
