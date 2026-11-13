from local_ai_hub.evidence_merge import (
    merge_overlapping_evidence,
    merge_overlapping_line_ranges,
)
from local_ai_hub.services import (
    merge_overlapping_evidence as services_merge_overlapping_evidence,
    merge_overlapping_line_ranges as services_merge_overlapping_line_ranges,
)


def test_service_imports_remain_compatibility_exports():
    assert services_merge_overlapping_line_ranges([(1, 2)]) == [(1, 2)]
    assert services_merge_overlapping_evidence([]) == []


def test_line_ranges_merge_overlap_adjacency_and_reversed_pairs():
    assert merge_overlapping_line_ranges(
        [(5, 7), (1, 2), (3, 3), (12, 10), ("invalid", 4)]
    ) == [(1, 3), (5, 7), (10, 12)]
    assert merge_overlapping_line_ranges([(1, 2), (4, 6)], max_gap=2) == [
        (1, 6)
    ]


def test_evidence_merge_uses_best_score_and_preserves_symbol_order():
    merged = merge_overlapping_evidence(
        [
            {"path": "src/a.py", "start_line": 2, "end_line": 3, "text": "b\nc", "score": 0.4, "symbol": "first"},
            {"path": "src/a.py", "start_line": 4, "end_line": 5, "text": "d\ne", "score": 0.8, "symbol": "second", "content": "old"},
            {"path": "src/b.py", "start_line": 1, "end_line": 1, "text": "separate", "score": 0.2},
        ]
    )

    assert len(merged) == 2
    assert merged[0]["path"] == "src/a.py"
    assert (merged[0]["start_line"], merged[0]["end_line"]) == (2, 5)
    assert merged[0]["text"] == merged[0]["content"] == "b\nc\nd\ne"
    assert merged[0]["score"] == 0.8
    assert merged[0]["symbol"] == "first, second"
    assert merged[1]["path"] == "src/b.py"


def test_evidence_merge_prefers_file_snapshot_when_root_contains_path(tmp_path):
    source = tmp_path / "src" / "a.py"
    source.parent.mkdir()
    source.write_text("line 1\nline 2\nline 3\nline 4\n", encoding="utf-8")

    merged = merge_overlapping_evidence(
        [
            {"path": "src/a.py", "start_line": 2, "end_line": 2, "text": "stale"},
            {"path": "src/a.py", "start_line": 3, "end_line": 3, "text": "stale"},
        ],
        root=tmp_path,
    )

    assert merged[0]["text"] == "line 2\nline 3"
