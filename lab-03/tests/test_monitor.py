"""Sample real Linux metrics and force deterministic threshold alerts."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'monitor.sh'


class MonitorTests(unittest.TestCase):
    def run_monitor(self, **overrides):
        with tempfile.TemporaryDirectory() as directory:
            env = {**os.environ, 'MONITOR_LOG': f'{directory}/monitor.log',
                   'CPU_MAX': '100', 'MEM_MAX': '100', 'DISK_MIN_FREE': '0',
                   'SAMPLE_SECONDS': '0.05', 'DISK_PATHS': directory,
                   'PROCESSES': '', 'SERVICES': '', **overrides}
            result = subprocess.run([str(SCRIPT)], env=env, text=True,
                                    capture_output=True, check=False)
            self.assertTrue(Path(env['MONITOR_LOG']).exists())
            return result

    def test_healthy_real_metrics(self):
        result = self.run_monitor()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        for metric in ('cpu_used_pct', 'memory_used_pct', 'disk_free_pct'):
            self.assertIn(f'metric={metric}', result.stdout)

    def test_forced_memory_alert(self):
        result = self.run_monitor(MEM_MAX='0')
        self.assertEqual(result.returncode, 11, result.stderr)
        self.assertRegex(result.stdout, r'metric=memory_used_pct .* result=ALERT')

    def test_process_absence_and_presence(self):
        self.assertEqual(self.run_monitor(PROCESSES='not-a-real-proc').returncode, 14)
        self.assertEqual(self.run_monitor(PROCESSES='python3').returncode, 0)

    def test_invalid_threshold(self):
        self.assertEqual(self.run_monitor(MEM_MAX='nan').returncode, 2)
        self.assertEqual(self.run_monitor(CPU_MAX='101').returncode, 2)
