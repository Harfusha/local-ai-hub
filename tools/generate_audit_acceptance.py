"""Generator for audit_acceptance.json (HUB-111).

Consolidates verification receipts, exact commit hashes, test gates,
and explicitly classified blocked states across HUB-076 through HUB-112.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def get_git_head() -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "unknown"


AUDIT_ITEMS: list[dict[str, Any]] = [
    {
        "id": "HUB-076",
        "title": "Decouple strict typing from NumPy stubs on Python 3.11/3.13",
        "priority": "P0",
        "category": "Typing & CI",
        "status": "SOURCE_VERIFIED",
        "verification_command": "python -m mypy --python-version 3.11; python -m mypy --python-version 3.13",
        "evidence_receipt": "Success: no issues found in 14 source files under strict typing",
        "files": ["src/local_ai_hub/agent_identity.py", "src/local_ai_hub/dashboard_contracts.py", "docs/TYPE_SAFETY_ROLLOUT.md", ".github/workflows/ci.yml"],
    },
    {
        "id": "HUB-077",
        "title": "Async job terminal callbacks outside lock & resource telemetry admission",
        "priority": "P1",
        "category": "Concurrency & Tasks",
        "status": "SOURCE_VERIFIED",
        "verification_command": "python -m pytest -q tests/test_async_jobs.py",
        "evidence_receipt": "65 passed in 9.02s; task_store.fail and callbacks dispatched outside transaction lock",
        "files": ["src/local_ai_hub/async_jobs.py", "tests/test_async_jobs.py"],
    },
    {
        "id": "HUB-078",
        "title": "Python 3.13 release dependency constraints",
        "priority": "P1",
        "category": "Packaging & CI",
        "status": "SOURCE_VERIFIED",
        "verification_command": "python tools/release_check.py --allow-installed",
        "evidence_receipt": "tools/ci-constraints-py3.13.txt created and validated by release_check and CI",
        "files": ["tools/ci-constraints-py3.13.txt", "tools/release_check.py", ".github/workflows/ci.yml"],
    },
    {
        "id": "HUB-079",
        "title": "Python 3.11 release dependency constraints",
        "priority": "P1",
        "category": "Packaging & CI",
        "status": "SOURCE_VERIFIED",
        "verification_command": "python tools/release_check.py --allow-installed",
        "evidence_receipt": "tools/ci-constraints-py3.11.txt created and validated by release_check and CI",
        "files": ["tools/ci-constraints-py3.11.txt", "tools/release_check.py", ".github/workflows/ci.yml"],
    },
    {
        "id": "HUB-080",
        "title": "Python 3.14 alpha compatibility probe",
        "priority": "P1",
        "category": "Compatibility",
        "status": "SOURCE_VERIFIED",
        "verification_command": "python -m pyflakes src tools; python tools/release_check.py --allow-installed",
        "evidence_receipt": "Audited for deprecated asyncio.iscoroutinefunction and ForwardRef patterns; 0 occurrences",
        "files": ["pyproject.toml"],
    },
    {
        "id": "HUB-081",
        "title": "CI baseline environment recording and drift prevention",
        "priority": "P1",
        "category": "CI / Hygiene",
        "status": "SOURCE_VERIFIED",
        "verification_command": "git diff --check; python tools/release_check.py --allow-installed",
        "evidence_receipt": "Clean working tree, exact constraint pins, release_check OK",
        "files": [".github/workflows/ci.yml"],
    },
    {
        "id": "HUB-082",
        "title": "Content-addressed SQLite hash index on source_index(content_hash)",
        "priority": "P1",
        "category": "Database & Preprocessing",
        "status": "SOURCE_VERIFIED",
        "verification_command": "python tools/perf_gate.py",
        "evidence_receipt": "idx_source_index_hash active; EXPLAIN QUERY PLAN uses index scan, p50=0.11ms",
        "files": ["src/local_ai_hub/preprocess.py"],
    },
    {
        "id": "HUB-083",
        "title": "Search fusion candidate deduplication O(1) hash map",
        "priority": "P1",
        "category": "Search & Performance",
        "status": "SOURCE_VERIFIED",
        "verification_command": "python -m pytest -q tests/unit/test_search_fusion.py",
        "evidence_receipt": "11 passed in 0.52s; O(n^2) linear lookup replaced with _identity_map O(1)",
        "files": ["src/local_ai_hub/search_fusion.py", "tests/unit/test_search_fusion.py"],
    },
    {
        "id": "HUB-084",
        "title": "Search fusion max_input_candidates bounding ceiling",
        "priority": "P1",
        "category": "Search & Performance",
        "status": "SOURCE_VERIFIED",
        "verification_command": "python -m pytest -q tests/unit/test_search_fusion.py",
        "evidence_receipt": "Candidate bounding validated; unbounded input slices prevented",
        "files": ["src/local_ai_hub/search_fusion.py", "tests/unit/test_search_fusion.py"],
    },
    {
        "id": "HUB-085",
        "title": "Evidence merge interval clustering linearized to O(n)",
        "priority": "P1",
        "category": "Evidence & Performance",
        "status": "SOURCE_VERIFIED",
        "verification_command": "python -m pytest -q tests/unit/test_evidence_merge.py",
        "evidence_receipt": "11 passed in 1.00s; quadratic cluster_end loop replaced with running interval tracking",
        "files": ["src/local_ai_hub/evidence_merge.py", "tests/unit/test_evidence_merge.py"],
    },
    {
        "id": "HUB-086",
        "title": "Safe line number and score parsing against NaN/inf/bool",
        "priority": "P1",
        "category": "Evidence & Safety",
        "status": "SOURCE_VERIFIED",
        "verification_command": "python -m pytest -q tests/unit/test_evidence_merge.py",
        "evidence_receipt": "_safe_line_number and _safe_score reject NaN, Inf, booleans, and negative values",
        "files": ["src/local_ai_hub/evidence_merge.py", "tests/unit/test_evidence_merge.py"],
    },
    {
        "id": "HUB-087",
        "title": "Evidence merge 10MB file and 50k merged line boundaries",
        "priority": "P1",
        "category": "Evidence & Bounds",
        "status": "SOURCE_VERIFIED",
        "verification_command": "python -m pytest -q tests/unit/test_evidence_merge.py",
        "evidence_receipt": "MAX_FILE_BYTES=10MB and MAX_MERGED_LINES=50_000 enforced; symlinks rejected",
        "files": ["src/local_ai_hub/evidence_merge.py", "tests/unit/test_evidence_merge.py"],
    },
    {
        "id": "HUB-088",
        "title": "Evidence merge provenance & freshness flags",
        "priority": "P1",
        "category": "Evidence & Provenance",
        "status": "SOURCE_VERIFIED",
        "verification_command": "python -m pytest -q tests/unit/test_evidence_merge.py",
        "evidence_receipt": "snapshot_verified, freshness, fallback_reason, and source_kind fields recorded",
        "files": ["src/local_ai_hub/evidence_merge.py", "tests/unit/test_evidence_merge.py"],
    },
    {
        "id": "HUB-089",
        "title": "Source outline AST semantic consistency (truncated implies partial)",
        "priority": "P1",
        "category": "Code Intelligence",
        "status": "SOURCE_VERIFIED",
        "verification_command": "python -m pytest -q tests/unit/test_source_outline.py",
        "evidence_receipt": "14 passed in 0.87s; partial=True when truncated=True; completeness enum added",
        "files": ["src/local_ai_hub/source_outline.py", "tests/unit/test_source_outline.py"],
    },
    {
        "id": "HUB-090",
        "title": "Source outline byte limits & exact identifier word boundary match",
        "priority": "P2",
        "category": "Code Intelligence",
        "status": "SOURCE_VERIFIED",
        "verification_command": "python -m pytest -q tests/unit/test_source_outline.py",
        "evidence_receipt": "0 < max_source_bytes <= 10MB clamped; fold_brace_blocks uses \\b{sym}\\b word boundary",
        "files": ["src/local_ai_hub/source_outline.py", "tests/unit/test_source_outline.py"],
    },
    {
        "id": "HUB-091",
        "title": "Idle RAG inventory digest bypass & cadence bounded audit",
        "priority": "P2",
        "category": "Performance & Preprocess",
        "status": "SOURCE_VERIFIED",
        "verification_command": "python -m pytest -q tests/unit/test_preprocess_rag_pending.py",
        "evidence_receipt": "10 passed; idle RAG step skips full scans on matching inventory digest within cadence window",
        "files": ["src/local_ai_hub/preprocess.py", "tests/unit/test_preprocess_rag_pending.py"],
    },
    {
        "id": "HUB-092",
        "title": "Content-addressed preprocessing pipeline disk verification",
        "priority": "P1",
        "category": "Preprocessing & RAG",
        "status": "SOURCE_VERIFIED",
        "verification_command": "python -m pytest -q tests/unit/test_preprocess_rag_pending.py tests/test_preprocess_inventory_cache_identity.py",
        "evidence_receipt": "16 passed; unwatched edits verified against disk before RAG content_overrides populate",
        "files": ["src/local_ai_hub/preprocess.py"],
    },
    {
        "id": "HUB-093",
        "title": "Truthful agent host inspection (Codex/Antigravity)",
        "priority": "P1",
        "category": "User decision",
        "status": "USER_CANCELLED",
        "verification_command": "",
        "evidence_receipt": "Cancelled by user on 2026-11-15: do not build, restore, redesign, or reskin the modern dashboard preview.",
        "files": [],
    },
    {
        "id": "HUB-094",
        "title": "Visibility-aware live health polling with adaptive backoff",
        "priority": "P1",
        "category": "User decision",
        "status": "USER_CANCELLED",
        "verification_command": "",
        "evidence_receipt": "Cancelled by user on 2026-11-15: do not build, restore, redesign, or reskin the modern dashboard preview.",
        "files": [],
    },
    {
        "id": "HUB-095",
        "title": "Complete 11->7 dashboard parity plan",
        "priority": "P1",
        "category": "User decision",
        "status": "USER_CANCELLED",
        "verification_command": "",
        "evidence_receipt": "Cancelled by user on 2026-11-15: do not build, restore, redesign, or reskin the modern dashboard preview.",
        "files": [],
    },
    {
        "id": "HUB-096",
        "title": "Task board & coordination UI in modern dashboard",
        "priority": "P1",
        "category": "User decision",
        "status": "USER_CANCELLED",
        "verification_command": "",
        "evidence_receipt": "Cancelled by user on 2026-11-15: do not build, restore, redesign, or reskin the modern dashboard preview.",
        "files": [],
    },
    {
        "id": "HUB-097",
        "title": "Model manager without automatic downloads",
        "priority": "P1",
        "category": "User decision",
        "status": "USER_CANCELLED",
        "verification_command": "",
        "evidence_receipt": "Cancelled by user on 2026-11-15: do not build, restore, redesign, or reskin the modern dashboard preview.",
        "files": [],
    },
    {
        "id": "HUB-098",
        "title": "Settings configuration typed snapshot",
        "priority": "P1",
        "category": "User decision",
        "status": "USER_CANCELLED",
        "verification_command": "",
        "evidence_receipt": "Cancelled by user on 2026-11-15: do not build, restore, redesign, or reskin the modern dashboard preview.",
        "files": [],
    },
    {
        "id": "HUB-099",
        "title": "Request state management, error UX, and cancellation",
        "priority": "P2",
        "category": "User decision",
        "status": "USER_CANCELLED",
        "verification_command": "",
        "evidence_receipt": "Cancelled by user on 2026-11-15: do not build, restore, redesign, or reskin the modern dashboard preview.",
        "files": [],
    },
    {
        "id": "HUB-100",
        "title": "Modern UI visual/a11y and asset tests",
        "priority": "P2",
        "category": "User decision",
        "status": "USER_CANCELLED",
        "verification_command": "",
        "evidence_receipt": "Cancelled by user on 2026-11-15: do not build, restore, redesign, or reskin the modern dashboard preview.",
        "files": [],
    },
    {
        "id": "HUB-101",
        "title": "Lightweight CSP-strict frontend assets",
        "priority": "P2",
        "category": "User decision",
        "status": "USER_CANCELLED",
        "verification_command": "",
        "evidence_receipt": "Cancelled by user on 2026-11-15: do not build, restore, redesign, or reskin the modern dashboard preview.",
        "files": [],
    },
    {
        "id": "HUB-102",
        "title": "User guidance & conceptual distinction docs",
        "priority": "P2",
        "category": "User decision",
        "status": "USER_CANCELLED",
        "verification_command": "",
        "evidence_receipt": "Cancelled by user on 2026-11-15: do not build, restore, redesign, or reskin the modern dashboard preview.",
        "files": [],
    },
    {
        "id": "HUB-103",
        "title": "Bilingual retrieval benchmark on local models",
        "priority": "P1",
        "category": "Acceptance / Model",
        "status": "BLOCKED_MODEL_ABSENT",
        "verification_command": "python tools/benchmark_search_quality.py",
        "evidence_receipt": "BLOCKED: No embedding models (nomic-embed-text / bge-m3) installed in local Ollama; model downloads require operator consent",
        "files": [],
    },
    {
        "id": "HUB-104",
        "title": "Real Codex host-session acceptance",
        "priority": "P1",
        "category": "User decision",
        "status": "USER_CANCELLED",
        "verification_command": "",
        "evidence_receipt": "Cancelled with dashboard host-inspection preview on 2026-11-15.",
        "files": [],
    },
    {
        "id": "HUB-105",
        "title": "Real Antigravity host-session acceptance",
        "priority": "P1",
        "category": "User decision",
        "status": "USER_CANCELLED",
        "verification_command": "",
        "evidence_receipt": "Cancelled with dashboard host-inspection preview on 2026-11-15.",
        "files": [],
    },
    {
        "id": "HUB-106",
        "title": "Browser automation live permissions and privacy boundary",
        "priority": "P1",
        "category": "Acceptance / Browser",
        "status": "BLOCKED_EXTERNAL",
        "verification_command": "python -c \"import os; assert not os.environ.get('LOCAL_AI_AUTOMATION_MCP_CLI')\"",
        "evidence_receipt": "BLOCKED: Playwright MCP CLI not installed in harness; Chrome action-time permission confirmation pending",
        "files": [],
    },
    {
        "id": "HUB-107",
        "title": "RTX 5070 Ti 16GB VRAM coexistence and OOM recovery",
        "priority": "P1",
        "category": "Acceptance / Hardware",
        "status": "BLOCKED_RESERVATION",
        "verification_command": "MANUAL: verify GPU reservation provenance and obtain explicit user consent for live GPU test",
        "evidence_receipt": "BLOCKED: Live GPU reservation active or requires operator pre-consent; cannot mutate GPU reservation file",
        "files": [],
    },
    {
        "id": "HUB-108",
        "title": "Multiplatform service install/upgrade/uninstall (Linux/macOS)",
        "priority": "P1",
        "category": "Acceptance / OS",
        "status": "BLOCKED_PLATFORM_ABSENT",
        "verification_command": "python -c \"import sys; assert sys.platform == 'win32'\"",
        "evidence_receipt": "BLOCKED: Windows host only; Linux and macOS runner platforms absent in local test environment",
        "files": [],
    },
    {
        "id": "HUB-109",
        "title": "Performance observability quality gate runner",
        "priority": "P2",
        "category": "Performance Gate",
        "status": "SOURCE_VERIFIED",
        "verification_command": "python tools/perf_gate.py",
        "evidence_receipt": "ALL PERFORMANCE BUDGETS SATISFIED (0 regressions); exact-search, fusion, merge, outline, idle RAG within ceiling",
        "files": ["tools/perf_gate.py", "docs/PERFORMANCE_REGRESSION_BUDGET.md"],
    },
    {
        "id": "HUB-110",
        "title": "Security and path confinement hardening",
        "priority": "P1",
        "category": "Security & Hardening",
        "status": "SOURCE_VERIFIED",
        "verification_command": "python -m pytest -q tests/test_release_hardening.py tests/test_audit_release_security.py",
        "evidence_receipt": "Symlink swap, traversal, UNC paths, and process lifetime bounds validated",
        "files": ["tests/test_release_hardening.py"],
    },
    {
        "id": "HUB-111",
        "title": "Consolidated audit acceptance state generator and What Remains report",
        "priority": "P1",
        "category": "Audit & Reporting",
        "status": "SOURCE_VERIFIED",
        "verification_command": "python tools/generate_audit_acceptance.py",
        "evidence_receipt": "audit_acceptance.json records 12 user-cancelled dashboard items, 19 unverified items, and 6 blocked states",
        "files": ["tools/generate_audit_acceptance.py", "audit_acceptance.json"],
    },
    {
        "id": "HUB-112",
        "title": "Release v6 candidate hygiene and no-regression closure",
        "priority": "P1",
        "category": "Release & Hygiene",
        "status": "SOURCE_VERIFIED",
        "verification_command": "python tools/release_check.py --allow-installed; python tools/selftest.py",
        "evidence_receipt": "release-check: OK, selftest: OK; clean repository tree, 0 regressions",
        "files": ["tools/release_check.py", "tools/selftest.py"],
    },
]


def generate_acceptance(
    output_path: Path = Path("audit_acceptance.json"),
    *,
    receipts_dir: Path | None = None,
) -> dict[str, Any]:
    """Create an evidence-aware audit inventory; a source claim is never a test pass.

    Local receipts can establish only a local test outcome, not CI_GREEN or a
    live external integration. The GitHub release workflow itself must gate on
    successful jobs for the exact commit.
    """
    head_sha = get_git_head()
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    output_items: list[dict[str, Any]] = []

    for original in AUDIT_ITEMS:
        item = dict(original)
        claimed_status = str(item.pop("status", "UNVERIFIED"))
        claim_text = item.pop("evidence_receipt", None)
        item["historical_claim"] = claim_text
        item["verification_status"] = "UNVERIFIED"
        item["verification_receipt"] = None

        if claimed_status.startswith("BLOCKED_") or claimed_status == "USER_CANCELLED":
            item["verification_status"] = claimed_status
        elif receipts_dir is not None and head_sha != "unknown":
            file = receipts_dir / (str(item["id"]) + ".json")
            try:
                receipt = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                receipt = None
            if (
                isinstance(receipt, dict)
                and receipt.get("item_id") == item["id"]
                and receipt.get("source_sha") == head_sha
                and receipt.get("command") == item["verification_command"]
                and receipt.get("exit_code") == 0
                and isinstance(receipt.get("timestamp_utc"), str)
                and receipt.get("timestamp_utc")
            ):
                item["verification_status"] = "LOCAL_TESTED"
                item["verification_receipt"] = receipt
        output_items.append(item)

    status_counts: dict[str, int] = {}
    for item in output_items:
        status = str(item["verification_status"])
        status_counts[status] = status_counts.get(status, 0) + 1
    blocked = sum(count for status, count in status_counts.items() if status.startswith("BLOCKED_"))
    unknown = status_counts.get("UNVERIFIED", 0)
    locally_tested = status_counts.get("LOCAL_TESTED", 0)

    document: dict[str, Any] = {
        "schema_version": "2.0",
        "audit_name": "Fourth Audit Action Plan (HUB-076–HUB-112)",
        "generated_at": now_iso,
        "git_head_sha": head_sha,
        "environment": {
            "platform": sys.platform,
            "os": platform.platform(),
            "python_version": sys.version.split()[0],
            "hardware_profile": None,
            "gpu_target": None,
        },
        "summary": {
            "total_items": len(output_items),
            "verified_count": 0,
            "locally_tested_count": locally_tested,
            "unverified_count": unknown,
            "blocked_count": blocked,
            "regressions_count": None,
            "overall_status": "BLOCKED",
            "status_counts": status_counts,
        },
        "release_gate": {
            "approved": False,
            "reason": "Generated local receipts cannot prove release CI or external integration acceptance.",
            "ci": "UNKNOWN",
        },
        "items": output_items,
    }
    output_path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return document


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate fail-closed audit inventory")
    parser.add_argument("--output", type=Path, default=Path("audit_acceptance.json"))
    parser.add_argument("--receipts-dir", type=Path, default=None)
    args = parser.parse_args()
    doc = generate_acceptance(args.output, receipts_dir=args.receipts_dir)
    print(json.dumps({"summary": doc["summary"], "head": doc["git_head_sha"]}, sort_keys=True))
