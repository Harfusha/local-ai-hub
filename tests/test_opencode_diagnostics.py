import hashlib

from local_ai_hub.opencode_diagnostics import inspect_components


def test_reports_verified_components_but_not_runtime_acceptance(tmp_path):
    exe = tmp_path / "opencode.exe"
    exe.write_bytes(b"verified")
    plugin = tmp_path / "tools" / "opencode_goal"
    plugin.mkdir(parents=True)
    (plugin / "index.js").touch()
    hardware = {"gpus": [{"vendor": "nvidia", "name": "GPU", "vram_mb": 12282}]}
    cfg = {"security": {"api_token": "x" * 40}}
    result = inspect_components(cfg, hardware, tmp_path, exe, hashlib.sha256(b"verified").hexdigest(), {"qwen3.5:9b"})
    assert result["hardware_profile"] == "12gb"
    assert result["executable_verified"] is True
    assert result["goal_plugin_present"] is True
    assert result["hub_token_configured"] is True
    assert result["available_candidates"] == ["qwen3.5:9b"]
    assert result["ready"] is False and result["runtime_verified"] is False
    assert "x" * 40 not in str(result)


def test_empty_inventory_is_unknown_and_bad_binary_is_not_accepted(tmp_path):
    exe = tmp_path / "opencode.exe"
    exe.write_bytes(b"wrong")
    result = inspect_components({}, {}, tmp_path, exe, "0" * 64, set())
    assert result["hardware_profile"] == "unsupported"
    assert result["executable_verified"] is False
    assert result["available_candidates"] is None
    assert result["hub_token_configured"] is False


def test_doctor_uses_bundled_installer_metadata_without_activating_runtime(tmp_path, monkeypatch):
    import ast
    import importlib.util
    import os
    from pathlib import Path
    from typing import Any
    root = Path(__file__).resolve().parents[1]
    doctor = root / "tools" / "doctor.py"
    tree = ast.parse(doctor.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "opencode_component_status")
    namespace = {"Any": Any, "Path": Path, "os": os, "root": root, "importlib": importlib,
                 "inspect_opencode_components": inspect_components}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(doctor), "exec"), namespace)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    result = namespace["opencode_component_status"]({"_hardware": {"gpus": []}}, set())
    assert result["executable_verified"] is False
    assert result["goal_plugin_present"] is True
    assert result["runtime_verified"] is False
