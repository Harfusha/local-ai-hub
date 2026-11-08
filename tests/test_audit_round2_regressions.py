"""Regression test suite for Audit Round 2 findings (N01 through N24).
Documented in docs/AUDIT_ROUND2.md and docs/AUDIT_ROUND2_PLAN.md.
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from local_ai_hub.agent_events import AgentStateStore, SwarmPubSub
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStore
from local_ai_hub.async_jobs import AsyncJobManager
from local_ai_hub.leases import ScopeLeaseStore
from local_ai_hub.preprocess_ingest import IngestedFile, SinglePassIngestCache
from local_ai_hub.token_router import LosslessTokenRouter


def test_t2_01_token_router_non_float_score_fallback():
    """T2-01 (N01): Non-float or invalid score in LLM ranges does not raise ValueError."""
    text = json.dumps({"ranges": [{"start": 2, "end": 6, "score": "high"}, {"start": 8, "end": 10, "score": None}]})
    ranges = LosslessTokenRouter._parse_ranges(text, max_line=20, max_ranges=5, context_lines=0)
    assert len(ranges) == 2
    assert ranges[0][0] == 2 and ranges[0][1] == 6 and ranges[0][2] == 1.0
    assert ranges[1][0] == 8 and ranges[1][1] == 10 and ranges[1][2] == 1.0


def test_t2_12_token_router_handles_extreme_and_malformed_ranges():
    """T03: 1,000 malformed or extreme model ranges stay bounded and exception-free."""
    values = [None, "bad", [], {}, True, -10**12, 10**12, float("inf"), float("nan")]
    for i in range(1000):
        start = values[i % len(values)] if i % 3 else i - 500
        end = values[(i + 3) % len(values)] if i % 4 else 100 - i
        score = values[(i + 6) % len(values)]
        raw = json.dumps({"ranges": [{"start": start, "end": end, "score": score}]})
        parsed = LosslessTokenRouter._parse_ranges(
            raw, max_line=100, max_ranges=5, context_lines=0
        )
        assert isinstance(parsed, list)
        assert len(parsed) <= 5


def test_t2_13_ingest_contention_isolated_across_roots(tmp_path: Path):
    """T02: Concurrent ingest of matching relative paths stays root-scoped and coalesced."""
    roots = [tmp_path / f"repo_{i}" for i in range(3)]
    for i, root in enumerate(roots):
        source = root / "src" / "main.py"
        source.parent.mkdir(parents=True)
        source.write_text(f"PROJECT_{i}\n", encoding="utf-8")

    cache = SinglePassIngestCache(max_entries=20, max_bytes=100_000)
    start_gate = threading.Barrier(12)
    read_counts: dict[Path, int] = {}
    counts_lock = threading.Lock()

    class SnapshotReader:
        def _read_snapshot(self, target: Path) -> tuple[str, list[str]]:
            with counts_lock:
                read_counts[target] = read_counts.get(target, 0) + 1
            lines = target.read_text(encoding="utf-8").splitlines()
            return f"sha-{target.parents[1].name}", lines

    reader = SnapshotReader()

    def ingest(root: Path):
        start_gate.wait(timeout=5)
        return cache.get_or_ingest(root, "src/main.py", reader)

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(ingest, roots * 4))

    for i, root in enumerate(roots):
        matching = [result for result in results if result.text == f"PROJECT_{i}"]
        assert len(matching) == 4
        assert cache.get("src/main.py", root=str(root)).text == f"PROJECT_{i}"
        assert read_counts[root / "src" / "main.py"] == 1


def test_t2_14_released_ancestor_lease_does_not_create_false_deadlock(tmp_path: Path):
    """T12: A waiting descendant acquires after the blocking ancestor releases."""
    leases = ScopeLeaseStore(state_dir=tmp_path / "state")
    root = tmp_path / "repo"
    root.mkdir()

    ancestor = leases.claim(
        owner="agent-parent", root=str(root), paths=["src"], ttl_seconds=600,
    )
    blocked = leases.claim(
        owner="agent-child", root=str(root), paths=["src/main.py"], ttl_seconds=600,
    )
    assert ancestor["success"] is True
    assert blocked["success"] is False
    assert blocked["deadlock"] is False

    released = leases.release(owner="agent-parent", lease_id=ancestor["lease_id"])
    assert released["success"] is True
    acquired = leases.claim(
        owner="agent-child", root=str(root), paths=["src/main.py"], ttl_seconds=600,
    )
    assert acquired["success"] is True


def test_t2_15_token_router_bounds_model_requested_output(tmp_path: Path):
    """T04: A selector requesting the whole source cannot exceed the output-line cap."""
    services = MagicMock()
    services._generate.return_value = {
        "success": True,
        "text": json.dumps({"ranges": [{"start": 1, "end": 300, "score": 1.0}]}),
    }
    router = LosslessTokenRouter(
        {
            "server": {"state_dir": str(tmp_path)},
            "lossless_router": {
                "enabled": True,
                "context_lines": 0,
                "max_output_lines": 20,
            },
        },
        services,
    )
    source = "\n".join(f"line {i} value" for i in range(1, 301))

    result = router.route_text(source, "target", force_local=True)

    assert result["success"] is True
    selected_lines = sum(item["end_line"] - item["start_line"] + 1 for item in result["evidence"])
    assert selected_lines <= 20
    assert len(result["context"]) < len(source)


def test_t2_16_async_burst_uses_bounded_dispatch_threads(tmp_path: Path):
    """T05: 256 accepted jobs do not create one live dispatch thread each."""
    entered = threading.Event()
    release = threading.Event()
    manager = AsyncJobManager(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "async_jobs": {"max_pending": 256, "max_workers": 4, "max_dispatch_workers": 3},
        },
        scheduler=object(),
        artifacts=object(),
        executor=lambda _action, _payload: {"success": True},
    )
    manager._resource_admission = lambda: {"state": "accepted"}

    def blocked_dispatch(_job_id: str) -> None:
        entered.set()
        release.wait(5)

    manager._dispatch = blocked_dispatch
    try:
        submitted = [
            manager.submit("reason", {"task": f"burst-{i}"})
            for i in range(256)
        ]
        assert all(item["success"] for item in submitted)
        assert entered.wait(5)
        with manager._lock:
            assert len(manager._dispatchers) <= manager.max_dispatch_workers == 3
        assert len([t for t in threading.enumerate() if t.name.startswith("async-dispatch-")]) <= 3
    finally:
        release.set()
        manager.close()


def test_t2_02_graph_traversal_closed_subgraph(tmp_path: Path):
    """T2-02 (N02): Graph traversal returns edges strictly between bounded nodes (closed subgraph)."""
    db_path = tmp_path / "graph_state.sqlite3"
    state_store = AgentStateStore(db_path=db_path)
    state_store._ensure_schema()
    mem_store = MemoryStore(state_store=state_store)

    # A -> B -> C -> D, with a cycle back to A.
    mem_store.record_relation("A", "calls", "B", weight=1.0)
    mem_store.record_relation("B", "calls", "C", weight=1.0)
    mem_store.record_relation("C", "calls", "D", weight=1.0)
    mem_store.record_relation("D", "calls", "A", weight=1.0)

    # Limit to max 2 nodes from A (A and B)
    traversal = mem_store.traverse_graph("A", max_depth=3, max_nodes=2)
    node_names = set(traversal["nodes"])
    assert len(node_names) <= 2
    assert "A" in node_names

    # All returned edges must connect only nodes that are in node_names
    for edge in traversal["edges"]:
        assert edge["source_entity"] in node_names
        assert edge["target_entity"] in node_names


def test_t2_03_memory_find_escapes_like_wildcards(tmp_path: Path):
    """T2-03 (N22): MemoryStore.find() escapes % and _ in LIKE queries."""
    db_path = tmp_path / "memory_state.sqlite3"
    state_store = AgentStateStore(db_path=db_path)
    state_store._ensure_schema()
    mem_store = MemoryStore(state_store=state_store)

    rec1 = MemoryRecord.create(
        scope=AgentScope.GLOBAL,
        key="exact_percent",
        value="value 100% discount",
        kind=MemoryKind.FACT,
    )
    rec2 = MemoryRecord.create(
        scope=AgentScope.GLOBAL,
        key="exact_wildcard",
        value="value 1000 discount",
        kind=MemoryKind.FACT,
    )
    mem_store.record(rec1)
    mem_store.record(rec2)

    matches = mem_store.find(scope=AgentScope.GLOBAL, query="100%", semantic=False)
    matched_keys = [m.key for m in matches]
    assert "exact_percent" in matched_keys
    assert "exact_wildcard" not in matched_keys


def test_t2_04_preprocess_ingest_root_isolation():
    """T2-04 (N11, N24): SinglePassIngestCache distinguishes identical relative paths across roots."""
    cache = SinglePassIngestCache(max_entries=10, max_bytes=100000)
    root1 = "C:/repo_one"
    root2 = "C:/repo_two"
    path = "src/main.py"

    cache.put(path, text="print('repo 1')", root=root1)
    cache.put(path, text="print('repo 2')", root=root2)

    assert cache.has(path, root=root1)
    assert cache.has(path, root=root2)

    item1 = cache.get(path, root=root1)
    item2 = cache.get(path, root=root2)
    assert item1 is not None and item1.text == "print('repo 1')"
    assert item2 is not None and item2.text == "print('repo 2')"

    cache.invalidate(path, root=root1)
    assert not cache.has(path, root=root1)
    assert cache.has(path, root=root2)


def test_t2_05_preprocess_ingest_rejects_oversized_file():
    """T2-05 (N21): Files exceeding max_bytes are not cached into memory."""
    cache = SinglePassIngestCache(max_entries=10, max_bytes=1024)
    large_text = "x" * 2048
    cache.put("large.py", text=large_text)
    assert not cache.has("large.py")
    assert len(cache) == 0


def test_t2_06_speculative_draft_reads_text_key(tmp_path: Path):
    """T2-06 (N08/A1): speculative_draft reads text key from generate result."""
    from local_ai_hub.services import LocalAIServices

    config = {
        "server": {"state_dir": str(tmp_path)},
        "models": {"fast_code": "test-model", "heavy_code": "test-heavy"},
    }
    services = LocalAIServices(
        config=config,
        runtime=MagicMock(),
        scheduler=MagicMock(),
        embeddings=MagicMock(),
        artifacts=MagicMock(),
        telemetry=MagicMock(),
        repo_tools=MagicMock(),
    )
    services._generate = MagicMock(return_value={
        "success": True,
        "text": "def calculate():\n    return 42\n",
    })

    result = services.speculative_draft({"task": "math function"})
    assert result["success"] is True
    assert result["draft"] == "def calculate():\n    return 42"


def test_t2_07_swarm_pubsub_publish_persists_events(tmp_path: Path):
    """T2-07 (Round 2 PubSub): SwarmPubSub appends events cleanly to state store."""
    db_path = tmp_path / "state.sqlite3"
    state_store = AgentStateStore(db_path=db_path)
    state_store._ensure_schema()

    pubsub = SwarmPubSub(state_store=state_store)
    res = pubsub.publish("notifications", message={"alert": "round2_ready"}, sender="agent_2")
    assert res["success"] is True


def test_t2_08_lease_release_scoped_wait_cleanup(tmp_path: Path):
    """T2-08 (N14): ScopeLeaseStore clean release of wait state."""
    leases = ScopeLeaseStore(state_dir=tmp_path)
    claim_a = leases.claim(owner="agent-a", root=str(tmp_path), paths=["file_a.py"], ttl_seconds=600)
    assert claim_a["success"] is True

    rel = leases.release(owner="agent-a", lease_id=claim_a["lease_id"])
    assert rel["success"] is True
    assert rel.get("released_rows", 1) >= 1


def test_t2_09_cache_shard_capacity_bounded():
    """T2-09 (N04): Small MemoryLRUCache bounds num_shards to not exceed max_entries."""
    from local_ai_hub.cache import MemoryLRUCache
    cache = MemoryLRUCache(max_entries=2, shards=16)
    assert cache.num_shards <= 2
    assert cache._shard_max >= 1


def test_t2_10_scheduler_enqueue_passes_model_admission():
    """T2-10 (N07): Scheduler.enqueue passes model to _admission."""
    from local_ai_hub.scheduler import Scheduler
    sched = Scheduler(max_concurrent=1, max_queue=10)
    admitted_models = []
    def mock_adm(*, background=False, model=""):
        admitted_models.append(model)
        return {"state": "accepted", "delay_seconds": 0.0}
    sched._admission = mock_adm
    sched.enqueue("qwen2.5-coder:7b", source="test", execute=lambda: {"success": True})
    assert "qwen2.5-coder:7b" in admitted_models


def test_t2_11_find_relations_source_and_target_filter(tmp_path: Path):
    """T2-11 (N13): find_relations supports simultaneous source_entity and target_entity filter."""
    db_path = tmp_path / "relations.sqlite3"
    state_store = AgentStateStore(db_path=db_path)
    state_store._ensure_schema()
    mem_store = MemoryStore(state_store=state_store)

    mem_store.record_relation("A", "calls", "B")
    mem_store.record_relation("A", "calls", "C")
    mem_store.record_relation("D", "calls", "B")

    res = mem_store.find_relations(source_entity="A", target_entity="B")
    assert len(res) == 1
    assert res[0]["source_entity"] == "A"
    assert res[0]["target_entity"] == "B"
