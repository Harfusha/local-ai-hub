#!/usr/bin/env python3
"""Functional smoke for a wheel installed in an isolated virtual environment."""

from __future__ import annotations

import asyncio
import importlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import site
import sys
import sysconfig
import tempfile
import threading
from typing import Any
from urllib.parse import urlsplit


class SmokeError(RuntimeError):
    """The installed-wheel smoke could not establish a required contract."""


def _within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except (OSError, ValueError):
        return False
    return True


def _site_package_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    for value in (sysconfig.get_path("purelib"), sysconfig.get_path("platlib"), *site.getsitepackages()):
        if value:
            path = Path(value).resolve()
            if _within(path, Path(sys.prefix)) and path not in roots:
                roots.append(path)
    return tuple(roots)


def _wheel_provenance() -> tuple[str, str]:
    try:
        direct_url_text = importlib.metadata.distribution("local-ai-hub").read_text("direct_url.json")
    except Exception as exc:
        raise SmokeError("installed distribution has no readable PEP 610 wheel provenance") from exc
    if not isinstance(direct_url_text, str) or not direct_url_text.strip():
        raise SmokeError("installed distribution has no PEP 610 wheel provenance")
    try:
        record = json.loads(direct_url_text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise SmokeError("installed distribution PEP 610 provenance is malformed") from exc
    if not isinstance(record, dict):
        raise SmokeError("installed distribution PEP 610 provenance is malformed")
    if "dir_info" in record:
        directory_info = record["dir_info"]
        if not isinstance(directory_info, dict):
            raise SmokeError("installed distribution PEP 610 directory provenance is malformed")
        if directory_info.get("editable") is True:
            raise SmokeError("editable installs are not valid wheel smoke candidates")
        raise SmokeError("directory installs are not valid wheel smoke candidates")
    archive_info = record.get("archive_info")
    if not isinstance(archive_info, dict):
        raise SmokeError("installed distribution has no archive identity for a wheel")
    hashes = archive_info.get("hashes")
    digest = hashes.get("sha256", "") if isinstance(hashes, dict) else ""
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise SmokeError("installed wheel provenance has no canonical SHA-256 archive identity")
    source_url = record.get("url")
    try:
        parsed_url = urlsplit(source_url) if isinstance(source_url, str) else None
    except ValueError as exc:
        raise SmokeError("installed distribution provenance has an invalid wheel URL") from exc
    if (
        parsed_url is None
        or parsed_url.scheme != "file"
        or parsed_url.netloc
        or parsed_url.query
        or parsed_url.fragment
        or not parsed_url.path.lower().endswith(".whl")
    ):
        raise SmokeError("installed distribution provenance does not identify a local wheel archive")
    return digest, source_url


def _verify_installed_package() -> dict[str, str]:
    """Reject source-tree/editable imports before importing or starting the app."""
    if Path(sys.prefix).resolve() == Path(sys.base_prefix).resolve():
        raise SmokeError("wheel smoke must run inside an active virtual environment")
    roots = _site_package_roots()
    if not roots:
        raise SmokeError("active virtual environment has no site-packages directory")
    spec = importlib.util.find_spec("local_ai_hub")
    origin = Path(spec.origin).resolve() if spec is not None and spec.origin else None
    if origin is None or not any(_within(origin, root) for root in roots):
        raise SmokeError("local_ai_hub did not resolve to the active virtual environment site-packages")

    wheel_sha256, wheel_url = _wheel_provenance()
    distribution_version = importlib.metadata.version("local-ai-hub")
    package = importlib.import_module("local_ai_hub")
    imported_path = Path(getattr(package, "__file__", "")).resolve()
    if imported_path != origin:
        raise SmokeError("imported local_ai_hub path changed after site-packages validation")
    module_version = getattr(package, "__version__", None)
    if not isinstance(module_version, str) or module_version != distribution_version:
        raise SmokeError("installed distribution and module versions do not match")
    return {
        "version": distribution_version,
        "module_path": str(origin),
        "site_packages": str(next(root for root in roots if _within(origin, root))),
        "wheel_sha256": wheel_sha256,
        "wheel_url": wheel_url,
    }


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _write_smoke_config(directory: Path, *, port: int) -> Path:
    if type(port) is not int or not 1 <= port <= 65535:
        raise SmokeError("smoke configuration requires an allocated valid HTTP port")
    state_dir = directory / "state"
    config_path = directory / "smoke.toml"
    config_path.write_text(
        "\n".join(
            (
                "[server]",
                'bind = "127.0.0.1"',
                f"port = {port}",
                f"state_dir = {_toml_string(str(state_dir))}",
                'ollama_url = "http://127.0.0.1:9"',
                "auto_start_ollama = false",
                "",
                "[hardware]",
                'profile = "cpu"',
                "auto_tune = false",
                "",
                "[security]",
                'api_token = ""',
                "",
                "[features]",
                "preprocessing = false",
                "",
                "[preprocessing]",
                "enabled = false",
                "task_context_warmup = false",
                "",
                "[prewarm]",
                "enabled = false",
                "",
                "[resilience]",
                "watchdog_enabled = false",
                "",
                "[ollama]",
                "enabled = false",
                "",
                "[llama_cpp]",
                'mode = "off"',
                "",
                "[observability]",
                "enabled = true",
                "",
            )
        ),
        encoding="utf-8",
    )
    return config_path


def _mcp_child_source() -> str:
    # This check executes in the SDK-managed child before the package server imports.
    return "\n".join(
        (
            "import importlib.util, pathlib, site, sys, sysconfig",
            "spec = importlib.util.find_spec('local_ai_hub')",
            "origin = pathlib.Path(spec.origin).resolve() if spec and spec.origin else None",
            "roots = [pathlib.Path(p).resolve() for p in (sysconfig.get_path('purelib'), sysconfig.get_path('platlib'), *site.getsitepackages()) if p]",
            "if origin is None or not any(origin.is_relative_to(root) and root.is_relative_to(pathlib.Path(sys.prefix).resolve()) for root in roots):",
            "    raise SystemExit('local_ai_hub is not installed in this virtual environment')",
            "from local_ai_hub import mcp_server",
            "mcp_server.CLIENT.auto_start = False",
            "mcp_server.main()",
            "",
        )
    )


async def _stdio_roundtrip(config_path: Path, *, cwd: Path, timeout: float) -> dict[str, Any]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = os.environ.copy()
    env["LOCAL_AI_CONFIG"] = str(config_path)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-I", "-c", _mcp_child_source()],
        env=env,
        cwd=str(cwd),
    )
    try:
        async with asyncio.timeout(timeout):
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    initialized = await asyncio.wait_for(session.initialize(), timeout=timeout)
                    tools = await asyncio.wait_for(session.list_tools(), timeout=timeout)
                    tool_names = {tool.name for tool in tools.tools}
                    if "local_ai_status" not in tool_names:
                        raise SmokeError("installed MCP server did not advertise local_ai_status")
                    result = await asyncio.wait_for(
                        session.call_tool("local_ai_status", {"detail": "brief", "extra_fields": ["queued", "cache_hits"]}),
                        timeout=timeout,
                    )
    except asyncio.TimeoutError as exc:
        raise SmokeError("MCP stdio roundtrip exceeded its deadline") from exc

    if getattr(result, "isError", False):
        raise SmokeError("local_ai_status returned an MCP error")
    content = getattr(result, "content", ())
    text_blocks = [getattr(block, "text", None) for block in content]
    payload = None
    for text in text_blocks:
        if isinstance(text, str):
            try:
                payload = json.loads(text)
                break
            except json.JSONDecodeError:
                continue
    if not isinstance(payload, dict):
        raise SmokeError("local_ai_status did not return canonical JSON")
    status_success = payload.get("success") is True
    degraded_but_online = payload.get("hub_online") is True and payload.get("degraded") is True
    if not status_success and not degraded_but_online:
        raise SmokeError("local_ai_status reported an offline or unsuccessful Hub")
    if "ollama_online" not in payload:
        raise SmokeError("local_ai_status omitted local-model availability")
    if "queued" in payload or "cache_hits" in payload:
        raise SmokeError("local_ai_status returned unnecessary queue or cache metrics")
    return {
        "server_name": getattr(getattr(initialized, "serverInfo", None), "name", ""),
        "tool_count": len(tools.tools),
        "ollama_online": payload["ollama_online"],
        "status_success": status_success,
        "hub_online": payload.get("hub_online", status_success),
        "degraded": payload.get("degraded") is True,
    }


