"""Authorization, commands, scheduled checks, recovery and durable bot state."""
import copy
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from telegram_bot import MonitorBot, discover_chat, instance_lock, read_state
from telegram_client import TelegramError
from toolkit_common import ToolError


class FakeClient:
    chat_id = 42

    def __init__(self):
        self.sent = []
        self.send_errors = []
        self.webhook = ''
        self.on_poll = lambda offset, timeout: []
        self.calls = []

    def call(self, method, payload=None):
        self.calls.append((method, payload))
        return {'getMe': {'id': 123, 'is_bot': True, 'username': 'devops_test_bot'},
                'getWebhookInfo': {'url': self.webhook}, 'setMyCommands': True}[method]

    def send_message(self, text):
        if self.send_errors:
            error = self.send_errors.pop(0)
            if error:
                raise error
        self.sent.append(text)
        return True

    def get_updates(self, offset, timeout=20):
        return self.on_poll(offset, timeout)


def result(failure=None, status=200):
    return {'time': '2026-10-27T16:00:00Z', 'target': 'local', 'status': status,
            'response_ms': 12, 'failure_type': failure, 'healthy': failure is None, 'attempts': 1}


class BotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patcher = patch.dict(os.environ, {'TOOLKIT_LOG': str(self.root / 'audit.jsonl')})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.config = self.root / 'api.json'
        self.target = {'name': 'local', 'url': 'https://example.com', 'expected_status': 200,
                       'timeout': 1, 'threshold_ms': 1000}
        self.config.write_text(json.dumps({'targets': [self.target]}))
        self.client = FakeClient()
        self.bot = self.new_bot()
        self.bot.username = 'devops_test_bot'

    def new_bot(self, **kwargs):
        return MonitorBot(self.client, config=self.config, output=self.root / 'results.json',
                          state_path=self.root / 'state.json', **kwargs)

    def update(self, text, update_id=1, chat_id=42):
        return {'update_id': update_id, 'message': {'chat': {'id': chat_id, 'type': 'private'},
                                                   'text': text}}

    def check(self, row):
        with patch('telegram_bot.run_checks', return_value=[copy.deepcopy(row)]):
            return self.bot.check()

    def test_commands_and_bot_addressing(self):
        for command in ('/start', '/help', '/targets', '/chatid', '/status', '/unknown'):
            self.bot.command(command)
        self.assertIn('/interval', self.client.sent[0])
        self.assertIn('local', self.client.sent[2])
        self.assertIn('42', self.client.sent[3])
        self.assertIn('Звіту ще немає', self.client.sent[4])
        self.assertIn('Невідома команда', self.client.sent[5])
        self.bot.command('/help@another_bot')
        self.assertEqual(len(self.client.sent), 6)
        self.bot.command('/help@devops_test_bot')
        self.assertEqual(len(self.client.sent), 7)

    def test_foreign_chat_cannot_run_checks_or_read_status(self):
        with patch.object(self.bot, 'check') as check:
            self.bot.handle_update(self.update('/check', chat_id=999))
            self.bot.handle_update(self.update('/status', update_id=2, chat_id=999))
            check.assert_not_called()
        self.assertEqual(self.client.sent, [])
        self.assertEqual(self.bot.state['offset'], 3)
        self.assertNotIn('999', (self.root / 'audit.jsonl').read_text())

    def test_pause_resume_interval_and_offset_survive_restart(self):
        self.bot.handle_update(self.update('/pause'))
        self.bot.handle_update(self.update('/interval 120', update_id=2))
        restarted = self.new_bot()
        self.assertFalse(restarted.state['enabled'])
        self.assertEqual(restarted.state['interval'], 120)
        self.assertEqual(restarted.state['offset'], 3)
        before = len(self.client.sent)
        restarted.handle_update(self.update('/resume', update_id=2))
        self.assertEqual(len(self.client.sent), before)
        restarted.handle_update(self.update('/resume', update_id=3))
        self.assertTrue(restarted.state['enabled'])
        for bad in ('/interval', '/interval NaN', '/interval -1', '/interval 9',
                    '/interval 86401', '/interval 10 extra', '/help extra'):
            restarted.command(bad)
        self.assertEqual(restarted.state['interval'], 120)

    def test_alert_deduplication_changed_failure_and_recovery(self):
        self.assertEqual(self.check(result()) [0]['notification'], 'not_needed')
        first = self.check(result('unexpected_status', 503))
        self.assertEqual(first[0]['notification'], 'sent')
        self.assertEqual(self.check(result('unexpected_status', 503))[0]['notification'], 'unchanged')
        # Changed HTTP status is a new incident; varying latency alone is not.
        self.assertEqual(self.check(result('unexpected_status', 500))[0]['notification'], 'sent')
        self.assertEqual(self.check(result('timeout', None))[0]['notification'], 'sent')
        recovered = self.check(result())
        self.assertEqual(recovered[0]['notification'], 'recovery_sent')
        self.assertIn('відновився', self.client.sent[-1])
        self.assertEqual(len(self.client.sent), 4)
        restarted = self.new_bot()
        with patch('telegram_bot.run_checks', return_value=[result()]):
            restarted.check()
        self.assertEqual(len(self.client.sent), 4)

    def test_failed_delivery_is_retried_and_report_is_retained(self):
        self.client.send_errors = [TelegramError('network_error')]
        first = self.check(result('dns', None))
        self.assertEqual(first[0]['notification'], 'failed')
        self.assertEqual(self.bot.state['alerts'], {})
        report = json.loads((self.root / 'results.json').read_text())
        self.assertEqual(report[0]['failure_type'], 'dns')
        self.assertEqual(self.check(result('dns', None))[0]['notification'], 'sent')
        self.assertEqual(len(self.client.sent), 1)
        self.client.send_errors = [TelegramError('network_error')]
        self.assertEqual(self.check(result())[0]['notification'], 'failed')
        self.assertEqual(self.check(result())[0]['notification'], 'recovery_sent')

    def test_manual_check_works_while_paused(self):
        self.bot.command('/pause')
        with patch('telegram_bot.run_checks', return_value=[result()]):
            self.bot.command('/check')
        self.assertFalse(self.bot.state['enabled'])
        self.assertIn('local: healthy', self.client.sent[-1])
        self.assertIn('пауза', self.client.sent[-1])

    def test_target_config_is_reloaded_and_changed_url_resets_alert_baseline(self):
        self.check(result('timeout', None))
        self.target['url'] = 'https://another.example.com'
        self.config.write_text(json.dumps({'targets': [self.target]}))
        self.check(result('timeout', None))
        self.assertEqual(len(self.client.sent), 2)
        self.assertEqual(len(self.bot.state['alerts']), 1)

    def test_startup_registers_chat_scoped_commands_and_refuses_active_webhook(self):
        self.bot.startup()
        self.assertEqual(self.client.calls[-1][0], 'setMyCommands')
        payload = self.client.calls[-1][1]
        self.assertEqual(payload['scope'], {'type': 'chat', 'chat_id': 42})
        self.assertIn('check', [entry['command'] for entry in payload['commands']])
        self.client.webhook = 'https://do-not-log.example/secret'
        with self.assertRaises(ToolError) as caught:
            self.bot.startup()
        self.assertNotIn('secret', str(caught.exception))

    def test_different_bot_or_chat_cannot_reuse_bound_state(self):
        self.bot.startup()
        self.client.chat_id = 99
        with self.assertRaises(ToolError):
            self.new_bot().startup()

    def test_durable_cursor_is_not_advanced_after_failed_command_reply(self):
        self.client.send_errors = [TelegramError('network_error')]
        with self.assertRaises(TelegramError):
            self.bot.handle_update(self.update('/help'))
        self.assertEqual(self.bot.state['offset'], 0)
        self.bot.handle_update(self.update('/help'))
        self.assertEqual(self.bot.state['offset'], 2)

    def test_scheduler_executes_three_checks_without_external_calls(self):
        stop = threading.Event()
        clock, polls = [0.0], []

        def poll(offset, timeout):
            polls.append(timeout)
            clock[0] += 60
            if len(polls) == 3:
                stop.set()
            return []

        self.client.on_poll = poll
        with patch('telegram_bot.time.monotonic', side_effect=lambda: clock[0]), \
                patch('telegram_bot.run_checks', return_value=[result()]) as checks:
            self.bot.next_check = 0
            self.bot.run(stop)
        self.assertEqual(checks.call_count, 3)
        self.assertTrue(all(0 <= timeout <= 20 for timeout in polls))

    def test_polling_fatal_and_rate_limit_paths(self):
        stop = threading.Event()
        self.client.on_poll = lambda *_: (_ for _ in ()).throw(TelegramError('polling_conflict'))
        with patch('telegram_bot.run_checks', return_value=[result()]), self.assertRaises(ToolError) as caught:
            self.bot.run(stop)
        self.assertEqual(caught.exception.code, 4)
        attempts = []

        def limited(*_):
            attempts.append(1)
            if len(attempts) == 1:
                raise TelegramError('rate_limited', retry_after=12)
            stop.set()
            return []

        self.client.on_poll = limited
        with patch.object(stop, 'wait') as wait:
            self.bot.run(stop)
        wait.assert_any_call(12)

    def test_discovery_does_not_send_or_auto_authorize(self):
        client = FakeClient()
        client.chat_id = None
        client.on_poll = lambda *_: [self.update('/start', chat_id=777)]
        with patch('builtins.print') as output:
            self.assertEqual(discover_chat(client, threading.Event()), 0)
        self.assertIn('777', str(output.call_args_list))
        self.assertEqual(client.sent, [])
        self.assertFalse((self.root / 'state.json').exists())

    def test_corrupt_state_and_duplicate_instance_are_friendly_errors(self):
        state = self.root / 'state.json'
        for text in ('broken', '{}', '{"version": 1, "offset": -1}'):
            state.write_text(text)
            with self.assertRaises(ToolError):
                read_state(state, 60, True)
        with instance_lock(state):
            with self.assertRaises(ToolError) as caught:
                with instance_lock(state):
                    pass
        self.assertEqual(caught.exception.code, 5)
