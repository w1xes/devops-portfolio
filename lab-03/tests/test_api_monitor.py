"""Real local HTTP, retry counts, TLS, and Slack payload contracts."""
import contextlib
import json
import os
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import api_monitor as api


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        import time
        if self.path == '/slow':
            time.sleep(0.08)
        self.send_response(503 if self.path == '/error' else 200)
        self.end_headers()
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(b'ok')

    def do_POST(self):
        self.server.payloads.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
        self.send_response(200)
        self.end_headers()


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.server.payloads = []
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patcher = patch.dict(os.environ, {'TOOLKIT_LOG': str(self.root / 'audit.jsonl')})
        patcher.start()
        self.addCleanup(patcher.stop)

    def target(self, path='/', **kwargs):
        return {'name': 'local', 'url': self.url + path, 'expected_status': 200,
                'timeout': 1, 'threshold_ms': 1000, **kwargs}

    def test_real_http_healthy_status_slow_and_timeout(self):
        opener = api.make_opener(True)
        for target, failure in [(self.target(), None),
                                (self.target('/error'), 'unexpected_status'),
                                (self.target('/slow', threshold_ms=1), 'slow_response'),
                                (self.target('/slow', timeout=0.01), 'timeout')]:
            with self.subTest(failure=failure):
                result = api.check_target(target, opener)
                self.assertEqual(result['failure_type'], failure)
                self.assertEqual(result['attempts'], 2 if failure == 'timeout' else 1)

    def test_four_distinct_failures_with_one_retry_on_network_errors(self):
        failures = [(socket.gaierror(-2, 'not known'), 'dns'),
                    (ConnectionRefusedError(111, 'refused'), 'connection_refused'),
                    (ssl.SSLCertVerificationError(1, 'expired'), 'certificate')]
        for error, expected in failures:
            with self.subTest(expected=expected):
                opener = unittest.mock.Mock()
                opener.open.side_effect = urllib.error.URLError(error)
                result = api.check_target(self.target(), opener)
                self.assertEqual(result['failure_type'], expected)
                self.assertEqual(opener.open.call_count, 2)
        result = api.check_target(self.target('/error'), api.make_opener(True))
        self.assertEqual(result['failure_type'], 'unexpected_status')
        log = (self.root / 'audit.jsonl').read_text()
        for name in ('dns', 'connection_refused', 'certificate', 'unexpected_status'):
            self.assertIn(f'"failure_type": "{name}"', log)

    def test_connection_refused_real_socket(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
            # Bound but not listening: port cannot be allocated by another test.
            result = api.check_target(self.target(url=f'http://127.0.0.1:{port}'), api.make_opener(True))
        self.assertEqual(result['failure_type'], 'connection_refused')

    def test_slack_payload_to_local_receiver(self):
        result = {'target': 'local', 'failure_type': 'dns', 'status': None, 'response_ms': 2}
        self.assertTrue(api.notify(result, self.url, api.make_opener(True)))
        self.assertIn('type=dns', self.server.payloads[-1]['text'])
        self.assertIn('local', self.server.payloads[-1]['text'])

    def test_cli_report_and_missing_webhook(self):
        config = self.root / 'config.json'
        config.write_text(json.dumps({'targets': [self.target('/error')]}))
        output = self.root / 'results.json'
        env = {k: v for k, v in os.environ.items() if k != 'API_MONITOR_WEBHOOK'}
        result = subprocess.run(['python3', str(Path(api.__file__)), '--config', str(config),
                                 '--output', str(output), '--direct'], env=env,
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertEqual(json.loads(output.read_text())[0]['notification'], 'missing_webhook')
        self.assertNotIn('Traceback', result.stderr)

    def test_exit_codes_and_healthy_report(self):
        config = self.root / 'config.json'
        output = self.root / 'results.json'
        for target, expected in ((self.target(), 0), (self.target('/error'), 14),
                                 (self.target('/slow', threshold_ms=1), 15)):
            config.write_text(json.dumps({'targets': [target]}))
            result = subprocess.run(['python3', str(Path(api.__file__)), '--config', str(config),
                                     '--output', str(output), '--direct', '--no-notify'],
                                    text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, expected, result.stderr)
            self.assertEqual(json.loads(output.read_text())[0]['healthy'], expected == 0)

    def test_validation_rejects_nan_bool_and_bad_urls(self):
        for change in ({'timeout': float('nan')}, {'expected_status': True},
                       {'url': 'https://user:secret@example.com'}, {'threshold_ms': -1}):
            path = self.root / 'bad.json'
            path.write_text(json.dumps({'targets': [self.target(**change)]}))
            with self.assertRaises(api.ToolError):
                api.load_config(path)

    def test_real_untrusted_tls_certificate(self):
        # Locally generate a cert; keep verification enabled in the actual request.
        key, cert = self.root / 'key.pem', self.root / 'cert.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', str(key), '-out', str(cert), '-days', '1',
                        '-subj', '/CN=localhost'], check=True, capture_output=True)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = api.check_target(self.target(url=f'https://127.0.0.1:{server.server_port}'),
                                      api.make_opener(True))
            self.assertEqual(result['failure_type'], 'certificate')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
