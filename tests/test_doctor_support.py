from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path
from typing import Any

from local_ai_hub import doctor_support
from local_ai_hub.doctor_support import (
    installed_models_from_status,
    optional_component_lines,
    optional_component_status,
    probe_hub_status,
)


class _StatusUnavailableClient:
    def __init__(self):
        self.paths: list[str] = []

    def _online(self):
        return True

    def get(self, path, timeout=15):
        self.paths.append(path)
        raise TimeoutError("status read timed out")


def test_doctor_keeps_hub_online_when_health_passes_but_status_times_out():
    client = _StatusUnavailableClient()
    probe = probe_hub_status(client)

    assert probe["hub_online"] is True
    assert probe["status_available"] is False
    assert probe["status"] == {}
    assert probe.get("code_intelligence_status") == {
        "available": False,
        "reason": "status_unavailable",
    }
    assert client.paths == ["/api/live/status?light=1"]


def test_doctor_reports_hub_offline_when_backend_diagnostics_are_unavailable():
    class OfflineClient:
        def _online(self):
            return False

        def get(self, path, timeout=15):
            raise ConnectionError("offline")

    probe = probe_hub_status(OfflineClient())

    assert probe.get("code_intelligence_status") == {
        "available": False,
        "reason": "hub_offline",
    }


def test_doctor_reports_when_hub_status_omits_backend_diagnostics():
    class StatusWithoutBackendDiagnosticsClient:
        def _online(self):
            return True

        def get(self, path, timeout=15):
            return {"hub_online": True}

    probe = probe_hub_status(StatusWithoutBackendDiagnosticsClient())

    assert probe.get("code_intelligence_status") == {
        "available": False,
        "reason": "diagnostics_not_reported",
    }


def test_doctor_finds_managed_serena_executable(tmp_path):
    serena = tmp_path / "tool-envs" / "serena" / "Scripts" / "serena.exe"
    serena.parent.mkdir(parents=True)
    serena.write_bytes(b"fixture executable")

    finder = getattr(doctor_support, "managed_serena_executable", None)
    assert callable(finder)
    assert finder(tmp_path, lambda _name: None) == str(serena)
    empty_install = tmp_path / "without-serena"
    empty_install.mkdir()
    assert finder(empty_install, lambda _name: None) is None


def test_hub_config_has_no_codegraph_runtime_flag():
    repo_root = Path(__file__).resolve().parents[1]
    sample = tomllib.loads((repo_root / "config.toml.example").read_text(encoding="utf-8"))
    assert sample.get("code_intelligence", {}).get("serena_enabled") is True

    for path in (repo_root / "defaults.toml", repo_root / "src/local_ai_hub/defaults.toml"):
        if path.is_file():
            config = tomllib.loads(path.read_text(encoding="utf-8"))
            assert "codegraph_enabled" not in config.get("code_intelligence", {}), path.name


def test_doctor_status_keeps_only_serena_backend_diagnostics():
    extract = getattr(doctor_support, "serena_backend_status", None)
    assert callable(extract)

    serena = {"enabled": True, "installed": True, "state": "healthy"}
    status = {
        "code_intelligence": {
            "serena": serena,
            "codegraph": {"enabled": True, "installed": True, "state": "healthy"},
        }
    }

    assert extract(status) == {"serena": serena}


def test_doctor_text_report_shows_local_tool_presence_when_hub_is_offline():
    doctor_path = Path(__file__).resolve().parents[1] / "tools" / "doctor.py"
    tree = ast.parse(doctor_path.read_text(encoding="utf-8"), filename=str(doctor_path))
    formatter = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "format_doctor_report"
    )
    namespace = {
        "Any": Any,
        "Path": Path,
        "__version__": "test",
        "optional_component_lines": optional_component_lines,
        "sys": sys,
    }
    exec(compile(ast.Module(body=[formatter], type_ignores=[]), str(doctor_path), "exec"), namespace)
    output = namespace["format_doctor_report"]({
        "runtime": {
            "hub_online": False,
            "serena_executable": None,
            "code_intelligence": None,
            "code_intelligence_status": {"available": False, "reason": "hub_offline"},
        },
        "config": {},
    })

    lines = output.splitlines()
    assert any("Serena executable" in line and "Not installed" in line for line in lines)
    assert not any("codegraph" in line.lower() for line in lines)
    assert any("Status unavailable" in line and "Hub is offline" in line for line in lines)


def test_doctor_falls_back_to_runtime_model_inventory_when_status_is_empty():
    class Runtime:
        def installed_models(self):
            return ["qwen3.5:9b", "qwen3-vl:4b"]

    models = installed_models_from_status({}, runtime_factory=lambda _cfg: Runtime(), cfg={})

    assert models == {"qwen3.5:9b", "qwen3-vl:4b"}


def test_doctor_reports_missing_optional_tree_sitter_and_whisper():
    missing = optional_component_status(lambda _module: False, lambda _command: None)
    assert missing == {"tree_sitter": False, "whisper_cli": False}
    assert optional_component_lines(missing) == [
        "  - Tree-sitter:        Not installed",
        "  - Whisper CLI:        Not installed",
    ]

    installed = optional_component_status(lambda _module: True, lambda _command: "whisper.exe")
    assert installed == {"tree_sitter": True, "whisper_cli": True}
    assert optional_component_lines(installed) == [
        "  - Tree-sitter:        Installed",
        "  - Whisper CLI:        Installed",
    ]


def test_doctor_text_report_states_presence_without_claiming_fallbacks():
    doctor_path = Path(__file__).resolve().parents[1] / "tools" / "doctor.py"
    tree = ast.parse(doctor_path.read_text(encoding="utf-8"), filename=str(doctor_path))
    formatter = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "format_doctor_report"
    )
    # Execute only the pure formatter; importing doctor.py runs host probes at module load.
    namespace = {
        "Any": Any,
        "Path": Path,
        "__version__": "test",
        "optional_component_lines": optional_component_lines,
        "sys": sys,
    }
    exec(compile(ast.Module(body=[formatter], type_ignores=[]), str(doctor_path), "exec"), namespace)

    output = namespace["format_doctor_report"]({
        "runtime": {
            "optional_components": {"tree_sitter": False, "whisper_cli": False},
            "openvino": {"installed": False},
            "code_intelligence": {
                "serena": {"enabled": True, "installed": False, "state": "missing"},
                "codegraph": {"enabled": True, "installed": False, "state": "missing"},
            },
        },
        "config": {},
    })

    lines = output.splitlines()
    optional_lines = [line for line in lines if "Tree-sitter:" in line or "Whisper CLI:" in line]
    assert optional_lines == [
        "  - Tree-sitter:        Not installed",
        "  - Whisper CLI:        Not installed",
    ]
    assert "  - OpenVINO:           Not installed" in lines
    assert any(line.startswith("  [ERR] serena") and "missing" in line for line in lines)
    assert not any("codegraph" in line.lower() for line in lines)

    offline_output = namespace["format_doctor_report"]({
        "runtime": {
            "hub_online": False,
            "code_intelligence": None,
            "code_intelligence_status": {"available": False, "reason": "hub_offline"},
        },
        "config": {},
    })
    assert any(
        "Status unavailable" in line and "Hub is offline" in line
        for line in offline_output.splitlines()
    )
