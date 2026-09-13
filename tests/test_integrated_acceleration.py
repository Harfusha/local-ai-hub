from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from local_ai_hub import accelerators
from local_ai_hub import hardware
from local_ai_hub.embeddings import EmbeddingModel
from local_ai_hub.hardware import _is_integrated_gpu, choose_profile, profile_overrides
from local_ai_hub.ollama import OllamaRuntime
from local_ai_hub.reranker import Reranker


def _integrated_hw() -> dict:
    return {
        "profile": "integrated",
        "ram": {"total_gb": 32.0},
        "gpus": [{
            "vendor": "intel",
            "name": "Intel(R) Arc(TM) Graphics",
            "vram_mb": 128,
            "integrated": True,
            "shared_memory": True,
        }],
        "npus": [{"vendor": "intel", "name": "Intel(R) AI Boost", "device": "NPU"}],
    }


def test_intel_arc_shared_memory_is_not_treated_as_dedicated_vram() -> None:
    assert _is_integrated_gpu("intel", "Intel(R) Arc(TM) Graphics", 128) is True
    assert _is_integrated_gpu("intel", "Intel Arc A370M Graphics", 4096) is False
    assert _is_integrated_gpu("intel", "Intel(R) Arc(TM) A370M Graphics", 128) is False
    assert choose_profile(_integrated_hw()["gpus"], 32.0) == "integrated"
    assert choose_profile(_integrated_hw()["gpus"], 8.0) == "cpu"


def test_windows_npu_probe_does_not_match_usb_input_device(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hardware.os, "name", "nt")
    monkeypatch.setattr(hardware.shutil, "which", lambda name: "powershell.exe" if name == "powershell" else None)

    def fake_run(cmd: list[str], **_kwargs):
        assert r"\b(?:NPU|AI Boost|Neural Processing)\b" in cmd[-1]
        return types.SimpleNamespace(
            returncode=0,
            stdout='[{"Name":"Intel(R) AI Boost","Manufacturer":"Intel","Status":"OK"}]',
        )

    monkeypatch.setattr(
        hardware,
        "_run",
        fake_run,
    )

    npus = hardware._windows_npus()
    assert [item["name"] for item in npus] == ["Intel(R) AI Boost"]


def test_integrated_profile_is_conservative_and_accelerates_retrieval() -> None:
    cfg = profile_overrides("integrated", _integrated_hw())
    assert cfg["models"]["background_code"] == "qwen2.5-coder:0.5b"
    assert cfg["models"]["fast_code"] == "qwen2.5-coder:1.5b"
    assert cfg["models"]["heavy_code"] == "qwen2.5-coder:3b"
    assert cfg["scheduler"]["max_parallel"] == 1
    assert cfg["scheduler"]["max_loaded_models"] == 1
    assert cfg["background_gpu"]["enabled"] is False
    assert cfg["preprocessing"]["cpu_workers"] == 2
    assert cfg["model_execution"]["fast"]["context_tokens"] == 8192
    assert cfg["model_execution"]["smart"]["max_context_tokens"] == 12288
    assert cfg["models"]["embedding"] == "BAAI/bge-small-en-v1.5"
    assert cfg["models"]["embedding_backend"] == "openvino"
    assert cfg["models"]["reranker"] == "cross-encoder/ms-marco-MiniLM-L6-v2"
    assert cfg["models"]["reranker_backend"] == "openvino"
    assert cfg["ollama"]["allow_integrated_gpu"] is True
    assert cfg["ollama"]["gpu_overhead_bytes"] == 1024 * 1024 * 1024


def test_openvino_auto_candidates_prioritize_npu_then_gpu_then_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        accelerators,
        "openvino_runtime",
        lambda: {"installed": True, "available": True, "devices": ["CPU", "GPU.0", "NPU"]},
    )
    cfg = {"openvino": {"enabled": True, "device_priority": ["NPU", "GPU", "CPU"]}}
    assert accelerators.openvino_device_candidates(cfg, "auto") == ["NPU", "GPU.0", "CPU"]
    assert accelerators.openvino_device_candidates(cfg, "GPU") == ["GPU.0"]


