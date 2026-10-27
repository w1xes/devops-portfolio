"""Telegram Bot API client: verified HTTPS, bounded replies, no secret-bearing errors."""
import http.client
import json
import math
import os
import re
import ssl
import time
import urllib.error
import urllib.request

from toolkit_common import ToolError

API_BASE = 'https://api.telegram.org'
FAILURES = {
    'dns': 'DNS: не вдалося визначити адресу',
    'connection_refused': 'З’єднання відхилено',
    'timeout': 'Тайм-аут',
    'certificate': 'Помилка TLS-сертифіката',
    'unexpected_status': 'Неочікуваний HTTP-код',
    'slow_response': 'Повільна відповідь',
    'network': 'Інша мережева помилка',
}


class TelegramError(Exception):
    """Only safe, fixed strings; never keep the URL, token or raw API response."""
    def __init__(self, reason, *, retry_after=5):
        super().__init__(f'Telegram: {reason}')
        self.reason = reason
        self.retry_after = retry_after

    @property
    def fatal(self):
        return self.reason in {'unauthorized', 'forbidden', 'polling_conflict'}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Tokens are in Telegram request paths. Never forward them to another host.
        return None


def secure_opener():
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()), NoRedirect())


def chat_id_from_env(required=True):
    value = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    if not value and not required:
        return None
    if not re.fullmatch(r'-?[1-9][0-9]{0,19}', value):
        raise ToolError('Set TELEGRAM_CHAT_ID to the numeric chat ID (not @username)', 2)
    return int(value)


def token_from_env():
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    if not token:
        raise ToolError('Set TELEGRAM_BOT_TOKEN securely in the environment', 2)
    # Validate path safety, without assuming a raw token instead of a proxy binding.
    if len(token) > 512 or not re.fullmatch(r'[A-Za-z0-9:_-]+', token):
        raise ToolError('TELEGRAM_BOT_TOKEN contains invalid path characters', 2)
    return token


def split_text(text, limit=3500):
    """Plain text chunks below Telegram's 4096 limit, including UTF-16 surrogates."""
    chunk, units = [], 0
    for char in text:
        width = 2 if ord(char) > 0xFFFF else 1
        if units + width > limit:
            yield ''.join(chunk)
            chunk, units = [], 0
        chunk.append(char)
        units += width
    if chunk:
        yield ''.join(chunk)


class TelegramClient:
    def __init__(self, token, chat_id=None, *, opener=None):
        self._token = token
        self.chat_id = chat_id
        self.opener = opener or secure_opener()
        self._not_before = 0.0

    @classmethod
    def from_env(cls, *, require_chat=True):
        return cls(token_from_env(), chat_id_from_env(require_chat))

    def call(self, method, payload=None, *, timeout=15):
        remaining = math.ceil(self._not_before - time.monotonic())
        if remaining > 0:
            raise TelegramError('rate_limited', retry_after=remaining)
        if method not in {'getMe', 'getUpdates', 'sendMessage', 'getWebhookInfo', 'setMyCommands'}:
            raise TelegramError('unsupported_method')
        request = urllib.request.Request(
            f'{API_BASE}/bot{self._token}/{method}', method='POST',
            data=json.dumps(payload or {}, ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type': 'application/json', 'User-Agent': 'devops-lab03/telegram'})
        status = None
        raw = b''
        failed_transport = False
        # Do not raise while a token-bearing urllib exception is active: that would
        # attach a secret-bearing exception as __context__ to the safe error.
        try:
            with self.opener.open(request, timeout=timeout) as response:
                status = response.status
                raw = response.read(1_048_577)
        except urllib.error.HTTPError as exc:
            status = exc.code
            try:
                raw = exc.read(1_048_577)
            except (OSError, http.client.HTTPException):
                raw = b''
            finally:
                exc.close()
        except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError):
            failed_transport = True
        if failed_transport:
            raise TelegramError('network_error')
        if len(raw) > 1_048_576:
            raise TelegramError('oversized_response')
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeError):
            body = None
        error_code = body.get('error_code') if isinstance(body, dict) else status
        if status == 429 or error_code == 429:
            parameters = body.get('parameters', {}) if isinstance(body, dict) else {}
            delay = parameters.get('retry_after', 5) if isinstance(parameters, dict) else 5
            delay = max(1, min(delay, 300)) if type(delay) is int else 5
            self._not_before = time.monotonic() + delay
            raise TelegramError('rate_limited', retry_after=delay)
        reasons = {401: 'unauthorized', 403: 'forbidden', 409: 'polling_conflict'}
        reason = reasons.get(status) or (reasons.get(error_code) if type(error_code) is int else None)
        if reason:
            raise TelegramError(reason)
        if status is None or not 200 <= status < 300:
            raise TelegramError('http_error')
        if not isinstance(body, dict) or body.get('ok') is not True or 'result' not in body:
            raise TelegramError('invalid_response')
        return body['result']

    def send_message(self, text):
        if self.chat_id is None:
            raise TelegramError('chat_not_configured')
        if not isinstance(text, str) or not text:
            raise TelegramError('empty_message')
        for chunk in split_text(text):
            result = self.call('sendMessage', {
                'chat_id': self.chat_id, 'text': chunk,
                'link_preview_options': {'is_disabled': True},
            })
            if not isinstance(result, dict) or type(result.get('message_id')) is not int:
                raise TelegramError('invalid_message_response')
        return True

    def get_updates(self, offset, timeout=20):
        result = self.call('getUpdates', {
            'offset': offset, 'timeout': timeout, 'limit': 100, 'allowed_updates': ['message'],
        }, timeout=timeout + 10)
        if not isinstance(result, list):
            raise TelegramError('invalid_updates')
        return result


def format_alert(result, *, recovered=False):
    title = '✅ API відновився' if recovered else '🚨 Проблема API'
    failure = result.get('failure_type')
    description = FAILURES.get(failure, failure or 'Норма')
    return (f"{title}: {result['target']}\n"
            f"Тип: {failure or 'healthy'} — {description}\n"
            f"HTTP: {result.get('status') if result.get('status') is not None else 'немає відповіді'}\n"
            f"Час: {result.get('response_ms')} мс\n"
            f"Спроб: {result.get('attempts', 1)}\n"
            f"Перевірено (UTC): {result.get('time', 'невідомо')}")
