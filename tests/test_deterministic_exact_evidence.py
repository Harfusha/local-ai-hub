from pathlib import Path

from local_ai_hub.deterministic_exact_evidence import collect_exact_evidence


class _Evidence:
    def __init__(self):
        self.items = []
        self.provenance = []

    def put_many(self, root, items):
        self.items = items
        return [{"evidence_id": f"evidence-{index}"} for index, _ in enumerate(items)]

    def record_source_provenance(self, evidence_id, *, root, source_code):
        self.provenance.append((evidence_id, root, source_code))


class _RepoTools:
    def __init__(self):
        self.reads = []

    def _read_snapshot(self, path):
        self.reads.append(path)
        return "sha256:source", ["one", "two", "three", "four", "five"]


class _CodeIndex:
    def symbol_bounds_at(self, root, path, line, *, content_hash):
        return (2, 4)


class _Engine:
    def __init__(self):
        self.evidence = _Evidence()
        self.max_evidence = 3
        self.repo_tools = _RepoTools()
        self.code_index = _CodeIndex()
        self.merged = None

    def merge_overlapping_slices(self, root, slices):
        self.merged = (root, slices)
        return [{**slices[0], "text": "two\nthree\nfour"}]


def test_collect_exact_evidence_confines_deduplicates_and_records_provenance(tmp_path):
    root = tmp_path.resolve()
    (root / "src").mkdir()
    engine = _Engine()

    result = collect_exact_evidence(
        engine,
        str(root),
        [
            {"path": "src/demo.py", "line": 3},
            {"path": "src/demo.py", "line": 3},
            {"path": "../outside.py", "line": 1},
        ],
    )

    assert len(engine.repo_tools.reads) == 1
    assert engine.repo_tools.reads[0] == root / "src" / "demo.py"
    assert engine.merged[1] == [
        {
            "path": "src/demo.py",
            "start_line": 2,
            "end_line": 4,
            "file_sha256": "sha256:source",
            "symbol_complete": True,
        }
    ]
    assert result == [
        {
            "path": "src/demo.py",
            "start_line": 2,
            "end_line": 4,
            "file_sha256": "sha256:source",
            "symbol_complete": True,
            "evidence_id": "evidence-0",
        }
    ]
    assert engine.evidence.provenance == [("evidence-0", str(root), "indexed")]
