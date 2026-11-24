"""Git fixtures prove the hook checks the index, not the working tree."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[1] / 'hooks'


class HookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {**os.environ, 'TOOLKIT_LOG': str(self.root / 'audit.jsonl')}
        self.git('init', '-q')

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.root, env=self.env,
                              capture_output=True, text=True, check=True)

    def hook(self):
        return subprocess.run(['python3', str(HOOKS / 'pre_commit.py')], cwd=self.root,
                              env=self.env, capture_output=True, text=True, check=False)

    def test_staged_error_blocks_even_when_working_tree_fixed(self):
        path = self.root / 'with spaces.py'
        path.write_text('print(undefined_name)\n')
        self.git('add', path.name)
        path.write_text('print("fixed but unstaged")\n')
        result = self.hook()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('F821', result.stdout)

    def test_unstaged_error_does_not_block_clean_index(self):
        path = self.root / 'clean.py'
        path.write_text('print("staged")\n')
        self.git('add', path.name)
        path.write_text('print(undefined_name)\n')
        (self.root / 'untracked.sh').write_text('if bad syntax')
        self.assertEqual(self.hook().returncode, 0)

    def test_shell_staged_blob_and_staged_symlink(self):
        path = self.root / 'script with spaces.sh'
        path.write_text('#!/bin/bash\nset -euo pipefail\necho $unquoted\n')
        self.git('add', path.name)
        self.assertEqual(self.hook().returncode, 1)
        self.git('rm', '--cached', path.name)
        (self.root / 'outside.py').symlink_to('/nonexistent')
        self.git('add', 'outside.py')
        self.assertEqual(self.hook().returncode, 0)

    def test_push_hook_blocks_failing_runner_and_allows_passing_runner(self):
        lab = self.root / 'lab-03'
        lab.mkdir()
        runner = lab / 'run-tests.sh'
        for exit_code, expected in ((23, 1), (0, 0)):
            runner.write_text(f'#!/bin/bash\nset -euo pipefail\nexit {exit_code}\n')
            runner.chmod(0o755)
            result = subprocess.run([str(HOOKS / 'pre-push'), 'origin', 'unused-url'],
                                    cwd=self.root, env=self.env, capture_output=True,
                                    text=True, check=False)
            self.assertEqual(result.returncode, expected, result.stderr)
        log = (lab / 'var/pre-push.log').read_text()
        self.assertIn('result=failed', log)
        self.assertIn('result=passed', log)