def _shutdown_http_server(server: Any, server_thread: threading.Thread | None, *, timeout: float = 1.5) -> None:
    failures: list[str] = []
    shutdown_error: list[BaseException] = []
    shutdown_thread: threading.Thread | None = None
    if server_thread is not None and server_thread.ident is not None and server_thread.is_alive():
        def stop_server() -> None:
            try:
                server.shutdown()
            except BaseException as exc:
                shutdown_error.append(exc)

        shutdown_thread = threading.Thread(target=stop_server, name="wheel-smoke-http-shutdown", daemon=True)
        shutdown_thread.start()
        shutdown_thread.join(timeout=timeout)
        if shutdown_thread.is_alive():
            failures.append("HTTP server shutdown exceeded its deadline")
        if shutdown_error:
            failures.append(f"HTTP server shutdown raised {type(shutdown_error[0]).__name__}")

    try:
        server.server_close()
    except Exception as exc:
        failures.append(f"HTTP server close raised {type(exc).__name__}")

    if server_thread is not None and server_thread.ident is not None:
        server_thread.join(timeout=timeout)
        if server_thread.is_alive():
            failures.append("HTTP serving thread remained alive after its deadline")
    if shutdown_thread is not None:
        shutdown_thread.join(timeout=0.1)
        if shutdown_thread.is_alive():
            failures.append("HTTP shutdown worker remained alive after socket close")
    if failures:
        raise SmokeError("; ".join(failures))


