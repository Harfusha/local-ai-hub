from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .cache import SQLiteCache, SingleFlightGroup, TieredCache, stable_hash
from .priority_gate import CooperativePriorityGate


class EmbeddingModel:
    """Lazy local embeddings with GPU acceleration, CPU fallback and cross-workspace persistent cache."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        models = config.get("models", {})
        self.model_name = models.get("embedding", "qwen3-embedding:0.6b")
        self.device = models.get("embedding_device", "cpu")
        self.backend = models.get("embedding_backend", "auto")
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
        state_dir = Path(config.get("server", {}).get("state_dir", "."))
        self.cache = TieredCache(
            SQLiteCache(
                state_dir / "cache.sqlite3",
                # v2 separates entries by the model/backend that actually produced
                # them; auto mode may legitimately fall back at runtime.
                namespace="embed:v2",
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

    def _ensure_model(self) -> bool:
        if not self.enabled:
            return False
        if self.backend == "ollama":
            return True
        if self._model is not None:
            return True
        if self._load_error is not None and self.backend == "sentence-transformers":
            import time
            if time.time() - self._load_error_time < 60.0:
                return False
            self._load_error = None
        with self._load_lock:
            if self._model is not None:
                return True
            try:
                from sentence_transformers import SentenceTransformer
                loaded_model_name = self.model_name
                try:
                    self._model = SentenceTransformer(self.model_name, device=self.device, trust_remote_code=self.trust_remote_code)
                except Exception:
                    # Fallback to standard BAAI/bge-small-en-v1.5 if custom model fails
                    if self.model_name != "BAAI/bge-small-en-v1.5":
                        self._model = SentenceTransformer("BAAI/bge-small-en-v1.5", device=self.device)
                        loaded_model_name = "BAAI/bge-small-en-v1.5"
                    else:
                        raise
                if hasattr(self._model, "max_seq_length"):
                    max_pos = getattr(self._model, "max_seq_length", 512) or 512
                    try:
                        max_pos = int(getattr(self._model[0].auto_model.config, "max_position_embeddings", max_pos) or max_pos)
                    except Exception:
                        pass
                    self._model.max_seq_length = min(self.max_seq_length, max_pos)
                self._loaded_model_name = loaded_model_name
                return True
            except Exception as exc:
                import time
                self._load_error = str(exc)
                self._load_error_time = time.time()
                return False

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
            if self.backend == "sentence-transformers" and self._ensure_model():
                self._active_cache_identity = f"sentence-transformers:{self._loaded_model_name}"
            elif self.backend == "ollama":
                self._active_cache_identity = f"ollama:{self._ollama_model_name}"
            cache_identity = self._active_cache_identity
        used_backend = self.backend
        for i, text in enumerate(texts):
            clean_text = str(text).replace("\r\n", "\n")
            key = stable_hash({"v": 2, "identity": cache_identity, "query": query, "text": clean_text}) if cache_identity else ""
            cached = self.cache.get(key) if self.cache_enabled and key else None
            if isinstance(cached, dict):
                cached_vector = cached.get("vector")
                cached_dimension = cached.get("dimension")
                if (cached.get("identity") == cache_identity and isinstance(cached_vector, list)
                        and isinstance(cached_dimension, int) and cached_dimension == len(cached_vector)
                        and (self._active_embedding_dimension is None or cached_dimension == self._active_embedding_dimension)):
                    vectors[i] = [float(v) for v in cached_vector]
                    self._memory_hits += 1
                    cache_hits += 1
                    continue
            # The same content is common across worktrees and generated/copied
            # files. Cache keys are content-addressed, so collapse duplicate misses
            # before invoking a model and fan one vector back out to every position.
            pending_key = key or stable_hash({"v": 1, "query": query, "text": text})
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

            # 2. Fallback to SentenceTransformers CPU
            if computed_vectors is None:
                # When backend is "ollama" but Ollama failed, we need to force-load SentenceTransformer
                if self.backend == "ollama" and self._model is None:
                    with self._load_lock:
                        if self._model is None:
                            try:
                                from sentence_transformers import SentenceTransformer
                                self._model = SentenceTransformer(self.model_name, device=self.device, trust_remote_code=self.trust_remote_code)
                                if hasattr(self._model, "max_seq_length"):
                                    self._model.max_seq_length = self.max_seq_length
                            except Exception as exc:
                                self._load_error = str(exc)
                if not self._ensure_model() or self._model is None:
                    return {"success": False, "error": self._load_error or "embedding model disabled", "model": self.model_name}
                prompts = getattr(self._model, "prompts", {}) or {}
                all_st_vectors: list[list[float]] = []
                for start in range(0, len(missing_texts), self.batch_size):
                    stop = min(len(missing_texts), start + self.batch_size)
                    batch_texts = missing_texts[start:stop]
                    kwargs: dict[str, Any] = {
                        "normalize_embeddings": True, "show_progress_bar": False, "batch_size": self.batch_size
                    }
                    if query and isinstance(prompts, dict) and "query" in prompts:
                        kwargs["prompt_name"] = "query"
                    with self._cpu_gate.slot(priority):
                        encoded = self._model.encode(batch_texts, **kwargs)
                    for vector in encoded:
                        as_list = vector.tolist() if hasattr(vector, "tolist") else list(vector)
                        all_st_vectors.append([float(v) for v in as_list])
                computed_vectors = all_st_vectors
                used_backend = "sentence-transformers"

            # 3. Store in vectors and persist to cache
            model_identity = self._ollama_model_name if used_backend == "ollama" else self._loaded_model_name
            self._active_cache_identity = f"{used_backend}:{model_identity}"
            dimensions = {len(vector) for vector in computed_vectors if isinstance(vector, list)}
            if len(dimensions) != 1 or 0 in dimensions:
                return {"success": False, "error": "embedding backend returned inconsistent vector dimensions", "model": self.model_name}
            self._active_embedding_dimension = dimensions.pop()
            for indices, text, vector in zip(missing_groups, missing_texts, computed_vectors):
                for idx in indices:
                    vectors[idx] = vector
                if self.cache_enabled:
                    clean_text = str(text).replace("\r\n", "\n")
                    key = stable_hash({"v": 2, "identity": self._active_cache_identity, "query": query, "text": clean_text})
                    self.cache.set(key, {"identity": self._active_cache_identity, "dimension": self._active_embedding_dimension, "vector": vector})
                self._computed += 1
            self._batch_deduplicated += batch_deduplicated

        return {
            "success": True,
            "model": self.model_name,
            "backend": used_backend,
            "device": self.device,
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
            "device": self.device,
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
