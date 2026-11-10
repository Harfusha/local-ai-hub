import hashlib
from pathlib import Path
from contextlib import closing
from unittest.mock import MagicMock
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.repo_tools import RepositoryTools


def test_barrel_export_and_types_synthesize_deterministic_card_without_llm(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    source_path = root / "index.ts"
    source_path.write_text("export * from './module_a';\nexport * from './module_b';\n", encoding="utf-8")
    content_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()

    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {"enabled": True, "disable_llm_card_synthesis": True},
    }
    services = MagicMock()
    runtime = MagicMock()

    prep = ProjectPreprocessor(
        cfg,
        services=services,
        rag=MagicMock(),
        scheduler=MagicMock(),
        runtime=runtime,
        repo_tools=RepositoryTools(cfg),
        code_index=MagicMock(),
    )
    prep._init_db()

    with prep._db_lock, closing(prep._connect()) as con:
        con.execute(
            "INSERT INTO file_refs(root, path, content_hash, size, needs_hash, generation, updated_at) "
            "VALUES(?, ?, ?, ?, 0, 1, 0.0)",
            (str(root), "index.ts", content_hash, 50),
        )
        con.commit()

    row = {"root": str(root), "generation": 1, "phase": "files"}
    stepped = prep._step_file_card(row)
    assert stepped is True

    # Check that the file reference points at the deterministic provisional barrel card.
    with prep._db_lock, closing(prep._connect()) as con:
        card = con.execute(
            "SELECT c.* FROM file_refs f JOIN content_cards c ON c.card_key=f.card_key "
            "WHERE f.root=? AND f.path='index.ts'",
            (str(root),),
        ).fetchone()
        assert card is not None
        assert card["model"] == "deterministic-barrel"

    # Runtime LLM should NEVER have been called for this barrel file!
    assert runtime.generate.call_count == 0
