from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

from .services import (
    Any as Any,
    Path as Path,
    _LinkedCancelEvent as _LinkedCancelEvent,
    __version__ as __version__,
    _active_sqlite_databases as _active_sqlite_databases,
    capture_job_cancellation as capture_job_cancellation,
    closing as closing,
    connect_sqlite as connect_sqlite,
    copy as copy,
    current_job_should_stop as current_job_should_stop,
    estimate_tokens as estimate_tokens,
    json as json,
    json_dumps as json_dumps,
    re as re,
    reject_retired_tenancy_fields as reject_retired_tenancy_fields,
    rollout_feature_enabled as rollout_feature_enabled,
    stable_hash as stable_hash,
    threading as threading,
    time as time,
)


class ServiceCommandMixin:
    def _authorize_command_action(
        self, action: str, *, endpoint: str, task_id: str = ""
    ) -> dict[str, Any] | None:
        broker = self.commands
        authorize = getattr(broker, "authorize_auxiliary_action", None) if broker is not None else None
        if not callable(authorize):
            policy = {
                "success": False,
                "allowed": False,
                "requires_approval": True,
                "reason": "auxiliary action policy boundary unavailable",
                "owner": "agent_policy",
                "side_effect_class": "unknown",
                "terminal": True,
                "retryable": False,
            }
        else:
            policy = authorize(
                action, endpoint=endpoint, task_id=task_id
            )
        if policy.get("allowed", False):
            return None
        return {
            "success": False,
            "error": policy.get("reason", "command action denied by policy"),
            "policy": policy,
            "policy_blocked": True,
            "terminal": True,
            "retryable": False,
        }

    def command(
        self, args: dict[str, Any], *, request_cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        reject_retired_tenancy_fields(args)
        if self.commands is None:
            return {"success": False, "error": "command broker unavailable"}
        raw_action = args.get("action", "run")
        if (
            type(raw_action) is not str
            or not raw_action
            or raw_action != raw_action.strip()
            or "\x00" in raw_action
        ):
            return {
                "success": False,
                "error": "command action must be a canonical nonempty string",
                "policy": {
                    "success": False,
                    "allowed": False,
                    "requires_approval": False,
                    "reason": "command action must be a canonical nonempty string",
                    "owner": "agent_policy",
                    "side_effect_class": "unknown",
                    "terminal": True,
                    "retryable": False,
                },
                "policy_blocked": True,
                "terminal": True,
                "retryable": False,
            }
        action = raw_action
        if bool(args.get("rollback_on_failure", False)) and (action != "run" or bool(args.get("auto_fix", False))):
            return {
                "success": False,
                "error": "rollback_on_failure is supported only for direct run actions",
                "rollback_unsupported_action": True,
                "terminal": True,
                "retryable": False,
            }
        denied = self._authorize_command_action(
            action,
            endpoint="services.command",
            task_id=str(args.get("task_id", "")),
        )
        if denied is not None:
            return denied

        task_id = args.get("task_id", "")
        stream_id = args.get("stream_id", "")
        if any(not isinstance(value, str) or value != value.strip() or "\x00" in value for value in (task_id, stream_id)):
            return {"success": False, "error": "task_id and stream_id must be canonical strings", "terminal": True, "retryable": False}
        if "stream" in args and type(args["stream"]) is not bool:
            return {"success": False, "error": "stream must be a boolean", "terminal": True, "retryable": False}
        if not stream_id and task_id:
            stream_id = f"cmd:{task_id}"
        if args.get("stream", False) and not stream_id:
            return {"success": False, "error": "stream requires stream_id or task_id", "terminal": True, "retryable": False}
        log_callback = None
        if stream_id and self.agent_state is not None and getattr(self.agent_state, "enabled", False):
            def _log_cb(st: str, line: str) -> None:
                try:
                    from .agent_events import AgentEvent
                    self.agent_state.append(AgentEvent.create(
                        stream_id=stream_id,
                        kind="command.log",
                        payload={"stream": st, "chunk": line},
                        actor="command_broker",
                    ))
                except Exception:
                    pass
            log_callback = _log_cb

        if action == "patch_and_verify":
            return self.commands.patch_and_verify(
                str(args.get("patch", "")),
                str(args.get("cwd", args.get("root", "."))),
                command=str(args.get("command", "")),
                criterion=str(args.get("criterion", "")),
                task_id=str(args.get("task_id", "")),
                timeout=int(args.get("timeout", 0) or 0) or None,
                auto_rollback=bool(args.get("auto_rollback", True)),
                log_callback=log_callback,
            )
        if action == "preflight":
            raw_paths = args.get("paths") or args.get("files")
            paths_list = [str(p) for p in raw_paths] if isinstance(raw_paths, list) else ([str(raw_paths)] if raw_paths else None)
            return self.commands.preflight(
                str(args.get("cwd", args.get("root", "."))),
                paths=paths_list,
                timeout=int(args.get("timeout", 10) or 10),
            )
        if action in {"repair_loop", "auto_fix"}:
            return self.commands.repair_loop(
                str(args.get("command", "")), str(args.get("cwd", args.get("root", "."))),
                timeout=int(args.get("timeout", 0) or 0) or None,
                task_id=str(args.get("task_id", "")), criterion=str(args.get("criterion", "")),
                max_attempts=int(args.get("max_attempts", 3)),
                fix_generator=self._synthesize_repair_patch,
                log_callback=log_callback,
            )
        if action == "run":
            fence_kwargs = (
                {"_work_attempt_fence": args["writer_fence"]}
                if args.get("writer_fence") is not None else {}
            )
            if args.get("writer_fence") is not None and "work_id" in args:
                fence_kwargs["_work_order_id"] = args["work_id"]
            if request_cancel_event is not None:
                fence_kwargs["request_cancel_event"] = request_cancel_event
            if args.get("env"):
                fence_kwargs["env"] = args["env"]
            if args.get("stdin") is not None:
                fence_kwargs["stdin"] = args["stdin"]
            elif args.get("input") is not None:
                fence_kwargs["stdin"] = args["input"]
            return self.commands.run(
                str(args.get("command", "")), str(args.get("cwd", args.get("root", "."))),
                timeout=int(args.get("timeout", 0) or 0) or None, force=bool(args.get("force", False)),
                task_id=str(args.get("task_id", "")), criterion=str(args.get("criterion", "")),
                record_verification=bool(args.get("record_verification", True)),
                auto_fix=bool(args.get("auto_fix", False)),
                fix_generator=self._synthesize_repair_patch if bool(args.get("auto_fix", False)) else None,
                log_callback=log_callback,
                snapshot=bool(args.get("snapshot", False)),
                rollback_on_failure=bool(args.get("rollback_on_failure", False)),
                rollback_paths=args.get("paths") if isinstance(args.get("paths"), list) else None,
                **fence_kwargs,
            )
        if action == "run_affected":
            root = str(args.get("cwd", args.get("root", ".")))
            aff = self.affected_tests(
                root,
                changed_paths=args.get("paths"),
                path_hints=args.get("path_hints"),
            )
            if not isinstance(aff, dict) or not aff.get("success", True):
                return aff if isinstance(aff, dict) else {"success": False, "error": "affected-test selection returned no result"}
            cmd = aff.get("suggested_command", "")
            if not cmd:
                if aff.get("excluded_incompatible_tests"):
                    return {
                        "success": False,
                        "error": "No affected tests are compatible with the detected runner",
                        "affected_tests_summary": aff,
                    }
                if aff.get("selection_uncertain"):
                    fallback = aff.get("selection_fallback")
                    error = (
                        "affected test selection is uncertain and no complete test matrix is available"
                        if fallback == "unavailable_test_matrix"
                        else "affected test selection is uncertain and no allowed test command is available"
                    )
                    return {
                        "success": False,
                        "error": error,
                        "selection_uncertain": True,
                        "changed_files": aff.get("changed_files", []),
                    }
                return {
                    "success": True,
                    "message": "No affected tests found for current changes",
                    "changed_files": aff.get("changed_files", []),
                    "test_files": aff.get("test_files", []),
                }
            run_res = self.commands.run(
                cmd, root,
                timeout=int(args.get("timeout", 0) or 0) or None,
                force=bool(args.get("force", False)),
                task_id=str(args.get("task_id", "")),
                criterion=str(args.get("criterion", "")),
                log_callback=log_callback,
            )
            run_res["affected_tests_summary"] = aff
            return run_res
        if action == "format":
            root = str(args.get("cwd", args.get("root", ".")))
            return self.commands.format(root, paths=args.get("paths"),  timeout=int(args.get("timeout", 0) or 0) or None)
        if action == "cancel":
            return self.commands.cancel(
                str(args.get("command", "")), str(args.get("cwd", args.get("root", "."))),
                execution_id=str(args.get("execution_id", "")),
            )
        if action == "classify":
            return {"success": True, "classification": self.commands.classify(str(args.get("command", "")))}
        if action == "stats":
            return {"success": True, "stats": self.commands.stats()}
        if action == "discover":
            root = str(args.get("root", args.get("cwd", ".")))
            profile = self.repo_profile(root)
            deterministic = self.deterministic_query(root, "test lint build validation commands dependencies", 40) if self.deterministic is not None else {}
            scripts = deterministic.get("scripts", []) if isinstance(deterministic, dict) else []
            return {
                "success": bool(profile.get("success")),
                "validation_commands": profile.get("validation_commands", []),
                "manifest_scripts": scripts[:20],
                "profile_cache": profile.get("workspace_cache"),
                "deterministic": bool(scripts),
            }
        if action == "lint_fix":
            return self.lint_fix(str(args.get("cwd", args.get("root", "."))), command=args.get("command"), paths=args.get("paths"),  timeout=args.get("timeout"))
        if action == "spawn_daemon":
            daemon_command = args.get("argv") if args.get("argv") is not None else str(args.get("command", ""))
            return self.spawn_daemon(
                daemon_command,
                str(args.get("cwd", args.get("root", "."))),
                name=str(args.get("name", "")),
                env=args.get("env"),
                task_id=str(args.get("task_id", "")),
            )
        if action == "daemon_status":
            task_id = str(args.get("task_id", ""))
            if not task_id:
                return {
                    "success": False,
                    "error": "daemon status requires a registered task id",
                    "policy_blocked": True,
                    "terminal": True,
                    "retryable": False,
                }
            daemon_id = args.get("daemon_id", args.get("command"))
            return self.commands.daemon_status(daemon_id, task_id=task_id)
        if action == "stop_daemon":
            return self.stop_daemon(
                str(args.get("daemon_id", args.get("task_id", args.get("command", "")))),
                task_id=str(args.get("task_id", "")),
            )
        return {"success": False, "error": f"unknown command action: {action}"}

    def _synthesize_repair_patch(self, command: str, cwd: str, failure_result: dict[str, Any]) -> dict[str, str] | None:
        """Use verified remediation or one bounded local diagnostic for a failed command."""
        if not failure_result or failure_result.get("success"):
            return None
        rem = failure_result.get("remediation") or {}
        if rem.get("verified_fix") and isinstance(rem["verified_fix"], dict):
            return {str(k): str(v) for k, v in rem["verified_fix"].items()}
        features = self.config.get("features", {})
        if not isinstance(features, dict) or not bool(features.get("tasks", True)):
            return None
        if not rollout_feature_enabled(self.config, "local_diagnostic_dispatch"):
            failure_result["local_diagnostic_dispatch"] = {
                "available": False,
                "unsupported": True,
                "feature": "local_diagnostic_dispatch",
                "error": "local diagnostic dispatch is disabled (features.local_diagnostic_dispatch=false)",
            }
            return None
        summary = failure_result.get("failure_summary") or {}
        if not isinstance(summary, dict):
            summary = {}
        confidence = 0.95 if summary.get("path") and summary.get("line") else 0.70 if summary.get("path") else 0.25
        artifact_id = str(failure_result.get("artifact_id") or "")
        preview = str(failure_result.get("preview") or "")[:800]
        # Parsed failures are deterministic enough to avoid local inference. Local
        # diagnosis is read-only and never returns a mutation candidate; repair still
        # needs a verified deterministic fix.
        if confidence >= 0.50 or not artifact_id or not preview or not self._is_bounded_diagnostic_command(command):
            return None
        model = self.config.get("models", {}).get("heavy_code", "qwen2.5-coder:7b")
        prompt = (
            f"Investigate this low-confidence command failure in {cwd}:\nCommand: {command}\n"
            f"Failure summary: {json_dumps(summary, sort_keys=True)}\n"
            f"Artifact reference: {artifact_id}\nFailure preview:\n{preview}\n"
            "Do not request or infer raw command logs; use only this bounded preview.\n"
            "Return only a short JSON diagnosis. Do not propose edits, patches, commands, architecture, or security work."
        )
        try:
            res = self.proxy_request("/api/generate", {
                "model": model,
                "prompt": prompt,
                "format": {
                    "type": "object",
                    "properties": {"diagnosis": {"type": "string"}},
                    "required": ["diagnosis"],
                    "additionalProperties": False,
                },
                "options": {"num_predict": 320},
            }, "hub", "local_ai_task", diagnostic_timeout_seconds=20)
            raw_text = str(res.get("response", "")).strip()
            parsed = json.loads(raw_text)
            diagnosis = str(parsed.get("diagnosis", "")).strip()[:600] if isinstance(parsed, dict) else ""
            if diagnosis:
                failure_result["local_diagnostic"] = diagnosis
        except Exception:
            pass
        return None

    @staticmethod
    def _is_bounded_diagnostic_command(command: str) -> bool:
        """Allow only direct, non-mutating validation commands for L1 diagnosis."""
        normalized = command.strip().lower()
        if not normalized or any(char in normalized for char in "|&;><\n\r"):
            return False
        mutation = r"(?:fix|write|apply|update|install|delete)"
        if re.search(rf"(?:^|\s)--{mutation}(?:[-_][a-z0-9]+)*(?:\s|=|$)", normalized):
            return False
        # `normalized` is lowercase, so this also rejects Jest's --updateSnapshot.
        if re.search(r"(?:^|\s)--(?:snapshot[-_]?update|update(?:[-_]?snapshot)?s?)(?:\s|=|$)", normalized):
            return False
        if re.search(rf"(?:^|\s)--(?:snapshot|golden|inline[-_]?snapshot)[-_]{mutation}(?:[-_][a-z0-9]+)*(?:\s|=|$)", normalized):
            return False
        if re.search(rf"(?:^|\s)--(?:snapshots?|goldens?|inline[-_]?snapshot)(?:\s|=){mutation}(?:\s|$)", normalized):
            return False
        if re.search(r"(?:^|\s)-u(?:\s|=|$)", normalized):
            return False
        python = r"(?:python(?:\.exe)?|py(?:\.exe)?)"
        patterns = (
            rf"^{python}\s+(?:-[a-z0-9_-]+\s+)*-m\s+(?:pytest|unittest|mypy|pyright|ruff|flake8)(?:\s|$)",
            r"^(?:pytest|unittest|mypy|pyright|ruff|flake8|eslint|tsc)(?:\s|$)",
            r"^(?:npm|pnpm|yarn)\s+test(?:\s|$)",
            r"^(?:go|cargo|dotnet|gradle|mvn)\s+test(?:\s|$)",
        )
        return any(re.match(pattern, normalized) is not None for pattern in patterns)

    @staticmethod
    def _proxy_timeout_seconds(config: dict[str, Any], diagnostic_timeout_seconds: float | None = None) -> float:
        """Keep normal proxy timeouts intact; cap only explicit diagnostic calls."""
        if diagnostic_timeout_seconds is not None:
            return min(60.0, max(1.0, float(diagnostic_timeout_seconds)))
        return max(1.0, float(config.get("server", {}).get("request_timeout_seconds", 300)))

    def proxy_request(
        self,
        endpoint: str,
        payload: dict[str, Any],
        *,
        source: str,
        diagnostic_timeout_seconds: float | None = None,
        repository_root: str | None = None,
        model_route_requested: bool = False,
    ) -> dict[str, Any]:
        reject_retired_tenancy_fields(payload)
        if payload.get("stream") is True:
            return {"success": False, "error": "streaming is intentionally disabled through the affinity queue"}
        explicit_model = str(payload.get("model") or "").strip()
        model = explicit_model or str(self.config.get("models", {}).get("general", "qwen2.5-coder:7b"))
        clean = dict(payload)
        clean.pop("_hub_timeout_seconds", None)
        has_diagnostic_cap = diagnostic_timeout_seconds is not None
        request_timeout = self._proxy_timeout_seconds(self.config, diagnostic_timeout_seconds)
        clean["stream"] = False
        clean.setdefault("keep_alive", self.config.get("ollama", {}).get("keep_alive", "-1"))
        clean.pop("priority", None)
        proxy_profile = None
        semantic_query = ""
        if endpoint in {"/api/generate", "/api/chat"}:
            promptish = clean.get("prompt", clean.get("messages", []))
            if isinstance(promptish, str) and len(promptish.strip()) >= 8:
                semantic_query = promptish.strip()
            elif isinstance(promptish, list) and promptish:
                last_msg = promptish[-1]
                if isinstance(last_msg, dict) and isinstance(last_msg.get("content"), str):
                    semantic_query = last_msg.get("content", "").strip()

            # Repository-scoped direct requests can benefit from the same typed
            # model-route advisory as repository delegation. Explicit model
            # choices and requests without an authorized repository root remain
            # fully deterministic and never invoke Laya.
            if (
                endpoint in {"/api/generate", "/api/chat"}
                and (not explicit_model or model_route_requested)
                and isinstance(repository_root, str)
                and repository_root.strip()
                and len(semantic_query) >= 8
            ):
                try:
                    context_parts: list[str] = []
                    system = clean.get("system")
                    if isinstance(system, str) and system.strip():
                        context_parts.append(system.strip())
                    if isinstance(promptish, list):
                        for message in promptish[:-1]:
                            if isinstance(message, dict) and isinstance(message.get("content"), str):
                                content = message["content"].strip()
                                if content:
                                    context_parts.append(content)
                    request_context = "\n\n".join(context_parts)[-4096:]
                    route = self.router.classify(
                        semantic_query[:4096], request_context, "auto", "auto",
                    )
                    route.setdefault("model", model)
                    project_context, _, _, _ = self._resolve_local_task_project(repository_root)
                    laya_route = self._request_laya_model_route(
                        {"root": repository_root},
                        route,
                        semantic_query[:4096],
                        request_context,
                        project_settings=project_context.settings if project_context is not None else None,
                    )
                    if laya_route is not None and isinstance(route.get("model"), str) and route["model"].strip():
                        model = route["model"]
                except Exception as exc:
                    logger.debug("Laya proxy model-route fallback: %s", type(exc).__name__)

            input_tokens = estimate_tokens(json_dumps(promptish, ensure_ascii=False, default=str) if not isinstance(promptish, str) else promptish)
            opts = clean.get("options", {}) if isinstance(clean.get("options"), dict) else {}
            output_tokens = int(opts.get("num_predict", 0) or 0)
            vram_free = self._available_vram_mb() if hasattr(self, "_available_vram_mb") else None
            proxy_role = "opencode" if "opencode" in source else "proxy"
            clean, proxy_profile = self.model_policy.apply_payload(
                model, clean, role=proxy_role, input_tokens=input_tokens, output_tokens=output_tokens,
                preserve_explicit_think=True,
                vram_free_mb=vram_free,
            )
            # Pre-flight context compaction & ceiling clamp
            if proxy_profile is not None and input_tokens > proxy_profile.prompt_budget_tokens:
                budget = proxy_profile.prompt_budget_tokens
                if isinstance(clean.get("prompt"), str):
                    p_text = clean["prompt"]
                    target_chars = max(500, int(budget * 3.5))
                    if len(p_text) > target_chars:
                        head_len = int(target_chars * 0.4)
                        tail_len = int(target_chars * 0.4)
                        clean["prompt"] = (
                            p_text[:head_len]
                            + "\n\n[...context compacted by Local AI Hub for model budget...]\n\n"
                            + p_text[-tail_len:]
                        )
                elif isinstance(clean.get("messages"), list) and len(clean["messages"]) > 2:
                    msgs = list(clean["messages"])
                    system_msgs = [m for m in msgs if m.get("role") == "system"]
                    other_msgs = [m for m in msgs if m.get("role") != "system"]
                    while other_msgs and estimate_tokens(json_dumps(system_msgs + other_msgs)) > budget:
                        if len(other_msgs) <= 1:
                            break
                        other_msgs.pop(0)
                    # KV-Cache prefix stabilization: ensure system message content is canonical and placed first
                    for sm in system_msgs:
                        if isinstance(sm.get("content"), str):
                            sm["content"] = sm["content"].replace("\r\n", "\n").strip()
                    clean["messages"] = system_msgs + other_msgs

        if self.semantic_cache.enabled and len(semantic_query) >= 8:
            sem_scope = stable_hash({"proxy": endpoint, "model": model, "system": clean.get("system", "")})
            sem_val, sem_score = self.semantic_cache.get(sem_scope, semantic_query)
            if isinstance(sem_val, dict):
                res = copy.deepcopy(sem_val)
                res["_local_ai_cache"] = {"hit": True, "coalesced": False, "layer": "semantic", "similarity": sem_score}
                if proxy_profile is not None:
                    res["_local_ai_execution"] = proxy_profile.cache_scope()
                return res

        key = stable_hash({"proxy": endpoint, "payload": clean, "app_version": __version__})

        def compute() -> dict[str, Any]:
            submit_kwargs: dict[str, Any] = {"priority": int(payload.get("priority", 5))}
            if has_diagnostic_cap:
                submit_kwargs["wait_timeout"] = request_timeout
            return self.scheduler.submit(
                model, source=source, execute=lambda: self.runtime.request(endpoint, clean, timeout=request_timeout),
                **submit_kwargs,
            )

        raw, hit, coalesced = self.generation_cache.get_or_compute(key, compute)
        result = copy.deepcopy(raw)
        result["_local_ai_cache"] = {"hit": hit, "coalesced": coalesced, "layer": "exact" if hit else "single-flight" if coalesced else "ollama"}
        if proxy_profile is not None:
            result["_local_ai_execution"] = proxy_profile.cache_scope()

        if self.semantic_cache.enabled and len(semantic_query) >= 8 and isinstance(result, dict) and result.get("success", "error" not in result):
            try:
                sem_scope = stable_hash({"proxy": endpoint, "model": model, "system": clean.get("system", "")})
                self.semantic_cache.set(sem_scope, semantic_query, result)
            except Exception:
                pass

        return result

    def batch_delegate(self, args: dict[str, Any], *, cancel_event: threading.Event | None = None) -> dict[str, Any]:
        reject_retired_tenancy_fields(args)
        tasks = args.get("tasks", [])
        if not isinstance(tasks, list) or not tasks:
            return {
                "success": False,
                "error": "tasks must be a non-empty array",
                "terminal": True,
                "retryable": False,
                "request_not_sent": True,
                "input_count": len(tasks) if isinstance(tasks, list) else 0,
                "accepted_count": 0,
                "rejected_count": 0,
                "rejected_indices": [],
                "results": [],
            }
        input_count = len(tasks)
        if input_count > 16:
            return {
                "success": False,
                "error": "batch exceeds the maximum of 16 tasks",
                "terminal": True,
                "retryable": False,
                "request_not_sent": True,
                "input_count": input_count,
                "accepted_count": 0,
                "rejected_count": input_count,
                "rejected_range": {"start": 0, "end_exclusive": input_count},
                "rejected_indices": list(range(min(input_count, 64))),
                "rejected_indices_truncated": input_count > 64,
                "results": [],
            }
        item_ids: set[str] = set()
        for item in tasks:
            if isinstance(item, dict) and "id" in item:
                identity = item["id"]
                if (not isinstance(identity, str) or not identity or identity != identity.strip()
                        or len(identity) > 160 or "\x00" in identity or identity in item_ids):
                    return {"success": False, "error": "batch item ids must be unique non-empty canonical strings",
                            "terminal": True, "retryable": False, "request_not_sent": True,
                            "input_count": input_count, "accepted_count": 0, "rejected_count": input_count,
                            "rejected_indices": list(range(input_count)),
                            "results": []}
                item_ids.add(identity)
        prepared: list[tuple[int, str, dict[str, Any]]] = []
        for i, raw in enumerate(tasks):
            item = raw if isinstance(raw, dict) else {"task": str(raw)}
            route = self.router.classify(str(item.get("task", "")), str(item.get("context", "")), str(item.get("task_type", "auto")), str(item.get("complexity", "auto")))
            prepared.append((i, route["model"], item))
        # Group work by intended model and start with the currently resident model when possible.
        try:
            active = self.scheduler.status().get("active_model")
        except Exception:
            active = None
        prepared.sort(key=lambda item: (0 if item[1] == active else 1, item[1], item[0]))
        results: dict[int, dict[str, Any]] = {}
        default_priority = int(args.get("priority", 5))
        inherited_root = args.get("root") or args.get("cwd")
        from .async_jobs import report_job_progress
        parent_stop = capture_job_cancellation()
        effective_cancel = (_LinkedCancelEvent(cancel_event or threading.Event(), parent_stop)
                            if parent_stop is not None else cancel_event)
        def cancelled() -> bool:
            return (effective_cancel is not None and effective_cancel.is_set()) or current_job_should_stop()
        for i, _model, item in prepared:
            if cancelled():
                break
            item = dict(item)
            item.setdefault("priority", default_priority)
            if inherited_root and not item.get("root") and not item.get("cwd"):
                item["root"] = inherited_root
            try:
                results[i] = self.delegate(item, **({"cancel_event": effective_cancel} if effective_cancel is not None else {}))
            except Exception as exc:
                results[i] = {
                    "success": False,
                    "error": f"batch item failed ({type(exc).__name__})",
                }
            if not isinstance(results[i], dict) or type(results[i].get("success")) is not bool:
                results[i] = {"success": False, "error": "batch item returned an invalid result"}
            if "id" in item:
                results[i] = {**results[i], "id": item["id"]}
            report_job_progress(100.0 * len(results) / len(prepared), f"batch:{len(results)}/{len(prepared)}")
        was_cancelled = cancelled()
        if was_cancelled:
            for i in range(input_count):
                if i not in results:
                    results[i] = {"success": False, "cancelled": True, "reason": "cancelled", "request_not_sent": True}
                    if isinstance(tasks[i], dict) and "id" in tasks[i]:
                        results[i]["id"] = tasks[i]["id"]
        batch_result = {
            "success": not was_cancelled and all(r["success"] is True for r in results.values()),
            **({"cancelled": True} if was_cancelled else {}),
            "input_count": input_count,
            "accepted_count": input_count,
            "rejected_count": 0,
            "rejected_indices": [],
            "results": [results[i] for i in range(input_count)],
        }
        response_limit = args.get("response_budget_tokens")
        if type(response_limit) is int and response_limit >= 128:
            from .agent_diagnostics import project_agent_response
            from .token_accounting import json_tokens

            # Artifacts can outlive the diagnostics toggle. Store only the
            # normally visible projection, even if diagnostics are enabled now.
            try:
                safe_result = project_agent_response(batch_result, enabled=False)
                item_fields = {
                    "id", "success", "text", "result", "output", "error", "status", "status_code",
                    "terminal", "retryable", "request_not_sent", "outcome_unknown", "in_progress",
                    "cancelled", "timed_out", "partial", "degraded", "stale", "unsupported",
                    "fallback_used", "warning", "warnings", "artifact_id", "output_artifact_id",
                    "evidence_id", "evidence_ids", "request_id", "job_id", "context_id", "next_action",
                }
                safe_result["results"] = [
                    {key: value for key, value in item.items() if key in item_fields}
                    for item in safe_result["results"]
                ]
                if json_tokens(safe_result) * 2 + 256 > response_limit:
                    batch_result["output_artifact_id"] = self.artifacts.put_json(
                        safe_result, kind="batch-result",
                    )
            except Exception:
                # The actual batch outcome remains authoritative; MCP must
                # fail closed if it cannot deliver or recover those items.
                batch_result["output_artifact_unavailable"] = True
        return batch_result

    def optimize_databases(self) -> dict[str, Any]:
        """Checkpoint WAL files and run SQLite's optimize pragma for each store."""
        state_dir = Path(self.config["server"]["state_dir"])
        db_files = _active_sqlite_databases(state_dir)
        details = []
        bytes_freed = 0
        succeeded = 0
        for db in db_files:
            try:
                before_size = db.stat().st_size
                with closing(connect_sqlite(db, timeout_seconds=10.0)) as con:
                    checkpoint = con.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                    checkpoint_result = checkpoint.fetchone()
                    if checkpoint_result and checkpoint_result[0]:
                        raise RuntimeError("WAL checkpoint remained busy")
                    con.execute("PRAGMA optimize;")
                after_size = db.stat().st_size
                freed = max(0, before_size - after_size)
                bytes_freed += freed
                succeeded += 1
                details.append({"db": db.name, "success": True, "before_kb": before_size // 1024, "after_kb": after_size // 1024, "freed_kb": freed // 1024})
            except Exception as exc:
                details.append({"db": db.name, "success": False, "error": f"{type(exc).__name__}: {str(exc)[:400]}"})
        attempted = len(db_files)
        failed = attempted - succeeded
        return {
            "success": failed == 0,
            "partial": succeeded > 0 and failed > 0,
            **({"error": f"{failed} of {attempted} database maintenance operations failed"} if failed else {}),
            "databases_attempted": attempted,
            "databases_succeeded": succeeded,
            "databases_failed": failed,
            "databases_optimized": succeeded,
            "total_freed_kb": bytes_freed // 1024,
            "details": details,
        }

    def purge_stale_cache(self, days: int = 7) -> dict[str, Any]:
        """Purge cache entries older than N days to free disk space."""
        state_dir = Path(self.config["server"]["state_dir"])
        cutoff = time.time() - (days * 86400)
        cache_db = state_dir / "cache.sqlite"
        deleted_entries = 0
        if cache_db.is_file():
            try:
                with closing(connect_sqlite(cache_db, timeout_seconds=10.0)) as con:
                    cur = con.execute("DELETE FROM cache_entries WHERE accessed_at < ?", (cutoff,))
                    deleted_entries = cur.rowcount
                    con.commit()
                    con.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except Exception as exc:
                return {"success": False, "error": str(exc)}
        return {"success": True, "purged_entries": deleted_entries, "days_threshold": days}

    def resolve_all_errors(self, *, timeout_seconds: float = 2.0) -> dict[str, Any]:
        """Acknowledge and resolve all operational failures, crashes, errors, and agent incidents."""
        deadline = time.monotonic() + max(0.001, min(10.0, float(timeout_seconds)))

        def remaining() -> float:
            budget = deadline - time.monotonic()
            if budget <= 0:
                raise TimeoutError("error resolution time budget exceeded")
            return budget

        telemetry_res: dict[str, Any] = {}
        retryable = False
        if self.telemetry:
            try:
                telemetry_res = self.telemetry.resolve_errors(timeout_seconds=remaining())
            except TimeoutError:
                telemetry_res = {"success": False, "retryable": True, "error": "telemetry resolution time budget exceeded"}
            except Exception as exc:
                telemetry_res = {"success": False, "error_type": type(exc).__name__}
            retryable = retryable or bool(telemetry_res.get("retryable"))

        resolved_incidents = 0
        if self.incident_store:
            try:
                resolved_incidents = self.incident_store.resolve_all(
                    verified_fix="Resolved by operator",
                    root_cause="Operator manual resolve",
                    timeout_seconds=remaining(),
                )
            except TimeoutError:
                resolved_incidents = -1
                retryable = True
            except Exception:
                resolved_incidents = -1

        success = telemetry_res.get("success", True) is not False and resolved_incidents >= 0
        if not success:
            return {"success": False, "degraded": True, "retryable": retryable,
                    "telemetry": telemetry_res, "resolved_incidents": resolved_incidents}
        try:
            state_dir = Path(self.config["server"]["state_dir"])
            sup_status_path = state_dir / "supervisor.status.json"
            if sup_status_path.exists():
                raw = json.loads(sup_status_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    raw["restarts"] = 0
                    raw["last_error"] = ""
                    sup_status_path.write_text(json_dumps(raw, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

        return {
            "success": True,
            "telemetry": telemetry_res,
            "resolved_incidents": resolved_incidents,
        }

    def run_doctor(self) -> dict[str, Any]:
        """Run comprehensive system, GPU, model, and database diagnostics."""
        from .gpu_monitor import get_gpu_telemetry
        from .llama_cpp_runtime import llama_cpp_backend_selection
        checks = []

        selected = llama_cpp_backend_selection(self.config)
        if selected == "disabled":
            checks.append({"component": "Inference Backend", "status": "OFF", "detail": "Ollama and llama.cpp are disabled."})
        if selected in {"ollama", "ollama + llama.cpp (managed)"}:
            online = self.runtime.is_online()
            checks.append({"component": "Inference Backend (Ollama)", "status": "OK" if online else "FAIL", "detail": f"Installed models: {len(self.runtime.installed_models())}"})
        if selected not in {"disabled", "ollama"}:
            online = self.runtime.llama_cpp.is_online()
            managed = selected in {"llama.cpp (managed)", "ollama + llama.cpp (managed)"}
            runtime_status = self.runtime.llama_cpp_managed.status() if managed else {}
            mode = str(runtime_status.get("mode", "") or "device unreported")
            detail = f"Selected provider: {selected}; server {'online' if online else 'unavailable'}"
            if managed:
                detail += f"; execution device: {mode}"
                if not online and runtime_status.get("last_error"):
                    detail += f"; {runtime_status['last_error']}"
            checks.append({"component": "Inference Backend (llama.cpp)", "status": "OK" if online else "FAIL", "detail": detail})

        gpu = get_gpu_telemetry()
        checks.append({
            "component": "NVIDIA GPU",
            "status": "OK" if gpu.get("available") else "WARN",
            "detail": f"{gpu.get('gpu_name', 'N/A')} · {gpu.get('vram_used_mb', 0):.0f} / {gpu.get('vram_total_mb', 0):.0f} MB VRAM ({gpu.get('temperature_c', 0)}°C)"
        })

        state_dir = Path(self.config["server"]["state_dir"])
        dbs = _active_sqlite_databases(state_dir)
        checks.append({"component": "SQLite Databases", "status": "OK", "detail": f"{len(dbs)} active databases in {state_dir.name}"})

        prep_status = self.preprocessor.status() if self.preprocessor else {}
        checks.append({"component": "Preprocessor", "status": "OK" if prep_status.get("enabled") else "OFF", "detail": f"{len(prep_status.get('projects', []))} projects tracked"})

        return {"success": True, "timestamp": time.time(), "checks": checks}

    def eval_suite(self, payload: dict[str, Any]) -> dict[str, Any]:
        from .service_eval import eval_suite
        return eval_suite(self, payload)

    def prompt_eval(self, payload: dict[str, Any]) -> dict[str, Any]:
        from .service_eval import prompt_eval
        return prompt_eval(self, payload)

    def eval_drift(self, payload: dict[str, Any]) -> dict[str, Any]:
        from .service_eval import eval_drift
        return eval_drift(self, payload)

