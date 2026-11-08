from __future__ import annotations

from contextlib import closing
from pathlib import Path
from local_ai_hub.leases import ScopeLeaseStore


def test_n14_no_false_deadlock_from_orphaned_wait_edges(tmp_path: Path):
    leases = ScopeLeaseStore(state_dir=tmp_path)
    root = str(tmp_path)

    # 1. Agent A claims parent directory "src"
    claim_a = leases.claim(owner="agent-A", root=root, paths=["src"], ttl_seconds=600)
    assert claim_a["success"] is True

    # 2. Agent B tries to claim child "src/service.py" -> overlaps with A, creates wait edge (B -> A)
    claim_b = leases.claim(owner="agent-B", root=root, paths=["src/service.py"], ttl_seconds=600)
    assert claim_b["success"] is False
    assert claim_b.get("deadlock") is False

    # 3. Agent A releases "src"
    rel_a = leases.release(owner="agent-A", lease_id=claim_a["lease_id"])
    assert rel_a["success"] is True

    # 4. Agent B claims unrelated path "docs/notes.txt"
    # Note: Agent B never successfully claimed src/service.py, but in claim() line 359 it only deletes
    # owner="agent-B" when B claims. But wait! What if B doesn't claim, or what if C claims?
    # Better yet: Agent B doesn't claim anything yet.
    # Agent C claims "tools/cli.py".
    # Agent B tries to claim "tools/cli.py" -> creates wait (B -> C).
    # Then Agent C tries to claim something else?
    # What if Agent B holds "docs" and Agent A tries to claim "docs"?
    # Let's inspect the exact database table:
    with closing(leases._connect()) as con:
        rows = con.execute("SELECT owner, blocked_by, requested_path FROM lease_waits").fetchall()
        assert len(rows) == 0, f"Expected lease_waits to be cleaned after release, but found orphaned rows: {rows}"
