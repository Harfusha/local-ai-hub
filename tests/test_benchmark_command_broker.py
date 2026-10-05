from __future__ import annotations

from types import SimpleNamespace

import pytest

from tools import benchmark_command_broker as benchmark


def test_pair_orders_are_balanced_and_reproducible() -> None:
    first = benchmark._pair_orders(12, seed=731)
    second = benchmark._pair_orders(12, seed=731)

    assert first == second
    assert first.count(("hit", "miss")) == 6
    assert first.count(("miss", "hit")) == 6


def test_pair_order_summary_keeps_hit_and_miss_strata_separate() -> None:
    rows = [
        {"order": "hit_then_miss", "hit_ms": 10.0, "miss_ms": 100.0},
        {"order": "hit_then_miss", "hit_ms": 12.0, "miss_ms": 120.0},
        {"order": "miss_then_hit", "hit_ms": 160.0, "miss_ms": 210.0},
        {"order": "miss_then_hit", "hit_ms": 180.0, "miss_ms": 230.0},
    ]

    summary = benchmark._pair_order_summary(rows)

    assert summary["hit_then_miss"]["n"] == 2
    assert summary["hit_then_miss"]["cache_hit"]["p50"] == 10.0
    assert summary["miss_then_hit"]["n"] == 2
    assert summary["miss_then_hit"]["cache_hit"]["p50"] == 160.0


class _CachePairBroker:
    def __init__(self) -> None:
        self.calls = []

    def run(self, command, root, *, tenant, force=False):
        self.calls.append((command, root, tenant, force))
        return {"success": True, "cache_hit": not force}


@pytest.fixture
def cache_pair_broker() -> _CachePairBroker:
    return _CachePairBroker()


def test_cache_pairs_use_same_command_and_account_for_each_outcome(
    tmp_path, cache_pair_broker: _CachePairBroker
) -> None:
    broker = cache_pair_broker

    result = benchmark._measure_cache_pairs(
        broker,
        str(tmp_path),
        paired_runs=8,
        order_seed=41,
    )

    assert len(result["pairs"]) == 8
    assert all(call[0] == benchmark.COMMAND for call in broker.calls)
    assert sum(call[3] for call in broker.calls) == 9  # seed plus one forced miss per pair
    assert sum(not call[3] for call in broker.calls) == 8
    assert result["orders"] == benchmark._pair_orders(8, seed=41)
    assert result["cache_accounting"] == {
        "paired_operations": 16,
        "expected_hits": 8,
        "observed_hits": 8,
        "expected_misses": 8,
        "observed_misses": 8,
        "classification_complete": True,
        "seed_miss_counted": False,
    }
    assert result["fixture"] == {
        "command": benchmark.COMMAND,
        "tenant": "t15-benchmark",
        "forced_seed_cache_hit": False,
        "seed_counted_in_pairs": False,
        "paired_runs": 8,
        "pair_order_seed": 41,
        "order_counts": {"hit_then_miss": 4, "miss_then_hit": 4},
    }
    assert all(pair["hit_cache_hit"] is True for pair in result["pairs"])
    assert all(pair["miss_cache_hit"] is False for pair in result["pairs"])


def test_cache_pairs_reject_missing_cache_outcome(tmp_path) -> None:
    broker = _CachePairBroker()
    original_run = broker.run

    def run_without_one_outcome(command, root, *, tenant, force=False):
        result = original_run(command, root, tenant=tenant, force=force)
        if len(broker.calls) == 2:
            result.pop("cache_hit")
        return result

    broker.run = run_without_one_outcome

    with pytest.raises(RuntimeError, match="did not report a boolean cache outcome"):
        benchmark._measure_cache_pairs(
            broker,
            str(tmp_path),
            paired_runs=1,
            order_seed=3,
        )


@pytest.mark.parametrize("cache_hit", [True, False])
def test_cache_outcome_accepts_only_boolean_classification(cache_hit) -> None:
    assert benchmark._require_cache_outcome({"cache_hit": cache_hit}, "sample") is cache_hit

    for invalid in (None, 1, "true"):
        with pytest.raises(RuntimeError, match="did not report a boolean cache outcome"):
            benchmark._require_cache_outcome({"cache_hit": invalid}, "sample")


def test_concurrent_cache_receipt_preserves_each_ordered_sample() -> None:
    receipt = benchmark._concurrent_cache_sample_receipts([(1.23456789, True), (2.0, False)])

    assert receipt == [
        {"sample_index": 0, "elapsed_ms": 1.234568, "cache_hit": True},
        {"sample_index": 1, "elapsed_ms": 2.0, "cache_hit": False},
    ]


