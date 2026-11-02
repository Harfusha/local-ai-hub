"""Call the explicitly configured isolated MCP server with unchanged JSON types."""
from __future__ import annotations

import json
import os
import sys
import tomllib
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = Path(__file__).resolve().parent
WORKSPACE = (HERE / "workspace").resolve()
CONFIG = HERE / "config.toml"
SOURCE = Path((HERE / "source.txt").read_text(encoding="utf-8")).resolve()
with CONFIG.open("rb") as file:
    config = tomllib.load(file)
server_config = config.get("server", {})
security = config.get("security", {})
if (server_config.get("bind") != "127.0.0.1"
        or type(server_config.get("port")) is not int
        or not 1024 <= server_config["port"] <= 65535
        or server_config["port"] == 11435
        or Path(server_config.get("state_dir", "")).resolve() != (HERE / "state").resolve()
        or security.get("allowed_roots") != [str(WORKSPACE).replace("\\", "/")]):
    raise SystemExit("fixture config does not describe this isolated state and workspace")
if len(sys.argv) != 3:
    raise SystemExit("usage: call_mcp.py TOOL JSON_ARGUMENTS")
tool, raw = sys.argv[1:]
arguments = json.loads(raw)
if not isinstance(arguments, dict) or (tool, arguments.get("action")) not in {
    ("local_ai_coord", "task_create"), ("local_ai_coord", "task_get"),
    ("local_ai_coord", "task_list"), ("local_ai_repo", "search"),
}:
    raise SystemExit("only case 076 task actions and read-only search are permitted")
if Path(arguments.get("root", "")).resolve() != WORKSPACE:
    raise SystemExit("explicit fixture workspace root required")
env = os.environ.copy()
for key in ("LOCAL_AI_TENANT", "LOCAL_AI_HUB_TOKEN", "LOCAL_AI_AGENT", "LOCAL_AI_AGENT_PROFILE"):
    env.pop(key, None)
env.update(LOCAL_AI_CONFIG=str(CONFIG), PYTHONPATH=str(SOURCE / "src"), PYTHONDONTWRITEBYTECODE="1")
server = StdioServerParameters(command=sys.executable, args=["-B", "-m", "local_ai_hub.mcp_server"], env=env, cwd=str(HERE))


async def run() -> None:
    async with stdio_client(server) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            result = await session.call_tool(tool, arguments)
            print(result.model_dump_json(exclude_none=True))


anyio.run(run)
