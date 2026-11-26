# Service hybrid & adaptive context module extracted from services.py
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, wait
import fnmatch
import itertools
import logging
import math
import re
import threading
import time
from pathlib import Path
from typing import Any

from .agent_consistency import AdaptiveContextPack, ConsistencyRequest
from .agent_context import ContextRequest
from .budget import chars_for_tokens, estimate_tokens
from .cache import stable_hash
from .evidence_merge import merge_overlapping_evidence
from .external_candidate_paths import collect_external_candidate_paths
from .process_utils import canonical_root
from .retrieval import (
    fuse_ranked_paths,
    is_source_context_query,
    prioritize_source_context_paths,
    source_context_path_tier,
)
from .state_paths import configured_state_dir

logger = logging.getLogger("local_ai_hub.services")

def _get_wait() -> Any:
    services_mod = sys.modules.get("local_ai_hub.services")
    if services_mod is not None and hasattr(services_mod, "wait"):
        return getattr(services_mod, "wait")
    return wait

# Keep optional context workers bounded across concurrent requests. Each backend
# gets its own single-worker lane for Serena
# or RAG, and timed-out work cannot cause a new thread per incoming request.
_CONTEXT_BACKEND_POOLS = {
    name: ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"context-{name}")
    for name in ("serena", "rag", "preprocessor")
}
_PREPROCESSOR_CONTEXT_ADMISSION = threading.BoundedSemaphore(1)


def _safe_int(val: Any, default: int, min_val: int | None = None, max_val: int | None = None) -> int:
    if isinstance(val, bool) or val is None:
        return default
    try:
        if isinstance(val, float) and not math.isfinite(val):
            return default
        res = int(val)
    except (ValueError, TypeError, OverflowError):
        return default
    if min_val is not None and res < min_val:
        return min_val
    if max_val is not None and res > max_val:
        return max_val
    return res


def _safe_float(val: Any, default: float, min_val: float | None = None, max_val: float | None = None) -> float:
    if isinstance(val, bool) or val is None:
        return default
    try:
        res = float(val)
        if not math.isfinite(res):
            return default
    except (ValueError, TypeError, OverflowError):
        return default
    if min_val is not None and res < min_val:
        return min_val
    if max_val is not None and res > max_val:
        return max_val
    return res

