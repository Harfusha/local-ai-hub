from __future__ import annotations

import asyncio
import builtins
from contextlib import asynccontextmanager
import json
from pathlib import Path
import sys
import threading
from types import ModuleType, SimpleNamespace
import tomllib

import pytest

from tools import wheel_smoke


def _install_fake_stdio_client(monkeypatch, payload: dict[str, object]) -> None:
    class FakeServerParameters:
        def __init__(self, **_kwargs) -> None:
            pass

    class FakeSession:
        def __init__(self, *_streams) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc_info):
            return None

        async def initialize(self):
            return SimpleNamespace(serverInfo=SimpleNamespace(name="local-ai", version="test"))

        async def list_tools(self):
            return SimpleNamespace(tools=[SimpleNamespace(name=name) for name in (
                "local_ai_artifact", "local_ai_coord", "local_ai_rag", "local_ai_repo",
                "local_ai_status", "local_ai_task", "local_ai_work",
            )])

        async def call_tool(self, _name, _arguments):
            return SimpleNamespace(
                isError=False,
                content=[SimpleNamespace(text=json.dumps(payload))],
            )

    @asynccontextmanager
    async def fake_stdio_client(_params):
        yield object(), object()

    mcp = ModuleType("mcp")
    mcp.ClientSession = FakeSession
    mcp.StdioServerParameters = FakeServerParameters
    client = ModuleType("mcp.client")
    client.__path__ = []
    stdio = ModuleType("mcp.client.stdio")
    stdio.stdio_client = fake_stdio_client
    monkeypatch.setitem(sys.modules, "mcp", mcp)
    monkeypatch.setitem(sys.modules, "mcp.client", client)
    monkeypatch.setitem(sys.modules, "mcp.client.stdio", stdio)


