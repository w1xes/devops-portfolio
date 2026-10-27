"""Acceptance run with DNS, closed TCP port, expired TLS and wrong HTTP status."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'demo_api.py'


class AcceptanceTests(unittest.TestCase):
    def test_four_real_failure_types(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(['python3', str(SCRIPT), '--output-dir', directory],
                                    env={**os.environ, 'TOOLKIT_LOG': f'{directory}/demo.jsonl'},
                                    capture_output=True, text=True, timeout=40, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            results = json.loads((Path(directory) / 'results.json').read_text())
            self.assertEqual({row['failure_type'] for row in results},
                             {'dns', 'connection_refused', 'certificate', 'unexpected_status'})
            self.assertEqual([row['attempts'] for row in results], [2, 2, 2, 1])
            self.assertIn('expired_confirmed', (Path(directory) / 'demo.jsonl').read_text())
