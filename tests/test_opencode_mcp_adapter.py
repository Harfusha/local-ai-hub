import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


def test_malformed_mcp_response_closes_adapter(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    package = tmp_path / "local_ai_hub"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "mcp_server.py").write_text("import sys\nsys.stdin.readline()\nprint('not-json', flush=True)\n", encoding="utf-8")
    module = (Path(__file__).resolve().parents[1] / "tools" / "opencode_mcp" / "index.js").as_uri()
    config = {"command": [sys.executable, "-m", "local_ai_hub.mcp_server"], "cwd": str(tmp_path), "environment": {"PYTHONPATH": str(tmp_path)}}
    script = '''
      import {openMcp} from process.env.ADAPTER_MODULE;
      const client = openMcp(JSON.parse(process.env.ADAPTER_CONFIG));
      let first = false, second = false;
      try { await client.request("initialize", {}); } catch (e) { first = /invalid MCP response/.test(e.message); }
      try { await client.request("tools/list", {}); } catch (e) { second = /unavailable/.test(e.message); }
      client.stop();
      if (!first || !second) process.exitCode = 1;
    '''
    # Dynamic import is required because static import specifiers are literals.
    script = script.replace('import {openMcp} from process.env.ADAPTER_MODULE;', 'const {openMcp} = await import(process.env.ADAPTER_MODULE);')
    result = subprocess.run([node, "--input-type=module", "-e", script],
                            env={**os.environ, "ADAPTER_MODULE": module, "ADAPTER_CONFIG": json.dumps(config)},
                            capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr[-2000:]
