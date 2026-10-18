from __future__ import annotations

import json
from pathlib import Path
import sys

import anyio
from jsonschema import Draft202012Validator
from mcp import ClientSession
import mcp.client.stdio as stdio


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TOOLS = {
    "local_ai_status", "local_ai_repo", "local_ai_rag",
    "local_ai_command", "local_ai_artifact", "local_ai_coord",
}


def test_live_stdio_publishes_valid_schemas_and_closes_child(tmp_path, monkeypatch):
    """Exercise the real protocol without calling tools or starting a backend."""
    config = tmp_path / "config.toml"
    config.write_text(
        "[server]\nauto_start_ollama = false\nstate_dir = "
        + json.dumps((tmp_path / "state").as_posix())
        + '\n[hardware]\nprofile = "cpu"\nauto_tune = false\n'
          '[ollama]\nenabled = false\n[llama_cpp]\nmode = "off"\n',
        encoding="utf-8",
    )
    bootstrap = (
        "import sys,pathlib; sys.path.insert(0,sys.argv[1]); "
        "import local_ai_hub.mcp_server as server; "
        "assert pathlib.Path(server.__file__).resolve() == "
        "pathlib.Path(sys.argv[1]).resolve()/'local_ai_hub'/'mcp_server.py'; "
        "server.main()"
    )
    params = stdio.StdioServerParameters(
        command=sys.executable,
        # Use the test runner's dependency environment, including user-site
        # installs. The bootstrap still asserts the exact Hub source path.
        args=["-B", "-c", bootstrap, str(ROOT / "src")],
        cwd=tmp_path,
        env={
            "LOCAL_AI_CONFIG": str(config),
            "LOCAL_AI_AGENT": "pytest-stdio",
        },
    )
    children = []
    original_spawn = stdio._create_platform_compatible_process

    async def capture_process(*args, **kwargs):
        child = await original_spawn(*args, **kwargs)
        children.append(child)
        return child

    # Observe the SDK-owned process without changing its arguments or behavior.
    monkeypatch.setattr(stdio, "_create_platform_compatible_process", capture_process)
    stderr_path = tmp_path / "mcp-stderr.log"

    async def initialize_and_list():
        try:
            with stderr_path.open("w", encoding="utf-8") as errlog:
                async with stdio.stdio_client(params, errlog=errlog) as (read, write):
                    async with ClientSession(read, write) as session:
                        # Let this cancellation scope exit before SDK teardown;
                        # otherwise timeout cancellation could interrupt cleanup.
                        with anyio.fail_after(20):
                            initialized = await session.initialize()
                            listed = await session.list_tools()
            return initialized, listed
        finally:
            # The SDK drains pipes and closes stdin, then waits/terminates its
            # process tree. Shield a final cleanup if teardown itself failed.
            with anyio.CancelScope(shield=True):
                for child in children:
                    if child.returncode is None:
                        await stdio._terminate_process_tree(child, timeout_seconds=2)

    initialized, listed = anyio.run(initialize_and_list)
    diagnostic = stderr_path.read_text(encoding="utf-8")
    assert len(children) == 1, diagnostic
    assert children[0].returncode == 0, diagnostic
    assert initialized.serverInfo.name == "Local AI Hub (compact)"
    assert initialized.protocolVersion
    assert {tool.name for tool in listed.tools} == EXPECTED_TOOLS
    assert len(listed.tools) == len(EXPECTED_TOOLS)

    for tool in listed.tools:
        Draft202012Validator.check_schema(tool.inputSchema)
        assert tool.outputSchema is not None, tool.name
        Draft202012Validator.check_schema(tool.outputSchema)
