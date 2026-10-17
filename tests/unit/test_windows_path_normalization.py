import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub import repo_state
from local_ai_hub.process_utils import canonical_path, canonical_root, canonical_workspace_id


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (r"c:\Users\tester\.\repo\..\Repo", "C:/Users/tester/Repo"),
        ("c:/Users/tester/./repo/../Repo", "C:/Users/tester/Repo"),
        (r"\\Server\Share\folder\..\Repo", "//Server/Share/Repo"),
        ("//Server/Share/folder/../Repo", "//Server/Share/Repo"),
    ],
)
def test_canonical_path_normalizes_windows_drive_and_unc_spellings(path, expected):
    assert canonical_path(path) == expected


def test_canonical_path_preserves_component_case_and_posix_backslashes():
    assert canonical_path(r"d:\Users\tester\Project") == "D:/Users/tester/Project"
    assert canonical_path("/Tmp/Repo/a\\b") == "/Tmp/Repo/a\\b"
    assert canonical_path("/Tmp/Repo/a\\b") != canonical_path("/Tmp/Repo/a/b")
    assert canonical_path(r"relative\file") == r"relative\file"


def test_fingerprint_cache_and_invalidation_share_lexical_path_key(tmp_path, monkeypatch):
    monkeypatch.setattr(repo_state, "canonical_root", lambda path: os.fspath(path))
    tracker = repo_state.RepoStateTracker({})
    git_calls = []

    def fake_git(_root_path, *args, **kwargs):
        git_calls.append(args)
        return SimpleNamespace(returncode=0, stdout=b"# branch.oid abc123\0")

    tracker._run_git = fake_git
    root = str(tmp_path)
    alias = root + os.sep + "."

    first = tracker.fingerprint(root)
    second = tracker.fingerprint(alias)
    assert first["fingerprint"] == second["fingerprint"]
    assert len(git_calls) == 1

    tracker.invalidate(alias)
    tracker.fingerprint(root)
    assert len(git_calls) == 2


def test_canonical_workspace_id_keeps_physical_root_hash_contract(tmp_path):
    resolved = canonical_root(tmp_path)
    expected = f"{Path(resolved).name}-{hashlib.sha1(resolved.encode('utf-8'), usedforsecurity=False).hexdigest()[:12]}"

    assert canonical_workspace_id(tmp_path) == expected
    assert canonical_workspace_id(str(tmp_path)) == expected
