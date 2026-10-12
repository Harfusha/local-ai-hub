"""Keep stdio open until both protocol responses arrive, then let SDK close it."""
from __future__ import annotations

from pathlib import Path
import json
import os
import tempfile
from unittest.mock import patch

import anyio
from mcp import ClientSession, types
from mcp.client.stdio import StdioServerParameters, stdio_client
import mcp.client.stdio as stdio

from local_ai_hub.config import load_config
from local_ai_hub.features import FeatureSet


def explicit_catalog_environment(
    tmp_path: Path, *, root: Path, base_env: dict[str, str] | None = None,
) -> tuple[dict[str, str], FeatureSet]:
    """Give the stdio child and parent schema expectations one fixed feature config."""
    config = tmp_path / "stdio-catalog.toml"
    config.write_text(
        "[server]\n"
        "state_dir = " + json.dumps((tmp_path / "stdio-catalog-state").as_posix()) + "\n"
        "auto_start_ollama = true\n"
        "[features]\n"
        "status = true\nrepo = true\ncommands = true\ncoord = true\n"
        "artifacts = true\nrag = true\ntasks = true\nlocal_models = true\n"
        "vision = true\nwork_orchestrator = true\n",
        encoding="utf-8",
    )
    env = (base_env if base_env is not None else os.environ).copy()
    env["LOCAL_AI_CONFIG"] = str(config)
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(root / "src"), env.get("PYTHONPATH", "")) if value
    )
    return env, FeatureSet.from_config(load_config(config))


def stdio_catalog(
    command: list[str], *, cwd: Path, env: dict[str, str],
    initialize_params: dict, timeout: float = 15,
) -> tuple[dict, dict]:
    """Exercise the requested protocol version without closing stdin early.

    Unlike communicate(input=...), an interactive client observes initialize
    before notifying initialized and observes tools/list before sending EOF.
    The SDK owns process handles, stream draining and bounded process teardown.
    No tool is called and no daemon autostart is requested by this helper.
    """
    params = StdioServerParameters(
        command=command[0], args=command[1:], cwd=str(cwd), env=env,
    )

    async def exchange() -> tuple[dict, dict]:
        children = []
        original_spawn = stdio._create_platform_compatible_process

        async def capture_process(*args, **kwargs):
            child = await original_spawn(*args, **kwargs)
            children.append(child)
            return child

        with tempfile.TemporaryFile(mode="w+b") as stderr:
            try:
                with patch.object(stdio, "_create_platform_compatible_process", capture_process):
                    try:
                        async with stdio_client(params, errlog=stderr) as (read, write):
                            async with ClientSession(read, write) as session:
                                # End the timeout scope before SDK process teardown.
                                with anyio.fail_after(timeout):
                                    initialized = await session.send_request(
                                        types.ClientRequest(types.InitializeRequest(
                                            params=types.InitializeRequestParams(**initialize_params),
                                        )),
                                        types.InitializeResult,
                                    )
                                    await session.send_notification(types.ClientNotification(
                                        types.InitializedNotification(),
                                    ))
                                    listed = await session.list_tools()
                        assert len(children) == 1, "expected one SDK-owned stdio process"
                        assert children[0].returncode == 0, children[0].returncode
                    finally:
                        with anyio.CancelScope(shield=True):
                            for child in children:
                                if child.returncode is None:
                                    await stdio._terminate_process_tree(child, timeout_seconds=2)
                return (
                    initialized.model_dump(by_alias=True, exclude_none=True),
                    listed.model_dump(by_alias=True, exclude_none=True),
                )
            except Exception as exc:
                stderr.seek(0, 2)
                size = stderr.tell()
                stderr.seek(max(0, size - 2000))
                exc.add_note("stdio server stderr tail: " + stderr.read().decode("utf-8", "replace"))
                raise

    return anyio.run(exchange)
