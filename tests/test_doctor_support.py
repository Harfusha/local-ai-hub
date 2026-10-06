from __future__ import annotations

import ast
from pathlib import Path

from local_ai_hub.doctor_support import installed_models_from_status, probe_hub_status


ROOT = Path(__file__).resolve().parents[1]


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
    assert client.paths == ["/api/live/status?light=1"]


def test_doctor_falls_back_to_runtime_model_inventory_when_status_is_empty():
    class Runtime:
        def installed_models(self):
            return ["qwen3.5:9b", "qwen3-vl:4b"]

    models = installed_models_from_status({}, runtime_factory=lambda _cfg: Runtime(), cfg={})

    assert models == {"qwen3.5:9b", "qwen3-vl:4b"}


def test_doctor_report_keeps_only_supported_code_intelligence_backend():
    doctor_path = ROOT / "tools" / "doctor.py"
    tree = ast.parse(doctor_path.read_text(encoding="utf-8"))
    helper = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_supported_code_intelligence"
    )
    namespace = {}
    exec(compile(ast.Module(body=[helper], type_ignores=[]), str(doctor_path), "exec"), namespace)

    serena = {"enabled": True, "state": "healthy"}
    status = {"code_intelligence": {"serena": serena}}
    assert namespace["_supported_code_intelligence"](status) == {"serena": serena}
    assert namespace["_supported_code_intelligence"]({"code_intelligence": {"cgc": {}}}) == {
        "serena": {
            "state": "unavailable",
            "unavailable_reason": "Hub did not report Serena diagnostics.",
        }
    }
