from __future__ import annotations

import sys
import os
import types
from pathlib import Path

import pytest

from local_ai_hub import accelerators
from local_ai_hub import hardware
from local_ai_hub.embeddings import EmbeddingModel
from local_ai_hub.hardware import _is_integrated_gpu, choose_profile, profile_overrides
from local_ai_hub.ollama import OllamaRuntime
from local_ai_hub.reranker import Reranker


@pytest.mark.skipif(os.name != 'nt', reason='Windows Job Object API')
def test_sandbox_job_enforces_memory_limit():
    import win32job
    from local_ai_hub.process_utils import create_sandboxed_job_object, close_job_object
    job = create_sandboxed_job_object(memory_limit_mb=512)
    assert job
    try:
        info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        assert info['JobMemoryLimit'] == 512 * 1024 * 1024
        assert info['BasicLimitInformation']['LimitFlags'] & win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    finally:
        close_job_object(job)


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
    assert _is_integrated_gpu("intel", "Intel(R) Arc(TM) Graphics", 2047) is True
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


@pytest.mark.parametrize('name', ['AMD Radeon (TM) Graphics', 'AMD Radeon(TM) Graphics', 'AMD Radeon Graphics', 'AMD Radeon 740M'])
def test_amd_shared_memory_names_use_integrated_profile(name):
    integrated = _is_integrated_gpu('amd', name, 2048)
    assert integrated
    assert choose_profile([{'vendor': 'amd', 'integrated': integrated, 'vram_mb': 2048}], 32) == 'integrated'


@pytest.mark.parametrize('name', ['AMD Radeon RX 7600', 'AMD Radeon Pro W7800', 'AMD Radeon R9 390'])
def test_amd_discrete_names_remain_discrete(name):
    assert not _is_integrated_gpu('amd', name, 8192)


def test_integrated_profile_is_conservative_and_accelerates_retrieval() -> None:
    cfg = profile_overrides("integrated", _integrated_hw())
    assert cfg["models"]["background_code"] == "qwen2.5-coder:0.5b"
    assert cfg["models"]["fast_code"] == "qwen2.5-coder:1.5b"
    assert cfg["models"]["heavy_code"] == "qwen2.5-coder:3b"
    assert cfg["scheduler"]["max_parallel"] == 1
    assert cfg["scheduler"]["max_loaded_models"] == 1
    assert cfg["background_gpu"]["enabled"] is False
    assert cfg["preprocessing"]["cpu_workers"] == 1
    assert cfg["model_execution"]["fast"]["context_tokens"] == 32768
    assert cfg["model_execution"]["smart"]["max_context_tokens"] == 32768
    base_cfg = profile_overrides("integrated")
    assert base_cfg["model_execution"]["fast"]["context_tokens"] == 8192
    assert base_cfg["model_execution"]["smart"]["max_context_tokens"] == 12288
    assert cfg["models"]["embedding"] == "BAAI/bge-small-en-v1.5"
    assert cfg["models"]["embedding_backend"] == "openvino"
    assert cfg["models"]["reranker"] == "cross-encoder/ms-marco-MiniLM-L6-v2"
    assert cfg["models"]["reranker_backend"] == "openvino"
    assert cfg["ollama"]["allow_integrated_gpu"] is False
    assert cfg["ollama"]["enable_vulkan"] is False
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

