import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import measure_network


def response(code=0, download=10000, upload=10000):
    payload = {'exit_code': code, 'curl': {'http_code': 200, 'size_download': download,
        'size_upload': upload}, 'stderr': ''}
    return subprocess.CompletedProcess([], 0, json.dumps(payload), '')


class NetworkMeasurementTests(unittest.TestCase):
    def run_measurement(self, directory, results):
        with patch('sys.argv', ['measure', 'fixture', str(directory), '--download-bytes', '10000', '--upload-bytes', '10000']), \
                patch('measure_network.subprocess.run', side_effect=results), \
                patch('measure_network.time.sleep'), contextlib.redirect_stdout(io.StringIO()):
            measure_network.main()

    def test_tls_failure_is_retained_before_complete_directional_probes(self):
        with tempfile.TemporaryDirectory() as temporary:
            p = Path(temporary)
            self.run_measurement(p, [response(35, 0, 0), response(), response()])
            rows = json.loads((p / 'throughput-measurements.json').read_text())['probes']
            self.assertEqual([r['complete_requested_transfer'] for r in rows], [False, True, True])
            self.assertEqual([r['direction'] for r in rows], ['download', 'download', 'upload'])

    def test_successful_http_with_short_payload_is_not_measurement_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            p = Path(temporary)
            with self.assertRaises(RuntimeError): self.run_measurement(p, [response(download=5)])
            rows = json.loads((p / 'throughput-measurements.json').read_text())['probes']
            self.assertEqual(len(rows), 1)
            self.assertFalse(rows[0]['complete_requested_transfer'])

    def test_deadlines_are_recorded_and_retries_are_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            p = Path(temporary)
            errors = [subprocess.TimeoutExpired('probe', 60)] * 3
            with self.assertRaises(RuntimeError): self.run_measurement(p, errors)
            rows = json.loads((p / 'throughput-measurements.json').read_text())['probes']
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(r['ssh_timed_out'] for r in rows))
