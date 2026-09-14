from __future__ import annotations

from collections.abc import Mapping

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .cache import SQLiteCache, SingleFlightGroup, TieredCache, stable_hash
from .priority_gate import CooperativePriorityGate
from .accelerators import openvino_cache_dir, openvino_device_candidates
from .state_paths import configured_state_dir


class EmbeddingModel:
    """Lazy local embeddings with GPU acceleration, CPU fallback and cross-workspace persistent cache."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        models = config.get("models", {})
        self.model_name = models.get("embedding", "qwen3-embedding:0.6b")
        self.device = str(models.get("embedding_device", "cpu")).strip() or "cpu"
        self.backend = str(models.get("embedding_backend", "auto")).strip().lower()
        self.active_backend: str | None = None
        self.active_device: str | None = None
        self._st_candidates: list[tuple[str, str]] | None = None
        self._st_candidate_index = -1
        self.ollama_url = str(config.get("server", {}).get("ollama_url", "http://127.0.0.1:11434")).rstrip("/")
        self.enabled = bool(config.get("features", {}).get("rag", True))
        cpu_cfg = config.get("cpu_retrieval", {})
        self.trust_remote_code = bool(cpu_cfg.get("embedding_trust_remote_code", False))
        self.max_seq_length = max(128, int(cpu_cfg.get("embedding_max_seq_length", 8192)))
        self.batch_size = max(1, int(cpu_cfg.get("embedding_batch_size", 32)))
        self._model = None
        self._load_lock = threading.Lock()
        self._cpu_gate = CooperativePriorityGate(int(cpu_cfg.get("foreground_priority", 3)))
        self._load_error: str | None = None
        self._load_error_time: float = 0.0
        self.flight_group = SingleFlightGroup(shards=16, default_timeout_seconds=90.0)
        cache_cfg = config.get("cache", {})
        state_dir = configured_state_dir(config)
        self.cache = TieredCache(
            SQLiteCache(
                state_dir / "cache.sqlite3",
                namespace="embeddings",
                ttl_seconds=int(cache_cfg.get("embedding_ttl_seconds", 30 * 86400)),
                max_entries=int(cache_cfg.get("embedding_max_entries", 100_000)),
            ),
            l1_entries=int(cache_cfg.get("l1_embedding_entries", 4096)),
            l1_ttl_seconds=int(cache_cfg.get("l1_embedding_ttl_seconds", 3600)),
        )
        self.cache_enabled = bool(cache_cfg.get("embeddings", True))
        self._memory_hits = 0
        self._computed = 0
        self._batch_deduplicated = 0
        self._ollama_model_name = "qwen3-embedding:0.6b" if "qwen" in self.model_name.lower() else self.model_name
        self._loaded_model_name = self.model_name
        self._active_cache_identity: str | None = None
        self._active_embedding_dimension: int | None = None

    @staticmethod
    def _valid_cached_vector(cached: Any, identity: str, expected_dimension: int | None) -> list[float] | None:
        if not isinstance(cached, dict) or cached.get("identity") != identity:
            return None
        vector = cached.get("vector")
        dimension = cached.get("dimension")
        if not isinstance(vector, list) or not isinstance(dimension, int) or dimension != len(vector):
            return None
        if expected_dimension is not None and dimension != expected_dimension:
            return None
        try:
            return [float(value) for value in vector]
        except (TypeError, ValueError):
            return None

    def _candidate_specs(self, *, ollama_fallback: bool = False) -> list[tuple[str, str]]:
        if ollama_fallback:
            return [("sentence-transformers", "cpu")]
        if self.backend == "openvino":
            candidates = [("openvino", device) for device in openvino_device_candidates(self.config, self.device)]
            if bool(self.config.get("openvino", {}).get("cpu_fallback", True)):
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
            try:
                model = SentenceTransformer(self.model_name, **kwargs)
            except Exception:
                if self.model_name == "BAAI/bge-small-en-v1.5":
                    raise
                fallback_kwargs = dict(kwargs)
                fallback_kwargs["trust_remote_code"] = False
                model = SentenceTransformer("BAAI/bge-small-en-v1.5", **fallback_kwargs)
                loaded_model_name = "BAAI/bge-small-en-v1.5"
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
            self._model = model
            self._loaded_model_name = loaded_model_name
            self.active_backend = backend
            self.active_device = str(device)
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

    def _ensure_model(self) -> bool:
        if not self.enabled:
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
        while True:
            if self._model is None and not self._ensure_st_model(ollama_fallback=self.backend == "ollama"):
                return None, self.active_backend or "sentence-transformers"
            model = self._model
            if model is None:
                return None, self.active_backend or "sentence-transformers"
            if (
                self.active_backend == "openvino"
                and str(self.active_device or "").upper().startswith("NPU")
                and len(batch_texts) > 1
            ):
                # The NPU model is compiled for batch 1. If that device rejects a
                # single input and fallback switches accelerators, finish the rest
                # of this logical batch on the new device in one call.
                vectors: list[list[float]] = []
                for index, text in enumerate(batch_texts):
                    item_vectors, active = self._encode_st_batch([text], query=query, priority=priority)
                    if item_vectors is None:
                        return None, active
                    vectors.extend(item_vectors)
                    if not str(self.active_device or "").upper().startswith("NPU"):
                        remaining = batch_texts[index + 1 :]
                        if remaining:
                            rest_vectors, active = self._encode_st_batch(remaining, query=query, priority=priority)
                            if rest_vectors is None:
                                return None, active
                            vectors.extend(rest_vectors)
                        return vectors, active
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
                return vectors, self.active_backend or "sentence-transformers"
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
                data=json.dumps({"model": self._ollama_model_name, "input": texts}).encode("utf-8"),
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
        if not texts:
            return {"success": True, "model": self.model_name, "backend": self.backend, "embeddings": []}

        vectors: list[list[float] | None] = [None] * len(texts)
        missing_texts: list[str] = []
        missing_groups: list[list[int]] = []
        pending_by_key: dict[str, int] = {}
        cache_hits = 0
        cache_identity = self._active_cache_identity
        # Establish a verified identity before the first lookup. Previously this
        # was assigned only after computing a miss, making every fresh process
        # ignore its persistent cross-worktree embedding cache for its first batch.
        if cache_identity is None and self.cache_enabled:
            if self.backend in {"sentence-transformers", "openvino"} and self._ensure_model():
                active = self.active_backend or "sentence-transformers"
                device = self.active_device or self.device
                self._active_cache_identity = f"{active}:{device}:{self._loaded_model_name}"
            elif self.backend == "ollama":
                self._active_cache_identity = f"ollama:{self._ollama_model_name}"
            cache_identity = self._active_cache_identity
        used_backend = self.active_backend or self.backend
        for i, text in enumerate(texts):
            clean_text = str(text).replace("\r\n", "\n")
            key = stable_hash({"identity": cache_identity, "query": query, "text": clean_text}) if cache_identity else ""
            cached = self.cache.get(key) if self.cache_enabled and key else None
            cached_vector = self._valid_cached_vector(cached, cache_identity, self._active_embedding_dimension) if cache_identity else None
            if cached_vector is not None:
                        self.cache.set(
                            key,
                            {"identity": cache_identity, "dimension": len(cached_vector), "vector": cached_vector},
                        )
            if cached_vector is not None:
                vectors[i] = cached_vector
                if self._active_embedding_dimension is None:
                    self._active_embedding_dimension = len(cached_vector)
                self._memory_hits += 1
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
                    execution_identity: tuple[str, str] | None = None
                    switched = False
                    for start in range(0, len(missing_texts), self.batch_size):
                        stop = min(len(missing_texts), start + self.batch_size)
                        batch_texts = missing_texts[start:stop]
                        encoded, active = self._encode_st_batch(batch_texts, query=query, priority=priority)
                        if encoded is None:
                            failed = True
                            break
                        current_identity = (active, str(self.active_device or self.device))
                        if execution_identity is None:
                            execution_identity = current_identity
                        elif current_identity != execution_identity:
                            switched = True
                            break
                        all_st_vectors.extend(encoded)
                        used_backend = active
                    if switched:
                        continue
                    if failed or len(all_st_vectors) != len(missing_texts):
                        return {"success": False, "error": self._load_error or "embedding model disabled", "model": self.model_name}
                    computed_vectors = all_st_vectors
                    break
                if computed_vectors is None:
                    return {"success": False, "error": self._load_error or "embedding accelerator repeatedly changed", "model": self.model_name}

            # 3. Store in vectors and persist to cache
            model_identity = self._ollama_model_name if used_backend == "ollama" else self._loaded_model_name
            if used_backend == "ollama":
                self._active_cache_identity = f"ollama:{model_identity}"
            else:
                self._active_cache_identity = f"{used_backend}:{self.active_device or self.device}:{model_identity}"
            dimensions = {len(vector) for vector in computed_vectors if isinstance(vector, list)}
            if len(dimensions) != 1 or 0 in dimensions:
                return {"success": False, "error": "embedding backend returned inconsistent vector dimensions", "model": self.model_name}
            self._active_embedding_dimension = dimensions.pop()
            for indices, text, vector in zip(missing_groups, missing_texts, computed_vectors):
                for idx in indices:
                    vectors[idx] = vector
                if self.cache_enabled:
                    clean_text = str(text).replace("\r\n", "\n")
                    key = stable_hash({"identity": self._active_cache_identity, "query": query, "text": clean_text})
                    self.cache.set(key, {"identity": self._active_cache_identity, "dimension": self._active_embedding_dimension, "vector": vector})
                self._computed += 1
            self._batch_deduplicated += batch_deduplicated

        return {
            "success": True,
            "model": self.model_name,
            "backend": used_backend,
            "device": self.active_device or self.device,
            "embeddings": vectors,
            "cache_hits": cache_hits,
            "computed": len(missing_texts),
            "unique_computed": len(missing_texts),
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
