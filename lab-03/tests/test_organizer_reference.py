"""Functional cross-check of the script used in the Go startup comparison."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'organizer_reference.py'


class ReferenceTests(unittest.TestCase):
    def test_dry_run_then_real_move_and_collision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'my files'
            source.mkdir()
            for name in ('a.pdf', 'b.PNG', 'c.mp4', 'd.zip', 'keep.unknown'):
                (source / name).write_text(name)
            command = ['python3', str(SCRIPT), 'organize', '--source', str(source)]
            env = {**os.environ, 'ORGANIZER_LOG': str(root / 'audit.log')}
            dry = subprocess.run([*command, '--dry-run'], env=env, capture_output=True, check=False)
            self.assertEqual(dry.returncode, 0, dry.stderr)
            self.assertFalse((root / 'audit.log').exists())
            self.assertEqual(len(list(source.iterdir())), 5)
            real = subprocess.run(command, env=env, capture_output=True, check=False)
            self.assertEqual(real.returncode, 0, real.stderr)
            for category, name in [('documents', 'a.pdf'), ('images', 'b.PNG'),
                                   ('videos', 'c.mp4'), ('archives', 'd.zip')]:
                self.assertEqual((source / category / name).read_text(), name)
            (source / 'a.pdf').write_text('new')
            collision = subprocess.run(command, env=env, capture_output=True, check=False)
            self.assertEqual(collision.returncode, 4)
            self.assertEqual((source / 'a.pdf').read_text(), 'new')
            self.assertEqual((source / 'documents/a.pdf').read_text(), 'a.pdf')
