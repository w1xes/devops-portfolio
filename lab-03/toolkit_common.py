"""Shared JSON audit log, atomic reports and friendly CLI error handling."""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class ToolError(Exception):
    def __init__(self, message, code=2):
        super().__init__(message)
        self.code = code


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def audit(action, **fields):
    record = {'time': now(), 'action': action, **fields}
    line = json.dumps(record, ensure_ascii=False, allow_nan=False)
    print(line, file=sys.stderr)
    path = Path(os.environ.get('TOOLKIT_LOG', Path(__file__).parent / 'var/toolkit.jsonl'))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as stream:
        stream.write(line + '\n')


def atomic_write(path, text):
    path = Path(path)
    # Do not create user-supplied parent directories silently.
    fd, temp = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def entrypoint(action, main):
    code = 0
    try:
        audit(action, result='started')
        code = main() or 0
    except ToolError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        code = exc.code
    except (OSError, UnicodeError) as exc:
        print(f'Error: file/system operation failed ({type(exc).__name__})', file=sys.stderr)
        code = 3
    except SystemExit as exc:
        code = exc.code or 0
    except KeyboardInterrupt:
        code = 130
    try:
        audit(action, result='finished', exit_code=code)
    except OSError:
        print('Error: cannot write audit log (TOOLKIT_LOG)', file=sys.stderr)
        code = 3
    return code
