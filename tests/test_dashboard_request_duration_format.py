from __future__ import annotations

import shutil
import subprocess

import pytest

from local_ai_hub.dashboard import DASHBOARD_HTML
from local_ai_hub.process_utils import hidden_run_kwargs


def test_http_request_duration_formatter_preserves_fractional_milliseconds() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise dashboard formatting")

    start = DASHBOARD_HTML.index("const n=v=>")
    end = DASHBOARD_HTML.index(", durSec=", start)
    formatter = DASHBOARD_HTML[start:end]
    script = "\n".join(
        [
            "const assert=require('node:assert/strict');",
            formatter,
            "assert.equal(ms(0.4), '0.40 ms');",
            "assert.equal(ms(19.76), '19.8 ms');",
            "assert.equal(ms(1000), '1.00 s');",
        ]
    )
    result = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, timeout=5,
        **hidden_run_kwargs(),
    )
    assert result.returncode == 0, result.stderr or result.stdout
