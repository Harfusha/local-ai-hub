from pathlib import Path
import pytest

from local_ai_hub.services import (
    merge_overlapping_line_ranges,
    merge_overlapping_evidence,
    LocalAIServices,
)


def test_merge_overlapping_line_ranges():
    # Empty
    assert merge_overlapping_line_ranges([]) == []

    # Single
    assert merge_overlapping_line_ranges([(10, 20)]) == [(10, 20)]

    # Disjoint
    assert merge_overlapping_line_ranges([(1, 5), (10, 15)]) == [(1, 5), (10, 15)]

    # Overlapping
    assert merge_overlapping_line_ranges([(1, 10), (5, 15)]) == [(1, 15)]

    # Fully contained
    assert merge_overlapping_line_ranges([(1, 20), (5, 12)]) == [(1, 20)]

    # Adjacent (within gap <= 1)
    assert merge_overlapping_line_ranges([(1, 10), (11, 20)]) == [(1, 20)]

    # Out of order
    assert merge_overlapping_line_ranges([(20, 30), (1, 10), (8, 15)]) == [(1, 15), (20, 30)]


def test_merge_overlapping_evidence_in_memory():
    evidence = [
        {
            "path": "src/module.py",
            "start_line": 10,
            "end_line": 20,
            "text": "line10\nline11\nline12\nline13\nline14\nline15\nline16\nline17\nline18\nline19\nline20",
            "score": 0.8,
            "symbol": "func_a",
        },
        {
            "path": "src/module.py",
            "start_line": 18,
            "end_line": 25,
            "text": "line18\nline19\nline20\nline21\nline22\nline23\nline24\nline25",
            "score": 0.95,
            "symbol": "func_b",
        },
        {
            "path": "src/other.py",
            "start_line": 1,
            "end_line": 5,
            "text": "l1\nl2\nl3\nl4\nl5",
            "score": 0.7,
        },
    ]

    merged = merge_overlapping_evidence(evidence)
    assert len(merged) == 2

    mod_item = next(item for item in merged if item["path"] == "src/module.py")
    assert mod_item["start_line"] == 10
    assert mod_item["end_line"] == 25
    assert mod_item["score"] == 0.95
    # Ensure lines are not duplicated in merged text
    lines = mod_item["text"].splitlines()
    assert len(lines) == 16
    assert lines[0] == "line10"
    assert lines[-1] == "line25"
    assert lines.count("line18") == 1
    assert lines.count("line19") == 1
    assert lines.count("line20") == 1


def test_merge_overlapping_evidence_with_disk_file(tmp_path: Path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    sample_file = src_dir / "app.py"
    file_lines = [f"# Line {i}" for i in range(1, 41)]
    sample_file.write_text("\n".join(file_lines) + "\n", encoding="utf-8")

    evidence = [
        {
            "path": "src/app.py",
            "start_line": 5,
            "end_line": 15,
            "text": "old snippet 1",
            "score": 0.5,
        },
        {
            "path": "src/app.py",
            "start_line": 12,
            "end_line": 22,
            "text": "old snippet 2",
            "score": 0.85,
        },
    ]

    merged = merge_overlapping_evidence(evidence, root=tmp_path)
    assert len(merged) == 1
    item = merged[0]
    assert item["start_line"] == 5
    assert item["end_line"] == 22
    assert item["score"] == 0.85
    lines = item["text"].splitlines()
    assert lines[0] == "# Line 5"
    assert lines[-1] == "# Line 22"
    assert len(lines) == 18


def test_services_method_integration():
    evidence = [
        {"path": "foo.py", "start_line": 1, "end_line": 10, "text": "a\nb\nc", "score": 0.6},
        {"path": "foo.py", "start_line": 5, "end_line": 15, "text": "c\nd\ne", "score": 0.9},
    ]
    res = LocalAIServices.merge_overlapping_evidence(evidence)
    assert len(res) == 1
    assert res[0]["start_line"] == 1
    assert res[0]["end_line"] == 15
    assert res[0]["score"] == 0.9


def test_merge_overlapping_evidence_edge_cases():
    # Empty
    assert merge_overlapping_evidence([]) == []

    # Non-dict items or missing paths
    assert merge_overlapping_evidence(["not-a-dict", {}, {"path": ""}]) == []

    # Same file, two separate disjoint clusters
    evidence = [
        {"path": "bar.py", "start_line": 1, "end_line": 5, "text": "l1\nl2\nl3\nl4\nl5"},
        {"path": "bar.py", "start_line": 3, "end_line": 7, "text": "l3\nl4\nl5\nl6\nl7"},
        {"path": "bar.py", "start_line": 50, "end_line": 60, "text": "l50\n...\nl60"},
    ]
    merged = merge_overlapping_evidence(evidence)
    assert len(merged) == 2
    c1 = next(x for x in merged if x["start_line"] == 1)
    c2 = next(x for x in merged if x["start_line"] == 50)
    assert c1["end_line"] == 7
    assert c2["end_line"] == 60

    # Inverted start and end lines
    inverted = [
        {"path": "inv.py", "start_line": 20, "end_line": 10, "text": "content"},
        {"path": "inv.py", "start_line": 15, "end_line": 25, "text": "content"},
    ]
    res_inv = merge_overlapping_evidence(inverted)
    assert len(res_inv) == 1
    assert res_inv[0]["start_line"] == 10
    assert res_inv[0]["end_line"] == 25


