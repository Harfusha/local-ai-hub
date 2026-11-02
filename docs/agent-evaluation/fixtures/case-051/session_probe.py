"""Issue one compact and one delta context request in one isolated MCP session."""
from __future__ import annotations

import hashlib
import argparse
import json
import os
import sys
import tomllib
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = Path(__file__).resolve().parent
ROOT = (HERE / "workspace").resolve()
CONFIG = HERE / "config.toml"
SOURCE = Path((HERE / "source.txt").read_text(encoding="utf-8")).resolve()
with CONFIG.open("rb") as stream:
    cfg = tomllib.load(stream)
server, security = cfg.get("server", {}), cfg.get("security", {})
if (server.get("bind") != "127.0.0.1" or type(server.get("port")) is not int
        or not 1024 <= server["port"] <= 65535 or server["port"] in (11434, 11435)
        or Path(server.get("state_dir", "")).resolve() != (HERE / "state").resolve()
        or security.get("allowed_roots") != [ROOT.as_posix()]):
    raise SystemExit("fixture config does not match the isolated root and state")

env = os.environ.copy()
for key in ("LOCAL_AI_TENANT", "LOCAL_AI_HUB_TOKEN", "LOCAL_AI_AGENT", "LOCAL_AI_AGENT_PROFILE"):
    env.pop(key, None)
env.update(LOCAL_AI_CONFIG=str(CONFIG), PYTHONPATH=str(SOURCE / "src"), PYTHONDONTWRITEBYTECODE="1")
params = StdioServerParameters(command=sys.executable, args=["-B", "-m", "local_ai_hub.mcp_server"], env=env, cwd=str(HERE))
paths = [SOURCE / "src" / "local_ai_hub" / name for name in ("mcp_server.py", "response_budget.py", "services.py")]
parser = argparse.ArgumentParser()
parser.add_argument("--change-marker", action="store_true")
arguments = parser.parse_args()
marker = ROOT / "marker.txt"
original_marker = "CASE051_CONTEXT_MARKER\n"
changed_marker = "CASE051_CONTEXT_MARKER revision=2\n"
if arguments.change_marker and marker.read_text(encoding="utf-8") != original_marker:
    raise SystemExit("fixture marker differs from the expected seed")
outcome_path = HERE / ("session-outcomes-changed.json" if arguments.change_marker else "session-outcomes.json")


def hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


async def run() -> None:
    before = hashes()
    args = {"action": "context", "root": str(ROOT), "query": "CASE051_CONTEXT_MARKER",
            "reuse_key": "fixture-051-session", "response_profile": "compact", "max_response_tokens": 3200}
    # Reserve the evidence path before any call so an interrupted probe cannot
    # silently repeat an operation whose outcome is unknown.
    with outcome_path.open("x", encoding="utf-8") as stream:
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                first = await session.call_tool("local_ai_repo", args)
                first_value = first.structuredContent
                values = [first.model_dump(exclude_none=True)]
                if (not first.isError and isinstance(first_value, dict) and first_value.get("success") is True
                        and first_value.get("in_progress") is not True and first_value.get("outcome_unknown") is not True):
                    if arguments.change_marker:
                        marker.write_text(changed_marker, encoding="utf-8")
                    second = await session.call_tool("local_ai_repo", {**args, "response_profile": "delta"})
                    values.append(second.model_dump(exclude_none=True))
        result = {"source_hashes_before": before, "source_hashes_after": hashes(),
                  "marker_changed": arguments.change_marker and marker.read_text(encoding="utf-8") == changed_marker,
                  "calls": values}
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"calls": len(values), "source_stable": result["source_hashes_before"] == result["source_hashes_after"],
                      "evidence": str(outcome_path)}))


anyio.run(run)
