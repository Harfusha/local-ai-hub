"""Git-native, bounded knowledge records using the existing repo-plan journal.

This initial contract keeps declarations and file freshness separate. A repo
record does not authenticate a person, create a receipt or authorize a write.
The repository root must already be authorized by the calling service.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from itertools import islice
from pathlib import Path
from typing import Any
from uuid import UUID

from .evidence import EvidenceStore, _evidence_path_under_root, _valid_portable_locator
from .project_config import resolve_project_config
from .repo_plan.schema_validation import RepoPlanValidationError, parse_plan_json
from .repo_plan.storage import RepoPlanStorage
from .secret_scan_config import _SECRET_SCAN_PATTERNS
from .source_slice import read_source_slice

_MAX_BYTES = 10000
_MAX_RECORDS = 128
_ID = re.compile(r"[a-z][a-z0-9_.-]{0,95}")
_MANIFEST = ".local-ai-hub/project.json"
_DIR = ".local-ai-hub/knowledge"
_KINDS = {
    "requirement": "requirements", "process": "processes", "entity": "entities",
    "feature": "features", "business_rule": "rules", "observation": "observations",
    "integration": "integrations", "glossary": "glossary", "runbook": "runbooks",
    "finding": "findings", "review": "reviews",
}


def _invalid() -> RepoPlanValidationError:
    return RepoPlanValidationError("Invalid or unsupported repository knowledge record")


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None and not value.endswith(".")


def _project_id(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _text(value: Any, maximum: int) -> bool:
    return isinstance(value, str) and 0 < len(value) <= maximum and all(
        c.isprintable() or c in "\n\t" for c in value
    )


def _path_for(kind: Any, record_id: Any) -> str:
    if not isinstance(kind, str) or kind not in _KINDS or not _identifier(record_id):
        raise _invalid()
    return f"{_DIR}/{_KINDS[kind]}/{record_id}.json"


def validate_knowledge_file(rel_path: str, data: bytes) -> dict[str, Any]:
    """Strict envelope and size validation before save, load and journal recovery."""
    if not isinstance(data, bytes) or not data or len(data) > _MAX_BYTES:
        raise _invalid()
    record = parse_plan_json(data)
    if type(record.get("schema_version")) is not int or record["schema_version"] != 1:
        raise _invalid()
    if not _project_id(record.get("project_id")):
        raise _invalid()
    if rel_path == _MANIFEST:
        if set(record) != {"schema_version", "project_id", "mode"} or record.get("mode") not in (
            "shared", "review_only", "read_only"
        ):
            raise _invalid()
        return record
    if set(record) != {"schema_version", "project_id", "kind", "id", "payload", "provenance", "evidence", "relations"}:
        raise _invalid()
    if _path_for(record["kind"], record["id"]) != rel_path:
        raise _invalid()
    payload = record["payload"]
    provenance = record["provenance"]
    if not isinstance(payload, dict) or not {"title", "statement", "layer"} <= set(payload):
        raise _invalid()
    if set(payload) - {"title", "statement", "layer", "claim_key", "claim_value"}:
        raise _invalid()
    if not _text(payload["title"], 160) or not _text(payload["statement"], 2000):
        raise _invalid()
    if payload["layer"] not in ("intended", "observed", "interpretation"):
        raise _invalid()
    if ("claim_key" in payload) != ("claim_value" in payload):
        raise _invalid()
    if "claim_key" in payload and (
        not _identifier(payload["claim_key"]) or type(payload["claim_value"]) is not bool
    ):
        raise _invalid()
    if not isinstance(provenance, dict) or set(provenance) - {"origin_kind", "review_ref"}:
        raise _invalid()
    if provenance.get("origin_kind") not in ("human_review", "manual", "deterministic", "model"):
        raise _invalid()
    if "review_ref" in provenance and not _identifier(provenance["review_ref"]):
        raise _invalid()
    evidence = record["evidence"]
    if not isinstance(evidence, list) or len(evidence) > 16 or any(
        not _valid_portable_locator(item) for item in evidence
    ):
        raise _invalid()
    relations = record["relations"]
    if not isinstance(relations, list) or len(relations) > 32:
        raise _invalid()
    for relation in relations:
        if not isinstance(relation, dict) or set(relation) != {"type", "target_kind", "target_id"}:
            raise _invalid()
        if not _identifier(relation["type"]):
            raise _invalid()
        _path_for(relation["target_kind"], relation["target_id"])
    # Reuse recognized secret patterns. This is not a guarantee that text is
    # shareable; the caller still owns privacy approval before publication.
    text = json.dumps(record, ensure_ascii=False)
    if any(pattern.search(text) for _, _, pattern, _ in _SECRET_SCAN_PATTERNS):
        raise RepoPlanValidationError("Repository knowledge contains a recognized secret pattern")
    return record


def _encode(record: Mapping[str, Any]) -> bytes:
    try:
        return (json.dumps(dict(record), sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise _invalid() from exc


class RepoKnowledgeStore:
    """Read and explicitly edit shared records in the current checkout only."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise _invalid()
        resolution = resolve_project_config(self.root)
        if resolution.error_codes:
            raise RepoPlanValidationError("Project configuration unavailable")
        settings = resolution.settings.workspace
        # Initial format supports the canonical default namespace only. Do not
        # silently route a customized workspace into another record store.
        if settings.knowledge_dir != _DIR or settings.intents_dir != ".local-ai-hub/local/intents":
            raise RepoPlanValidationError("Custom knowledge workspace is not yet supported")
        self.storage = RepoPlanStorage(self.root, intents_dir=settings.intents_dir)

    def _read(self, rel: str) -> tuple[dict[str, Any], str]:
        path = _evidence_path_under_root(str(self.root), rel, strict=True)
        if path is None:
            raise FileNotFoundError("Knowledge file unavailable")
        result = read_source_slice(str(self.root), rel, line_end=200, max_chars=12000)
        if (
            result.get("success") is not True or result.get("complete") is not True
            or result.get("total_lines", 201) > 200 or result.get("relative_path") != rel
            or _evidence_path_under_root(str(self.root), rel, strict=True) != path
        ):
            raise _invalid()
        raw = result["text"].encode("utf-8")
        if hashlib.sha256(raw).hexdigest() != result["file_sha256"]:
            raise _invalid()
        return validate_knowledge_file(rel, raw), result["file_sha256"]

    def manifest(self) -> tuple[dict[str, Any], str]:
        return self._read(_MANIFEST)

    def bootstrap(
        self, project_id: str, *, mode: str, owner: str, idempotency_key: str,
        authorize_write: Callable[[], bool],
    ) -> dict[str, Any]:
        """Explicit initial identity creation; never adopt or overwrite an identity."""
        data = _encode({"schema_version": 1, "project_id": project_id, "mode": mode})
        return self.storage.save_knowledge_file(
            _MANIFEST, data, expected_revision="", owner=owner,
            idempotency_key=idempotency_key, lease_check_fn=authorize_write,
        )

    def get(self, kind: str, record_id: str) -> dict[str, Any]:
        manifest, revision = self.manifest()
        record, record_revision = self._read(_path_for(kind, record_id))
        if record["project_id"] != manifest["project_id"]:
            raise _invalid()
        # Reject a change of manifest while reading, including a checkout.
        if self.manifest()[1] != revision:
            raise _invalid()
        states = [EvidenceStore.portable_source_status(ref, root=str(self.root)) for ref in record["evidence"]]
        freshness = (
            "stale" if "stale" in states else
            "unknown" if not states or any(state != "matching_file" for state in states) else
            "matching_sources"
        )
        return {"record": record, "revision": record_revision, "freshness": freshness,
                "authority": "repository_declaration", "evidence_statuses": states}

    def save(
        self, record: Mapping[str, Any], *, expected_revision: str, owner: str,
        idempotency_key: str, authorize_write: Callable[[], bool],
    ) -> dict[str, Any]:
        """Explicit publication through the same journal as plans.

        Authorization is external to Git content. This API is intentionally
        internal until the HTTP/MCP actor and privacy policy is wired.
        """
        manifest, manifest_revision = self.manifest()
        data = _encode(record)
        rel = _path_for(record.get("kind"), record.get("id"))
        clean = validate_knowledge_file(rel, data)
        if clean["project_id"] != manifest["project_id"] or manifest["mode"] == "read_only":
            raise _invalid()

        def fence() -> bool:
            try:
                return authorize_write() is True and self.manifest()[1] == manifest_revision
            except (OSError, RepoPlanValidationError):
                return False

        return self.storage.save_knowledge_file(
            rel, data, expected_revision=expected_revision, owner=owner,
            idempotency_key=idempotency_key, lease_check_fn=fence,
        )

    def catalog(self) -> dict[str, Any]:
        """Bounded scan; missing, invalid and truncated inventory is not success."""
        manifest, manifest_revision = self.manifest()
        records: list[dict[str, Any]] = []
        issues: list[dict[str, str]] = []
        complete = True
        remaining = _MAX_RECORDS
        for kind, directory in _KINDS.items():
            parent = self.root / _DIR / directory
            if not parent.exists() and not parent.is_symlink():
                continue
            if _evidence_path_under_root(str(self.root), f"{_DIR}/{directory}", strict=True) != parent or not parent.is_dir():
                issues.append({"kind": kind, "code": "unsafe_directory"})
                complete = False
                continue
            try:
                entries = list(islice(parent.iterdir(), remaining + 1))
            except OSError:
                issues.append({"kind": kind, "code": "directory_unavailable"})
                complete = False
                continue
            if len(entries) > remaining:
                complete = False
                break
            remaining -= len(entries)
            for entry in sorted(entries):
                if entry.suffix != ".json" or not _identifier(entry.stem):
                    issues.append({"kind": kind, "code": "unexpected_entry"})
                    complete = False
                    continue
                try:
                    records.append(self.get(kind, entry.stem))
                except (OSError, RepoPlanValidationError):
                    issues.append({"kind": kind, "code": "invalid_or_unavailable_record"})
                    complete = False
        if self.manifest()[1] != manifest_revision:
            raise _invalid()
        return {"project_id": manifest["project_id"], "mode": manifest["mode"],
                "complete": complete, "records": records, "issues": issues}


