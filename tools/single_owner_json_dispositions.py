"""Explicit, source-pinned JSON dispositions for offline conversion only."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping


class DispositionError(ValueError):
    """Manifest, source pin, or transformation did not satisfy its contract."""


_RETIRED_KEYS = frozenset(
    {"tenant", "tenant_id", "tenant_identity", "tenant_key", "tenant_scope", "tenant_partition"}
)
_PROVENANCE_SELECTOR = ("agent_state", "agent_memory_records", "provenance")
_TASK_CONTEXT_SELECTOR = ("agent_state", "agent_tasks_projection", "context")
_WORK_PAYLOAD_SELECTOR = ("work_orchestrator", "work_orders", "payload_json")
_ASYNC_PAYLOAD_SELECTOR = ("async_jobs", "async_jobs", "payload_json")
_TELEMETRY_SELECTOR = ("telemetry", "snapshots", "metrics_json")
_ASYNC_RETIRED_KEYS = frozenset({"tenant", "tenant_id", "tenant_key", "tenant_scope"})
_TELEMETRY_RETIRED_KEYS = _ASYNC_RETIRED_KEYS
_TELEMETRY_CONTAINERS = frozenset({"context", "metadata", "metrics", "provenance", "scope"})
_TASK_CONTEXT_FIELDS = frozenset({"repository_id", "clone_id", "worktree_id", "branch", "task_id", "session_id"})
_TASK_SCOPE_POINTERS = {
    ("agent_state", "agent_tasks_projection", "checkpoint"): "/state_data/_agent_task_scope",
    ("agent_state", "agent_snapshots", "state"): "/checkpoint/state_data/_agent_task_scope",
}
_MEMORY_CONTEXT_POINTERS = {
    ("agent_state", "agent_tasks_projection", "checkpoint"): "/state_data/memory_context",
    ("agent_state", "agent_snapshots", "state"): "/checkpoint/state_data/memory_context",
}
_MEMORY_CONTEXT_FIELDS = frozenset({"root", "coordination_id", "task_id", "session_id", "clone_id", "worktree_id", "branch"})
_HEX256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_MANIFEST_BYTES = 8 * 1024 * 1024
_MAX_ENTRIES = 100_000
_MAX_OPERATIONS = 128
_MAX_POINTER_DEPTH = 32
_MAX_RECORD_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class Disposition:
    store: str
    table: str
    column: str
    key: str
    raw_sha256: str
    operations: tuple[dict[str, Any], ...]
    token: str


@dataclass(frozen=True)
class DispositionManifest:
    source_sha256: str
    entries: tuple[Disposition, ...]
    _seal: object = field(default=None, repr=False, compare=False)


_MANIFEST_SEAL = object()


def _pairs_no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DispositionError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise DispositionError(f"non-finite JSON number is forbidden: {value}")


def _finite_float(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        raise DispositionError("non-finite JSON number is forbidden")
    return parsed


def _object(value, label):
    if not isinstance(value, Mapping) or any(not isinstance(k, str) for k in value):
        raise DispositionError(f"{label} must be a JSON object")
    return value


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value):
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _text(value, label, *, limit=512):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > limit
        or "\x00" in value
        or value != value.strip()
    ):
        raise DispositionError(f"{label} must be nonempty text within bound")
    return value


def _pointer(pointer, selector):
    if not isinstance(pointer, str) or not pointer.startswith("/") or len(pointer) > 2048:
        raise DispositionError("remove operation needs bounded absolute JSON pointer")
    parts = pointer[1:].split("/")
    if len(parts) > _MAX_POINTER_DEPTH:
        raise DispositionError("JSON pointer exceeds depth bound")
    decoded = []
    for part in parts:
        if re.search(r"~(?![01])", part):
            raise DispositionError("invalid JSON pointer escape")
        decoded.append(part.replace("~1", "/").replace("~0", "~"))
    key = decoded[-1]
    allowed = (
        selector == _PROVENANCE_SELECTOR and len(decoded) == 1 and key in _RETIRED_KEYS
        or selector == _TASK_CONTEXT_SELECTOR and len(decoded) == 1 and key in _RETIRED_KEYS
        or selector == _WORK_PAYLOAD_SELECTOR and tuple(decoded) == ("tenant",)
        or selector == _ASYNC_PAYLOAD_SELECTOR and len(decoded) == 1 and key in _ASYNC_RETIRED_KEYS
        or selector == _TELEMETRY_SELECTOR
        and key in _TELEMETRY_RETIRED_KEYS
        and (len(decoded) == 1 or len(decoded) == 2 and decoded[0] in _TELEMETRY_CONTAINERS)
    )
    if not allowed:
        raise DispositionError("remove operation path is not registered for this store/table/column")
    return tuple(decoded)


def load_dispositions(path, *, source_sha256):
    """Load immutable manifest, pinned to exact source bytes."""
    if not isinstance(source_sha256, str) or not _HEX256.fullmatch(source_sha256):
        raise DispositionError("source_sha256 must be lowercase SHA-256")
    with Path(path).open("rb") as stream:
        raw = stream.read(_MAX_MANIFEST_BYTES + 1)
    if len(raw) > _MAX_MANIFEST_BYTES:
        raise DispositionError("manifest exceeds size bound")
    try:
        parsed = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise DispositionError("manifest must be valid UTF-8 JSON") from exc
    root = _object(parsed, "manifest")
    if set(root) != {"version", "source_sha256", "entries"} or root["version"] != 1:
        raise DispositionError("manifest requires exact version 1 fields")
    if root["source_sha256"] != source_sha256:
        raise DispositionError("manifest source SHA-256 pin mismatch")
    rows = root["entries"]
    if not isinstance(rows, list) or len(rows) > _MAX_ENTRIES:
        raise DispositionError("manifest entries must be bounded array")
    entries, selectors = [], set()
    for pos, row in enumerate(rows):
        row = _object(row, f"entry {pos}")
        if set(row) != {"store", "table", "column", "key", "raw_sha256", "operations"}:
            raise DispositionError(f"entry {pos} has unknown or missing fields")
        store = _text(row["store"], "store")
        table = _text(row["table"], "table")
        column = _text(row["column"], "column")
        key = _text(row["key"], "key", limit=4096)
        digest = row["raw_sha256"]
        if not isinstance(digest, str) or not _HEX256.fullmatch(digest):
            raise DispositionError(f"entry {pos} raw_sha256 must be lowercase SHA-256")
        selector = (store, table, column, key)
        if selector in selectors:
            raise DispositionError(f"duplicate record selector at entry {pos}")
        selectors.add(selector)
        ops = row["operations"]
        if not isinstance(ops, list) or not 1 <= len(ops) <= _MAX_OPERATIONS:
            raise DispositionError(f"entry {pos} operations must be nonempty and bounded")
        seen_ops = set()
        frozen_ops = []
        for op_index, raw_op in enumerate(ops):
            op = _object(raw_op, f"entry {pos} operation {op_index}")
            kind = op.get("op")
            if kind == "remove_json_pointer":
                if set(op) != {"op", "pointer"}:
                    raise DispositionError("remove operation has unknown or missing fields")
                decoded = _pointer(op["pointer"], (store, table, column))
                identity = (kind, decoded)
                frozen_ops.append(MappingProxyType({"op": kind, "pointer_parts": decoded}))
            elif kind == "upgrade_task_scope":
                expected_pointer = _TASK_SCOPE_POINTERS.get((store, table, column))
                if set(op) != {"op", "pointer", "expected_old", "repo_root"} or op["pointer"] != expected_pointer:
                    raise DispositionError("task scope operation requires exact pointer and fields")
                old = _object(op["expected_old"], "expected old task scope")
                if type(old.get("version")) is not int or old.get("version") != 1 or not isinstance(old.get("repo_root"), str):
                    raise DispositionError("task scope conversion requires exact version 1 root metadata")
                if set(old) - _RETIRED_KEYS != {"version", "repo_root"}:
                    raise DispositionError("task scope old object contains unsupported nonretired fields")
                repo_root = _canonical_historical_root(op["repo_root"])
                old_root = _canonical_historical_root(old["repo_root"])
                if old_root != repo_root:
                    raise DispositionError("task scope root must match the stored canonical physical root")
                identity = (kind, op["pointer"])
                frozen_ops.append(MappingProxyType({"op": kind, "pointer": op["pointer"], "expected_old": _freeze(dict(old)), "repo_root": repo_root}))
            elif kind == "upgrade_memory_context_v2":
                expected_pointer = _MEMORY_CONTEXT_POINTERS.get((store, table, column))
                if set(op) != {"op", "pointer", "expected_old", "context"} or op["pointer"] != expected_pointer:
                    raise DispositionError("memory context operation requires exact pointer and fields")
                old = _object(op["expected_old"], "expected old memory context")
                if type(old.get("schema_version")) is not int or old.get("schema_version") != 1:
                    raise DispositionError("memory context conversion requires schema version 1")
                required_old = {"schema_version", "instruction", "items", "warnings", "estimated_tokens"}
                if set(old) not in (required_old, required_old | {"tenant_key"}):
                    raise DispositionError("memory context v1 object contains unsupported fields")
                if type(old["instruction"]) is not str or not isinstance(old["items"], list) or not isinstance(old["warnings"], list):
                    raise DispositionError("memory context v1 fields are malformed")
                if type(old["estimated_tokens"]) is not int or old["estimated_tokens"] < 0:
                    raise DispositionError("memory context token estimate is malformed")
                context = _object(op["context"], "v2 memory context")
                if set(context) != _MEMORY_CONTEXT_FIELDS or any(type(context[name]) is not str for name in _MEMORY_CONTEXT_FIELDS):
                    raise DispositionError("v2 memory context must preserve the exact canonical identity fields")
                frozen_ops.append(MappingProxyType({"op": kind, "pointer": op["pointer"], "expected_old": _freeze(dict(old)), "context": _freeze(dict(context))}))
                identity = (kind, op["pointer"])
            elif kind == "archive_memory_context":
                expected_pointer = _MEMORY_CONTEXT_POINTERS.get((store, table, column))
                if set(op) != {"op", "pointer", "expected_old", "reason"} or op["pointer"] != expected_pointer:
                    raise DispositionError("memory context archive requires exact pointer and fields")
                old = _object(op["expected_old"], "archived memory context")
                required_old = {"schema_version", "instruction", "items", "warnings", "estimated_tokens"}
                if (type(old.get("schema_version")) is not int or old.get("schema_version") != 1
                        or set(old) not in (required_old, required_old | {"tenant_key"})
                        or type(old.get("instruction")) is not str or not isinstance(old.get("items"), list)
                        or not isinstance(old.get("warnings"), list) or type(old.get("estimated_tokens")) is not int
                        or old["estimated_tokens"] < 0):
                    raise DispositionError("archived memory context differs from the exact legacy v1 envelope")
                reason = _text(op["reason"], "archive reason", limit=2048)
                frozen_ops.append(MappingProxyType({"op": kind, "pointer": op["pointer"],
                                                    "expected_old": _freeze(dict(old)), "reason": reason}))
                identity = (kind, op["pointer"])
            else:
                raise DispositionError(f"unsupported operation: {kind!r}")
            if identity in seen_ops:
                raise DispositionError(f"duplicate or conflicting operation at entry {pos}")
            seen_ops.add(identity)
        if any(op["op"] == "upgrade_task_scope" for op in frozen_ops) and any(
            op["op"] == "remove_json_pointer" and op["pointer_parts"][-1:] == ("_agent_task_scope",)
            for op in frozen_ops
        ):
            raise DispositionError("task scope migration conflicts with separate scope-key removal")
        memory_ops = [op["op"] for op in frozen_ops if op["op"] in {"upgrade_memory_context_v2", "archive_memory_context"}]
        if len(memory_ops) > 1:
            raise DispositionError("memory context upgrade and archive dispositions conflict")
        token = hashlib.sha256(f"{store}\0{table}\0{column}\0{key}\0{digest}".encode()).hexdigest()
        entries.append(Disposition(store, table, column, key, digest, tuple(frozen_ops), token))
    return DispositionManifest(source_sha256, tuple(entries), _MANIFEST_SEAL)


def _canonical_root(value):
    if (not isinstance(value, str) or not value or value != value.strip()
            or any(ord(char) < 32 for char in value) or not Path(value).is_absolute()):
        raise DispositionError("task scope root must be absolute")
    try:
        candidate = Path(value)
        canonical = str(candidate.resolve(strict=True))
    except (OSError, RuntimeError) as exc:
        raise DispositionError("task scope root must resolve to existing physical root") from exc
    if canonical != value or not candidate.is_dir():
        raise DispositionError("task scope root must already be canonical")
    if any(parent.is_symlink() for parent in (candidate, *candidate.parents)):
        raise DispositionError("task scope root cannot include symlinked directories")
    return canonical


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise DispositionError("historical task root path cannot be inspected safely") from exc
    reparse_flag = getattr(os, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & reparse_flag)


def _canonical_historical_root(value):
    """Preserve an exact historical absolute root without granting its authority."""
    if (type(value) is not str or not value or value != value.strip()
            or any(ord(char) < 32 for char in value) or not Path(value).is_absolute()):
        raise DispositionError("historical task scope root must be canonical and absolute")
    candidate = Path(value)
    try:
        canonical = str(candidate.resolve(strict=False))
    except (OSError, RuntimeError) as exc:
        raise DispositionError("historical task scope root cannot be canonicalized") from exc
    if canonical != value:
        raise DispositionError("historical task scope root must retain its exact canonical spelling")
    if any(_is_reparse_or_symlink(parent) for parent in (candidate, *candidate.parents)):
        raise DispositionError("historical task scope root cannot include a symlink or reparse alias")
    if candidate.exists() and not candidate.is_dir():
        raise DispositionError("historical task scope root must identify a directory when it exists")
    return value


def _require_checkpoint_envelope(value):
    expected = {"phase", "next_action", "affected_paths", "evidence_ids", "blockers", "state_data"}
    if not isinstance(value, dict) or set(value) != expected:
        raise DispositionError("checkpoint scope conversion requires TaskCheckpoint serialization")
    if any(not isinstance(value[name], str) for name in ("phase", "next_action")):
        raise DispositionError("TaskCheckpoint text fields invalid")
    if any(not isinstance(value[name], list) or any(not isinstance(item, str) for item in value[name]) for name in ("affected_paths", "evidence_ids", "blockers")):
        raise DispositionError("TaskCheckpoint sequence fields invalid")
    if not isinstance(value["state_data"], dict):
        raise DispositionError("TaskCheckpoint state_data invalid")


def _require_scope_context_envelope(value):
    if not isinstance(value, dict) or not _TASK_CONTEXT_FIELDS.issubset(value):
        raise DispositionError("context tenant disposition requires ScopeContext serialization")
    if set(value) - _TASK_CONTEXT_FIELDS - _RETIRED_KEYS:
        raise DispositionError("ScopeContext contains unsupported context fields")
    if any(not isinstance(value[name], str) for name in _TASK_CONTEXT_FIELDS):
        raise DispositionError("ScopeContext fields must remain strings")
    if any(not isinstance(value[name], str) for name in _RETIRED_KEYS.intersection(value)):
        raise DispositionError("retired ScopeContext fields must be strings")


def _require_task_state_envelope(value):
    required = {
        "task_id", "status", "owner", "lease_id", "contract", "context", "checkpoint",
        "verification_receipts", "created_at", "updated_at", "heartbeat_expires_at", "stale", "stale_reason",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise DispositionError("snapshot scope conversion requires serialized TaskState envelope")
    if not isinstance(value["task_id"], str) or not value["task_id"] or "\x00" in value["task_id"]:
        raise DispositionError("TaskState task_id invalid")
    statuses = {"draft", "planned", "active", "verifying", "completed", "waiting", "blocked", "failed", "cancelled", "abandoned"}
    if not isinstance(value["status"], str) or value["status"] not in statuses:
        raise DispositionError("TaskState status invalid")
    if any(not isinstance(value[name], str) for name in ("owner", "lease_id", "stale_reason")) or not isinstance(value["stale"], bool):
        raise DispositionError("TaskState ownership or stale fields invalid")
    contract = value["contract"]
    contract_fields = {"goal", "description", "acceptance_criteria", "scope", "non_goals", "constraints", "risk_profile", "slo_profile"}
    if not isinstance(contract, dict) or set(contract) != contract_fields:
        raise DispositionError("TaskState contract serialization invalid")
    if any(not isinstance(contract[name], str) for name in ("goal", "description", "scope", "risk_profile")) or not contract["goal"]:
        raise DispositionError("TaskState contract identity invalid")
    if any(not isinstance(contract[name], list) or any(not isinstance(item, str) for item in contract[name]) for name in ("acceptance_criteria", "non_goals", "constraints")) or not isinstance(contract["slo_profile"], dict):
        raise DispositionError("TaskState contract fields invalid")
    context = value["context"]
    context_fields = {"repository_id", "clone_id", "worktree_id", "branch", "task_id", "session_id"}
    if not isinstance(context, dict) or set(context) != context_fields or any(not isinstance(item, str) for item in context.values()):
        raise DispositionError("TaskState context serialization invalid")
    _require_checkpoint_envelope(value["checkpoint"])
    receipts = value["verification_receipts"]
    if not isinstance(receipts, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in receipts.items()):
        raise DispositionError("TaskState verification receipts invalid")
    for name in ("created_at", "updated_at", "heartbeat_expires_at"):
        number = value[name]
        if isinstance(number, bool) or not isinstance(number, (int, float)) or number < 0 or not math.isfinite(number):
            raise DispositionError("TaskState timestamp invalid")


def transform_json(raw, *, store, table, key, column, manifest):
    """Apply only exact record and raw-byte-pinned operations; return provenance."""
    if not isinstance(manifest, DispositionManifest) or manifest._seal is not _MANIFEST_SEAL:
        raise DispositionError("manifest must come from load_dispositions")
    if not isinstance(raw, str):
        raise DispositionError("raw JSON must be text")
    try:
        raw_bytes = raw.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise DispositionError("raw JSON must be valid UTF-8 text") from exc
    if len(raw_bytes) > _MAX_RECORD_BYTES:
        raise DispositionError("JSON record exceeds size bound")
    selector_digest = hashlib.sha256(raw_bytes).hexdigest()
    entry = next((item for item in manifest.entries if (item.store, item.table, item.column, item.key, item.raw_sha256) == (store, table, column, key, selector_digest)), None)
    if entry is None:
        return raw, {"matched": False, "source_sha256": manifest.source_sha256}
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except DispositionError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise DispositionError("pinned JSON record is invalid or has duplicate members") from exc
    removed = []
    if (entry.store, entry.table, entry.column) == _TASK_CONTEXT_SELECTOR:
        _require_scope_context_envelope(value)
    for operation in entry.operations:
        if operation["op"] == "remove_json_pointer":
            node = value
            parts = operation["pointer_parts"]
            for part in parts[:-1]:
                if not isinstance(node, dict) or part not in node:
                    raise DispositionError("pinned JSON pointer parent missing")
                node = node[part]
            leaf = parts[-1]
            if not isinstance(node, dict) or leaf not in node:
                raise DispositionError("pinned JSON pointer target missing")
            removed.append({"pointer": "/" + "/".join(parts), "value": node.pop(leaf)})
        elif operation["op"] == "upgrade_task_scope":
            selector = (entry.store, entry.table, entry.column)
            if selector == ("agent_state", "agent_tasks_projection", "checkpoint"):
                _require_checkpoint_envelope(value)
            elif selector == ("agent_state", "agent_snapshots", "state"):
                _require_task_state_envelope(value)
            old = operation["expected_old"]
            old_value = _thaw(old)
            parts = tuple(operation["pointer"].split("/"))[1:]
            node = value
            for part in parts[:-1]:
                if not isinstance(node, dict) or part not in node:
                    raise DispositionError("task scope metadata parent missing")
                node = node[part]
            leaf = parts[-1]
            if not isinstance(node, dict) or node.get(leaf) != old_value:
                raise DispositionError("task scope object differs from exact pinned old object")
            new_scope = dict(old_value)
            for retired in _RETIRED_KEYS:
                if retired in new_scope:
                    removed.append({"pointer": f"{operation['pointer']}/{retired}", "value": new_scope.pop(retired)})
            new_scope.update({"version": 2, "repo_root": operation["repo_root"]})
            node[leaf] = new_scope
        elif operation["op"] == "upgrade_memory_context_v2":
            selector = (entry.store, entry.table, entry.column)
            if selector == ("agent_state", "agent_tasks_projection", "checkpoint"):
                _require_checkpoint_envelope(value)
            elif selector == ("agent_state", "agent_snapshots", "state"):
                _require_task_state_envelope(value)
            parts = tuple(operation["pointer"].split("/"))[1:]
            node = value
            for part in parts[:-1]:
                if not isinstance(node, dict) or part not in node:
                    raise DispositionError("memory context parent missing")
                node = node[part]
            leaf = parts[-1]
            old_value = _thaw(operation["expected_old"])
            if not isinstance(node, dict) or node.get(leaf) != old_value:
                raise DispositionError("memory context differs from exact pinned v1 object")
            context = _thaw(operation["context"])
            scope = node.get("_agent_task_scope")
            if not isinstance(scope, dict) or type(scope.get("version")) is not int or scope.get("version") != 2:
                raise DispositionError("memory context migration requires an explicitly upgraded v2 task scope")
            if context["root"] != scope.get("repo_root"):
                raise DispositionError("memory context root must equal the explicit v2 task scope root")
            expected_task_id = value.get("task_id") if selector == ("agent_state", "agent_snapshots", "state") else entry.key
            if context["task_id"] != expected_task_id:
                raise DispositionError("memory context task_id must match the pinned task record key")
            new_value = dict(old_value)
            new_value.pop("tenant_key", None)
            new_value["schema_version"] = 2
            new_value["context"] = context
            node[leaf] = new_value
            if "tenant_key" in old_value:
                removed.append({"pointer": f"{operation['pointer']}/tenant_key", "value": old_value["tenant_key"]})
        elif operation["op"] == "archive_memory_context":
            selector = (entry.store, entry.table, entry.column)
            if selector == ("agent_state", "agent_tasks_projection", "checkpoint"):
                _require_checkpoint_envelope(value)
            elif selector == ("agent_state", "agent_snapshots", "state"):
                _require_task_state_envelope(value)
            parts = tuple(operation["pointer"].split("/"))[1:]
            node = value
            for part in parts[:-1]:
                if not isinstance(node, dict) or part not in node:
                    raise DispositionError("memory context archive parent missing")
                node = node[part]
            leaf = parts[-1]
            old_value = _thaw(operation["expected_old"])
            if not isinstance(node, dict) or node.get(leaf) != old_value:
                raise DispositionError("memory context differs from exact pinned v1 archive object")
            removed.append({"pointer": operation["pointer"], "value": node.pop(leaf)})
        else:
            raise DispositionError("manifest contains an unsupported operation")
    try:
        serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        serialized_bytes = serialized.encode("utf-8")
    except (RecursionError, UnicodeEncodeError) as exc:
        raise DispositionError("transformed JSON exceeds supported encoding or depth") from exc
    if len(serialized_bytes) > _MAX_RECORD_BYTES:
        raise DispositionError("transformed JSON exceeds size bound")
    provenance = {
        "matched": True,
        "manifest_entry": entry.token,
        "source_sha256": manifest.source_sha256,
        "store": entry.store,
        "table": entry.table,
        "column": entry.column,
        "key": entry.key,
        "old_raw_sha256": entry.raw_sha256,
        "new_raw_sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        "operations": tuple(op["op"] for op in entry.operations),
        "removed_count": len(removed),
        "removed_values": tuple(removed),
    }
    archive = next((op for op in entry.operations if op["op"] == "archive_memory_context"), None)
    if archive is not None:
        provenance["archive_reason"] = archive["reason"]
    return serialized, provenance


def require_all_dispositions_used(manifest, provenance_records):
    """Reject a conversion whose manifest entries were unused or reused."""
    expected = [entry.token for entry in manifest.entries]
    used = [row.get("manifest_entry") for row in provenance_records if row.get("matched") is True]
    if len(used) != len(set(used)) or set(used) != set(expected):
        raise DispositionError("manifest contains unused or multiply used record dispositions")
