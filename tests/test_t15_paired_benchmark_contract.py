from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools import t15_paired_benchmark as paired


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _harness_sha() -> str:
    return hashlib.sha256(Path(paired.__file__).read_bytes()).hexdigest()


def _runtime_sha() -> str:
    return paired.runtime_fingerprint()["sha256"]


def _config_sha(value: str = "config") -> str:
    return paired.config_sha256(value)


def _fixture_source(root: Path) -> None:
    package = root / "src" / "local_ai_hub"
    package.mkdir(parents=True)
    (package / "commands.py").write_text("VALUE = 'base'\n", encoding="utf-8")
    (package / "cache.py").write_text("CACHE = True\n", encoding="utf-8")


def test_build_overlay_pins_exact_patch_and_only_changes_allowed_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _fixture_source(source)
    patch = tmp_path / "t15.patch"
    patch.write_text(
        "diff --git a/src/local_ai_hub/commands.py b/src/local_ai_hub/commands.py\n"
        "--- a/src/local_ai_hub/commands.py\n"
        "+++ b/src/local_ai_hub/commands.py\n"
        "@@ -1 +1 @@\n"
        "-VALUE = 'base'\n"
        "+VALUE = 't15'\n",
        encoding="utf-8",
    )
    patch_hash = hashlib.sha256(patch.read_bytes()).hexdigest()

    baseline = paired.baseline_input(
        source,
        config_sha256=_config_sha(),
        harness_sha256=_harness_sha(),
        runtime_sha256=_runtime_sha(),
    )
    overlay = paired.build_overlay(
        source,
        patch,
        tmp_path / "overlay",
        expected_patch_sha256=patch_hash,
        allowed_paths=["src/local_ai_hub/commands.py"],
        config_sha256=_config_sha(),
        harness_sha256=_harness_sha(),
        runtime_sha256=_runtime_sha(),
    )

    paired.validate_comparable_inputs(baseline, overlay)
    assert overlay["base_source_sha256"] == baseline["source_sha256"]
    assert overlay["source_sha256"] != baseline["source_sha256"]
    assert overlay["overlay_patch_sha256"] == patch_hash
    assert overlay["overlay_paths"] == ["src/local_ai_hub/commands.py"]
    assert (source / "src/local_ai_hub/commands.py").read_text() == "VALUE = 'base'\n"
    assert (tmp_path / "overlay/src/local_ai_hub/commands.py").read_text() == "VALUE = 't15'\n"


