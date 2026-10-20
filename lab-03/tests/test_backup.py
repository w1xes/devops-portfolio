"""Exercise real archives, source isolation and mutation-free dry runs."""
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'backup.sh'


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'my project'
        self.source.mkdir()
        (self.source / 'hello.txt').write_text('preserve this content')
        self.dest = self.root / 'my backups'

    def run_backup(self, *args, source=None):
        return subprocess.run(
            [str(SCRIPT), '--source', str(source or self.source), '--dest',
             str(self.dest), *args], cwd=self.root, text=True, capture_output=True,
            env={**os.environ, 'BACKUP_LOG': str(self.root / 'backup.log')}, check=False)

    def test_six_backups_keep_three_and_preserve_foreign_files(self):
        self.dest.mkdir()
        foreign = self.dest / 'my project-foreign.tar.gz'
        foreign.write_text('unrelated')
        for _ in range(6):
            result = self.run_backup('--keep', '3')
            self.assertEqual(result.returncode, 0, result.stderr)
        archives = [p for p in self.dest.glob('*.tar.gz') if p != foreign]
        self.assertEqual(len(archives), 3)
        with tarfile.open(sorted(archives)[-1]) as archive:
            self.assertEqual(archive.extractfile('my project/hello.txt').read(),
                             b'preserve this content')
        self.assertEqual(foreign.read_text(), 'unrelated')
        self.assertIn('archived_files=1', (self.root / 'backup.log').read_text())

    def test_dry_run_plans_rotation_without_changes(self):
        for _ in range(5):
            self.assertEqual(self.run_backup().returncode, 0)
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = self.run_backup('--keep', '3', '--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count('DELETE '), 3)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_dry_run_does_not_create_destination_or_log(self):
        result = self.run_backup('--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.dest.exists())
        self.assertFalse((self.root / 'backup.log').exists())

    def test_invalid_input_and_nested_destination(self):
        self.assertEqual(self.run_backup(source=self.root / 'missing').returncode, 3)
        self.assertEqual(self.run_backup('--keep', '0').returncode, 2)
        self.dest = self.source / 'backups'
        self.assertEqual(self.run_backup().returncode, 4)

    def test_same_basename_sources_rotate_independently(self):
        other = self.root / 'other' / self.source.name
        other.mkdir(parents=True)
        (other / 'other.txt').write_text('other')
        for source in (self.source, other, self.source, other):
            self.assertEqual(self.run_backup('--keep', '1', source=source).returncode, 0)
        self.assertEqual(len(list(self.dest.glob('*.tar.gz'))), 2)