def adaptive_context_pack(self, request: ConsistencyRequest, *, mode: str = "adaptive", since_hash: str = "") -> dict[str, Any]:
    """Build deterministic context plus bounded, soft consistency findings."""
    if not isinstance(request, ConsistencyRequest):
        raise TypeError("guarded context request must be ConsistencyRequest")
    if not isinstance(mode, str) or mode not in {"adaptive", "fast", "full"}:
        return {
            "success": False, "terminal": True, "retryable": False,
            "error": "context mode must be adaptive, full or fast",
        }
    try:
        memory_revision = self._adaptive_memory_revision(request)
    except Exception as exc:
        return {
            "success": False, "terminal": True, "retryable": False,
            "stop_code": "context_memory_revision_unavailable",
            "error": f"context memory revision unavailable: {type(exc).__name__}",
            "context": "", "evidence": [],
        }
    project_config_digest = ""
    coordination_id = ""
    retrieval_weights: dict[str, float] = {}
    request_path_hints = tuple(getattr(request, "path_hints", ()))
    request_directory_hints = tuple(getattr(request, "directory_hints", ()))
    request_exclude_paths = tuple(getattr(request, "exclude_paths", ()))
    request_force_include_paths = tuple(getattr(request, "force_include_paths", ()))
    effective_path_hints = request_path_hints
    if mode in {"full", "adaptive"}:
        from .project_config import ProjectConfigError, resolve_project_context

        try:
            project_context = resolve_project_context(
                request.root,
                configured_state_dir(getattr(self, "config", {}), create=False),
            )
            project_config_digest = str(project_context.config_digest or "")[:200]
            resolved_identity = project_context.coordination_id
            if isinstance(resolved_identity, str) and resolved_identity and resolved_identity == resolved_identity.strip() and "\x00" not in resolved_identity:
                coordination_id = resolved_identity
            retrieval_weights = dict(project_context.settings.retrieval_weights)
            from .context_identity import normalize_context_path_hints
            from .task_context import _project_context_hint_groups

            pinned_hints, entry_hints, saved_hints = _project_context_hint_groups(
                project_context,
                project_root=Path(request.root).expanduser().resolve(strict=False),
                repository_revision="",
                config_digest=project_config_digest,
            )
            effective_path_hints = normalize_context_path_hints(
                (*pinned_hints, *entry_hints, *request_path_hints, *saved_hints)
            )
        except ProjectConfigError as exc:
            return {
                "success": False, "terminal": True, "retryable": False,
                "stop_code": "context_project_config_invalid",
                "error": f"context project configuration invalid: {type(exc).__name__}",
                "context": "", "evidence": [],
            }
        except (RuntimeError, ValueError) as exc:
            return {
                "success": False, "terminal": True, "retryable": False,
                "stop_code": "context_project_hints_invalid",
                "error": f"context project hints invalid: {type(exc).__name__}",
                "context": "", "evidence": [],
            }
    retrieval_config = {
        "search": getattr(self, "config", {}).get("search", {}),
        "features": getattr(self, "config", {}).get("features", {}),
        "preprocessing": getattr(self, "config", {}).get("preprocessing", {}),
        "rag": getattr(self, "config", {}).get("rag", {}),
        "retrieval": getattr(self, "config", {}).get("retrieval", {}),
        "external_tools": getattr(self, "config", {}).get("external_tools", {}),
        "code_intelligence": getattr(self, "config", {}).get("code_intelligence", {}),
        "project_config_digest": project_config_digest,
        "retrieval_weights": retrieval_weights,
    }
    retrieval_config_revision = stable_hash(retrieval_config)
    from .repo_knowledge import attach_knowledge_context, reserve_knowledge_context

    knowledge: dict[str, Any] = {"status": "skipped", "text": ""}
    technical_budget = request.token_budget
    if mode == "adaptive":
        knowledge, technical_budget = reserve_knowledge_context(
            getattr(self, "config", {}), request.root, request.query, token_budget=request.token_budget,
            changed_paths=tuple(request.changed_paths),
        )
    knowledge_text = str(knowledge.get("text", ""))
    context_cache_identity = {
        "mode": mode,
        "task_id": request.task_id,
        "session_id": request.session_id,
        "workspace": request.workspace,
        "phase": request.phase,
        "query": request.query,
        "focus": request.focus,
        "changed_paths": request.changed_paths,
        "path_hints": effective_path_hints,
        "directory_hints": request_directory_hints,
        "exclude_paths": request_exclude_paths,
        "force_include_paths": request_force_include_paths,
        "preload_profile": request.preload_profile,
        "token_budget": request.token_budget,
        "base": request.base,
        "staged": request.staged,
        "memory_revision": memory_revision,
        "retrieval_config_revision": retrieval_config_revision,
        "project_config_digest": project_config_digest,
        "retrieval_weights": retrieval_weights,
        "knowledge_context_digest": stable_hash(knowledge_text) if knowledge_text else "",
        "since_hash": since_hash,
        "approval": request.approval,
        "override_reason": request.override_reason,
    }
    if mode in {"full", "adaptive"}:
        base = self._hybrid_context(
            request.root,
            request.query,
            workspace=request.workspace or None,
            max_tokens=technical_budget,
            quality_first=mode == "adaptive",
            context_identity=context_cache_identity,
            path_hints=effective_path_hints if mode == "adaptive" else (),
            directory_hints=request_directory_hints if mode == "adaptive" else (),
            exclude_paths=request_exclude_paths if mode == "adaptive" else (),
            force_include_paths=request_force_include_paths if mode == "adaptive" else (),
            focus=request.focus,
            changed_paths=request.changed_paths,
            retrieval_weights=retrieval_weights if mode == "adaptive" else None,
        )
    else:
        base = self.fast_context(ContextRequest(
            task_id=request.task_id, root=request.root, token_budget=request.token_budget, phase="fast",
        ))
    if not isinstance(base, dict):
        base = {"success": False, "context": "", "evidence": []}
    else:
        base = dict(base)
    laya_retrieval_choice = None
    laya_retrieval_fallback = None
    laya_cfg = getattr(self, "config", {}).get("laya", {})
    if mode == "adaptive" and isinstance(laya_cfg, dict) and laya_cfg.get("enabled") is True:
        raw_rows = base.get("evidence")
        evidence_ids = list(dict.fromkeys(
            row.get("evidence_id") for row in raw_rows
            if isinstance(row, dict)
            and isinstance(row.get("evidence_id"), str)
            and row.get("evidence_id")
        ))[:64] if isinstance(raw_rows, list) else []
        evidence_store = getattr(self, "evidence_store", None)
        get_many = getattr(evidence_store, "get_many", None)
        evaluate_laya = getattr(self, "evaluate_laya_advisory", None)
        if evidence_ids and callable(get_many) and callable(evaluate_laya):
            try:
                root_value = canonical_root(request.root)
                rows = get_many(evidence_ids, verify=True, root=root_value)
                verified = (
                    type(rows) is list and len(rows) == len(evidence_ids)
                    and all(
                        type(row) is dict
                        and row.get("success") is True
                        and row.get("evidence_id") == evidence_id
                        and row.get("root") == root_value
                        and row.get("stale") is False
                        for row, evidence_id in zip(rows, evidence_ids, strict=True)
                    )
                )
                features = getattr(self, "config", {}).get("features", {})
                rag_available = (
                    getattr(self, "rag", None) is not None
                    and (not isinstance(features, dict) or features.get("rag", True) is True)
                )
                code_available = getattr(self, "code_index", None) is not None
                options = ["lexical_bm25", "hybrid"]
                if code_available:
                    options.insert(0, "ast_graph")
                if rag_available:
                    options.insert(-1, "dense_rag")
                if verified and len(options) >= 2:
                    operation = {
                        "action": "evaluate_decision",
                        **({"task_id": request.task_id.strip()} if request.task_id.strip() else {}),
                        "decision": {
                            "category": "retrieval_strategy",
                            "evidence_ids": evidence_ids,
                            "options": options,
                            "state": {
                                "context_source": "hybrid",
                                "rag_available": "true" if rag_available else "false",
                                "code_index_available": "true" if code_available else "false",
                                "mode": mode,
                            },
                            "training_content": {
                                "task_input": request.query.encode("utf-8", errors="replace")[:4096].decode("utf-8", errors="ignore"),
                            },
                        },
                    }
                    suggestion = evaluate_laya(
                        operation,
                        root=root_value,
                        baseline={
                            "method": "adaptive_context_hybrid_default",
                            "suggestion": "hybrid",
                            "evidence_id": evidence_ids[0],
                        },
                    )
                    internal_strategy = {
                        "ast_graph": "ast_symbol",
                        "lexical_bm25": "lexical_bm25",
                        "dense_rag": "semantic_hnsw",
                        "hybrid": "hybrid",
                    }.get(suggestion)
                    if internal_strategy is not None and suggestion in options:
                        if suggestion == "hybrid":
                            laya_retrieval_choice = suggestion
                        else:
                            rerun = self._hybrid_context(
                                request.root,
                                request.query,
                                workspace=request.workspace or None,
                                max_tokens=request.token_budget,
                                quality_first=True,
                                context_identity={
                                    **context_cache_identity,
                                    "laya_retrieval_strategy": suggestion,
                                },
                                path_hints=effective_path_hints,
                                directory_hints=request_directory_hints,
                                exclude_paths=request_exclude_paths,
                                force_include_paths=request_force_include_paths,
                                focus=request.focus,
                                changed_paths=request.changed_paths,
                                retrieval_weights=retrieval_weights,
                                laya_retrieval_strategy=internal_strategy,
                            )
                            if isinstance(rerun, dict) and rerun.get("success") is True:
                                base = dict(rerun)
                                laya_retrieval_choice = suggestion
                            else:
                                laya_retrieval_fallback = "retrieval_rerun_unavailable"
            except Exception as exc:
                laya_retrieval_fallback = "advisory_unavailable"
                logger.debug("Laya adaptive context strategy fallback: %s", type(exc).__name__)
    raw_evidence = base.get("evidence")
    if isinstance(raw_evidence, list):
        normalized_evidence = []
        for item in raw_evidence:
            if not isinstance(item, dict):
                continue
            evidence_item = dict(item)
            if not evidence_item.get("evidence_id"):
                text_value = evidence_item.get("text", evidence_item.get("content", ""))
                evidence_item["evidence_id"] = "local-" + stable_hash({
                    "root": canonical_root(request.root),
                    "path": evidence_item.get("path", ""),
                    "symbol": evidence_item.get("symbol", ""),
                    "start_line": evidence_item.get("start_line", evidence_item.get("line", 0)),
                    "end_line": evidence_item.get("end_line", evidence_item.get("start_line", evidence_item.get("line", 0))),
                    "content_hash": evidence_item.get("content_hash") or stable_hash(str(text_value)),
                    "revision": evidence_item.get("repository_revision", evidence_item.get("revision", "")),
                })[:24]
            normalized_evidence.append(evidence_item)
        base["evidence"] = merge_overlapping_evidence(normalized_evidence, root=request.root)
    base, preload_warnings = self._apply_context_preloads(request, base, coordination_id=coordination_id)
    base = attach_knowledge_context(base, knowledge, token_budget=request.token_budget)
    guard = self.consistency_guard
    if guard is None:
        context_id = stable_hash({
            "root": canonical_root(request.root),
            "repository_revision": base.get("repo_revision", base.get("revision", "")),
            **context_cache_identity,
            "evidence_ids": tuple(str(item.get("evidence_id") or "") for item in base.get("evidence", ()) if isinstance(item, dict)),
            "retrieval_revision": (base.get("retrieval") or {}).get("rag_revision", "") if isinstance(base.get("retrieval"), dict) else "",
        })[:24]
        pack = AdaptiveContextPack(
            context_id=context_id, phase=request.phase, focus=request.focus,
            changed_paths=tuple(request.changed_paths), preload_profile=request.preload_profile,
            memory_revision=memory_revision, warnings=preload_warnings,
        ).to_dict()
        return {
            **base,
            **({"laya_retrieval_strategy": laya_retrieval_choice} if laya_retrieval_choice else {}),
            **({"laya_retrieval_fallback": laya_retrieval_fallback} if laya_retrieval_fallback else {}),
            "guarded": False,
            "context_id": context_id,
            "context_pack": pack,
        }

    revision = ""
    fresh_fingerprint = False
    try:
        # Use the bounded worktree fingerprint for guarded provenance.  The
        # GitSnapshot revision is HEAD-only, which makes dirty working-tree
        # receipts look stale even when the indexed evidence is current.
        state = self.repo_state.fingerprint(request.root, force=True)
        if isinstance(state, dict) and not state.get("degraded") and not state.get("stale"):
            revision = str(state.get("fingerprint", "") or "")[:200]
            fresh_fingerprint = bool(revision)
    except Exception:
        pass
    fingerprint_matches_since_hash = bool(
        since_hash and fresh_fingerprint and since_hash == revision
    )
    snapshot_paths = ()
    if not fingerprint_matches_since_hash:
        try:
            snapshot = self.repo_tools.git_snapshot(request.root)
            if not revision:
                revision = str(getattr(snapshot, "revision", "") or "")[:200]
            snapshot_paths = tuple(str(path) for path in (getattr(snapshot, "changed_paths", ()) or ()))[:64]
        except Exception:
            snapshot_paths = ()
    evidence = tuple(item for item in (base.get("evidence") or ()) if isinstance(item, dict))[:24]
    changed_paths = tuple(request.changed_paths or base.get("changed_paths") or snapshot_paths)[:64]
    if since_hash and since_hash == revision:
        changed_paths = ()
    contract = guard.build_contract(request)
    candidates = tuple(guard.find_reuse_candidates(request, contract))[:24]
    mappings, mapping_warnings = guard.build_contract_mappings(request, evidence)
    diff: Any = None
    try:
        diff = self.repo_tools.git_diff(request.root, base=request.base, staged=request.staged, max_tokens=request.token_budget)
        if since_hash and isinstance(diff, dict):
            diff = {**diff, "diff_sha256": since_hash}
    except Exception as exc:
        diff = {"success": False, "paths_complete": False, "error": type(exc).__name__}
    if diff is None:
        diff = {"success": False, "paths_complete": False, "error": "diff_unavailable"}
    analysis_status = guard.diff_analysis_status(diff)
    drift_warnings = guard.check_drift(
        request,
        contract,
        changed_paths,
        diff,
        reuse_candidates=candidates,
    )
    warnings = tuple(dict.fromkeys((*preload_warnings, *mapping_warnings, *drift_warnings)))[:24]
    boundary = any(item.requires_approval or item.severity.lower() in {"boundary", "high", "high-risk"} for item in warnings)
    stop_code = self._guard_stop_code(request, boundary)
    if stop_code:
        warning_payload = [
            warning.to_dict() if hasattr(warning, "to_dict") else dict(warning)
            for warning in warnings
        ]
        return {
            **base,
            "success": False,
            "guarded": True,
            "delivery_mode": mode,
            "terminal": True,
            "retryable": False,
            "stop_code": stop_code,
            "error": f"guarded context stopped: {stop_code}",
            "warnings": warning_payload[:24],
            "analysis_status": analysis_status,
            "repo_revision": revision,
            "changed_paths": list(changed_paths),
            "task_status": "",
            "waiting": False,
        }
    relevance = self._adaptive_relevance(request, evidence, revision, memory_revision)
    retrieval_report = dict(base.get("retrieval") or {})
    backend_states = dict(retrieval_report.get("backend_states") or {})
    model_state = (
        "used" if isinstance(relevance, dict) and relevance.get("success")
        else "skipped" if isinstance(relevance, dict) and relevance.get("degraded_reason") == "no_authoritative_evidence"
        else "degraded"
    )
    backend_states["local_model"] = model_state
    retrieval_report["backend_states"] = dict(sorted(backend_states.items()))
    retrieval_report["used_backends"] = sorted(name for name, state in backend_states.items() if state == "used")
    retrieval_report["skipped_backends"] = sorted(name for name, state in backend_states.items() if state == "skipped")
    retrieval_report["degraded_backends"] = sorted(name for name, state in backend_states.items() if state == "degraded")
    base["retrieval"] = retrieval_report
    metric = getattr(guard, "record_metric", None)
    if callable(metric):
        if since_hash and since_hash == revision:
            metric("duplicate_context_reuse")
        if not isinstance(relevance, dict) or not relevance.get("success"):
            metric("degraded_local_model_fallback")
        relevance_warnings = tuple(relevance.get("warnings", ())) if isinstance(relevance, dict) else ()
        for warning in relevance_warnings:
            severity = getattr(warning, "severity", None)
            if severity is None and isinstance(warning, dict):
                severity = warning.get("severity", "warning")
            metric("warning", severity=str(severity or "warning"))
    model_warnings = tuple(relevance.get("warnings", ()))[:24] if isinstance(relevance, dict) else ()
    pack = AdaptiveContextPack(
        contract=contract,
        reuse_candidates=candidates,
        mappings=tuple(mappings),
        warnings=warnings,
        evidence=evidence,
        repo_revision=revision,
        changed_paths=changed_paths,
        stale=False,
        context_id=stable_hash({
            "root": canonical_root(request.root),
            "repository_revision": revision,
            "changed_paths": changed_paths,
            **context_cache_identity,
            "evidence_ids": tuple(str(item.get("evidence_id") or "") for item in evidence if isinstance(item, dict)),
            "retrieval_revision": (base.get("retrieval") or {}).get("rag_revision", "") if isinstance(base.get("retrieval"), dict) else "",
        })[:24],
        phase=request.phase,
        focus=request.focus,
        preload_profile=request.preload_profile,
        memory_revision=memory_revision,
        model_warnings=model_warnings,
    )
    pack_data = pack.to_dict()
    unchanged = bool(since_hash and since_hash == revision and knowledge["status"] in {"uninitialized", "skipped"})
    ordinary = any(not (item.requires_approval or item.severity.lower() in {"boundary", "high", "high-risk"}) for item in warnings)
    decision_recorded, decision_persisted = self._guard_decision(request, revision, reason=request.override_reason, approval=request.approval)
    if (str(request.override_reason or "").strip() or self._guard_truthy(request.approval)) and not decision_persisted:
        return {
            **base, "success": False, "terminal": True, "retryable": False,
            "stop_code": "context_decision_persistence_failed",
            "error": "context decision could not be persisted", "context": "", "evidence": [],
        }
    try:
        task_status, waiting = self._guard_task_state(request, warnings, revision)
    except Exception as exc:
        return {
            "success": False, "terminal": True, "retryable": False,
            "stop_code": "context_task_state_unavailable",
            "error": f"context task state unavailable: {type(exc).__name__}",
            "context": "", "evidence": [],
        }
    approved = self._guard_truthy(request.approval) or self._guard_existing_approval(request)
    if str(task_status).lower() == "waiting":
        approved = False
    result = dict(base)
    result.update({
        "query": request.query,
        **({"laya_retrieval_strategy": laya_retrieval_choice} if laya_retrieval_choice else {}),
        **({"laya_retrieval_fallback": laya_retrieval_fallback} if laya_retrieval_fallback else {}),
        "guarded": True,
        "delivery_mode": mode,
        "adaptive_context_pack": pack_data,
        "context_pack": pack_data,
        "contract": pack_data["contract"],
        "reuse": pack_data["reuse_candidates"],
        "reuse_candidates": pack_data["reuse_candidates"],
        "mappings": pack_data["mappings"],
        "analysis_status": analysis_status,
        "warnings": [*pack_data["warnings"], *list(model_warnings)][:24],
        "evidence_ids": list(dict.fromkeys(item.get("evidence_id", "") for item in evidence if item.get("evidence_id")))[:24],
        "warning_ids": list(dict.fromkeys(
            evidence_id
            for item in (*warnings, *model_warnings)
            for evidence_id in (item.evidence_ids if hasattr(item, "evidence_ids") else item.get("evidence_ids", ()) if isinstance(item, dict) else ())
        ))[:24],
        "model_warnings": list(model_warnings),
        "relevance": {
            key: relevance.get(key)
            for key in ("selected_evidence_ids", "claims", "unknowns", "gaps", "wording")
            if isinstance(relevance, dict) and key in relevance
        },
        "model_degraded": bool(not isinstance(relevance, dict) or not relevance.get("success")),
        "model_degraded_reason": str(relevance.get("degraded_reason", ""))[:120] if isinstance(relevance, dict) else "relevance_error",
        "repo_revision": revision,
        "unchanged": unchanged,
        "reuse_pointer": pack.context_id if unchanged else "",
        "memory_revision": memory_revision,
        "changed_paths": list(changed_paths),
        "since_hash": str(since_hash)[:200],
        "delta_from": str(since_hash)[:200] if since_hash else "",
        "requires_override": bool(ordinary and not str(request.override_reason or "").strip() and not approved),
        "requires_approval": bool(boundary and not approved),
        "decision_recorded": bool(decision_recorded),
        "decision_persisted": bool(decision_persisted),
        "task_status": task_status,
        "waiting": bool(waiting),
    })
    snapshotter = getattr(getattr(self, "telemetry", None), "record_snapshot", None)
    metrics_getter = getattr(guard, "metrics_snapshot", None)
    if callable(snapshotter) and callable(metrics_getter):
        try:
            snapshotter("consistency_guard", metrics_getter())
        except Exception:
            pass
    return result