def test_overlay_rejects_patch_outside_t15_allowlist(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _fixture_source(source)
    patch = tmp_path / "unowned.patch"
    patch.write_text(
        "diff --git a/src/local_ai_hub/cache.py b/src/local_ai_hub/cache.py\n"
        "--- a/src/local_ai_hub/cache.py\n"
        "+++ b/src/local_ai_hub/cache.py\n"
        "@@ -1 +1 @@\n"
        "-CACHE = True\n"
        "+CACHE = False\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="outside declared T15 paths"):
        paired.build_overlay(
            source,
            patch,
            tmp_path / "overlay",
            expected_patch_sha256=hashlib.sha256(patch.read_bytes()).hexdigest(),
            allowed_paths=["src/local_ai_hub/commands.py"],
            config_sha256=_config_sha(),
            harness_sha256=_harness_sha(),
            runtime_sha256=_runtime_sha(),
        )


def test_paired_measurement_rejects_incomparable_config_before_running(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _fixture_source(source)
    baseline = paired.baseline_input(
        source,
        config_sha256=_config_sha("config-a"),
        harness_sha256=_harness_sha(),
        runtime_sha256=_runtime_sha(),
    )
    patch = tmp_path / "t15.patch"
    patch.write_text(
        "diff --git a/src/local_ai_hub/commands.py b/src/local_ai_hub/commands.py\n"
        "--- a/src/local_ai_hub/commands.py\n"
        "+++ b/src/local_ai_hub/commands.py\n"
        "@@ -1 +1 @@\n"
        "-VALUE = 'base'\n"
        "+VALUE = 'overlay'\n",
        encoding="utf-8",
    )
    overlay = paired.build_overlay(
        source,
        patch,
        tmp_path / "overlay",
        expected_patch_sha256=hashlib.sha256(patch.read_bytes()).hexdigest(),
        allowed_paths=["src/local_ai_hub/commands.py"],
        config_sha256=_config_sha("config-a"),
        harness_sha256=_harness_sha(),
        runtime_sha256=_runtime_sha(),
    )
    overlay["config_sha256"] = _config_sha("config-b")
    calls: list[str] = []

    with pytest.raises(ValueError, match="config_sha256 differs"):
        paired.measure_paired(
            baseline,
            overlay,
            lambda: calls.append("baseline") or 1.0,
            lambda: calls.append("overlay") or 1.0,
            pairs=4,
            seed=37,
        )
    assert calls == []


def test_synthetic_paired_receipt_has_randomized_order_stats_and_no_claim(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _fixture_source(source)
    patch = tmp_path / "t15.patch"
    patch.write_text(
        "diff --git a/src/local_ai_hub/commands.py b/src/local_ai_hub/commands.py\n"
        "--- a/src/local_ai_hub/commands.py\n"
        "+++ b/src/local_ai_hub/commands.py\n"
        "@@ -1 +1 @@\n"
        "-VALUE = 'base'\n"
        "+VALUE = 'overlay'\n",
        encoding="utf-8",
    )
    hashes = {
        "config_sha256": _config_sha(),
        "harness_sha256": _harness_sha(),
        "runtime_sha256": _runtime_sha(),
    }
    baseline = paired.baseline_input(source, **hashes)
    overlay = paired.build_overlay(
        source,
        patch,
        tmp_path / "overlay",
        expected_patch_sha256=hashlib.sha256(patch.read_bytes()).hexdigest(),
        allowed_paths=["src/local_ai_hub/commands.py"],
        **hashes,
    )
    baseline_values = iter([99.0, 1.0, 2.0, 3.0, 4.0])
    overlay_values = iter([199.0, 2.0, 4.0, 6.0, 8.0])

    receipt = paired.measure_paired(
        baseline,
        overlay,
        lambda: next(baseline_values),
        lambda: next(overlay_values),
        pairs=4,
        warmups=1,
        seed=73,
    )

    assert receipt["performance_claim"] is False
    assert receipt["input_hashes"]["config_sha256"] == hashes["config_sha256"]
    assert receipt["input_hashes"]["harness_sha256"] == hashes["harness_sha256"]
    assert receipt["input_hashes"]["overlay_patch_sha256"] == overlay["overlay_patch_sha256"]
    assert receipt["order_seed"] == 73
    assert len(receipt["raw_pairs"]) == 4
    expected_orders = paired._paired_orders(4, seed=73)
    assert expected_orders == paired._paired_orders(4, seed=73)
    assert [row["order"] for row in receipt["raw_pairs"]] == [
        "_then_".join(order) for order in expected_orders
    ]
    assert receipt["order_counts"] == {
        "baseline_then_overlay": 2,
        "overlay_then_baseline": 2,
    }
    assert {row["order"] for row in receipt["raw_pairs"]} == {
        "baseline_then_overlay",
        "overlay_then_baseline",
    }
    assert receipt["baseline_ms"]["median"] == 2.5
    assert receipt["baseline_ms"]["p95"] == 4.0
    assert receipt["baseline_ms"]["sample_variance"] == pytest.approx(1.667)
    assert receipt["overlay_ms"]["median"] == 5.0
    assert receipt["overlay_ms"]["p95"] == 8.0
    json.dumps(receipt)


def test_receipt_writer_refuses_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "receipt.json"
    receipt = {"schema": "t15-paired-overlay-v1", "performance_claim": False}

    paired.write_receipt(receipt, output)
    assert json.loads(output.read_text(encoding="utf-8")) == receipt
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        paired.write_receipt(receipt, output)


def test_exclusive_benchmark_lock_rejects_competing_run(tmp_path: Path, monkeypatch) -> None:
    lock = tmp_path / "local-ai-hub-t15-paired-benchmark.lock"
    monkeypatch.setattr(paired.tempfile, "gettempdir", lambda: str(tmp_path))
    lock.write_text("pid=other\n", encoding="ascii")

    with pytest.raises(RuntimeError, match="another T15 paired benchmark"):
        with paired._exclusive_benchmark_lock():
            pytest.fail("competing benchmark must be rejected")


def test_project_benchmark_config_pins_cache_and_stream_scenarios_separately() -> None:
    argv = ["python", "-B", "-c", "print('t15-paired-ok')"]

    cache_config, cache_hash = paired.project_benchmark_config(
        argv, case="warm_success_cache"
    )
    stream_config, stream_hash = paired.project_benchmark_config(
        argv, case="stream_callback"
    )

    assert cache_config == stream_config
    assert cache_hash != stream_hash


def test_stream_command_emits_stdout_and_stderr_for_callback_capture() -> None:
    argv = paired.stream_command_argv()

    assert argv[:2] == [paired.sys.executable, "-B"]
    assert "print('t15-paired-ok')" in argv[-1]
    assert "sys.stderr.write" in argv[-1]


def test_broker_worker_supports_forced_callback_stream_samples() -> None:
    compile(paired._BROKER_WORKER, "t15-paired-broker-worker", "exec")

    assert 'request.get("force", False)' in paired._BROKER_WORKER
    assert 'request.get("capture_logs")' in paired._BROKER_WORKER
    assert '"callback_chunks"' in paired._BROKER_WORKER


def test_diagnostic_pair_allows_different_source_pins_but_never_claims_acceptance(
    tmp_path: Path,
) -> None:
    baseline_root = tmp_path / "baseline"
    current_root = tmp_path / "current"
    _fixture_source(baseline_root)
    _fixture_source(current_root)
    (current_root / "src/local_ai_hub/commands.py").write_text(
        "VALUE = 'current'\n", encoding="utf-8"
    )
    shared = {
        "config_sha256": _config_sha(),
        "harness_sha256": _harness_sha(),
        "runtime_sha256": _runtime_sha(),
    }
    baseline = paired.checkout_input(baseline_root, **shared)
    current = paired.checkout_input(current_root, **shared)
    calls: list[str] = []

    receipt = paired.measure_paired_diagnostic(
        baseline,
        current,
        lambda: calls.append("baseline") or 1.0,
        lambda: calls.append("current") or 1.25,
        pairs=4,
        warmups=1,
        seed=91,
    )

    assert calls.count("baseline") == 5
    assert calls.count("current") == 5
    assert receipt["comparison_trusted"] is False
    assert receipt["performance_claim"] is False
    assert receipt["comparison_reasons"] == ["source hashes differ"]
    assert receipt["baseline_ms"]["median"] == 1.0
    assert receipt["current_ms"]["median"] == 1.25


def test_diagnostic_pair_rejects_config_mismatch_before_measurement(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _fixture_source(source)
    baseline = paired.checkout_input(
        source,
        config_sha256=_config_sha("cold"),
        harness_sha256=_harness_sha(),
        runtime_sha256=_runtime_sha(),
    )
    current = paired.checkout_input(
        source,
        config_sha256=_config_sha("warm"),
        harness_sha256=_harness_sha(),
        runtime_sha256=_runtime_sha(),
    )
    calls: list[str] = []

    with pytest.raises(ValueError, match="config_sha256 differs"):
        paired.measure_paired_diagnostic(
            baseline,
            current,
            lambda: calls.append("baseline") or 1.0,
            lambda: calls.append("current") or 1.0,
            pairs=2,
            warmups=0,
            seed=2,
        )
    assert calls == []


def test_paired_measurement_rejects_source_drift(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _fixture_source(source)
    patch = tmp_path / "t15.patch"
    patch.write_text(
        "diff --git a/src/local_ai_hub/commands.py b/src/local_ai_hub/commands.py\n"
        "--- a/src/local_ai_hub/commands.py\n"
        "+++ b/src/local_ai_hub/commands.py\n"
        "@@ -1 +1 @@\n"
        "-VALUE = 'base'\n"
        "+VALUE = 'overlay'\n",
        encoding="utf-8",
    )
    hashes = {
        "config_sha256": _config_sha(),
        "harness_sha256": _harness_sha(),
        "runtime_sha256": _runtime_sha(),
    }
    baseline = paired.baseline_input(source, **hashes)
    overlay = paired.build_overlay(
        source,
        patch,
        tmp_path / "overlay",
        expected_patch_sha256=hashlib.sha256(patch.read_bytes()).hexdigest(),
        allowed_paths=["src/local_ai_hub/commands.py"],
        **hashes,
    )

    def mutate_baseline() -> float:
        (source / "src/local_ai_hub/commands.py").write_text("VALUE = 'drift'\n")
        return 1.0

    with pytest.raises(RuntimeError, match="source changed during paired benchmark"):
        paired.measure_paired(
            baseline,
            overlay,
            mutate_baseline,
            lambda: 1.0,
            pairs=1,
            warmups=0,
            seed=19,
        )