@pytest.mark.parametrize(
    "direct_url_text",
    [
        None,
        "{",
        json.dumps({"url": "file:///tmp/source", "dir_info": {"editable": True}}),
        json.dumps({"url": "file:///tmp/local-ai-hub.whl", "archive_info": {}}),
        json.dumps({"url": "file:///tmp/local-ai-hub.whl", "archive_info": {"hash": "sha256=short"}}),
        json.dumps({"url": "file:///tmp/local-ai-hub.whl", "archive_info": {"hash": f"sha256={'a' * 64}"}}),
        json.dumps({
            "url": "file://remote-host/tmp/local-ai-hub.whl",
            "archive_info": {"hashes": {"sha256": "a" * 64}},
        }),
    ],
    ids=[
        "missing-record", "malformed-record", "editable", "missing-archive",
        "missing-sha256", "legacy-hash-only", "remote-file-host",
    ],
)
def test_unverifiable_wheel_provenance_is_rejected_before_app_import(monkeypatch, tmp_path, direct_url_text) -> None:
    venv = tmp_path / "venv"
    site_packages = venv / "Lib" / "site-packages"
    package_origin = site_packages / "local_ai_hub" / "__init__.py"
    monkeypatch.setattr(wheel_smoke.sys, "prefix", str(venv))
    monkeypatch.setattr(wheel_smoke.sys, "base_prefix", str(tmp_path / "base-python"))
    monkeypatch.setattr(wheel_smoke, "_site_package_roots", lambda: (site_packages,))
    monkeypatch.setattr(wheel_smoke.importlib.util, "find_spec", lambda _name: SimpleNamespace(origin=str(package_origin)))

    class FakeDistribution:
        def read_text(self, _name):
            return direct_url_text

    monkeypatch.setattr(wheel_smoke.importlib.metadata, "distribution", lambda _name: FakeDistribution())
    imported_packages: list[str] = []
    real_import_module = wheel_smoke.importlib.import_module

    def tracked_import_module(name, *args, **kwargs):
        imported_packages.append(name)
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(wheel_smoke.importlib, "import_module", tracked_import_module)
    imported_runtime_modules: list[str] = []
    real_import = builtins.__import__

    def tracked_import(name, *args, **kwargs):
        if name in {"local_ai_hub.app", "local_ai_hub.http_server"}:
            imported_runtime_modules.append(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", tracked_import)

    with pytest.raises(wheel_smoke.SmokeError, match="provenance|editable|archive|SHA-256"):
        wheel_smoke.run_smoke()

    assert imported_packages == []
    assert imported_runtime_modules == []


def test_local_wheel_provenance_returns_canonical_archive_identity(monkeypatch) -> None:
    digest = "a" * 64

    class FakeDistribution:
        def read_text(self, _name):
            return json.dumps({
                "url": "file:///tmp/local-ai-hub-4.0.0-py3-none-any.whl",
                "archive_info": {"hash": "sha256=" + "b" * 64, "hashes": {"sha256": digest}},
            })

    monkeypatch.setattr(wheel_smoke.importlib.metadata, "distribution", lambda _name: FakeDistribution())
    assert wheel_smoke._wheel_provenance() == (
        digest,
        "file:///tmp/local-ai-hub-4.0.0-py3-none-any.whl",
    )


def test_smoke_configuration_is_temporary_and_disables_background_startup(tmp_path: Path) -> None:
    config_path = wheel_smoke._write_smoke_config(tmp_path, port=54321)
    with config_path.open("rb") as handle:
        config = tomllib.load(handle)

    assert config_path.parent == tmp_path
    assert Path(config["server"]["state_dir"]).parent == tmp_path
    assert config["server"]["bind"] == "127.0.0.1"
    assert config["server"]["port"] == 54321
    assert config["server"]["auto_start_ollama"] is False
    assert config["hardware"]["profile"] == "cpu"
    assert config["hardware"]["auto_tune"] is False
    assert config["features"]["preprocessing"] is False
    assert config["preprocessing"]["enabled"] is False
    assert config["preprocessing"]["task_context_warmup"] is False
    assert config["prewarm"]["enabled"] is False
    assert config["resilience"]["watchdog_enabled"] is False
    assert config["ollama"]["enabled"] is False
    assert config["llama_cpp"]["mode"] == "off"
    assert config["server"]["ollama_url"] == "http://127.0.0.1:9"


@pytest.mark.parametrize("port", [0, False, 65536, -1])
def test_smoke_config_never_writes_an_invalid_listener_port(tmp_path, port):
    with pytest.raises(wheel_smoke.SmokeError):
        wheel_smoke._write_smoke_config(tmp_path, port=port)


def test_stdio_child_disables_autostart_before_mcp_server_main() -> None:
    source = wheel_smoke._mcp_child_source()
    disable_index = source.index("mcp_server.CLIENT.auto_start = False")
    main_index = source.index("mcp_server.main()")
    assert disable_index < main_index


def test_stdio_roundtrip_accepts_compact_status_without_retired_metrics(monkeypatch, tmp_path) -> None:
    _install_fake_stdio_client(monkeypatch, {"success": True, "ollama_online": False})

    result = asyncio.run(wheel_smoke._stdio_roundtrip(tmp_path / "smoke.toml", cwd=tmp_path, timeout=1))

    assert result == {
        "server_name": "local-ai",
        "tool_count": 7,
        "ollama_online": False,
    }


@pytest.mark.parametrize("metric", ["queued", "cache_hits"])
def test_stdio_roundtrip_rejects_retired_status_metrics(monkeypatch, tmp_path, metric) -> None:
    _install_fake_stdio_client(
        monkeypatch,
        {"success": True, "ollama_online": False, metric: 0},
    )

    with pytest.raises(wheel_smoke.SmokeError, match="unnecessary queue or cache metrics"):
        asyncio.run(wheel_smoke._stdio_roundtrip(tmp_path / "smoke.toml", cwd=tmp_path, timeout=1))


def test_http_shutdown_timeout_is_bounded_reported_and_socket_closed() -> None:
    released = threading.Event()
    shutdown_started = threading.Event()

    class BlockingServer:
        closed = False

        def shutdown(self) -> None:
            shutdown_started.set()
            released.wait()

        def server_close(self) -> None:
            self.closed = True
            released.set()

    serving_thread = threading.Thread(target=released.wait, daemon=True)
    serving_thread.start()
    server = BlockingServer()
    try:
        with pytest.raises(wheel_smoke.SmokeError, match="shutdown exceeded its deadline"):
            wheel_smoke._shutdown_http_server(server, serving_thread, timeout=0.05)
    finally:
        released.set()

    assert shutdown_started.is_set()
    assert server.closed is True
    assert not serving_thread.is_alive()


def test_cli_reports_actual_smoke_failure_as_machine_readable_nonzero(monkeypatch, capsys) -> None:
    def fail_smoke():
        raise wheel_smoke.SmokeError("stdio session did not initialize")

    monkeypatch.setattr(wheel_smoke, "run_smoke", fail_smoke)
    assert wheel_smoke.main() == 1

    result = json.loads(capsys.readouterr().out)
    assert result["success"] is False
    assert result["smoke"] == "failed"
    assert result["error_type"] == "SmokeError"
    assert "stdio session" in result["error"]
