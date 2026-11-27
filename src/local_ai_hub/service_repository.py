from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout

from .services import (
    Any as Any,
    MAX_PAGE_SIZE as MAX_PAGE_SIZE,
    MAX_PAGE_WINDOW as MAX_PAGE_WINDOW,
    Path as Path,
    SchedulerCancelledError as SchedulerCancelledError,
    SchedulerTimeoutError as SchedulerTimeoutError,
    _LinkedCancelEvent as _LinkedCancelEvent,
    __version__ as __version__,
    canonical_root as canonical_root,
    copy as copy,
    keyword as keyword,
    logger as logger,
    pagination_bounds_error as pagination_bounds_error,
    re as re,
    rollout_feature_enabled as rollout_feature_enabled,
    sqlite3 as sqlite3,
    stable_hash as stable_hash,
    stat as stat,
    subprocess as subprocess,
    threading as threading,
)


# OpenVINO's first SentenceTransformers load can take minutes on Windows. Keep
# that cold load outside the HTTP request thread, and allow only one model call
# to own the device while it warms up.
_EMBEDDING_LOAD_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hub-embedding")
_EMBEDDING_LOAD_CAPACITY = threading.BoundedSemaphore(1)
# A completed future may invoke its callback inline while add_done_callback is
# called below, so the callback must be able to reacquire this lock.
_EMBEDDING_LOAD_LOCK = threading.RLock()
_EMBEDDING_LOADS: dict[str, Future[Any]] = {}
_EMBEDDING_LOAD_WAIT_CAP_SECONDS = 8.0


