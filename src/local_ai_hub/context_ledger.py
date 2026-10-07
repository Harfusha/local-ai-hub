"""Bounded metadata-only ledger for agent context pressure."""

from __future__ import annotations

from collections import Counter, deque
import hashlib
import json
from threading import Lock
import time
from typing import Any

from .context_identity import (
    ContextPathHintInput,
    context_path_hints_identity,
    normalize_context_root,
    normalize_settings_digest,
)
from .evidence import is_current_evidence_id


class ContextLedger:
    """Track token pressure without retaining prompts, source, or command text."""

    def __init__(self, *, max_entries: int = 512, pointer_ttl_seconds: int = 300) -> None:
        self._max_entries = max(1, int(max_entries))
        self._entries: deque[dict[str, Any]] = deque(maxlen=self._max_entries)
        self._totals: Counter[str] = Counter()
        self._outcomes: Counter[str] = Counter()
        # Retain bounded pointers by semantic identity so newer contexts for the
        # same task do not invalidate still-fresh reuse keys.
        self._compiled: dict[str, dict[str, Any]] = {}
        self._compiled_by_scope: dict[str, str] = {}
        self._pointer_ttl_seconds = max(1, int(pointer_ttl_seconds))
        self._lock = Lock()

    def record(
        self,
        *,
        tool: str,
        operation: str,
        request_tokens: int = 0,
        response_tokens: int = 0,
        saved_tokens: int = 0,
        baseline_tokens_est: int | None = None,
        baseline_evidence_id: str = "",
        evidence_store: Any = None,
        protocol_tokens_est: int = 0,
        schema_tokens_est: int = 0,
        local_compute_reused_tokens_est: int = 0,
        cache_outcome: str = "",
        result_id: str = "",
        session_id: str = "",
    ) -> None:
        evidence_id = str(baseline_evidence_id or "").strip()
        response_count = _safe_nonnegative_int(response_tokens)
        baseline_count = _optional_nonnegative_int(baseline_tokens_est)
        has_baseline = baseline_count is not None and is_current_evidence_id(evidence_id, evidence_store)
        baseline_delta = 0
        if has_baseline:
            baseline_delta = baseline_count - response_count
        entry = {
            "tool": str(tool or "")[:64],
            "operation": str(operation or "default")[:64],
            "request_tokens": _safe_nonnegative_int(request_tokens),
            "response_tokens": response_count,
            "saved_tokens": baseline_delta,
            "baseline_tokens_est": baseline_count if has_baseline else 0,
            "baseline_evidence_id": evidence_id[:64] if has_baseline else "",
            "protocol_tokens_est": _safe_nonnegative_int(protocol_tokens_est),
            "schema_tokens_est": _safe_nonnegative_int(schema_tokens_est),
            "local_compute_reused_tokens_est": _safe_nonnegative_int(local_compute_reused_tokens_est),
            "cache_outcome": str(cache_outcome or "none")[:24],
            "result_id": str(result_id or "")[:32],
        }
        with self._lock:
            if len(self._entries) == self._entries.maxlen:
                evicted = self._entries[0]
                self._totals.subtract({
                    key: evicted[key]
                    for key in (
                        "request_tokens",
                        "response_tokens",
                        "saved_tokens",
                        "protocol_tokens_est",
                        "schema_tokens_est",
                        "local_compute_reused_tokens_est",
                    )
                })
                if evicted["cache_outcome"]:
                    self._outcomes[evicted["cache_outcome"]] -= 1
                    if self._outcomes[evicted["cache_outcome"]] <= 0:
                        del self._outcomes[evicted["cache_outcome"]]
            self._entries.append(entry)
            self._totals.update({
                key: entry[key]
                for key in (
                    "request_tokens",
                    "response_tokens",
                    "saved_tokens",
                    "protocol_tokens_est",
                    "schema_tokens_est",
                    "local_compute_reused_tokens_est",
                )
            })
            if entry["cache_outcome"]:
                self._outcomes[entry["cache_outcome"]] += 1

    def snapshot(self, *, limit: int = 8) -> dict[str, Any]:
        with self._lock:
            entries = list(self._entries)[-max(1, min(int(limit), len(self._entries))):]
            return {
                "entries": len(self._entries),
                "totals": dict(self._totals),
                "cache_outcomes": dict(self._outcomes),
                "last": dict(entries[-1]) if entries else {},
                "recent": [dict(entry) for entry in entries],
            }

    def adaptive_profile(self, requested: str = "compact") -> str:
        profile = str(requested or "compact").strip().lower()
        if profile in {"minimal", "standard", "debug", "delta"}:
            return profile
        with self._lock:
            recent = list(self._entries)[-8:]
        if len(recent) >= 3 and sum(item["response_tokens"] for item in recent) >= 240:
            hits = sum(item["cache_outcome"] in {"hit", "reused"} for item in recent)
            if hits >= max(2, len(recent) // 2):
                return "minimal"
        return "compact"

    def compile(
        self,
        task_id: str,
        revision: str,
        evidence_ids: list[str] | tuple[str, ...],
        context: str,
        *,
        root: str = "",
        identity: str = "",
        phase: str = "",
        focus: list[str] | tuple[str, ...] = (),
        path_hints: list[ContextPathHintInput] | tuple[ContextPathHintInput, ...] | None = (),
        settings_digest: str | None = "",
        preload_profile: str = "",
        configuration: Any = None,
        model: str = "",
        memory_revision: str = "",
        artifact_store: Any = None,
        tenant: str = "local",
    ) -> dict[str, Any]:
        """Return bounded context plus a freshness-bounded, scope-safe reuse key."""
        task = str(task_id or "")
        rev = str(revision or "")
        raw_context = str(context or "")
        full_ids = list(dict.fromkeys(str(item) for item in evidence_ids if str(item)))
        ids = full_ids[:64]
        focus_values = list(focus) if isinstance(focus, (list, tuple)) else [str(focus)] if focus else []
        normalized_root = normalize_context_root(root)
        path_hint_values = list(context_path_hints_identity(path_hints))
        normalized_settings_digest = normalize_settings_digest(settings_digest) or ""
        context_hash = hashlib.sha256()
        for start in range(0, len(raw_context), 8192):
            context_hash.update(raw_context[start:start + 8192].encode("utf-8", "replace"))
        semantic_inputs = {
            "root": normalized_root,
            "revision": rev,
            "identity": str(identity or ""),
            "task_id": task,
            "phase": str(phase or ""),
            "focus": focus_values,
            "path_hints": path_hint_values,
            "settings_digest": normalized_settings_digest,
            "preload_profile": str(preload_profile or ""),
            "configuration": configuration,
            "model": str(model or ""),
            "memory_revision": str(memory_revision or ""),
            "tenant": str(tenant or ""),
            "evidence_ids": full_ids,
            "context_sha256": context_hash.hexdigest(),
        }
        canonical = json.dumps(semantic_inputs, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(canonical.encode("utf-8", "replace")).hexdigest()[:32]
        scope_inputs = {
            "tenant": str(tenant or ""),
            "root": normalized_root,
            "identity": str(identity or ""),
            "task_id": task,
        }
        scope_canonical = json.dumps(scope_inputs, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        scope_key = hashlib.sha256(scope_canonical.encode("utf-8", "replace")).hexdigest()[:32]
        reuse_key = f"ctx_{digest}"
        inline_context = raw_context[:12000]
        context_metadata = (
            {"context_truncated": True, "context_chars": len(raw_context)}
            if len(raw_context) > len(inline_context)
            else {}
        )
        artifact_id = ""
        fresh_until = 0.0
        if artifact_store is not None:
            artifact_id = str(artifact_store.put(raw_context, tenant, "agent-context"))
            artifact_ttl = max(1, int(getattr(artifact_store, "ttl_seconds", self._pointer_ttl_seconds)))
            fresh_until = time.time() + min(self._pointer_ttl_seconds, artifact_ttl)
        current = {
            "tenant": str(tenant or ""),
            "root": normalized_root,
            "identity": str(identity or ""),
            "task_id": task,
            "revision": rev[:200],
            "phase": str(phase or "")[:64],
            "evidence_ids": ids,
            "digest": digest,
            "reuse_key": reuse_key,
            "scope_key": scope_key,
            "artifact_id": artifact_id,
            "fresh_until": fresh_until,
        }
        with self._lock:
            previous_key = self._compiled_by_scope.get(scope_key)
            previous = self._compiled.get(previous_key) if previous_key else None
            if (
                not artifact_id
                and previous
                and previous.get("digest") == digest
                and previous.get("artifact_id")
                and float(previous.get("fresh_until") or 0.0) > time.time()
            ):
                artifact_id = str(previous["artifact_id"])
                fresh_until = float(previous["fresh_until"])
                current["artifact_id"] = artifact_id
                current["fresh_until"] = fresh_until
            if reuse_key not in self._compiled and len(self._compiled) >= self._max_entries:
                evicted_key = next(iter(self._compiled))
                self._compiled.pop(evicted_key)
                for mapped_scope, mapped_key in list(self._compiled_by_scope.items()):
                    if mapped_key == evicted_key:
                        self._compiled_by_scope.pop(mapped_scope, None)
            self._compiled[reuse_key] = current
            self._compiled_by_scope[scope_key] = reuse_key
        pointer = {
            "reuse_key": reuse_key,
            # The public context API has no scoped materialization action yet.
            # Do not expose the underlying artifact ID or advertise raw artifact/get.
            "freshness": "unavailable",
        }
        if previous and previous["digest"] == digest:
            return {
                "status": "unchanged", "context": None,
                **context_metadata, **pointer, "etag": digest,
            }
        added = [item for item in ids if not previous or item not in previous.get("evidence_ids", [])]
        if previous:
            return {
                "status": "delta",
                "context": inline_context,
                "added_evidence_ids": added,
                **context_metadata, **pointer,
                "etag": digest,
            }
        return {
            "status": "materialized", "context": inline_context,
            **context_metadata, **pointer, "etag": digest,
        }

    def materialize(
        self,
        reuse_key: str,
        artifact_store: Any,
        tenant: str,
        *,
        identity: str,
        root: str,
        task_id: str,
        offset: int = 0,
        max_chars: int = 6000,
    ) -> dict[str, Any]:
        """Fetch a fresh context slice through its tenant, root, task, and identity-scoped pointer."""
        with self._lock:
            stored = self._compiled.get(str(reuse_key))
            entry = dict(stored) if stored is not None else None
        if not entry or not entry.get("artifact_id"):
            return {"success": False, "status": "unavailable", "freshness": "unknown", "error": "context pointer cannot be materialized"}
        if (
            entry.get("tenant") != str(tenant or "")
            or entry.get("root") != normalize_context_root(root)
            or entry.get("identity") != str(identity or "")
            or entry.get("task_id") != str(task_id or "")
        ):
            return {"success": False, "status": "unavailable", "freshness": "unknown", "error": "context pointer cannot be materialized"}
        with self._lock:
            current_key = self._compiled_by_scope.get(str(entry.get("scope_key") or ""))
        if current_key != str(reuse_key):
            return {"success": False, "status": "stale", "freshness": "stale", "error": "context pointer cannot be materialized", "reuse_key": reuse_key}
        if float(entry.get("fresh_until") or 0.0) <= time.time():
            return {"success": False, "status": "stale", "freshness": "stale", "error": "context pointer expired", "reuse_key": reuse_key}
        result = artifact_store.get(
            str(entry["artifact_id"]), offset=offset, max_chars=max_chars, tenant=tenant
        )
        if not isinstance(result, dict) or not result.get("success"):
            return {"success": False, "status": "stale", "freshness": "stale", "error": "context artifact expired or unavailable", "reuse_key": reuse_key}
        return {
            **result,
            "status": "materialized",
            "freshness": "fresh",
            "fresh_until": entry["fresh_until"],
            "reuse_key": reuse_key,
        }


def _safe_nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _optional_nonnegative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
        if parsed < 0 or float(value) != parsed:
            return None
        return parsed
    except (TypeError, ValueError, OverflowError):
        return None
