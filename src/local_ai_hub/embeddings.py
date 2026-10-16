from __future__ import annotations

from collections.abc import Mapping

import json
import math
import threading
import urllib.error
import urllib.request
from typing import Any

from .cache import SQLiteCache, SingleFlightGroup, TieredCache, stable_hash
from .priority_gate import CooperativePriorityGate
from .accelerators import openvino_cache_dir, openvino_device_candidates
from .state_paths import configured_state_dir
from .json_utils import dumps as json_dumps
from .model_lifecycle import acquire_locks, load_model, release_model, uses_torch_cuda


def _safe_int(val: Any, default: int, min_val: int = 0) -> int:
    if val is None or isinstance(val, bool):
        return default
    try:
        if isinstance(val, float) and not math.isfinite(val):
            return default
        i = int(val)
        return max(min_val, i)
    except (ValueError, TypeError, OverflowError):
        return default


class EmbeddingModel:
    """Lazy local embeddings with GPU acceleration, CPU fallback and cross-workspace persistent cache."""

    def __init__(self, config: dict[str, Any]):
        cfg = config if isinstance(config, dict) else {}
        self.config = cfg
        models = cfg.get("models") if isinstance(cfg.get("models"), dict) else {}
        server_cfg = cfg.get("server") if isinstance(cfg.get("server"), dict) else {}
        features_cfg = cfg.get("features") if isinstance(cfg.get("features"), dict) else {}
        cpu_cfg = cfg.get("cpu_retrieval") if isinstance(cfg.get("cpu_retrieval"), dict) else {}
        cache_cfg = cfg.get("cache") if isinstance(cfg.get("cache"), dict) else {}

        raw_model = models.get("embedding", "qwen3-embedding:0.6b")
        self.model_name = str(raw_model or "qwen3-embedding:0.6b").replace("\x00", "").strip() or "qwen3-embedding:0.6b"
        self.device = str(models.get("embedding_device", "cpu")).replace("\x00", "").strip() or "cpu"
        self.backend = str(models.get("embedding_backend", "auto")).replace("\x00", "").strip().lower() or "auto"
        self.active_backend: str | None = None
        self.active_device: str | None = None
        self._st_candidates: list[tuple[str, str]] | None = None
        self._st_candidate_index = -1
        self.ollama_url = str(server_cfg.get("ollama_url", "http://127.0.0.1:11434")).replace("\x00", "").rstrip("/")
        self.enabled = bool(features_cfg.get("rag", True))
        self.trust_remote_code = bool(cpu_cfg.get("embedding_trust_remote_code", False))
        self.max_seq_length = _safe_int(cpu_cfg.get("embedding_max_seq_length"), 8192, 128)
        self.batch_size = _safe_int(cpu_cfg.get("embedding_batch_size"), 32, 1)
        self._model = None
        self._load_lock = threading.Lock()
        self._cpu_gate = CooperativePriorityGate(_safe_int(cpu_cfg.get("foreground_priority"), 3))
        self._load_error: str | None = None
        self._load_error_time: float = 0.0
        self.flight_group = SingleFlightGroup(shards=16, default_timeout_seconds=90.0)
        state_dir = configured_state_dir(cfg)
        self.cache = TieredCache(
            SQLiteCache(
                state_dir / "cache.sqlite",
                namespace="embeddings",
                ttl_seconds=_safe_int(cache_cfg.get("embedding_ttl_seconds"), 30 * 86400),
                max_entries=_safe_int(cache_cfg.get("embedding_max_entries"), 100_000),
            ),
            l1_entries=_safe_int(cache_cfg.get("l1_embedding_entries"), 4096),
            l1_ttl_seconds=_safe_int(cache_cfg.get("l1_embedding_ttl_seconds"), 3600),
        )
        self.cache_enabled = bool(cache_cfg.get("embeddings", True))
        self._memory_hits = 0
        self._computed = 0
        self._batch_deduplicated = 0
        self._ollama_model_name = "qwen3-embedding:0.6b" if "qwen" in self.model_name.lower() else self.model_name
        self._loaded_model_name = self.model_name
        self._active_cache_identity: str | None = None
        self._active_embedding_dimension: int | None = None
        self._identity_dimension_lock = threading.Lock()
        self._dimensions_by_identity: dict[str, int] = {}
        self._model_provenance_lock = threading.Lock()
        self._model_provenance_by_identity: dict[str, dict[str, str | None]] = {}
        self._loaded_model_revision: str | None = None
        self._loaded_model_digest: str | None = None
        self._encoder_lock_state = threading.RLock()
        self._execution_local_state = threading.local()

    @property
    def _encoder_lock(self) -> threading.RLock:
        lock = getattr(self, "_encoder_lock_state", None)
        if lock is None:
            lock = threading.RLock()
            self._encoder_lock_state = lock
        return lock

    @_encoder_lock.setter
    def _encoder_lock(self, value: threading.RLock) -> None:
        self._encoder_lock_state = value

    @property
    def _execution_local(self) -> threading.local:
        local_state = getattr(self, "_execution_local_state", None)
        if local_state is None:
            local_state = threading.local()
            self._execution_local_state = local_state
        return local_state

    @_execution_local.setter
    def _execution_local(self, value: threading.local) -> None:
        self._execution_local_state = value

    @staticmethod
    def _valid_cached_vector(cached: Any, identity: str, expected_dimension: int | None) -> list[float] | None:
        if not isinstance(cached, dict) or cached.get("identity") != identity:
            return None
        vector = cached.get("vector")
        dimension = cached.get("dimension")
        if not isinstance(vector, list) or not isinstance(dimension, int) or isinstance(dimension, bool) or dimension != len(vector):
            return None
        if expected_dimension is not None and dimension != expected_dimension:
            return None
        try:
            converted = [float(value) for value in vector]
        except (OverflowError, TypeError, ValueError):
            return None
        if not converted or not all(math.isfinite(value) for value in converted):
            return None
        if not any(value != 0.0 for value in converted):
            return None
        return converted

    @staticmethod
    def _resolved_model_revision(model: Any) -> str | None:
        candidates = [model]
        try:
            candidates.append(model[0])
        except (IndexError, KeyError, TypeError):
            pass
        candidates.extend(getattr(candidate, "auto_model", None) for candidate in tuple(candidates))
        for candidate in candidates:
            config = getattr(candidate, "config", None)
            revision = getattr(config, "_commit_hash", None)
            if isinstance(revision, str):
                value = revision.strip().lower()
                if len(value) in {40, 64} and all(char in "0123456789abcdef" for char in value):
                    return value
        return None

    def _record_model_provenance(
        self,
        identity: str,
        *,
        model: Any = None,
        revision: str | None = None,
        digest: str | None = None,
    ) -> dict[str, str | None]:
        resolved = {
            "revision": revision or self._resolved_model_revision(model),
            "digest": digest or getattr(model, "digest", None),
        }
        with self._model_provenance_lock:
            self._model_provenance_by_identity[identity] = resolved
        if identity == getattr(self, "_active_cache_identity", None) or identity.startswith(
            f"{self.active_backend or ''}:{self.active_device or ''}:"
        ):
            self._loaded_model_revision = resolved["revision"]
            self._loaded_model_digest = resolved["digest"]
        return resolved

    def _model_provenance(self, identity: str | None) -> dict[str, str | None]:
        if identity:
            lock = getattr(self, "_model_provenance_lock", None)
            if lock is not None:
                with lock:
                    known = getattr(self, "_model_provenance_by_identity", {}).get(identity)
                if isinstance(known, dict):
                    return known
        models = self.config.get("models", {})
        return {
            "revision": models.get("embedding_revision") or models.get("model_revision"),
            "digest": models.get("embedding_digest") or models.get("model_digest"),
        }

    def _identity_cacheable(self, identity: str | None) -> bool:
        return bool(identity)

    def _configured_embedding_dimension(self) -> int | None:
        models = self.config.get("models", {})
        cpu_cfg = self.config.get("cpu_retrieval", {})
        for value in (models.get("embedding_dimension"), cpu_cfg.get("embedding_dimension")):
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                return value
        return None

    def _dimension_identity_key(self, identity: str) -> str:
        provenance = self._model_provenance(identity)
        provider, _, remainder = identity.partition(":")
        model_name = remainder.partition(":")[2] if provider in {"sentence-transformers", "openvino"} else remainder
        return stable_hash({
            "identity": identity,
            "model": model_name,
            "digest": provenance.get("digest"),
            "revision": provenance.get("revision"),
            "normalized": self._embedding_normalized(identity),
            "configured_dimension": self._configured_embedding_dimension(),
        })

    def _dimension_for_identity(self, identity: str) -> int | None:
        identity_key = self._dimension_identity_key(identity)
        dimensions = getattr(self, "_dimensions_by_identity", None)
        lock = getattr(self, "_identity_dimension_lock", None)
        if isinstance(dimensions, dict) and lock is not None:
            with lock:
                known = dimensions.get(identity_key)
            if known is not None:
                return known

        cache = getattr(self, "cache", None)
        if (
            cache is not None
            and bool(getattr(self, "cache_enabled", False))
            and self._identity_cacheable(identity)
        ):
            try:
                metadata = cache.get(stable_hash({"embedding_dimension_metadata": identity_key}))
            except Exception:
                metadata = None
            if isinstance(metadata, dict) and metadata.get("identity") == identity_key:
                dimension = metadata.get("dimension")
                configured = self._configured_embedding_dimension()
                if (
                    isinstance(dimension, int)
                    and not isinstance(dimension, bool)
                    and dimension > 0
                    and (configured is None or configured == dimension)
                ):
                    self._remember_dimension(identity, dimension, persist=False)
                    return dimension
        return self._configured_embedding_dimension()

    def _remember_dimension(self, identity: str, dimension: int, *, persist: bool = True) -> None:
        lock = getattr(self, "_identity_dimension_lock", None)
        if lock is None:
            lock = threading.Lock()
            self._identity_dimension_lock = lock
        dimensions = getattr(self, "_dimensions_by_identity", None)
        if not isinstance(dimensions, dict):
            dimensions = {}
            self._dimensions_by_identity = dimensions
        identity_key = self._dimension_identity_key(identity)
        with lock:
            dimensions[identity_key] = int(dimension)
        cache = getattr(self, "cache", None)
        if (
            persist
            and cache is not None
            and bool(getattr(self, "cache_enabled", False))
            and self._identity_cacheable(identity)
            and isinstance(cache, (TieredCache, SQLiteCache))
        ):
            try:
                cache.set(
                    stable_hash({"embedding_dimension_metadata": identity_key}),
                    {"identity": identity_key, "dimension": int(dimension)},
                )
            except Exception:
                pass

    def _embedding_normalized(self, identity: str | None = None) -> bool | None:
        if identity and identity.startswith("ollama:"):
            return False
        provider = identity.split(":", 1)[0] if identity else self.backend
        if provider in {"sentence-transformers", "openvino"}:
            return True
        if provider == "ollama":
            return False
        return None

    def _embedding_cache_key(
        self,
        identity: str,
        query: bool,
        text: str,
        *,
        dimension: int | None = None,
    ) -> str:
        provider, _, remainder = identity.partition(":")
        model_name = remainder.partition(":")[2] if provider in {"sentence-transformers", "openvino"} else remainder
        provenance = self._model_provenance(identity)
        return stable_hash({
            "space": stable_hash({
                "identity": identity,
                "provider": identity.split(":", 1)[0],
                "model": model_name,
                "digest": provenance.get("digest"),
                "revision": provenance.get("revision"),
                "dimension": dimension if dimension is not None else self._dimension_for_identity(identity),
                "normalized": self._embedding_normalized(identity),
            }),
            "query": query,
            "text": text,
        })

    def embedding_space_id(self, identity: str | None = None, *, dimension: int | None = None) -> str:
        selected = identity or self._active_cache_identity or f"configured:{self.backend}:{self.device}:{self.model_name}"
        if dimension is not None:
            try:
                return self._embedding_cache_key(selected, False, "", dimension=dimension)
            except TypeError:
                pass
        return self._embedding_cache_key(selected, False, "")

    def _encode_request_key(self, texts: list[str], query: bool) -> str:
        identity = self._active_cache_identity or f"configured:{self.backend}:{self.device}:{self.model_name}"
        return stable_hash(
            {
                "identity": identity,
                "dimension": self._configured_embedding_dimension(),
                "normalized": self._embedding_normalized(identity),
                "query": query,
                "texts": [str(text).replace("\r\n", "\n") for text in texts],
            }
        )

    def _candidate_specs(self, *, ollama_fallback: bool = False) -> list[tuple[str, str]]:
        if ollama_fallback:
            return [("sentence-transformers", "cpu")]
        if self.backend == "openvino":
            candidates = [("openvino", device) for device in openvino_device_candidates(self.config, self.device)]
            openvino_cfg = self.config.get("openvino") if isinstance(self.config, dict) else None
            cpu_fallback = bool(openvino_cfg.get("cpu_fallback", True)) if isinstance(openvino_cfg, dict) else True
            if cpu_fallback:
                candidates.append(("sentence-transformers", "cpu"))
            # Keep order stable while removing duplicate logical devices.
            deduped: list[tuple[str, str]] = []
            seen: set[tuple[str, str]] = set()
            for backend, device in candidates:
                key = (backend, str(device).upper())
                if key not in seen:
                    seen.add(key)
                    deduped.append((backend, device))
            return deduped
        return [("sentence-transformers", self.device)]

    def _load_candidate(self, index: int, *, ollama_fallback: bool = False) -> bool:
        candidates = self._candidate_specs(ollama_fallback=ollama_fallback)
        if index < 0 or index >= len(candidates):
            return False
        backend, device = candidates[index]
        # Record the attempted generation even if model construction fails. Without
        # this, a missing/broken optional accelerator was retried on every request
        # instead of respecting the cooldown after all fallbacks were exhausted.
        self._st_candidates = candidates
        self._st_candidate_index = index
        try:
            from sentence_transformers import SentenceTransformer
            loaded_model_name = self.model_name
            kwargs: dict[str, Any] = {
                "device": str(device).lower(),
                "trust_remote_code": self.trust_remote_code,
            }
            models = self.config.get("models", {})
            configured_revision = models.get("embedding_revision") or models.get("model_revision")
            if isinstance(configured_revision, str) and configured_revision.strip():
                kwargs["revision"] = configured_revision.strip()
            if backend == "openvino":
                # SentenceTransformers is still an nn.Module and calls .to(device) on
                # its pooling/output modules.  Passing "npu" there can make PyTorch
                # try to resolve a torch NPU backend before OpenVINO ever sees the
                # model.  Keep the wrapper on CPU and pass the real accelerator to
                # Optimum/OpenVINO through model_kwargs instead.
                kwargs["device"] = "cpu"
                kwargs["backend"] = "openvino"
                npu_static = str(device).upper().startswith("NPU")
                ov_model_kwargs: dict[str, Any] = {"device": str(device).lower()}
                if npu_static:
                    # OpenVINO's NPU plugin only accepts static shapes. Defer the
                    # initial compile so we can reshape the exported transformer.
                    ov_model_kwargs["compile"] = False
                cache_dir = openvino_cache_dir(self.config)
                if cache_dir is not None:
                    ov_model_kwargs["ov_config"] = {"CACHE_DIR": str(cache_dir)}
                kwargs["model_kwargs"] = ov_model_kwargs
            def _load_st(name: str, kw: dict[str, Any]) -> SentenceTransformer:
                try:
                    return SentenceTransformer(name, local_files_only=True, **kw)
                except Exception:
                    if self.config.get("models", {}).get("allow_hf_downloads") is not True:
                        raise
                    return SentenceTransformer(name, **kw)

            def create_model():
                nonlocal loaded_model_name
                try:
                    model = _load_st(self.model_name, kwargs)
                except Exception:
                    if self.model_name == "BAAI/bge-small-en-v1.5":
                        raise
                    fallback_kwargs = dict(kwargs)
                    fallback_kwargs["trust_remote_code"] = False
                    fallback_kwargs.pop("revision", None)
                    loaded_model_name = "BAAI/bge-small-en-v1.5"
                    model = _load_st(loaded_model_name, fallback_kwargs)
                if hasattr(model, "max_seq_length"):
                    max_pos = getattr(model, "max_seq_length", 512) or 512
                    try:
                        max_pos = int(getattr(model[0].auto_model.config, "max_position_embeddings", max_pos) or max_pos)
                    except Exception:
                        pass
                    model.max_seq_length = min(self.max_seq_length, max_pos)
                    if backend == "openvino" and str(device).upper().startswith("NPU"):
                        ov_model = getattr(model[0], "auto_model", None)
                        if ov_model is None:
                            raise RuntimeError("OpenVINO NPU model does not expose a reshapeable transformer")
                        ov_model.reshape(1, int(model.max_seq_length))
                        ov_model.compile()
                return model

            model = load_model(
                self,
                uses_cuda=uses_torch_cuda(backend, device),
                factory=create_model,
            )
            self._model = model
            self._loaded_model_name = loaded_model_name
            self.active_backend = backend
            self.active_device = str(device)
            identity = f"{backend}:{device}:{loaded_model_name}"
            self._record_model_provenance(identity, model=model)
            self._load_error = None
            return True
        except Exception as exc:
            import time
            self._load_error = f"{backend}/{device}: {exc}"
            self._load_error_time = time.time()
            self._model = None
            self.active_backend = None
            self.active_device = None
            return False

    def _ensure_st_model(self, *, ollama_fallback: bool = False) -> bool:
        if self._model is not None:
            return True
        with self._load_lock:
            if self._model is not None:
                return True
            candidates = self._candidate_specs(ollama_fallback=ollama_fallback)
            start = max(0, self._st_candidate_index + 1) if self._st_candidates == candidates else 0
            for index in range(start, len(candidates)):
                if self._load_candidate(index, ollama_fallback=ollama_fallback):
                    return True
            return False

    def release(self, timeout_seconds: float = 3.0) -> bool:
        """Detach the local model; CUDA allocator cleanup remains best-effort."""
        with acquire_locks((self._encoder_lock, self._load_lock), timeout_seconds) as acquired:
            if not acquired:
                return False
            model = self._model
            if model is None:
                return False
            used_cuda = uses_torch_cuda(self.active_backend, self.active_device)
            self._model = None
            self.active_backend = None
            self.active_device = None
            self._st_candidates = None
            self._st_candidate_index = -1
            self._loaded_model_name = self.model_name
            self._active_cache_identity = None
            self._active_embedding_dimension = None
            del model
            release_model(self, used_cuda=used_cuda)
            return True

    def _ensure_model(self) -> bool:
        if not getattr(self, "enabled", True):
            return False
        if self.backend == "ollama":
            self.active_backend = "ollama"
            self.active_device = "ollama"
            return True
        if self._model is not None:
            return True
        if self._load_error is not None:
            import time
            if time.time() - self._load_error_time < 15.0 and self._st_candidates is not None and self._st_candidate_index >= len(self._st_candidates) - 1:
                return False
        return self._ensure_st_model()

    def _encode_st_batch(self, batch_texts: list[str], *, query: bool, priority: int) -> tuple[list[list[float]] | None, str]:
        with self._encoder_lock:
            self._execution_local.snapshot = None
            return self._encode_st_batch_locked(batch_texts, query=query, priority=priority)

    def _encode_st_batch_locked(
        self, batch_texts: list[str], *, query: bool, priority: int
    ) -> tuple[list[list[float]] | None, str]:
        while True:
            if self._model is None and not self._ensure_st_model(ollama_fallback=self.backend == "ollama"):
                return None, self.active_backend or "sentence-transformers"
            model = self._model
            if model is None:
                return None, self.active_backend or "sentence-transformers"
            backend = self.active_backend or "sentence-transformers"
            device = str(self.active_device or self.device)
            model_name = self._loaded_model_name
            identity = f"{backend}:{device}:{model_name}"
            provenance = self._model_provenance(identity)
            execution_snapshot = {
                "identity": identity,
                "backend": backend,
                "device": device,
                "model": model_name,
                "revision": provenance.get("revision"),
                "digest": provenance.get("digest"),
            }
            if (
                self.active_backend == "openvino"
                and str(self.active_device or "").upper().startswith("NPU")
                and len(batch_texts) > 1
            ):
                # The NPU model is compiled for batch 1. If that device rejects a
                # single input and fallback switches accelerators, finish the rest
                # of this logical batch on the new device in one call.
                vectors: list[list[float]] = []
                for text in batch_texts:
                    item_vectors, active = self._encode_st_batch([text], query=query, priority=priority)
                    if item_vectors is None:
                        return None, active
                    vectors.extend(item_vectors)
                    if not str(self.active_device or "").upper().startswith("NPU"):
                        # Earlier items may already be NPU vectors. Re-encode the
                        # whole batch on the fallback device so one batch never
                        # mixes embedding spaces or precision.
                        restarted, active = self._encode_st_batch(
                            batch_texts, query=query, priority=priority
                        )
                        if restarted is None:
                            return None, active
                        return restarted, active
                return vectors, self.active_backend or "sentence-transformers"
            prompts = getattr(model, "prompts", {}) or {}
            kwargs: dict[str, Any] = {
                "normalize_embeddings": True, "show_progress_bar": False, "batch_size": self.batch_size
            }
            if query and isinstance(prompts, dict) and "query" in prompts:
                kwargs["prompt_name"] = "query"
            try:
                with self._cpu_gate.slot(priority):
                    if self.active_backend == "openvino" and str(self.active_device or "").upper().startswith("NPU"):
                        encoded = self._encode_static_npu_batch(model, batch_texts, prompts=prompts, query=query)
                    else:
                        encoded = model.encode(batch_texts, **kwargs)
                vectors: list[list[float]] = []
                for vector in encoded:
                    as_list = vector.tolist() if hasattr(vector, "tolist") else list(vector)
                    vectors.append([float(v) for v in as_list])
                self._execution_local.snapshot = execution_snapshot
                return vectors, backend
            except Exception as exc:
                # OpenVINO may discover an NPU but reject a particular model/shape
                # at first inference. Advance to iGPU/CPU instead of poisoning RAG.
                if self.backend == "openvino" and self.active_backend == "openvino":
                    failed = self.active_device or "openvino"
                    self._load_error = f"openvino/{failed} inference failed: {exc}"
                    self._model = None
                    self.active_backend = None
                    self.active_device = None
                    if self._ensure_st_model():
                        continue
                return None, self.active_backend or "sentence-transformers"

    @staticmethod
    def _encode_static_npu_batch(
        model: Any, batch_texts: list[str], *, prompts: dict[str, Any], query: bool
    ) -> Any:
        """Run one fixed-shape OpenVINO NPU batch through SentenceTransformers."""
        import torch

        sequence_length = int(getattr(model, "max_seq_length", 512) or 512)
        prompt = prompts.get("query") if query and isinstance(prompts, dict) else None
        preprocess = getattr(model, "preprocess", None)
        if callable(preprocess):
            features = preprocess(batch_texts, prompt=prompt) if prompt else preprocess(batch_texts)
        else:
            features = None
        if not isinstance(features, Mapping):
            inputs = [f"{prompt}{text}" for text in batch_texts] if prompt else batch_texts
            features = model.tokenize(inputs)
        if not isinstance(features, Mapping):
            raise RuntimeError("SentenceTransformers preprocessing did not return input features")
        features = dict(features)

        tokenizer = getattr(model[0], "tokenizer", None)
        pad_token_id = int(getattr(tokenizer, "pad_token_id", 0) or 0)
        for name, value in list(features.items()):
            if not torch.is_tensor(value) or value.ndim != 2:
                continue
            width = int(value.shape[1])
            if width < sequence_length:
                pad_value = pad_token_id if name == "input_ids" else 0
                features[name] = torch.nn.functional.pad(
                    value, (0, sequence_length - width), value=pad_value
                )
            elif width > sequence_length:
                features[name] = value[:, :sequence_length]

        with torch.inference_mode():
            output = model(features)
        embeddings = output.get("sentence_embedding") if isinstance(output, dict) else None
        if embeddings is None:
            raise RuntimeError("SentenceTransformers model returned no sentence_embedding")
        embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)
        return embeddings.detach().cpu().numpy()

    def _encode_ollama(self, texts: list[str]) -> list[list[float]] | None:
        """Call Ollama /api/embed on GPU."""
        try:
            req = urllib.request.Request(
                f"{self.ollama_url}/api/embed",
                data=json_dumps({"model": self._ollama_model_name, "input": texts}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                vectors = data.get("embeddings")
                if isinstance(vectors, list) and len(vectors) == len(texts):
                    return vectors
        except Exception:
            return None
        return None

    def encode(self, texts: list[str], query: bool = False, priority: int = 3) -> dict[str, Any]:
        self._execution_local.snapshot = None
        request_key = self._encode_request_key(texts, query)
        result, _coalesced = self.flight_group.do(
            request_key,
            lambda: self._encode_uncached(texts, query=query, priority=priority),
        )
        output = dict(result)
        if isinstance(output.get("embeddings"), list):
            output["embeddings"] = [list(vector) if isinstance(vector, (list, tuple)) else vector for vector in output["embeddings"]]
        return output

    def _encode_uncached(self, texts: list[str], query: bool = False, priority: int = 3) -> dict[str, Any]:
        if not texts:
            return {"success": True, "model": self.model_name, "backend": self.backend, "embeddings": []}

        vectors: list[list[float] | None] = [None] * len(texts)
        missing_texts: list[str] = []
        missing_groups: list[list[int]] = []
        cached_items: list[tuple[int, str]] = []
        pending_by_key: dict[str, int] = {}
        cache_hits = 0
        cache_identity = self._active_cache_identity
        # Establish a verified identity before the first lookup. Previously this
        # was assigned only after computing a miss, making every fresh process
        # ignore its persistent cross-worktree embedding cache for its first batch.
        if cache_identity is None and self.cache_enabled and self.backend in {"sentence-transformers", "openvino"}:
            with self._encoder_lock:
                model_ready = self._ensure_model()
                if model_ready:
                    active = self.active_backend or "sentence-transformers"
                    device = self.active_device or self.device
                    self._active_cache_identity = f"{active}:{device}:{self._loaded_model_name}"
            if model_ready:
                cache_identity = self._active_cache_identity
        elif cache_identity is None and self.cache_enabled and self.backend == "ollama":
            self._active_cache_identity = f"ollama:{self._ollama_model_name}"
            cache_identity = self._active_cache_identity
        used_backend = cache_identity.split(":", 1)[0] if cache_identity else (self.active_backend or self.backend)
        backend_fallback = False
        cache_identity_usable = self.cache_enabled and self._identity_cacheable(cache_identity)

        batch_keys: list[str] = []
        if cache_identity_usable:
            for text in texts:
                clean_text = str(text).replace("\r\n", "\n")
                batch_keys.append(self._embedding_cache_key(cache_identity, query, clean_text))
            get_many = getattr(self.cache, "get_many", None)
            if callable(get_many):
                cached_map = get_many(batch_keys)
            else:
                cached_map = {k: v for k in batch_keys if (v := self.cache.get(k)) is not None}
        else:
            cached_map = {}

        for i, text in enumerate(texts):
            clean_text = str(text).replace("\r\n", "\n")
            key = batch_keys[i] if cache_identity_usable and i < len(batch_keys) else (self._embedding_cache_key(cache_identity, query, clean_text) if cache_identity_usable else "")
            if cache_identity_usable and key:
                cached = cached_map.get(key)
            else:
                cached = None
            # Runtime dimension is shared mutable state. Concurrent requests may
            # finish on different backends, so use dimensions learned for this
            # exact cache identity rather than a process-wide last result.
            expected_dimension = self._dimension_for_identity(cache_identity) if cache_identity_usable else None
            cached_vector = self._valid_cached_vector(cached, cache_identity, expected_dimension) if cache_identity else None
            if cached_vector is not None:
                vectors[i] = cached_vector
                if self._active_embedding_dimension is None:
                    self._active_embedding_dimension = len(cached_vector)
                self._memory_hits += 1
                cached_items.append((i, text))
                cache_hits += 1
                continue
            # The same content is common across worktrees and generated/copied
            # files. Cache keys are content-addressed, so collapse duplicate misses
            # before invoking a model and fan one vector back out to every position.
            pending_key = key or stable_hash({"query": query, "text": text})
            group_index = pending_by_key.get(pending_key)
            if group_index is None:
                pending_by_key[pending_key] = len(missing_texts)
                missing_texts.append(text)
                missing_groups.append([i])
            else:
                missing_groups[group_index].append(i)

        batch_deduplicated = sum(len(group) - 1 for group in missing_groups)
        recomputed_cached = 0
        response_cache_identity = cache_identity
        result_cache_enabled = cache_identity_usable
        pending_cache_writes: dict[str, dict[str, Any]] = {}

        if missing_texts:
            computed_vectors: list[list[float]] | None = None

            # 1. Try Ollama GPU if backend is "auto" or "ollama"
            if self.backend in ("auto", "ollama"):
                all_ollama_vectors: list[list[float]] = []
                failed = False
                for start in range(0, len(missing_texts), self.batch_size):
                    stop = min(len(missing_texts), start + self.batch_size)
                    batch = missing_texts[start:stop]
                    res = self._encode_ollama(batch)
                    if res is not None:
                        all_ollama_vectors.extend(res)
                    else:
                        failed = True
                        break
                if not failed and len(all_ollama_vectors) == len(missing_texts):
                    computed_vectors = all_ollama_vectors
                    used_backend = "ollama"

            # 2. Local SentenceTransformers/OpenVINO path. OpenVINO uses NPU ->
            # Intel GPU -> CPU device fallback; Ollama failure falls back to torch CPU.
            if computed_vectors is None:
                # If NPU inference succeeds for one batch but rejects a later shape,
                # _encode_st_batch advances to GPU/CPU. Restart the whole logical
                # request on that new device so one embedding set never mixes
                # accelerator precision while being cached under a single identity.
                max_restarts = max(1, len(self._candidate_specs()) + 1)
                for _restart in range(max_restarts):
                    all_st_vectors: list[list[float]] = []
                    failed = False
                    execution_identity: tuple[str, str, str, str | None] | None = None
                    switched = False
                    for start in range(0, len(missing_texts), self.batch_size):
                        stop = min(len(missing_texts), start + self.batch_size)
                        batch_texts = missing_texts[start:stop]
                        encoded, active = self._encode_st_batch(batch_texts, query=query, priority=priority)
                        if encoded is None:
                            failed = True
                            break
                        snapshot = getattr(self._execution_local, "snapshot", None)
                        if isinstance(snapshot, dict):
                            current_identity = (
                                str(snapshot["backend"]),
                                str(snapshot["device"]),
                                str(snapshot["model"]),
                                snapshot.get("revision"),
                            )
                        else:
                            current_identity = (
                                active,
                                str(self.active_device or self.device),
                                self._loaded_model_name,
                                getattr(self, "_loaded_model_revision", None),
                            )
                        if execution_identity is None:
                            execution_identity = current_identity
                        elif current_identity != execution_identity:
                            switched = True
                            break
                        all_st_vectors.extend(encoded)
                        used_backend = current_identity[0]
                    if switched:
                        continue
                    if failed or len(all_st_vectors) != len(missing_texts):
                        return {"success": False, "error": self._load_error or "embedding model disabled", "model": self.model_name}
                    computed_vectors = all_st_vectors
                    backend_fallback = self.backend in ("auto", "ollama")
                    break
                if computed_vectors is None:
                    return {"success": False, "error": self._load_error or "embedding accelerator repeatedly changed", "model": self.model_name}

            # 3. Store in vectors and persist to cache
            execution_snapshot = getattr(self._execution_local, "snapshot", None)
            model_identity = self._ollama_model_name if used_backend == "ollama" else self._loaded_model_name
            if used_backend == "ollama":
                result_cache_identity = f"ollama:{model_identity}"
                result_device = "ollama"
            else:
                if isinstance(execution_snapshot, dict) and execution_snapshot.get("backend") == used_backend:
                    result_cache_identity = str(execution_snapshot["identity"])
                    model_identity = str(execution_snapshot["model"])
                    result_device = str(execution_snapshot["device"])
                else:
                    result_device = str(self.active_device or self.device)
                    result_cache_identity = f"{used_backend}:{result_device}:{model_identity}"
            with self._encoder_lock:
                self._active_cache_identity = result_cache_identity
            result_cache_enabled = self.cache_enabled and self._identity_cacheable(result_cache_identity)
            if len(computed_vectors) != len(missing_texts) or any(
                not isinstance(vector, list) for vector in computed_vectors
            ):
                return {"success": False, "error": "embedding backend returned incomplete vectors", "model": self.model_name}
            dimensions = {len(vector) for vector in computed_vectors}
            if len(dimensions) != 1 or 0 in dimensions:
                return {"success": False, "error": "embedding backend returned inconsistent vector dimensions", "model": self.model_name}
            try:
                computed_vectors = [[float(value) for value in vector] for vector in computed_vectors]
            except (OverflowError, TypeError, ValueError):
                return {"success": False, "error": "embedding backend returned an invalid vector", "model": self.model_name}
            if any(
                not vector
                or not all(math.isfinite(value) for value in vector)
                or not any(value != 0.0 for value in vector)
                for vector in computed_vectors
            ):
                return {"success": False, "error": "embedding backend returned an invalid vector", "model": self.model_name}
            if any(not vector or not all(math.isfinite(value) for value in vector) for vector in computed_vectors):
                return {"success": False, "error": "embedding backend returned an invalid vector", "model": self.model_name}
            result_dimension = dimensions.pop()
            self._active_embedding_dimension = result_dimension
            self._remember_dimension(result_cache_identity, result_dimension, persist=result_cache_enabled)

            if result_cache_identity != cache_identity and cached_items:
                cached_groups: dict[str, list[int]] = {}
                for index, text in cached_items:
                    clean_text = str(text).replace("\r\n", "\n")
                    cached_groups.setdefault(clean_text, []).append(index)
                cached_texts = list(cached_groups)
                cached_vectors: list[list[float]] = []
                for start in range(0, len(cached_texts), self.batch_size):
                    batch = cached_texts[start:start + self.batch_size]
                    encoded, active = self._encode_st_batch(batch, query=query, priority=priority)
                    snapshot = getattr(self._execution_local, "snapshot", None)
                    active_identity = (
                        str(snapshot["identity"])
                        if isinstance(snapshot, dict)
                        else f"{active}:{self.active_device or self.device}:{self._loaded_model_name}"
                    )
                    if encoded is None or len(encoded) != len(batch) or active_identity != result_cache_identity:
                        return {"success": False, "error": "embedding backend changed while reconciling cached vectors", "model": self.model_name}
                    for vector in encoded:
                        try:
                            clean_vector = [float(value) for value in vector]
                        except (OverflowError, TypeError, ValueError):
                            return {"success": False, "error": "embedding backend returned an invalid cached replacement", "model": self.model_name}
                        if (
                            len(clean_vector) != result_dimension
                            or not clean_vector
                            or not all(math.isfinite(value) for value in clean_vector)
                            or not any(value != 0.0 for value in clean_vector)
                        ):
                            return {"success": False, "error": "embedding backend returned an invalid cached replacement", "model": self.model_name}
                        cached_vectors.append(clean_vector)
                for text, vector in zip(cached_texts, cached_vectors):
                    for index in cached_groups[text]:
                        vectors[index] = vector
                    if result_cache_enabled:
                        key = self._embedding_cache_key(result_cache_identity, query, text)
                        pending_cache_writes[key] = {
                            "identity": result_cache_identity,
                            "dimension": result_dimension,
                            "vector": vector,
                        }
                recomputed_cached = len(cached_texts)
                batch_deduplicated += sum(len(indices) - 1 for indices in cached_groups.values())
                cache_hits = 0
            response_cache_identity = result_cache_identity

            for indices, text, vector in zip(missing_groups, missing_texts, computed_vectors):
                for idx in indices:
                    vectors[idx] = vector
                if result_cache_enabled:
                    clean_text = str(text).replace("\r\n", "\n")
                    key = self._embedding_cache_key(result_cache_identity, query, clean_text)
                    pending_cache_writes[key] = {
                        "identity": result_cache_identity,
                        "dimension": result_dimension,
                        "vector": vector,
                    }
                self._computed += 1
            self._computed += recomputed_cached
            self._batch_deduplicated += batch_deduplicated

        if any(vector is None for vector in vectors):
            return {"success": False, "error": "embedding backend returned incomplete vectors", "model": self.model_name}
        vector_dimensions = {len(vector) for vector in vectors if vector is not None}
        if len(vector_dimensions) != 1:
            return {"success": False, "error": "embedding backend returned inconsistent vector dimensions", "model": self.model_name}
        result_dimension = vector_dimensions.pop()
        if pending_cache_writes:
            batch_writer = getattr(self.cache, "set_many", None)
            if not callable(batch_writer):
                return {
                    "success": False,
                    "error": "embedding cache does not support batch writes",
                    "model": self.model_name,
                }
            batch_writer(pending_cache_writes)
        if response_cache_identity:
            self._remember_dimension(
                response_cache_identity,
                result_dimension,
                persist=self.cache_enabled and self._identity_cacheable(response_cache_identity),
            )

        execution_snapshot = getattr(self._execution_local, "snapshot", None)
        provenance = self._model_provenance(response_cache_identity)
        if used_backend == "ollama":
            models = self.config.get("models", {})
            model_digest = models.get("embedding_digest") or models.get("model_digest")
            model_revision = models.get("embedding_revision") or models.get("model_revision")
            result_device = "ollama"
        else:
            model_digest = (
                execution_snapshot.get("digest")
                if isinstance(execution_snapshot, dict)
                and execution_snapshot.get("identity") == response_cache_identity
                else provenance.get("digest")
            )
            model_revision = (
                execution_snapshot.get("revision")
                if isinstance(execution_snapshot, dict)
                and execution_snapshot.get("identity") == response_cache_identity
                else provenance.get("revision")
            )
            result_device = (
                str(execution_snapshot["device"])
                if isinstance(execution_snapshot, dict)
                and execution_snapshot.get("identity") == response_cache_identity
                else str(self.active_device or self.device)
            )
        if self.backend in {"auto", "ollama"}:
            backend_fallback = used_backend != "ollama"
        else:
            backend_fallback = (
                used_backend != self.backend
                or str(result_device).lower() != str(self.device).lower()
            )
        return {
            "success": True,
            "model": self.model_name,
            "backend": used_backend,
            "device": result_device,
            "embedding_space_id": self.embedding_space_id(response_cache_identity, dimension=result_dimension),
            "embedding_dimension": result_dimension,
            "normalized": self._embedding_normalized(response_cache_identity),
            "model_digest": model_digest,
            "model_revision": model_revision,
            "degraded": backend_fallback,
            "fallback": used_backend if backend_fallback else None,
            "embeddings": vectors,
            "cache_hits": cache_hits,
            "computed": len(missing_texts) + recomputed_cached,
            "unique_computed": len(missing_texts) + recomputed_cached,
            "batch_deduplicated": batch_deduplicated,
        }

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "model": self.model_name,
            "backend": self.backend,
            "active_backend": self.active_backend,
            "device": self.device,
            "active_device": self.active_device,
            "loaded": self._model is not None or self.backend == "ollama",
            "load_error": self._load_error,
            "cache_enabled": self.cache_enabled,
            "cache": self.cache.stats(),
            "cache_hits_runtime": self._memory_hits,
            "computed_runtime": self._computed,
            "batch_deduplicated_runtime": self._batch_deduplicated,
            "batch_size": self.batch_size,
            "max_seq_length": self.max_seq_length,
            "priority_gate": self._cpu_gate.status(),
        }