def detect_declared_claim_conflicts(catalog: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Only compare explicitly structured booleans; never infer from prose.

    A result is a review candidate, not a verified defect or a claim about
    actual runtime behavior. Stale sources cannot support a current candidate.
    """
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for item in catalog["records"]:
        if item["freshness"] != "matching_sources":
            continue
        record = item["record"]
        payload = record["payload"]
        if payload.get("claim_key") and payload["layer"] in ("intended", "observed"):
            groups.setdefault(payload["claim_key"], {}).setdefault(payload["layer"], []).append(record)
    findings = []
    for claim, layers in sorted(groups.items()):
        for intended in layers.get("intended", []):
            for observed in layers.get("observed", []):
                if intended["payload"]["claim_value"] != observed["payload"]["claim_value"]:
                    findings.append({"type": "declared_claim_conflict", "claim_key": claim,
                                     "intended_id": intended["id"], "observed_id": observed["id"],
                                     "status": "candidate"})
                    if len(findings) >= 128:
                        return findings
    return findings

def query_declared_knowledge(catalog: Mapping[str, Any], query: str, *, limit: int = 8) -> dict[str, Any]:
    """Bounded lexical discovery over curated records; not a semantic verifier."""
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise ValueError("A bounded knowledge query is required")
    if type(limit) is not int or not 1 <= limit <= 32:
        raise ValueError("Knowledge limit must be between 1 and 32")
    terms = set(re.findall(r"\w+", query.casefold())[:64])
    ranked = []
    for item in catalog["records"]:
        record = item["record"]
        payload = record["payload"]
        words = set(re.findall(r"\w+", " ".join((
            record["id"], payload["title"], payload["statement"], payload.get("claim_key", "")
        )).casefold()))
        score = len(terms & words)
        if score:
            ranked.append((score, record["kind"], record["id"], item))
    ranked.sort(key=lambda entry: (-entry[0], entry[1], entry[2]))
    return {
        "project_id": catalog["project_id"], "complete": catalog["complete"],
        "issues": catalog["issues"], "match_count": len(ranked),
        "records": [entry[3] for entry in ranked[:limit]],
        "truncated": len(ranked) > limit,
        "answer_status": "declarations_only",
    }
