"""Narrow MCP client for the isolated case 081 Hub."""
import json
import os
import sys
import tomllib
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

here = Path(__file__).resolve().parent
config_path = here / "config.toml"
with config_path.open("rb") as file:
    cfg = tomllib.load(file)
server_cfg = cfg.get("server", {})
if (server_cfg.get("bind") != "127.0.0.1"
        or type(server_cfg.get("port")) is not int
        or server_cfg["port"] in (11434, 11435)
        or Path(server_cfg.get("state_dir", "")).resolve() != (here / "state").resolve()
        or cfg.get("security", {}).get("allowed_roots") != [(here / "workspace").resolve().as_posix()]):
    raise SystemExit("config does not describe this isolated Hub")
if len(sys.argv) != 3:
    raise SystemExit("usage: call_mcp.py TOOL JSON_ARGUMENTS")
tool, raw = sys.argv[1:]
args = json.loads(raw)
if not isinstance(args, dict) or (tool, args.get("action")) not in {
    ("local_ai_task", "batch"), ("local_ai_artifact", "get"), ("local_ai_artifact", "slice"),
}:
    raise SystemExit("only case 081 batch and artifact reads are permitted")
if tool == "local_ai_task":
    tasks = args.get("tasks")
    allowed = {"id", "task", "context", "task_type", "complexity", "prompt"}
    if not isinstance(tasks, list) or any(not isinstance(t, dict) or set(t) - allowed for t in tasks):
        raise SystemExit("unexpected batch item fields")
source = Path((here / "source.txt").read_text(encoding="utf-8")).resolve()
env = os.environ.copy()
for key in ("LOCAL_AI_TENANT", "LOCAL_AI_AGENT", "LOCAL_AI_AGENT_PROFILE"):
    env.pop(key, None)
env.update(LOCAL_AI_CONFIG=str(config_path), PYTHONPATH=str(source / "src"), PYTHONDONTWRITEBYTECODE="1")
params = StdioServerParameters(command=sys.executable, args=["-B", "-m", "local_ai_hub.mcp_server"], env=env, cwd=str(here))

async def run():
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            result = await session.call_tool(tool, args)
            print(result.model_dump_json(exclude_none=True))

anyio.run(run)
