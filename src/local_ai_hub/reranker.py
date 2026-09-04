from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from .cache import SQLiteCache, SingleFlightGroup, TieredCache, stable_hash
from .priority_gate import CooperativePriorityGate


class Reranker:
    def __init__(self, config: dict[str, Any]):
        self.model_name = config.get("models", {}).get("reranker", "BAAI/bge-reranker-base")
        self.device = config.get("models", {}).get("reranker_device", "cpu")
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
                Path(config["server"]["state_dir"]) / "cache.sqlite3",
                namespace=f"rerank:{self.model_name}",
                ttl_seconds=int(cache_cfg.get("reranker_ttl_seconds", 14 * 86400)),
                max_entries=int(cache_cfg.get("reranker_max_entries", 100_000)),
            ),
            l1_entries=int(cache_cfg.get("l1_reranker_entries", 4096)),
            l1_ttl_seconds=int(cache_cfg.get("l1_reranker_ttl_seconds", 3600)),
        )
        self._cache_hits = 0
        self._computed = 0

    def _ensure_model(self) -> bool:
        if not self.enabled:
            return False
        if self._model is not None:
            return True
        now = time.time()
        if self._load_error is not None:
            if now - self._load_error_time < 60.0:
                return False
            self._load_error = None
        with self._load_lock:
            if self._model is not None:
                return True
            try:
                from sentence_transformers import CrossEncoder
                self._model = CrossEncoder(self.model_name, device=self.device, max_length=self.max_length)
                return True
            except Exception as exc:
                self._load_error = str(exc)
                self._load_error_time = time.time()
                return False

    def rerank(self, query: str, documents: list[str], top_k: int | None = None, priority: int = 3) -> dict[str, Any]:
        if not documents:
            return {"success": True, "model": self.model_name, "results": []}
        if not self._ensure_model():
            return {"success": False, "error": self._load_error or "reranker disabled", "results": []}

        scores: list[float | None] = [None] * len(documents)
        missing_pairs: list[tuple[str, str]] = []
        missing_indices: list[int] = []
        missing_keys: list[str] = []
        for i, doc in enumerate(documents):
            key = stable_hash({"q": query, "d": doc})
            cached = self.cache.get(key) if self.cache_enabled else None
            if isinstance(cached, (int, float)):
                scores[i] = float(cached)
                self._cache_hits += 1
            else:
                missing_pairs.append((query, doc))
                missing_indices.append(i)
                missing_keys.append(key)

        if missing_pairs:
            for start in range(0, len(missing_pairs), self.batch_size):
                stop = min(len(missing_pairs), start + self.batch_size)
                with self._cpu_gate.slot(priority):
                    with self._predict_lock:
                        predicted = self._model.predict(
                            missing_pairs[start:stop], batch_size=self.batch_size, show_progress_bar=False
                        )
                for idx, key, score in zip(missing_indices[start:stop], missing_keys[start:stop], predicted):
                    value = float(score)
                    scores[idx] = value
                    if self.cache_enabled:
                        self.cache.set(key, value)
                    self._computed += 1

        ranked = sorted(
            ({"index": i, "score": float(score if score is not None else -9999.0), "text": documents[i]} for i, score in enumerate(scores)),
            key=lambda x: x["score"], reverse=True,
        )
        if top_k is not None:
            ranked = ranked[: max(1, int(top_k))]
        return {
            "success": True, "model": self.model_name, "device": self.device, "results": ranked,
            "cache_hits": len(documents) - len(missing_pairs), "computed": len(missing_pairs),
        }

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "model": self.model_name,
            "device": self.device,
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
