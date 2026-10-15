from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock

import pytest

from local_ai_hub.cache import MemoryLRUCache, SingleFlightCache
from local_ai_hub.services import LocalAIServices


class RecordingFlight:
    def __init__(self) -> None:
        self.keys: list[str] = []
        self.values: dict[str, object] = {}

    def get_or_compute(self, key, compute):
        self.keys.append(key)
        if key in self.values:
            return self.values[key], True, False
        value = compute()
        self.values[key] = value
        return value, False, False


def _service(state, flight=None) -> LocalAIServices:
    service = object.__new__(LocalAIServices)
    service._touch_project = lambda _root: None
    service._repo_cache_state = lambda _root: state
    service.repo_flight = flight or RecordingFlight()
    return service


def test_repository_cache_isolated_by_physical_root(tmp_path: Path) -> None:
    first_root = tmp_path / "clone-one"
    second_root = tmp_path / "clone-two"
    first_root.mkdir()
    second_root.mkdir()
    flight = SingleFlightCache(
        MemoryLRUCache(max_entries=16, shards=1), wait_timeout_seconds=2, shards=1,
    )
    service = _service({"fingerprint": "same-head-and-dirty-state", "kind": "indexed"}, flight)
    calls = 0
    calls_lock = Lock()
    both_computing = Barrier(2)

    def compute_for(root: Path):
        def compute():
            nonlocal calls
            with calls_lock:
                calls += 1
            both_computing.wait(timeout=1)
            return {"success": True, "root": str(root)}
        return compute

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(service._repo_cached, "search", str(first_root), {"query": "same"}, compute_for(first_root))
        second_future = pool.submit(service._repo_cached, "search", str(second_root), {"query": "same"}, compute_for(second_root))
        first = first_future.result(timeout=3)
        second = second_future.result(timeout=3)

    assert first["root"] == str(first_root)
    assert second["root"] == str(second_root)
    assert first["cache_hit"] is False and first["coalesced"] is False
    assert second["cache_hit"] is False and second["coalesced"] is False
    assert calls == 2
    assert flight.hits == 0
    assert flight.coalesced_waiters == 0


def test_repository_cache_collapses_lexical_alias_for_same_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    alias = root / "child" / ".."
    flight = RecordingFlight()
    service = _service({"fingerprint": "same", "kind": "indexed"}, flight)
    calls = 0

    def compute():
        nonlocal calls
        calls += 1
        return {"success": True, "value": ["cached"]}

    first = service._repo_cached("search", str(root), {"query": "same"}, compute)
    second = service._repo_cached("search", str(alias), {"query": "same"}, compute)

    assert len(set(flight.keys)) == 1
    assert calls == 1
    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    second["value"].append("caller mutation")
    assert first["value"] == ["cached"]


@pytest.mark.parametrize(
    "state",
    [{}, {"fingerprint": None}, {"fingerprint": ""}, {"fingerprint": 0}, {"fingerprint": False}],
)
def test_invalid_repository_fingerprint_bypasses_cache_and_coalescing(state) -> None:
    class ForbiddenFlight:
        def get_or_compute(self, *_args, **_kwargs):
            raise AssertionError("invalid fingerprint must bypass cache and single-flight")

    service = _service(state, ForbiddenFlight())
    calls = 0
    shared = {"success": True, "value": ["original"]}

    def compute():
        nonlocal calls
        calls += 1
        return shared

    first = service._repo_cached("search", "C:/repo", {"query": "same"}, compute)
    first["value"].append("caller mutation")
    second = service._repo_cached("search", "C:/repo", {"query": "same"}, compute)

    assert calls == 2
    assert first["cache_hit"] is False and first["coalesced"] is False
    assert second["cache_hit"] is False and second["coalesced"] is False
    assert first["workspace_cache"]["degraded"] is True
    assert first["workspace_cache"]["reason"] == "missing_or_invalid_fingerprint"
    assert first["cache_layer"] == "workspace-miss"
    assert second["value"] == ["original"]
