from __future__ import annotations

import os
from pathlib import Path

from local_ai_hub.process_utils import canonical_root
from local_ai_hub.rag import RAGStore
from local_ai_hub.memory import WorkspaceMemoryStore
from local_ai_hub.repo_state import RepoStateTracker


def test_canonical_root_normalizes_slashes_and_casing(tmp_path: Path):
    resolved = tmp_path.resolve()
    c1 = canonical_root(str(resolved))
    c2 = canonical_root(str(resolved).replace("\\", "/"))
    assert c1 == c2

    if os.name == "nt":
        # Windows drive letter case normalization
        drive_lower = str(resolved)[0].lower() + str(resolved)[1:]
        assert canonical_root(drive_lower) == canonical_root(str(resolved))



def test_rag_and_memory_workspace_id_case_insensitive(tmp_path: Path):
    resolved = tmp_path.resolve()

    if os.name == "nt":
        drive_lower = str(resolved)[0].lower() + str(resolved)[1:]
        assert RAGStore.workspace_id(drive_lower) == RAGStore.workspace_id(str(resolved))
        assert WorkspaceMemoryStore.workspace_id(drive_lower) == WorkspaceMemoryStore.workspace_id(str(resolved))





def test_repo_state_fingerprint_case_insensitive(tmp_path: Path):
    tracker = RepoStateTracker({})
    resolved = tmp_path.resolve()
    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")

    if os.name == "nt":
        drive_lower = str(resolved)[0].lower() + str(resolved)[1:]
        fp1 = tracker.fingerprint(drive_lower)
        fp2 = tracker.fingerprint(str(resolved))
        assert fp1["root"] == fp2["root"]
        assert fp1["files_seen"] == fp2["files_seen"]
        assert fp1["fingerprint"] == fp2["fingerprint"]


def test_code_index_case_insensitive(tmp_path: Path):
    from local_ai_hub.code_index import CodeIndex
    from local_ai_hub.repo_tools import RepositoryTools

    cfg = {"server": {"state_dir": str(tmp_path / "state")}}
    tools = RepositoryTools(cfg)
    index = CodeIndex(cfg, tools)

    resolved = tmp_path.resolve()
    py_file = tmp_path / "mod.py"
    py_file.write_text("def compute_result():\n    return 42\n", encoding="utf-8")

    index.update_file(str(resolved), "mod.py")

    res1 = index.find_symbol(str(resolved), "compute_result")
    assert res1["success"] is True
    assert len(res1["symbols"]) >= 1

    if os.name == "nt":
        drive_lower = str(resolved)[0].lower() + str(resolved)[1:]
        res2 = index.find_symbol(drive_lower, "compute_result")
        assert res2["success"] is True
        assert len(res2["symbols"]) >= 1
        assert res2["root"] == res1["root"]



