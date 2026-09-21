from __future__ import annotations

import json
import re
from pathlib import Path

from local_ai_hub import __version__


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "MIGRATION_3_TO_4.md"


def _guide() -> str:
    return GUIDE.read_text(encoding="utf-8")


def test_migration_guide_has_required_sections() -> None:
    guide = _guide()
    required_headings = {
        "# Local AI Hub 3.0.0 → 4.0.0 migration",
        "## Scope and version transition rules",
        "## Backup and rollback",
        "## State directory and SQLite state",
        "## Configuration changes",
        "## Unified task-context contract",
        "## Telemetry and schema changes",
        "## Agent OS tasks and receipts",
        "## Model quality registry",
        "## Command transport compatibility",
        "## Staged rollout",
        "## Post-upgrade verification",
    }
    headings = {line for line in guide.splitlines() if line.startswith("#")}
    assert required_headings <= headings


def test_migration_guide_matches_current_metadata_and_target_rules() -> None:
    release = json.loads((ROOT / "RELEASE.json").read_text(encoding="utf-8"))
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    guide = _guide()

    assert __version__ == "3.0.0"
    assert release["version"] == "3.0.0"
    assert 'version = "3.0.0"' in pyproject
    assert re.search(r"3\.0\.0\s+→\s+4\.0\.0", guide)
    assert "current 3.0" in guide
    assert "Target version: `4.0.0`" in guide
    assert re.search(
        r"this document is not a\s+claim that the current installation is already version 4",
        guide,
    )
    assert "Do not call a 3.0 installation upgraded" in guide


def test_migration_guide_covers_reversible_state_and_contract_gates() -> None:
    guide = _guide()
    required_terms = (
        "server.state_dir",
        "agent_state.sqlite3",
        "SHA-256",
        "rollback",
        "task_id",
        "repo_revision",
        "evidence_ids",
        "context_id",
        "verify_completion",
        "candidate",
        "champion",
        "rejected",
        "request ID",
        "retry_after_seconds",
        "process-scoped",
        "quality floor",
    )
    missing = [term for term in required_terms if term not in guide]
    assert not missing, f"migration contract terms missing: {missing}"


def test_migration_guide_does_not_claim_source_is_already_v4() -> None:
    guide = _guide().lower()
    forbidden_claims = (
        "current version is 4.0.0",
        "already version 4.0.0",
        "the current installation is version 4",
    )
    assert not any(claim in guide for claim in forbidden_claims)
