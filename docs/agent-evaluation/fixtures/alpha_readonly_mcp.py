"""Query only the alpha fixture through its dedicated loopback MCP server."""

import json
import os
from pathlib import Path
import sys
import tomllib

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


HERE = Path(__file__).resolve().parent
WORKSPACE = (HERE / "workspace").resolve()
ROOT = (WORKSPACE / "repo").resolve()
CONFIG = HERE / "config.toml"
SOURCE = Path((HERE / "source.txt").read_text(encoding="utf-8")).resolve()
with CONFIG.open("rb") as file:
    config = tomllib.load(file)
server = config.get("server", {})
security = config.get("security", {})
preprocessing = config.get("preprocessing", {})
code_intelligence = config.get("code_intelligence", {})
if (server.get("bind") != "127.0.0.1"
        or type(server.get("port")) is not int
        or not 1024 <= server["port"] <= 65535
        or server["port"] in (11434, 11435)
        or Path(server.get("state_dir", "")).resolve() != (HERE / "state").resolve()
        or security.get("allowed_roots") != [WORKSPACE.as_posix()]
        or any(key in security for key in ("api_token", "supervisor_token", "action_tokens", "api_token_permissions"))
        or preprocessing.get("enabled") is not False
        or preprocessing.get("fs_watcher_enabled") is not False
        or code_intelligence.get("enabled") is not False
        or ROOT.parent != WORKSPACE or not ROOT.is_dir()
        or not (SOURCE / "src/local_ai_hub/mcp_server.py").is_file()):
    raise SystemExit("invalid isolated alpha Hub configuration")

if len(sys.argv) != 3 or sys.argv[1] not in {"repo", "artifact"}:
    raise SystemExit("usage: alpha_readonly_mcp.py repo|artifact JSON_ARGUMENTS")
kind = sys.argv[1]
arguments = json.loads(sys.argv[2])
allowed = {
    "repo": {"action", "query", "path", "limit", "offset", "response_profile", "max_response_tokens"},
    "artifact": {"action", "path", "line_start", "line_end", "response_profile", "max_response_tokens"},
}
actions = {"repo": {"search", "code_index"}, "artifact": {"source"}}
if not isinstance(arguments, dict) or arguments.get("action") not in actions[kind]:
    raise SystemExit("only bounded alpha search, code_index, and source actions are allowed")
if set(arguments) - allowed[kind]:
    valid = ", ".join(sorted(allowed[kind]))
    raise SystemExit(f"unsupported {kind} argument; allowed fields: {valid}")
arguments["root"] = str(ROOT)
env = {key: value for key, value in os.environ.items()
       if key not in {"LOCAL_AI_TENANT", "LOCAL_AI_AGENT", "LOCAL_AI_AGENT_PROFILE"}}
env.update(LOCAL_AI_CONFIG=str(CONFIG),
           PYTHONPATH=str(SOURCE / "src"), PYTHONDONTWRITEBYTECODE="1")
params = StdioServerParameters(command=sys.executable, args=["-B", "-m", "local_ai_hub.mcp_server"],
                               env=env, cwd=str(HERE))


async def run() -> None:
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            result = await session.call_tool("local_ai_" + kind, arguments)
            print(result.model_dump_json(exclude_none=True))


anyio.run(run)
