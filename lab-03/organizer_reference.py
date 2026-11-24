#!/usr/bin/env python3
"""Script analogue for measuring organizer startup; same move/no-clobber policy."""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

CATEGORIES = {
    'documents': '.txt .md .pdf .doc .docx .odt .csv .xlsx',
    'images': '.jpg .jpeg .png .gif .webp .svg .bmp',
    'videos': '.mp4 .mkv .mov .avi .webm',
    'archives': '.zip .gz .bz2 .xz .tar .7z .rar',
}
EXTENSIONS = {extension: category for category, values in CATEGORIES.items()
              for extension in values.split()}


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        'Example: python3 lab-03/organizer_reference.py organize --source /tmp/files --dry-run. '
        'Environment: ORGANIZER_LOG. Exit: 0 success, 2 args, 3 source, 4 move, 5 log.'))
    sub = parser.add_subparsers(dest='command', required=True)
    organize = sub.add_parser('organize', help='Move files by extension')
    organize.add_argument('--source', required=True, help='Existing directory')
    organize.add_argument('--dry-run', action='store_true', help='Print without any file changes')
    sub.add_parser('categories', help='Show supported extensions')
    args = parser.parse_args()
    if args.command == 'categories':
        for extension, category in sorted(EXTENSIONS.items()):
            print(extension, category)
        return 0
    source = Path(args.source)
    if not source.is_dir():
        print('Error: source must be an accessible directory', file=sys.stderr)
        return 3
    moves = []
    try:
        for path in sorted(source.iterdir()):
            category = EXTENSIONS.get(path.suffix.lower())
            if not category or path.is_symlink() or not path.is_file():
                continue
            directory = source / category
            if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
                raise OSError('Category must be a real directory')
            destination = directory / path.name
            if destination.exists() or destination.is_symlink():
                raise OSError('Destination already exists')
            moves.append((path, destination))
        for path, destination in moves:
            if args.dry_run:
                print(f'MOVE {str(path)!r} -> {str(destination)!r}')
                continue
            destination.parent.mkdir(exist_ok=True)
            os.link(path, destination)
            try:
                path.unlink()
            except OSError:
                destination.unlink()
                raise
            print(f'MOVED {str(path)!r} -> {str(destination)!r}')
    except OSError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 4
    print(f'files={len(moves)} dry_run={str(args.dry_run).lower()}')
    return 0


def run():
    # Dry-run never writes a log, even for invalid arguments. Every run logs to stderr.
    code = 0
    try:
        code = main()
    except SystemExit as exc:
        code = exc.code or 0
    record = {'time': datetime.now(timezone.utc).isoformat(), 'action': 'organizer_reference',
              'result': 'finished', 'exit_code': code}
    text = json.dumps(record) + '\n'
    sys.stderr.write(text)
    if '--dry-run' not in sys.argv:
        try:
            with open(os.environ.get('ORGANIZER_LOG', 'organizer.log'), 'a', encoding='utf-8') as stream:
                stream.write(text)
        except OSError:
            print('Error: cannot write ORGANIZER_LOG', file=sys.stderr)
            return 5
    return code


if __name__ == '__main__':
    raise SystemExit(run())
