"""Exercise compression argument rejection over an isolated MCP stdio process."""

import json
import os
import sys
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_invalid_compress_input_returns_actionable_compact_error_over_mcp(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        '[server]\nport = 1\nauto_start_ollama = false\n', encoding="utf-8"
    )
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith("GIT_") and key not in {"LOCAL_AI_TENANT", "LOCAL_AI_HUB_TOKEN"}}
    env.update(LOCAL_AI_CONFIG=str(config),
               PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"),
               PYTHONDONTWRITEBYTECODE="1")
    params = StdioServerParameters(command=sys.executable, args=["-B", "-m", "local_ai_hub.mcp_server"],
                                   env=env, cwd=str(tmp_path))

    async def call():
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                result = await session.call_tool("local_ai_task", {
                    "action": "compress", "task": "preserve facts", "input": "source",
                    "response_profile": "minimal", "max_response_tokens": 256,
                })
                return json.loads(result.content[0].text)

    payload = anyio.run(call)
    assert payload["success"] is False
    assert payload["status_code"] == 400
    assert payload["terminal"] is True and payload["retryable"] is False
    assert "input" in payload["error"] and "text" in payload["error"]
    assert payload["response_budget"]["returned_tokens"] <= 256