def fast_context(self, root: str, query: str, max_tokens: int) -> dict[str, Any]:
    """Return bounded deterministic context when foreground SLO excludes hybrid retrieval."""
    if self.deterministic is None:
        return {"success": False, "terminal": True, "retryable": False, "error": "deterministic context is unavailable"}
    dcfg = self.config.get("deterministic", {})
    char_budget = min(int(dcfg.get("context_max_chars", 5200)), max(900, int(max_tokens) * 4))
    packed = self._repo_cached(
        "fast-context", root,
        {"query": query, "max_chars": char_budget, "raw": int(dcfg.get("context_raw_evidence", 5))},
        lambda: self.deterministic.context_pack(
            root, query, max_chars=char_budget,
            max_raw_evidence=int(dcfg.get("context_raw_evidence", 5)),
        ),
    )
    if isinstance(packed, dict):
        packed["context_source"] = "deterministic-fast"
        packed["degraded"] = True
        packed["degraded_reason"] = "deterministic_only"
        packed["continuation"] = {
            "available": True, "mode": "adaptive",
            "hint": "Retry the adaptive context pack when deterministic-only context is insufficient.",
        }
    return packed


def recommend_direct_rag_strategy(
    self, root: str, query: str, *, workspace: str,
) -> str | None:
    """Reuse the adaptive pack's verified retrieval advisory for direct RAG search."""
    if not isinstance(query, str) or not query.strip():
        return None
    available = getattr(self, "laya_advisory_available", None)
    if not callable(available) or available() is not True:
        return None
    try:
        request = ConsistencyRequest(
            root=canonical_root(root),
            query=query,
            phase="discover",
            workspace=workspace,
            token_budget=512,
        )
        packed = self.adaptive_context_pack(request, mode="adaptive")
    except Exception as exc:
        logger.debug("Laya direct RAG strategy fallback: %s", type(exc).__name__)
        return None
    if not isinstance(packed, dict) or packed.get("success") is not True:
        return None
    strategy = packed.get("laya_retrieval_strategy")
    return strategy if strategy in {"dense_rag", "lexical_bm25"} else None

