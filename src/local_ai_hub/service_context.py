from __future__ import annotations

from .services import (
    AgentStateStore as AgentStateStore,
    Any as Any,
    ConsistencyRequest as ConsistencyRequest,
    ContextCompiler as ContextCompiler,
    ContextRequest as ContextRequest,
    GuardWarning as GuardWarning,
    Path as Path,
    configured_state_dir as configured_state_dir,
    hashlib as hashlib,
    json as json,
    re as re,
    reject_retired_tenancy_fields as reject_retired_tenancy_fields,
    stable_hash as stable_hash,
    threading as threading,
    time as time,
)


class ServiceContextMixin:
    @staticmethod
    def _adaptive_label(value: Any, limit: int = 160) -> str:
        text = str(value or "")[:limit]
        if re.search(r"(?i)(api[_ -]?key|access[_ -]?token|password|secret|authorization|bearer)\s*[:=]", text):
            return "<redacted>"
        return re.sub(r"[^A-Za-z0-9_./:@+ -]", " ", text).strip()[:limit]

    def _adaptive_memory_revision(self, request: ConsistencyRequest) -> str:
        explicit = str(getattr(request, "memory_revision", "") or "")[:200]
        if explicit:
            return explicit
        store = getattr(self.consistency_guard, "memory_store", None)
        for name in ("memory_revision", "revision"):
            value = getattr(store, name, "") if store is not None else ""
            if callable(value):
                try:
                    value = value(request.root)
                except TypeError:
                    value = value()
            if value:
                return str(value)[:200]
        return ""

    def _context_preload_source(self) -> ContextCompiler | None:
        compiler = getattr(self, "context_compiler", None)
        if compiler is not None:
            return compiler
        try:
            compiler = ContextCompiler(
                AgentStateStore(
                    configured_state_dir(getattr(self, "config", {}), create=False) / "agent_state.sqlite",
                    enabled=False,
                ),
                config=getattr(self, "config", {}),
            )
        except Exception:
            return None
        self.context_compiler = compiler
        return compiler

    def _apply_context_preloads(
        self, request: ConsistencyRequest, base: dict[str, Any],
        *, coordination_id: str = "",
    ) -> tuple[dict[str, Any], tuple[GuardWarning, ...]]:
        compiler = self._context_preload_source()
        if compiler is None:
            return base, ()
        try:
            elements, preload_warnings = compiler.preload_elements(ContextRequest(
                task_id=request.task_id,
                token_budget=max(1, int(request.token_budget)),
                changed_paths=tuple(request.changed_paths or ()),
                root=request.root,
                session_id=request.session_id,
                coordination_id=coordination_id,
                phase=request.phase,
                focus=tuple(request.focus or ()),
                preload_profile=request.preload_profile,
            ))
        except Exception:
            return base, ()
        if not elements and not preload_warnings:
            return base, ()

        enriched = dict(base)
        evidence = [dict(item) for item in (base.get("evidence") or ()) if isinstance(item, dict)]
        context = str(base.get("context", "") or "").strip()
        for element in elements:
            content = str(element.content or "")
            context = "\n\n".join(item for item in (context, content) if item)
            provenance = dict(element.provenance or {})
            evidence.append({
                "evidence_id": element.element_id,
                "source_kind": element.source_kind,
                "path": provenance.get("path", ""),
                "text": content,
                "reason": element.reason,
            })
        enriched["context"] = context
        enriched["evidence"] = evidence[:64]
        enriched["preload_profile"] = request.preload_profile
        enriched["preload_evidence_ids"] = [element.element_id for element in elements[:32]]
        warning_objects = tuple(
            GuardWarning(
                "warning",
                str(item.get("code", "preload_warning")),
                str(item.get("message", "preload warning")),
                affected_paths=(str(item["path"]),) if item.get("path") else (),
                recommended_action="review configured context preload",
            )
            for item in preload_warnings
            if isinstance(item, dict)
        )
        return enriched, warning_objects

    def _adaptive_relevance(self, request: ConsistencyRequest, evidence: tuple[dict[str, Any], ...], revision: str, memory_revision: str) -> dict[str, Any]:
        guard = self.consistency_guard
        if guard is None or not evidence:
            return {"success": False, "degraded": True, "degraded_reason": "no_authoritative_evidence", "warnings": []}
        try:
            projector = getattr(guard, "structured_evidence", None)
            if callable(projector):
                structured = list(projector(evidence, limit=24))
            else:
                structured = []
                for item in evidence[:24]:
                    if isinstance(item, dict):
                        structured.append({
                            "evidence_id": str(item.get("evidence_id") or item.get("id") or "")[:200],
                            "authority": "deterministic",
                            "path": self._adaptive_label(item.get("path"), 240),
                            "start_line": max(0, int(item.get("start_line", 0) or 0)),
                            "end_line": max(0, int(item.get("end_line", 0) or 0)),
                        })
            structured = [item for item in structured if isinstance(item, dict) and item.get("evidence_id")][:24]
            if not structured:
                return {"success": False, "degraded": True, "degraded_reason": "no_authoritative_evidence", "warnings": []}
            focus = [self._adaptive_label(item, 80) for item in tuple(getattr(request, "focus", ()) or ())[:16]]
            model_focus = ["focus-" + hashlib.sha256(item.encode("utf-8", "replace")).hexdigest()[:12] for item in focus if item]
            phase = self._adaptive_label(request.phase, 80)
            if phase.casefold() not in {"plan", "discover", "edit", "implementation", "review", "test", "handoff"}:
                phase = "other"
            preload_profile = self._adaptive_label(request.preload_profile, 120)
            if preload_profile.casefold() not in {"", "default", "plan", "edit", "review", "test", "handoff"}:
                preload_profile = "profile-" + hashlib.sha256(preload_profile.encode("utf-8", "replace")).hexdigest()[:12]
            payload = {
                "operation": "context_relevance",
                "phase": phase,
                "focus": model_focus,
                "preload_profile": preload_profile,
                "repository_revision": str(revision)[:200],
                "memory_revision": str(memory_revision)[:200],
                "evidence": structured,
                "limits": {"max_selected_evidence": 12, "max_claims": 16, "max_gaps": 16, "max_wording_chars": 1200},
            }
            params = {
                "repository_revision": str(revision)[:200],
                "task_id": request.task_id,
                "session_id": request.session_id,
                "phase": self._adaptive_label(request.phase, 80),
                "memory_revision": str(memory_revision)[:200],
                "focus": tuple(focus),
                "preload_profile": self._adaptive_label(request.preload_profile, 120),
                "changed_paths": tuple(request.changed_paths),
                "query": self._adaptive_label(request.query, 800),
                "retrieval_config_revision": stable_hash({
                    "search": getattr(self, "config", {}).get("search", {}),
                    "features": getattr(self, "config", {}).get("features", {}),
                    "preprocessing": getattr(self, "config", {}).get("preprocessing", {}),
                    "rag": getattr(self, "config", {}).get("rag", {}),
                    "retrieval": getattr(self, "config", {}).get("retrieval", {}),
                    "external_tools": getattr(self, "config", {}).get("external_tools", {}),
                    "code_intelligence": getattr(self, "config", {}).get("code_intelligence", {}),
                }),
                "evidence_ids": tuple(str(item["evidence_id"])[:200] for item in structured),
            }

            def compute() -> dict[str, Any]:
                queue_state = self._adaptive_relevance_queue_state()
                with queue_state["lock"]:
                    if queue_state["until"] > time.monotonic():
                        return {
                            "success": False,
                            "degraded": True,
                            "degraded_reason": queue_state["reason"],
                            "warnings": [],
                        }
                try:
                    pending_count = getattr(getattr(self, "scheduler", None), "pending_count", None)
                    if callable(pending_count) and pending_count() > 0:
                        return {"success": False, "degraded": True, "degraded_reason": "backend_busy", "warnings": []}
                    models = getattr(self, "config", {}).get("models", {})
                    model = getattr(self, "config", {}).get("context_relevance_model") or models.get("context_relevance_model") or models.get("fast_code") or models.get("general") or "context-relevance"
                    active_model = getattr(getattr(self, "scheduler", None), "active_model", None)
                    if callable(active_model) and str(active_model() or "") != str(model):
                        return {"success": False, "degraded": True, "degraded_reason": "backend_model_mismatch", "warnings": []}
                    generated = self._generate(
                        str(model),
                        json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
                        "Return JSON only. Use only supplied deterministic evidence IDs. Never invent repository facts, repeat source text, reveal secrets, or use the user prompt as evidence.",
                        min(1024, max(128, int(request.token_budget) // 2)),
                        0.0,
                        source="context-relevance", priority=4,
                        semantic_query="context relevance",
                        semantic_context_fingerprint=stable_hash(params),
                        internal=True,
                        format={"type": "object"},
                        # Context relevance is optional; deterministic evidence remains
                        # available when local inference exceeds its latency budget.
                        request_timeout_seconds=3.0,
                    )
                except Exception:
                    return {"success": False, "degraded": True, "degraded_reason": "model_error", "warnings": []}
                if not isinstance(generated, dict) or not generated.get("success"):
                    is_result = isinstance(generated, dict)
                    error_type = str(generated.get("error_type") or "") if is_result else ""
                    error_code = str(generated.get("error_code") or "") if is_result else ""
                    timed_out = is_result and generated.get("timed_out") is True
                    if error_type == "QueueFullError":
                        with queue_state["lock"]:
                            queue_state["until"] = max(
                                queue_state["until"],
                                time.monotonic() + self._ADAPTIVE_RELEVANCE_QUEUE_BACKOFF_SECONDS,
                            )
                            queue_state["reason"] = "backend_queue_full"
                        degraded_reason = "backend_queue_full"
                    elif timed_out or error_code == "model_request_timeout":
                        with queue_state["lock"]:
                            queue_state["until"] = max(
                                queue_state["until"],
                                time.monotonic() + self._ADAPTIVE_RELEVANCE_TIMEOUT_BACKOFF_SECONDS,
                            )
                            queue_state["reason"] = "backend_timeout"
                        degraded_reason = "backend_timeout"
                    elif error_code == "local_backend_transport":
                        degraded_reason = "backend_transport"
                    else:
                        degraded_reason = "model_unavailable"
                    return {"success": False, "degraded": True, "degraded_reason": degraded_reason, "warnings": []}
                raw = generated.get("text") or generated.get("response") or ""
                try:
                    if isinstance(raw, dict):
                        parsed = raw
                    else:
                        text = str(raw).strip()
                        if text.startswith("```"):
                            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S)
                        parsed = json.loads(text)
                    if not isinstance(parsed, dict):
                        raise ValueError("structured response required")
                except Exception:
                    return {"success": False, "degraded": True, "degraded_reason": "invalid_model_output", "warnings": []}
                claims = parsed.get("claims") if isinstance(parsed.get("claims"), list) else []
                postprocess = getattr(guard, "postprocess_model_claims", None)
                if callable(postprocess):
                    checked = postprocess(evidence, claims, request)
                else:
                    checked = {"claims": [], "unknowns": [], "warnings": []}
                authoritative = set(checked.get("authoritative_evidence_ids", ()))
                selected = [str(item)[:200] for item in (parsed.get("selected_evidence_ids") or ()) if str(item) in authoritative][:12]
                gaps = [self._adaptive_label(item, 240) for item in (parsed.get("gaps") or ())][:16]
                wording = self._adaptive_label(parsed.get("wording"), 1200)
                warning_dicts = []
                for warning in checked.get("warnings", ())[:24]:
                    converter = getattr(warning, "to_dict", None)
                    warning_dicts.append(converter() if callable(converter) else dict(warning) if isinstance(warning, dict) else {"code": "unsupported_model_claim", "message": self._adaptive_label(warning, 240)})
                return {
                    "success": True,
                    "selected_evidence_ids": selected,
                    "claims": list(checked.get("claims", ()))[:16],
                    "unknowns": [self._adaptive_label(item, 240) for item in checked.get("unknowns", ())][:16],
                    "gaps": [item for item in gaps if item],
                    "wording": wording,
                    "warnings": warning_dicts[:24],
                }

            return self._repo_cached("adaptive-relevance", request.root, params, compute)
        except Exception:
            return {"success": False, "degraded": True, "degraded_reason": "relevance_error", "warnings": []}

    def schedule_task_context_warmup(self, task: Any, *, root: str,
                                     changed_paths: list[str] | None = None) -> bool:
        """Optional prediction; reuse only the normal adaptive cache and its fences."""
        if not isinstance(root, str) or not root or not (task.contract.acceptance_criteria or changed_paths):
            return False
        if not bool(self.config.get("preprocessing", {}).get("task_context_warmup", True)):
            return False
        if not Path(root).is_absolute() or not Path(root).is_dir() or len(root) > 400:
            return False
        from .agent_tasks import _task_matches_scope
        from .operational_mode import load_operational_mode
        from .repository_scope import RepositoryScopeError, authorized_repository_root

        try:
            canonical = authorized_repository_root(self.config, root)
        except RepositoryScopeError:
            return False
        if not _task_matches_scope(task, canonical, task.task_id):
            return False

        def allowed() -> bool:
            snapshot = load_operational_mode(configured_state_dir(self.config, create=False))
            return snapshot.mode == "active" and not snapshot.degraded

        if not allowed():
            return False
        request = ConsistencyRequest(
            root=canonical, task_id=task.task_id,
            query=task.contract.goal, session_id=task.context.session_id,
            changed_paths=tuple(changed_paths or ())[:64], token_budget=4000,
        )
        expected_updated = task.updated_at
        key = stable_hash({"request": request.__dict__, "task_updated_at": expected_updated})

        def warm() -> None:
            if not allowed():
                return
            try:
                if authorized_repository_root(self.config, root) != canonical:
                    return
            except RepositoryScopeError:
                return
            store = getattr(self, "task_store", None)
            current = store.get(task.task_id) if store is not None else None
            if current is None or current.updated_at != expected_updated or not _task_matches_scope(current, canonical, task.task_id):
                return
            if str(getattr(current.status, "value", current.status)) in {"completed", "cancelled", "failed", "abandoned"}:
                return
            self.adaptive_context_pack(request, mode="adaptive")

        return self._context_warmup.submit(key, warm)

    def close_context_warmup(self) -> None:
        worker = getattr(self, "_context_warmup", None)
        if worker is not None:
            worker.close()

    def adaptive_context_pack(self, request: ConsistencyRequest, *, mode: str = "adaptive", since_hash: str = "") -> dict[str, Any]:
        from .service_hybrid_context import adaptive_context_pack as _impl_adaptive_pack
        return _impl_adaptive_pack(self, request, mode=mode, since_hash=since_hash)

    def fast_context(self, request: ContextRequest) -> dict[str, Any]:
        from .service_hybrid_context import fast_context as _impl_fast_context
        return _impl_fast_context(self, request.root, request.task_id, request.token_budget)

    def _hybrid_context(self, *args: Any, **kwargs: Any) -> Any:
        from .service_hybrid_context import _hybrid_context as _impl_hybrid_context
        return _impl_hybrid_context(self, *args, **kwargs)

    @staticmethod
    def _rrf_fuse(*args: Any, **kwargs: Any) -> Any:
        from .service_hybrid_context import _rrf_fuse as _impl_rrf_fuse
        return _impl_rrf_fuse(*args, **kwargs)

    @staticmethod
    def _external_candidate_paths(*args: Any, **kwargs: Any) -> Any:
        from .service_hybrid_context import _external_candidate_paths as _impl_ext_paths
        return _impl_ext_paths(*args, **kwargs)

    def _external_context_candidates(self, *args: Any, **kwargs: Any) -> Any:
        from .service_hybrid_context import _external_context_candidates as _impl_ext_cand
        return _impl_ext_cand(self, *args, **kwargs)

    @staticmethod
    def _adaptive_builtin_confidence(*args: Any, **kwargs: Any) -> Any:
        from .service_hybrid_context import _adaptive_builtin_confidence as _impl_conf
        return _impl_conf(*args, **kwargs)

    def _hybrid_context_uncached(self, *args: Any, **kwargs: Any) -> Any:
        from .service_hybrid_context import _hybrid_context_uncached as _impl_uncached
        return _impl_uncached(self, *args, **kwargs)

    def delegate_repo(self, args: dict[str, Any], *, cancel_event: threading.Event | None = None) -> dict[str, Any]:
        reject_retired_tenancy_fields(args)
        if cancel_event is None:
            from .client import CURRENT_REQUEST_CANCEL_EVENT
            cancel_event = CURRENT_REQUEST_CANCEL_EVENT.get()
        if cancel_event is not None and cancel_event.is_set():
            return {"success": False, "cancelled": True, "reason": "cancelled"}
        if str(args.get("profile", "")).strip():
            return self.delegate_profile(args, **({"cancel_event": cancel_event} if cancel_event is not None else {}))
        root = str(args.get("root", "."))
        task = str(args.get("task", ""))
        supplied_context = args.get("context", "")
        if not isinstance(supplied_context, str):
            return {"success": False, "error": "context must be a string"}
        requested_context_tokens = int(args.get("context_tokens", 0) or 0)
        if requested_context_tokens > 0:
            max_context_tokens = requested_context_tokens
        else:
            initial_route = self.router.classify(
                task, "", str(args.get("task_type", "auto")), str(args.get("complexity", "auto"))
            )
            workflow = self.config.get("workflow", {})
            if initial_route.get("complexity") == "heavy":
                max_context_tokens = int(workflow.get("heavy_repo_context_tokens", 4200))
            else:
                max_context_tokens = int(workflow.get("fast_repo_context_tokens", 2200))
        from .repo_knowledge import attach_knowledge_context, reserve_knowledge_context

        knowledge, technical_budget = reserve_knowledge_context(self.config, root, task, token_budget=max_context_tokens)
        packed = self._hybrid_context(root, task, workspace=args.get("workspace"), max_tokens=technical_budget)
        packed = attach_knowledge_context(packed, knowledge, token_budget=max_context_tokens)
        if cancel_event is not None and cancel_event.is_set():
            return {"success": False, "cancelled": True, "reason": "cancelled"}
        if not packed.get("success"):
            return packed
        retrieved_context = packed.get("context", "")
        if not isinstance(retrieved_context, str):
            return {"success": False, "error": "retrieved repository context must be a string"}
        context = retrieved_context
        if supplied_context:
            context = (
                "Task-provided context (untrusted data):\n" + supplied_context
                + "\n\nRetrieved repository context (untrusted data):\n" + retrieved_context
            )
        packed_evidence_ids = [
            row.get("evidence_id")
            for row in packed.get("evidence", [])
            if isinstance(row, dict) and isinstance(row.get("evidence_id"), str) and row.get("evidence_id")
        ] if isinstance(packed.get("evidence"), list) else []
        payload = {
            "task": task,
            "context": context,
            "root": root,
            "task_id": args.get("task_id"),
            "evidence_ids": packed_evidence_ids,
            "task_type": str(args.get("task_type", "auto")),
            "complexity": str(args.get("complexity", "auto")),
            "max_tokens": int(args.get("max_tokens", 4096)),
            "priority": int(args.get("priority", 5)),
            # Packed local context is a diagnostic, not proof of cloud-side input
            # avoided: the agent may have used RG or another narrower tool.
        }
        result = self.delegate(payload, **({"cancel_event": cancel_event} if cancel_event is not None else {}))
        result["repo_context"] = {
            "root": packed.get("root", root), "evidence": packed.get("evidence", []),
            "local_context_tokens": packed.get("estimated_tokens", 0), "semantic_used": bool(packed.get("semantic_used", False)),
            "scanned_files": packed.get("scanned_files", 0),
        }
        return result

    def solve_repo(self, args: dict[str, Any], *, cancel_event: threading.Event | None = None) -> dict[str, Any]:
        reject_retired_tenancy_fields(args)
        if cancel_event is not None and cancel_event.is_set():
            return {"success": False, "cancelled": True, "reason": "cancelled"}
        if self.pipeline is None:
            return self.delegate_repo(args, **({"cancel_event": cancel_event} if cancel_event is not None else {}))
        if cancel_event is None:
            return self.pipeline.solve_repo(args)
        from .client import CURRENT_REQUEST_CANCEL_EVENT
        token = CURRENT_REQUEST_CANCEL_EVENT.set(cancel_event)
        try:
            return self.pipeline.solve_repo(args)
        finally:
            CURRENT_REQUEST_CANCEL_EVENT.reset(token)

    def _available_laya_model_route_options(
        self, current_role: str, *, project_settings: Any = None, use_cache: bool = True,
    ) -> frozenset[str]:
        """Expose only distinct model routes whose exact installed digest is verified."""
        from .laya_decisions import filter_verified_model_route_options

        router = getattr(self, "router", None)
        model_for_role = getattr(router, "model_for_role", None)
        if not callable(model_for_role):
            return frozenset()
        runtime = getattr(self, "runtime", None)
        if runtime is None:
            return frozenset()
        is_online = getattr(runtime, "is_online", None)
        if callable(is_online) and not is_online():
            return frozenset()

        models_by_role: dict[str, str] = {}
        installed_digests: dict[str, str] = {}
        roles = ("fast_code", "heavy_code", "reasoning", "general")
        now = time.monotonic()
        digest_cache = getattr(self, "_laya_digest_cache", None)
        if not isinstance(digest_cache, dict):
            digest_cache = {}
            self._laya_digest_cache = digest_cache

        for role in roles:
            try:
                model = model_for_role(role)
            except Exception:
                model = ""
            if not isinstance(model, str) or not model.strip():
                models_by_role[role] = ""
                continue
            if project_settings is not None:
                try:
                    model, _ = self.model_policy.apply_project_settings(
                        model, {"model": model}, settings=project_settings, role=role,
                    )
                except Exception:
                    models_by_role[role] = ""
                    continue
            model = str(model or "").strip()
            models_by_role[role] = model
            if not model or model in installed_digests:
                continue
            cached_entry = digest_cache.get(model) if use_cache else None
            if cached_entry is not None and (now - cached_entry[0]) < 60.0:
                digest = cached_entry[1]
            else:
                try:
                    digest = runtime.model_digest(model)
                except Exception:
                    digest = None
                digest_cache[model] = (now, digest)
            if isinstance(digest, str):
                installed_digests[model] = digest

        verified = filter_verified_model_route_options(
            models_by_role, installed_digests, current_role,
        )
        return verified

    def route_context(self, args: dict[str, Any], *, cancel_event: threading.Event | None = None) -> dict[str, Any]:
        reject_retired_tenancy_fields(args)
        if cancel_event is not None and cancel_event.is_set():
            return {"success": False, "cancelled": True, "reason": "cancelled"}
        if self.token_router is None:
            return {"success": False, "error": "lossless token router unavailable"}
        if "task" in args or "context" in args:
            return {
                "success": False,
                "error": "route accepts query and text; task and context are not aliases",
            }
        query = args.get("query", "")
        text = args.get("text", "")
        if not isinstance(query, str):
            return {"success": False, "error": "query must be a string"}
        if not isinstance(text, str):
            return {"success": False, "error": "text must be a string"}
        path = args.get("path")
        if path is not None and not isinstance(path, str):
            return {"success": False, "error": "path must be a string"}
        label = args.get("label")
        if label is not None and not isinstance(label, str):
            return {"success": False, "error": "label must be a string"}
        if path:
            root = args.get("root", ".")
            if not isinstance(root, str):
                return {"success": False, "error": "root must be a string"}
        from .client import CURRENT_REQUEST_CANCEL_EVENT
        token = CURRENT_REQUEST_CANCEL_EVENT.set(cancel_event) if cancel_event is not None else None
        try:
            result = (self.token_router.route_file(root, path, query) if path
                      else self.token_router.route_text(text, query, path=label))
        finally:
            if token is not None:
                CURRENT_REQUEST_CANCEL_EVENT.reset(token)
        if cancel_event is not None and cancel_event.is_set():
            return {"success": False, "cancelled": True, "reason": "cancelled"}
        return result