def test_managed_ollama_enables_igpu_only_when_profile_requests_it(tmp_path: Path) -> None:
    runtime = OllamaRuntime({
        "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434"},
        "scheduler": {"max_parallel": 1, "max_loaded_models": 1},
        "ollama": {"num_parallel": 1, "allow_integrated_gpu": True},
    })
    assert runtime._configured_environment()["OLLAMA_IGPU_ENABLE"] == "1"

    runtime2 = OllamaRuntime({
        "server": {"state_dir": str(tmp_path / "other"), "ollama_url": "http://127.0.0.1:11434"},
        "scheduler": {"max_parallel": 1, "max_loaded_models": 1},
        "ollama": {"num_parallel": 1, "allow_integrated_gpu": False},
    })
    # A user-set process environment is deliberately preserved, but the hub does
    # not inject admission when the active profile does not request it.
    env = runtime2._configured_environment()
    if "OLLAMA_IGPU_ENABLE" not in __import__("os").environ:
        assert "OLLAMA_IGPU_ENABLE" not in env


def test_embedding_openvino_falls_from_npu_to_gpu(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    attempts: list[tuple[str, str, str]] = []

    class FakeSentenceTransformer:
        prompts: dict[str, str] = {}
        max_seq_length = 512

        def __init__(self, _model: str, **kwargs):
            self.device = kwargs.get("device")
            self.backend = kwargs.get("backend", "torch")
            self.ov_device = str(kwargs.get("model_kwargs", {}).get("device", self.device))
            attempts.append((self.backend, str(self.device), self.ov_device))

        def encode(self, texts, **_kwargs):
            if self.ov_device == "npu":
                raise RuntimeError("shape not supported on NPU")
            return [[1.0, float(i + 1)] for i, _ in enumerate(texts)]

    fake = types.ModuleType("sentence_transformers")
    fake.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake)
    monkeypatch.setattr("local_ai_hub.embeddings.openvino_device_candidates", lambda *_args, **_kwargs: ["NPU", "GPU.0", "CPU"])
    monkeypatch.setattr("local_ai_hub.embeddings.openvino_cache_dir", lambda _cfg: None)

    model = EmbeddingModel({
        "server": {"state_dir": str(tmp_path)},
        "models": {"embedding": "test", "embedding_backend": "openvino", "embedding_device": "auto"},
        "openvino": {"enabled": True, "cpu_fallback": True},
        "cache": {"embeddings": False},
        "features": {"rag": True},
    })
    result = model.encode(["a", "b"])
    assert result["success"] is True
    assert result["backend"] == "openvino"
    assert result["device"] == "GPU.0"
    # The SentenceTransformers wrapper stays on CPU; Optimum/OpenVINO receives
    # the actual accelerator. This avoids requiring a torch-native NPU backend.
    assert attempts[:2] == [("openvino", "cpu", "npu"), ("openvino", "cpu", "gpu.0")]


def test_reranker_openvino_falls_from_npu_to_gpu(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    attempts: list[tuple[str, str, str]] = []

    class FakeCrossEncoder:
        def __init__(self, _model: str, **kwargs):
            self.device = kwargs.get("device")
            self.backend = kwargs.get("backend", "torch")
            self.ov_device = str(kwargs.get("model_kwargs", {}).get("device", self.device))
            attempts.append((self.backend, str(self.device), self.ov_device))

        def predict(self, pairs, **_kwargs):
            if self.ov_device == "npu":
                raise RuntimeError("dynamic pair shape rejected")
            return [float(len(right)) for _left, right in pairs]

    fake = types.ModuleType("sentence_transformers")
    fake.CrossEncoder = FakeCrossEncoder
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake)
    monkeypatch.setattr("local_ai_hub.reranker.openvino_device_candidates", lambda *_args, **_kwargs: ["NPU", "GPU.0", "CPU"])
    monkeypatch.setattr("local_ai_hub.reranker.openvino_cache_dir", lambda _cfg: None)

    reranker = Reranker({
        "server": {"state_dir": str(tmp_path)},
        "models": {"reranker": "test", "reranker_backend": "openvino", "reranker_device": "auto"},
        "openvino": {"enabled": True, "cpu_fallback": True},
        "features": {"reranker": True},
        "cache": {"reranker": False},
    })
    result = reranker.rerank("q", ["a", "longer"])
    assert result["success"] is True
    assert result["backend"] == "openvino"
    assert result["device"] == "GPU.0"
    assert attempts[:2] == [("openvino", "cpu", "npu"), ("openvino", "cpu", "gpu.0")]


