#!/usr/bin/env python3
"""Measure warmed sequential CLI startup and file size on this machine."""
import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

from toolkit_common import ToolError, atomic_write, audit, entrypoint


def measure(command, runs):
    samples = []
    for iteration in range(runs + 3):
        start = time.perf_counter_ns()
        subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       env={**os.environ, 'ORGANIZER_LOG': os.devnull}, check=True)
        if iteration >= 3:
            samples.append((time.perf_counter_ns() - start) / 1_000_000)
    return {'runs': runs, 'median_ms': round(statistics.median(samples), 3),
            'min_ms': round(min(samples), 3), 'max_ms': round(max(samples), 3)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        'Example: python3 lab-03/benchmark_startup.py --output /tmp/benchmark.json. '
        'Environment: TOOLKIT_LOG. Exit: 0 success, 2 args/binary, 3 I/O, 4 subprocess.'))
    parser.add_argument('--binary', type=Path, default=Path(__file__).parent / 'bin/organizer',
                        help='Built Go executable')
    parser.add_argument('--runs', type=int, default=30, help='Measured runs after 3 warmups')
    parser.add_argument('--output', type=Path, required=True, help='JSON results file')
    args = parser.parse_args()
    if args.runs < 2 or not args.binary.is_file():
        raise ToolError('Need an existing Go binary and --runs >= 2')
    reference = Path(__file__).parent / 'organizer_reference.py'
    report = {'platform': platform.platform(), 'python_version': platform.python_version(),
              'method': 'Sequential --help runs, 3 warmups; logs to /dev/null; perf_counter_ns',
              'go': {'bytes': args.binary.stat().st_size,
                     **measure([str(args.binary.resolve()), '--help'], args.runs)},
              'python': {'bytes': reference.stat().st_size,
                         **measure([sys.executable, str(reference), '--help'], args.runs)}}
    atomic_write(args.output, json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    audit('benchmark', result='success', runs=args.runs)
    return 0


if __name__ == '__main__':
    def safe_main():
        try:
            return main()
        except subprocess.CalledProcessError as exc:
            raise ToolError('A measured command failed', 4) from exc
    raise SystemExit(entrypoint('benchmark', safe_main))
