#!/usr/bin/env python3
"""Reproduce four distinct API failure types without public test services."""
import argparse
import json
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from toolkit_common import ToolError, audit, entrypoint


class WrongStatusHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(418)
        self.end_headers()


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        'Example: python3 lab-03/demo_api.py --output-dir lab-03/var/demo. '
        'Requires openssl; keeps TLS verification enabled, trusts only a generated '
        'ephemeral CA with an expired leaf certificate. Environment: TOOLKIT_LOG. Exit: 0 expected failures '
        'verified, 2 arguments, 3 I/O, 4 unexpected result.'))
    parser.add_argument('--output-dir', type=Path, required=True, help='Directory for results and audit')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='lab03-tls-') as directory:
        root = Path(directory)
        key, csr, cert = [root / name for name in ('key.pem', 'req.pem', 'cert.pem')]
        ca_key, ca_cert = root / 'ca.key', root / 'ca.pem'
        (root / 'index.txt').write_text('')
        (root / 'serial').write_text('1000\n')
        ca_config = root / 'ca.cnf'
        ca_config.write_text(f"""[ca]
default_ca=local
[local]
database={root}/index.txt
new_certs_dir={root}
serial={root}/serial
private_key={ca_key}
certificate={ca_cert}
default_md=sha256
policy=names
x509_extensions=server
[names]
commonName=supplied
[server]
subjectAltName=DNS:localhost,IP:127.0.0.1
basicConstraints=CA:FALSE
extendedKeyUsage=serverAuth
""")
        commands = [
            ['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
             '-keyout', str(ca_key), '-out', str(ca_cert), '-days', '1',
             '-subj', '/CN=Lab ephemeral CA', '-addext', 'basicConstraints=critical,CA:TRUE'],
            ['openssl', 'req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(key),
             '-out', str(csr), '-subj', '/CN=localhost'],
            ['openssl', 'ca', '-batch', '-config', str(ca_config), '-in', str(csr),
             '-out', str(cert), '-startdate', '20200101000000Z', '-enddate', '20200102000000Z'],
        ]
        for command in commands:
            completed = subprocess.run(command, capture_output=True, check=False)
            if completed.returncode:
                raise ToolError('OpenSSL could not generate an expired test certificate', 3)
        verification = subprocess.run(['openssl', 'verify', '-CAfile', str(ca_cert), str(cert)],
                                      capture_output=True, text=True, check=False,
                                      env={**os.environ, 'LC_ALL': 'C'})
        if verification.returncode == 0 or 'certificate has expired' not in verification.stderr:
            raise ToolError('Test certificate is not demonstrably expired', 4)
        audit('demo_certificate', result='expired_confirmed')
        http = ThreadingHTTPServer(('127.0.0.1', 0), WrongStatusHandler)
        https = ThreadingHTTPServer(('127.0.0.1', 0), WrongStatusHandler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        https.socket = context.wrap_socket(https.socket, server_side=True)
        threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (http, https)]
        for thread in threads:
            thread.start()
        try:
            with socket.socket() as refused:
                refused.bind(('127.0.0.1', 0))  # Hold the port without listening.
                urls = {
                    'dns': 'http://does-not-exist.invalid',
                    'connection_refused': f'http://127.0.0.1:{refused.getsockname()[1]}',
                    'certificate': f'https://localhost:{https.server_port}',
                    'unexpected_status': f'http://127.0.0.1:{http.server_port}',
                }
                config = args.output_dir / 'targets.json'
                report = args.output_dir / 'results.json'
                config.write_text(json.dumps({'targets': [
                    {'name': name, 'url': url, 'expected_status': 200, 'timeout': 1,
                     'threshold_ms': 1000} for name, url in urls.items()]}, indent=2) + '\n')
                env = {**os.environ, 'SSL_CERT_FILE': str(ca_cert),
                       'TOOLKIT_LOG': str(args.output_dir / 'api-audit.jsonl')}
                completed = subprocess.run([
                    sys.executable, str(Path(__file__).parent / 'api_monitor.py'),
                    '--config', str(config), '--output', str(report), '--direct', '--no-notify'],
                    env=env, text=True, capture_output=True, check=False)
                print(completed.stdout, end='')
                (args.output_dir / 'console.txt').write_text(completed.stdout + completed.stderr)
                if completed.returncode != 1 or not report.is_file():
                    raise ToolError('Demo monitor did not produce the expected unhealthy report', 4)
                results = json.loads(report.read_text())
                for result in results:
                    if result['target'] != result['failure_type']:
                        raise ToolError('Unexpected classification; inspect demo results', 4)
                audit('api_demo', result='success', distinct_failures=len(results))
        finally:
            for server in (http, https):
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join()
    return 0


if __name__ == '__main__':
    raise SystemExit(entrypoint('api_demo', main))
