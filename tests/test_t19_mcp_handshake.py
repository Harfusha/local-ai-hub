from __future__ import annotations

import os
import sys
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("auto_start_ollama", "expected_tools"),
    [
        pytest.param(
            False,
            {
                "local_ai_artifact",
                "local_ai_coord",
                "local_ai_rag",
                "local_ai_repo",
                "local_ai_status",
            },
            id="models-disabled",
        ),
        pytest.param(
            True,
            {
                "local_ai_artifact",
                "local_ai_coord",
                "local_ai_rag",
                "local_ai_repo",
                "local_ai_status",
                "local_ai_task",
                "local_ai_work",
            },
            id="models-enabled",
        ),
    ],
)
def test_local_mcp_server_completes_stdio_initialize_and_tools_list(
    tmp_path: Path, auto_start_ollama: bool, expected_tools: set[str]
) -> None:
    state_dir = tmp_path / "state"
    install_dir = tmp_path / "install"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            (
                "[server]",
                'bind = "127.0.0.1"',
                "port = 59992",
                f'auto_start_ollama = {str(auto_start_ollama).lower()}',
                f'state_dir = "{state_dir.as_posix()}"',
                "[setup]",
                f'install_dir = "{install_dir.as_posix()}"',
                "",
            )
        ),
        encoding="utf-8",
    )

    async def handshake() -> tuple[str, list[str]]:
        env = os.environ.copy()
        source_path = str(ROOT / "src")
        env["PYTHONPATH"] = os.pathsep.join(filter(None, (source_path, env.get("PYTHONPATH", ""))))
        env["LOCAL_AI_CONFIG"] = str(config_path)
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "local_ai_hub.mcp_server"],
            env=env,
        )
        with anyio.fail_after(20):
            async with stdio_client(server) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    initialized = await session.initialize()
                    listed = await session.list_tools()
                    return initialized.serverInfo.name, [tool.name for tool in listed.tools]

    server_name, tool_names = anyio.run(handshake)

    assert server_name == "Local AI Hub (compact)"
    assert set(tool_names) == expected_tools
