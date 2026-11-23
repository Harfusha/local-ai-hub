from __future__ import annotations

from .app import (
    Any as Any,
    Mapping as Mapping,
    Path as Path,
    _redact_laya_training_text as _redact_laya_training_text,
    shutdown_logging as shutdown_logging,
    threading as threading,
    time as time,
)


LocalAIApp = None


class AppCaptureMixin:
    def _capture_laya_context_source_from_context(
        self,
        request: Any,
        result: Any,
    ) -> dict[str, Any]:
        """Collect one real, incomplete context decision in shadow mode only."""
        if not self._laya_inference_enabled():
            return {"status": "skipped", "reason": "laya_disabled"}
        if not isinstance(result, dict) or result.get("success") is not True:
            return {"status": "skipped", "reason": "context_unavailable"}
        task_id = str(getattr(request, "task_id", "") or "").strip()
        if not task_id:
            return {"status": "skipped", "reason": "task_identity_unavailable"}
        config = getattr(self, "config", {})
        laya_cfg = config.get("laya", {}) if isinstance(config, Mapping) else {}
        runtime_cfg = laya_cfg.get("runtime", {}) if isinstance(laya_cfg, dict) else {}
        if (
            not isinstance(runtime_cfg, dict)
            or not isinstance(runtime_cfg.get("checkpoint_path"), str)
            or not runtime_cfg.get("checkpoint_path")
            or not isinstance(runtime_cfg.get("revision"), str)
            or not runtime_cfg.get("revision")
            or not isinstance(runtime_cfg.get("expected_sha256"), dict)
            or not runtime_cfg.get("expected_sha256")
        ):
            return {"status": "skipped", "reason": "checkpoint_unavailable"}
        try:
            canonical_root = str(Path(getattr(request, "root", "")).resolve(strict=True))
            task = self.laya_candidates._find_task(self.agent_tasks, canonical_root, task_id)
            session_id = self.laya_candidates._session_for_task(task)
            request_session = str(getattr(request, "session_id", "") or "").strip()
            if request_session and request_session != session_id:
                return {"status": "skipped", "reason": "session_identity_mismatch"}
        except (OSError, RuntimeError, ValueError) as exc:
            return {
                "status": "skipped", "reason": "task_scope_unavailable",
                "error_type": type(exc).__name__,
            }

        retrieval = result.get("retrieval")
        evidence_rows = result.get("evidence")
        if not isinstance(retrieval, dict) or not isinstance(evidence_rows, list):
            return {"status": "skipped", "reason": "retrieval_provenance_unavailable"}
        states = retrieval.get("backend_states")
        if not isinstance(states, dict):
            return {"status": "skipped", "reason": "backend_states_unavailable"}

        source_rows: dict[str, dict[str, Any]] = {}
        for row in evidence_rows:
            if not isinstance(row, dict):
                continue
            semantic = row.get("semantic") is True
            source_code = "rag" if semantic else "indexed"
            eligible_backend = states.get("rag") == "used" if semantic else any(
                states.get(name) == "used" for name in ("lexical", "deterministic", "code_index", "preprocessor")
            )
            if not eligible_backend or source_code in source_rows:
                continue
            if not row.get("path") or not (row.get("content_hash") or row.get("file_sha256")):
                continue
            evidence_id = None
            if semantic:
                evidence_id = str(row.get("evidence_id") or "")
                verified = self.evidence.get_many([evidence_id], verify=True, root=canonical_root) if evidence_id else []
                provenance_ok = self.evidence.validate_source_provenance(
                    [evidence_id], [source_code], root=canonical_root,
                ) if evidence_id else False
                if not verified or verified[0].get("success") is not True or verified[0].get("stale") is not False or not provenance_ok:
                    evidence_id = None
            elif row.get("text"):
                stored = self.evidence.put_many(canonical_root, [row], source_code=source_code)
                evidence_id = str(stored[0].get("evidence_id") or "") if stored else None
            if evidence_id:
                source_rows[source_code] = {"evidence_id": evidence_id, "row": row}

        lexical = retrieval.get("lexical") if isinstance(retrieval.get("lexical"), dict) else {}
        semantic = retrieval.get("semantic") if isinstance(retrieval.get("semantic"), dict) else {}

        def coverage_code(source_code: str) -> str:
            if source_code == "memory":
                return "partial"
            metadata = semantic if source_code == "rag" else lexical
            raw_coverage = metadata.get("coverage") if isinstance(metadata.get("coverage"), dict) else {}
            if raw_coverage.get("complete") is True and metadata.get("truncated") is not True:
                return "complete"
            if raw_coverage.get("candidate_count", 0) or raw_coverage.get("included_evidence_count", 0):
                return "partial"
            return "incomplete"

        if len(source_rows) >= 2 and all(
            coverage_code(source_code) == "complete" for source_code in source_rows
        ):
            return {"status": "skipped", "reason": "no_unresolved_evidence_gap"}

        memory_store = getattr(self, "agent_memory", None)
        find_memory = getattr(memory_store, "find", None)
        if callable(find_memory):
            try:
                from .agent_identity import AgentScope
                from .agent_memory import MemoryStatus

                scoped_queries = [
                    (AgentScope.TASK, {"root": canonical_root, "task_id": task_id}),
                    (
                        AgentScope.SESSION,
                        {"root": canonical_root, "task_id": task_id, "session_id": session_id},
                    ),
                ]
                state_dir = self.config.get("server", {}).get("state_dir")
                if isinstance(state_dir, str) and state_dir:
                    try:
                        from .project_config import resolve_project_context

                        project = resolve_project_context(canonical_root, Path(state_dir))
                        coordination_id = getattr(project, "coordination_id", None)
                        if isinstance(coordination_id, str) and coordination_id:
                            scoped_queries.append((
                                AgentScope.REPOSITORY,
                                {"root": canonical_root, "repository_id": coordination_id},
                            ))
                    except Exception:
                        pass
                memory_records = []
                for scope, context_args in scoped_queries:
                    for status in (MemoryStatus.ACTIVE, MemoryStatus.CONFIRMED):
                        memory_records.extend(find_memory(
                            scope=scope,
                            status=status,
                            semantic=False,
                            limit=20,
                            **context_args,
                        ))
                used_evidence_ids = {
                    entry["evidence_id"] for entry in source_rows.values()
                }
                for record in memory_records:
                    record_id = getattr(record, "record_id", None)
                    record_scope = getattr(getattr(record, "scope", None), "value", None)
                    record_status = getattr(getattr(record, "status", None), "value", None)
                    linked_ids = getattr(record, "evidence_ids", ())
                    value = getattr(record, "value", None)
                    if (
                        type(record_id) is not str
                        or record_scope not in {"repository", "task", "session"}
                        or record_status not in {"active", "confirmed"}
                        or getattr(record, "sensitivity", None) != "normal"
                        or type(linked_ids) not in (tuple, list)
                        or not isinstance(value, str)
                        or not value.strip()
                    ):
                        continue
                    for linked_id in linked_ids:
                        if type(linked_id) is not str or linked_id in used_evidence_ids:
                            continue
                        verified = self.evidence.get_many(
                            [linked_id], verify=True, root=canonical_root,
                        )
                        if (
                            type(verified) is not list
                            or len(verified) != 1
                            or verified[0].get("success") is not True
                            or verified[0].get("evidence_id") != linked_id
                            or verified[0].get("root") != canonical_root
                            or verified[0].get("stale") is not False
                        ):
                            continue
                        source_rows["memory"] = {
                            "evidence_id": linked_id,
                            "record_id": record_id,
                            "row": {"text": value},
                        }
                        used_evidence_ids.add(linked_id)
                        break
                    if "memory" in source_rows:
                        break
            except Exception:
                # Memory is an optional additional source; retrieval remains authoritative.
                pass
        if len(source_rows) < 2:
            return {"status": "skipped", "reason": "fewer_than_two_verified_sources"}

        sources = list(source_rows.items())[:4]
        freshness: list[str] = []
        coverage: list[str] = []
        for source_code, _ in sources:
            if source_code == "memory":
                freshness.append("current")
                coverage.append(coverage_code(source_code))
                continue
            metadata = semantic if source_code == "rag" else lexical
            raw_freshness = metadata.get("freshness") if isinstance(metadata.get("freshness"), dict) else {}
            freshness_status = raw_freshness.get("status")
            freshness.append("current" if freshness_status == "current" and result.get("stale") is not True else "unknown")
            coverage.append(coverage_code(source_code))
        if all(code == "complete" for code in coverage):
            return {"status": "skipped", "reason": "no_unresolved_evidence_gap"}

        evidence = {
            "gap_code": "unresolved_evidence_gap",
            "source_codes": [source_code for source_code, _ in sources],
            "freshness_codes": freshness,
            "coverage_codes": coverage,
            "evidence_ids": [source_rows[source_code]["evidence_id"] for source_code, _ in sources],
            "source_record_ids": [
                source_rows[source_code].get("record_id") for source_code, _ in sources
            ],
        }
        def bounded_laya_text(value: str, limit: int) -> str:
            redacted = _redact_laya_training_text(value)
            raw = redacted.replace("\x00", "").strip().encode("utf-8", errors="replace")[:limit]
            return raw.decode("utf-8", errors="ignore").strip()

        task_input = getattr(request, "query", "")
        training_content: dict[str, str] = {}
        if isinstance(task_input, str) and task_input.strip():
            bounded_input = bounded_laya_text(task_input, 8192)
            if bounded_input:
                training_content["task_input"] = bounded_input
        excerpts: list[str] = []
        remaining_bytes = 8192
        for source_code, source_entry in sources:
            source_text = source_entry["row"].get("text")
            if not isinstance(source_text, str) or not source_text.strip() or remaining_bytes <= 0:
                continue
            prefix = f"{source_code}: "
            prefix_bytes = len(prefix.encode("utf-8"))
            if prefix_bytes >= remaining_bytes:
                continue
            excerpt = bounded_laya_text(source_text, remaining_bytes - prefix_bytes)
            if not excerpt:
                continue
            rendered = prefix + excerpt
            excerpts.append(rendered)
            remaining_bytes -= len(rendered.encode("utf-8")) + 1
        if excerpts:
            training_content["context_excerpt"] = "\n".join(excerpts)
        if training_content:
            evidence["training_content"] = training_content
        baseline = {
            "method": "retrieval_rank_order",
            "suggestion": sources[0][0],
            "evidence_id": source_rows[sources[0][0]]["evidence_id"],
        }
        operation = {
            "action": "evaluate_context_source",
            "task_id": task_id,
            "session_id": session_id,
            "evidence": evidence,
        }
        executor = getattr(self, "_status_dependency_executor", None)
        capture_lock = getattr(self, "_laya_capture_lock", None)
        capture_queue = getattr(self, "_laya_capture_queue", None)
        shutdown = getattr(self, "_shutdown", None)
        if (
            not callable(getattr(executor, "submit", None))
            or not callable(getattr(capture_lock, "acquire", None))
            or not isinstance(capture_queue, list)
        ):
            return {"status": "skipped", "reason": "capture_executor_unavailable"}
        if shutdown is not None and shutdown.is_set():
            return {"status": "skipped", "reason": "hub_shutdown"}
        dispatch = False
        with capture_lock:
            if shutdown is not None and shutdown.is_set():
                return {"status": "skipped", "reason": "hub_shutdown"}
            if len(capture_queue) >= 16:
                return {"status": "skipped", "reason": "capture_queue_unavailable"}
            capture_queue.append((operation, canonical_root, baseline))
            if not getattr(self, "_laya_capture_draining", False):
                self._laya_capture_draining = True
                dispatch = True
        self._record_laya_capture_observation("queued", "queued")

        if not dispatch:
            return {"status": "queued"}
        try:
            future = executor.submit(self._drain_laya_capture_queue)
        except Exception:
            with capture_lock:
                discarded = len(capture_queue)
                capture_queue.clear()
                self._laya_capture_draining = False
            for _ in range(max(0, discarded - 1)):
                self._record_laya_capture_observation("skipped", "capture_queue_unavailable")
            return {"status": "skipped", "reason": "capture_queue_unavailable"}

        def observe_dispatch(completed: Any) -> None:
            try:
                error = completed.exception()
            except Exception as exc:
                error = exc
            if error is None:
                return
            with capture_lock:
                discarded = len(capture_queue)
                capture_queue.clear()
                self._laya_capture_draining = False
            reason = "hub_shutdown" if shutdown is not None and shutdown.is_set() else "capture_queue_unavailable"
            for _ in range(discarded):
                self._record_laya_capture_observation("skipped", reason, error_type=type(error).__name__)
            self.logger.warning("Laya capture queue stopped: %s", type(error).__name__)

        future.add_done_callback(observe_dispatch)
        return {"status": "queued"}

    def _drain_laya_capture_queue(self) -> None:
        """Run eligible shadow captures serially from a bounded in-memory queue."""
        capture_lock = self._laya_capture_lock
        capture_queue = self._laya_capture_queue
        shutdown = getattr(self, "_shutdown", None)
        while True:
            with capture_lock:
                if shutdown is not None and shutdown.is_set():
                    discarded = len(capture_queue)
                    capture_queue.clear()
                    self._laya_capture_draining = False
                    operation = None
                elif capture_queue:
                    operation = capture_queue.pop(0)
                    discarded = 0
                else:
                    self._laya_capture_draining = False
                    return
            if operation is None:
                for _ in range(discarded):
                    self._record_laya_capture_observation("skipped", "hub_shutdown")
                return
            request, root, baseline = operation
            try:
                if isinstance(request, dict) and request.get("action") == "evaluate_context_source":
                    result = self.evaluate_laya_context_source(request, root=root, baseline=baseline)
                elif isinstance(request, dict) and request.get("action") == "evaluate_decision":
                    result = self.evaluate_laya_decision(
                        request, root=root, _server_baseline=baseline,
                        _record_capture_observation=False,
                    )
                elif isinstance(request, dict) and request.get("action") == "record_completion_outcome":
                    operation = request.get("operation")
                    result = self.laya_candidates.record_completion_outcome(
                        operation,
                        root=root,
                        task_store=self.agent_tasks,
                    )
                    if result.get("event_count", 0) > 0:
                        self._record_laya_capture_observation("captured", "completion_outcome")
                    else:
                        self._record_laya_capture_observation("skipped", "completion_no_candidate")
                    continue
                else:
                    raise ValueError("unsupported queued Laya observation")
                candidate = result.get("candidate") if isinstance(result, dict) else None
                if request.get("action") == "evaluate_decision":
                    if isinstance(candidate, dict) and candidate:
                        self._record_laya_capture_observation("captured", "decision_outcome")
                    else:
                        self._record_laya_capture_observation("failed", "outcome_not_captured")
                        self.logger.warning("Laya shadow outcome was not captured")
                    continue
                if isinstance(candidate, dict) and candidate:
                    self._record_laya_capture_observation("captured", "runtime_outcome")
                else:
                    self._record_laya_capture_observation("failed", "outcome_not_captured")
                    self.logger.warning("Laya shadow outcome was not captured")
            except Exception as exc:
                self._record_laya_capture_observation(
                    "failed", "runtime_error", error_type=type(exc).__name__
                )
                self.logger.warning("Laya shadow capture failed: %s", type(exc).__name__)

    def close(self, *, timeout: float = 5.0) -> None:
        """Stop admission, then wait boundedly for owned component cleanup.

        Inspect close_report for failed/pending phases. Repeated calls retry failed
        phases only; an in-flight callback retains its owner and is never duplicated.
        """
        from .shutdown import CloseCoordinator
        self._shutdown.set()
        with self._close_lock:
            self._closed = True
            coordinator = getattr(self, "_close_coordinator", None)
            if coordinator is None:
                caller = threading.current_thread()
                def join_helpers():
                    deadline = time.monotonic() + 1.5
                    pending = []
                    for thread in (self._prewarm_thread, self._watchdog_thread):
                        if thread is None or thread is caller or thread is threading.current_thread():
                            continue
                        if thread.is_alive():
                            thread.join(timeout=max(0.0, deadline - time.monotonic()))
                        if thread.is_alive():
                            pending.append(thread.name)
                    if pending:
                        raise TimeoutError("helper thread cleanup incomplete")
                steps = [
                    ("lint_daemons", self.services.close_lint_daemons),
                    ("context_warmup", self.services.close_context_warmup),
                    ("status_dependencies", lambda: self._status_dependency_executor.shutdown(wait=False, cancel_futures=True)),
                    ("helper_threads", join_helpers),
                ]
                for name in ("automation", "recovery", "preprocessor", "external_tools", "work_orchestrator", "async_jobs", "background_gpu", "scheduler", "laya_lifecycle", "telemetry", "deterministic", "code_index", "endpoint_stats", "execution_pool", "training_collector"):
                    component = getattr(self, name, None)
                    if component is not None and callable(getattr(component, "close", None)):
                        steps.append((name, component.close))
                steps.append(("logging", shutdown_logging))
                coordinator = CloseCoordinator(steps)
                self._close_coordinator = coordinator
        report = coordinator.close(timeout)
        self.close_report = report
        if report["failed"] or report["pending"]:
            logger = getattr(self, "logger", None)
            if logger is not None:
                try:
                    logger.error("shutdown cleanup incomplete failed=%s pending=%s", report["failed"], report["pending"])
                except Exception:
                    report["logging_unconfirmed"] = True

