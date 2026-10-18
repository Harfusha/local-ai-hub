from __future__ import annotations

import subprocess
from contextlib import closing
from pathlib import Path

import local_ai_hub.rag as rag_module
import pytest

RAGStore = rag_module.RAGStore
ROOT_RAG = Path(__file__).parents[1] / "src" / "local_ai_hub" / "rag.py"


class RecordingEmbedder:
    def __init__(self, space_id: str = "overlay-test-space"):
        self.space_id = space_id
        self.calls = 0

    def embed(self, texts, **_kwargs):
        self.calls += 1
        return {
            "success": True,
            "embeddings": [[float(len(text)), 1.0] for text in texts],
            "backend": "test",
            "embedding_space_id": self.space_id,
        }


class ConfigIdentityEmbedder:
    def __init__(self):
        self.calls = 0

    def embed(self, texts, **_kwargs):
        self.calls += 1
        return {
            "success": True,
            "embeddings": [[float(len(text)), 1.0] for text in texts],
            "backend": "test",
        }


def _store(tmp_path: Path, *, rag_config: dict | None = None, models: dict | None = None):
    return RAGStore(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "models": models or {},
            "rag": rag_config or {
                "extensions": [".py"], "ignore_dirs": [], "max_file_bytes": 1024,
            },
            "features": {"reranker": False},
        },
        services=RecordingEmbedder(),
    )


def _stored_paths(store: RAGStore, workspace: str) -> set[str]:
    with closing(store._connect()) as con:
        rows = con.execute(
            "SELECT path FROM files WHERE workspace=?",
            (workspace,),
        ).fetchall()
    return {str(row[0]) for row in rows}


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def test_000_overlay_imports_actual_root_rag_source():
    assert Path(rag_module.__file__).resolve() == ROOT_RAG.resolve()


@pytest.mark.parametrize("entrypoint", ["index", "index_step", "index_paths_step"])
def test_custom_extensions_and_project_size_policy_reach_all_rag_entrypoints(
    tmp_path: Path, entrypoint: str,
):
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
    store = _store(tmp_path)
    workspace = store.workspace_id(str(root))

    if entrypoint == "index":
        result = store.index(root=str(root), workspace=workspace)
    elif entrypoint == "index_step":
        result = store.index_step(root=str(root), workspace=workspace, max_files=10)
    else:
        result = store.index_paths_step(
            str(root), workspace=workspace,
            paths=["view.tmpl", "asset.blob", "large.tmpl", "included.py"],
        )

    assert result["success"] is True
    assert _stored_paths(store, workspace) == {"view.tmpl", "included.py"}


def test_explicit_index_path_cannot_resurrect_rag_ignored_directory(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".local-ai.toml").write_text(
        'force_include_paths = ["generated/keep.py"]\n', encoding="utf-8",
    )
    generated = root / "generated"
    generated.mkdir()
    (generated / "keep.py").write_text("keep = True\n", encoding="utf-8")
    rag_config = {"extensions": [".py"], "ignore_dirs": [], "max_file_bytes": 1024}
    store = _store(tmp_path, rag_config=rag_config)
    workspace = store.workspace_id(str(root))
    assert store.index_paths_step(
        str(root), workspace=workspace, paths=["generated/keep.py"]
    )["success"] is True
    assert _stored_paths(store, workspace) == {"generated/keep.py"}

    rag_config["ignore_dirs"] = ["generated"]
    result = store.index_paths_step(root=str(root), workspace=workspace, paths=["generated/keep.py"])

    assert result["success"] is True
    assert _stored_paths(store, workspace) == set()


@pytest.mark.parametrize("entrypoint", ["index", "index_step", "index_paths_step"])
def test_linked_worktree_skip_rag_override_reaches_rag_entrypoints(
    tmp_path: Path, entrypoint: str,
):
    primary = tmp_path / "primary"
    linked = tmp_path / "linked"
    primary.mkdir()
    _git(primary, "init", "--quiet")
    _git(primary, "config", "user.email", "test@example.invalid")
    _git(primary, "config", "user.name", "Test")
    (primary / ".local-ai.toml").write_text(
        'shared_namespace = "primary"\n', encoding="utf-8",
    )
    (primary / "module.py").write_text("value = 1\n", encoding="utf-8")
    _git(primary, "add", ".local-ai.toml", "module.py")
    _git(primary, "commit", "--quiet", "-m", "fixture")
    _git(primary, "worktree", "add", "--quiet", "--detach", str(linked), "HEAD")
    (linked / ".local-ai.worktree.toml").write_text(
        'shared_namespace = "linked"\nskip_phases = ["rag"]\n', encoding="utf-8",
    )
    store = _store(tmp_path)
    workspace = store.workspace_id(str(linked))

    if entrypoint == "index":
        result = store.index(root=str(linked), workspace=workspace)
    elif entrypoint == "index_step":
        result = store.index_step(root=str(linked), workspace=workspace, max_files=10)
    else:
        result = store.index_paths_step(root=str(linked), workspace=workspace, paths=["module.py"])

    assert result["success"] is True
    assert result.get("skipped") is True
    assert _stored_paths(store, workspace) == set()


def test_full_index_reembeds_unchanged_files_after_embedding_config_change(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "stable.py").write_text("stable project knowledge\n", encoding="utf-8")
    workspace = RAGStore.workspace_id(str(root))
    first_config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "models": {"embedding": "configured-test", "embedding_digest": "sha256:first"},
        "rag": {"extensions": [".py"], "max_file_bytes": 1024},
    }
    embedder = ConfigIdentityEmbedder()
    first = RAGStore(first_config, services=embedder)
    assert first.index(root=str(root), workspace=workspace)["success"] is True
    first_space = first._embedding_space_id({"backend": "test"})
    assert embedder.calls == 1

    second_config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "models": {"embedding": "configured-test", "embedding_digest": "sha256:second"},
        "rag": {"extensions": [".py"], "max_file_bytes": 1024},
    }
    second = RAGStore(second_config, services=embedder)
    second_space = second._embedding_space_id({"backend": "test"})
    result = second.index(root=str(root), workspace=workspace)

    assert first_space != second_space
    assert result["success"] is True
    assert result["changed_files"] == 1
    assert embedder.calls == 2
    with closing(second._connect()) as con:
        spaces = {
            str(row[0])
            for row in con.execute(
                "SELECT DISTINCT embedding_space FROM chunks WHERE workspace=?",
                (workspace,),
            ).fetchall()
        }
    assert spaces == {second_space}