def test_openvino_load_failures_advance_and_then_cool_down(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    attempts: list[str] = []

    class BrokenSentenceTransformer:
        def __init__(self, _model: str, **kwargs):
            attempts.append(str(kwargs.get("model_kwargs", {}).get("device", kwargs.get("device"))))
            raise RuntimeError("unavailable")

    fake = types.ModuleType("sentence_transformers")
    fake.SentenceTransformer = BrokenSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake)
    monkeypatch.setattr("local_ai_hub.embeddings.openvino_device_candidates", lambda *_args, **_kwargs: ["NPU", "GPU.0"])
    monkeypatch.setattr("local_ai_hub.embeddings.openvino_cache_dir", lambda _cfg: None)

    model = EmbeddingModel({
        "server": {"state_dir": str(tmp_path)},
        "models": {"embedding": "test", "embedding_backend": "openvino", "embedding_device": "auto"},
        "openvino": {"enabled": True, "cpu_fallback": False},
        "cache": {"embeddings": False},
        "features": {"rag": True},
    })
    assert model._ensure_model() is False
    # Each device gets the configured model and the safe BGE-small fallback once.
    assert attempts == ["npu", "npu", "gpu.0", "gpu.0"]
    before = list(attempts)
    assert model._ensure_model() is False
    assert attempts == before


def test_reranker_uses_only_current_device_qualified_cache_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reranker = Reranker({
        "server": {"state_dir": str(tmp_path)},
        "models": {"reranker": "cache-test", "reranker_backend": "torch", "reranker_device": "cpu"},
        "features": {"reranker": True},
        "cache": {"reranker": True},
    })

    class Model:
        def predict(self, pairs, **_kwargs):
            return [0.42 for _ in pairs]

    reranker._model = Model()
    reranker.active_backend = "torch"
    reranker.active_device = "cpu"
    unrelated_key = __import__("local_ai_hub.cache", fromlist=["stable_hash"]).stable_hash({"q": "q", "d": "doc"})
    reranker.cache.set(unrelated_key, 0.75)

    result = reranker.rerank("q", ["doc"])

    assert result["success"] is True
    assert result["cache_hits"] == 0
    assert result["computed"] == 1
    assert result["results"][0]["score"] == pytest.approx(0.42)
    current_key = __import__("local_ai_hub.cache", fromlist=["stable_hash"]).stable_hash(
        {"identity": "torch:cpu:cache-test", "q": "q", "d": "doc"}
    )
    assert reranker.cache.get(current_key) == pytest.approx(0.42)

def test_reranker_device_switch_restarts_before_cache_write(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class SwitchingModel:
        def __init__(self, device: str):
            self.device = device

        def predict(self, pairs, **_kwargs):
            if self.device == "NPU":
                raise RuntimeError("NPU shape unsupported")
            return [2.0 for _ in pairs]

    reranker = Reranker({
        "server": {"state_dir": str(tmp_path)},
        "models": {"reranker": "switch-test", "reranker_backend": "openvino", "reranker_device": "auto"},
        "openvino": {"enabled": True, "cpu_fallback": False},
        "features": {"reranker": True},
        "cache": {"reranker": True},
    })
    monkeypatch.setattr(reranker, "_candidate_specs", lambda: [("openvino", "NPU"), ("openvino", "GPU.0")])

    loads: list[str] = []

    def load_candidate(index: int) -> bool:
        device = ["NPU", "GPU.0"][index]
        loads.append(device)
        reranker._candidates = [("openvino", "NPU"), ("openvino", "GPU.0")]
        reranker._candidate_index = index
        reranker._model = SwitchingModel(device)
        reranker.active_backend = "openvino"
        reranker.active_device = device
        return True

    monkeypatch.setattr(reranker, "_load_candidate", load_candidate)
    assert reranker._load_candidate(0) is True

    result = reranker.rerank("q", ["doc"])

    assert result["success"] is True
    assert result["device"] == "GPU.0"
    assert result["computed"] == 1
    npu_key = __import__("local_ai_hub.cache", fromlist=["stable_hash"]).stable_hash(
        {"identity": "openvino:npu:switch-test", "q": "q", "d": "doc"}
    )
    gpu_key = __import__("local_ai_hub.cache", fromlist=["stable_hash"]).stable_hash(
        {"identity": "openvino:gpu.0:switch-test", "q": "q", "d": "doc"}
    )
    assert reranker.cache.get(npu_key) is None
    assert reranker.cache.get(gpu_key) == pytest.approx(2.0)
    assert loads == ["NPU", "GPU.0"]
