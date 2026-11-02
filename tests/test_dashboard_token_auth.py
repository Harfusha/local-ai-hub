import shutil
import subprocess

import pytest

from local_ai_hub.dashboard import DASHBOARD_HTML


def test_dashboard_auth_header_is_scoped_to_secure_same_origin_api():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to execute the dashboard JavaScript")
    start = DASHBOARD_HTML.index("function dashboardAuthenticatedHeaders(")
    end = DASHBOARD_HTML.index("\nasync function apiFetch(", start)
    function = DASHBOARD_HTML[start:end]
    script = function + r"""
const assert = require('node:assert/strict');
const base = 'http://127.0.0.1:61298/dashboard';
const auth = (path, token='example-token', secure=true, headers={}) =>
  dashboardAuthenticatedHeaders(path, headers, token, base, secure).get('Authorization');
assert.equal(auth('/api/agent-state/tasks'), 'Bearer example-token');
assert.equal(auth('http://127.0.0.1:61298/api/status'), 'Bearer example-token');
assert.equal(auth('http://127.0.0.1:61299/api/status'), null);
assert.equal(auth('https://example.org/api/status'), null);
assert.equal(auth('/health'), null);
assert.equal(auth('/api/status', 'example-token', false), null);
assert.equal(auth('/api/status', ''), null);
assert.equal(auth('/api/status', 'example-token', true, {Authorization: 'Bearer explicit'}), 'Bearer explicit');
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
