from __future__ import annotations

from .services import (
    Any as Any,
    Path as Path,
    _LinkedCancelEvent as _LinkedCancelEvent,
    apply_path_coverage as apply_path_coverage,
    assess_semantic_result as assess_semantic_result,
    build_prompt as build_prompt,
    current_job_should_stop as current_job_should_stop,
    logger as logger,
    math as math,
    normalize_changed_paths as normalize_changed_paths,
    os as os,
    re as re,
    reject_retired_tenancy_fields as reject_retired_tenancy_fields,
    shlex as shlex,
    shutil as shutil,
    stable_hash as stable_hash,
    subprocess as subprocess,
    threading as threading,
    time as time,
)


class ServiceDelegationMixin:
    def _resolve_local_task_project(self, root: Any) -> tuple[Any | None, str, str, str]:
        root_value = str(root or "").strip()
        if not root_value:
            return None, "", "", ""
        try:
            from .project_config import resolve_project_context
            from .state_paths import configured_state_dir

            project = resolve_project_context(
                root_value,
                configured_state_dir(getattr(self, "config", {}), create=False),
            )
        except (OSError, ValueError) as project_exc:
            logger.debug(
                "Project task context unavailable (%s)",
                type(project_exc).__name__,
            )
            return None, "", "", ""

        snapshot = self.repo_tools.git_snapshot(root_value)
        revision = str(getattr(snapshot, "repository_revision", "") or "")[:200]
        namespace = str(project.coordination_id or "")
        return project, project.config_digest, namespace, revision

    def delegate(
        self, args: dict[str, Any], *, cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        reject_retired_tenancy_fields(args)
        if "prompt" in args:
            return {"success": False, "error": "delegate accepts task; prompt is not an alias"}
        if bool(args.get("conversation", False)):
            if str(args.get("profile", "")).strip():
                return self._conversation_error("", "conversations do not support profiles")
            if str(args.get("delivery", "sync")).strip().lower() != "sync":
                return self._conversation_error("", "conversations require delivery=sync")
        if str(args.get("profile", "")).strip():
            return self.delegate_profile(args, **({"cancel_event": cancel_event} if cancel_event is not None else {}))
        project_context, project_config_digest, project_namespace, project_revision = self._resolve_local_task_project(
            args.get("root") or args.get("cwd", "")
        )
        project_settings = project_context.settings if project_context is not None else None
        project_error_codes = getattr(getattr(project_context, "resolution", None), "error_codes", ())
        if not isinstance(project_error_codes, (list, tuple)):
            project_error_codes = ()
        project_warning = ""
        if project_error_codes:
            safe_codes = [
                code[:80] for code in (str(value) for value in project_error_codes[:8])
                if re.fullmatch(r"[A-Za-z0-9_.-]+", code)
            ]
            code_summary = ", ".join(safe_codes)
            project_warning = "Project settings invalid; defaults used" + (f" (codes: {code_summary})" if code_summary else ".")

        def attach_project_warning(result: dict[str, Any]) -> dict[str, Any]:
            if project_warning:
                warnings = result.get("warnings", [])
                warnings = list(warnings) if isinstance(warnings, (list, tuple)) else []
                warnings.append(project_warning)
                result["warnings"] = warnings
            return result

        task = args.get("task", "")
        context_value = args.get("context", "")
        if not isinstance(task, str):
            return {"success": False, "error": "task must be a string"}
        if not isinstance(context_value, str):
            return {"success": False, "error": "context must be a string"}
        if bool(args.get("conversation", False)):
            task = task.strip()
            if not task:
                return self._conversation_error("", "task is required")
        context = context_value
        task_type_override = str(args.get("task_type", "auto"))
        complexity_override = str(args.get("complexity", "auto"))
        route = self.router.classify(task, context, task_type_override, complexity_override)
        route = self._resident_optimize(route, task_type_override, complexity_override)
        try:
            route = self.router.apply_model_override(route, str(args.get("model", "")))
        except ValueError as exc:
            return {"success": False, "error": str(exc), "error_code": "model_override_below_quality_floor",
                    "status_code": 400, "terminal": True, "retryable": False}
        task_type = route["task_type"]
        if task_type in {"code", "review"}:
            project_role = "heavy_code" if route.get("complexity") == "heavy" else "fast_code"
        elif task_type == "reasoning":
            project_role = "reasoning" if route.get("complexity") == "heavy" else "heavy_code"
        else:
            project_role = "general"
        if project_settings is not None:
            route["model"], _project_payload = self.model_policy.apply_project_settings(
                route["model"], {"model": route["model"]},
                settings=project_settings, role=project_role,
            )
        operation = str(args.get("operation") or task_type).strip().lower()
        package = build_prompt(
            operation=operation,
            model=route["model"],
            role=task_type,
            profile=str(getattr(self, "config", {}).get("_hardware", {}).get("profile", "auto")),
            task=task,
            context=context,
            changed_paths=args.get("changed_paths") or (),
            evidence_ids=args.get("evidence_ids") or (),
            acceptance_criteria=args.get("acceptance_criteria") or (),
            repository_revision=str(args.get("repository_revision", "")),
            static_facts=str(args.get("static_facts", "")),
        )
        system = package.system
        trace_system = system
        # Conversation turns keep the compact transcript protocol so follow-ups
        # remain lossless; the richer static contract lives in the conversation
        # system message and one-shot operations use the full package.user form.
        prompt = self._conversation_user_prompt(task, context) if bool(args.get("conversation", False)) else package.user
        max_tokens = int(args.get("max_tokens", 4096))
        temperature = float(args.get("temperature", 0.15))
        source = f"delegate:{task_type}"
        priority = int(args.get("priority", 5))
        if bool(args.get("conversation", False)):
            if project_settings is not None:
                _conversation_model, project_payload = self.model_policy.apply_project_settings(
                    route["model"], {"model": route["model"], "system": system},
                    settings=project_settings, role=project_role,
                )
                system = str(project_payload.get("system", system))
            result = self._start_conversation(
                prompt=prompt, route=route, system=system, max_tokens=max_tokens,
                temperature=temperature, source=source, priority=priority, trace_system=trace_system,
                cancel_event=cancel_event,
            )
            return attach_project_warning(result)
        format_val = args.get("format") or args.get("json_schema")
        result = self._generate(
            route["model"], prompt, system,
            max_tokens, temperature, source=source, priority=priority,
            semantic_query=task, semantic_context_fingerprint=stable_hash(context),
            format=format_val,
            project_settings=project_settings,
            project_role=project_role,
            project_config_digest=project_config_digest,
            project_namespace=project_namespace,
            repository_revision=project_revision or str(args.get("repository_revision", "")),
            use_cache=project_context is None or bool(project_namespace),
            route=route,
            **({"cancel_event": cancel_event} if cancel_event is not None else {}),
        )
        if cancel_event is not None and cancel_event.is_set() and result.get("success") is True:
            return attach_project_warning({"success": False, "cancelled": True, "reason": "cancelled", "route": route})
        if result.get("cancelled") is True:
            result["route"] = route
            return attach_project_warning(result)
        result = self._apply_semantic_quality(result, task=task, evidence_paths=args.get("changed_paths") or ())
        result["route"] = route
        return attach_project_warning(result)

    @staticmethod
    def _apply_semantic_quality(result: dict[str, Any], *, task: str, evidence_paths: Any) -> dict[str, Any]:
        """Reject obvious ungrounded model paths while keeping output advisory."""
        if not isinstance(result, dict) or not result.get("success", "error" not in result):
            return result
        paths = evidence_paths if isinstance(evidence_paths, (list, tuple, set)) else ()
        if not paths:
            return result
        quality = assess_semantic_result(task, [str(path) for path in paths], result)
        result["advisory_only"] = True
        result["semantic_quality"] = quality
        if not quality.get("usable", False):
            reason = quality.get("bypass_reason", quality.get("reason", "quality_gate"))
            result["quality_warning"] = f"advisory semantic output requires verification: {reason}"
            result["bypass_reason"] = reason
        return result

    def delegate_profile(
        self, args: dict[str, Any], *, cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        reject_retired_tenancy_fields(args)
        profile_name = str(args.get("profile", "")).strip()
        if not self.profile_catalog.enabled:
            return {"success": False, "unsupported": True, "error": "Ollama subagent profiles disabled"}
        try:
            available = set(str(x) for x in self.runtime.installed_models())
        except Exception:
            available = None
        try:
            profile = self.profile_catalog.resolve(profile_name, available_models=available)
        except ValueError as exc:
            return {"success": False, "unsupported": True, "error": str(exc)}

        root = str(args.get("root", "")).strip()
        task = str(args.get("task", ""))
        if root:
            if self.tool_agent is None:
                return {"success": False, "unsupported": True, "error": "read-only Ollama tool agent unavailable"}
            return self.tool_agent.run_profile(
                profile.name,
                task,
                root,
                workspace=args.get("workspace"),
                seed_context=str(args.get("context", "")),
                priority=int(args.get("priority", 5)),
                **({"cancel_event": cancel_event} if cancel_event is not None else {}),
            )

        context = str(args.get("context", ""))
        candidate = str(args.get("candidate", ""))
        package = build_prompt(
            operation=str(args.get("operation") or profile.role or "delegate"),
            model=profile.model,
            profile=str(getattr(self, "config", {}).get("_hardware", {}).get("profile", "auto")),
            task=task,
            context=context + (f"\nCANDIDATE:\n{candidate}" if candidate else ""),
        )
        result = self._generate(
            profile.model,
            package.user,
            self.profile_catalog.system_contract(profile, task, prompt=package.system),
            int(args.get("max_tokens", 0) or profile.max_tokens),
            profile.temperature,
            source=f"profile:{profile.name}", priority=int(args.get("priority", 5)),
            semantic_query=task,
            semantic_context_fingerprint=stable_hash(context + candidate),
            **({"cancel_event": cancel_event} if cancel_event is not None else {}),
        )
        if cancel_event is not None and cancel_event.is_set() and result.get("success") is True:
            return {"success": False, "cancelled": True, "reason": "cancelled"}
        result.update({
            "profile": profile.name,
            "language": self.profile_catalog.detect_language(task),
            "advisory_only": profile.advisory_only,
            "declared_model": profile.declared_model,
            "resolved_model": profile.model,
            "model_fallback": profile.model_fallback,
            "model_fallback_reason": profile.model_fallback_reason,
            "tools_used": [],
        })
        return result

    def review(self, args: dict[str, Any], *, cancel_event: threading.Event | None = None) -> dict[str, Any]:
        reject_retired_tenancy_fields(args)
        if "context" in args:
            return {"success": False, "error": "review accepts code; context is not an alias"}
        code = args.get("code", "")
        instructions = args.get("instructions", "Review the supplied code or diff and report actionable defects only.")
        if not isinstance(code, str):
            return {"success": False, "error": "code must be a string"}
        if not isinstance(instructions, str):
            return {"success": False, "error": "instructions must be a string"}
        payload = {key: value for key, value in args.items() if key not in {"code", "instructions"}}
        payload["task_type"] = "review"
        payload["task"] = instructions + "\nFor each finding, cite a supplied file path and a verifiable post-image line. Include citation.quote only when the supplied material contains the exact full source line; otherwise state the evidence limitation without inventing a location."
        payload["context"] = code
        payload["operation"] = str(args.get("operation", "review"))
        payload.setdefault("max_tokens", 8192)
        payload.setdefault("format", "json")
        result = self.delegate(payload, cancel_event=cancel_event) if cancel_event is not None else self.delegate(payload)
        if not isinstance(result, dict) or result.get("success") is not True:
            return result
        from .semantic_quality import assess_review_consistency, constrain_semantic_quality
        result = dict(result)
        quality = assess_review_consistency(result, args.get("changed_paths", ()), source_diff=code)
        result["advisory_only"] = True
        result["review_consistency"] = quality
        result["semantic_quality"] = constrain_semantic_quality(quality, result)
        if not quality["usable"]:
            warning = f"advisory review requires verification: {quality['reason']}"
            result["quality_warning"] = "; ".join(filter(None, (result.get("quality_warning"), warning)))
            result.setdefault("bypass_reason", quality["reason"])
        return result

    def reason(self, args: dict[str, Any], *, cancel_event: threading.Event | None = None) -> dict[str, Any]:
        reject_retired_tenancy_fields(args)
        if "task" in args:
            return {"success": False, "error": "reason accepts problem; task is not an alias"}
        problem = args.get("problem", "")
        if not isinstance(problem, str):
            return {"success": False, "error": "problem must be a string"}
        payload = {key: value for key, value in args.items() if key != "problem"}
        payload["task_type"] = "reasoning"
        payload["task"] = problem
        payload["operation"] = str(args.get("operation", "reason"))
        payload.setdefault("max_tokens", 4096)
        if cancel_event is not None:
            return self.delegate(payload, cancel_event=cancel_event)
        return self.delegate(payload)

    def distill_command_error(
        self, failure: dict[str, Any], *, cancel_event: threading.Event | None = None,
        timeout_seconds: float | None = None,
    ) -> str:
        """Use the local task route only when command parsing found no coordinates."""
        if cancel_event is None:
            from .client import CURRENT_REQUEST_CANCEL_EVENT
            cancel_event = CURRENT_REQUEST_CANCEL_EVENT.get()
        summary = str(failure.get("summary", "")).strip()[:800]
        if not summary or (cancel_event is not None and cancel_event.is_set()):
            return ""
        request = {
            "problem": "Summarize this unstructured command failure in one actionable sentence. Do not invent a file, line, test, or fix.",
            "context": summary,
            "max_tokens": 120,
            "complexity": "simple",
        }
        timer = None
        effective_cancel = cancel_event
        diagnostic_deadline = None
        if timeout_seconds is not None:
            import math
            if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 30:
                return ""
            deadline_event = threading.Event()
            effective_cancel = _LinkedCancelEvent(deadline_event, cancel_event.is_set) if cancel_event is not None else deadline_event
            diagnostic_deadline = time.monotonic() + float(timeout_seconds)
            timer = threading.Timer(float(timeout_seconds), deadline_event.set)
            timer.daemon = True
            timer.start()
        try:
            result = self.reason(request, cancel_event=effective_cancel) if effective_cancel is not None else self.reason(request)
        finally:
            if timer is not None:
                timer.cancel()
        if ((effective_cancel is not None and effective_cancel.is_set())
                or (diagnostic_deadline is not None and time.monotonic() >= diagnostic_deadline)):
            return ""
        if not isinstance(result, dict) or result.get("success") is not True or not isinstance(result.get("text"), str):
            return ""
        if "semantic_quality" in result:
            quality = result["semantic_quality"]
            if not isinstance(quality, dict) or quality.get("usable") is not True:
                return ""
        return result["text"].strip()[:300]

    def second_opinion(self, args: dict[str, Any], *, cancel_event: threading.Event | None = None) -> dict[str, Any]:
        reject_retired_tenancy_fields(args)
        question = str(args.get("question", "") or args.get("task", "") or args.get("prompt", ""))
        candidate = str(args.get("candidate", "") or args.get("code", ""))
        context = str(args.get("context", "") or args.get("text", ""))
        focus = str(args.get("focus", "correctness, missing assumptions, edge cases, and alternative explanations"))
        route = self.router.classify(
            f"{question}\n{focus}",
            f"{candidate}\n{context}",
            "reasoning",
            str(args.get("complexity", "auto")),
        )
        try:
            route = self.router.apply_model_override(route, str(args.get("model", "")))
        except ValueError as exc:
            return {"success": False, "error": str(exc), "error_code": "model_override_below_quality_floor",
                    "status_code": 400, "terminal": True, "retryable": False}
        model = str(route["model"])
        package = build_prompt(
            operation="second_opinion",
            model=model,
            role="reasoning",
            profile=str(getattr(self, "config", {}).get("_hardware", {}).get("profile", "auto")),
            task=question,
            context=f"CANDIDATE ANSWER / PLAN:\n{candidate}\n\nADDITIONAL CONTEXT:\n{context}",
            changed_paths=args.get("changed_paths") or (),
            static_facts=f"FOCUS: {focus}",
        )
        result = self._generate(
            model, package.user, package.system,
            int(args.get("max_tokens", 4096)), float(args.get("temperature", 0.2)),
            source="second-opinion", priority=int(args.get("priority", 6)),
            semantic_query=f"{question}\n{focus}", semantic_context_fingerprint=stable_hash({"candidate": candidate, "context": context}),
            route=route,
            **({"cancel_event": cancel_event} if cancel_event is not None else {}),
        )
        if cancel_event is not None and cancel_event.is_set() and result.get("success") is True:
            return {"success": False, "cancelled": True, "reason": "cancelled", "route": route}
        if result.get("cancelled") is True:
            result["route"] = route
            return result
        result = self._apply_semantic_quality(result, task=question, evidence_paths=args.get("changed_paths") or ())
        result["route"] = route
        return result

    def speculative_draft(self, args: dict[str, Any], *, cancel_event: threading.Event | None = None) -> dict[str, Any]:
        """Draft code using fast model and verify against affected tests."""
        reject_retired_tenancy_fields(args)
        if cancel_event is not None and cancel_event.is_set():
            return {"success": False, "cancelled": True, "reason": "cancelled"}
        aliases = {"prompt", "path", "cwd"} & args.keys()
        if aliases:
            return {"success": False, "error": "speculative_draft rejects aliases: " + ", ".join(sorted(aliases))}
        task = args.get("task", "")
        file_path = args.get("file", "")
        context = args.get("context", "")
        root = args.get("root", ".")
        if not isinstance(task, str) or not isinstance(file_path, str) or not isinstance(context, str) or not isinstance(root, str):
            return {"success": False, "error": "task, file, context, and root must be strings"}
        resolved_root = Path(root).resolve()

        if not task:
            return {"success": False, "error": "task is required"}

        models_cfg = self.config.get("models", {}) if isinstance(self.config.get("models"), dict) else {}
        fast_model = str(models_cfg.get("fast_code", "qwen2.5-coder:3b"))
        draft_model = str(args.get("draft_model") or models_cfg.get("draft_code", "")).strip()
        use_cascade = bool(args.get("use_cascade", bool(draft_model and draft_model != fast_model)))
        cascade_layers: list[str] = []

        if use_cascade and draft_model and draft_model != fast_model:
            # Tier 1: Draft model generates rapid candidate patch
            draft_package = build_prompt(
                operation="speculative_draft",
                model=draft_model,
                role="code",
                profile=str(getattr(self, "config", {}).get("_hardware", {}).get("profile", "auto")),
                task=task,
                context=f"FILE: {file_path}\n\n{context}",
                changed_paths=[file_path] if file_path else (),
            )
            draft_res = self._generate(
                draft_model,
                draft_package.user,
                draft_package.system + " Return the minimal candidate code or diff.",
                min(int(args.get("max_tokens", 2048)), 1024),
                float(args.get("temperature", 0.1)),
                source="speculative-draft:tier1",
                priority=5,
                **({"cancel_event": cancel_event} if cancel_event is not None else {}),
            )
            candidate_val = draft_res.get("text") or draft_res.get("response") or ""
            candidate_code = candidate_val.strip() if isinstance(candidate_val, str) else ""

            if candidate_code and draft_res.get("success") is not False:
                cascade_layers.append(draft_model)
                refine_prompt = (
                    f"TASK: {task}\nFILE: {file_path}\n\n"
                    f"CANDIDATE DRAFT CODE (grounded starting proposal):\n{candidate_code}\n\n"
                    f"CONTEXT (authority):\n{context}"
                )
                gen_result = self._generate(
                    fast_model,
                    refine_prompt,
                    "Complete and verify the candidate code or diff against the task and context. Return clean, final code or diff only.",
                    int(args.get("max_tokens", 2048)),
                    float(args.get("temperature", 0.1)),
                    source="speculative-draft:tier3",
                    priority=5,
                    **({"cancel_event": cancel_event} if cancel_event is not None else {}),
                )
                cascade_layers.append(fast_model)
            else:
                package = build_prompt(
                    operation="speculative_draft",
                    model=fast_model,
                    role="code",
                    profile=str(getattr(self, "config", {}).get("_hardware", {}).get("profile", "auto")),
                    task=task,
                    context=f"FILE: {file_path}\n\n{context}",
                    changed_paths=[file_path] if file_path else (),
                )
                gen_result = self._generate(
                    fast_model,
                    package.user,
                    package.system + " Return the minimal valid code or diff only after grounding it in the supplied file and context.",
                    int(args.get("max_tokens", 2048)),
                    float(args.get("temperature", 0.1)),
                    source="speculative-draft",
                    priority=5,
                    **({"cancel_event": cancel_event} if cancel_event is not None else {}),
                )
        else:
            package = build_prompt(
                operation="speculative_draft",
                model=fast_model,
                role="code",
                profile=str(getattr(self, "config", {}).get("_hardware", {}).get("profile", "auto")),
                task=task,
                context=f"FILE: {file_path}\n\n{context}",
                changed_paths=[file_path] if file_path else (),
            )
            gen_result = self._generate(
                fast_model,
                package.user,
                package.system + " Return the minimal valid code or diff only after grounding it in the supplied file and context.",
                int(args.get("max_tokens", 2048)),
                float(args.get("temperature", 0.1)),
                source="speculative-draft",
                priority=5,
                **({"cancel_event": cancel_event} if cancel_event is not None else {}),
            )
        if cancel_event is not None and cancel_event.is_set():
            return {"success": False, "cancelled": True, "reason": "cancelled"}
        if gen_result.get("cancelled") is True:
            return gen_result

        draft_value = gen_result.get("text") or gen_result.get("response") or ""
        draft_code = draft_value.strip() if isinstance(draft_value, str) else ""
        if gen_result.get("success") is False:
            return {
                "success": False,
                "model": gen_result.get("model", fast_model),
                "draft": "",
                "verification": {"syntax_valid": False},
                "validated": False,
                "error": str(gen_result.get("error") or "Draft generation failed."),
            }
        if not draft_code:
            return {
                "success": False,
                "model": gen_result.get("model", fast_model),
                "draft": "",
                "verification": {"syntax_valid": False},
                "validated": False,
                "error": "Model returned an empty draft.",
            }
        verification: dict[str, Any] = {"syntax_valid": True}
        if file_path.endswith(".py"):
            import ast
            try:
                clean_code = re.sub(r"^```[\w]*\n", "", draft_code.strip())
                clean_code = re.sub(r"\n```$", "", clean_code)
                ast.parse(clean_code)
                verification["syntax_valid"] = True
            except Exception as e:
                verification["syntax_valid"] = False
                verification["syntax_error"] = str(e)

        if (
            bool(args.get("verify_tests", False))
            and file_path
            and self.commands
            and verification["syntax_valid"]
        ):
            if cancel_event is not None and cancel_event.is_set():
                return {"success": False, "cancelled": True, "reason": "cancelled"}
            aff = self.affected_tests(str(resolved_root), changed_paths=[file_path])
            if aff.get("suggested_command"):
                cmd_res = self.commands.run(
                    aff["suggested_command"], str(resolved_root),
                    **({"request_cancel_event": cancel_event} if cancel_event is not None else {}),
                )
                verification["tests_passed"] = bool(cmd_res.get("success"))
                verification["test_summary"] = cmd_res.get("summary", "")

        if bool(args.get("smart_review", False)):
            if cancel_event is not None and cancel_event.is_set():
                return {"success": False, "cancelled": True, "reason": "cancelled"}
            smart_model = str(self.config.get("models", {}).get("heavy_code", "qwen2.5-coder:3b"))
            review_prompt = f"REVIEW DRAFT IMPLEMENTATION:\nTask: {task}\nDraft Code:\n{draft_code}\nDoes this draft correctly solve the task without syntax or logical bugs? Return a short JSON object: {{\"approved\": true/false, \"confidence\": 0.0-1.0, \"summary\": \"...\"}}"
            review_res = self._generate(
                smart_model,
                review_prompt,
                "You are an expert code reviewer. Return only valid JSON.",
                512,
                0.1,
                source="speculative-review",
                priority=6,
                **({"cancel_event": cancel_event} if cancel_event is not None else {}),
            )
            if cancel_event is not None and cancel_event.is_set():
                return {"success": False, "cancelled": True, "reason": "cancelled"}
            if review_res.get("cancelled") is True:
                return review_res
            review_text = review_res.get("text") or review_res.get("response") or ""
            verification["smart_review"] = {
                "model": smart_model,
                "response": review_text,
                "approved": "true" in review_text.lower(),
            }

        if cancel_event is not None and cancel_event.is_set():
            return {"success": False, "cancelled": True, "reason": "cancelled"}
        res: dict[str, Any] = {
            "success": True,
            "model": fast_model,
            "draft": draft_code,
            "verification": verification,
            "validated": bool(verification.get("tests_passed")) and verification["syntax_valid"],
            "duration_ms": gen_result.get("duration_ms", 0),
        }
        if cascade_layers:
            res["cascade"] = cascade_layers
            res["draft_model"] = cascade_layers[0]
            res["target_model"] = cascade_layers[-1]
        return res

    def speculative_lint(self, args: dict[str, Any]) -> dict[str, Any]:
        """Run opt-in, read-only lint against only caller-supplied changed paths."""
        reject_retired_tenancy_fields(args)
        root = str(args.get("root", args.get("cwd", ".")))
        try:
            paths = normalize_changed_paths(root, list(args.get("paths") or []))
        except ValueError as exc:
            return {"success": False, "error": str(exc), "terminal": True, "retryable": False}
        custom = str(args.get("command", "")).strip()
        ruff_executable = shutil.which("ruff")
        lint_config = self.config.get("speculative_lint", {})
        daemon_mode = bool(lint_config.get("daemon_mode", True))
        biome_suffixes = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts", ".json", ".jsonc"}
        biome_executable = (
            shutil.which("biome")
            if not custom and all(Path(path).suffix.lower() in biome_suffixes for path in paths)
            else None
        )
        if custom:
            target_text = " ".join(subprocess.list2cmdline([path]) for path in paths) if os.name == "nt" else " ".join(shlex.quote(path) for path in paths)
            command = custom.replace("{paths}", target_text)
            if command == custom:
                command = f"{custom} {target_text}"
        elif ruff_executable and all(Path(path).suffix.lower() == ".py" for path in paths):
            target_text = " ".join(subprocess.list2cmdline([path]) for path in paths) if os.name == "nt" else " ".join(shlex.quote(path) for path in paths)
            command = f"ruff check {target_text}"
        elif biome_executable and daemon_mode:
            target_text = " ".join(subprocess.list2cmdline([path]) for path in paths) if os.name == "nt" else " ".join(shlex.quote(path) for path in paths)
            command = f"{subprocess.list2cmdline([biome_executable]) if os.name == 'nt' else shlex.quote(biome_executable)} ci {target_text}"
        elif biome_executable:
            target_text = " ".join(subprocess.list2cmdline([path]) for path in paths) if os.name == "nt" else " ".join(shlex.quote(path) for path in paths)
            command = f"{subprocess.list2cmdline([biome_executable]) if os.name == 'nt' else shlex.quote(biome_executable)} ci {target_text}"
        elif shutil.which("eslint"):
            target_text = " ".join(subprocess.list2cmdline([path]) for path in paths) if os.name == "nt" else " ".join(shlex.quote(path) for path in paths)
            command = f"eslint {target_text}"
        else:
            return {"success": False, "error": "no read-only linter found (tried ruff, biome, eslint)", "terminal": True, "retryable": False}
        lowered = command.lower()
        if any(marker in lowered for marker in ("--fix", " -w ", "autopep8", "cargo fix", "gofmt -w")):
            return {"success": False, "error": "speculative lint rejects formatter or auto-fix commands", "terminal": True, "retryable": False}
        biome_daemon = bool(not custom and biome_executable and daemon_mode)
        classification = self.commands.classify(command) if self.commands is not None else {"allowed": False, "class": "unknown"}
        if not classification.get("allowed", False) or classification.get("class") in {"mutating", "dangerous"}:
            return {"success": False, "error": "speculative lint requires an allowed read-only command", "classification": classification, "terminal": True, "retryable": False}
        if not custom and ruff_executable and all(Path(path).suffix.lower() == ".py" for path in paths) and daemon_mode:
            result = self._lint_daemons.run(
                ruff_executable, root, paths=paths,
                timeout=float(args.get("timeout", self.config.get("speculative_lint", {}).get("timeout_seconds", 120)) or 120),
                should_stop=current_job_should_stop,
            )
            result.update({"paths": paths, "command": command})
            return apply_path_coverage(result, args, paths)
        if biome_daemon:
            daemon_timeout = args["timeout"] if "timeout" in args else lint_config.get("timeout_seconds", 120)
            if (isinstance(daemon_timeout, bool) or not isinstance(daemon_timeout, (int, float))
                    or not math.isfinite(daemon_timeout) or daemon_timeout <= 0):
                return {"success": False, "provider": "biome", "daemon_mode": True,
                        "transport": "owned_foreground_lsp", "error": "Biome timeout must be a positive finite number",
                        "terminal": True, "retryable": False}
            result = self._biome_daemons.run(
                biome_executable, root, paths=paths,
                timeout=daemon_timeout,
                should_stop=current_job_should_stop,
            )
            result.update({"paths": paths, "command": command})
            return apply_path_coverage(result, args, paths)
        result = self.commands.run(
            command,
            str(Path(root).expanduser().resolve(strict=False)),

            timeout=int(args.get("timeout", self.config.get("speculative_lint", {}).get("timeout_seconds", 120)) or 120),
            force=True,
            auto_fix=False,
            bypass_cache=True,
        )
        result.update({"read_only": True, "auto_fix": False, "paths": paths, "command": command})
        result.update({"daemon_mode": False, "transport": "one_shot"})
        if biome_executable and not custom:
            result["provider"] = "biome"
        return apply_path_coverage(result, args, paths)

    def close_lint_daemons(self) -> None:
        self._lint_daemons.close()
        self._biome_daemons.close()

    def task_scaffold(self, args: dict[str, Any], *, cancel_event: threading.Event | None = None) -> dict[str, Any]:
        """Generate boilerplate code, DTOs, interfaces, or unit test scaffolds using local model."""
        reject_retired_tenancy_fields(args)
        if cancel_event is not None and cancel_event.is_set():
            return {"success": False, "cancelled": True, "reason": "cancelled"}
        aliases = {"spec", "task"} & args.keys()
        if aliases:
            return {"success": False, "error": "scaffold rejects aliases: " + ", ".join(sorted(aliases))}
        spec = args.get("prompt", "")
        context = args.get("context", "")
        if not isinstance(spec, str) or not isinstance(context, str):
            return {"success": False, "error": "prompt and context must be strings"}
        language = str(args.get("language", "python"))
        max_tokens = int(args.get("max_tokens", 4096))

        if not spec:
            return {"success": False, "error": "prompt is required"}

        fast_model = str(self.config.get("models", {}).get("fast_code", "qwen2.5-coder:7b"))
        prompt = (
            f"You are a fast code scaffolder. Generate clean, idiomatic {language} code implementing the following specification:\n\n"
            f"SPECIFICATION:\n{spec}\n\n"
        )
        if context:
            prompt += f"CONTEXT / EXISTING CODE:\n{context}\n\n"
        prompt += (
            "REQUIREMENTS:\n"
            "- Emit ONLY valid code with minimal necessary docstrings.\n"
            "- Implement all requested types, data structures, constructors, and method signatures.\n"
            "- Do not include markdown conversational preamble or apologies.\n"
        )
        gen_result = self._generate(
            fast_model,
            prompt,
            "You are a precise code scaffolder. Emit only valid source code.",
            max_tokens,
            float(args.get("temperature", 0.1)),
            source="scaffold",
            priority=5,
            **({"cancel_event": cancel_event} if cancel_event is not None else {}),
        )
        if cancel_event is not None and cancel_event.is_set():
            return {"success": False, "cancelled": True, "reason": "cancelled"}
        if gen_result.get("cancelled") is True:
            return gen_result
        if gen_result.get("success") is False:
            return {
                "success": False,
                "code": "",
                "language": language,
                "model": gen_result.get("model", fast_model),
                "tokens_generated": gen_result.get("tokens", 0),
                "validated": False,
                "error": str(gen_result.get("error") or "Code generation failed."),
            }
        draft_value = gen_result.get("text") or gen_result.get("response") or ""
        draft_code = draft_value if isinstance(draft_value, str) else ""
        clean_code = re.sub(r"^```[\w]*\n", "", draft_code.strip())
        clean_code = re.sub(r"\n```$", "", clean_code)
        if not clean_code.strip():
            return {
                "success": False,
                "code": "",
                "language": language,
                "model": gen_result.get("model", fast_model),
                "tokens_generated": gen_result.get("tokens", 0),
                "validated": False,
                "error": "Model returned an empty scaffold.",
            }

        return {
            "success": True,
            "code": clean_code,
            "language": language,
            "model": gen_result.get("model", fast_model),
            "tokens_generated": gen_result.get("tokens", 0),
            "validated": False,
        }

    def vision(
        self,
        args: dict[str, Any],
        *,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Multimodal image understanding via local vision model."""
        reject_retired_tenancy_fields(args)
        from .vision_service import VisionService

        return VisionService(
            config=self.config,
            runtime=self.runtime,
            artifacts=self.artifacts,
            model_policy=self.model_policy,
            repo_tools=self.repo_tools,
            max_output_tokens=self._VISION_MAX_OUTPUT_TOKENS,
        ).run(args, cancel_event=cancel_event)

    def transcribe(
        self,
        args: dict[str, Any],
        *,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        from .service_transcription import transcribe
        return transcribe(self, args, cancel_event=cancel_event)

    def benchmark(self) -> dict[str, Any]:
        """Manual tiny benchmark used to seed the adaptive runtime cost model."""
        models=[]
        for key in ("fast_code","heavy_code","reasoning","general"):
            model=str(self.config.get("models",{}).get(key,"") or "")
            if model and model not in models: models.append(model)
        results=[]
        for model in models:
            started=time.perf_counter()
            def run(m=model):
                payload, _profile = self.model_policy.apply_payload(
                    m, {"model":m,"prompt":"Reply exactly: OK","stream":False,"keep_alive":self.config.get("ollama",{}).get("keep_alive","-1"),"options":{"num_predict":8,"temperature":0}},
                    role="benchmark", input_tokens=4, output_tokens=8, preserve_explicit_think=False,
                )
                return self.runtime.request("/api/generate", payload)
            try:
                raw=self.scheduler.submit(model, source="benchmark", execute=run, priority=2, wait_timeout=float(self.config.get("resilience",{}).get("scheduler_wait_timeout_seconds",330)))
            except Exception as exc:
                raw={"error":str(exc)}
            elapsed=(time.perf_counter()-started)*1000
            success="error" not in raw
            if success and self.tuner is not None:
                try: self.tuner.observe(model, raw, elapsed)
                except Exception: pass
            results.append({"model":model,"success":success,"elapsed_ms":round(elapsed,1),"load_ms":round(float(raw.get("load_duration",0) or 0)/1e6,1),"eval_count":int(raw.get("eval_count",0) or 0)})
        return {"success":all(x["success"] for x in results),"results":results,"autotune":self.tuner.stats() if self.tuner is not None else {"enabled":False}}

    def evaluation(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action", "report")).strip().lower()
        if action == "record":
            try:
                duration_ms = float(payload.get("duration_ms", 0) or 0)
            except (TypeError, ValueError):
                return {"success": False, "error": "duration_ms must be numeric", "terminal": True}
            return self.telemetry.record_evaluation(
                task_id=str(payload.get("task_id", "")),
                cohort=str(payload.get("cohort", "")),
                quality_pass=payload.get("quality_pass"),
                test_pass=payload.get("test_pass"),
                duration_ms=duration_ms,
            )
        if action == "report":
            try:
                days = max(1, min(int(payload.get("days", 30) or 30), self.telemetry.rollup_retention_days))
            except (TypeError, ValueError):
                return {"success": False, "error": "days must be an integer", "terminal": True}
            return {"success": True, "evaluation": self.telemetry.report(days).get("evaluation", {})}
        return {"success": False, "error": "unknown evaluation action", "terminal": True}

