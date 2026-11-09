from pathlib import Path
from contextlib import closing
from unittest.mock import MagicMock
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.repo_tools import RepositoryTools


def test_proactive_git_seeding_when_evidence_empty(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "main.py").write_text("import helper\n", encoding="utf-8")
    (root / "helper.py").write_text("def run(): pass\n", encoding="utf-8")

    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": True},
    }
    services = MagicMock()
    evidence_mock = MagicMock()
    # Evidence store returns empty list (no agent interaction yet)
    evidence_mock.recent_paths.return_value = []
    services.evidence_store = evidence_mock

    code_index = MagicMock()
    code_index.files_needing_reindex.side_effect = lambda root, refs: refs
    code_index.update_files_batch.return_value = {"files_processed": 2}
    code_index.prune.return_value = {"success": True}

    prep = ProjectPreprocessor(
        cfg,
        services=services,
        rag=MagicMock(),
        scheduler=MagicMock(),
        runtime=MagicMock(),
        repo_tools=RepositoryTools(cfg),
        code_index=code_index,
    )
    prep._init_db()

    # Prepopulate file_refs
    with prep._db_lock, closing(prep._connect()) as con:
        con.execute(
            "INSERT INTO file_refs(root, path, content_hash, size, needs_hash, generation, updated_at) "
            "VALUES(?, ?, ?, ?, 0, 1, 0.0)",
            (str(root), "main.py", "hash1", 20),
        )
        con.execute(
            "INSERT INTO file_refs(root, path, content_hash, size, needs_hash, generation, updated_at) "
            "VALUES(?, ?, ?, ?, 0, 1, 0.0)",
            (str(root), "helper.py", "hash2", 20),
        )
        con.commit()

    # Run _step_code_index
    row = {"root": str(root), "generation": 1}
    stepped = prep._step_code_index(row)
    assert stepped is True

    # Assert code_index received main.py and/or helper.py as proactive seeds!
    assert code_index.update_files_batch.called
    call_args = code_index.update_files_batch.call_args[0]
    indexed_paths = [p for p, _ in call_args[1]]
    assert "main.py" in indexed_paths or "helper.py" in indexed_paths
