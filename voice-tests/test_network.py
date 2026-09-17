import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import network


class NetworkOwnershipTests(unittest.TestCase):
    def test_obsolete_safety_timer_cannot_restore_a_new_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            lease = pathlib.Path(directory) / "owner"
            marker = pathlib.Path(directory) / "restored"
            lease.write_text("new-profile")
            with patch.object(network, "LEASE", str(lease)):
                command = network.owned_restore("old-profile", f"touch {marker}")
            subprocess.run(["sh", "-c", command], check=True)
            self.assertFalse(marker.exists())
            self.assertEqual(lease.read_text(), "new-profile")
