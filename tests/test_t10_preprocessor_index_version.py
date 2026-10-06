from __future__ import annotations

from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub import code_index as code_index_module
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.process_utils import canonical_root
from local_ai_hub.repo_tools import RepositoryTools


def test_preprocessor_queues_unchanged_files_after_analyzer_version_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_dir = tmp_path / "state"
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "module.py"
    source.write_text("def caller():\n    target()\n", encoding="utf-8")
    repo_tools = RepositoryTools({})
    index = CodeIndex({"server": {"state_dir": str(state_dir)}}, repo_tools=repo_tools)
    content_hash, _lines = repo_tools._read_snapshot(source)
    assert index.update_file(str(root), "module.py")["success"] is True

    config = {
        "server": {"state_dir": str(state_dir)},
        "preprocessing": {"code_index_files_per_step": 8},
    }
    preprocessor = ProjectPreprocessor(
        config, services=None, rag=None, scheduler=None, runtime=None,
        repo_tools=repo_tools, code_index=index,
    )
    root_key = canonical_root(str(root))
    generation = 7
    preprocessor._missing_refs_checked_generations.add((root_key, generation))
    preprocessor._code_index_pruned_generations.add((root_key, generation))
    with closing(preprocessor._connect()) as con:
        con.execute(
            "INSERT INTO file_refs(root,path,content_hash,size,generation,updated_at) VALUES(?,?,?,?,?,?)",
            (root_key, "module.py", content_hash, source.stat().st_size, generation, 0.0),
        )
        con.commit()

    old_version = code_index_module._PARSER_ANALYZER_VERSION
    monkeypatch.setattr(code_index_module, "_PARSER_ANALYZER_VERSION", f"{old_version}:preprocess-bump")
    submitted: list[tuple[str, str]] = []
    update_batch = index.update_files_batch

    def track_batch(batch_root: str, items: list[tuple[str, str]]):
        submitted.extend(items)
        return update_batch(batch_root, items)

    monkeypatch.setattr(index, "update_files_batch", track_batch)
    monkeypatch.setattr(preprocessor, "_record_progress", lambda *_args: None)

    assert preprocessor._step_code_index({"root": root_key, "generation": generation}) is True
    assert submitted == [("module.py", content_hash)]
    assert index._parse_blob_get(content_hash, "python") is not None
