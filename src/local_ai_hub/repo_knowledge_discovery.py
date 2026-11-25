"""Bounded publication of source-grounded *candidate* file-card observations.

This reuses the current preprocessing card, source reader and plan journal.
A machine-side exact checkout allowlist is mandatory. Git metadata alone
never authorizes publication. No new model calls, raw quotes or task receipts.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from .evidence import EvidenceStore, _evidence_path_under_root
from .repo_knowledge import RepoKnowledgeStore, _digest_value, _encode, _path_for, validate_knowledge_file
from .repo_plan.schema_validation import RepoPlanError
from .repository_scope import RepositoryScopeError, authorized_repository_root, canonical_repository_root
from .source_slice import read_source_slice

_GENERATOR = "preprocess-card-v1"
_BUSINESS = re.compile(
    r"\b(?:orders?|bookings?|reservations?|payments?|paid|refunds?|invoices?|"
    r"customers?|subscriptions?|pricing|discounts?|checkout|fulfillment|"
    r"objednáv\w*|rezervac\w*|platb\w*|faktur\w*|zákazník\w*)\b", re.IGNORECASE
)


def auto_publish_authorized(config: Mapping[str, Any], root: str) -> bool:
    security = config.get("security", {})
    if not isinstance(security, Mapping):
        return False
    allowed = security.get("knowledge_auto_publish_roots", [])
    if not isinstance(allowed, list) or not allowed or len(allowed) > 32:
        return False
    try:
        actual = canonical_repository_root(authorized_repository_root(config, root))
        # Exact checkout identity, not an inherited ancestor grant.
        return any(actual == canonical_repository_root(entry) for entry in allowed)
    except (RepositoryScopeError, OSError, ValueError):
        return False


def _generation_digest(record: Mapping[str, Any]) -> str:
    copied = dict(record)
    provenance = dict(copied["provenance"])
    provenance.pop("generated_digest", None)
    copied["provenance"] = provenance
    return _digest_value(copied)


def candidate_from_file_card(
    store: RepoKnowledgeStore, path: str, source_digest: str, card: Mapping[str, Any], model: str,
) -> dict[str, Any] | None:
    """Only use exact source-matching quotes attached to business-related card fields."""
    from .repo_task_handoff import _safe_relative_path

    if not _safe_relative_path(path) or path.startswith(".local-ai-hub/"):
        return None
    if model.startswith("deterministic-") or not isinstance(card, Mapping):
        return None
    evidence = card.get("evidence")
    if not isinstance(evidence, list):
        return None
    candidates = []
    for item in evidence[:32]:
        if not isinstance(item, Mapping) or item.get("field") not in {"purpose", "side_effects", "risks"}:
            continue
        value, quote = item.get("value"), item.get("quote")
        if (
            isinstance(value, str) and 1 <= len(value) <= 500 and _BUSINESS.search(value)
            and isinstance(quote, str) and 4 <= len(quote) <= 500
        ):
            candidates.append((value, quote))
    if not candidates:
        return None
    source = _evidence_path_under_root(str(store.root), path, strict=True)
    if source is None:
        return None
    sliced = read_source_slice(
        str(store.root), path, line_end=200, max_chars=12000, expected_file_sha256=source_digest,
    )
    if sliced.get("success") is not True or sliced.get("relative_path") != path:
        return None
    if _evidence_path_under_root(str(store.root), path, strict=True) != source:
        return None
    text = sliced["text"]
    statements = []
    locators = []
    for value, quote in candidates:
        offset = text.find(quote)
        if offset < 0 or text.find(quote, offset + 1) >= 0 or value in statements:
            continue
        start = text[:offset].count("\n") + 1
        end = start + quote.rstrip("\r\n").count("\n")
        statements.append(value)
        locators.append({
            "schema_version": 1, "path": path, "content_digest": source_digest,
            "start_line": start, "end_line": end,
        })
        if len(statements) >= 3:
            break
    if not statements:
        return None
    manifest, _ = store.manifest()
    record = {
        "schema_version": 1, "project_id": manifest["project_id"], "kind": "observation",
        "id": "auto-" + _digest_value([_GENERATOR, path])[:24],
        "payload": {
            "title": "Business candidate from file card",
            "statement": "Unreviewed source-card interpretation; verify behavior: " + "; ".join(statements),
            "layer": "interpretation",
        },
        "provenance": {"origin_kind": "deterministic" if model == "deterministic" else "model",
                       "generator": _GENERATOR},
        "evidence": locators, "relations": [],
    }
    record["provenance"]["generated_digest"] = _generation_digest(record)
    validate_knowledge_file(_path_for(record["kind"], record["id"]), _encode(record))
    return record


def publish_file_card_candidate(
    config: Mapping[str, Any], root: str, path: str, source_digest: str,
    card: Mapping[str, Any], model: str,
) -> str:
    """Update only an untouched generated candidate, never a human-edited record."""
    if not auto_publish_authorized(config, root):
        return "not_authorized"
    try:
        store = RepoKnowledgeStore(root)
        manifest, manifest_revision = store.manifest()
        if manifest["mode"] != "shared":
            return "not_shared"
        record = candidate_from_file_card(store, path, source_digest, card, model)
        if record is None:
            return "no_candidate"
        if record["project_id"] != manifest["project_id"]:
            return "changed"
        try:
            prior = store.get("observation", record["id"], verify_sources=False)
        except FileNotFoundError:
            prior = None
        if prior is not None:
            current = prior["record"]
            provenance = current["provenance"]
            if (
                provenance.get("generator") != _GENERATOR
                or provenance.get("generated_digest") != _generation_digest(current)
                or "review_ref" in provenance
            ):
                return "human_preserved"
            if current == record:
                return "unchanged"
            expected = prior["revision"]
        else:
            catalog = store.catalog(verify_sources=False)
            if not catalog["complete"] or len(catalog["records"]) >= 128:
                return "inventory_bound"
            expected = ""

        def authorized() -> bool:
            try:
                return (
                    auto_publish_authorized(config, root)
                    and store.manifest()[1] == manifest_revision
                    and EvidenceStore.portable_source_status(record["evidence"][0], root=root) == "matching_file"
                )
            except (OSError, RepoPlanError):
                return False

        result = store.save(record, expected_revision=expected, owner="preprocess-knowledge",
                            idempotency_key=str(uuid4()), authorize_write=authorized)
        return "published" if result.get("success") else "unavailable"
    except FileNotFoundError:
        return "uninitialized"
    except (OSError, RepoPlanError, ValueError, RuntimeError):
        return "unavailable"
