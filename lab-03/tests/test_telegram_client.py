"""Telegram protocol, bounded responses, redaction and retries without real secrets."""
import io
import json
import os
import traceback
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch

from telegram_client import (
    TelegramClient,
    TelegramError,
    chat_id_from_env,
    secure_opener,
    split_text,
    token_from_env,
)
from toolkit_common import ToolError


class Reply(io.BytesIO):
    def __init__(self, body, status=200):
        super().__init__(body if isinstance(body, bytes) else json.dumps(body).encode())
        self.status = status


def opener_with(body, status=200):
    return Mock(open=Mock(return_value=Reply(body, status)))


class TelegramClientTests(unittest.TestCase):
    def test_send_message_contract_and_unicode(self):
        opener = opener_with({'ok': True, 'result': {'message_id': 1}})
        client = TelegramClient('123:fake-secret', -100123, opener=opener)
        self.assertTrue(client.send_message('🚨 API: dns'))
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.telegram.org/bot123:fake-secret/sendMessage')
        body = json.loads(request.data)
        self.assertEqual(body['chat_id'], -100123)
        self.assertEqual(body['text'], '🚨 API: dns')
        self.assertNotIn('parse_mode', body)
        self.assertEqual(body['link_preview_options'], {'is_disabled': True})

    def test_long_messages_preserve_text_and_respect_utf16_limit(self):
        text = '🚨Українська\n' * 1000
        chunks = list(split_text(text))
        self.assertEqual(''.join(chunks), text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk.encode('utf-16-le')) // 2 <= 3500 for chunk in chunks))
        opener = Mock()
        opener.open.side_effect = lambda *a, **k: Reply({'ok': True, 'result': {'message_id': 1}})
        TelegramClient('fake', 42, opener=opener).send_message(text)
        self.assertEqual(opener.open.call_count, len(chunks))

    def test_errors_never_retain_secret_url_or_raw_server_description(self):
        for code, reason in [(401, 'unauthorized'), (403, 'forbidden'),
                             (409, 'polling_conflict'), (500, 'http_error')]:
            token = '123:super-secret-token'
            url = f'https://api.telegram.org/bot{token}/sendMessage'
            error = urllib.error.HTTPError(url, code, token, {}, io.BytesIO(json.dumps({
                'ok': False, 'error_code': code, 'description': token}).encode()))
            client = TelegramClient(token, 42, opener=Mock(open=Mock(side_effect=error)))
            try:
                client.send_message('test')
            except TelegramError as exc:
                self.assertEqual(exc.reason, reason)
                self.assertIsNone(exc.__context__)
                self.assertNotIn(token, ''.join(traceback.format_exception(exc)))
            else:
                self.fail('API error was accepted')

    def test_network_error_and_invalid_json_are_safe(self):
        for outcome, expected in [(urllib.error.URLError('123:secret'), 'network_error'),
                                  (Reply(b'bad JSON 123:secret'), 'invalid_response'),
                                  (Reply({'ok': True}), 'invalid_response'),
                                  (Reply({'ok': True, 'result': {'message_id': True}}),
                                   'invalid_message_response'),
                                  (Reply(b'x' * 1_048_577), 'oversized_response')]:
            opener = Mock()
            if isinstance(outcome, Exception):
                opener.open.side_effect = outcome
            else:
                opener.open.return_value = outcome
            with self.subTest(expected=expected), self.assertRaises(TelegramError) as caught:
                TelegramClient('123:secret', 42, opener=opener).send_message('test')
            self.assertEqual(caught.exception.reason, expected)
            self.assertNotIn('123:secret', str(caught.exception))

    def test_rate_limit_preserves_bounded_retry_after(self):
        for delay, expected in [(12, 12), (99999, 300), (-1, 1), ('bad', 5)]:
            opener = opener_with({'ok': False, 'error_code': 429,
                                  'parameters': {'retry_after': delay}}, 429)
            with self.assertRaises(TelegramError) as caught:
                TelegramClient('fake', 42, opener=opener).send_message('test')
            self.assertEqual(caught.exception.retry_after, expected)
            self.assertFalse(caught.exception.fatal)

    def test_cooldown_blocks_early_requests_after_429(self):
        opener = opener_with({'ok': False, 'error_code': 429,
                              'parameters': {'retry_after': 30}}, 429)
        client = TelegramClient('fake', 42, opener=opener)
        with patch('telegram_client.time.monotonic', return_value=100):
            with self.assertRaises(TelegramError):
                client.send_message('first')
        with patch('telegram_client.time.monotonic', return_value=105):
            with self.assertRaises(TelegramError) as caught:
                client.get_updates(0)
        self.assertEqual(caught.exception.retry_after, 25)
        self.assertEqual(opener.open.call_count, 1)

    def test_updates_use_long_poll_timeout_and_offset(self):
        opener = opener_with({'ok': True, 'result': []})
        client = TelegramClient('fake', 42, opener=opener)
        self.assertEqual(client.get_updates(123, timeout=20), [])
        self.assertEqual(json.loads(opener.open.call_args.args[0].data),
                         {'offset': 123, 'timeout': 20, 'limit': 100, 'allowed_updates': ['message']})
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 30)

    def test_environment_validation_and_optional_chat_discovery(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ToolError):
                token_from_env()
            self.assertIsNone(chat_id_from_env(required=False))
        for value in ('@username', '0', '42\nsecret', 'not-an-id'):
            with patch.dict(os.environ, {'TELEGRAM_CHAT_ID': value}), self.assertRaises(ToolError):
                chat_id_from_env()
        with patch.dict(os.environ, {'TELEGRAM_CHAT_ID': '-100123', 'TELEGRAM_BOT_TOKEN': '123:fake'}):
            self.assertEqual(TelegramClient.from_env().chat_id, -100123)
        with patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': '123:secret/another-host'}):
            with self.assertRaises(ToolError):
                TelegramClient.from_env(require_chat=False)

    def test_secure_opener_refuses_redirects(self):
        handlers = secure_opener().handlers
        redirects = [handler for handler in handlers
                     if isinstance(handler, urllib.request.HTTPRedirectHandler)]
        self.assertEqual(len(redirects), 1)
        self.assertIsNone(redirects[0].redirect_request(None, None, 302, '', {}, 'https://other.example'))
