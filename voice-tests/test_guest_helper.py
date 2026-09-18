"""Exercise the actual macOS shell helper without contacting any device."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


HELPER = Path(__file__).resolve().parents[1] / 'install-tests/electron-macos/guest-automate.sh'


class GuestHelperAuthenticationTests(unittest.TestCase):
    def invoke(self, identity):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = {
                'tart': '#!/bin/sh\nprintf 192.0.2.1\n',
                'ssh': '#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n',
                'sshpass': '#!/bin/sh\nshift 2\nexec "$@"\n',
            }
            for name, content in scripts.items():
                path = root / name
                path.write_text(content)
                path.chmod(0o755)
            key = root / 'identity with spaces'
            key.touch()
            environment = {**os.environ, 'PATH': str(root) + ':' + os.environ['PATH'], 'VM_PASS': 'fixture-only'}
            environment.pop('VM_SSH_IDENTITY_FILE', None)
            if identity is not None:
                environment['VM_SSH_IDENTITY_FILE'] = str(key if identity else root / 'missing')
            return subprocess.run(['/bin/bash', str(HELPER), 'ssh', 'fixture', 'printf probe'],
                env=environment, capture_output=True, text=True)

    def test_explicit_identity_survives_macos_bash_nounset(self):
        result = self.invoke(True)
        self.assertEqual(result.returncode, 0, result.stderr)
        arguments = json.loads(result.stdout)
        self.assertIn('BatchMode=yes', arguments)
        self.assertIn('IdentityAgent=none', arguments)
        self.assertTrue(arguments[arguments.index('-i') + 1].endswith('identity with spaces'))
        self.assertEqual(arguments[-1], 'printf probe')

    def test_default_password_path_remains_available(self):
        result = self.invoke(None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('PubkeyAuthentication=no', json.loads(result.stdout))

    def test_missing_explicit_identity_never_falls_back(self):
        result = self.invoke(False)
        self.assertEqual(result.returncode, 2)
        self.assertIn('identity is missing', result.stderr)
