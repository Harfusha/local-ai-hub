"""Optional deterministic consistency guard over existing repository knowledge.

Only explicitly modeled contradictions and source/target checks are evaluated.
The guard is additional completion authority, never evidence for an obligation.
"""
from __future__ import annotations

from typing import Any

from .repo_knowledge import RepoKnowledgeStore
from .repo_knowledge_quality import quality_report
from .repo_state import RepoStateTracker

BLOCKING_TYPES = frozenset({
    "declared_claim_conflict", "source_literal_mismatch", "source_literal_unverified",
    "verification_target_missing", "verification_target_unknown",
})


def knowledge_consistency(root: str, revision: str) -> dict[str, Any]:
    """Fail closed on partial inventory or unstable repository/knowledge snapshots."""
    unavailable = {"complete": False, "status": "unavailable", "blocking_count": 0,
                   "findings_preview": [], "authority": "deterministic_repository_knowledge"}
    if not root or not revision:
        return unavailable
    try:
        tracker = RepoStateTracker({})
        before = tracker.fingerprint(root, force=True)
        if (before.get("success") is not True or before.get("degraded")
                or before.get("stale") or before.get("truncated")
                or before.get("fingerprint") != revision):
            return {**unavailable, "status": "revision_unavailable"}
        store = RepoKnowledgeStore(root)
        epoch = store.read_epoch()
        manifest_revision = store.manifest()[1]
        catalog = store.catalog()
        audit = quality_report(catalog)
        if audit["complete"] is not True:
            return {**unavailable, "status": "partial_inventory"}
        # Re-read after evaluation; Git content is not itself a proof of current
        # source bytes. Detect changes to records or observed source status.
        after_catalog = store.catalog()
        if catalog != after_catalog or store.manifest()[1] != manifest_revision:
            return {**unavailable, "status": "snapshot_changed"}
        store.require_read_epoch(epoch)
        after = tracker.fingerprint(root, force=True)
        if (after.get("success") is not True or after.get("degraded")
                or after.get("stale") or after.get("truncated")
                or after.get("fingerprint") != revision):
            return {**unavailable, "status": "snapshot_changed"}
        findings = [finding for finding in audit["findings"] if finding["type"] in BLOCKING_TYPES]
        return {
            "complete": not findings, "status": "consistent" if not findings else "contradictions",
            "blocking_count": len(findings),
            "findings_preview": [{key: finding[key] for key in ("id", "type", "subject_digest")}
                                 for finding in findings[:12]],
            "authority": "deterministic_repository_knowledge",
        }
    except Exception:
        return unavailable
