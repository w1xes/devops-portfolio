#!/usr/bin/env python3
"""Private Telegram bot with API checks, scheduled alerts and recovery notifications."""
import argparse
import fcntl
import hashlib
import json
import math
import signal
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from api_monitor import load_config, run_checks, save_results
from telegram_client import TelegramClient, TelegramError, format_alert
from toolkit_common import ToolError, atomic_write, audit, entrypoint

ROOT = Path(__file__).resolve().parent
COMMANDS = [
    ('start', 'Почати роботу'), ('help', 'Довідка'), ('status', 'Останні результати API'),
    ('check', 'Перевірити API зараз'), ('targets', 'Список цілей'),
    ('pause', 'Призупинити автоматичні перевірки'), ('resume', 'Відновити перевірки'),
    ('interval', 'Інтервал у секундах: /interval 60'), ('chatid', 'ID цього чату'),
]
HELP = '''DevOps API Monitor
/start, /help — ця довідка
/status — останній звіт і стан розкладу
/check — перевірити всі налаштовані API зараз
/targets — цілі, очікувані коди й пороги
/pause — призупинити автоматичні перевірки
/resume — відновити перевірки
/interval N — змінити інтервал (10..86400 секунд)
/chatid — ID дозволеного чату

Під час збою надходить сповіщення з його типом; однакові повтори приглушені.
При відновленні надходить окреме повідомлення. /check працює й під час паузи.
Пауза, інтервал і підтверджені сповіщення зберігаються між перезапусками.'''


def valid_interval(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 10 <= value <= 86400:
        raise ToolError('Interval must be 10..86400 seconds', 2)
    return float(value)


def read_state(path, interval, enabled):
    initial = {'version': 1, 'offset': 0, 'interval': valid_interval(interval),
               'enabled': enabled, 'alerts': {}}
    if not Path(path).exists():
        return initial
    try:
        state = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeError) as exc:
        raise ToolError('Cannot read bot state; preserve it and restore a valid backup', 3) from exc
    valid = (isinstance(state, dict) and type(state.get('version')) is int and state['version'] == 1
             and type(state.get('offset')) is int and state['offset'] >= 0
             and type(state.get('enabled')) is bool and isinstance(state.get('alerts'), dict))
    if not valid:
        raise ToolError('Invalid bot state schema; preserve the file before recovery', 3)
    try:
        valid_interval(state.get('interval'))
    except ToolError as exc:
        raise ToolError('Invalid interval in bot state', 3) from exc
    for key, result in state['alerts'].items():
        if (not isinstance(key, str) or not isinstance(result, dict)
                or type(result.get('healthy')) is not bool
                or result.get('failure_type') not in (None, 'dns', 'connection_refused', 'timeout',
                                                     'certificate', 'network', 'unexpected_status',
                                                     'slow_response')
                or (result.get('status') is not None and type(result.get('status')) is not int)):
            raise ToolError('Invalid alert state schema', 3)
    return state


