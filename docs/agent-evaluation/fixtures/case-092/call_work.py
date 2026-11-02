"""Restricted MCP client for one disposable case-092 work order."""
import json
import os
import sys
import tomllib
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

here = Path(__file__).resolve().parent
root = (here / "workspace" / "repo").resolve()
config = here / "config.toml"
source = Path((here / "source.txt").read_text(encoding="utf-8")).resolve()
with config.open("rb") as stream:
    cfg = tomllib.load(stream)
server = cfg.get("server", {})
if (server.get("bind") != "127.0.0.1" or server.get("port") != 61392
        or Path(server.get("state_dir", "")).resolve() != (here / "state").resolve()
        or cfg.get("security", {}).get("allowed_roots") != [(here / "workspace").resolve().as_posix()]):
    raise SystemExit("config does not describe the isolated case-092 state")
if len(sys.argv) != 2:
    raise SystemExit("usage: call_work.py JSON_ARGUMENTS")
arguments = json.loads(sys.argv[1])
if (not isinstance(arguments, dict) or arguments.get("action") not in {"submit", "wait", "get"}
        or Path(arguments.get("root", "")).resolve() != root):
    raise SystemExit("case-092 work action and exact fixture root required")
if arguments["action"] == "submit" and arguments.get("allowed_paths") != ["report.py"]:
    raise SystemExit("only report.py is authorized for the delegated edit")
if arguments["action"] == "submit":
    if arguments.get("mode") != "bounded":
        raise SystemExit("bounded mode is required to enforce fixture path and command scope")
    # Execute mode requires both validation capability flags; the sole command
    # remains explicitly limited below to this fixture's unit-test oracle.
    allowed_permissions = {"read": True, "edit": True, "tests": True, "build": True,
                           "network": False, "git_commit": False, "create": False, "delete": False}
    if arguments.get("permissions") != allowed_permissions:
        raise SystemExit("exact fixture permissions required")
    if arguments.get("approved_commands") != ["python -m unittest oracle_092"]:
        raise SystemExit("only the fixture oracle command is authorized")
    # Reserve before submit; an interrupted client cannot safely repeat it.
    with (here / "work-submit-once.marker").open("x", encoding="utf-8") as stream:
        stream.write("submit attempted; inspect sandbox work state before any further action\n")
env = os.environ.copy()
for key in ("LOCAL_AI_TENANT", "LOCAL_AI_HUB_TOKEN", "LOCAL_AI_AGENT", "LOCAL_AI_AGENT_PROFILE"):
    env.pop(key, None)
env.update(LOCAL_AI_CONFIG=str(config), PYTHONPATH=str(source / "src"), PYTHONDONTWRITEBYTECODE="1")
params = StdioServerParameters(command=sys.executable, args=["-B", "-m", "local_ai_hub.mcp_server"], env=env, cwd=str(here))


async def run():
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            result = await session.call_tool("local_ai_work", arguments)
            print(result.model_dump_json(exclude_none=True))


anyio.run(run)