def test_embedding_openvino_npu_uses_static_model_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    class FakeOpenVINOModel:
        config = types.SimpleNamespace(max_position_embeddings=512)

        def reshape(self, batch_size: int, sequence_length: int) -> None:
            calls["shape"] = (batch_size, sequence_length)

        def compile(self) -> None:
            calls["compiled"] = True

    class FakeSentenceTransformer:
        prompts: dict[str, str] = {}
        max_seq_length = 512

        def __init__(self, _model: str, **kwargs: object) -> None:
            calls["kwargs"] = kwargs
            self.auto_model = FakeOpenVINOModel()

        def __getitem__(self, _index: int) -> types.SimpleNamespace:
            return types.SimpleNamespace(auto_model=self.auto_model)

    sentence_transformers = types.ModuleType("sentence_transformers")
    sentence_transformers.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", sentence_transformers)
    monkeypatch.setattr("local_ai_hub.embeddings.openvino_device_candidates", lambda *_args: ["NPU"])

    embeddings = EmbeddingModel(
        {
            "models": {
                "embedding": "BAAI/bge-small-en-v1.5",
                "embedding_backend": "openvino",
                "embedding_device": "auto",
            },
            "openvino": {"device_priority": ["NPU"], "cpu_fallback": False},
            "cpu_retrieval": {},
        }
    )

    assert embeddings._load_candidate(0) is True
    assert calls["kwargs"]["model_kwargs"]["compile"] is False  # type: ignore[index]
    assert calls["shape"] == (1, 512)
    assert calls["compiled"] is True
    assert embeddings.active_device == "NPU"


def test_embedding_openvino_npu_pads_tokens_to_static_shape() -> None:
    torch = pytest.importorskip("torch")

    class FakeSentenceTransformer:
        max_seq_length = 8
        prompts: dict[str, str] = {}

        def __init__(self) -> None:
            self.seen_features: dict[str, object] = {}

        def __getitem__(self, _index: int) -> types.SimpleNamespace:
            return types.SimpleNamespace(tokenizer=types.SimpleNamespace(pad_token_id=0))

        def preprocess(self, _texts: list[str], prompt: str | None = None) -> dict[str, object]:
            return {
                "input_ids": torch.tensor([[101, 102, 103]], dtype=torch.long),
                "attention_mask": torch.tensor([[1, 1, 1]], dtype=torch.long),
            }

        def __call__(self, features: dict[str, object]) -> dict[str, object]:
            self.seen_features = features
            return {"sentence_embedding": torch.tensor([[3.0, 4.0]])}

    model = FakeSentenceTransformer()
    encoded = EmbeddingModel._encode_static_npu_batch(model, ["short text"], prompts={}, query=False)

    assert tuple(model.seen_features["input_ids"].shape) == (1, 8)  # type: ignore[union-attr]
    assert tuple(model.seen_features["attention_mask"].shape) == (1, 8)  # type: ignore[union-attr]
    assert model.seen_features["input_ids"][0, -1].item() == 0  # type: ignore[index]
    assert model.seen_features["attention_mask"][0, -1].item() == 0  # type: ignore[index]


def test_embedding_openvino_npu_accepts_mapping_preprocess_features() -> None:
    torch = pytest.importorskip("torch")
    from collections import UserDict

    class FakeSentenceTransformer:
        max_seq_length = 8

        def preprocess(self, texts: list[str]) -> UserDict[str, object]:
            return UserDict(
                {
                    "input_ids": torch.tensor([[1, 2, 3]]),
                    "attention_mask": torch.tensor([[1, 1, 1]]),
                    "modality": "text",
                }
            )

        def tokenize(self, texts: list[str]) -> dict[str, object]:
            raise AssertionError("preprocess mapping should be used directly")

        def __getitem__(self, index: int) -> object:
            return types.SimpleNamespace(tokenizer=types.SimpleNamespace(pad_token_id=0))

        def __call__(self, features: dict[str, object]) -> dict[str, object]:
            return {"sentence_embedding": torch.tensor([[3.0, 4.0]])}

    encoded = EmbeddingModel._encode_static_npu_batch(
        FakeSentenceTransformer(), ["short text"], prompts={}, query=False
    )

    assert encoded.shape == (1, 2)
    assert torch.allclose(torch.from_numpy(encoded), torch.tensor([[0.6, 0.8]]))
    assert torch.allclose(torch.linalg.vector_norm(torch.from_numpy(encoded), dim=1), torch.ones(1))


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
