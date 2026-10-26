from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from local_ai_hub.token_accounting import (
    _streaming_json_tokens,
    json_tokens,
)


def _assert_parity(value: Any) -> None:
    expected = _streaming_json_tokens(value)
    actual = json_tokens(value)
    assert actual == expected, f"Parity mismatch for {value!r}: actual={actual} != expected={expected}"


def test_parity_basic_primitives():
    cases = [
        None,
        True,
        False,
        0,
        1,
        -1,
        42,
        3.14159,
        -0.0,
        "",
        "hello world",
        [],
        {},
    ]
    for case in cases:
        _assert_parity(case)


def test_parity_unicode_and_special_characters():
    cases = [
        "Příliš žluťoučký kůň úpěl ďábelské ódy",
        "🚀 Antigravity / Local AI Hub 💻 🎉",
        "雪 / こんにちは世界 / 中文测试",
        "αβγδε / café / naïve / résumé",
        "Line 1\nLine 2\tTabbed\r\nCarriage",
        "Quotes: \"double\" and 'single' and \\backslash\\",
        "JSON escape chars: \b \f \t \n \r",
    ]
    for text in cases:
        _assert_parity({"text": text, "nested": [text, {"inner": text}]})


def test_parity_integer_boundaries():
    # Exactly at int64 boundaries
    max_int64 = (1 << 63) - 1
    min_int64 = -(1 << 63)
    _assert_parity({"max_int64": max_int64, "min_int64": min_int64})

    # Integers exceeding 64-bit range (should trigger fallback to streaming)
    huge_pos = 1 << 65
    huge_neg = -(1 << 65)
    _assert_parity({"huge_pos": huge_pos, "huge_neg": huge_neg, "normal": 100})


def test_parity_float_edge_cases():
    # Negative zero and exponents
    _assert_parity({"neg_zero": -0.0, "small": 1e-10, "large": 1e20, "exp": 2.5e-5})

    # Non-finite floats: NaN, +Inf, -Inf (should trigger fallback to streaming)
    _assert_parity({"nan": float("nan")})
    _assert_parity({"inf": float("inf")})
    _assert_parity({"neg_inf": float("-inf")})
    _assert_parity({
        "status": "ok",
        "metrics": [1.0, float("nan"), 3.5, float("inf"), -2.0, float("-inf")],
        "metadata": {"score": float("nan")},
    })


def test_parity_non_string_keys():
    # Integer and float keys
    int_keys = {
        10: "ten",
        20: "twenty",
        100: "hundred",
    }
    bool_keys = {
        True: "true_val",
        False: "false_val",
    }
    _assert_parity(int_keys)
    _assert_parity(bool_keys)


def test_parity_custom_objects_default_str():
    # Objects serialized via default=str
    data = {
        "file_path": Path("src/local_ai_hub/token_accounting.py"),
        "nested_paths": [Path("a/b/c"), Path("d/e/f")],
    }
    _assert_parity(data)


def test_parity_surrogate_and_invalid_keys_recovery():
    # Lone surrogate string
    surrogate_payload = {"surrogate": "\ud83d"}
    _assert_parity(surrogate_payload)

    # Non-serializable key (tuple key)
    tuple_key_payload = {(1, 2): "invalid_key"}
    _assert_parity(tuple_key_payload)


def test_parity_deeply_nested_structures():
    # 20 levels of nesting
    nested: dict[str, Any] = {"level": 0}
    curr = nested
    for i in range(1, 20):
        curr["child"] = {"level": i, "items": [i, i * 2]}
        curr = curr["child"]
    _assert_parity(nested)


def test_parity_cyclic_structure_recovery():
    cyclic: dict[str, Any] = {"name": "cyclic"}
    cyclic["self"] = cyclic
    # Both fast and streaming paths must safely recover without crashing
    _assert_parity(cyclic)


def test_parity_realistic_agent_payloads():
    # Realistic Task list payload (~5 KiB)
    task_payload = {
        "success": True,
        "tasks": [
            {
                "task_id": f"task-20261025-0{i}",
                "status": "in_progress" if i % 2 == 0 else "completed",
                "owner": "agent_os",
                "contract": {
                    "goal": f"Execute benchmark cohort {i} and measure latency regressions",
                    "acceptance_criteria": ["All tests pass", "No timeout", "Clean receipts"],
                },
                "checkpoint": {
                    "phase": f"phase_{i}",
                    "next_action": f"validate_milestone_{i}",
                    "affected_paths": [f"src/module_{i}.py", f"tests/test_module_{i}.py"],
                },
            }
            for i in range(25)
        ],
        "total_count": 25,
        "request_id": "req_bench_realistic_01",
    }
    _assert_parity(task_payload)

    # Realistic Memory records payload (~15 KiB)
    memory_payload = {
        "success": True,
        "records": [
            {
                "record_id": f"rec_{i:04d}",
                "scope": "project",
                "scope_id": "proj_hub_main",
                "operation_class": "architecture_fact",
                "key": f"convention.routing.rule_{i}",
                "value": f"Fast backend routing requires fallback for non-finite floats and int64 boundaries in rule {i}",
                "score": 0.85 + (i % 15) * 0.01,
            }
            for i in range(100)
        ],
        "total_records": 100,
    }
    _assert_parity(memory_payload)


def test_performance_speedup_on_realistic_payloads():
    # Generate realistic 50 KiB payload
    payload = {
        "success": True,
        "results": [
            {
                "path": f"src/local_ai_hub/component_{i}.py",
                "line": i * 10,
                "text": f"def process_chunk_{i}(data: list[dict[str, Any]]) -> dict[str, Any]: return {{'chunk_id': {i}}}",
                "score": 0.95 - i * 0.001,
                "symbols": [f"process_chunk_{i}", f"HelperClass_{i}"],
            }
            for i in range(200)
        ],
        "request_id": "req_perf_benchmark_test",
    }

    # Verify exact parity
    _assert_parity(payload)

    # Warmup
    for _ in range(3):
        _streaming_json_tokens(payload)
        json_tokens(payload)

    # Measure streaming baseline (15 iterations)
    t0 = time.perf_counter()
    for _ in range(15):
        _streaming_json_tokens(payload)
    t_streaming = time.perf_counter() - t0

    # Measure fast json_tokens (15 iterations)
    t1 = time.perf_counter()
    for _ in range(15):
        json_tokens(payload)
    t_fast = time.perf_counter() - t1

    # Verify speedup
    speedup_ratio = t_streaming / max(1e-6, t_fast)
    print(f"\nThroughput benchmark: streaming={t_streaming*1000:.2f}ms, fast={t_fast*1000:.2f}ms, speedup={speedup_ratio:.1f}x")
    if sys.gettrace() is not None or os.environ.get("CI"):
        # Under CI virtual runners or coverage tracing, scheduling jitter can distort microbenchmarks
        assert t_fast <= t_streaming * 1.05, f"Expected fast to not be slower than streaming, got {speedup_ratio:.2f}x"
    else:
        assert t_fast < t_streaming * 0.80, f"Expected >= 20% speedup, got {speedup_ratio:.2f}x (fast={t_fast*1000:.2f}ms vs streaming={t_streaming*1000:.2f}ms)"
