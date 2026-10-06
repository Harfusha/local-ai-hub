from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = Path(r'C:\Users\Adam\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe')
sys.path.insert(0, str(ROOT / 'src'))

from local_ai_hub.app import LocalAIApp
from local_ai_hub import http_server


class RegisteredHandler(http_server.Handler):
    def do_GET(self):
        if self.path == '/_test/artifacts':
            body = json.dumps({'artifact_ids': [item['artifact_id'] for item in self.server.app.artifacts.list(limit=100)]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def do_POST(self):
        if self.path == '/_test/origin':
            length = int(self.headers.get('Content-Length', '0'))
            payload = json.loads(self.rfile.read(length).decode('utf-8'))
            origin = str(payload.get('origin', ''))
            if not origin.startswith('chrome-extension://'):
                self.send_error(400)
                return
            self.server.app.config['browser_bridge']['allowed_origins'] = [origin]
            body = json.dumps({'success': True}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_POST()


with tempfile.TemporaryDirectory(prefix='t17-registered-handler-') as temp:
    temp_path = Path(temp)
    config = temp_path / 'config.toml'
    config.write_text(
        '\n'.join([
            '[server]', 'bind = "127.0.0.1"', 'port = 11435',
            f'state_dir = "{(temp_path / "state").as_posix()}"',
            '[browser_bridge]', 'enabled = true', 'allowed_origins = ["chrome-extension://pending"]',
            'max_payload_bytes = 2000000',
        ]), encoding='utf-8')
    app = LocalAIApp(str(config))
    previous = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(('127.0.0.1', 0), RegisteredHandler)
    server.app = app
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env = os.environ.copy()
        env['T17_HANDLER_URL'] = f'http://127.0.0.1:{server.server_address[1]}'
        run = subprocess.run([str(NODE), str(ROOT / 'handoff' / 't17-browser-registered-handler-e2e.mjs')],
                             cwd=ROOT, env=env, text=True, capture_output=True, timeout=90)
        if run.stdout:
            print(run.stdout.strip())
        if run.returncode:
            print(run.stderr[-2000:], file=sys.stderr)
            raise SystemExit(run.returncode)
        lines = [line for line in run.stdout.splitlines() if line.startswith('T17_HANDLER_RESULT=')]
        if not lines:
            raise SystemExit('missing Node E2E result receipt')
        result = json.loads(lines[-1].split('=', 1)[1])
        artifacts = app.artifacts.list(limit=100)
        ids = {item['artifact_id'] for item in artifacts}
        committed = result['positive'].get('bundle_artifact_id')
        assert result['negative']['success'] is False
        assert result['negative']['error_code'] == 'permission_denied'
        assert committed and committed in ids
        assert result['negative_artifact_ids'] == []
        expected_ids = {
            result['positive'][key] for key in (
                'bundle_artifact_id', 'screenshot_artifact_id', 'dom_artifact_id',
                'accessibility_artifact_id', 'computed_styles_artifact_id', 'runtime_artifact_id',
            )
        }
        assert ids == expected_ids, f"expected positive capture's six artifacts, got {len(ids)}"
        stored = app.artifacts.get(committed)
        assert stored.get('success') is True
        print(json.dumps({'registered_handler': 'PASS', 'activeTab_negative': 'PASS',
                          'positive_all_urls_stage_commit': 'PASS', 'artifact_count': len(ids),
                          'bundle_artifact_id': committed, 'store_receipt': 'PASS'}, sort_keys=True))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        http_server.APP = previous
        app.close()