class ServiceRepositoryMixin:
    @staticmethod
    def _embedding_key(text: str, *, backend: str, model: str, query: bool) -> str:
        return stable_hash({
            "kind": "embedding",
            "backend": backend,
            "model": model,
            "query": bool(query),
            "text": str(text),
            "app_version": __version__,
        })

    @staticmethod
    def _json_embedding(vector: Any) -> list[float]:
        if hasattr(vector, "tolist"):
            vector = vector.tolist()
        return [float(value) for value in vector]

    def _encode_openvino_bounded(
        self, texts: list[str], *, model: str, query: bool, priority: int, wait_timeout: float,
    ) -> dict[str, Any]:
        key = stable_hash({
            "service": id(self), "embedder": id(self.embeddings), "model": model,
            "texts": texts, "query": query,
        })
        with _EMBEDDING_LOAD_LOCK:
            future = _EMBEDDING_LOADS.get(key)
            if future is None:
                if not _EMBEDDING_LOAD_CAPACITY.acquire(blocking=False):
                    return {
                        "success": False, "error_code": "embedding_busy",
                        "error": "OpenVINO embedding model is warming up; retry shortly",
                        "operation_not_started": True, "retryable": True, "terminal": False,
                    }
                try:
                    future = _EMBEDDING_LOAD_EXECUTOR.submit(
                        self.embeddings.encode, texts, query=query, priority=priority,
                        wait_timeout_seconds=wait_timeout,
                    )
                except Exception:
                    _EMBEDDING_LOAD_CAPACITY.release()
                    raise
                _EMBEDDING_LOADS[key] = future

                def forget_finished(done: Future[Any]) -> None:
                    with _EMBEDDING_LOAD_LOCK:
                        if _EMBEDDING_LOADS.get(key) is done:
                            _EMBEDDING_LOADS.pop(key, None)
                    _EMBEDDING_LOAD_CAPACITY.release()

                future.add_done_callback(forget_finished)

        bounded_wait = max(0.05, min(float(wait_timeout), _EMBEDDING_LOAD_WAIT_CAP_SECONDS))
        try:
            result = future.result(timeout=bounded_wait)
        except FutureTimeout:
            return {
                "success": False, "error_code": "embedding_warming",
                "error": "OpenVINO embedding model is still warming up",
                "timed_out": True, "outcome_unknown": True, "retryable": True,
                "terminal": False,
            }
        return result if isinstance(result, dict) else {"success": False, "error": "embedding failed"}

    def embed(self, texts: list[str], *, priority: int = 3, query: bool = False,
              background: bool | None = None, wait_timeout: float | None = None,
              cancel_event: threading.Event | None = None) -> dict[str, Any]:
        backend = self.config["models"].get("embedding_backend", "sentence-transformers")
        model = str(self.config.get("models", {}).get("embedding", "qwen3-embedding:0.6b"))
        if not texts:
            return {"success": True, "model": model, "backend": "ollama", "embeddings": []}
        cancelled = {"success": False, "cancelled": True, "error": "embedding cancelled",
                     "terminal": True, "retryable": False}
        if cancel_event is not None and cancel_event.is_set():
            return dict(cancelled, request_not_sent=True, operation_not_started=True)

        def reject_uncertain(result: Any) -> Any:
            flags = ("outcome_unknown", "timed_out", "cancelled", "preempted",
                     "cleanup_unconfirmed", "_lah_partial_response", "in_progress",
                     "output_truncated", "partial")
            if isinstance(result, dict) and any(key in result and result[key] is not False for key in flags):
                result = dict(result)
                result["success"] = False
                result.pop("embeddings", None)
            return result

        def encode_uncached(batch: list[str]) -> dict[str, Any]:
            if backend in {"auto", "sentence-transformers", "openvino"}:
                encode_options = {} if wait_timeout is None else {"wait_timeout_seconds": wait_timeout}
                if backend == "openvino" and wait_timeout is not None:
                    return reject_uncertain(self._encode_openvino_bounded(
                        batch, model=model, query=query, priority=priority, wait_timeout=wait_timeout,
                    ))
                return reject_uncertain(self.embeddings.encode(batch, query=query, priority=priority, **encode_options))
            batch_size = int(self.config.get("rag", {}).get("embedding_batch_size", 12))
            job_cancel = None
            if cancel_event is not None:
                # Scheduler timeouts must signal this job without cancelling the parent request.
                job_cancel = _LinkedCancelEvent(threading.Event(), cancel_event.is_set)
            elif wait_timeout is not None:
                job_cancel = threading.Event()

            def run() -> dict[str, Any]:
                all_vectors: list[list[float]] = []
                for start in range(0, len(batch), batch_size):
                    if job_cancel is not None and job_cancel.is_set():
                        return cancelled
                    response = self.runtime.request("/api/embed", {"model": model, "input": batch[start:start + batch_size]})
                    response = reject_uncertain(response)
                    if isinstance(response, dict) and response.get("success") is False:
                        return response
                    if "error" in response:
                        return {"success": False, "error": response["error"], "model": model}
                    all_vectors.extend(response.get("embeddings", []))
                return {"success": True, "model": model, "backend": "ollama", "embeddings": all_vectors}

            is_bg = background if background is not None else (priority <= 1)
            submit_options = {"cancel_event": job_cancel} if job_cancel is not None else {}
            try:
                return reject_uncertain(self.scheduler.submit(
                    model, source="embed", execute=run, priority=priority,
                    background=is_bg, wait_timeout=wait_timeout, **submit_options,
                ))
            except (SchedulerCancelledError, SchedulerTimeoutError) as exc:
                if job_cancel is None:
                    raise
                pending = exc.state == "pending"
                outcome = "cancelled" if isinstance(exc, SchedulerCancelledError) else "timed_out"
                result = {"success": False, outcome: True, "error": str(exc), "error_code": exc.error_code,
                          "job_id": exc.job_id, "scheduler_state": exc.state,
                          "terminal": pending, "retryable": False}
                if pending:
                    result.update(request_not_sent=True, operation_not_started=True)
                else:
                    result.update(outcome_unknown=True, cleanup_unconfirmed=True)
                return result

        if backend in {"auto", "sentence-transformers", "openvino"}:
            # EmbeddingModel owns the provenance-aware cache. The outer cache
            # is keyed only by the configured name and can mix model spaces.
            result = encode_uncached(list(texts))
            if not isinstance(result, dict):
                return {"success": False, "error": "embedding failed"}
            return result

        # A mutable Ollama tag does not establish which model produced a
        # vector. Deduplicate within this request, but do not reuse a vector
        # across calls without an execution-bound model identity.
        unique_texts = list(dict.fromkeys(texts))
        result = encode_uncached(unique_texts)
        if not isinstance(result, dict) or result.get("success") is not True:
            return result if isinstance(result, dict) else {"success": False, "error": "embedding failed"}
        vectors = result.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(unique_texts):
            return {"success": False, "error": "embedding count mismatch"}
        by_text = dict(zip(unique_texts, vectors))
        result = dict(result)
        result["embeddings"] = [by_text[text] for text in texts]
        return result

    def _context_evidence_current(self, value: Any) -> bool:
        if not isinstance(value, dict) or value.get("success") is False:
            return True
        evidence = value.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            return True
        evidence_store = getattr(self, "evidence_store", None)
        if len(evidence) > 64:
            return False
        try:
            evidence_ids = [
                item.get("evidence_id")
                for item in evidence
                if isinstance(item, dict)
            ]
            if len(evidence_ids) != len(evidence):
                return False
            validate_many = getattr(evidence_store, "validate_current_many", None)
            if callable(validate_many):
                return validate_many(evidence_ids) is True
            validate = getattr(evidence_store, "validate_current", None)
            if not callable(validate):
                return False
            return all(isinstance(item, dict) and isinstance(item.get("evidence_id"), str)
                       and bool(item["evidence_id"]) and validate(item["evidence_id"]) is True
                       for item in evidence)
        except Exception:
            return False

    def _repo_cached(
        self, operation: str, root: str, params: dict[str, Any], compute: Any,
        *, state_override: dict[str, Any] | None = None,
        cache_results: bool = True,
    ) -> dict[str, Any]:
        # Worktrees/temp repositories can disappear between an agent request and a
        # coalesced background computation. Treat that as a stale input, not a hub 500.
        try:
            self._touch_project(root)
            tracker = getattr(self, "repo_state", None)

            if not cache_results:
                state = state_override if isinstance(state_override, dict) else self._repo_cache_state(root) or {}
            elif operation == "search" and tracker is not None:
                # Exact counts cover the whole repository, including files not
                # present in the previous page. A TTL-cached fingerprint cannot
                # prove that no new match appeared since the previous request.
                state = (
                    state_override if isinstance(state_override, dict)
                    else tracker.fingerprint(root, force=True) or {}
                )
            else:
                state = self._repo_cache_state(root) or {}
            fingerprint = state.get("fingerprint")
            changed_files = state.get("changed_files")
            search_state_incomplete = operation == "search" and (
                bool(state.get("degraded") or state.get("stale") or state.get("truncated"))
                or bool(params.get("force_include_patterns"))
                or (isinstance(changed_files, int) and not isinstance(changed_files, bool)
                    and changed_files > getattr(tracker, "max_changed_paths", changed_files))
            )
            if not cache_results:
                raw = compute()
                hit = coalesced = False
                cache_degraded = bool(state.get("degraded", False))
                cache_reason = "live_source_search"
            elif not isinstance(fingerprint, str) or not fingerprint.strip() or search_state_incomplete:
                raw = compute()
                hit = coalesced = False
                cache_degraded = True
                cache_reason = "incomplete_search_fingerprint" if search_state_incomplete else "missing_or_invalid_fingerprint"
            else:
                # Physical-root identity isolates clean clones with otherwise
                # identical fingerprints while collapsing lexical aliases.
                cache_identity = {
                    "op": operation,
                    "root": canonical_root(root),
                    "state": fingerprint,
                    "params": params,
                }
                if operation in {"code-index", "deterministic"}:
                    # Older entries may contain answers from an incomplete foreground refresh.
                    cache_identity["version"] = 2
                key = stable_hash(cache_identity)
                raw, hit, coalesced = self.repo_flight.get_or_compute(key, compute)
                cache_degraded = bool(state.get("degraded", False))
                cache_reason = state.get("degraded_reason")
        except (FileNotFoundError, ValueError) as exc:
            return {
                "success": False,
                "stale_root": True,
                "error": str(exc),
                "error_type": type(exc).__name__,
                "error_code": "stale_repository_input",
                "status_code": 409,
                "terminal": True,
                "retryable": False,
                "operation": operation,
            }
        if operation in {"hybrid-context", "deterministic-context"} and not self._context_evidence_current(raw):
            if hit or coalesced:
                raw = compute()
                hit = coalesced = False
                cache_degraded = True
                cache_reason = "stale_context_evidence"
            if not self._context_evidence_current(raw):
                return {"success": False, "terminal": True, "retryable": False, "stale": True,
                        "root": root, "operation": operation,
                        "error": "context source evidence is stale or cannot be verified"}
        if isinstance(raw, dict):
            result = copy.deepcopy(raw)
            result.pop("_cacheable", None)
        elif raw is not None:
            result = {"result": raw, "success": True}
        else:
            result = {"success": False, "error": f"{operation} computation failed"}
        result["workspace_cache"] = {
            "hit": bool(hit), "coalesced": bool(coalesced), "operation": operation,
            "fingerprint": state.get("fingerprint"), "kind": state.get("kind"),
            "degraded": cache_degraded, "reason": cache_reason,
            "stale": bool(state.get("stale", False)),
        }
        # Promote mechanical cache reuse to the common HTTP contract. This lets
        # clients reuse repository answers and makes endpoint cache hit telemetry
        # comparable with generation cache telemetry.
        result["cache_hit"] = bool(hit)
        result["coalesced"] = bool(coalesced)
        result["cache_layer"] = "workspace" if hit else "workspace-miss"
        if isinstance(raw, dict) and "preprocessed_hit" in raw:
            result["preprocessed_hit"] = bool(raw["preprocessed_hit"])
        return result

    def repo_profile(self, root: str) -> dict[str, Any]:
        return self._repo_cached("profile", root, {}, lambda: self.repo_tools.project_profile(root))

    def repo_search(
        self,
        root: str,
        query: str,
        top_k: int = 12,
        context_lines: int | None = None,
        enrich: bool = False,
        path_hints: list[Any] | tuple[Any, ...] | None = None,
        scope: str = "repo_search",
        *,
        limit: int | None = None,
        offset: int = 0,
        search_mode: str | None = None,
        exact_count: bool = True,
    ) -> dict[str, Any]:
        from .service_repo_search import repo_search as _impl_repo_search
        return _impl_repo_search(
            self,
            root,
            query,
            top_k=top_k,
            context_lines=context_lines,
            enrich=enrich,
            path_hints=path_hints,
            scope=scope,
            limit=limit,
            offset=offset,
            search_mode=search_mode,
            exact_count=exact_count,
        )

    def _repo_rag_search(self, *args: Any, **kwargs: Any) -> Any:
        from .service_repo_search import _repo_rag_search as _impl_rag_search
        return _impl_rag_search(self, *args, **kwargs)

    def _hint_directory_candidates(self, *args: Any, **kwargs: Any) -> Any:
        from .service_repo_search import _hint_directory_candidates as _impl_hint_dir
        return _impl_hint_dir(*args, **kwargs)

    def _repo_search_lexical(self, *args: Any, **kwargs: Any) -> Any:
        from .service_repo_search import _repo_search_lexical as _impl_lexical
        return _impl_lexical(self, *args, **kwargs)

    def _refresh_changed_intelligence(self, root: str) -> bool:
        """Synchronize only Git-changed files before serving a cache-miss intelligence query.

        Preprocessing remains the bulk indexer. This foreground safety net prevents a
        just-edited file from forcing a full rebuild or returning stale deterministic
        facts while the background pipeline is still catching up.
        """
        try:
            state = self._repo_cache_state(root)
            # Background preprocessing owns incremental index updates while active.
            # Do not duplicate that work synchronously inside a foreground query;
            # the durable index is safer than making the feature wait on a large batch.
            if state.get("kind") == "preprocessed-watcher":
                return True
            fp = str(state.get("fingerprint") or "")
            base = Path(root).expanduser().resolve()
            if not fp:
                return self._refresh_index_paths(base, fp, state)
            key = stable_hash({"op": "foreground-index-refresh", "root": str(base), "fingerprint": fp})
            refreshed, _ = self.flight_group.do(key, lambda: self._refresh_index_paths(base, fp, state))
            return refreshed
        except (OSError, sqlite3.Error, ValueError) as refresh_exc:
            logger.debug("Changed-file intelligence refresh skipped (%s)", type(refresh_exc).__name__)
            return False

    def _refresh_index_paths(self, base: Path, fp: str, state: dict[str, Any]) -> bool:
        root_key = str(base)
        try:
            with self._index_refresh_lock:
                if fp and self._index_refresh_state.get(root_key) == fp:
                    return True
            paths = [str(x) for x in state.get("changed_paths", [])][:256]
            if not paths:
                with self._index_refresh_lock:
                    if fp:
                        self._index_refresh_state[root_key] = fp
                return True
            existing: list[tuple[str, str]] = []
            missing: list[str] = []
            complete = True
            for rel in paths:
                try:
                    target = (base / rel).resolve(strict=False)
                    target.relative_to(base)
                except (OSError, RuntimeError, ValueError) as path_exc:
                    if isinstance(path_exc, OSError):
                        complete = False
                    logger.debug(
                        "Changed-file path skipped (%s)",
                        type(path_exc).__name__,
                    )
                    continue
                try:
                    regular = stat.S_ISREG(target.stat().st_mode)
                except (FileNotFoundError, NotADirectoryError):
                    regular = False
                if regular:
                    try:
                        existing.append((rel, self.repo_tools._hash_file_only(target)))
                    except (OSError, ValueError) as hash_exc:
                        complete = False
                        logger.debug(
                            "Changed-file hash skipped (%s)",
                            type(hash_exc).__name__,
                        )
                else:
                    missing.append(rel)
            if self.code_index is not None:
                # A changed source path is not evidence that the Hub used it.
                # Refresh only paths already admitted by demand-driven
                # preprocessing; new paths wait for actual evidence use.
                reindex_existing = getattr(self.code_index, "files_needing_reindex", None)
                indexed_changes = (
                    reindex_existing(str(base), existing, only_existing=True)
                    if existing and callable(reindex_existing) else []
                )
                if indexed_changes and hasattr(self.code_index, "update_files_batch"):
                    outcome = self.code_index.update_files_batch(str(base), indexed_changes)
                    if outcome.get("success") is False or outcome.get("coverage_complete") is False:
                        complete = False
                for rel in missing:
                    try:
                        outcome = self.code_index.update_file(str(base), rel)
                        if outcome.get("success") is False:
                            complete = False
                    except (OSError, sqlite3.Error, ValueError) as index_exc:
                        complete = False
                        logger.debug(
                            "CodeIndex changed-file update skipped (%s)",
                            type(index_exc).__name__,
                        )
            if self.deterministic is not None and getattr(self.deterministic, "enabled", True):
                if existing and hasattr(self.deterministic, "update_files_batch"):
                    outcome = self.deterministic.update_files_batch(str(base), existing)
                    if outcome.get("success") is False or outcome.get("failed"):
                        complete = False
                for rel in missing:
                    try:
                        outcome = self.deterministic.update_file(str(base), rel)
                        if outcome.get("success") is False:
                            complete = False
                    except (OSError, sqlite3.Error, ValueError) as index_exc:
                        complete = False
                        logger.debug(
                            "Deterministic changed-file update skipped (%s)",
                            type(index_exc).__name__,
                        )
            with self._index_refresh_lock:
                if fp and complete:
                    self._index_refresh_state[root_key] = fp
                    if len(self._index_refresh_state) > 256:
                        self._index_refresh_state.pop(next(iter(self._index_refresh_state)), None)
            return complete
        except (OSError, sqlite3.Error, ValueError) as refresh_exc:
            # Query correctness still falls back to the last durable index plus exact
            # lexical/source tools; this accelerator must never turn a query into 500.
            logger.debug(
                "Changed-file intelligence refresh skipped (%s)",
                type(refresh_exc).__name__,
            )
            return False

    def deterministic_query(self, root: str, query: str, limit: int = 24) -> dict[str, Any]:
        if self.deterministic is None:
            return {"success": False, "error": "deterministic engine unavailable", "confidence": 0.0}
        if self.learner is not None:
            try: self.learner.record(root, query)
            except Exception: pass
        try:
            canonical = {
                "intent": self.deterministic.classify_intent(query).get("intent", "general"),
                "terms": sorted(set(self.deterministic._terms(query))),
                "limit": limit,
            }
        except Exception:
            canonical = {"query": " ".join(query.lower().split()), "limit": limit}
        def compute() -> dict[str, Any]:
            refreshed = self._refresh_changed_intelligence(root)
            result = self.deterministic.query(root, query, limit)
            if refreshed is False:
                result = {**result, "stale": True, "degraded": True, "_cacheable": False}
            return result
        return self._repo_cached("deterministic", root, canonical, compute)

    def code_query(self, root: str, query: str, limit: int = 24, include_code: bool = False, offset: int = 0) -> dict[str, Any]:
        bounds_error = pagination_bounds_error(limit, offset)
        if bounds_error:
            return {"success": False, "error": bounds_error, "status_code": 400,
                    "limit": limit if isinstance(limit, int) and not isinstance(limit, bool) and 1 <= limit <= MAX_PAGE_SIZE else None,
                    "offset": offset if isinstance(offset, int) and not isinstance(offset, bool) and 0 <= offset < MAX_PAGE_WINDOW else None,
                    "total_matches": 0, "has_more": False, "symbols": []}
        if self.code_index is None:
            return {"success": False, "error": "code index unavailable", "status_code": 503, "limit": limit, "offset": offset, "total_matches": 0, "has_more": False, "symbols": []}
        if self.learner is not None:
            try: self.learner.record(root, query)
            except Exception: pass
        try:
            # Exact identifier lookup differs from a token-equivalent fuzzy
            # query (generate_tests versus generate tests).
            canonical = {"query": query, "terms": sorted(set(self.code_index._query_terms(query))), "limit": limit, "offset": offset, "include_code": include_code}
        except Exception:
            canonical = {"query": " ".join(query.lower().split()), "limit": limit, "offset": offset, "include_code": include_code}
        def compute() -> dict[str, Any]:
            refreshed = self._refresh_changed_intelligence(root)
            res = self.code_index.query(root, query, limit=limit, offset=offset)
            if isinstance(res, dict):
                if refreshed is False:
                    res = {**res, "stale": True, "degraded": True, "_cacheable": False}
                res["preprocessed_hit"] = bool(res.get("success") and res.get("symbols"))
                if include_code and res.get("symbols") and self.repo_tools is not None:
                    for sym in res["symbols"][:5]:
                        fp = sym.get("file") or sym.get("path")
                        sl = int(sym.get("line") or 1)
                        el = int(sym.get("end_line") or (sl + 30))
                        if fp:
                            slice_res = self.repo_tools.file_slice(root, fp, start_line=sl, end_line=min(el, sl + 60), max_chars=2500)
                            if slice_res.get("success"):
                                sym["code"] = slice_res.get("text")
            return res
        return self._repo_cached("code-index", root, canonical, compute)

    def repo_investigate(
        self,
        root: str,
        query: str,
        path: str = "",
        include_code: bool = True,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Single-roundtrip smart investigation for cloud models."""
        cq_res = self.code_query(root, query, limit=limit, include_code=include_code)
        symbols = cq_res.get("symbols", []) if isinstance(cq_res, dict) else []

        search_hits = []
        if len(symbols) < 2:
            s_res = self.repo_search(root, query, top_k=limit)
            if isinstance(s_res, dict):
                search_hits = s_res.get("results", []) or s_res.get("hits", [])
                if include_code and self.repo_tools is not None:
                    for hit in search_hits[:3]:
                        h_path = hit.get("path") or hit.get("file")
                        h_line = int(hit.get("line") or 1)
                        if h_path:
                            sl_res = self.repo_tools.file_slice(root, h_path, start_line=max(1, h_line - 5), end_line=h_line + 30, max_chars=2000)
                            if sl_res.get("success"):
                                hit["code"] = sl_res.get("text")

        primary_sym = symbols[0].get("name", "") if symbols else (search_hits[0].get("name", "") if search_hits else query)
        callers: list[dict[str, Any]] = []
        if primary_sym and self.code_index is not None:
            try:
                ref_res = self.code_index.find_referencing_symbols(root, primary_sym)
                if isinstance(ref_res, dict) and ref_res.get("success"):
                    callers = ref_res.get("references", [])[:10]
            except (OSError, sqlite3.Error, ValueError) as reference_exc:
                logger.debug(
                    "Repository investigation references skipped (%s)",
                    type(reference_exc).__name__,
                )

        related_tests: list[str] = []
        try:
            target_files = [s.get("file") for s in symbols if s.get("file")]
            if target_files:
                aff_res = self.affected_tests(root, changed_paths=target_files)
                if isinstance(aff_res, dict):
                    related_tests = aff_res.get("test_files", [])[:5]
        except (OSError, sqlite3.Error, ValueError) as tests_exc:
            logger.debug(
                "Related test lookup skipped (%s)",
                type(tests_exc).__name__,
            )

        return {
            "success": True,
            "query": query,
            "root": root,
            "primary_symbol": primary_sym,
            "symbols": symbols[:limit],
            "search_hits": search_hits[:limit] if not symbols else [],
            "callers": callers[:10],
            "related_tests": related_tests,
            "cascade_layers": ["code_index", "tests"] if symbols else ["search", "tests"],
        }

    def repo_diagnose(self, root: str, text: str) -> dict[str, Any]:
        """Parse stack traces / crash logs and fetch inline code snippets for each frame."""
        resolved_root = canonical_root(root)
        if not Path(resolved_root).is_dir():
            return {"success": False, "error": "Root directory does not exist"}

        if not text or not text.strip():
            return {"success": False, "error": "No traceback or error log text provided"}

        py_pat = re.compile(r'File "(?P<file>[^"]+)", line (?P<line>\d+)(?:, in (?P<func>\w+))?')
        js_pat = re.compile(r'at\s+(?:(?P<func>[^\s(]+)\s+\()?(?P<file>[^:()\s]+):(?P<line>\d+):(?P<col>\d+)\)?')
        cs_pat = re.compile(r'at\s+(?P<func>[^\s]+)\s+in\s+(?P<file>[^:]+):line\s+(?P<line>\d+)')
        go_pat = re.compile(r'(?P<file>[^\s:]+\.go):(?P<line>\d+)(?:\s+\+0x[0-9a-f]+)?')
        rs_pat = re.compile(r'at\s+(?P<file>[^:]+\.rs):(?P<line>\d+):(?P<col>\d+)')
        gen_pat = re.compile(r'(?P<file>[a-zA-Z0-9_./\\-]+\.[a-zA-Z0-9_]+):(?P<line>\d+)')

        raw_frames: list[dict[str, Any]] = []
        lines = text.splitlines()

        error_type = ""
        error_message = ""
        for line in reversed(lines):
            line_str = line.strip()
            if not line_str:
                continue
            err_m = re.search(r'\b(?P<type>[A-Z][A-Za-z0-9_]*(?:Error|Exception|Panic|Failure))\s*:\s*(?P<msg>.*)', line_str)
            if err_m:
                error_type = err_m.group("type")
                error_message = err_m.group("msg").strip()
                break
            if line_str.startswith("AssertionError") or line_str.startswith("FAILED") or line_str.startswith("panic:"):
                parts = line_str.split(":", 1)
                error_type = parts[0].strip()
                error_message = parts[1].strip() if len(parts) > 1 else ""
                break

        for line in lines:
            m = py_pat.search(line) or js_pat.search(line) or cs_pat.search(line) or rs_pat.search(line) or go_pat.search(line) or gen_pat.search(line)
            if m:
                d = m.groupdict()
                raw_frames.append({
                    "file": d.get("file", "").replace("\\", "/").strip(),
                    "line": int(d.get("line", 1)),
                    "function": d.get("func", ""),
                })

        base_path = Path(resolved_root)
        processed_frames: list[dict[str, Any]] = []
        seen = set()

        for f in raw_frames:
            f_str = f["file"]
            ln = f["line"]
            target = (base_path / f_str).resolve(strict=False)
            if not target.is_file() and Path(f_str).is_file():
                target = Path(f_str).resolve(strict=False)

            try:
                rel = target.relative_to(base_path).as_posix()
            except ValueError:
                rel = f_str

            key = (rel, ln)
            if key in seen:
                continue
            seen.add(key)

            snippet = ""
            if target.is_file():
                slice_res = self.repo_tools.file_slice(resolved_root, rel, start_line=max(1, ln - 4), end_line=ln + 4, max_chars=1200)
                if slice_res.get("success"):
                    snippet = slice_res.get("text", "")

            processed_frames.append({
                "file": rel,
                "line": ln,
                "function": f.get("function", ""),
                "in_project": target.is_file(),
                "snippet": snippet,
            })

        project_frames = [pf for pf in processed_frames if pf["in_project"]]
        root_cause = project_frames[-1] if project_frames else (processed_frames[-1] if processed_frames else None)

        return {
            "success": True,
            "root": resolved_root,
            "error_type": error_type or "UnknownError",
            "error_message": error_message,
            "frames_count": len(processed_frames),
            "project_frames_count": len(project_frames),
            "frames": processed_frames,
            "root_cause": root_cause,
        }

    def repo_briefing(self, root: str) -> dict[str, Any]:
        """Produce an ultra-compact (<300 token) project orientation snapshot for cloud models."""
        resolved_root = canonical_root(root)
        base = Path(resolved_root)
        if not base.is_dir():
            return {"success": False, "error": "Root directory does not exist"}

        manifests: list[str] = []
        stack_types: list[str] = []
        test_commands: list[str] = []

        if (base / "pyproject.toml").is_file() or (base / "setup.py").is_file() or (base / "requirements.txt").is_file():
            stack_types.append("Python")
            manifests.extend([m for m in ("pyproject.toml", "setup.py", "requirements.txt") if (base / m).is_file()])
            test_commands.append("pytest")
        if (base / "package.json").is_file():
            stack_types.append("TypeScript/JavaScript")
            manifests.append("package.json")
            test_commands.append("npm test")
        if any(base.glob("*.csproj")) or any(base.glob("*.sln")):
            stack_types.append("C# / .NET")
            test_commands.append("dotnet test")
        if (base / "Cargo.toml").is_file():
            stack_types.append("Rust")
            manifests.append("Cargo.toml")
            test_commands.append("cargo test")
        if (base / "go.mod").is_file():
            stack_types.append("Go")
            manifests.append("go.mod")
            test_commands.append("go test ./...")

        common_entries = [
            "src/main.py", "main.py", "app.py", "src/index.ts", "src/index.js",
            "Program.cs", "main.go", "src/main.rs"
        ]
        entry_points = [e for e in common_entries if (base / e).is_file()]

        branch = "unknown"
        dirty_files = 0
        recent_commits: list[str] = []
        try:
            from .process_utils import hidden_run_kwargs
            cp_branch = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=str(base), capture_output=True, text=True, check=False, timeout=2, **hidden_run_kwargs()
            )
            if cp_branch.returncode == 0:
                branch = cp_branch.stdout.strip()

            cp_status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(base), capture_output=True, text=True, check=False, timeout=2, **hidden_run_kwargs()
            )
            if cp_status.returncode == 0:
                dirty_files = len([l for l in cp_status.stdout.splitlines() if l.strip()])

            cp_log = subprocess.run(
                ["git", "log", "-n", "3", "--oneline"],
                cwd=str(base), capture_output=True, text=True, check=False, timeout=2, **hidden_run_kwargs()
            )
            if cp_log.returncode == 0:
                recent_commits = [l.strip() for l in cp_log.stdout.splitlines() if l.strip()]
        except Exception:
            pass

        active_task = None
        task_store = getattr(self, "task_store", None)
        if task_store is not None:
            try:
                active_task = task_store.get_active_task(repo_root=resolved_root)
            except Exception:
                active_task = None

        brief_card = (
            f"**Repo**: {base.name} | **Branch**: {branch} ({dirty_files} dirty)\n"
            f"**Stack**: {', '.join(stack_types) or 'Generic'} | **Manifests**: {', '.join(manifests) or 'None'}\n"
            f"**Test Runner**: {', '.join(test_commands) or 'None'}\n"
            f"**Entrypoints**: {', '.join(entry_points) or 'None'}\n"
            f"**Recent**: {recent_commits[0] if recent_commits else 'No git history'}"
        )

        return {
            "success": True,
            "root": resolved_root,
            "repo_name": base.name,
            "stack": stack_types,
            "manifests": manifests,
            "test_commands": test_commands,
            "entry_points": entry_points,
            "git": {
                "branch": branch,
                "dirty_files": dirty_files,
                "recent_commits": recent_commits,
            },
            "active_task": active_task,
            "markdown_card": brief_card,
        }

    def repo_map(self, root: str, max_symbols: int = 120) -> dict[str, Any]:
        def compute() -> dict[str, Any]:
            indexed_paths = None
            if self.preprocessor is not None:
                try:
                    indexed_paths = self.preprocessor.indexed_paths(root)
                except Exception:
                    indexed_paths = None
            if indexed_paths:
                res = self.repo_tools.repo_map(root, max_symbols, paths=indexed_paths)
                if isinstance(res, dict):
                    res["preprocessed_hit"] = True
                return res
            res = self.repo_tools.repo_map(root, max_symbols)
            if isinstance(res, dict):
                res["preprocessed_hit"] = False
            return res

        return self._repo_cached("map", root, {"max_symbols": max_symbols}, compute)

    def deterministic_operation(self, operation: str, root: str, params: dict[str, Any], compute: Any, *, cache_results: bool = True) -> dict[str, Any]:
        """Cache expensive deterministic analyses by repository fingerprint.

        These operations are pure derived views of repository state. Sharing the same
        cache with search/context prevents dashboard, MCP and local-model callers from
        independently repeating AST/security/test/dependency scans.
        """
        def wrapped_compute() -> dict[str, Any]:
            res = compute()
            if isinstance(res, dict):
                res["preprocessed_hit"] = bool(res.get("success", True))
            return res
        return self._repo_cached(f"det:{operation}", root, params, wrapped_compute, cache_results=cache_results)

    def _repository_test_impact_service(self):
        from .repository_test_impact import RepositoryTestImpactService

        return RepositoryTestImpactService(
            self.deterministic,
            self.deterministic_operation,
        )

    def test_matrix(self, root: str) -> dict[str, Any]:
        return self._repository_test_impact_service().test_matrix(root)

    def affected_tests(
        self,
        root: str,
        changed_paths: list[str] | None = None,
        base: str = "HEAD",
        path_hints: list[Any] | tuple[Any, ...] | None = None,
    ) -> dict[str, Any]:
        from .service_affected_tests import affected_tests
        return affected_tests(self, root, changed_paths=changed_paths, base=base, path_hints=path_hints)

    def repo_topology(self, root: str) -> dict[str, Any]:
        return self.deterministic_operation("repo-topology", root, {}, lambda: self.deterministic.repo_topology(root))

    def ast_rename(self, root: str, file_path: str, old_symbol: str, new_symbol: str, apply_changes: bool = False) -> dict[str, Any]:
        return self.deterministic.ast_rename(root, file_path, old_symbol, new_symbol, apply_changes=apply_changes)

    def generate_mocks(self, root: str, file_path: str, symbol: str) -> dict[str, Any]:
        return self.deterministic.generate_mocks(root, file_path, symbol)

    def split_changes(
        self, root: str, changed_files: list[str] | None = None, *,
        mode: str = "full", limit: int = 8, offset: int = 0,
        base: str | None = None, head: str = "HEAD", task_id: str = "",
        expected_revision: str | None = None,
    ) -> dict[str, Any]:
        from .change_commit_preflight import commit_preflight, revision_error
        from .change_plan_projection import project_change_plan

        if mode not in {"full", "summary", "details", "semantic", "preflight", "pr", "release", "artifact", "delta"}:
            return {"success": False, "error": "invalid change plan mode"}
        if type(limit) is not int or not 1 <= limit <= 8 or type(offset) is not int or not 0 <= offset <= 100000:
            return {"success": False, "error": "invalid change plan page"}
        from .repository_scope import authorized_repository_root
        from .change_task_context import attach_task_context, current_task_revision, scoped_tasks

        root = authorized_repository_root(getattr(self, "config", {}), root)
        if mode == "delta" and (base is not None or changed_files is not None):
            return {"success": False, "error": "Delta requires the complete worktree scope"}
        if mode == "preflight":
            if base is not None:
                return {"success": False, "error": "Preflight requires a working tree"}
            return commit_preflight(self.deterministic.split_changes(root, None), changed_files, expected_revision)
        if mode in {"pr", "release"} and base is None:
            return {"success": False, "error": "PR and release summaries require an explicit base revision"}
        tasks: list[Any] = []
        truncated = False
        revision_before = ""
        if base is None and (mode != "full" or task_id):
            try:
                tasks, truncated = scoped_tasks(getattr(self, "task_store", None), root, task_id)
            except ValueError as exc:
                return {"success": False, "error": str(exc)}
            if tasks:
                revision_before = current_task_revision(self, root)
        elif task_id:
            return {"success": False, "error": "task_id is only supported for worktree changes"}
        result = (self.deterministic.split_changes(root, changed_files, base=base, head=head)
                  if base is not None else self.deterministic.split_changes(root, changed_files))
        if result.get("success") is True and mode != "delta":
            error = revision_error(result, expected_revision)
            if error:
                return {"success": False, "error": error, "commit_ready": False}
        if base is None and (mode != "full" or task_id):
            attach_task_context(self, result, tasks, root, revision_before=revision_before, truncated=truncated)
        from .change_plan_delta import change_delta, remember_baseline

        cache = getattr(self.deterministic, "_change_summary_cache", None)
        if mode == "delta":
            return change_delta(result, cache, expected_revision, limit=limit, offset=offset)
        if mode == "full":
            return result
        if mode == "artifact":
            from .change_plan_artifact import publish_change_plan

            return publish_change_plan(result, getattr(self, "artifacts", None))
        projected = project_change_plan(
            result, mode=mode, limit=limit, offset=offset,
            delegate=self.delegate if mode == "semantic" else None, root=root,
        )
        if mode == "summary" and projected.get("success") is True:
            projected["baseline_stored"] = remember_baseline(result, cache)
        return projected

    def synthesize_rules(self, root: str, limit: int = 10) -> dict[str, Any]:
        return self.deterministic.synthesize_rules(root, limit)

    def code_invariants(self, root: str, path: str | None = None) -> dict[str, Any]:
        return self.deterministic.code_invariants(root, path)

    def generate_dataset(self, root: str, schema_or_model: Any, count: int = 10, format: str = "json") -> dict[str, Any]:
        return self.deterministic.generate_dataset(root, schema_or_model, count=count, format=format)

    def profile_digest(self, profile_path: str, top_n: int = 15) -> dict[str, Any]:
        return self.deterministic.profile_digest(profile_path, top_n=top_n)

    def worktree_lease(self, root: str, branch_name: str | None = None, worktree_path: str | None = None) -> dict[str, Any]:
        from .git_worktrees import create_git_worktree
        return create_git_worktree(root, branch_name=branch_name, worktree_path=worktree_path)

    def worktree_release(self, root: str, worktree_path: str, delete_branch: bool = True, branch_name: str | None = None, *, worktree_id: str = "") -> dict[str, Any]:
        from .git_worktrees import remove_git_worktree
        return remove_git_worktree(root, worktree_path, delete_branch=delete_branch, branch_name=branch_name, worktree_id=worktree_id)

    def list_worktrees(self, root: str) -> dict[str, Any]:
        from .git_worktrees import list_git_worktrees
        return list_git_worktrees(root)

    def prune_worktrees(self, root: str) -> dict[str, Any]:
        from .git_worktrees import prune_git_worktrees
        return prune_git_worktrees(root)

    def spawn_daemon(
        self,
        command: str | list[str],
        cwd: str,
        name: str = "",
        env: dict[str, str] | None = None,
        *,
        task_id: str = "",
    ) -> dict[str, Any]:
        if not self.commands:
            return {"success": False, "error": "command broker unavailable"}
        return self.commands.spawn_daemon(command, cwd, name=name, env=env, task_id=task_id)

    def daemon_status(
        self, daemon_id: str | None = None, *, task_id: str = ""
    ) -> dict[str, Any]:
        if not self.commands:
            return {"success": False, "error": "command broker unavailable"}
        if not task_id:
            return {
                "success": False,
                "error": "daemon status requires a registered task id",
                "policy_blocked": True,
                "terminal": True,
                "retryable": False,
            }
        denied = self._authorize_command_action(
            "daemon_status", endpoint="services.daemon_status", task_id=task_id
        )
        if denied is not None:
            return denied
        return self.commands.daemon_status(daemon_id, task_id=task_id)

    def stop_daemon(self, daemon_id: str, *, task_id: str = "") -> dict[str, Any]:
        if not self.commands:
            return {"success": False, "error": "command broker unavailable"}
        return self.commands.stop_daemon(daemon_id, task_id=task_id)

    def lint_fix(self, root: str, *, command: str | None = None, paths: list[str] | None = None, timeout: int | None = None) -> dict[str, Any]:
        if not self.commands:
            return {"success": False, "error": "command broker unavailable"}
        return self.commands.lint_fix(root, command=command, paths=paths,  timeout=timeout)

    def security_audit(self, root: str, limit: int = 200) -> dict[str, Any]:
        return self.deterministic_operation("security-audit", root, {"limit": int(limit)}, lambda: self.deterministic.security_audit(root, int(limit)))

    def ast_outline(self, root: str, path: str) -> dict[str, Any]:
        return self.deterministic_operation("ast-outline", root, {"path": path}, lambda: self.deterministic.ast_outline(root, path))

    def batch_replace(
        self,
        root: str,
        edits: list[dict[str, Any]],
        dry_run: bool = False,
        *,
        owner: str | None = None,
        lease_id: str | None = None,
        lease_store: Any | None = None,
    ) -> dict[str, Any]:
        if not rollout_feature_enabled(self.config, "batch_replacement"):
            return {
                "success": False,
                "unsupported": True,
                "feature": "batch_replacement",
                "error": "batch replacement is disabled (features.batch_replacement=false)",
            }
        if not self.deterministic:
            return {"success": False, "error": "deterministic engine disabled"}
        if (owner is None) != (lease_id is None):
            return {"success": False, "error": "owner and lease_id must be supplied together"}
        owned_paths: list[str] = []
        if owner is not None and lease_id is not None:
            if (
                not isinstance(owner, str) or not owner or owner != owner.strip() or "\x00" in owner
                or not isinstance(lease_id, str) or not lease_id or lease_id != lease_id.strip() or "\x00" in lease_id
            ):
                return {"success": False, "error": "invalid owner or lease_id"}
            if lease_store is None or not callable(getattr(lease_store, "list", None)):
                return {"success": False, "error": "lease store unavailable for owner verification"}
            try:
                leases = lease_store.list(root)
            except Exception as exc:
                return {"success": False, "error": f"unable to verify active lease: {type(exc).__name__}"}
            root_path = Path(root).expanduser().resolve()
            for lease in leases:
                if not isinstance(lease, dict) or lease.get("owner") != owner or lease.get("lease_id") != lease_id:
                    continue
                lease_root = lease.get("root")
                lease_path = lease.get("path")
                if not isinstance(lease_root, str) or not isinstance(lease_path, str) or not lease_path:
                    continue
                try:
                    if Path(lease_root).expanduser().resolve() != root_path:
                        continue
                    owned_paths.append(lease_path)
                except (OSError, RuntimeError, ValueError):
                    continue
            if not owned_paths:
                return {"success": False, "error": "active lease not found for owner, lease_id, and repository root"}
        return self.deterministic.batch_replace(root, edits, dry_run=dry_run, owned_paths=owned_paths)

    def refactor_impact(self, root: str, file_path: str, symbol: str) -> dict[str, Any]:
        return self.deterministic_operation("refactor-impact", root, {"file": file_path, "symbol": symbol}, lambda: self.deterministic.refactor_impact(root, file_path, symbol))

    def resolve_imports(self, root: str, symbols: list[str], language: str = "auto") -> dict[str, Any]:
        # Revalidate source hashes rather than reuse workspace-only export proof.
        return self.deterministic.resolve_imports(root, symbols, language)

    def callers(self, root: str, symbol: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        bounds_error = pagination_bounds_error(limit, offset)
        if bounds_error:
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": bounds_error}
        if not isinstance(symbol, str) or not symbol.strip():
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": "symbol must be a non-empty string"}
        if self.code_index is not None:
            ci_res = self.code_index.find_callers(root, symbol, limit, offset)
            if ci_res.get("success"):
                if ci_res.get("count", 0) > 0 or ci_res.get("index_available") is not False:
                    return ci_res
        return self.deterministic_operation(
            "callers", root, {"symbol": symbol, "limit": limit, "offset": offset},
            lambda: self.deterministic.find_callers(root, symbol, limit, offset),
        )

    def callees(self, root: str, symbol: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        bounds_error = pagination_bounds_error(limit, offset)
        if bounds_error:
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": bounds_error}
        if not isinstance(symbol, str) or not symbol.strip():
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": "symbol must be a non-empty string"}
        if self.code_index is not None:
            ci_res = self.code_index.find_callees(root, symbol, limit, offset)
            if ci_res.get("success"):
                if ci_res.get("count", 0) > 0 or ci_res.get("index_available") is not False:
                    return ci_res
        return self.deterministic_operation(
            "callees", root, {"symbol": symbol, "limit": limit, "offset": offset},
            lambda: self.deterministic.find_callees(root, symbol, limit, offset),
        )

    def call_graph(
        self,
        root: str,
        symbol: str,
        path: str | None = None,
        depth: int = 1,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Aggregate caller and callee hierarchy for a symbol in a single structured response."""
        if not isinstance(symbol, str) or not symbol.strip():
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": "symbol must be a non-empty string"}

        decl_res = self.code_find_declaration(root, symbol, path=path)
        found_in = None
        if isinstance(decl_res, dict) and decl_res.get("success"):
            found_in = {
                "path": decl_res.get("path"),
                "line": decl_res.get("line"),
                "kind": decl_res.get("kind"),
            }

        callers_res = self.callers(root, symbol, limit=limit)
        callers_ok = isinstance(callers_res, dict) and callers_res.get("success") is True
        caller_items = callers_res.get("callers", []) if callers_ok else []

        callees_res = self.callees(root, symbol, limit=limit)
        callees_ok = isinstance(callees_res, dict) and callees_res.get("success") is True
        callee_items = callees_res.get("callees", []) if callees_ok else []

        caller_coverage = callers_res.get("coverage") if isinstance(callers_res, dict) else None
        callee_coverage = callees_res.get("coverage") if isinstance(callees_res, dict) else None
        coverage_complete = (
            callers_ok and callees_ok
            and isinstance(caller_coverage, dict) and caller_coverage.get("complete") is True
            and isinstance(callee_coverage, dict) and callee_coverage.get("complete") is True
        )
        if coverage_complete:
            coverage_reason = None
        elif not isinstance(caller_coverage, dict) or not isinstance(callee_coverage, dict):
            coverage_reason = "subquery_coverage_missing"
        else:
            coverage_reason = "subquery_coverage_incomplete"

        caller_freshness = callers_res.get("freshness") if isinstance(callers_res, dict) else None
        callee_freshness = callees_res.get("freshness") if isinstance(callees_res, dict) else None
        freshness_statuses = [
            item.get("status") for item in (caller_freshness, callee_freshness)
            if isinstance(item, dict) and isinstance(item.get("status"), str)
        ]
        if "not_checked" in freshness_statuses:
            freshness_status = "not_checked"
        elif not freshness_statuses:
            freshness_status = "not_reported"
        elif len(set(freshness_statuses)) == 1:
            freshness_status = freshness_statuses[0]
        else:
            freshness_status = "mixed"

        index_states = [
            item.get("index_available") for item in (callers_res, callees_res)
            if isinstance(item, dict) and isinstance(item.get("index_available"), bool)
        ]
        index_available = False if False in index_states else True if len(index_states) == 2 and all(index_states) else None
        subquery_errors = {
            name: response.get("error")
            for name, response, succeeded in (
                ("callers", callers_res, callers_ok), ("callees", callees_res, callees_ok),
            )
            if not succeeded and isinstance(response, dict) and response.get("error")
        }
        truncated = any(
            response.get("truncated") is True
            for response in (callers_res, callees_res)
            if isinstance(response, dict)
        )
        stale = any(
            response.get("stale") is True
            for response in (callers_res, callees_res)
            if isinstance(response, dict)
        )

        expanded_callers = []
        if depth > 1 and caller_items:
            for item in caller_items[:3]:
                caller_sym = item.get("symbol") if isinstance(item, dict) else str(item)
                if caller_sym and caller_sym != symbol:
                    sub = self.callers(root, caller_sym, limit=5)
                    sub_callers = sub.get("callers", []) if isinstance(sub, dict) and sub.get("success") else []
                    expanded_callers.append({"symbol": caller_sym, "called_by": sub_callers})

        expanded_callees = []
        if depth > 1 and callee_items:
            for item in callee_items[:3]:
                callee_sym = item.get("symbol") if isinstance(item, dict) else str(item)
                if callee_sym and callee_sym != symbol:
                    sub = self.callees(root, callee_sym, limit=5)
                    sub_callees = sub.get("callees", []) if isinstance(sub, dict) and sub.get("success") else []
                    expanded_callees.append({"symbol": callee_sym, "calls": sub_callees})

        result = {
            "success": callers_ok and callees_ok,
            "symbol": symbol,
            "found_in": found_in,
            "callers": caller_items,
            "caller_count": len(caller_items),
            "callees": callee_items,
            "callee_count": len(callee_items),
            "depth": depth,
            "partial": not (callers_ok and callees_ok and coverage_complete and freshness_status not in {"not_checked", "not_reported", "mixed"}) or truncated or stale,
            "coverage": {
                "complete": coverage_complete,
                "reason": coverage_reason,
                "callers": caller_coverage,
                "callees": callee_coverage,
            },
            "freshness": {
                "status": freshness_status,
                "callers": caller_freshness,
                "callees": callee_freshness,
            },
            "index_available": index_available,
            "truncated": truncated,
            "stale": stale,
            "subquery_errors": subquery_errors,
        }
        if depth > 1:
            result["hierarchy"] = {
                "expanded_callers": expanded_callers,
                "expanded_callees": expanded_callees,
            }
        return result

    def dead_code(self, root: str, limit: int = 200) -> dict[str, Any]:
        return self.deterministic_operation("dead-code", root, {"limit": int(limit)}, lambda: getattr(self.deterministic, "find_dead_code", getattr(self.deterministic, "detect_dead_code", None))(root, int(limit)))

    def secret_scan(self, root: str, path: str | None = None, scan_git_history: bool = False, commit_depth: int = 20) -> dict[str, Any]:
        return self.deterministic_operation("secret-scan", root, {"path": path, "git": scan_git_history, "depth": commit_depth}, lambda: self.deterministic.secret_scan(root, path, scan_git_history=scan_git_history, commit_depth=commit_depth))

    def schema_inspect(self, root: str, db_path: str | None = None) -> dict[str, Any]:
        return self.deterministic_operation("schema-inspect", root, {"db_path": db_path}, lambda: self.deterministic.schema_inspect(root, db_path))

    def explain_query(self, root: str, query: str, db_path: str | None = None) -> dict[str, Any]:
        return self.deterministic_operation("explain-query", root, {"query": query, "db_path": db_path}, lambda: self.deterministic.explain_query(root, query, db_path))

    def env_compat(self, root: str) -> dict[str, Any]:
        return self.deterministic_operation("env-compat", root, {}, lambda: self.deterministic.env_compat(root))

    def circular_dependencies(self, root: str, language: str = "python") -> dict[str, Any]:
        return self.deterministic_operation("circular-dependencies", root, {"language": language}, lambda: self.deterministic.find_circular_dependencies(root, language))

    def generate_types(self, root: str, path: str) -> dict[str, Any]:
        return self.deterministic_operation("generate-types", root, {"path": path}, lambda: self.deterministic.generate_types(root, path))

    def code_complexity(
        self, root: str, path: str | None = None, max_results: int = 20, include_tests: bool = False
    ) -> dict[str, Any]:
        return self.deterministic_operation(
            "code-complexity", root,
            {"path": path, "max": max_results, "include_tests": include_tests},
            lambda: self.deterministic.code_complexity(root, path, max_results, include_tests),
        )

    def extract_api_spec(self, root: str, framework: str | None = None) -> dict[str, Any]:
        return self.deterministic_operation("extract-api-spec", root, {"framework": framework}, lambda: self.deterministic.extract_api_spec(root, framework))

    def slice_dependency_graph(self, root: str, symbol: str, path: str | None = None, depth: int = 2) -> dict[str, Any]:
        if not isinstance(symbol, str) or not symbol.isidentifier() or keyword.iskeyword(symbol):
            return {"success": False, "status_code": 400, "error": "symbol must be a valid Python identifier"}
        return self.deterministic_operation("slice-dependency-graph", root, {"symbol": symbol, "path": path, "depth": depth}, lambda: self.deterministic.slice_dependency_graph(root, symbol, path, depth))

    def migration_drift(self, root: str, db_path: str | None = None) -> dict[str, Any]:
        return self.deterministic_operation("migration-drift", root, {"db_path": db_path}, lambda: self.deterministic.migration_drift(root, db_path))

    def package_audit(self, root: str, lockfile_path: str | None = None) -> dict[str, Any]:
        return self.deterministic_operation("package-audit", root, {"lockfile": lockfile_path}, lambda: self.deterministic.package_audit(root, lockfile_path))

    def structural_search(self, root: str, pattern: str, path: str | None = None, max_results: int = 30, *, file_offset: int = 0, match_offset: int = 0, expected_revision: str | None = None) -> dict[str, Any]:
        return self.deterministic_operation(
            "structural-search", root,
            {"pattern": pattern, "path": path, "max_results": max_results,
             "file_offset": file_offset, "match_offset": match_offset, "expected_revision": expected_revision},
            lambda: self.deterministic.structural_search(
                root, pattern, path=path, max_results=max_results, file_offset=file_offset, match_offset=match_offset,
                expected_revision=expected_revision,
            ),
            # Never serve cached search pages whose revision guard may be stale.
            cache_results=False,
        )

    def context_budget(self, root: str, files: list[str] | None = None, max_tokens: int = 4000) -> dict[str, Any]:
        return self.deterministic_operation("context-budget", root, {"files": files, "max_tokens": max_tokens}, lambda: self.deterministic.context_budget(root, files=files, max_tokens=max_tokens))

    def git_diff(self, root: str, path: str | None = None, staged: bool = False, max_lines: int = 1000,
                 *, rev1: str | None = None, rev2: str | None = None) -> dict[str, Any]:
        if rev1 is not None or rev2 is not None:
            # Moving refs must be pinned afresh, not served from a workspace-only cache.
            return self.deterministic.git_diff(root, path=path, staged=staged, max_lines=max_lines, rev1=rev1, rev2=rev2)
        return self.deterministic_operation("git-diff", root, {"path": path, "staged": staged, "max_lines": max_lines}, lambda: self.deterministic.git_diff(root, path=path, staged=staged, max_lines=max_lines))

    def git_history_search(
        self,
        root: str,
        query: str,
        max_commits: int = 20,
        *,
        author: str | None = None,
        since: str | None = None,
        until: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "query": query,
            "max_commits": max_commits,
            "author": author,
            "since": since,
            "until": until,
            "path": path,
        }
        return self.deterministic_operation(
            "git-history-search", root, params,
            lambda: self.deterministic.git_history_search(
                root, query, max_commits=max_commits,
                author=author, since=since, until=until, path=path,
            ),
        )

    def find_hotspots(self, root: str, days: int = 30, limit: int = 20) -> dict[str, Any]:
        return self.deterministic_operation(
            "find-hotspots", root,
            {"days": days, "limit": limit, "algorithm": "git-recency-half-life-90d-v1"},
            lambda: self.deterministic.find_hotspots(root, days=days, limit=limit),
        )

    def generate_tests_for_diff(self, root: str, diff: str | None = None, path: str | None = None) -> dict[str, Any]:
        return self.deterministic_operation("generate-tests-for-diff", root, {"diff": bool(diff), "path": path}, lambda: self.deterministic.generate_tests_for_diff(root, diff=diff, path=path))

    def cross_repo_contract(self, backend_root: str, frontend_root: str) -> dict[str, Any]:
        return self.deterministic_operation("cross-repo-contract", backend_root, {"frontend_root": frontend_root}, lambda: self.deterministic.cross_repo_contract(backend_root, frontend_root))