@contextmanager
def instance_lock(path):
    lock = Path(str(path) + '.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ToolError('Another bot uses this state file; run one polling instance only', 5) from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


class MonitorBot:
    def __init__(self, client, *, config, output, state_path, interval=60, enabled=True, direct=False):
        self.client = client
        self.config = Path(config)
        self.output = Path(output)
        self.state_path = Path(state_path)
        self.state = read_state(state_path, interval, enabled)
        self.direct = direct
        self.username = None
        self.next_check = time.monotonic()

    def persist(self):
        atomic_write(self.state_path, json.dumps(self.state, ensure_ascii=False, indent=2) + '\n')

    def startup(self):
        identity = self.client.call('getMe')
        if (not isinstance(identity, dict) or not isinstance(identity.get('username'), str)
                or type(identity.get('id')) is not int or identity.get('is_bot') is not True):
            raise TelegramError('invalid_identity')
        owner = {'bot_id': identity['id'], 'chat_id': self.client.chat_id}
        if self.state.get('owner', owner) != owner:
            raise ToolError('Bot/chat differs from saved state; use a separate --state file', 2)
        self.state['owner'] = owner
        self.username = identity['username'].lower()
        webhook = self.client.call('getWebhookInfo')
        if not isinstance(webhook, dict):
            raise TelegramError('invalid_webhook_info')
        if webhook.get('url'):
            raise ToolError('Bot has an active webhook; remove it before using long polling', 4)
        registered = self.client.call('setMyCommands', {
            'commands': [{'command': command, 'description': text} for command, text in COMMANDS],
            'scope': {'type': 'chat', 'chat_id': self.client.chat_id},
        })
        if registered is not True:
            raise TelegramError('commands_not_registered')
        self.persist()
        audit('telegram_bot', result='connected', automatic_checks=self.state['enabled'],
              interval=self.state['interval'])

    @staticmethod
    def alert_key(target):
        # A changed URL/expected status is a new check, even when its name is unchanged.
        return hashlib.sha256(json.dumps(target, sort_keys=True).encode()).hexdigest()

    def check(self):
        targets = load_config(self.config)  # Reload on every run, without accepting URLs from chat.
        results = run_checks(targets, direct=self.direct)
        for result in results:
            result['notification'] = 'pending' if not result['healthy'] else 'not_needed'
        save_results(self.output, results)  # Preserve observations even if notification/state I/O fails.
        active_keys = set()
        for target, result in zip(targets, results, strict=True):
            key = self.alert_key(target)
            active_keys.add(key)
            previous = self.state['alerts'].get(key)
            recovered = result['healthy'] and previous is not None and not previous['healthy']
            changed = (not result['healthy'] and (previous is None or previous['healthy']
                       or (previous['failure_type'], previous['status'])
                       != (result['failure_type'], result['status'])))
            delivered = True
            if recovered or changed:
                try:
                    self.client.send_message(format_alert(result, recovered=recovered))
                    result['notification'] = 'recovery_sent' if recovered else 'sent'
                except TelegramError as exc:
                    delivered = False
                    result['notification'] = 'failed'
                    audit('telegram_alert', result='failed', reason=exc.reason,
                          target=result['target'])
                    if exc.fatal:
                        save_results(self.output, results)
                        raise
            elif not result['healthy']:
                result['notification'] = 'unchanged'
            if delivered:
                self.state['alerts'][key] = {field: result[field] for field in
                                             ('healthy', 'failure_type', 'status')}
                self.persist()  # Do not mark failed notifications as delivered.
            audit('telegram_alert', target=result['target'], result=result['notification'])
        self.state['alerts'] = {key: value for key, value in self.state['alerts'].items()
                                if key in active_keys}
        self.persist()
        save_results(self.output, results)
        self.next_check = time.monotonic() + self.state['interval']
        return results

    def status_text(self):
        schedule = 'увімкнено' if self.state['enabled'] else 'пауза'
        prefix = f"Автоперевірки: {schedule}; інтервал {self.state['interval']:g} с.\n"
        try:
            results = json.loads(self.output.read_text(encoding='utf-8'))
            if not isinstance(results, list) or not results:
                raise ValueError
            lines = []
            for row in results:
                if (not isinstance(row, dict) or not isinstance(row.get('target'), str)
                        or type(row.get('healthy')) is not bool):
                    raise ValueError
                lines.append(f"{'✅' if row['healthy'] else '🚨'} {row['target']}: "
                             f"{row.get('failure_type') or 'healthy'}; "
                             f"HTTP={row.get('status')}; {row.get('response_ms')} мс; "
                             f"UTC={row.get('time')}")
            return prefix + '\n'.join(lines)
        except (OSError, ValueError, UnicodeError):
            return prefix + 'Звіту ще немає або він недоступний. Виконайте /check.'

    def handle_update(self, update):
        if not isinstance(update, dict) or type(update.get('update_id')) is not int:
            raise TelegramError('invalid_update')
        update_id = update['update_id']
        if update_id < self.state['offset']:
            return
        message = update.get('message')
        authorized = (isinstance(message, dict) and isinstance(message.get('chat'), dict)
                      and type(message['chat'].get('id')) is int
                      and message['chat']['id'] == self.client.chat_id)
        if authorized:
            text = message.get('text')
            if isinstance(text, str) and text.startswith('/'):
                self.command(text)
        else:
            audit('telegram_update', result='ignored_unauthorized_or_nonmessage')
        self.state['offset'] = update_id + 1
        self.persist()  # Acknowledge only after processing/reply; retries may repeat a reply.

    def command(self, text):
        parts = text.split()
        verb, separator, recipient = parts[0].partition('@')
        if separator and recipient.lower() != self.username:
            return
        args = parts[1:]
        audit('telegram_command', command=verb if verb in {'/' + x[0] for x in COMMANDS}
              else 'unknown', result='received')
        if verb != '/interval' and args:
            self.client.send_message('Ця команда не приймає параметрів. Довідка: /help')
            return
        if verb in {'/start', '/help'}:
            reply = HELP
        elif verb == '/chatid':
            reply = f'ID дозволеного чату: {self.client.chat_id}'
        elif verb == '/status':
            reply = self.status_text()
        elif verb == '/targets':
            reply = '\n'.join(f"{target['name']}: HTTP {target['expected_status']}, "
                              f"timeout={target['timeout']} с, поріг={target['threshold_ms']} мс"
                              for target in load_config(self.config))
        elif verb == '/check':
            self.check()
            reply = self.status_text()
        elif verb in {'/pause', '/resume'}:
            self.state['enabled'] = verb == '/resume'
            if self.state['enabled']:
                self.next_check = time.monotonic()
            self.persist()
            reply = 'Автоперевірки відновлено.' if self.state['enabled'] else 'Автоперевірки призупинено.'
        elif verb == '/interval':
            try:
                interval = valid_interval(int(args[0])) if len(args) == 1 else None
            except (ValueError, ToolError):
                interval = None
            if interval is None:
                reply = 'Використання: /interval N, де N — ціле число 10..86400 секунд.'
            else:
                self.state['interval'] = interval
                self.next_check = time.monotonic() + interval
                self.persist()
                reply = f'Інтервал: {interval:g} с.'
        else:
            reply = 'Невідома команда. Довідка: /help'
        self.client.send_message(reply)

    def run(self, stop):
        self.startup()
        failures = 0
        while not stop.is_set():
            try:
                if self.state['enabled'] and time.monotonic() >= self.next_check:
                    try:
                        self.check()
                    except ToolError:
                        audit('telegram_schedule', result='invalid_target_configuration')
                        self.next_check = time.monotonic() + self.state['interval']
                remaining = self.next_check - time.monotonic() if self.state['enabled'] else 20
                poll_timeout = max(0, min(20, int(remaining)))
                updates = self.client.get_updates(self.state['offset'], timeout=poll_timeout)
                for update in updates:
                    if stop.is_set():
                        break
                    try:
                        self.handle_update(update)
                    except ToolError:
                        self.client.send_message('Помилка локальної конфігурації або звіту; перевірте журнал сервера.')
                        self.state['offset'] = update['update_id'] + 1
                        self.persist()
                failures = 0
                # Avoid a spin loop if Telegram returns immediately or interval remainder is <1s.
                stop.wait(min(0.2, max(0.05, remaining)))
            except TelegramError as exc:
                audit('telegram_poll', result='failed', reason=exc.reason)
                if exc.fatal:
                    raise ToolError(str(exc), 4) from None
                failures += 1
                delay = exc.retry_after if exc.reason == 'rate_limited' else min(2 ** min(failures, 6), 60)
                stop.wait(delay)
        audit('telegram_bot', result='stopped')


def discover_chat(client, stop):
    """Explicit setup mode: list IDs from /start, never reply to unconfigured chats."""
    identity = client.call('getMe')
    if not isinstance(identity, dict) or not isinstance(identity.get('username'), str):
        raise TelegramError('invalid_identity')
    webhook = client.call('getWebhookInfo')
    if not isinstance(webhook, dict) or webhook.get('url'):
        raise ToolError('An active webhook must be removed before polling', 4)
    print(f"Надішліть /start боту @{identity['username']}. Очікую до 120 секунд…", flush=True)
    deadline = time.monotonic() + 120
    offset = 0
    while not stop.is_set() and time.monotonic() < deadline:
        for update in client.get_updates(offset, timeout=10):
            if isinstance(update, dict) and type(update.get('update_id')) is int:
                offset = max(offset, update['update_id'] + 1)
            message = update.get('message', {}) if isinstance(update, dict) else {}
            chat = message.get('chat', {}) if isinstance(message, dict) else {}
            text = message.get('text', '') if isinstance(message, dict) else ''
            if (chat.get('type') == 'private' and type(chat.get('id')) is int
                    and isinstance(text, str) and text.split() and text.split()[0] == '/start'):
                print(f"Кандидат TELEGRAM_CHAT_ID={chat['id']}; підтвердьте, що це ваш приватний чат.")
                print('Додайте ID у налаштування середовища, потім запустіть бота без --discover-chat.')
                return 0
        stop.wait(0.2)
    raise ToolError('No private /start received; send it and retry --discover-chat', 4)


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        'Example: python3 lab-03/telegram_bot.py --config lab-03/config/api.json. '
        'Environment: TELEGRAM_BOT_TOKEN (secret), TELEGRAM_CHAT_ID (numeric), TOOLKIT_LOG. '
        'Exit: 0 stopped/setup/test succeeded, 2 config/arguments, 3 I/O/state, '
        '4 Telegram access, 5 duplicate instance. No incoming HTTP port required.'))
    parser.add_argument('--config', type=Path, default=ROOT / 'config/api.json', help='Targets JSON')
    parser.add_argument('--output', type=Path, default=ROOT / 'var/telegram-results.json', help='Latest JSON report')
    parser.add_argument('--state', type=Path, default=ROOT / 'var/telegram-state.json', help='Persistent private state')
    parser.add_argument('--interval', type=float, default=60, help='Initial interval 10..86400 seconds; saved state wins')
    parser.add_argument('--paused', action='store_true', help='Initial paused state; saved state wins')
    parser.add_argument('--direct', action='store_true', help='Bypass proxy for monitored targets only')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--discover-chat', action='store_true', help='Setup: show private /start chat ID; requires only token')
    mode.add_argument('--test-message', action='store_true', help='Send a test message and exit; does not poll updates')
    args = parser.parse_args()
    valid_interval(args.interval)
    client = TelegramClient.from_env(require_chat=not args.discover_chat)
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    try:
        if args.test_message:
            client.send_message('✅ DevOps API Monitor: тестове Telegram-сповіщення. З’єднання працює.')
            print('Тестове повідомлення надіслано.')
            return 0
        if args.discover_chat:
            with instance_lock(args.state):
                return discover_chat(client, stop)
        load_config(args.config)
        for path in (args.state, args.output):
            path.parent.mkdir(parents=True, exist_ok=True)
        if args.state.resolve() in {args.output.resolve(), args.config.resolve()} or args.output.resolve() == args.config.resolve():
            raise ToolError('Config, state and output paths must be different', 2)
        with instance_lock(args.state):
            MonitorBot(client, config=args.config, output=args.output, state_path=args.state,
                       interval=args.interval, enabled=not args.paused, direct=args.direct).run(stop)
    except TelegramError as exc:
        raise ToolError(str(exc), 4) from None
    return 0


if __name__ == '__main__':
    raise SystemExit(entrypoint('telegram_bot', main))
