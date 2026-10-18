from __future__ import annotations

from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.rag import RAGStore


class RecordingEmbedder:
    def embed(self, texts, **_kwargs):
        return {
            "success": True,
            "embeddings": [[1.0, float(index + 1)] for index in range(len(texts))],
            "backend": "test",
            "embedding_space_id": "t11-project-policy",
        }


def _project(tmp_path: Path, *, skip_rag: bool = False) -> tuple[Path, dict[str, object]]:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".local-ai.toml").write_text(
        'exclude_paths = ["general.py"]\n'
        'force_include_paths = ["general.py"]\n'
        f'skip_phases = [{"\"rag\"" if skip_rag else ""}]\n'
        '\n[preprocess]\nexclude_paths = ["preprocess-only.py"]\n',
        encoding="utf-8",
    )
    (root / "preprocess-only.py").write_text("preprocess_only = True\n", encoding="utf-8")
    (root / "general.py").write_text("general_excluded = True\n", encoding="utf-8")
    (root / "included.py").write_text("included = True\n", encoding="utf-8")
    config: dict[str, object] = {
        "server": {"state_dir": str(tmp_path / "state")},
        "rag": {"extensions": [".py"], "max_file_bytes": 2_000_000},
    }
    return root, config


def _stored_paths(store: RAGStore, workspace: str) -> set[str]:
    with closing(store._connect()) as con:
        return {
            str(row[0])
            for row in con.execute(
                "SELECT path FROM files WHERE workspace=?", (workspace)
            ).fetchall()
        }


@pytest.mark.parametrize("entrypoint", ["index", "index_step", "index_paths_step"])
def test_rag_ingest_uses_rag_policy_not_preprocess_exclusions(tmp_path: Path, entrypoint: str) -> None:
    root, config = _project(tmp_path)
    store = RAGStore(config, services=RecordingEmbedder())
    workspace = store.workspace_id(str(root))

    if entrypoint == "index":
        result = store.index(root=str(root), workspace=workspace)
    elif entrypoint == "index_step":
        result = store.index_step(root=str(root), max_files=10, workspace=workspace)
    else:
        result = store.index_paths_step(root=str(root), workspace=workspace, paths=["preprocess-only.py", "general.py", "included.py"])

    assert result["success"] is True
    assert _stored_paths(store, workspace) == {"preprocess-only.py", "included.py"}


@pytest.mark.parametrize("entrypoint", ["index", "index_step", "index_paths_step"])
def test_rag_skip_phase_is_respected_by_each_ingest_entrypoint(tmp_path: Path, entrypoint: str) -> None:
    root, config = _project(tmp_path, skip_rag=True)
    store = RAGStore(config, services=RecordingEmbedder())
    workspace = store.workspace_id(str(root))

    if entrypoint == "index":
        result = store.index(root=str(root), workspace=workspace)
    elif entrypoint == "index_step":
        result = store.index_step(root=str(root), max_files=10, workspace=workspace)
    else:
        result = store.index_paths_step(root=str(root), workspace=workspace, paths=["included.py"])

    assert result["success"] is True
    assert result.get("skipped") is True
    assert _stored_paths(store, workspace) == set()

def test_rag_index_paths_respects_hard_ignored_directory_with_force_include(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".local-ai.toml").write_text(
        'force_include_paths = ["generated/keep.py"]\n', encoding="utf-8"
    )
    generated = root / "generated"
    generated.mkdir()
    (generated / "keep.py").write_text("keep = True\n", encoding="utf-8")
    rag_config = {"extensions": [".py"], "ignore_dirs": [], "max_file_bytes": 1024}
    config: dict[str, object] = {
        "server": {"state_dir": str(tmp_path / "state")}, "rag": rag_config,
    }
    store = RAGStore(config, services=RecordingEmbedder())
    workspace = store.workspace_id(str(root))
    assert store.index_paths_step(root=str(root), workspace=workspace, paths=["generated/keep.py"])["success"] is True
    assert _stored_paths(store, workspace) == {"generated/keep.py"}

    rag_config["ignore_dirs"] = ["generated"]
    result = store.index_paths_step(root=str(root), workspace=workspace, paths=["generated/keep.py"])

    assert result["success"] is True
    assert _stored_paths(store, workspace) == set()


@pytest.mark.parametrize("entrypoint", ["index", "index_step", "index_paths_step"])
def test_rag_ingestion_applies_custom_extension_and_project_size_policy(
    tmp_path: Path, entrypoint: str,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".local-ai.toml").write_text(
        '[custom_extensions]\ntext = [".tmpl"]\nbinary = [".blob"]\n'
        '[file_limits]\nmax_file_size_bytes = 12\n',
        encoding="utf-8",
    )
    (root / "view.tmpl").write_text("view\n", encoding="utf-8")
    (root / "asset.blob").write_text("binary\n", encoding="utf-8")
    (root / "large.tmpl").write_text("x" * 13, encoding="utf-8")
    (root / "included.py").write_text("ok\n", encoding="utf-8")
    config: dict[str, object] = {
        "server": {"state_dir": str(tmp_path / "state")},
        "rag": {"extensions": [".py"], "ignore_dirs": [], "max_file_bytes": 1024},
    }
    store = RAGStore(config, services=RecordingEmbedder())
    workspace = store.workspace_id(str(root))

    if entrypoint == "index":
        result = store.index(root=str(root), workspace=workspace)
    elif entrypoint == "index_step":
        result = store.index_step(root=str(root), max_files=10, workspace=workspace)
    else:
        result = store.index_paths_step(root=str(root), workspace=workspace, paths=["view.tmpl", "asset.blob", "large.tmpl", "included.py"])

    assert result["success"] is True
    assert _stored_paths(store, workspace) == {"view.tmpl", "included.py"}