def _hybrid_context(
    self,
    root: str,
    query: str,
    *,
    workspace: str | None,
    max_tokens: int,
    quality_first: bool = False,
    context_identity: dict[str, Any] | None = None,
    path_hints: tuple[dict[str, str], ...] = (),
    directory_hints: tuple[str, ...] = (),
    exclude_paths: tuple[str, ...] = (),
    force_include_paths: tuple[str, ...] = (),
    focus: tuple[str, ...] = (),
    changed_paths: tuple[str, ...] = (),
    retrieval_weights: dict[str, float] | None = None,
    laya_retrieval_strategy: str | None = None,
) -> dict[str, Any]:
    resolved_root = Path(root).expanduser().resolve(strict=False)
    if not resolved_root.is_dir():
        return {
            "success": False,
            "root": str(resolved_root),
            "query": query,
            "stale_root": True,
            "degraded": True,
            "error_type": "ValueError",
            "error": f"root directory does not exist: {resolved_root}",
            "context": "",
            "evidence": [],
        }
    if quality_first and "project_config_digest" not in (context_identity or {}):
        from .project_config import ProjectConfigError, resolve_project_context

        try:
            project_context = resolve_project_context(
                resolved_root,
                configured_state_dir(getattr(self, "config", {}), create=False),
            )
            project_config_digest = str(project_context.config_digest or "")[:200]
            configured_weights = dict(project_context.settings.retrieval_weights)
            if retrieval_weights is None:
                retrieval_weights = configured_weights
            from .context_identity import normalize_context_path_hints
            from .task_context import _project_context_hint_groups

            pinned_hints, entry_hints, saved_hints = _project_context_hint_groups(
                project_context,
                project_root=resolved_root,
                repository_revision="",
                config_digest=project_config_digest,
            )
            path_hints = normalize_context_path_hints(
                (*pinned_hints, *entry_hints, *path_hints, *saved_hints)
            )
            identity = dict(context_identity or {})
            identity.update({
                "path_hints": path_hints,
                "project_config_digest": project_config_digest,
                "retrieval_weights": retrieval_weights or {},
                "directory_hints": directory_hints,
                "exclude_paths": exclude_paths,
                "force_include_paths": force_include_paths,
                "focus": focus,
                "changed_paths": changed_paths,
            })
            try:
                from .agent_consistency import ConsistencyRequest

                memory_revision = self._adaptive_memory_revision(ConsistencyRequest(
                    root=str(resolved_root), query=query,
                    workspace=workspace or "", token_budget=max_tokens,
                ))
            except Exception:
                memory_revision = ""
            identity["memory_revision"] = memory_revision
            context_identity = identity
        except ProjectConfigError as exc:
            return {
                "success": False, "terminal": True, "retryable": False,
                "stop_code": "context_project_config_invalid",
                "error": f"context project configuration invalid: {type(exc).__name__}",
                "context": "", "evidence": [],
            }
        except (RuntimeError, ValueError) as exc:
            return {
                "success": False, "terminal": True, "retryable": False,
                "stop_code": "context_project_hints_invalid",
                "error": f"context project hints invalid: {type(exc).__name__}",
                "context": "", "evidence": [],
            }
    strategy_scales = {
        "ast_symbol": {"lexical": 0.55, "rag": 0.35, "serena": 0.6, "preprocessor": 0.7},
        "lexical_bm25": {"lexical": 1.0, "rag": 0.45, "serena": 0.7, "preprocessor": 0.75},
        "semantic_hnsw": {"lexical": 0.45, "rag": 1.0, "serena": 0.65, "preprocessor": 0.7},
        "graphrag": {"lexical": 0.5, "rag": 0.9, "serena": 0.8, "preprocessor": 0.8},
    }
    scales = strategy_scales.get(laya_retrieval_strategy or "")
    if scales:
        retrieval_weights = dict(retrieval_weights or {})
        for source, scale in scales.items():
            configured_scale = retrieval_weights.get(source, 1.0)
            if (
                isinstance(configured_scale, (int, float))
                and not isinstance(configured_scale, bool)
                and math.isfinite(float(configured_scale))
            ):
                retrieval_weights[source] = max(0.0, min(1.0, float(configured_scale) * scale))
        context_identity = {
            **(context_identity or {}),
            "laya_retrieval_strategy": laya_retrieval_strategy,
            "retrieval_weights": retrieval_weights,
        }
    # Deterministic fallback remains internal to adaptive retrieval. The adaptive
    # path bypasses this early return so independent backends can cross-check the pack.
    if self.deterministic is not None and not quality_first:
        try:
            det = self.deterministic_query(root, query, 30)
            dcfg = self.config.get("deterministic", {})
            enough = (
                det.get("success")
                and float(det.get("confidence", 0.0) or 0.0) >= float(dcfg.get("context_confidence", 0.80))
                and bool(det.get("facts") or det.get("dependencies") or det.get("scripts") or det.get("evidence") or det.get("code_index"))
            )
            if enough:
                char_budget = min(
                    int(dcfg.get("context_max_chars", 5200)),
                    max(900, int(max_tokens) * 4),
                )
                packed = self._repo_cached(
                    "deterministic-context", root,
                    {"query": query, "max_chars": char_budget, "raw": int(dcfg.get("context_raw_evidence", 5))},
                    lambda: self.deterministic.context_pack(
                        root, query, max_chars=char_budget,
                        max_raw_evidence=int(dcfg.get("context_raw_evidence", 5)),
                    ),
                )
                if isinstance(packed, dict):
                    packed["context_source"] = "deterministic"
                return packed
        except Exception:
            pass
    rag_enabled = self.rag is not None and self.config.get("features", {}).get("rag", True)
    try:
        if rag_enabled:
            self.rag.require_workspace_root(workspace=workspace or self.rag.workspace_id(root), root=root)
        rag_revision = self.rag.revision(workspace=workspace or self.rag.workspace_id(root)) if rag_enabled else None
        rag_revision_available = not rag_enabled or bool(str(rag_revision or "").strip())
    except Exception:
        # RAG is optional. Its revision store failing must not prevent the
        # deterministic and lexical context path from serving the request.
        rag_revision = None
        rag_revision_available = not rag_enabled
    compute = lambda: self._hybrid_context_uncached(
        root, query, workspace=workspace, max_tokens=max_tokens, quality_first=quality_first,
        rag_revision=str(rag_revision or ""), rag_revision_available=rag_revision_available,
        path_hints=path_hints, directory_hints=directory_hints,
        exclude_paths=exclude_paths, force_include_paths=force_include_paths,
        focus=focus, changed_paths=changed_paths,
        retrieval_weights=retrieval_weights,
    )
    if rag_enabled and not rag_revision_available:
        result = compute()
        if isinstance(result, dict):
            result["workspace_cache"] = {"hit": False, "coalesced": False, "degraded": True, "stale": False, "kind": "rag-revision-unavailable"}
            result["cache_hit"] = False
            result["coalesced"] = False
            result["cache_layer"] = "workspace-bypassed"
    else:
        result = self._repo_cached(
            "hybrid-context", root,
            {
                "query": query,
                "workspace": workspace,
                "max_tokens": max_tokens,
                "rag_revision": rag_revision,
                "quality_first": quality_first,
                "context_identity": context_identity or {},
                "path_hints": path_hints,
                "directory_hints": directory_hints,
                "exclude_paths": exclude_paths,
                "force_include_paths": force_include_paths,
                "retrieval_weights": retrieval_weights or {},
                "laya_retrieval_strategy": laya_retrieval_strategy,
            },
            compute,
        )
    retrieval = result.get("retrieval") if isinstance(result, dict) else None
    backend_selection = retrieval.get("backend_selection") if isinstance(retrieval, dict) else None
    empty_adaptive_result = (
        isinstance(result, dict)
        and result.get("success") is True
        and not str(result.get("context") or "").strip()
        and not result.get("evidence")
        and isinstance(backend_selection, dict)
        and backend_selection.get("decision") in {"deadline_exhausted", "optional_backends_selected"}
    )
    stale_hybrid = (
        isinstance(result, dict)
        and result.get("success") is False
        and result.get("stale") is True
    )
    if quality_first and (stale_hybrid or empty_adaptive_result):
        fallback = self.fast_context(ContextRequest(
            task_id=query, root=root, token_budget=max_tokens, phase="fast",
        ))
        if (
            isinstance(fallback, dict)
            and fallback.get("success") is True
            and (str(fallback.get("context") or "").strip() or fallback.get("evidence"))
        ):
            if stale_hybrid:
                fallback_reason = "adaptive_stale_evidence"
            elif isinstance(backend_selection, dict) and backend_selection.get("decision") == "deadline_exhausted":
                fallback_reason = "adaptive_deadline_empty"
            else:
                fallback_reason = "adaptive_optional_empty"
            result = {
                **fallback,
                "context_source": "deterministic-fast-fallback",
                "degraded": True,
                "degraded_reason": fallback_reason,
                "fallback_from": "adaptive-hybrid",
            }
    if isinstance(result, dict): result.setdefault("context_source", "adaptive-hybrid" if quality_first else "hybrid")
    return result

