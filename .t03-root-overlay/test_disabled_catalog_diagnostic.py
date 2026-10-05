import json
import os
import subprocess
import sys
from pathlib import Path
import pytest


@pytest.mark.parametrize("disabled_feature", ["rag", "commands"])
def test_disabled_catalog_diagnostic(tmp_path, disabled_feature):
    root = Path(r"C:\Users\Adam\.local-ai-hub")
    config = tmp_path / "disabled-features.toml"
    config.write_text(f"[features]\n{disabled_feature} = false\n", encoding="utf-8")
    env = os.environ.copy()
    env["LOCAL_AI_CONFIG"] = str(config)
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(root / "src"), env.get("PYTHONPATH", "")) if value
    )
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "disabled-schema-test", "version": "1"},
        }},
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    completed = subprocess.run(
        [sys.executable, "-B", "-c", "from local_ai_hub import mcp_server; "
         "mcp_server.CLIENT.ensure_server = lambda **_kwargs: True; mcp_server.main()"],
        cwd=root, env=env,
        input="".join(json.dumps(message, separators=(",", ":")) + "\n" for message in messages),
        capture_output=True, text=True, timeout=15, check=False,
    )
    state = subprocess.run(
        [sys.executable, "-B", "-c", "from local_ai_hub import mcp_server; "
         "print('disabled=' + repr(mcp_server.FEATURES.disabled_tools)); "
         "print('registered=' + repr(sorted(mcp_server.mcp._tool_manager._tools)))"],
        cwd=root, env=env, capture_output=True, text=True, timeout=15, check=False,
    )
    responses = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    assert any(response.get("id") == 2 for response in responses), (
        f"returncode={completed.returncode}; stdout={completed.stdout!r}; "
        f"stderr={completed.stderr[-2000:]!r}; state={state.stdout!r}; state_err={state.stderr[-1000:]!r}"
    )
