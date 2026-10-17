from __future__ import annotations

import math
import os
import threading
import time
from typing import Any

from .cache import SQLiteCache, SingleFlightGroup, TieredCache, stable_hash
from .priority_gate import CooperativePriorityGate
from .accelerators import openvino_cache_dir, openvino_device_candidates
from .state_paths import configured_state_dir
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


class Reranker:
    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config if isinstance(config, dict) else {}
        self.config = cfg
        models_cfg = cfg.get("models", {}) if isinstance(cfg.get("models"), dict) else {}
        features_cfg = cfg.get("features", {}) if isinstance(cfg.get("features"), dict) else {}
        cpu_cfg = cfg.get("cpu_retrieval", {}) if isinstance(cfg.get("cpu_retrieval"), dict) else {}
        cache_cfg = cfg.get("cache", {}) if isinstance(cfg.get("cache"), dict) else {}

        raw_model = models_cfg.get("reranker")
        self.model_name = str(raw_model or "BAAI/bge-reranker-base").replace("\x00", "").strip() or "BAAI/bge-reranker-base"
        self.device = str(models_cfg.get("reranker_device", "cpu")).replace("\x00", "").strip() or "cpu"
        self.backend = str(models_cfg.get("reranker_backend", "torch")).replace("\x00", "").strip().lower() or "torch"
        self.active_backend: str | None = None
        self.active_device: str | None = None
        self._candidates: list[tuple[str, str]] | None = None
        self._candidate_index = -1
        self.enabled = bool(features_cfg.get("reranker", True))
        self.batch_size = max(1, _safe_int(cpu_cfg.get("reranker_batch_size"), 16))
        self.max_length = max(128, _safe_int(cpu_cfg.get("reranker_max_length"), 1024))
        self._model = None
        self._load_lock = threading.Lock()
        self._predict_lock = threading.Lock()
        self._cpu_gate = CooperativePriorityGate(_safe_int(cpu_cfg.get("foreground_priority"), 3))
        self._load_error: str | None = None
        self._load_error_time: float = 0.0
        self.flight_group = SingleFlightGroup(shards=16, default_timeout_seconds=60.0)
        self.cache_enabled = bool(cache_cfg.get("reranker", True))
        self.cache = TieredCache(
            SQLiteCache(
                configured_state_dir(cfg) / "cache.sqlite",
                namespace=f"rerank:{self.model_name}",
                ttl_seconds=_safe_int(cache_cfg.get("reranker_ttl_seconds"), 14 * 86400),
                max_entries=_safe_int(cache_cfg.get("reranker_max_entries"), 100_000),
            ),
            l1_entries=_safe_int(cache_cfg.get("l1_reranker_entries"), 4096),
            l1_ttl_seconds=_safe_int(cache_cfg.get("l1_reranker_ttl_seconds"), 3600),
        )
        self._cache_hits = 0
        self._computed = 0

    def is_enabled(self) -> bool:
        return self.enabled

    def is_loaded(self) -> bool:
        return self._model is not None

    def active_model_name(self) -> str:
        return self.model_name

    def _loaded_model_revision(self) -> str | None:
        model = self._model
        for candidate in (model, getattr(model, "model", None)):
            config = getattr(candidate, "config", None)
            revision = getattr(config, "_commit_hash", None)
            if isinstance(revision, str) and revision.strip():
                value = revision.strip().lower()
                if len(value) in {40, 64} and all(char in "0123456789abcdef" for char in value):
                    return value
        return None

    def _execution_identity(self) -> str:
        backend = self.active_backend or self.backend
        device = str(self.active_device or self.device or "cpu").strip().lower()
        revision = self._loaded_model_revision() or ""
        return stable_hash({
            "backend": backend,
            "device": device,
            "model": self.model_name,
            "revision": revision,
            "max_length": self.max_length,
        })

    def _cache_identity(self, *, allow_cpu_fallback: bool = True) -> str | None:
        if self._loaded_model_revision() is None:
            return None
        return stable_hash({
            "execution": self._execution_identity(),
            "allow_cpu_fallback": allow_cpu_fallback,
        })

    def _candidate_specs(self) -> list[tuple[str, str]]:
        if self.backend == "openvino":
            candidates = [("openvino", device) for device in openvino_device_candidates(self.config, self.device)]
            openvino_cfg = self.config.get("openvino") if isinstance(self.config, dict) else None
            cpu_fallback = bool(openvino_cfg.get("cpu_fallback", True)) if isinstance(openvino_cfg, dict) else True
            if cpu_fallback:
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
            if backend == "torch" or str(device).lower() == "cpu":
                try:
                    import torch
                    if hasattr(torch, "set_num_threads") and torch.get_num_threads() > 4:
                        torch.set_num_threads(max(1, min(4, (os.cpu_count() or 4) // 2)))
                except Exception:
                    pass
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
            def _create_cross_encoder():
                try:
                    return CrossEncoder(self.model_name, local_files_only=True, **kwargs)
                except Exception:
                    models_cfg = self.config.get("models") if isinstance(self.config, dict) else None
                    allow_hf = models_cfg.get("allow_hf_downloads") is True if isinstance(models_cfg, dict) else False
                    if not allow_hf:
                        raise
                    return CrossEncoder(self.model_name, **kwargs)

            self._model = load_model(
                self,
                uses_cuda=uses_torch_cuda(backend, device),
                factory=_create_cross_encoder,
            )
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

    def _ensure_model(self, *, allow_cpu_fallback: bool = True) -> bool:
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
                if not allow_cpu_fallback and str(candidates[index][1]).strip().lower().startswith("cpu"):
                    continue
                if self._load_candidate(index):
                    return True
            return False

    def release(self, timeout_seconds: float = 3.0) -> bool:
        """Detach the reranker model; CUDA allocator cleanup remains best-effort."""
        with acquire_locks((self._predict_lock, self._load_lock), timeout_seconds) as acquired:
            if not acquired:
                return False
            model = self._model
            if model is None:
                return False
            used_cuda = uses_torch_cuda(self.active_backend, self.active_device)
            self._model = None
            self.active_backend = None
            self.active_device = None
            self._candidates = None
            self._candidate_index = -1
            del model
            release_model(self, used_cuda=used_cuda)
            return True

    def _predict(
        self, pairs: list[tuple[str, str]], *, priority: int, allow_cpu_fallback: bool = True
    ) -> Any | None:
        while True:
            if not self._ensure_model(allow_cpu_fallback=allow_cpu_fallback):
                return None
            if self._model is None:
                continue
            try:
                with self._cpu_gate.slot(priority):
                    with self._predict_lock:
                        model = self._model
                        if model is None:
                            continue
                        return model.predict(pairs, batch_size=self.batch_size, show_progress_bar=False)
            except Exception as exc:
                if self.backend == "openvino" and self.active_backend == "openvino":
                    failed = self.active_device or "openvino"
                    self._load_error = f"openvino/{failed} inference failed: {exc}"
                    self._load_error_time = time.time()
                    self._model = None
                    self.active_backend = None
                    self.active_device = None
                    if self._ensure_model(allow_cpu_fallback=allow_cpu_fallback):
                        continue
                return None

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int | None = None,
        priority: int = 3,
        allow_cpu_fallback: bool = True,
    ) -> dict[str, Any]:
        if not documents or not isinstance(documents, (list, tuple)):
            return {"success": True, "model": self.model_name, "results": []}
        clean_docs = [str(d or "").replace("\x00", "") for d in documents if d is not None]
        if not clean_docs:
            return {"success": True, "model": self.model_name, "results": []}
        if not self._ensure_model(allow_cpu_fallback=allow_cpu_fallback):
            return {"success": False, "error": self._load_error or "reranker disabled", "results": []}
        if not allow_cpu_fallback and str(self.active_device or "").strip().lower().startswith("cpu"):
            return {"success": False, "error": "CPU reranking disabled for this request", "results": []}

        clean_query = str(query or "").replace("\x00", "").strip()
        clean_priority = _safe_int(priority, 3)
        clean_top_k: int | None = None
        if top_k is not None and not isinstance(top_k, bool):
            try:
                if isinstance(top_k, float) and not math.isfinite(top_k):
                    clean_top_k = len(clean_docs)
                else:
                    clean_top_k = max(1, int(top_k))
            except (ValueError, TypeError, OverflowError):
                clean_top_k = len(clean_docs)

        request_key = stable_hash({
            "execution": self._execution_identity(),
            "query": clean_query,
            "documents": clean_docs,
            "top_k": clean_top_k,
            "allow_cpu_fallback": allow_cpu_fallback,
        })
        result, _coalesced = self.flight_group.do(
            request_key,
            lambda: self._rerank_uncached(
                clean_query,
                clean_docs,
                top_k=clean_top_k,
                priority=clean_priority,
                allow_cpu_fallback=allow_cpu_fallback,
            ),
        )
        output = dict(result)
        if isinstance(output.get("results"), list):
            output["results"] = [dict(item) if isinstance(item, dict) else item for item in output["results"]]
        return output

    def _rerank_uncached(
        self,
        query: str,
        documents: list[str],
        top_k: int | None = None,
        priority: int = 3,
        allow_cpu_fallback: bool = True,
    ) -> dict[str, Any]:

        # OpenVINO may compile successfully for NPU and then reject a real input
        # shape at predict time.  Keep each logical ranking on exactly one
        # backend/device: if inference falls through NPU -> GPU -> CPU, restart
        # lookups/computation under the new identity instead of mixing scores or
        # writing GPU results into NPU cache keys.
        max_restarts = max(1, len(self._candidate_specs()) + 1)
        for _restart in range(max_restarts):
            execution_identity = self._execution_identity()
            cache_identity = self._cache_identity(allow_cpu_fallback=allow_cpu_fallback)
            use_cache = self.cache_enabled and cache_identity is not None
            scores: list[float | None] = [None] * len(documents)
            missing_pairs: list[tuple[str, str]] = []
            missing_indices: list[int] = []
            missing_keys: list[str] = []
            local_cache_hits = 0

            for i, doc in enumerate(documents):
                key = stable_hash({"identity": cache_identity, "q": query, "d": doc}) if use_cache else ""
                cached = self.cache.get(key) if use_cache else None
                try:
                    cached_score = float(cached)
                except (TypeError, ValueError, OverflowError):
                    cached_score = float("nan")
                if isinstance(cached, (int, float)) and not isinstance(cached, bool) and math.isfinite(cached_score):
                    scores[i] = cached_score
                    local_cache_hits += 1
                else:
                    missing_pairs.append((query, doc))
                    missing_indices.append(i)
                    missing_keys.append(key)

            pending_writes: list[tuple[str, float]] = []
            switched = False
            if missing_pairs:
                micro_batch_size = 2
                for start in range(0, len(missing_pairs), micro_batch_size):
                    stop = min(len(missing_pairs), start + micro_batch_size)
                    predicted = self._predict(
                        missing_pairs[start:stop],
                        priority=priority,
                        allow_cpu_fallback=allow_cpu_fallback,
                    )
                    if predicted is None:
                        return {"success": False, "error": self._load_error or "reranker backend unavailable", "results": []}
                    try:
                        predicted_count = len(predicted)
                    except TypeError:
                        predicted_count = -1
                    if predicted_count != stop - start:
                        return {"success": False, "error": "reranker returned invalid score count", "results": []}
                    if self._execution_identity() != execution_identity:
                        switched = True
                        break
                    for idx, key, score in zip(missing_indices[start:stop], missing_keys[start:stop], predicted):
                        if isinstance(score, bool):
                            return {"success": False, "error": "reranker returned invalid score", "results": []}
                        try:
                            value = float(score)
                        except (TypeError, ValueError, OverflowError):
                            return {"success": False, "error": "reranker returned invalid score", "results": []}
                        if not math.isfinite(value):
                            return {"success": False, "error": "reranker returned invalid score", "results": []}
                        scores[idx] = value
                        pending_writes.append((key, value))

            if switched:
                continue

            if any(score is None for score in scores):
                return {"success": False, "error": "reranker returned incomplete scores", "results": []}

            if use_cache:
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
                "cache_enabled": use_cache,
                **({} if use_cache else {"cache_bypass_reason": "loaded_model_revision_unavailable"}),
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
