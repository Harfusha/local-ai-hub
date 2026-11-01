import asyncio
import json
import os
from pathlib import Path
import sys

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


@pytest.mark.parametrize("agent,profile", [("opencode-local", "opencode-local"), ("codex", "codex"), ("codex", "opencode-local")])
def test_opencode_local_hides_generative_tools_without_changing_other_clients(tmp_path, agent, profile):
    config = tmp_path / "config.toml"
    config.write_text(
        f'[server]\nstate_dir = "{(tmp_path / "state").as_posix()}"\n'
        'port = 21435\nauto_start_ollama = false\n[ollama]\nenabled = true\n',
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("LOCAL_AI_TENANT", None)
    env.update({
        "LOCAL_AI_AGENT": agent,
        "LOCAL_AI_AGENT_PROFILE": profile,
        "LOCAL_AI_CONFIG": str(config),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
    })
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "local_ai_hub.mcp_server"], env=env, cwd=str(tmp_path),
    )

    async def exercise():
        async with asyncio.timeout(30):
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    names = {tool.name for tool in (await session.list_tools()).tools}
                    assert {"local_ai_status", "local_ai_repo", "local_ai_rag", "local_ai_coord", "local_ai_artifact"} <= names
                    if profile == "opencode-local":
                        assert "local_ai_task" not in names
                        assert "local_ai_work" not in names
                        for tool in ("local_ai_task", "local_ai_work"):
                            result = await session.call_tool(tool, {"action": "reason"})
                            body = result.structuredContent or json.loads(result.content[0].text)
                            assert body["success"] is False
                            assert body["error_code"] == "profile_tool_disabled"
                    else:
                        assert {"local_ai_task", "local_ai_work"} <= names

    asyncio.run(exercise())
