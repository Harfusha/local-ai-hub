from __future__ import annotations

from pathlib import Path
import pytest

from local_ai_hub.commands import (
    CommandBroker,
    cluster_stack_traces,
    deduplicate_stack_traces,
)


SAMPLE_TRACEBACK_1 = """\
Traceback (most recent call last):
  File "src/runner.py", line 42, in execute
    result = compute(item)
  File "src/compute.py", line 15, in compute
    raise ValueError("invalid value in computation")
ValueError: invalid value in computation
"""

SAMPLE_TRACEBACK_2 = """\
Traceback (most recent call last):
  File "src/runner.py", line 45, in execute
    result = parse(item)
  File "src/parser.py", line 88, in parse
    raise KeyError("missing token")
KeyError: missing token
"""


def test_cluster_stack_traces_finds_repetitions() -> None:
    text = (
        "Starting test suite...\n"
        + SAMPLE_TRACEBACK_1 + "\n"
        + "Running next batch...\n"
        + SAMPLE_TRACEBACK_1 + "\n"
        + "Running third batch...\n"
        + SAMPLE_TRACEBACK_1 + "\n"
        + "Finished tests with failures.\n"
    )

    result = cluster_stack_traces(text)

    assert result["total_traces"] == 3
    assert len(result["clusters"]) == 1
    cluster = result["clusters"][0]
    assert cluster["count"] == 3
    assert "ValueError: invalid value in computation" in cluster["signature"]


def test_deduplicate_stack_traces_collapses_duplicates() -> None:
    text = (
        "=== Failure Log ===\n"
        + (SAMPLE_TRACEBACK_1 + "\nIntermittent message\n") * 4
        + "=== End Log ===\n"
    )

    compacted, meta = deduplicate_stack_traces(text, max_repeats=1)

    assert meta["total_collapsed"] == 3
    assert meta["chars_saved"] > 0
    # First instance preserved
    assert "ValueError: invalid value in computation" in compacted
    # Redundant occurrences replaced with collapse indicator
    assert "identical stack trace omitted" in compacted or "repeated" in compacted
    assert meta["unique_clusters"] == 1


def test_single_stack_trace_untouched() -> None:
    text = "Error occurred:\n" + SAMPLE_TRACEBACK_1 + "Done.\n"

    compacted, meta = deduplicate_stack_traces(text)

    assert meta["total_collapsed"] == 0
    assert meta["chars_saved"] == 0
    assert compacted == text


def test_mixed_stack_trace_clusters() -> None:
    text = (
        "Batch 1:\n" + SAMPLE_TRACEBACK_1 + "\n"
        "Batch 2:\n" + SAMPLE_TRACEBACK_2 + "\n"
        "Batch 3:\n" + SAMPLE_TRACEBACK_1 + "\n"
        "Batch 4:\n" + SAMPLE_TRACEBACK_2 + "\n"
    )

    result = cluster_stack_traces(text)

    assert result["total_traces"] == 4
    assert len(result["clusters"]) == 2
    counts = {c["exception_type"]: c["count"] for c in result["clusters"]}
    assert counts["ValueError"] == 2
    assert counts["KeyError"] == 2


def test_command_broker_compact_deduplicates_repetitive_traces(tmp_path: Path) -> None:
    cfg = {"server": {"state_dir": str(tmp_path / "state")}}
    broker = CommandBroker(cfg)

    repetitive_output = (SAMPLE_TRACEBACK_1 + "\n") * 5
    raw_result = {
        "stdout": "Running tests...\n" + repetitive_output,
        "stderr": "",
        "exit_code": 1,
        "success": False,
    }

    compacted = broker._compact(raw_result, command="pytest")

    assert "stack_trace_clusters" in compacted
    assert len(compacted["stack_trace_clusters"]) == 1
    assert compacted["stack_trace_clusters"][0]["count"] == 5
    assert compacted["stdout"].count("raise ValueError") == 1
