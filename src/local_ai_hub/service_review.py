from __future__ import annotations

from .services import (
    Any as Any,
    _MAX_REVIEW_DIFF_CHUNKS as _MAX_REVIEW_DIFF_CHUNKS,
    _REVIEW_DIFF_CONTEXT_FRACTION as _REVIEW_DIFF_CONTEXT_FRACTION,
    _REVIEW_DIFF_MIN_CHUNK_TOKENS as _REVIEW_DIFF_MIN_CHUNK_TOKENS,
    _REVIEW_SYNTHESIS_CONTEXT_TOKENS as _REVIEW_SYNTHESIS_CONTEXT_TOKENS,
    _merge_review_segment_results as _merge_review_segment_results,
    _review_failure_details as _review_failure_details,
    _review_model_identity as _review_model_identity,
    _review_text_error as _review_text_error,
    _split_review_diff as _split_review_diff,
    estimate_tokens as estimate_tokens,
    fit_text as fit_text,
    json_dumps as json_dumps,
    re as re,
    reject_retired_tenancy_fields as reject_retired_tenancy_fields,
    review_diff_complexity as review_diff_complexity,
    stable_hash as stable_hash,
    threading as threading,
)


class ServiceReviewMixin:
    def review_diff(self, args: dict[str, Any], *, cancel_event: threading.Event | None = None) -> dict[str, Any]:
        reject_retired_tenancy_fields(args)
        def cancelled() -> bool:
            return cancel_event is not None and cancel_event.is_set()
        def cancelled_result() -> dict[str, Any]:
            return {"success": False, "cancelled": True, "reason": "cancelled"}
        def delegate_review(payload: dict[str, Any]) -> dict[str, Any]:
            if cancelled():
                return cancelled_result()
            return self.delegate(payload, **({"cancel_event": cancel_event} if cancel_event is not None else {}))
        if cancelled():
            return cancelled_result()
        diff_text = args.get("diff")
        if isinstance(diff_text, str) and diff_text.strip():
            diff_tokens = estimate_tokens(diff_text)
            diff = {
                "success": True,
                "diff": diff_text,
                "changed_files": [],
                "truncated": False,
                "estimated_tokens": diff_tokens,
                "original_estimated_tokens": diff_tokens,
            }
        else:
            diff = self.repo_diff(
                str(args.get("root", ".")), str(args.get("base", "HEAD")), bool(args.get("staged", False)),
                max_tokens=int(args.get("diff_tokens", self.config.get("token_saving", {}).get("max_diff_tokens", 8000))),
                path=args.get("path"),
            )
        if cancelled():
            return cancelled_result()
        if not diff.get("success"):
            return diff
        # Git omits untracked files. An explicitly named file can be read via
        # bounded source pages only while every page describes the same bytes.
        path = args.get("path")
        excluded = diff.get("untracked_files_excluded", [])
        if (not diff.get("diff", "").strip() and isinstance(path, str)
                and path.replace("\\", "/") in excluded
                and len(excluded) == 1 and diff.get("untracked_inventory_complete") is True
                and path == path.strip()
                and not any((char.isspace() and char != " ") or char == '"' for char in path)):
            from .source_slice import read_source_slice
            requested_path = path.replace("\\", "/")
            root = str(args.get("root", "."))
            source = read_source_slice(root, requested_path, line_end=200, max_chars=12000)
            total = source.get("total_lines")
            digest = source.get("file_sha256")
            parts = []
            valid = (source.get("success") is True and source.get("complete") is True
                     and type(total) is int and 0 <= total <= 3200
                     and isinstance(digest, str) and len(digest) == 64
                     and source.get("relative_path") == requested_path
                     and isinstance(source.get("text"), str))
            if valid:
                parts.append(source["text"])
                for start in range(201, total + 1, 200):
                    page = read_source_slice(root, requested_path, line_start=start, line_end=start + 199, max_chars=12000)
                    if (page.get("success") is not True or page.get("complete") is not True
                            or page.get("total_lines") != total or page.get("file_sha256") != digest
                            or page.get("relative_path") != requested_path or not isinstance(page.get("text"), str)):
                        valid = False
                        break
                    parts.append(page["text"])
            source_text = "".join(parts)
            if valid and "\r" not in source_text.replace("\r\n", "\n"):
                lines = source_text.replace("\r\n", "\n").split("\n")
                if lines[-1] == "":
                    lines.pop()
                addition = "".join("+" + line + "\n" for line in lines)
                added_diff = (f"diff --git a/{requested_path} b/{requested_path}\n"
                              f"--- /dev/null\n+++ b/{requested_path}\n@@ -0,0 +1,{len(lines)} @@\n" + addition)
                diff_budget = int(args.get("diff_tokens", self.config.get("token_saving", {}).get("max_diff_tokens", 8000)))
                if not fit_text(added_diff, diff_budget).truncated:
                    diff = {**diff, "diff": added_diff, "changed_files": [requested_path],
                            "untracked_files_excluded": [], "review_source_sha256": digest}
        if cancelled():
            return cancelled_result()
        if not diff.get("diff", "").strip():
            excluded = diff.get("untracked_files_excluded", [])
            complete = diff.get("untracked_inventory_complete", False)
            if excluded or complete is not True:
                return {"success": False, "error": "No tracked diff to review; untracked files are excluded or their inventory is incomplete.",
                        "changed_files": [], "diff_truncated": False, "untracked_files_excluded": excluded,
                        "untracked_inventory_complete": complete, "review_scope_complete": False}
            return {"success": True, "text": "No diff to review.", "changed_files": [], "diff_truncated": False}
        provided_diff = isinstance(diff_text, str) and bool(diff_text.strip())
        excluded = diff.get("untracked_files_excluded", [])
        inventory_complete = None if provided_diff else diff.get("untracked_inventory_complete", False)
        scope_complete = not provided_diff and not excluded and inventory_complete is True and not bool(diff.get("truncated", False))
        det_diff = {}
        if self.deterministic is not None:
            try:
                det_diff = self.deterministic.diff_facts(str(diff.get("diff", "")))
            except Exception:
                det_diff = {}
        if isinstance(diff_text, str) and diff_text.strip():
            parsed_files = det_diff.get("files") if isinstance(det_diff, dict) else None
            if isinstance(parsed_files, list) and all(isinstance(path, str) and path for path in parsed_files):
                diff["changed_files"] = parsed_files
            if self.deterministic is not None and (
                not isinstance(parsed_files, list)
                or not parsed_files
                or not all(isinstance(path, str) and path for path in parsed_files)
            ):
                return {
                    "success": False,
                    "error": "Supplied diff has no parseable file entries; send a unified diff.",
                    "terminal": True,
                    "retryable": False,
                    "invalid_diff": True,
                    "changed_files": [],
                    "review_scope_complete": False,
                }
        instructions = str(args.get("instructions", "Review this git diff for actionable defects, regressions, security/concurrency issues and missing tests. Cite changed files/hunks."))
        det_hint = ""
        if det_diff:
            det_hint = "\nDETERMINISTIC DIFF METADATA (facts only, verify semantics in the diff):\n" + json_dumps(det_diff, ensure_ascii=False, separators=(",", ":"))[:1800] + "\n"
            if det_diff.get("breaking_changes"):
                det_hint += "\nPOTENTIAL BREAKING CHANGES DETECTED:\n"
                for bc in det_diff["breaking_changes"][:10]:
                    det_hint += f"- [{bc.get('type')}] {bc.get('symbol')} in {bc.get('file')}: {bc.get('description')}\n"

        regressions: list[dict[str, Any]] = []
        from .process_utils import is_rooted_path
        regression_root = args.get("root")
        if diff.get("changed_files") and isinstance(regression_root, str) and is_rooted_path(regression_root):
            try:
                from .repo_project_incidents import find_project_incidents

                found = find_project_incidents(
                    regression_root, affected_paths=diff["changed_files"], limit=10,
                )
                regressions = [
                    {
                        "incident_id": item.get("id"),
                        "error_class": item.get("payload", {}).get("error_class"),
                        "affected_paths": item.get("payload", {}).get("affected_paths", []),
                        "verified_fix": item.get("payload", {}).get("verified_fix"),
                    }
                    for item in found
                    if item.get("payload", {}).get("resolved") is True
                    and item.get("payload", {}).get("verified_fix")
                ]
            except Exception:
                regressions = []
        if regressions:
            det_hint += "\nAUTO-REGRESSION WATCHDOG (verified fixes from prior incidents affecting changed files):\n"
            for reg in regressions[:5]:
                aff = ", ".join(reg.get("affected_paths", []))
                det_hint += f"- [PRIOR VERIFIED FIX] {reg.get('error_class')} in {aff}: {reg.get('verified_fix')}\n"

        if args.get("mode") == "ast" or str(args.get("instructions", "")).strip().lower() == "ast":
            if cancelled():
                return cancelled_result()
            count_fields = ("additions", "deletions", "hunks")
            if not all(type(det_diff.get(field)) is int and det_diff[field] >= 0 for field in count_fields):
                return {"success": False, "mode": "ast", "changed_files": diff.get("changed_files", []),
                        "error": "Deterministic diff metadata unavailable", "diff_facts": det_diff}
            return {
                "success": True,
                "mode": "ast",
                "changed_files": diff.get("changed_files", []),
                "diff_facts": det_diff,
                "breaking_changes": det_diff.get("breaking_changes", []),
                "regressions": regressions,
                "untracked_files_excluded": excluded,
                "untracked_inventory_complete": inventory_complete,
                "review_scope_complete": scope_complete,
                **({"review_source_sha256": diff["review_source_sha256"]} if "review_source_sha256" in diff else {}),
                "summary": f"AST Diff Summary: {len(diff.get('changed_files', []))} files, {det_diff['additions']} additions, {det_diff['deletions']} deletions across {det_diff['hunks']} hunks. {len(det_diff.get('breaking_changes', []))} potential breaking changes.",
            }

        # Keep non-diff prompt material bounded too; metadata descriptions and custom
        # instructions can otherwise undo the per-segment input limit.
        instructions = fit_text(instructions, 600).text
        det_hint = fit_text(det_hint, 700).text if det_hint else ""

        diff_text = str(diff["diff"])
        laya_evidence_ids = args.get("evidence_ids")
        if isinstance(laya_evidence_ids, (list, tuple)):
            laya_evidence_ids = list(dict.fromkeys(
                item.strip() for item in laya_evidence_ids
                if isinstance(item, str) and item.strip()
            ))[:64]
        else:
            laya_evidence_ids = []
        review_root = args.get("root")
        if not laya_evidence_ids and isinstance(review_root, str) and review_root.strip():
            pack_context = getattr(self, "_hybrid_context", None)
            if callable(pack_context):
                try:
                    packed_context = pack_context(
                        review_root,
                        instructions[:2048],
                        workspace=args.get("workspace"),
                        max_tokens=512,
                        changed_paths=tuple(
                            path for path in diff.get("changed_files", [])
                            if isinstance(path, str)
                        )[:64],
                    )
                    evidence = packed_context.get("evidence", []) if isinstance(packed_context, dict) else []
                    laya_evidence_ids = list(dict.fromkeys(
                        row.get("evidence_id") for row in evidence
                        if isinstance(row, dict)
                        and isinstance(row.get("evidence_id"), str)
                        and row.get("evidence_id")
                    ))[:64] if isinstance(evidence, list) else []
                except Exception:
                    laya_evidence_ids = []
        complexity_hint = review_diff_complexity(args, det_diff, diff)
        full_route = self.router.classify(
            instructions + det_hint, diff_text, "review", complexity_hint
        )
        full_route = self._resident_optimize(full_route, "review", complexity_hint)
        review_model = str(full_route.get("model", ""))
        selected_tier = self.model_policy.tier_for(review_model)
        complexity = (
            "heavy" if selected_tier == "smart"
            else "fast" if selected_tier in {"fast", "background"}
            else str(full_route.get("complexity", "fast"))
        )
        max_output_tokens = max(64, int(args.get("max_tokens", 1800)))
        vram_free_mb = None
        try:
            if getattr(self, "vram_balancer", None):
                vram_status = self.vram_balancer.status(force=True)
                if vram_status.get("available", "vram_available_mb" in vram_status):
                    vram_free_mb = vram_status.get("vram_available_mb")
        except Exception:
            vram_free_mb = None
        profile = self.model_policy.profile(
            review_model,
            role="review",
            input_tokens=estimate_tokens(instructions + det_hint + diff_text),
            output_tokens=max_output_tokens,
            vram_free_mb=vram_free_mb,
        )
        configured_input_budget = max(
            _REVIEW_DIFF_MIN_CHUNK_TOKENS,
            int(self.config.get("token_saving", {}).get("max_local_input_tokens", 56000)),
        )
        effective_prompt_budget_tokens = min(configured_input_budget, profile.prompt_budget_tokens)
        task_budget = max(128, int(effective_prompt_budget_tokens * 0.15))
        review_task = fit_text(
            instructions + "\nReturn one SUMMARY: line followed by a fenced JSON object with verdict and findings. "
            "Each finding must cite path, post-image line, and exact full source line as citation.quote."
            + det_hint, task_budget,
        ).text
        prompt_overhead = estimate_tokens(f"TASK:\n{review_task}\n\nCONTEXT:\n") + 64
        synthesis_task = fit_text(
            "SYNTHESIZE REVIEW FINDINGS ONLY. Merge duplicate findings and keep distinct actionable findings. "
            "Preserve file paths, hunk/line references, severity and uncertainty. Do not re-review the source, "
            "invent new findings, or discard a finding unless supplied findings show it is a duplicate or false positive. "
            f"Return a concise final review.\n\nReview goal: {review_task}",
            task_budget,
        ).text
        synthesis_prompt_overhead = estimate_tokens(f"TASK:\n{synthesis_task}\n\nCONTEXT:\n") + 64
        synthesis_context_budget = max(
            0,
            min(
                _REVIEW_SYNTHESIS_CONTEXT_TOKENS,
                int(effective_prompt_budget_tokens * _REVIEW_DIFF_CONTEXT_FRACTION),
                effective_prompt_budget_tokens - synthesis_prompt_overhead,
            ),
        )
        review_chunk_token_budget = min(
            int(effective_prompt_budget_tokens * _REVIEW_DIFF_CONTEXT_FRACTION),
            effective_prompt_budget_tokens - prompt_overhead,
        )
        if review_chunk_token_budget < _REVIEW_DIFF_MIN_CHUNK_TOKENS:
            return {
                "success": False,
                "error": "The selected model's prompt budget is too small for a safe diff review.",
                "error_code": "review_prompt_budget_too_small",
                "status_code": 422,
                "terminal": True,
                "retryable": False,
                "changed_files": diff.get("changed_files", []),
                "effective_prompt_budget_tokens": effective_prompt_budget_tokens,
            }

        review_chunks = _split_review_diff(diff_text, max_tokens=review_chunk_token_budget)
        largest_review_chunk_tokens = max(estimate_tokens(chunk) for chunk in review_chunks)
        if largest_review_chunk_tokens > review_chunk_token_budget:
            return {
                "success": False,
                "error_code": "review_diff_fragment_exceeds_budget",
                "status_code": 422,
                "error": (
                    f"A diff fragment exceeds the {review_chunk_token_budget}-token review budget and cannot be split safely. "
                    "Narrow the diff or exclude generated/minified files."
                ),
                "terminal": True,
                "retryable": False,
                "changed_files": diff.get("changed_files", []),
                "diff_truncated": bool(diff.get("truncated", False)),
                "largest_review_chunk_tokens": largest_review_chunk_tokens,
                "review_chunk_token_budget": review_chunk_token_budget,
            }
        max_review_chunks = _MAX_REVIEW_DIFF_CHUNKS
        if bool(args.get("_async_job")):
            max_review_chunks = max(
                _MAX_REVIEW_DIFF_CHUNKS,
                int(self.config.get("review", {}).get("max_async_chunks", 32)),
            )
        if len(review_chunks) > max_review_chunks:
            scope_guidance = (
                "The supplied diff is not truncated by diff_tokens; narrow it before review or call with root/base/path and omit diff."
                if provided_diff
                else "Narrow to a path or reduce diff_tokens."
            )
            return {
                "success": False,
                "error_code": "review_diff_segment_limit_exceeded",
                "status_code": 422,
                "error": (
                    f"Review requires {len(review_chunks)} segments; the safe limit is "
                    f"{max_review_chunks}. {scope_guidance}"
                ),
                "terminal": True,
                "retryable": False,
                "changed_files": diff.get("changed_files", []),
                "diff_truncated": bool(diff.get("truncated", False)),
                "review_chunks": len(review_chunks),
            }
        chunked = len(review_chunks) > 1
        if chunked:
            header_tokens = sum(
                estimate_tokens(f"### Counter-review segment {index}/{len(review_chunks)}\n") + 2
                for index in range(1, len(review_chunks) + 1)
            )
            per_chunk_output_tokens = min(
                max_output_tokens,
                max(256, (synthesis_context_budget - header_tokens - 64) // len(review_chunks)),
            )
        else:
            per_chunk_output_tokens = max_output_tokens
        review_payloads: list[dict[str, Any]] = []
        primary_results: list[dict[str, Any]] = []
        format_recovery_used = False
        format_recoveries: list[dict[str, Any]] = []
        index = 0
        while index < len(review_chunks):
            if cancelled():
                return cancelled_result()
            review_code = review_chunks[index]
            segment_count = len(review_chunks)
            chunked = segment_count > 1
            if chunked:
                header_tokens = sum(
                    estimate_tokens(f"### Counter-review segment {segment}\n") + 2
                    for segment in range(1, segment_count + 1)
                )
                per_chunk_output_tokens = min(
                    max_output_tokens,
                    max(256, (synthesis_context_budget - header_tokens - 64) // segment_count),
                )
            else:
                per_chunk_output_tokens = max_output_tokens
            task = review_task
            if chunked:
                task += (
                    f"\n\nThis is review segment {index + 1}/{segment_count} of one diff. "
                    "Review only the changed code shown in this segment; other segments are reviewed separately. "
                    "Ground each finding in the displayed file and hunk."
                )
            review_payload = {
                "task_type": "review",
                "operation": "review_diff",
                "task": task,
                "context": review_code,
                **({"root": review_root} if isinstance(review_root, str) and review_root.strip() else {}),
                **({"evidence_ids": laya_evidence_ids} if laya_evidence_ids else {}),
                "changed_paths": diff.get("changed_files", []),
                "static_facts": det_hint,
                "complexity": complexity,
                "max_tokens": per_chunk_output_tokens,
                "priority": int(args.get("priority", 5)),
            }
            review_payloads.append(review_payload)
            response = delegate_review(review_payload)
            if cancelled():
                return cancelled_result()
            if not isinstance(response, dict) or response.get("success") is False:
                if isinstance(response, dict) and response.get("output_truncated") is True:
                    split_budget = max(_REVIEW_DIFF_MIN_CHUNK_TOKENS, estimate_tokens(review_code) // 2)
                    smaller_chunks = _split_review_diff(review_code, split_budget)
                    if (
                        len(smaller_chunks) > 1
                        and all(len(chunk) < len(review_code) for chunk in smaller_chunks)
                        and len(review_chunks) + len(smaller_chunks) - 1 <= max_review_chunks
                    ):
                        review_chunks[index:index + 1] = smaller_chunks
                        review_payloads.pop()
                        chunked = True
                        continue
                if len(review_chunks) == 1 and isinstance(response, dict):
                    return response
                failure = {
                    "success": False,
                    "error": f"Review segment {index + 1}/{segment_count} failed.",
                    "failed_segment": index + 1,
                    "partial_reviews": [str(item.get("text", "")) for item in primary_results],
                }
                failure.update(_review_failure_details(response))
                return failure
            output_error = _review_text_error(response.get("text"))
            if output_error:
                if format_recovery_used:
                    return {
                        "success": False,
                        "error": f"Review segment {index + 1}/{segment_count} returned unusable output after the single format-recovery attempt: {output_error}",
                        "failed_segment": index + 1,
                        "model": response.get("model"),
                        "attempted_models": [str(response.get("model") or "")],
                        "invalid_model_output": True,
                        "partial_reviews": [str(item.get("text", "")) for item in primary_results],
                    }
                format_recovery_used = True
                primary_model = str(response.get("model") or "").strip()
                models = self.config.get("models", {})
                role_ranks = {"fast_code": 0, "general": 0, "heavy_code": 1, "reasoning": 2}
                model_ranks: dict[str, tuple[int, str]] = {}
                if isinstance(models, dict):
                    for role, rank in role_ranks.items():
                        candidate = str(models.get(role) or "").strip()
                        identity = _review_model_identity(candidate)
                        if identity:
                            previous = model_ranks.get(identity)
                            if previous is None or rank > previous[0]:
                                model_ranks[identity] = (rank, candidate)
                primary_identity = _review_model_identity(primary_model)
                primary_rank = model_ranks.get(primary_identity, (0, primary_model))[0]
                retry_candidates = [
                    (rank, index, candidate)
                    for index, (role, rank) in enumerate(role_ranks.items())
                    if (candidate := str(models.get(role) or "").strip())
                    and _review_model_identity(candidate) != primary_identity
                    and model_ranks.get(_review_model_identity(candidate), (rank, candidate))[0] >= primary_rank
                ] if isinstance(models, dict) else []
                retry_model = min(retry_candidates)[2] if retry_candidates else primary_model
                retry_payload = dict(review_payload)
                if retry_model:
                    retry_payload["model"] = retry_model
                retry_payload["task"] = (
                    f"{review_payload.get('task', review_task)}\n\nFORMAT RECOVERY: The previous response was unusable ({output_error}). "
                    "Review this diff again. Return plain text whose first line begins `SUMMARY:` followed by at least two words. "
                    "Then list only actionable defects, or write `- None.` when there are none. Do not emit fragments or markdown fences."
                )
                try:
                    retry_response = delegate_review(retry_payload)
                except Exception as exc:
                    if cancelled():
                        return cancelled_result()
                    return {
                        "success": False,
                        "error": f"Review segment {index + 1}/{segment_count} format recovery failed: {exc}",
                        "failed_segment": index + 1,
                        "model": retry_model or primary_model or None,
                        "attempted_models": [model for model in (primary_model, retry_model) if model],
                        "invalid_model_output": True,
                        "partial_reviews": [str(item.get("text", "")) for item in primary_results],
                    }
                if cancelled():
                    return cancelled_result()
                retry_error = (
                    _review_text_error(retry_response.get("text"))
                    if isinstance(retry_response, dict) and retry_response.get("success") is not False
                    else "fallback model did not return a successful review"
                )
                if retry_error:
                    retry_model_returned = (
                        str(retry_response.get("model") or retry_model or "").strip()
                        if isinstance(retry_response, dict)
                        else retry_model
                    )
                    return {
                        "success": False,
                        "error": f"Review segment {index + 1}/{segment_count} remained unusable after format recovery: {retry_error}",
                        "failed_segment": index + 1,
                        "model": retry_model_returned or primary_model or None,
                        "attempted_models": [model for model in (primary_model, retry_model_returned) if model],
                        "invalid_model_output": True,
                        "partial_reviews": [str(item.get("text", "")) for item in primary_results],
                    }
                response = retry_response
                format_recoveries.append({
                    "segment": index + 1,
                    "from_model": primary_model or None,
                    "to_model": str(response.get("model") or retry_model or "").strip() or None,
                })
            primary_results.append(response)
            index += 1

        result = dict(primary_results[0])
        if format_recoveries:
            result["degraded"] = True
            result["format_recoveries"] = format_recoveries

        merge_options = {
            "chunked": chunked,
            "synthesis_context_budget": synthesis_context_budget,
            "synthesis_task": synthesis_task,
            "max_output_tokens": max_output_tokens,
            "complexity": complexity,
            "delegate": delegate_review,
            "priority": int(args.get("priority", 5)),
        }
        result["text"], result["review_synthesis"] = _merge_review_segment_results(
            primary_results, label="Review segment", task_type="review", **merge_options
        )
        if cancelled():
            return cancelled_result()
        if result["review_synthesis"].get("model"):
            result["model"] = result["review_synthesis"]["model"]

        # Multi-model consensus review for high-risk breaking changes or when explicitly requested
        consensus_requested = bool(args.get("consensus", False))
        auto_consensus = args.get("consensus") is None and bool(det_diff.get("breaking_changes"))

        if consensus_requested or auto_consensus:
            try:
                secondary_results = []
                for review_payload in review_payloads:
                    if cancelled():
                        return cancelled_result()
                    sec_payload = dict(review_payload)
                    sec_payload["task_type"] = "reasoning"
                    sec_payload["task"] = (
                        "CRITICAL COUNTER-REVIEW / CONSENSUS AUDIT:\n"
                        "Analyze the shown diff segment independently and verify potential defects or breaking changes. "
                        "Confirm genuine issues and flag false positives.\n\n"
                        + str(review_payload["task"])
                    )
                    sec_result = delegate_review(sec_payload)
                    if cancelled():
                        return cancelled_result()
                    if not isinstance(sec_result, dict) or sec_result.get("success") is False:
                        raise ValueError(f"Counter-review segment {len(secondary_results) + 1} failed.")
                    output_error = _review_text_error(sec_result.get("text"))
                    if output_error:
                        raise ValueError(
                            f"Counter-review segment {len(secondary_results) + 1} returned unusable output: {output_error}"
                        )
                    secondary_results.append(sec_result)
                if secondary_results:
                    secondary_text, secondary_synthesis = _merge_review_segment_results(
                        secondary_results,
                        label="Counter-review segment",
                        task_type="reasoning",
                        **merge_options,
                    )
                    result["consensus"] = {
                        "enabled": True,
                        "triggered_by": "explicit" if consensus_requested else "breaking_changes",
                        "primary_model": result.get("model", "primary"),
                        "secondary_model": secondary_results[0].get("model", "secondary"),
                        "secondary_review": secondary_text,
                        "synthesis": secondary_synthesis,
                    }
                    result["text"] = str(result.get("text", "")) + "\n\n### Consensus / Counter-Review Findings:\n" + secondary_text
            except Exception as exc:
                result["consensus"] = {"enabled": True, "degraded": True, "error": str(exc)}

        if cancelled():
            return cancelled_result()
        if regressions:
            result["regressions"] = regressions
        result["diff"] = {
            "changed_files": diff.get("changed_files", []),
            "truncated": bool(diff.get("truncated", False)),
            "local_diff_tokens": int(diff.get("estimated_tokens", 0)),
            "original_diff_tokens": int(diff.get("original_estimated_tokens", 0)),
            "deterministic": det_diff,
            "review_chunks": len(review_chunks),
            "effective_prompt_budget_tokens": effective_prompt_budget_tokens,
            "review_chunk_token_budget": review_chunk_token_budget,
            "review_chunk_context_fraction": _REVIEW_DIFF_CONTEXT_FRACTION,
            "review_segment_output_budget_tokens": per_chunk_output_tokens,
            "review_synthesis_context_budget_tokens": synthesis_context_budget,
            "review_model": review_model,
            "largest_review_chunk_tokens": largest_review_chunk_tokens,
        }
        result["untracked_files_excluded"] = excluded
        result["untracked_inventory_complete"] = inventory_complete
        result["review_scope_complete"] = scope_complete
        if "review_source_sha256" in diff:
            result["review_source_sha256"] = diff["review_source_sha256"]
        from .semantic_quality import assess_review_consistency, constrain_semantic_quality
        quality = assess_review_consistency(result, diff.get("changed_files", ()), source_diff=diff_text)
        result["advisory_only"] = True
        result["review_consistency"] = quality
        result["semantic_quality"] = constrain_semantic_quality(quality, result)
        if not quality["usable"]:
            warning = f"advisory review requires verification: {quality['reason']}"
            result["quality_warning"] = "; ".join(filter(None, (result.get("quality_warning"), warning)))
            result.setdefault("bypass_reason", quality["reason"])
        return result

    def compress(self, args: dict[str, Any], *, cancel_event: threading.Event | None = None) -> dict[str, Any]:
        from .service_code_assist import compress
        return compress(self, args, cancel_event=cancel_event)

    def complete_code(self, args: dict[str, Any], *, cancel_event: threading.Event | None = None) -> dict[str, Any]:
        from .service_code_assist import complete_code
        return complete_code(self, args, cancel_event=cancel_event)

    def _record_symbol_focus(self, symbols: list[str], *, root: str, session_id: str) -> None:
        if not symbols:
            return
        with self._focus_lock:
            scope = (root, session_id)
            current = self._recent_focus_symbols.setdefault(scope, [])
            for s in symbols:
                if s and len(s) >= 3 and s not in current:
                    current.insert(0, s)
            self._recent_focus_symbols[scope] = current[:16]
            if len(self._recent_focus_symbols) > 256:
                for k in list(self._recent_focus_symbols.keys())[:-128]:
                    self._recent_focus_symbols.pop(k, None)

    def expand_query(self, query: str, *, root: str = "", session_id: str = "") -> list[str]:
        """Expand terms within the actual repository/session or owner-global scope."""
        from .repository_scope import authorized_repository_root

        if not isinstance(query, str):
            raise ValueError("query must be a string")
        if not isinstance(root, str) or root != root.strip() or "\x00" in root:
            raise ValueError("root must be a canonical string")
        if not isinstance(session_id, str) or session_id != session_id.strip() or "\x00" in session_id:
            raise ValueError("session_id must be a canonical string")
        scoped_root = authorized_repository_root(self.config, root) if root else ""
        with self._focus_lock:
            recent = list(self._recent_focus_symbols.get((scoped_root, session_id), []))
        cache_key = stable_hash({"root": scoped_root, "session_id": session_id,
                                 "query": query.strip().lower(), "focus": recent})
        if hasattr(self, "_query_expansion_l1"):
            cached = self._query_expansion_l1.get(cache_key)
            if cached is not None:
                return list(cached)
        terms = re.findall(r"[A-Za-z0-9_]{3,}", query.lower())
        synonyms: list[str] = list(terms)
        for t in terms:
            if t in self.DOMAIN_SYNONYMS:
                synonyms.extend(self.DOMAIN_SYNONYMS[t])

        # Multi-turn context bonus: if query is brief/contextual, add recently investigated AST symbols
        if recent and len(terms) <= 4:
            synonyms.extend(recent[:4])

        # Record newly identified proper-case or identifier symbols as focus
        explicit_symbols = [w for w in re.findall(r"\b[A-Z][A-Za-z0-9_]{3,}\b", query)]
        if explicit_symbols:
            self._record_symbol_focus(explicit_symbols, root=scoped_root, session_id=session_id)

        result = list(dict.fromkeys(synonyms))
        if hasattr(self, "_query_expansion_l1"):
            self._query_expansion_l1.set(cache_key, result)
        return result

    def generate_tests(self, payload: dict[str, Any], *, cancel_event: threading.Event | None = None) -> dict[str, Any]:
        from .service_code_assist import generate_tests
        return generate_tests(self, payload, cancel_event=cancel_event)

    def validate_patch(self, payload: dict[str, Any]) -> dict[str, Any]:
        from .service_code_assist import validate_patch
        return validate_patch(self, payload)

    def preprocess(self, args: dict[str, Any]) -> dict[str, Any]:
        action = str(args.get("action", "status")).strip().lower().replace("-", "_")
        root = str(args.get("root", "."))
        if action in {"start", "register", "preprocess", "refresh", "force_refresh", "resume"}:
            from .operational_mode import load_operational_mode, operational_mode_gate_error

            state_dir = self.config.get("server", {}).get("state_dir")
            if state_dir:
                mode = load_operational_mode(state_dir)
                rejection = operational_mode_gate_error(mode, "preprocess")
                if rejection is not None:
                    return rejection
        if self.preprocessor is None:
            return {"success": False, "error": "project preprocessor unavailable", "terminal": True, "retryable": False}
        if action in {"start", "register", "preprocess"}:
            return self.preprocessor.register(
                root, source="agent",
                is_worktree=bool(args.get("is_worktree", False)),
                parent_root=args.get("parent_root") or None,
            )
        if action in {"refresh", "force_refresh"}:
            return self.preprocessor.refresh(root)
        if action == "pause":
            return self.preprocessor.pause(root if args.get("root") else None)
        if action == "resume":
            return self.preprocessor.resume(root if args.get("root") else None)
        if action in {"cancel", "stop"}:
            return self.preprocessor.cancel(root)
        if action in {"unregister", "remove", "delete"}:
            return self.preprocessor.unregister(root, purge_data=bool(args.get("purge_data", False)))
        if action in {"prune", "cleanup_deleted", "cleanup"}:
            return self.preprocessor.cleanup_deleted_projects()
        if action in {"cleanup_orphans", "cleanup_orphaned_indexes"}:
            return self.preprocessor.cleanup_orphaned_indexes()
        if action in {"status", "get"}:
            return self.preprocessor.status(root if args.get("root") else None)
        if action in {"lookup", "context"}:
            return self.preprocessor.lookup(root, str(args.get("query", "")), int(args.get("limit", 5)))
        return {"success": False, "error": f"unknown preprocess action: {action}", "terminal": True, "retryable": False}