def run_smoke() -> dict[str, Any]:
    provenance = _verify_installed_package()
    # Imports that can construct app/runtime objects happen only after origin validation.
    from local_ai_hub.app import LocalAIApp
    from local_ai_hub import http_server
    from local_ai_hub.repo_plan.schema_validation import validate_plan_dict

    validate_plan_dict({
        "schema_version": 1,
        "id": "plan_wheel_smoke",
        "title": "Wheel smoke",
        "description": "",
        "lifecycle": "draft",
        "default_target_ref": "refs/heads/master",
        "spec_refs": [],
        "tasks": {},
    })
    provenance["planner_schema"] = "passed"

    with tempfile.TemporaryDirectory(prefix="local-ai-hub-wheel-smoke-") as raw_temp:
        temp_dir = Path(raw_temp).resolve()
        app: LocalAIApp | None = None
        server = None
        server_thread: threading.Thread | None = None
        try:
            server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
            config_path = _write_smoke_config(temp_dir, port=int(server.server_address[1]))
            app = LocalAIApp(str(config_path))
            http_server.APP = app
            server_thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
            server_thread.start()
            roundtrip = asyncio.run(_stdio_roundtrip(config_path, cwd=temp_dir, timeout=24.0))
            provenance.update({"smoke": "passed", "mcp": roundtrip})
            return provenance
        finally:
            if server is not None:
                try:
                    _shutdown_http_server(server, server_thread)
                except Exception:
                    http_server.APP = None
                    if app is not None:
                        app.close()
                    raise
            http_server.APP = None
            if app is not None:
                app.close()


def main() -> int:
    try:
        result = {"success": True, **run_smoke()}
    except Exception as exc:
        result = {
            "success": False,
            "smoke": "failed",
            "error": str(exc)[:400],
            "error_type": type(exc).__name__,
        }
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
