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
    import hashlib

    source = tmp_path / "src" / "a.py"
    source.parent.mkdir()
    source.write_text("line 1\nline 2\nline 3\nline 4\n", encoding="utf-8")

    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    merged = merge_overlapping_evidence(
        [
            {"path": "src/a.py", "start_line": 2, "end_line": 2, "text": "stale", "content_hash": digest},
            {"path": "src/a.py", "start_line": 3, "end_line": 3, "text": "stale", "content_hash": digest},
        ],
        root=tmp_path,
    )

    assert merged[0]["text"] == "line 2\nline 3"


def test_evidence_merge_rejects_parent_and_absolute_paths(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "safe.py").write_text("safe line\n", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")

    evidence = [
        {"path": "../outside.txt", "start_line": 1, "end_line": 1, "text": "bad"},
        {"path": "/etc/passwd", "start_line": 1, "end_line": 1, "text": "bad"},
        {"path": "C:\\Windows\\System32\\cmd.exe", "start_line": 1, "end_line": 1, "text": "bad"},
        {"path": "safe.py", "start_line": 1, "end_line": 1, "text": "safe line"},
    ]

    merged = merge_overlapping_evidence(evidence, root=root)
    assert len(merged) == 1
    assert merged[0]["path"] == "safe.py"


def test_evidence_merge_does_not_merge_across_different_revisions():
    evidence = [
        {"path": "src/a.py", "start_line": 1, "end_line": 2, "text": "v1", "repository_revision": "rev_A"},
        {"path": "src/a.py", "start_line": 2, "end_line": 3, "text": "v2", "repository_revision": "rev_B"},
    ]
    merged = merge_overlapping_evidence(evidence)
    assert len(merged) == 2
    assert merged[0]["repository_revision"] == "rev_A"
    assert merged[1]["repository_revision"] == "rev_B"


def test_evidence_merge_does_not_merge_across_different_content_hashes():
    evidence = [
        {"path": "src/a.py", "start_line": 1, "end_line": 2, "text": "v1", "content_hash": "hash1"},
        {"path": "src/a.py", "start_line": 2, "end_line": 3, "text": "v2", "content_hash": "hash2"},
    ]
    merged = merge_overlapping_evidence(evidence)
    assert len(merged) == 2
    assert merged[0]["content_hash"] == "hash1"
    assert merged[1]["content_hash"] == "hash2"


def test_evidence_merge_lineage_and_id_provenance():
    evidence = [
        {"path": "src/a.py", "start_line": 1, "end_line": 2, "text": "line1\nline2", "evidence_id": "ev1", "score": 0.5},
        {"path": "src/a.py", "start_line": 2, "end_line": 3, "text": "line2\nline3", "evidence_id": "ev2", "score": 0.9},
    ]
    merged = merge_overlapping_evidence(evidence)
    assert len(merged) == 1
    assert merged[0]["evidence_id"].startswith("merged-")
    assert merged[0]["parent_evidence_ids"] == ["ev1", "ev2"]
    assert merged[0]["merged_from_count"] == 2
    assert merged[0]["score"] == 0.9


def test_evidence_merge_falls_back_when_disk_hash_mismatches(tmp_path):
    import hashlib

    source = tmp_path / "src" / "a.py"
    source.parent.mkdir()
    source.write_text("modified on disk line 1\nmodified line 2\n", encoding="utf-8")

    stale_hash = hashlib.sha256(b"original content").hexdigest()
    evidence = [
        {"path": "src/a.py", "start_line": 1, "end_line": 1, "text": "orig1", "content_hash": stale_hash},
        {"path": "src/a.py", "start_line": 2, "end_line": 2, "text": "orig2", "content_hash": stale_hash},
    ]

    merged = merge_overlapping_evidence(evidence, root=tmp_path)
    assert len(merged) == 1
    # Since disk file does not match stale_hash, disk must NOT be read, in-memory lines must be used
    assert merged[0]["text"] == "orig1\norig2"
    assert merged[0]["snapshot_verified"] is False
    assert merged[0]["freshness"] == "stale"
    assert merged[0]["fallback_reason"] == "disk_hash_mismatch"


def test_evidence_merge_linear_scaling_and_safe_numeric_validation():
    # NaN score, bool start_line, negative values, and thousands of segments in linear time
    evidence = [
        {
            "path": "src/big.py",
            "start_line": i,
            "end_line": i + 1,
            "text": f"line_{i}\nline_{i+1}",
            "score": float("nan") if i % 2 == 0 else 0.5,
        }
        for i in range(1, 1000)
    ]
    # Malformed entry with boolean lines and string scores
    evidence.append({
        "path": "src/big.py",
        "start_line": True,  # bool must not crash
        "end_line": "invalid",
        "score": float("inf"),
        "text": "bad",
    })

    merged = merge_overlapping_evidence(evidence)
    assert len(merged) == 1
    assert merged[0]["path"] == "src/big.py"
    assert merged[0]["start_line"] == 1
    assert merged[0]["score"] == 0.5


def test_evidence_merge_bounded_file_read_and_symlink_protection(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    target = root / "large.py"
    # Create file that exceeds MAX_FILE_BYTES
    target.write_bytes(b"A" * (11 * 1024 * 1024))
    evidence = [
        {"path": "large.py", "start_line": 1, "end_line": 2, "text": "chunk1"},
        {"path": "large.py", "start_line": 2, "end_line": 3, "text": "chunk2"},
    ]
    merged = merge_overlapping_evidence(evidence, root=root)
    assert len(merged) == 1
    assert merged[0]["fallback_reason"] == "file_too_large"
    assert merged[0]["snapshot_verified"] is False




def test_unhashed_evidence_never_replaced_by_current_disk(tmp_path):
    source = tmp_path / "a.py"
    source.write_text("new line 1\nnew line 2\n", encoding="utf-8")
    records = [
        {"path": "a.py", "start_line": 1, "end_line": 1, "text": "original line 1"},
        {"path": "a.py", "start_line": 2, "end_line": 2, "text": "original line 2"},
    ]
    merged = merge_overlapping_evidence(records, root=tmp_path)
    assert merged[0]["text"] == "original line 1\noriginal line 2"
    assert merged[0]["snapshot_verified"] is False
    assert merged[0]["freshness"] == "unverified"
    assert merged[0]["fallback_reason"] == "missing_content_hash"


def test_large_merged_range_reports_exact_omitted_lines():
    merged = merge_overlapping_evidence([
        {"path": "a.py", "start_line": 1, "end_line": 2, "text": "one\ntwo"},
        {"path": "a.py", "start_line": 2, "end_line": 50005, "text": "two"},
    ])
    assert len(merged) == 1
    assert merged[0]["start_line"] == 1
    assert merged[0]["end_line"] == 50000
    assert merged[0]["original_end_line"] == 50005
    assert merged[0]["omitted_lines"] == 5
    assert merged[0]["truncated"] is True
    assert merged[0]["truncation_reason"] == "max_merged_lines"
