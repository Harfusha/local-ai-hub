from __future__ import annotations

import threading
import time
from typing import Any

from .cache import SQLiteCache, SingleFlightGroup, TieredCache, stable_hash
from .priority_gate import CooperativePriorityGate
from .accelerators import openvino_cache_dir, openvino_device_candidates
from .state_paths import configured_state_dir


class Reranker:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.model_name = config.get("models", {}).get("reranker", "BAAI/bge-reranker-base")
        self.device = str(config.get("models", {}).get("reranker_device", "cpu")).strip() or "cpu"
        self.backend = str(config.get("models", {}).get("reranker_backend", "torch")).strip().lower()
        self.active_backend: str | None = None
        self.active_device: str | None = None
        self._candidates: list[tuple[str, str]] | None = None
        self._candidate_index = -1
        self.enabled = bool(config.get("features", {}).get("reranker", True))
        cpu_cfg = config.get("cpu_retrieval", {})
        self.batch_size = max(1, int(cpu_cfg.get("reranker_batch_size", 16)))
        self.max_length = max(128, int(cpu_cfg.get("reranker_max_length", 1024)))
        self._model = None
        self._load_lock = threading.Lock()
        self._predict_lock = threading.Lock()
        self._cpu_gate = CooperativePriorityGate(int(cpu_cfg.get("foreground_priority", 3)))
        self._load_error: str | None = None
        self._load_error_time: float = 0.0
        self.flight_group = SingleFlightGroup(shards=16, default_timeout_seconds=60.0)
        cache_cfg = config.get("cache", {})
        self.cache_enabled = bool(cache_cfg.get("reranker", True))
        self.cache = TieredCache(
            SQLiteCache(
                configured_state_dir(config) / "cache.sqlite3",
                namespace=f"rerank:{self.model_name}",
                ttl_seconds=int(cache_cfg.get("reranker_ttl_seconds", 14 * 86400)),
                max_entries=int(cache_cfg.get("reranker_max_entries", 100_000)),
            ),
            l1_entries=int(cache_cfg.get("l1_reranker_entries", 4096)),
            l1_ttl_seconds=int(cache_cfg.get("l1_reranker_ttl_seconds", 3600)),
        )
        self._cache_hits = 0
        self._computed = 0

    def _cache_identity(self) -> str:
        backend = self.active_backend or self.backend
        device = str(self.active_device or self.device or "cpu").strip().lower()
        return f"{backend}:{device}:{self.model_name}"

    def _candidate_specs(self) -> list[tuple[str, str]]:
        if self.backend == "openvino":
            candidates = [("openvino", device) for device in openvino_device_candidates(self.config, self.device)]
            if bool(self.config.get("openvino", {}).get("cpu_fallback", True)):
                candidates.append(("torch", "cpu"))
            result: list[tuple[str, str]] = []
            seen: set[tuple[str, str]] = set()
            for backend, device in candidates:
                key = (backend, str(device).upper())
                if key not in seen:
                    seen.add(key)
                    result.append((backend, device))
            return result
        return [("torch", self.device)]

    def _load_candidate(self, index: int) -> bool:
        candidates = self._candidate_specs()
        if index < 0 or index >= len(candidates):
            return False
        backend, device = candidates[index]
        self._candidates = candidates
        self._candidate_index = index
        try:
            from sentence_transformers import CrossEncoder
            kwargs: dict[str, Any] = {
                "device": str(device).lower(),
                "max_length": self.max_length,
            }
            if backend == "openvino":
                # See EmbeddingModel: accelerator placement belongs to the
                # Optimum/OpenVINO model, while the SentenceTransformers wrapper
                # remains on CPU. This works even when torch has no native NPU
                # device registered.
                kwargs["device"] = "cpu"
                kwargs["backend"] = "openvino"
                ov_model_kwargs: dict[str, Any] = {"device": str(device).lower()}
                cache_dir = openvino_cache_dir(self.config)
                if cache_dir is not None:
                    ov_model_kwargs["ov_config"] = {"CACHE_DIR": str(cache_dir)}
                kwargs["model_kwargs"] = ov_model_kwargs
            self._model = CrossEncoder(self.model_name, **kwargs)
            self.active_backend = backend
            self.active_device = str(device)
            self._load_error = None
            return True
        except Exception as exc:
            self._model = None
            self._load_error = f"{backend}/{device}: {exc}"
            self._load_error_time = time.time()
            self.active_backend = None
            self.active_device = None
            return False

    def _ensure_model(self) -> bool:
        if not self.enabled:
            return False
        if self._model is not None:
            return True
        with self._load_lock:
            if self._model is not None:
                return True
            candidates = self._candidate_specs()
            start = max(0, self._candidate_index + 1) if self._candidates == candidates else 0
            if self._load_error is not None and start >= len(candidates) and time.time() - self._load_error_time < 15.0:
                return False
            for index in range(start, len(candidates)):
                if self._load_candidate(index):
                    return True
            return False

    def _predict(self, pairs: list[tuple[str, str]], *, priority: int) -> Any | None:
        while True:
            if not self._ensure_model() or self._model is None:
                return None
            try:
                with self._cpu_gate.slot(priority):
                    with self._predict_lock:
                        return self._model.predict(pairs, batch_size=self.batch_size, show_progress_bar=False)
            except Exception as exc:
                if self.backend == "openvino" and self.active_backend == "openvino":
                    failed = self.active_device or "openvino"
                    self._load_error = f"openvino/{failed} inference failed: {exc}"
                    self._load_error_time = time.time()
                    self._model = None
                    self.active_backend = None
                    self.active_device = None
                    if self._ensure_model():
                        continue
                return None

    def rerank(self, query: str, documents: list[str], top_k: int | None = None, priority: int = 3) -> dict[str, Any]:
        if not documents:
            return {"success": True, "model": self.model_name, "results": []}
        if not self._ensure_model():
            return {"success": False, "error": self._load_error or "reranker disabled", "results": []}

        # OpenVINO may compile successfully for NPU and then reject a real input
        # shape at predict time.  Keep each logical ranking on exactly one
        # backend/device: if inference falls through NPU -> GPU -> CPU, restart
        # lookups/computation under the new identity instead of mixing scores or
        # writing GPU results into NPU cache keys.
        max_restarts = max(1, len(self._candidate_specs()) + 1)
        for _restart in range(max_restarts):
            execution_identity = self._cache_identity()
            scores: list[float | None] = [None] * len(documents)
            missing_pairs: list[tuple[str, str]] = []
            missing_indices: list[int] = []
            missing_keys: list[str] = []
            local_cache_hits = 0

            for i, doc in enumerate(documents):
                key = stable_hash({"identity": execution_identity, "q": query, "d": doc})
                cached = self.cache.get(key) if self.cache_enabled else None
                if isinstance(cached, (int, float)):
                    scores[i] = float(cached)
                    local_cache_hits += 1
                else:
                    missing_pairs.append((query, doc))
                    missing_indices.append(i)
                    missing_keys.append(key)

            pending_writes: list[tuple[str, float]] = []
            switched = False
            if missing_pairs:
                for start in range(0, len(missing_pairs), self.batch_size):
                    stop = min(len(missing_pairs), start + self.batch_size)
                    predicted = self._predict(missing_pairs[start:stop], priority=priority)
                    if predicted is None:
                        return {"success": False, "error": self._load_error or "reranker backend unavailable", "results": []}
                    if self._cache_identity() != execution_identity:
                        switched = True
                        break
                    for idx, key, score in zip(missing_indices[start:stop], missing_keys[start:stop], predicted):
                        value = float(score)
                        scores[idx] = value
                        pending_writes.append((key, value))

            if switched:
                continue

            if any(score is None for score in scores):
                return {"success": False, "error": "reranker returned incomplete scores", "results": []}

            if self.cache_enabled:
                for key, value in pending_writes:
                    self.cache.set(key, value)
            self._cache_hits += local_cache_hits
            self._computed += len(pending_writes)

            ranked = sorted(
                ({"index": i, "score": float(score), "text": documents[i]} for i, score in enumerate(scores)),
                key=lambda x: x["score"], reverse=True,
            )
            if top_k is not None:
                ranked = ranked[: max(1, int(top_k))]
            return {
                "success": True, "model": self.model_name, "backend": self.active_backend or self.backend,
                "device": self.active_device or self.device, "results": ranked,
                "cache_hits": local_cache_hits, "computed": len(pending_writes),
            }

        return {"success": False, "error": "reranker accelerator repeatedly changed", "results": []}

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "model": self.model_name,
            "backend": self.backend,
            "active_backend": self.active_backend,
            "device": self.device,
            "active_device": self.active_device,
            "loaded": self._model is not None,
            "load_error": self._load_error,
            "cache_enabled": self.cache_enabled,
            "cache": self.cache.stats(),
            "cache_hits_runtime": self._cache_hits,
            "computed_runtime": self._computed,
            "batch_size": self.batch_size,
            "max_length": self.max_length,
            "priority_gate": self._cpu_gate.status(),
        }
