#!/usr/bin/env python3
"""Lint only changed staged blobs, including partially staged files."""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from toolkit_common import ToolError, audit, entrypoint  # noqa: E402


def git(*args):
    return subprocess.check_output(['git', *args])


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        'Example: git -c core.hooksPath=lab-03/hooks commit; or lab-03/hooks/pre-commit. '
        'Environment: PATH must contain shellcheck/ruff, TOOLKIT_LOG. '
        'Exit: 0 clean, 1 lint findings, 2 arguments/missing linter, 3 I/O, 4 Git failure.'))
    parser.parse_args()
    root = Path(os.fsdecode(git('rev-parse', '--show-toplevel')).strip())
    os.chdir(root)
    paths = [os.fsdecode(path) for path in git('diff', '--cached', '--name-only',
                                              '--diff-filter=ACMR', '-z').split(b'\0') if path]
    with tempfile.TemporaryDirectory(prefix='lab03-index-') as directory:
        snapshot = Path(directory)
        groups = {'shellcheck': [], 'ruff': []}
        for name in paths:
            # Never follow symlinks from the Git index.
            mode = git('ls-files', '--stage', '--', name).split(b' ', 1)[0]
            if mode not in (b'100644', b'100755'):
                continue
            content = git('show', ':' + name)
            first = content.split(b'\n', 1)[0]
            shell = name.endswith('.sh') or first in (b'#!/usr/bin/env bash', b'#!/bin/bash')
            python = name.endswith('.py') or first in (b'#!/usr/bin/env python3', b'#!/usr/bin/python3')
            if not shell and not python:
                continue
            path = snapshot / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            if shell:
                groups['shellcheck'].append(str(path))
            if python:
                groups['ruff'].append(str(path))
        for tool, files in groups.items():
            if not files:
                continue
            if not shutil.which(tool):
                raise ToolError(f'Missing {tool}: activate .venv / install requirements-dev.txt', 2)
            # Explicit isolated policy is identical to lab-03/pyproject.toml and CI.
            command = [tool] if tool == 'shellcheck' else [tool, 'check', '--isolated', '--target-version', 'py312', '--select', 'E4,E7,E9,F,I']
            result = subprocess.run([*command, '--', *files], check=False)
            audit('staged_lint', tool=tool, files=len(files), result=result.returncode)
            if result.returncode:
                return 1
    audit('staged_lint', result='success', changed_paths=len(paths))
    return 0


if __name__ == '__main__':
    def safe_main():
        try:
            return main()
        except subprocess.CalledProcessError as exc:
            raise ToolError('Git index read failed', 4) from exc
    raise SystemExit(entrypoint('pre_commit', safe_main))
