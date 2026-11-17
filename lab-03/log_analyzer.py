#!/usr/bin/env python3
"""Stream a Combined access log into a text/JSON traffic report."""
import argparse
import ipaddress
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from toolkit_common import ToolError, atomic_write, audit, entrypoint

QUOTED = r'"(?:\\.|[^"\\])*"'
COMBINED = re.compile(
    r'^(?P<address>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] '
    + r'(?P<request>' + QUOTED + r') (?P<status>[1-5][0-9]{2}) (?:[0-9]+|-) '
    + QUOTED + ' ' + QUOTED + r'\s*$')


def parse_line(line):
    """Return normalized fields, or None for a malformed Combined line."""
    match = COMBINED.fullmatch(line.rstrip('\r\n'))
    if not match:
        return None
    try:
        address = str(ipaddress.ip_address(match['address']))
        timestamp = datetime.strptime(match['time'], '%d/%b/%Y:%H:%M:%S %z')
    except ValueError:
        return None
    return {'address': address, 'time': timestamp,
            'status': int(match['status']), 'request': match['request'][1:-1]}


def analyze(lines, top):
    addresses, classes, hours = Counter(), Counter(), Counter()
    malformed = 0
    for line in lines:
        record = parse_line(line)
        if record is None:
            malformed += 1
            continue
        addresses[record['address']] += 1
        classes[f"{record['status'] // 100}xx"] += 1
        hour = record['time'].astimezone(timezone.utc).strftime('%Y-%m-%dT%H:00:00Z')
        hours[hour] += 1
    peak = max(hours.values(), default=0)
    return {
        'valid_lines': sum(addresses.values()), 'malformed_lines': malformed,
        'top_addresses': [{'address': address, 'requests': count} for address, count
                          in sorted(addresses.items(), key=lambda item: (-item[1], item[0]))[:top]],
        'status_classes': {f'{i}xx': classes[f'{i}xx'] for i in range(1, 6)},
        'requests_by_hour_utc': dict(sorted(hours.items())),
        'peak_hours_utc': [hour for hour, count in sorted(hours.items()) if count == peak],
        'peak_requests': peak,
    }


def text_report(report):
    lines = [f"Valid lines: {report['valid_lines']}",
             f"Malformed lines: {report['malformed_lines']}", 'Top addresses:']
    lines += [f"  {item['address']}: {item['requests']}" for item in report['top_addresses']]
    lines += ['Status classes:']
    lines += [f'  {key}: {value}' for key, value in report['status_classes'].items()]
    lines += ['Requests by hour (UTC):']
    lines += [f'  {key}: {value}' for key, value in report['requests_by_hour_utc'].items()]
    lines += [f"Peak hours (UTC): {', '.join(report['peak_hours_utc']) or 'none'} "
              f"({report['peak_requests']} requests each)"]
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        'Example: python3 lab-03/log_analyzer.py --input lab-03/tests/fixtures/access.combined '
        '--output /tmp/report.json --format json --top 5. '
        'Environment: TOOLKIT_LOG. Exit: 0 success (including malformed lines), '
        '2 arguments/input validation, 3 file or log I/O.'))
    parser.add_argument('--input', required=True, help='Combined access log (UTF-8)')
    parser.add_argument('--output', required=True, help='Report file (parent must exist)')
    parser.add_argument('--format', choices=['text', 'json'], default='text', help='Output format')
    parser.add_argument('--top', type=int, default=10, help='Number of top addresses (positive, default 10)')
    args = parser.parse_args()
    if args.top <= 0:
        raise ToolError('--top must be positive')
    if Path(args.input).resolve() == Path(args.output).resolve():
        raise ToolError('Input and output must be different files')
    with Path(args.input).open(encoding='utf-8', errors='replace') as stream:
        report = analyze(stream, args.top)
    output = json.dumps(report, ensure_ascii=False, indent=2) + '\n' if args.format == 'json' else text_report(report)
    atomic_write(args.output, output)
    print(output, end='')
    audit('log_analysis', result='success', valid_lines=report['valid_lines'],
          malformed_lines=report['malformed_lines'])
    return 0


if __name__ == '__main__':
    raise SystemExit(entrypoint('log_analyzer', main))
