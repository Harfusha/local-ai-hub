from __future__ import annotations

import logging
import time
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock

from local_ai_hub.preprocess import ProjectPreprocessor


def test_lookup_skips_invalid_json_and_non_object_cards_but_keeps_valid_siblings(
    tmp_path: Path, caplog
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    repo_tools = MagicMock()
    repo_tools._terms.return_value = {"needle"}
    prep = ProjectPreprocessor(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "preprocessing": {"enabled": False},
        },
        services=MagicMock(),
        rag=MagicMock(),
        scheduler=MagicMock(),
        runtime=MagicMock(),
        repo_tools=repo_tools,
    )
    now = time.time()
    caplog.set_level(logging.DEBUG, logger="local_ai_hub.preprocess")
    try:
        with closing(prep._connect()) as con:
            con.execute(
                "INSERT INTO project_cards(root, revision_hash, card_json, updated_at) VALUES(?,?,?,?)",
                (str(root), "rev", "PROJECT_SECRET_SHOULD_NOT_LOG {", now),
            )
            con.executemany(
                "INSERT INTO module_cards(root, module, revision_hash, card_json, updated_at) VALUES(?,?,?,?,?)",
                [
                    (str(root), "module-bad", "rev", '["MODULE_SECRET_SHOULD_NOT_LOG"]', now),
                    (str(root), "module-invalid-utf8", "rev", b"\xff", now),
                    (str(root), "module-good", "rev", '{"summary":"needle module"}', now),
                ],
            )
            file_cards = [
                ("file-bad", "file-hash-bad", "needle-bad.py", "null"),
                ("file-good", "file-hash-good", "needle-good.py", '{"summary":"valid sibling"}'),
            ]
            for card_key, content_hash, path, card_json in file_cards:
                con.execute(
                    "INSERT INTO content_cards(card_key, content_hash, model, analyzer_version, card_json, created_at, accessed_at) VALUES(?,?,?,?,?,?,?)",
                    (card_key, content_hash, "model", "v1", card_json, now, now),
                )
                con.execute(
                    "INSERT INTO file_refs(root, path, content_hash, size, generation, card_key, updated_at) VALUES(?,?,?,?,?,?,?)",
                    (str(root), path, content_hash, 1, 0, card_key, now),
                )
            con.executemany(
                "INSERT INTO task_capsules(root, query, revision_hash, capsule_json, updated_at) VALUES(?,?,?,?,?)",
                [
                    (str(root), "needle bad-list", "rev", '["CAPSULE_SECRET_SHOULD_NOT_LOG"]', now),
                    (str(root), "needle bad-null", "rev", "null", now),
                    (str(root), "needle good", "rev", '{"summary":"valid capsule"}', now),
                ],
            )
            con.commit()

        result = prep.lookup(str(root), "needle", limit=5)

        assert result["project"] == {}
        assert [item["module"] for item in result["modules"]] == ["module-good"]
        assert [item["path"] for item in result["files"]] == ["needle-good.py"]
        assert len(result["capsules"]) == 1
        assert result["capsules"][0]["summary"] == "valid capsule"
        assert result["preprocessed"] is True
        assert "Skipping invalid preprocessing card" in caplog.text
        for sensitive in (
            "PROJECT_SECRET_SHOULD_NOT_LOG",
            "MODULE_SECRET_SHOULD_NOT_LOG",
            "CAPSULE_SECRET_SHOULD_NOT_LOG",
            "needle-bad.py",
        ):
            assert sensitive not in caplog.text
    finally:
        prep.close()