def test_broker_shell_path_matches_platform_resolution_order(monkeypatch) -> None:
    available = {"pwsh": None, "powershell": r"C:\Tools\powershell.exe", "sh": "/custom/bin/sh"}
    monkeypatch.setattr(benchmark.shutil, "which", lambda name: available.get(name))

    assert benchmark._broker_shell_path(windows=True) == r"C:\Tools\powershell.exe"
    assert benchmark._broker_shell_path(windows=False) == "/custom/bin/sh"
    available["pwsh"] = r"C:\Tools\pwsh.exe"
    assert benchmark._broker_shell_path(windows=True) == r"C:\Tools\pwsh.exe"


def test_revision_gate_requires_clean_matching_checkouts() -> None:
    source = {"head": "abc", "dirty": False}
    execution = {"head": "abc", "dirty": False}

    benchmark._validate_revision_match(source, execution)

    with pytest.raises(RuntimeError, match="clean"):
        benchmark._validate_revision_match({**source, "dirty": True}, execution)
    with pytest.raises(RuntimeError, match="same pinned revision"):
        benchmark._validate_revision_match(source, {**execution, "head": "def"})


def test_source_snapshot_hashes_command_file_from_selected_checkout(tmp_path, monkeypatch) -> None:
    command_file = tmp_path / "src" / "local_ai_hub" / "commands.py"
    command_file.parent.mkdir(parents=True)
    command_file.write_text("selected checkout", encoding="utf-8")
    monkeypatch.setattr(benchmark, "_git_identity", lambda _root: {"head": "abc", "dirty": False})

    snapshot = benchmark._source_snapshot(tmp_path)

    assert snapshot["commands_sha256"] == benchmark.hashlib.sha256(b"selected checkout").hexdigest()


def test_command_api_imports_from_selected_checkout(tmp_path, monkeypatch) -> None:
    package_dir = tmp_path / "src" / "local_ai_hub"
    package_dir.mkdir(parents=True)
    command_file = package_dir / "commands.py"
    command_file.write_text("# selected checkout", encoding="utf-8")
    broker_type = type("SelectedBroker", (), {})
    cache_module = SimpleNamespace(stable_hash=lambda _value: "stable")
    commands_module = SimpleNamespace(__file__=str(command_file), CommandBroker=broker_type)
    imports = []

    def import_module(name: str):
        imports.append(name)
        return cache_module if name.endswith("cache") else commands_module

    monkeypatch.setattr(benchmark.importlib, "import_module", import_module)
    monkeypatch.setattr(benchmark.sys, "path", [])

    stable_hash, command_broker = benchmark._load_command_api(tmp_path)

    assert stable_hash("value") == "stable"
    assert command_broker is broker_type
    assert imports == ["local_ai_hub.cache", "local_ai_hub.commands"]
    assert benchmark.sys.path[0] == str(tmp_path / "src")


class _CaptureBroker:
    def __init__(self) -> None:
        self.callbacks = []

    def _execute(self, _command, _root, _timeout, *, log_callback=None):
        stdout = ("O" * 64 + "\n") * 2_000
        stderr = ("E" * 64 + "\n") * 2_000
        if log_callback is not None:
            log_callback("stdout", stdout)
            log_callback("stderr", stderr)
        self.callbacks.append(log_callback)
        return {
            "success": True,
            "stdout": stdout,
            "stderr": stderr,
            "log_chunks_dropped": 0,
            "log_dispatch_incomplete": False,
        }


def test_capture_fixture_measures_callback_and_no_callback_paths(tmp_path) -> None:
    broker = _CaptureBroker()

    with_callback = benchmark._capture_sample(broker, str(tmp_path), callback_enabled=True)
    without_callback = benchmark._capture_sample(broker, str(tmp_path), callback_enabled=False)

    assert broker.callbacks[0] is not None
    assert broker.callbacks[1] is None
    assert with_callback["callback_stdout_bytes"] == with_callback["stdout_bytes"]
    assert with_callback["callback_stderr_bytes"] == with_callback["stderr_bytes"]
    assert without_callback["callback_chunks"] == 0
    assert without_callback["stdout_bytes"] == with_callback["stdout_bytes"]
    assert without_callback["stderr_bytes"] == with_callback["stderr_bytes"]