@staticmethod
def _rrf_fuse(lexical_ranked: list[str], vector_ranked: list[str], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion: RRF(d) = sum(1 / (k + rank_i(d)))."""
    scores: dict[str, float] = {}
    for rank, item in enumerate(lexical_ranked):
        scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank + 1)
    for rank, item in enumerate(vector_ranked):
        scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)

@staticmethod
def _external_candidate_paths(root: str, payload: Any) -> list[str]:
    """Compatibility entry point for external backend path normalization."""
    return collect_external_candidate_paths(root, payload)

def _external_context_candidates(
    self, root: str, query: str, *, timeout_budget: float | None = None
) -> tuple[dict[str, list[str]], list[str], dict[str, str]]:
    """Query optional structural backends concurrently; degrade per backend."""
    groups: dict[str, list[str]] = {}
    warnings: list[str] = []
    states: dict[str, str] = {}
    external = getattr(self, "external_tools", None)
    if external is None:
        return groups, warnings, {"serena": "skipped"}
    if getattr(external, "serena_enabled", True) is False:
        return groups, warnings, {"serena": "skipped"}
    try:
        terms = list(self.repo_tools.search_terms(query))[:8]
    except Exception:
        terms = []
    anchor_query = (terms[0] if terms else str(query)[:80]).strip()
    surface_match = re.search(re.escape(anchor_query), str(query), flags=re.IGNORECASE)
    if surface_match:
        anchor_query = surface_match.group(0)
    if not anchor_query:
        return groups, warnings, {"serena": "skipped"}

    def run(backend: str) -> tuple[str, list[str], str | None]:
        try:
            call_kwargs: dict[str, Any] = {"backend": backend, "action": "search", "limit": 12}
            try:
                import inspect
                sig = inspect.signature(external.query).parameters
                if "soft_timeout" in sig:
                    call_kwargs["soft_timeout"] = timeout
                elif "timeout" in sig:
                    call_kwargs["timeout"] = timeout
            except Exception:
                pass
            response = external.query(root, anchor_query, **call_kwargs)
            if not isinstance(response, dict):
                return backend, [], f"{backend} malformed response"
            if response.get("success") is False:
                return backend, [], f"{backend} unavailable"
            result_keys = ("result", "results", "data", "matches", "items", "paths", "symbols")
            result_key = next((key for key in result_keys if key in response), None)
            payload = response.get(result_key) if result_key else None
            if result_key is None or not isinstance(payload, (dict, list, tuple)):
                return backend, [], f"{backend} malformed response"
            return backend, self._external_candidate_paths(root, response), None
        except Exception as exc:
            return backend, [], f"{backend} degraded: {type(exc).__name__}"

    search_cfg = getattr(self, "config", {}).get("search", {})
    configured_timeout = search_cfg.get("context_backend_timeout_seconds")
    timeout = configured_timeout if configured_timeout is not None else 1.0
    try:
        timeout = max(0.05, min(float(timeout), 120.0))
    except (TypeError, ValueError):
        timeout = 1.0
    if timeout_budget is not None:
        try:
            timeout = min(timeout, max(0.0, float(timeout_budget)))
        except (TypeError, ValueError, OverflowError):
            timeout = 0.0
    if timeout <= 0.0:
        return groups, warnings, {"serena": "skipped"}
    futures = {
        _CONTEXT_BACKEND_POOLS[backend].submit(run, backend): backend
        for backend in ("serena",)
    }
    done, pending = _get_wait()(futures, timeout=timeout)
    for future in done:
        backend = futures[future]
        try:
            backend, paths, warning = future.result()
        except Exception as exc:
            paths, warning = [], f"{backend} degraded: {type(exc).__name__}"
        states[backend] = "degraded" if warning else "used"
        if paths:
            groups[backend] = paths
        if warning:
            warnings.append(warning)
    for future in pending:
        backend = futures[future]
        future.cancel()
        states[backend] = "degraded"
        warnings.append(f"{backend} timeout")
    # Cancellation is best-effort for a running thread. The persistent
    # per-backend lane bounds stragglers without delaying this request.
    return groups, warnings, states

@staticmethod
def _adaptive_builtin_confidence(
    deterministic_result: dict[str, Any] | None,
    path_groups: dict[str, list[str]],
) -> float:
    """Require deterministic confidence plus independent index agreement."""
    if not isinstance(deterministic_result, dict) or deterministic_result.get("success") is not True:
        return 0.0
    if not any(
        deterministic_result.get(key)
        for key in ("facts", "dependencies", "scripts", "evidence", "code_index", "test_candidates")
    ):
        return 0.0
    try:
        confidence = float(deterministic_result.get("confidence", 0.0))
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not 0.0 <= confidence <= 1.0:
        return 0.0
    deterministic_paths = {str(path) for path in path_groups.get("deterministic", []) if path}
    indexed_paths = {str(path) for path in path_groups.get("code_index", []) if path}
    union = deterministic_paths | indexed_paths
    agreement = len(deterministic_paths & indexed_paths) / len(union) if union else 0.0
    return min(confidence, agreement)

def _hybrid_context_uncached(
    self,
    root: str,
    query: str,
    *,
    workspace: str | None,
    max_tokens: int,
    quality_first: bool = False,
    rag_revision: str = "",
    rag_revision_available: bool = True,
    path_hints: tuple[dict[str, str], ...] = (),
    directory_hints: tuple[str, ...] = (),
    exclude_paths: tuple[str, ...] = (),
    force_include_paths: tuple[str, ...] = (),
    focus: tuple[str, ...] = (),
    changed_paths: tuple[str, ...] = (),
    retrieval_weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    search_cfg = self.config.get("search", {})

    def bounded_timeout(key: str, default: float) -> float:
        try:
            return max(0.05, min(float(search_cfg.get(key, default)), 120.0))
        except (TypeError, ValueError, OverflowError):
            return default

    backend_budget_seconds = max(
        bounded_timeout("context_backend_timeout_seconds", 1.0),
        bounded_timeout("context_rag_timeout_seconds", 3.0),
    )
    if self.learner is not None:
        try: self.learner.record(root, query)
        except Exception: pass
    target_workspace = workspace
    rag_setup_error: str | None = None
    if self.rag is not None and self.config.get("features", {}).get("rag", True) and not target_workspace:
        try:
            candidate = self.rag.workspace_id(root)
            has_chunks = getattr(self.rag, "has_workspace_chunks", None)
            if callable(has_chunks):
                workspace_indexed = has_chunks(workspace=candidate)
            else:
                workspace_indexed = any(
                    isinstance(item, dict) and str(item.get("workspace", "")) == candidate
                    for item in self.rag.list_workspaces()
                )
            if workspace_indexed:
                target_workspace = candidate
        except Exception as exc:
            rag_setup_error = f"rag workspace unavailable: {type(exc).__name__}"

    rag_configured = self.rag is not None and self.config.get("features", {}).get("rag", True)
    retrieval_warnings: list[str] = [rag_setup_error] if rag_setup_error else []
    if rag_configured and not rag_revision_available:
        retrieval_warnings.append("rag revision unavailable; cache bypassed")
    rag_pool = None
    rag_future = None
    preprocessor_future = None
    semantic_fraction = max(0.0, min(float(search_cfg.get("semantic_fraction", 0.35)), 0.7))
    lexical_tokens = max_tokens if not target_workspace else max(512, int(max_tokens * (1.0 - semantic_fraction)))
    # Local AI: deterministic/semantic paths are ranking hints only. Keep lexical
    # search repository-wide so one hit in a hinted file cannot hide other candidates.
    candidate_paths: list[str] = []
    path_groups: dict[str, list[str]] = {}
    backend_states: dict[str, str] = {}
    deterministic_result: dict[str, Any] | None = None
    # Prioritize files explicitly named in the query/task (e.g. AGENTS.md, src/main.py)
    root_path = Path(root)
    explicit_paths: list[str] = []
    for token in query.split():
        clean_tok = token.strip("`'\"(),:;[]{}*")
        if clean_tok and ("." in clean_tok or "/" in clean_tok or "\\" in clean_tok):
            try:
                rel_p = clean_tok.replace("\\", "/").lstrip("./")
                if (root_path / rel_p).exists() and rel_p not in explicit_paths:
                    explicit_paths.append(rel_p)
            except Exception:
                pass
    if explicit_paths:
        path_groups["explicit"] = explicit_paths
    if self.deterministic is not None:
        try:
            if quality_first:
                try:
                    deterministic_result = self.deterministic_query(root, query, 30)
                except Exception:
                    deterministic_result = None
            related_kwargs: dict[str, Any] = {"limit": 28}
            if deterministic_result is not None:
                try:
                    import inspect

                    parameters = inspect.signature(self.deterministic.related_paths).parameters
                    if "result" in parameters or any(
                        parameter.kind == parameter.VAR_KEYWORD for parameter in parameters.values()
                    ):
                        related_kwargs["result"] = deterministic_result
                except Exception:
                    pass
            path_groups["deterministic"] = list(self.deterministic.related_paths(root, query, **related_kwargs))
            backend_states["deterministic"] = "used"
        except Exception as exc:
            backend_states["deterministic"] = "degraded"
            retrieval_warnings.append(f"deterministic degraded: {type(exc).__name__}")
    else:
        backend_states["deterministic"] = "skipped"
    if self.code_index is not None:
        try:
            code_index_kwargs: dict[str, Any] = {"limit": 24}
            indexed_result = (
                deterministic_result.get("code_index")
                if isinstance(deterministic_result, dict)
                else None
            )
            if isinstance(indexed_result, dict):
                try:
                    import inspect

                    parameters = inspect.signature(self.code_index.related_paths).parameters
                    if "result" in parameters or any(
                        parameter.kind == parameter.VAR_KEYWORD for parameter in parameters.values()
                    ):
                        code_index_kwargs["result"] = indexed_result
                except Exception:
                    pass
            path_groups["code_index"] = list(
                self.code_index.related_paths(root, query, **code_index_kwargs)
            )
            backend_states["code_index"] = "used"
        except Exception as exc:
            backend_states["code_index"] = "degraded"
            retrieval_warnings.append(f"code_index degraded: {type(exc).__name__}")
    else:
        backend_states["code_index"] = "skipped"
    backend_states["preprocessor"] = "skipped"
    confidence = self._adaptive_builtin_confidence(deterministic_result, path_groups) if quality_first else 0.0
    try:
        confidence_threshold = max(
            0.0,
            min(float(self.config.get("deterministic", {}).get("context_confidence", 0.80)), 1.0),
        )
    except (TypeError, ValueError, OverflowError):
        confidence_threshold = 0.80
    confident_builtin = quality_first and confidence >= confidence_threshold
    # Synchronous workspace/index preparation above is outside this optional
    # backend budget. Start it only when the bounded backends can actually run.
    preparation_ms = round((time.perf_counter() - started_at) * 1000.0, 3)
    backend_deadline = time.perf_counter() + backend_budget_seconds
    remaining_budget = max(0.0, backend_deadline - time.perf_counter())
    request_optional = not confident_builtin
    rag_ready = bool(
        rag_configured and target_workspace and query.strip() and rag_revision_available
    )
    requested_backends: list[str] = []
    external_tools = getattr(self, "external_tools", None)
    serena_enabled = external_tools is not None and getattr(external_tools, "serena_enabled", True) is not False
    if self.preprocessor is not None:
        if remaining_budget <= 0.0:
            backend_states["preprocessor"] = "skipped"
        elif not _PREPROCESSOR_CONTEXT_ADMISSION.acquire(blocking=False):
            backend_states["preprocessor"] = "degraded"
            retrieval_warnings.append("preprocessor busy")
        else:
            try:
                preprocessor_limit = max(
                    12,
                    int(self.config.get("preprocessing", {}).get("lookup_file_cards", 5)) * 4,
                )
                preprocessor_future = _CONTEXT_BACKEND_POOLS["preprocessor"].submit(
                    self.preprocessor.candidate_paths,
                    root,
                    query,
                    limit=preprocessor_limit,
                )
                preprocessor_future.add_done_callback(
                    lambda _future: _PREPROCESSOR_CONTEXT_ADMISSION.release()
                )
                backend_states["preprocessor"] = "pending"
                requested_backends.append("preprocessor")
            except Exception as exc:
                _PREPROCESSOR_CONTEXT_ADMISSION.release()
                backend_states["preprocessor"] = "degraded"
                retrieval_warnings.append(f"preprocessor degraded: {type(exc).__name__}")
    if quality_first and request_optional and serena_enabled:
        requested_backends.append("serena")
    if rag_ready and request_optional:
        requested_backends.append("rag")
    rag_cancel_event = None
    if rag_ready and request_optional and remaining_budget > 0.0:
        rag_pool = _CONTEXT_BACKEND_POOLS["rag"]
        reranker_obj = getattr(self, "reranker", None) or getattr(getattr(self, "rag", None), "reranker", None)
        active_device = str(getattr(reranker_obj, "active_device", "") or getattr(reranker_obj, "device", "") or "").strip().lower()
        rag_use_reranker = (
            bool(self.config.get("rag", {}).get("use_reranker", True))
            and not (reranker_obj and active_device == "cpu")
        )
        rag_cancel_event = threading.Event()
        rag_future = rag_pool.submit(
            self.rag.search, query, workspace=target_workspace,
            top_k=10, use_reranker=rag_use_reranker,
            deadline=backend_deadline,
            cancel_event=rag_cancel_event,
        )
    elif rag_ready and request_optional:
        backend_states["rag"] = "skipped"
    elif rag_configured and not rag_revision_available:
        backend_states["rag"] = "degraded"
    else:
        backend_states["rag"] = "skipped"
    if confident_builtin:
        backend_states["serena"] = "skipped"
    elif quality_first and remaining_budget <= 0.0:
        backend_states["serena"] = "skipped"
    elif quality_first:
        external_groups, external_warnings, external_states = self._external_context_candidates(
            root, query, timeout_budget=remaining_budget,
        )
        path_groups.update(external_groups)
        backend_states.update(external_states)
        retrieval_warnings.extend(external_warnings)
    else:
        backend_states.update({"serena": "skipped", "rag": "skipped"})
    selected_backends = requested_backends if remaining_budget > 0.0 else []
    if confident_builtin:
        selection_decision = "builtin_confident"
    elif requested_backends and remaining_budget <= 0.0:
        selection_decision = "deadline_exhausted"
    elif selected_backends:
        selection_decision = "optional_backends_selected"
    else:
        selection_decision = "no_optional_backend_available"
    backend_selection = {
        "decision": selection_decision,
        "confidence": round(confidence, 4),
        "threshold": round(confidence_threshold, 4),
        "selected_backends": selected_backends,
        "preparation_ms": preparation_ms,
        "remaining_budget_ms": round(remaining_budget * 1000, 3),
    }
    hinted_paths = [
        str(item.get("path", "")) if isinstance(item, dict) else item
        for item in path_hints
        if (isinstance(item, dict) and item.get("path")) or isinstance(item, str)
    ]
    if hinted_paths:
        path_groups["project_hints"] = hinted_paths
    if directory_hints:
        path_groups["directory_hints"] = list(directory_hints)
    if force_include_paths:
        path_groups["force_include"] = list(force_include_paths)

    def path_matches(path: str, patterns: tuple[str, ...]) -> bool:
        normalized = path.replace("\\", "/").strip("/").casefold()
        basename = normalized.rsplit("/", 1)[-1]
        for pattern in patterns:
            pattern = pattern.replace("\\", "/").strip("/").casefold()
            if not pattern:
                continue
            if any(char in pattern for char in "*?["):
                if fnmatch.fnmatchcase(normalized, pattern) or fnmatch.fnmatchcase(basename, pattern):
                    return True
            elif normalized == pattern or normalized.startswith(pattern + "/"):
                return True
        return False

    def excluded_path(path: str) -> bool:
        return path_matches(path, exclude_paths)

    def safe_relative_candidate(raw_path: Any, base_path: Path) -> str | None:
        value = str(raw_path or "").strip()
        if not value:
            return None
        try:
            candidate = Path(value)
            candidate = candidate if candidate.is_absolute() else base_path / candidate
            lexical_relative = candidate.relative_to(base_path)
            if ".." in lexical_relative.parts:
                return None
            current = base_path
            for part in lexical_relative.parts:
                current = current / part
                if current.is_symlink():
                    return None
            resolved = candidate.resolve(strict=False)
            relative = resolved.relative_to(base_path)
        except (OSError, RuntimeError, ValueError):
            return None
        normalized = relative.as_posix().strip("/")
        return normalized if normalized and normalized != "." else None

    inventory_candidate_limit = 512
    inventory_scan_limit = 4096
    try:
        fallback_scan_limit = max(1, min(512, int(search_cfg.get("context_fallback_scan_limit", 512))))
    except (TypeError, ValueError, OverflowError):
        fallback_scan_limit = 512
    path_inventory_state = "skipped"
    recall_paths: tuple[str, ...] = ()
    path_controls_active = bool(
        path_hints or directory_hints or exclude_paths or force_include_paths or focus or changed_paths
    )
    forced_candidate_paths: tuple[str, ...] = ()
    if path_controls_active:
        base_path = Path(root).expanduser().resolve(strict=False)
        forced_candidate_paths = tuple(dict.fromkeys(
            path for raw_path in force_include_paths
            if (path := safe_relative_candidate(raw_path, base_path))
        ))
        raw_inventory: Any = None
        inventory_source = ""
        indexed_paths = getattr(self.preprocessor, "indexed_paths", None)
        if callable(indexed_paths):
            try:
                raw_inventory = indexed_paths(root)
                inventory_source = "preprocessor"
                path_inventory_state = "used"
            except Exception as exc:
                retrieval_warnings.append(f"path inventory unavailable: {type(exc).__name__}")
        indexes_available = any(
            backend_states.get(name) == "used"
            for name in ("deterministic", "code_index", "preprocessor")
        )
        if raw_inventory is None and indexes_available:
            # Existing ranked backend results remain the bounded index candidate set.
            raw_inventory = ()
            path_inventory_state = "degraded"
            retrieval_warnings.append("path inventory unavailable; using ranked index candidates")
        elif (
            raw_inventory is not None
            and hasattr(raw_inventory, "__len__")
            and len(raw_inventory) == 0
            and not bool(getattr(self.preprocessor, "enabled", True))
        ):
            # A disabled preprocessor may expose an empty inventory method,
            # but that is not an indexed proof that the repository is empty.
            raw_inventory = self.repo_tools.iter_files(str(base_path))
            inventory_source = "filesystem_fallback"
            path_inventory_state = "degraded"
            retrieval_warnings.append("preprocessor disabled; using bounded filesystem fallback")
        elif raw_inventory is None:
            raw_inventory = self.repo_tools.iter_files(str(base_path))
            inventory_source = "filesystem_fallback"
            path_inventory_state = "degraded"
            retrieval_warnings.append("path inventory unavailable; bounded filesystem fallback")

        scan_limit = fallback_scan_limit if inventory_source == "filesystem_fallback" else inventory_scan_limit
        scope_patterns = tuple(dict.fromkeys((
            *hinted_paths, *directory_hints, *force_include_paths, *changed_paths,
        )))
        focus_terms = tuple(dict.fromkeys(
            term.casefold()
            for value in focus
            for term in re.findall(r"[a-zA-Z0-9_]{3,}", str(value))
        ))
        selected_inventory: list[str] = []
        other_inventory: list[str] = []
        inspected_count = 0
        try:
            for inspected, raw_path in enumerate(itertools.islice(raw_inventory, scan_limit)):
                inspected_count = inspected + 1
                candidate = safe_relative_candidate(raw_path, base_path)
                if candidate is None:
                    continue
                in_scope = (
                    not scope_patterns and not focus_terms
                ) or path_matches(candidate, scope_patterns) or any(
                    term in candidate.casefold() for term in focus_terms
                )
                target = selected_inventory if in_scope else other_inventory
                if candidate not in target and len(target) < inventory_candidate_limit:
                    target.append(candidate)
                if len(selected_inventory) >= inventory_candidate_limit:
                    break
            if inventory_source == "filesystem_fallback" and inspected_count >= scan_limit:
                retrieval_warnings.append("filesystem fallback candidate limit reached")
            if inventory_source != "filesystem_fallback" and inspected_count >= scan_limit:
                raw_size = len(raw_inventory) if hasattr(raw_inventory, "__len__") else None
                if raw_size is None or raw_size > scan_limit:
                    retrieval_warnings.append("indexed path candidate scan reached its bound")
                    path_inventory_state = "degraded"
        except Exception as exc:
            path_inventory_state = "degraded"
            retrieval_warnings.append(f"path inventory scan degraded: {type(exc).__name__}")
        recall_paths = tuple((
            *selected_inventory,
            *other_inventory[:max(0, inventory_candidate_limit - len(selected_inventory))],
        ))
        normalized_directories = tuple(dict.fromkeys(
            path for raw_path in directory_hints
            if (path := safe_relative_candidate(raw_path, base_path))
        ))
        if normalized_directories:
            directory_candidates = tuple(
                candidate for candidate in recall_paths
                if path_matches(candidate, normalized_directories)
            )
            if directory_candidates:
                path_groups["directory_hints"] = list(directory_candidates)
        backend_states["path_inventory"] = path_inventory_state

    base_path = Path(root).expanduser().resolve(strict=False)
    forced_candidate_paths = tuple(dict.fromkeys((
        *forced_candidate_paths,
        *(path for raw_path in force_include_paths
          if (path := safe_relative_candidate(raw_path, base_path))),
    )))
    preprocessor_wait_started = time.perf_counter()
    if preprocessor_future is not None:
        preprocessor_timeout = max(0.0, backend_deadline - time.perf_counter())
        _preprocessor_done, preprocessor_pending = _get_wait()(
            (preprocessor_future,), timeout=preprocessor_timeout,
        )
        if preprocessor_pending:
            preprocessor_future.cancel()
            backend_states["preprocessor"] = "degraded"
            retrieval_warnings.append("preprocessor timeout")
        else:
            try:
                candidate_paths = preprocessor_future.result()
                if not isinstance(candidate_paths, (list, tuple)):
                    raise TypeError("preprocessor candidate paths are malformed")
                path_groups["preprocessor"] = list(candidate_paths)
                backend_states["preprocessor"] = "used"
            except Exception as exc:
                backend_states["preprocessor"] = "degraded"
                retrieval_warnings.append(f"preprocessor degraded: {type(exc).__name__}")
    backend_selection["preprocessor_wait_ms"] = round(
        (time.perf_counter() - preprocessor_wait_started) * 1000.0, 3,
    )
    # Every backend and request hint is normalized against the same repository root.
    path_groups = {
        backend: list(dict.fromkeys(
            path for raw_path in paths
            if (path := safe_relative_candidate(raw_path, base_path))
        ))
        for backend, paths in path_groups.items()
    }
    if exclude_paths:
        path_groups = {
            backend: [path for path in paths if not excluded_path(path)]
            for backend, paths in path_groups.items()
        }
    changed_candidate_paths = tuple(dict.fromkeys(
        path for raw_path in changed_paths
        if (path := safe_relative_candidate(raw_path, Path(root).expanduser().resolve(strict=False)))
        and not excluded_path(path)
    ))
    all_candidate_paths = tuple(dict.fromkeys((
        *(path for paths in path_groups.values() for path in paths), *recall_paths,
        *changed_candidate_paths,
    )))
    focus_terms = tuple(dict.fromkeys(
        term.casefold()
        for value in focus
        for term in re.findall(r"[a-zA-Z0-9_]{3,}", str(value))
    ))
    focus_candidate_paths = tuple(
        path for path in all_candidate_paths
        if any(term in path.casefold() for term in focus_terms)
        and not excluded_path(path)
    )
    if changed_candidate_paths:
        path_groups["changed_paths"] = list(changed_candidate_paths)
    if focus_candidate_paths:
        path_groups["task_focus"] = list(focus_candidate_paths)
    pinned_paths = tuple(
        path
        for item in path_hints[:64]
        if isinstance(item, dict)
        and item.get("provenance") == "project_config:pinned_context"
        and isinstance(item.get("path"), str)
        and (path := safe_relative_candidate(item["path"], base_path))
    )
    source_priority_paths = tuple(dict.fromkeys((
        *pinned_paths, *forced_candidate_paths, *changed_candidate_paths, *focus_candidate_paths,
        *(path for raw_path in explicit_paths if (path := safe_relative_candidate(raw_path, base_path))),
    )))
    source_query = is_source_context_query(query)
    if source_query:
        path_groups = {
            backend: prioritize_source_context_paths(
                paths, query, priority_paths=source_priority_paths,
            )
            for backend, paths in path_groups.items()
        }
    fused_candidates = fuse_ranked_paths(
        path_groups, limit=256 if source_query else 64, max_per_path=2,
    )
    if source_query:
        priority_keys = {path.casefold() for path in source_priority_paths}
        fused_candidates.sort(key=lambda item: (
            0 if item[0].replace("\\", "/").casefold() in priority_keys
            else 1 + source_context_path_tier(item[0]),
            -item[1],
            item[0],
        ))
        fused_candidates = fused_candidates[:64]
    # Pins survive ranking limits, but never become force-include authorization.
    candidate_paths = list(dict.fromkeys((
        *pinned_paths,
        *forced_candidate_paths,
        *changed_candidate_paths,
        *focus_candidate_paths,
        *(path for path, _score in fused_candidates),
        *recall_paths,
    )))
    candidate_paths = [
        path for raw_path in candidate_paths
        if (path := safe_relative_candidate(raw_path, base_path))
        and not excluded_path(path)
        and not ((base_path / path).is_dir() and any(
            candidate.startswith(path.rstrip("/") + "/") for candidate in recall_paths
        ))
    ]
    candidate_paths = candidate_paths[:inventory_candidate_limit]
    try:
        lexical_candidate_limit = max(1, min(64, int(search_cfg.get("context_top_k", 14))))
    except (TypeError, ValueError, OverflowError):
        lexical_candidate_limit = 14
    if (
        (path_controls_active or quality_first)
        and path_inventory_state != "used"
        and len(candidate_paths) < lexical_candidate_limit
    ):
        # Hints bias candidate ordering; they must not turn a bounded adaptive
        # lookup into a search restricted to hinted paths. Fill sparse indexed
        # candidates with a bounded lexical pass, then apply explicit excludes.
        try:
            completion = self.repo_tools.search(
                root,
                query,
                limit=lexical_candidate_limit,
            )
            if isinstance(completion, dict) and completion.get("success"):
                candidate_paths.extend(
                    path
                    for item in completion.get("results", [])
                    if isinstance(item, dict)
                    and isinstance(item.get("path"), str)
                    and item.get("path")
                    and (path := safe_relative_candidate(item["path"], base_path))
                    and not excluded_path(path)
                )
                candidate_paths = list(dict.fromkeys(candidate_paths))
            else:
                retrieval_warnings.append("lexical completeness pass unavailable")
        except Exception as exc:
            retrieval_warnings.append(f"lexical completeness pass degraded: {type(exc).__name__}")
    try:
        # A single backend path is only a ranking hint; preserve broad lexical
        # recall until retrieval has produced multiple bounded candidates.
        if candidate_paths and (path_controls_active or len(candidate_paths) > 1):
            candidate_paths = list(dict.fromkeys(candidate_paths))
            pack_kwargs: dict[str, Any] = {
                "max_tokens": lexical_tokens,
                "top_k": int(search_cfg.get("context_top_k", 14)),
            }
            if path_hints or directory_hints or exclude_paths or force_include_paths:
                hinted_directories = tuple(dict.fromkeys((
                    *directory_hints,
                    *hinted_paths,
                )))
                pack_kwargs.update({
                    "directory_hints": hinted_directories,
                    "exclude_paths": exclude_paths,
                    "force_include_paths": force_include_paths,
                })
            if source_query:
                try:
                    import inspect

                    pack_signature = inspect.signature(self.repo_tools.context_pack_paths).parameters
                    supports_priority_paths = "priority_paths" in pack_signature or any(
                        parameter.kind == parameter.VAR_KEYWORD
                        for parameter in pack_signature.values()
                    )
                except (TypeError, ValueError):
                    supports_priority_paths = False
                if supports_priority_paths:
                    pack_kwargs["priority_paths"] = list(source_priority_paths)
            lexical = self.repo_tools.context_pack_paths(
                root, query, candidate_paths, **pack_kwargs,
            )
        elif path_controls_active:
            lexical = {
                "success": True, "root": str(root_path), "context": "", "evidence": [],
                "scanned_files": 0, "targeted": True,
            }
        else:
            lexical = self.repo_tools.context_pack(
                root, query, max_tokens=lexical_tokens,
                top_k=int(search_cfg.get("context_top_k", 14)),
            )
    except Exception as exc:
        lexical = {"success": False, "error": f"lexical backend degraded: {type(exc).__name__}"}
    if not isinstance(lexical, dict) or not isinstance(lexical.get("evidence", []), list):
        lexical = {"success": False, "error": "lexical backend malformed response"}
    if not lexical.get("success"):
        if not quality_first:
            return lexical
        backend_states["lexical"] = "degraded"
        retrieval_warnings.append(str(lexical.get("error", "lexical backend unavailable"))[:240])
        lexical = {
            "success": True,
            "root": str(root_path),
            "context": "",
            "evidence": [],
            "scanned_files": 0,
        }
    else:
        backend_states["lexical"] = "used"
    evidence = list(lexical.get("evidence", []))
    path_groups["lexical"] = [str(item.get("path")) for item in evidence if item.get("path")]
    baseline_fused_evidence = fuse_ranked_paths(
        path_groups, limit=max(24, len(evidence)), max_per_path=2,
    )
    fused_evidence = baseline_fused_evidence
    if retrieval_weights:
        selected_paths = {path for path, _score in baseline_fused_evidence}
        selected_groups = {
            source: [path for path in paths if path in selected_paths]
            for source, paths in path_groups.items()
        }
        fused_evidence = fuse_ranked_paths(
            selected_groups,
            limit=max(1, len(selected_paths)),
            max_per_path=max(1, len(selected_paths)),
            source_weights=retrieval_weights,
        )
    evidence_rank = {path: rank for rank, (path, _score) in enumerate(fused_evidence)}
    if source_query:
        priority_keys = {path.replace("\\", "/").casefold() for path in source_priority_paths}

        def final_evidence_rank(item: dict[str, Any]) -> tuple[int, int, int, str]:
            path = str(item.get("path", ""))
            normalized_path = path.replace("\\", "/").casefold()
            return (
                0 if normalized_path in priority_keys else 1,
                source_context_path_tier(path),
                evidence_rank.get(path, 999),
                path,
            )

        evidence.sort(key=final_evidence_rank)
    else:
        evidence.sort(key=lambda item: (
            evidence_rank.get(str(item.get("path", "")), 999),
            str(item.get("path", "")),
        ))
    if self.evidence_store is not None:
        try:
            stored_evidence = self.evidence_store.put_many(
                str(lexical.get("root", root)),
                evidence,
                source_code="indexed",
            )
        except Exception as exc:
            return {
                "success": False, "terminal": True, "retryable": False,
                "stop_code": "context_evidence_persistence_failed",
                "error": f"context evidence persistence failed: {type(exc).__name__}",
                "root": str(root), "query": query, "context": "", "evidence": [],
            }
        if not isinstance(stored_evidence, (list, tuple)) or any(
            not isinstance(item, dict) or not str(item.get("evidence_id") or "").strip()
            for item in stored_evidence
        ):
            return {
                "success": False, "terminal": True, "retryable": False,
                "stop_code": "context_evidence_receipt_incomplete",
                "error": "context evidence receipt is missing or incomplete",
                "root": str(root), "query": query, "context": "", "evidence": [],
            }
        evidence = list(stored_evidence)
    else:
        traceable: list[dict[str, Any]] = []
        for item in evidence:
            if not isinstance(item, dict):
                continue
            traced = dict(item)
            if not str(traced.get("evidence_id") or "").strip():
                traced["evidence_id"] = "local-" + stable_hash({
                    "root": canonical_root(str(lexical.get("root", root))),
                    "path": str(traced.get("path") or ""),
                    "symbol": str(traced.get("symbol") or ""),
                    "start_line": traced.get("start_line", 0),
                    "end_line": traced.get("end_line", 0),
                    "content_hash": traced.get("content_hash") or stable_hash(str(traced.get("text") or "")),
                })[:24]
            traceable.append(traced)
        evidence = traceable
    context = str(lexical.get("context", ""))
    # Keep the already budgeted, exact lexical rendering intact; only move
    # its complete snippet blocks into the same order as their evidence.
    rendered_positions: list[tuple[int, int]] = []
    used_positions: set[int] = set()
    for evidence_index, item in enumerate(evidence):
        if not isinstance(item, dict) or not item.get("path"):
            rendered_positions = []
            break
        header = (
            f"--- {item['path']}:{item.get('start_line')}-{item.get('end_line')} "
            f"score={item.get('score')} ---\n"
        )
        position = context.find(header)
        while position in used_positions and position >= 0:
            position = context.find(header, position + 1)
        if position < 0:
            rendered_positions = []
            break
        rendered_positions.append((evidence_index, position))
        used_positions.add(position)
    source_order = sorted(rendered_positions, key=lambda item: item[1])
    if rendered_positions and len(rendered_positions) == len(evidence) and source_order[0][1] == 0:
        blocks: dict[int, str] = {}
        for offset, (evidence_index, start) in enumerate(source_order):
            end = source_order[offset + 1][1] if offset + 1 < len(source_order) else len(context)
            blocks[evidence_index] = context[start:end]
        context = "".join(blocks[index] for index in range(len(evidence)))
    semantic_used = False
    semantic_candidate_count = 0
    semantic_included_count = 0
    semantic_omitted_count = 0
    semantic_truncated_count = 0
    semantic_malformed_count = 0
    semantic_declared_hash_count = 0
    semantic_backend_truncated: bool | None = None
    semantic_backend_coverage_complete: bool | None = None
    per_path: dict[str, int] = {}
    for item in evidence:
        path = str(item.get("path", ""))
        per_path[path] = per_path.get(path, 0) + 1
    max_per_file = max(1, int(search_cfg.get("max_snippets_per_file", 3)))

    if rag_future is not None and rag_pool is not None:
        rag_timeout = min(
            bounded_timeout("context_rag_timeout_seconds", 3.0),
            max(0.0, backend_deadline - time.perf_counter()),
        )
        rag_done, rag_pending = _get_wait()((rag_future,), timeout=rag_timeout)
        if rag_pending:
            if rag_cancel_event is not None:
                rag_cancel_event.set()
            rag_future.cancel()
            rr = None
            backend_states["rag"] = "degraded"
            retrieval_warnings.append("rag timeout")
        else:
            try:
                rr = rag_future.result()
            except Exception as exc:
                rr = None
                backend_states["rag"] = "degraded"
                retrieval_warnings.append(f"rag degraded: {type(exc).__name__}")
    else:
        rr = None
        if rag_setup_error:
            backend_states["rag"] = "degraded"
        else:
            backend_states["rag"] = "skipped"
    if rag_future is not None:
        from .token_router import strip_boilerplate
        if isinstance(rr, dict) and rr.get("success") and isinstance(rr.get("results"), list):
            raw_results = rr["results"]
            if isinstance(rr.get("truncated"), bool):
                semantic_backend_truncated = rr["truncated"]
            raw_backend_coverage = rr.get("coverage")
            if isinstance(raw_backend_coverage, dict) and isinstance(raw_backend_coverage.get("complete"), bool):
                semantic_backend_coverage_complete = raw_backend_coverage["complete"]
            sorted_results_input = []
            malformed_results = False
            for item in raw_results:
                if not isinstance(item, dict) or not str(item.get("path") or "").strip():
                    malformed_results = True
                    semantic_malformed_count += 1
                    continue
                rag_path = str(item.get("path", "")).replace("\\", "/").strip("/")
                if excluded_path(rag_path):
                    continue
                try:
                    chunk_no = int(item.get("chunk_no", 0))
                except (TypeError, ValueError, OverflowError):
                    malformed_results = True
                    semantic_malformed_count += 1
                    continue
                if not isinstance(item.get("text", ""), str):
                    malformed_results = True
                    semantic_malformed_count += 1
                    continue
                sorted_results_input.append({**item, "chunk_no": chunk_no})
            if malformed_results:
                backend_states["rag"] = "degraded"
                retrieval_warnings.append("rag malformed result entries")
            elif backend_states.get("rag") != "degraded" and rag_revision_available:
                backend_states["rag"] = "used"
            elif not rag_revision_available:
                backend_states["rag"] = "degraded"
            # RRF candidate ordering
            lex_paths = [str(e.get("path")) for e in evidence if e.get("path")]
            vec_paths = [str(r.get("path")) for r in sorted_results_input]
            path_groups["lexical"] = lex_paths
            path_groups["rag"] = vec_paths
            fused_order = [p for p, _score in fuse_ranked_paths(path_groups, limit=64, max_per_path=2)]
            fused_rank = {p: i for i, p in enumerate(fused_order)}
            sorted_results = sorted(sorted_results_input, key=lambda item: fused_rank.get(str(item.get("path", "")), 999))
            semantic_candidate_count = len(sorted_results)
            remaining = max(0, chars_for_tokens(max_tokens) - len(context))
            seen_chunks: set[tuple[str, int]] = set()
            for result_index, item in enumerate(sorted_results):
                path = str(item.get("path", ""))
                chunk_no = int(item.get("chunk_no", 0))
                key = (path, chunk_no)
                if key in seen_chunks or per_path.get(path, 0) >= max_per_file:
                    semantic_omitted_count += 1
                    continue
                seen_chunks.add(key)
                clean_text = strip_boilerplate(str(item.get("text", "")))
                rendered = f"\n--- semantic {path} chunk={chunk_no} ---\n{clean_text}\n"
                if len(rendered) > remaining:
                    if remaining > 400:
                        rendered = rendered[:remaining] + "\n[semantic snippet truncated]\n"
                        semantic_truncated_count += 1
                    else:
                        semantic_omitted_count += len(sorted_results) - result_index
                        break
                context += rendered
                remaining -= len(rendered)
                per_path[path] = per_path.get(path, 0) + 1
                semantic_used = True
                rag_evidence = {
                    "evidence_id": str(item.get("evidence_id") or "rag-" + stable_hash({"root": str(root_path), "path": path, "chunk_no": chunk_no, "content_hash": item.get("content_hash"), "revision": item.get("revision")})[:24]),
                    "path": path, "chunk_no": chunk_no, "semantic": True,
                    "revision": str(item.get("revision") or item.get("repository_revision") or item.get("content_hash") or "")[:200],
                    "content_hash": item.get("content_hash"),
                }
                for field in ("symbol", "start_line", "end_line", "repository_revision"):
                    if field in item:
                        rag_evidence[field] = item[field]
                evidence_store = getattr(self, "evidence_store", None)
                if evidence_store is not None and item.get("content_hash") and item.get("start_line") and item.get("end_line"):
                    stored = evidence_store.put_many(
                        str(root_path),
                        [{
                            "path": path,
                            "text": str(item.get("text", "")),
                            "content_hash": str(item.get("content_hash")),
                            "start_line": item.get("start_line"),
                            "end_line": item.get("end_line"),
                        }],
                        source_code="rag",
                    )
                    if stored and stored[0].get("evidence_id"):
                        rag_evidence["evidence_id"] = stored[0]["evidence_id"]
                evidence.append(rag_evidence)
                semantic_included_count += 1
                if item.get("content_hash"):
                    semantic_declared_hash_count += 1
                if remaining <= 0:
                    semantic_omitted_count += len(sorted_results) - result_index - 1
                    break
        elif backend_states.get("rag") != "degraded":
            backend_states["rag"] = "degraded" if rr is not None else "skipped"
            if backend_states["rag"] == "degraded":
                retrieval_warnings.append("rag unavailable or malformed response")
    else:
        backend_states["rag"] = "degraded" if rag_setup_error or (rag_configured and not rag_revision_available) else "skipped"
    evidence_paths = [str(item.get("path") or "") for item in evidence if isinstance(item, dict) and item.get("path")]
    path_backend_counts: dict[str, int] = {}
    for backend_paths in path_groups.values():
        for candidate in set(backend_paths):
            path_backend_counts[candidate] = path_backend_counts.get(candidate, 0) + 1
    lexical_coverage = lexical.get("coverage")
    lexical_freshness = lexical.get("freshness")
    lexical_truncation = lexical.get("truncation")
    lexical_metadata = {
        "coverage": dict(lexical_coverage) if isinstance(lexical_coverage, dict) else {
            "scope": "unknown", "complete": False,
        },
        "freshness": dict(lexical_freshness) if isinstance(lexical_freshness, dict) else {
            "scope": "unknown", "status": "not_reported", "complete": False,
        },
        "truncated": lexical.get("truncated") if isinstance(lexical.get("truncated"), bool) else None,
        "truncation": dict(lexical_truncation) if isinstance(lexical_truncation, dict) else {
            "status": "unknown", "complete": False,
        },
    }
    semantic_metadata = {
        "coverage": {
            "scope": "returned_rag_candidates",
            "candidate_count": semantic_candidate_count,
            "included_evidence_count": semantic_included_count,
            "omitted_chunk_count": semantic_omitted_count,
            "malformed_chunk_count": semantic_malformed_count,
            "complete": semantic_candidate_count > 0 and semantic_omitted_count == 0 and semantic_truncated_count == 0 and semantic_malformed_count == 0 and semantic_backend_truncated is not True and semantic_backend_coverage_complete is not False,
        },
        "freshness": {
            "scope": "included_semantic_evidence",
            "status": "not_checked" if semantic_included_count else "not_available",
            "checked_chunks": 0,
            "declared_hash_chunks": semantic_declared_hash_count,
            "complete": False,
        },
        "truncated": (
            semantic_truncated_count > 0 or semantic_omitted_count > 0 or semantic_backend_truncated is True or semantic_backend_coverage_complete is False
            if semantic_candidate_count > 0 or semantic_backend_truncated is not None or semantic_backend_coverage_complete is not None else None
        ),
        "truncation": {
            "status": "truncated" if semantic_truncated_count or semantic_omitted_count or semantic_backend_truncated is True or semantic_backend_coverage_complete is False else "none_observed" if semantic_candidate_count else "not_available",
            "rendered_truncated_chunks": semantic_truncated_count,
            "omitted_chunks": semantic_omitted_count,
            "backend_reported_truncated": semantic_backend_truncated,
            "backend_coverage_complete": semantic_backend_coverage_complete,
            "complete": semantic_candidate_count > 0 and semantic_truncated_count == 0 and semantic_omitted_count == 0 and semantic_backend_truncated is not True and semantic_backend_coverage_complete is not False,
        },
    }
    fallbacks = [
        {"backend": name, "fallback": "lexical"}
        for name, state in sorted(backend_states.items())
        if name != "lexical" and state == "degraded" and backend_states.get("lexical") == "used"
    ]
    return {
        "success": True, "root": lexical["root"], "query": query, "context": context,
        "evidence": evidence, "estimated_tokens": estimate_tokens(context),
        "scanned_files": lexical.get("scanned_files", 0), "semantic_used": semantic_used,
        **({"degraded": True, "degraded_reason": "bounded_path_candidate_fallback"}
           if path_inventory_state == "degraded" else {}),
        "context_budget_tokens": max_tokens,
        "retrieval": {
            "quality_first": bool(quality_first),
            "rag_revision": str(rag_revision)[:200],
            "backends": sorted(path_groups),
            "used_backends": sorted(name for name, state in backend_states.items() if state == "used"),
            "skipped_backends": sorted(name for name, state in backend_states.items() if state == "skipped"),
            "degraded_backends": sorted(name for name, state in backend_states.items() if state == "degraded"),
            "backend_states": dict(sorted(backend_states.items())),
            "backend_selection": backend_selection,
            "fallbacks": fallbacks,
            "lexical": lexical_metadata,
            "semantic": semantic_metadata,
            "warnings": list(dict.fromkeys(retrieval_warnings))[:8],
            "fused_paths": [path for path, _score in fuse_ranked_paths(path_groups, limit=24, max_per_path=2)],
            "quality": {
                "candidate_count": len(candidate_paths),
                "evidence_count": len(evidence),
                "file_coverage": len(set(evidence_paths)),
                "cross_backend_agreement_count": sum(1 for count in path_backend_counts.values() if count > 1),
            },
            "latency_ms": round((time.perf_counter() - started_at) * 1000, 3),
        },
    }
