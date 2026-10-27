#!/usr/bin/env python3
"""Check HTTP endpoints, classify failures and send Telegram alerts."""
import argparse
import errno
import http.client
import json
import math
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from telegram_client import TelegramClient, TelegramError, format_alert
from toolkit_common import ToolError, atomic_write, audit, entrypoint, now

FAILURE_CODES = {'dns': 10, 'connection_refused': 11, 'timeout': 12,
                 'certificate': 13, 'unexpected_status': 14, 'slow_response': 15, 'network': 16}

NETWORK_FAILURES = {'dns', 'connection_refused', 'timeout', 'certificate', 'network'}


def valid_url(value, *, https_only=False):
    if not isinstance(value, str) or any(ord(char) <= 32 or ord(char) == 127 for char in value):
        return False
    try:
        url = urllib.parse.urlsplit(value)
        return (url.scheme in ({'https'} if https_only else {'http', 'https'})
                and bool(url.hostname) and not url.username and not url.password
                and url.port != 0 and not url.fragment)
    except ValueError:
        return False


def load_config(path):
    try:
        config = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeError) as exc:
        raise ToolError('Cannot read valid JSON configuration', 2) from exc
    targets = config.get('targets') if isinstance(config, dict) else None
    if not isinstance(targets, list) or not targets:
        raise ToolError('Configuration must contain a nonempty targets list', 2)
    names = set()
    for target in targets:
        if not isinstance(target, dict):
            raise ToolError('Every target must be an object', 2)
        name = target.get('name')
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ToolError('Target names must be nonempty and unique', 2)
        names.add(name)
        if not valid_url(target.get('url')):
            raise ToolError(f'{name}: url must be HTTP(S), without embedded credentials', 2)
        status = target.get('expected_status')
        if type(status) is not int or not 100 <= status <= 599:
            raise ToolError(f'{name}: expected_status must be 100..599', 2)
        for key in ('timeout', 'threshold_ms'):
            value = target.get(key)
            if (type(value) not in (int, float) or not math.isfinite(value) or value <= 0):
                raise ToolError(f'{name}: {key} must be a finite positive number', 2)
    return targets


def classify(exc):
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, socket.gaierror):
        return 'dns'
    if isinstance(reason, ssl.SSLCertVerificationError):
        return 'certificate'
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return 'timeout'
    if isinstance(reason, ConnectionRefusedError) or getattr(reason, 'errno', None) == errno.ECONNREFUSED:
        return 'connection_refused'
    return 'network'


def make_opener(direct=False):
    handlers = [urllib.request.HTTPSHandler(context=ssl.create_default_context())]
    if direct:
        handlers.append(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers)


def check_once(target, opener):
    started = time.monotonic()
    status, failure = None, None
    try:
        request = urllib.request.Request(target['url'], headers={'User-Agent': 'devops-lab03/1'})
        try:
            with opener.open(request, timeout=target['timeout']) as response:
                status = response.status
                response.read(1)
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
        if status != target['expected_status']:
            failure = 'unexpected_status'
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        failure = classify(exc)
    elapsed = round((time.monotonic() - started) * 1000, 3)
    if failure is None and elapsed > target['threshold_ms']:
        failure = 'slow_response'
    return {'time': now(), 'target': target['name'], 'status': status,
            'response_ms': elapsed, 'failure_type': failure,
            'healthy': failure is None}


def check_target(target, opener):
    for attempt in (1, 2):
        result = check_once(target, opener)
        result['attempts'] = attempt
        audit('api_check', **result)
        if result['failure_type'] not in NETWORK_FAILURES:
            break
    return result


def notify(result, client):
    try:
        client.send_message(format_alert(result))
    except TelegramError as exc:
        audit('telegram_notification', result='failed', reason=exc.reason)
        return False
    return True


def run_checks(targets, *, direct=False):
    opener = make_opener(direct)
    return [check_target(target, opener) for target in targets]


def save_results(path, results):
    atomic_write(path, json.dumps(results, indent=2, ensure_ascii=False) + '\n')


def health_exit_code(results):
    failures = {item['failure_type'] for item in results if not item['healthy']}
    return (FAILURE_CODES[next(iter(failures))] if len(failures) == 1 else 1) if failures else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        'Example: python3 lab-03/api_monitor.py --config lab-03/config/api.json '
        '--output /tmp/api-results.json\nEnvironment: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, '
        'TOOLKIT_LOG (audit JSONL). Exit: 0 healthy, 1 unhealthy, 2 config/arguments, '
        '3 I/O, 4 notification unavailable/failed, 10 DNS, 11 refused, 12 timeout, '
        '13 certificate, 14 unexpected status, 15 slow, 16 other network; 1 mixed failures.'))
    parser.add_argument('--config', required=True, help='JSON file containing targets')
    parser.add_argument('--output', required=True, help='Atomic JSON report (parent must exist)')
    parser.add_argument('--direct', action='store_true', help='Ignore HTTP proxy for target requests')
    parser.add_argument('--no-notify', action='store_true', help='Explicit diagnostic mode, skip Telegram')
    args = parser.parse_args()
    targets = load_config(args.config)
    client = None
    if not args.no_notify:
        # Missing credentials must not hide the actual endpoint results.
        try:
            client = TelegramClient.from_env()
        except ToolError:
            audit('telegram_notification', result='configuration_missing_or_invalid')
    results = run_checks(targets, direct=args.direct)
    save_results(args.output, results)
    notification_failed = False
    for result in results:
        if result['healthy']:
            result['notification'] = 'not_needed'
        elif args.no_notify:
            result['notification'] = 'disabled'
        elif client is None:
            result['notification'] = 'missing_telegram_config'
            notification_failed = True
        else:
            success = notify(result, client)
            result['notification'] = 'sent' if success else 'failed'
            notification_failed |= not success
        if not result['healthy']:
            audit('api_notification', target=result['target'],
                  result=result['notification'], failure_type=result['failure_type'])
    save_results(args.output, results)
    for result in results:
        print(f"{result['target']}: {result['failure_type'] or 'healthy'} "
              f"status={result['status']} time_ms={result['response_ms']} "
              f"notification={result['notification']}")
    if notification_failed:
        return 4
    return health_exit_code(results)


if __name__ == '__main__':
    raise SystemExit(entrypoint('api_monitor', main))
