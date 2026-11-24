"""Run the entire polling bot as a process against a real, trusted local TLS API."""
import json
import os
import signal
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKEN = '123:fake-e2e-secret'


class BotAPIHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.target_requests += 1
        self.send_response(503 if self.server.target_requests == 1 else 200)
        self.end_headers()
        self.wfile.write(b'API response')

    def do_POST(self):
        method = self.path.rsplit('/', 1)[-1]
        if not self.path.startswith(f'/bot{TOKEN}/'):
            self.send_error(404)
            return
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.calls.append((method, body))
        if method == 'getMe':
            result = {'id': 123, 'is_bot': True, 'username': 'devops_e2e_bot'}
        elif method == 'getWebhookInfo':
            result = {'url': ''}
        elif method == 'setMyCommands':
            result = True
        elif method == 'getUpdates':
            result = [update for update in self.server.updates if update['update_id'] >= body['offset']]
        elif method == 'sendMessage':
            self.server.messages.append(body)
            result = {'message_id': len(self.server.messages)}
        else:
            self.send_error(400)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'ok': True, 'result': result}).encode())


class TelegramE2ETests(unittest.TestCase):
    def test_real_https_polling_commands_alert_recovery_and_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key, cert = root / 'key.pem', root / 'cert.pem'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                            '-keyout', str(key), '-out', str(cert), '-days', '1',
                            '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost'],
                           capture_output=True, check=True)
            server = ThreadingHTTPServer(('127.0.0.1', 0), BotAPIHandler)
            server.calls, server.messages, server.target_requests = [], [], 0
            commands = ['/check', '/start', '/check', '/interval 10', '/pause',
                        '/status', '/resume', '/targets', '/chatid', '/help']
            server.updates = [
                {'update_id': index + 1, 'message': {'chat': {'id': 999 if index == 0 else 42,
                                                            'type': 'private'}, 'text': command}}
                for index, command in enumerate(commands)]
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            config, state, report = root / 'api.json', root / 'state.json', root / 'report.json'
            config.write_text(json.dumps({'targets': [
                {'name': 'local', 'url': f'https://localhost:{server.server_port}/api',
                 'expected_status': 200, 'timeout': 1, 'threshold_ms': 1000}]}))
            env = {key: value for key, value in os.environ.items()
                   if key.lower() not in {'http_proxy', 'https_proxy', 'all_proxy'}}
            env.update(SSL_CERT_FILE=str(cert), TELEGRAM_BOT_TOKEN=TOKEN,
                       TELEGRAM_CHAT_ID='42', TOOLKIT_LOG=str(root / 'audit.jsonl'),
                       PYTHONPATH=str(ROOT))
            runner = ('import runpy,sys,telegram_client; telegram_client.API_BASE=sys.argv[1]; '
                      'sys.argv=sys.argv[2:]; runpy.run_path(sys.argv[0], run_name="__main__")')
            with (root / 'console.txt').open('w') as console:
                process = subprocess.Popen([
                    'python3', '-c', runner, f'https://localhost:{server.server_port}',
                    str(ROOT / 'telegram_bot.py'), '--config', str(config), '--state', str(state),
                    '--output', str(report), '--interval', '60', '--direct'],
                    env=env, stdout=console, stderr=console)
                try:
                    deadline = time.monotonic() + 15
                    completed = False
                    while time.monotonic() < deadline and process.poll() is None:
                        if state.exists() and json.loads(state.read_text()).get('offset') == 11:
                            completed = True
                            break
                        threading.Event().wait(0.05)
                    self.assertTrue(completed, (root / 'console.txt').read_text())
                    process.send_signal(signal.SIGTERM)
                    self.assertEqual(process.wait(timeout=10), 0)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)
                    server.shutdown()
                    server.server_close()
                    thread.join()
            messages = server.messages
            self.assertTrue(all(message['chat_id'] == 42 for message in messages))
            self.assertEqual(sum('🚨 Проблема API' in message['text'] for message in messages), 1)
            self.assertEqual(sum('✅ API відновився' in message['text'] for message in messages), 1)
            self.assertTrue(any('Інтервал: 10 с.' in message['text'] for message in messages))
            self.assertTrue(any('Автоперевірки призупинено' in message['text'] for message in messages))
            saved = json.loads(state.read_text())
            self.assertTrue(saved['enabled'])
            self.assertEqual(saved['interval'], 10)
            self.assertGreaterEqual(server.target_requests, 2)
            self.assertTrue(json.loads(report.read_text())[0]['healthy'])
            for file in (root / 'audit.jsonl', root / 'console.txt', state, report):
                self.assertNotIn(TOKEN, file.read_text())
