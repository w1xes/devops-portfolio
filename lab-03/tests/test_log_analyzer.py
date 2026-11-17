"""Parser and report tests include malformed and timezone-normalized input."""
import unittest
from pathlib import Path

from log_analyzer import analyze, parse_line, text_report

FIXTURE = Path(__file__).parent / 'fixtures/access.combined'


class LogAnalyzerTests(unittest.TestCase):
    def test_parse_valid_line(self):
        result = parse_line(FIXTURE.read_text().splitlines()[0])
        self.assertEqual(result['address'], '192.0.2.10')
        self.assertEqual(result['status'], 200)
        self.assertEqual(result['time'].utcoffset().total_seconds(), 10800)

    def test_parse_invalid_line(self):
        for line in ('garbage', '', '192.0.2.1 - - [bad] "GET /" 200 1 "-" "agent"',
                     FIXTURE.read_text().splitlines()[-1]):
            self.assertIsNone(parse_line(line))

    def test_escaped_quotes_and_ipv6(self):
        line = r'2001:db8::1 - - [20/Oct/2026:10:00:00 +0000] "GET / HTTP/1.1" 200 - "-" "agent\"test"'
        self.assertEqual(parse_line(line)['address'], '2001:db8::1')

    def test_full_report_and_corrupt_line_count(self):
        report = analyze(FIXTURE.read_text().splitlines(), 1)
        self.assertEqual(report['valid_lines'], 4)
        self.assertEqual(report['malformed_lines'], 2)
        self.assertEqual(report['top_addresses'], [{'address': '192.0.2.10', 'requests': 2}])
        self.assertEqual(report['status_classes'], {'1xx': 0, '2xx': 1, '3xx': 1, '4xx': 1, '5xx': 1})
        self.assertEqual(report['peak_hours_utc'], ['2026-10-20T07:00:00Z'])
        self.assertEqual(report['peak_requests'], 3)
        self.assertIn('Malformed lines: 2', text_report(report))

    def test_empty_log(self):
        report = analyze([], 5)
        self.assertEqual(report['peak_hours_utc'], [])
        self.assertEqual(report['valid_lines'], 0)
