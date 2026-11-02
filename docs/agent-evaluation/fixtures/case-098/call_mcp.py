"""Invoke only case 098 coordination actions against the isolated Hub."""
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
server = config.get("server", {})
security = config.get("security", {})
token = security.get("api_token")
if (server.get("bind") != "127.0.0.1"
        or type(server.get("port")) is not int
        or not 1024 <= server["port"] <= 65535
        or server["port"] in (11434, 11435)
        or Path(server.get("state_dir", "")).resolve() != (HERE / "state").resolve()
        or security.get("allowed_roots") != [WORKSPACE.as_posix()]
        or not isinstance(token, str) or len(token) < 32):
    raise SystemExit("fixture config does not describe this isolated token-protected Hub")
if len(sys.argv) != 2:
    raise SystemExit("usage: call_mcp.py JSON_ARGUMENTS")
arguments = json.loads(sys.argv[1])
allowed = {"task_create", "task_get", "task_list", "task_checkpoint", "verify_completion", "task_complete"}
if (not isinstance(arguments, dict) or arguments.get("action") not in allowed
        or Path(arguments.get("root", "")).resolve() != WORKSPACE):
    raise SystemExit("case 098 action and explicit fixture workspace root required")
env = os.environ.copy()
for key in ("LOCAL_AI_TENANT", "LOCAL_AI_HUB_TOKEN", "LOCAL_AI_AGENT", "LOCAL_AI_AGENT_PROFILE"):
    env.pop(key, None)
env.update(LOCAL_AI_CONFIG=str(CONFIG), LOCAL_AI_HUB_TOKEN=token,
           PYTHONPATH=str(SOURCE / "src"), PYTHONDONTWRITEBYTECODE="1")
params = StdioServerParameters(command=sys.executable, args=["-B", "-m", "local_ai_hub.mcp_server"], env=env, cwd=str(HERE))


async def run() -> None:
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            result = await session.call_tool("local_ai_coord", arguments)
            print(result.model_dump_json(exclude_none=True))


anyio.run(run)
