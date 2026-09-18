import subprocess
import unittest
from unittest.mock import patch
from guest import read_guest


class GuestObservationTests(unittest.TestCase):
    def test_transport_retry_preserves_private_stdin_without_printing_it(self):
        results = [subprocess.CompletedProcess([],255,'','transport failure'),
            subprocess.CompletedProcess([],0,'observed state','')]
        with patch('guest.subprocess.run',side_effect=results) as run, patch('guest.time.sleep'):
            self.assertEqual(read_guest('helper','fixture','read-only command',input='private stdin\n'),'observed state')
        self.assertEqual(run.call_count,2)
        self.assertTrue(all(c.kwargs['input']=='private stdin\n' for c in run.call_args_list))

    def test_command_error_is_not_retried(self):
        with patch('guest.subprocess.run',return_value=subprocess.CompletedProcess([],1,'','command error')) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                read_guest('helper','fixture','read-only command')
        self.assertEqual(run.call_count,1)
