from __future__ import annotations

import hashlib
from pathlib import Path

from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.deterministic_slice_merging import merge_overlapping_source_slices


class _SnapshotRepo:
    def _read_snapshot(self, path: Path) -> tuple[str, list[str]]:
        content = path.read_bytes()
        return hashlib.sha256(content).hexdigest(), content.decode("utf-8").splitlines()


class _Evidence:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def put(self, _root: str, item: dict) -> str:
        self.items.append(dict(item))
        return f"evidence-{len(self.items)}"


def _engine(root: Path) -> DeterministicEngine:
    engine = DeterministicEngine.__new__(DeterministicEngine)
    engine.repo_tools = _SnapshotRepo()
    engine.code_index = None
    engine.evidence = _Evidence()
    engine.max_evidence = 12
    return engine


def test_merge_overlapping_slices_rereads_exact_source(tmp_path: Path) -> None:
    source = tmp_path / "foo.py"
    source.write_text("".join(f"line-{number}\n" for number in range(1, 41)), encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    slices = [
        {"path": "foo.py", "start_line": 10, "end_line": 25, "file_sha256": digest},
        {"path": "foo.py", "start_line": 20, "end_line": 35, "file_sha256": digest},
        {"path": "foo.py", "start_line": 37, "end_line": 40, "file_sha256": digest},
    ]

    merged = _engine(tmp_path).merge_overlapping_slices(str(tmp_path), slices)

    assert len(merged) == 1
    assert (merged[0]["start_line"], merged[0]["end_line"]) == (10, 40)
    assert merged[0]["text"].splitlines() == [f"{line}: line-{line}" for line in range(10, 41)]


def test_exact_evidence_stores_merged_overlapping_slices(tmp_path: Path) -> None:
    source = tmp_path / "foo.py"
    source.write_text("".join(f"line-{number}\n" for number in range(1, 21)), encoding="utf-8")
    engine = _engine(tmp_path)

    evidence = engine._exact_evidence(
        str(tmp_path),
        [{"path": "foo.py", "line": 10}, {"path": "foo.py", "line": 14}],
    )

    assert len(evidence) == 1
    assert (evidence[0]["start_line"], evidence[0]["end_line"]) == (8, 16)
    assert engine.evidence.items[0]["text"].splitlines() == [
        f"{line}: line-{line}" for line in range(8, 17)
    ]


def test_merge_overlapping_slices_discards_changed_source(tmp_path: Path) -> None:
    source = tmp_path / "foo.py"
    source.write_text("before\n", encoding="utf-8")
    stale_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    source.write_text("after\n", encoding="utf-8")

    merged = _engine(tmp_path).merge_overlapping_slices(
        str(tmp_path),
        [{"path": "foo.py", "start_line": 1, "end_line": 1, "file_sha256": stale_digest}],
    )

    assert merged == []


def test_extracted_slice_merger_keeps_distinct_ranges_and_drops_escape_paths(
    tmp_path: Path,
) -> None:
    source = tmp_path / "foo.py"
    source.write_text("".join(f"line-{number}\n" for number in range(1, 11)), encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    slices = [
        {"path": "foo.py", "start_line": 4, "end_line": 5, "file_sha256": digest},
        {
            "path": "foo.py",
            "start_line": 1,
            "end_line": 2,
            "file_sha256": digest,
            "symbol_complete": True,
        },
        {
            "path": "foo.py",
            "start_line": 8,
            "end_line": 9,
            "file_sha256": digest,
            "symbol_complete": True,
        },
        {"path": "../outside.py", "start_line": 1, "end_line": 1, "file_sha256": digest},
    ]

    merged = merge_overlapping_source_slices(_SnapshotRepo(), str(tmp_path), slices)

    assert [(item["start_line"], item["end_line"]) for item in merged] == [(1, 5), (8, 9)]
    assert merged[0]["symbol_complete"] is False
    assert merged[1]["symbol_complete"] is True
    assert merged[0]["text"].splitlines() == [f"{line}: line-{line}" for line in range(1, 6)]
