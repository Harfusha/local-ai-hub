"""Regression test suite for Audit Round 4 findings (A01 through A17).
Documented in docs/AUDIT_ROUND_4_2026-11-08.md.
"""
from __future__ import annotations

import hashlib
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from local_ai_hub.agent_consistency import AgentConsistencyGuard
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_learning import CandidateStatus, ImprovementCandidate, LearningStore
from local_ai_hub.command_transactions import TransactionStashHook
from local_ai_hub.evidence import EvidenceStore
from local_ai_hub.worktrees import get_worktree_status


def test_t4_10_evidence_validation_streams_requested_lines(tmp_path: Path, monkeypatch):
    """A02: Source validation hashes and scans without materializing all lines."""
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "large.py"
    content = "".join(f"line {index}\n" for index in range(10000))
    source.write_bytes(content.encode("utf-8"))
    store = EvidenceStore(state_dir=tmp_path / "state")
    evidence_id = store.put(
        str(root),
        {
            "path": "large.py",
            "text": "line 9\nline 10",
            "file_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "start_line": 10,
            "end_line": 11,
        },
    )
    assert evidence_id
    assert store.get(evidence_id)["stale"] is False
    original_open = Path.open

    class NoReadlines:
        def __init__(self, stream):
            self._stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self._stream.__exit__(*args)

        def __iter__(self):
            return iter(self._stream)

        def read(self, *args):
            return self._stream.read(*args)

        def readlines(self, *args):
            raise AssertionError("evidence validation must not materialize all file lines")

    def open_without_readlines(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        if Path(path) == source and args and args[0] == "r":
            return NoReadlines(stream)
        return stream

    monkeypatch.setattr(Path, "open", open_without_readlines)
    assert store.validate_current(evidence_id) is True


def test_t4_01_evidence_store_path_confinement(tmp_path: Path):
    """T4-01 (A17): EvidenceStore.put rejects paths escaping repository root."""
    ev_store = EvidenceStore(state_dir=tmp_path)
    root = tmp_path / "repo"
    root.mkdir()

    # Path attempting to escape via parent directory
    escaped_item = {
        "path": "../../../etc/passwd",
        "text": "root:x:0:0:",
        "file_sha256": "abcdef123456",
        "start_line": 1,
        "end_line": 1,
    }
    eid = ev_store.put(str(root), escaped_item)
    assert eid is None

    # Valid relative path inside root
    valid_file = root / "valid.py"
    valid_file.write_text("print('hello')\n", encoding="utf-8")
    valid_item = {
        "path": "valid.py",
        "text": "print('hello')",
        "file_sha256": "validhash123",
        "start_line": 1,
        "end_line": 1,
    }
    valid_eid = ev_store.put(str(root), valid_item)
    assert valid_eid is not None
    assert valid_eid.startswith("E")


def test_t4_02_learning_store_advance_rejects_promoted(tmp_path: Path):
    """T4-02 (A06): LearningStore.advance rejects direct jump to PROMOTED without promote() approval."""
    db_path = tmp_path / "learning.sqlite3"
    state_store = AgentStateStore(db_path=db_path)
    state_store._ensure_schema()
    store = LearningStore(state_store=state_store)

    candidate = ImprovementCandidate(
        candidate_id="cand_test",
        name="test_experiment",
        baseline_version="1.0",
        candidate_version="1.1",
        status=CandidateStatus.CANDIDATE,
        slo_thresholds={},
        metrics={},
        approver="",
        created_at=time.time(),
        updated_at=time.time(),
    )
    store.create_candidate(candidate)

    # advance to PROMOTED must raise ValueError
    with pytest.raises(ValueError, match="PROMOTED is prohibited"):
        store.advance("cand_test", CandidateStatus.PROMOTED)


def test_t4_03_agent_consistency_strict_boolean_audit():
    """T4-03 (A16): completion_audit does not treat string 'false' as passed boolean."""
    guard = AgentConsistencyGuard()
    receipts = [
        {
            "criterion": "all_tests_pass",
            "passed": "false",  # string false must not be treated as passed
            "repository_revision": "rev1",
            "evidence_id": "ev1",
            "receipt_id": "rc1",
        }
    ]
    audit = guard.completion_audit(
        criteria=["all_tests_pass"],
        receipts=receipts,
        current_revision="rev1",
    )
    assert audit["criteria"]["all_tests_pass"]["status"] != "satisfied"
    assert audit["current_revision_receipt_coverage"]["covered"] == 0


def test_t4_04_worktree_status_handles_non_existent():
    """T4-04 (A03): get_worktree_status cleanly handles non-existent or invalid paths."""
    status = get_worktree_status("non_existent_worktree_path_xyz")
    assert status["exists"] is False
    assert status["locked"] is False


def test_t4_05_transaction_stash_tracks_exact_sha(tmp_path: Path):
    """T4-05 (A05): TransactionStashHook tracks _stash_sha and rejects missing stash on restore."""
    repo_dir = tmp_path / "git_repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo_dir), check=True)
    (repo_dir / "init.txt").write_text("initial\n", encoding="utf-8")
    subprocess.run(["git", "add", "init.txt"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo_dir), check=True)

    hook = TransactionStashHook(root=repo_dir, message="test_guard")
    assert hook.is_stashed is False

    # Make dirty
    (repo_dir / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    saved = hook.save()
    assert saved is True
    assert hook.is_stashed is True
    assert hook._stash_sha is not None

    # Restore
    restored = hook.restore()
    assert restored is True
    assert hook.is_stashed is False
    assert (repo_dir / "dirty.txt").exists()


def test_t4_06_evidence_text_mismatch_fails_validation(tmp_path: Path):
    """T4-06 (A01): validate_current fails if evidence text does not match file lines."""
    import hashlib
    from local_ai_hub.evidence import EvidenceStore
    store = EvidenceStore(state_dir=tmp_path)
    file_p = tmp_path / "code.py"
    file_p.write_text("line 1\nline 2: return True\nline 3\n", encoding="utf-8")
    actual_hash = hashlib.sha256(file_p.read_bytes()).hexdigest()

    # Valid evidence
    ev_ok = store.put(str(tmp_path), {
        "path": "code.py",
        "file_sha256": actual_hash,
        "start_line": 2,
        "end_line": 2,
        "text": "line 2: return True",
    })
    assert ev_ok is not None
    assert store.validate_current(ev_ok) is True

    # Forged text at line 2
    ev_forged = store.put(str(tmp_path), {
        "path": "code.py",
        "file_sha256": actual_hash,
        "start_line": 2,
        "end_line": 2,
        "text": "line 2: return False",
    })
    assert ev_forged is not None
    assert store.validate_current(ev_forged) is False


def test_t4_07_learning_slo_success_rate_window(tmp_path: Path):
    """T4-07 (A08): LearningStore.observe does not rollback on single failure before window/sample threshold."""
    from local_ai_hub.agent_learning import LearningStore, CandidateStatus, SLOObservation, ImprovementCandidate
    from local_ai_hub.agent_events import AgentStateStore
    state_store = AgentStateStore(db_path=tmp_path / "learning.sqlite3")
    state_store._ensure_schema()
    store = LearningStore(state_store=state_store)

    candidate = ImprovementCandidate.create(
        "cand_1", "baseline_v1", "v2",
        slo_thresholds={"min_success_rate": 0.8, "min_samples": 4},
        metrics={"slo_obs_total": 0, "slo_obs_success": 0},
    )
    c = store.create_candidate(candidate)
    dec = store.promote(c.candidate_id, approver="user")
    assert dec.promoted is True
    c_prom = store.get(c.candidate_id)
    assert c_prom.status == CandidateStatus.PROMOTED

    # 1st observation: failure -> shouldn't rollback yet because min_samples=4
    rb1 = store.observe(c.candidate_id, SLOObservation(success=False))
    assert rb1 is None

    # 2nd observation: success
    rb2 = store.observe(c.candidate_id, SLOObservation(success=True))
    assert rb2 is None


def test_t4_08_contract_mapping_skips_unrelated_files(tmp_path: Path):
    """T4-08 (A09): build_contract_mappings returns empty mapping when frontend and backend share no endpoint or name."""
    from local_ai_hub.agent_consistency import AgentConsistencyGuard, ConsistencyRequest
    guard = AgentConsistencyGuard()
    req = ConsistencyRequest(root=str(tmp_path), task_id="t1", changed_paths=("src/users.py", "web/checkout.tsx"))
    evidence = [
        {"path": "src/users.py", "text": "def get_users(): return []"},
        {"path": "web/checkout.tsx", "text": "export const Checkout = () => <div/>;"},
    ]
    mappings, warnings = guard.build_contract_mappings(req, evidence)
    assert len(mappings) == 0
    assert len(warnings) == 0


def test_t4_09_model_quality_receipt_validation():
    """T4-09 (A14): promote_candidate requires reproducible evaluation receipt with hash and suite."""
    from local_ai_hub.model_quality import promote_candidate
    cand = {
        "candidate_id": "c1",
        "metrics": {
            "grounded_rate": 0.95,
            "schema_pass_rate": 0.98,
            "abstention_accuracy": 0.95,
            "hallucinated_path_rate": 0.0,
            "false_positive_rate": 0.01,
        },
    }
    # Weak receipt lacking evaluation_hash and suite
    weak_receipt = {"receipt_id": "r1", "reproducible": False}
    dec_weak = promote_candidate(cand, receipt=weak_receipt)
    assert dec_weak["status"] == "rejected"
    assert dec_weak["reason"] == "evaluation_receipt_required"

    # Strong receipt
    strong_receipt = {"receipt_id": "r2", "evaluation_hash": "sha256abc", "suite_version": "v1"}
    dec_strong = promote_candidate(cand, receipt=strong_receipt)
    assert dec_strong["status"] == "champion"
