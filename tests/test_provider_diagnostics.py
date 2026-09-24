from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.services import LocalAIServices


def _services(config, tmp_path, *, llama_online=False, ollama_online=False, mode=""):
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {**config, "server": {"state_dir": str(tmp_path)}}
    services.runtime = SimpleNamespace(
        is_online=lambda: ollama_online,
        installed_models=lambda: ["model"] if ollama_online else [],
        llama_cpp=SimpleNamespace(is_online=lambda: llama_online),
        llama_cpp_managed=SimpleNamespace(status=lambda: {"mode": mode}),
    )
    services.preprocessor = None
    return services


def test_doctor_reports_disabled_backends_as_off_not_failure(tmp_path):
    service = _services({"ollama": {"enabled": False}, "llama_cpp": {"mode": "off"}}, tmp_path)
    with patch("local_ai_hub.gpu_monitor.get_gpu_telemetry", return_value={"available": False}):
        checks = service.run_doctor()["checks"]
    backend = next(row for row in checks if row["component"] == "Inference Backend")
    assert backend["status"] == "OFF"


def test_doctor_reports_managed_llama_cpu_fallback_as_healthy(tmp_path):
    service = _services(
        {"ollama": {"enabled": False}, "llama_cpp": {"mode": "on"}},
        tmp_path,
        llama_online=True,
        mode="none",
    )
    with patch("local_ai_hub.gpu_monitor.get_gpu_telemetry", return_value={"available": False}):
        checks = service.run_doctor()["checks"]
    backend = next(row for row in checks if row["component"] == "Inference Backend (llama.cpp)")
    assert backend["status"] == "OK"
    assert "execution device: none" in backend["detail"]


def test_doctor_uses_ollama_only_when_selected(tmp_path):
    service = _services(
        {"ollama": {"enabled": True}, "llama_cpp": {"mode": "on"}},
        tmp_path,
        llama_online=True,
        ollama_online=False,
    )
    with patch("local_ai_hub.gpu_monitor.get_gpu_telemetry", return_value={"available": False}):
        checks = service.run_doctor()["checks"]
    backend = next(row for row in checks if row["component"].startswith("Inference Backend"))
    assert backend["component"] == "Inference Backend (Ollama)"
    assert backend["status"] == "FAIL"
