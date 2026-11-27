from __future__ import annotations

import subprocess

import pytest
from unittest.mock import MagicMock

from local_ai_hub.change_stage_execution import stage_selection


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch, tmp_path):
    from local_ai_hub import change_stage_execution as module

    config = tmp_path / "isolated-git-config"
    config.write_text("", encoding="utf-8")
    overrides = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(config)}
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)
    original = module.clean_git_env

    def clean(*args, **kwargs):
        return {**original(*args, **kwargs), **overrides}

    monkeypatch.setattr(module, "clean_git_env", clean)


def _git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root).strip().decode()


def _fixture(root):
    _git(root, "init")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.invalid")
    (root / "a").write_text("old")
    (root / "b").write_text("old")
    _git(root, "add", "a", "b")
    _git(root, "commit", "-m", "base")
    (root / "a").write_text("new")
    (root / "b").write_text("unrelated")
    engine = MagicMock()
    engine.split_changes.return_value = {
        "success": True, "observed_change_set_id": "a" * 64, "git_visible_observation_complete": True,
        "comparison": None, "git_snapshot_metadata": {"head": _git(root, "rev-parse", "HEAD")},
        "clusters": [{"group_key": "a", "files": ["a"], "changes": [{"path": "a", "status": " M"}]},
                     {"group_key": "b", "files": ["b"], "changes": [{"path": "b", "status": " M"}]}],
    }
    leases = MagicMock()
    leases.claim.return_value = {"success": True, "lease_id": "lease"}
    leases.renew.return_value = {"success": True}
    leases.release.return_value = {"success": True}
    return engine, leases


def test_preview_and_apply_exact_stage(tmp_path):
    engine, leases = _fixture(tmp_path)
    index = tmp_path / ".git" / "index"
    before = index.read_bytes()
    kwargs = dict(root=str(tmp_path.resolve()), paths=["a"], expected_revision="a" * 64)
    preview = stage_selection({}, engine, leases, **kwargs)
    assert preview["success"], preview
    assert not preview["applied"]
    assert index.read_bytes() == before
    tree = preview["prospective_tree_oid"]
    denied = stage_selection({}, engine, leases, **kwargs, expected_tree="b" * len(tree), apply=True)
    assert not denied["success"]
    assert index.read_bytes() == before
    result = stage_selection({}, engine, leases, **kwargs, expected_tree=tree, apply=True)
    assert result["success"], result
    assert result["applied"]
    assert _git(tmp_path, "diff", "--cached", "--name-only") == "a"
    assert _git(tmp_path, "diff", "--name-only") == "b"
    assert _git(tmp_path, "write-tree") == tree
    assert not (tmp_path / ".git" / "index.lock").exists()


def test_stage_refuses_filters_and_external_lock(tmp_path):
    engine, leases = _fixture(tmp_path)
    kwargs = dict(root=str(tmp_path.resolve()), paths=["a"], expected_revision="a" * 64)
    _git(tmp_path, "config", "filter.test.clean", "false")
    assert not stage_selection({}, engine, leases, **kwargs)["success"]
    _git(tmp_path, "config", "--unset", "filter.test.clean")
    lock = tmp_path / ".git" / "index.lock"
    lock.write_text("foreign")
    assert not stage_selection({}, engine, leases, **kwargs)["success"]
    assert lock.read_text() == "foreign"


def test_partial_hunks_preserve_unselected_lines(tmp_path):
    import hashlib
    from local_ai_hub.change_atoms import _hunks, identity
    from local_ai_hub.change_hunk_selection import select_hunks

    root = str(tmp_path.resolve())
    before = b"one\ntwo\nthree\nfour\nfive\n"
    after = b"ONE\ntwo\nthree\nfour\nFIVE\n"
    def oid(data):
        return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    patch = (f"diff --git a/a b/a\nindex {oid(before)}..{oid(after)} 100644\n--- a/a\n+++ b/a\n".encode()
             + b"@@ -1 +1 @@\n-one\n+ONE\n@@ -5 +5 @@\n-five\n+FIVE\n")
    atom = identity("patch-v1", root, "a", "unstaged", hashlib.sha256(patch).hexdigest())
    ranges, _, _ = _hunks(patch, atom)
    first = identity("hunk-v1", root, "a", "unstaged", ranges[0][4])
    actual, mode = select_hunks(before, patch, root, "a", atom, [first])
    assert actual == b"ONE\ntwo\nthree\nfour\nfive\n"
    assert mode == "100644"


def test_real_partial_stage_commit_preserves_unrelated_changes_and_project_lease(tmp_path):
    import sys
    from pathlib import Path
    from types import SimpleNamespace

    from local_ai_hub.change_commit_execution import execute_staged_commit
    from local_ai_hub.change_git_coordination import git_coordination_id
    from local_ai_hub.leases import ScopeLeaseStore
    from local_ai_hub.split_changes import run_split_changes

    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.name", "Fixture")
    _git(root, "config", "user.email", "fixture@example.invalid")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "a.txt").write_text("one\ntwo\nthree\nfour\nfive\n", encoding="utf-8")
    (root / "b.txt").write_text("old\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base")
    (root / "a.txt").write_text("ONE\ntwo\nthree\nfour\nFIVE\n", encoding="utf-8")
    (root / "b.txt").write_text("unrelated\n", encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    lease = ScopeLeaseStore(tmp_path / "state")
    root_str = str(root.resolve())
    context = SimpleNamespace(_root=lambda value: value, git_status_timeout=10)
    class Engine:
        def split_changes(self, requested_root, paths):
            return run_split_changes(context, requested_root, paths, path_type=Path,
                                     subprocess_module=subprocess, hidden_run_kwargs_fn=lambda: {})
    engine = Engine()
    plan = engine.split_changes(root_str, None)
    assert plan["git_visible_observation_complete"], plan
    group = next(g for g in plan["clusters"] if g["files"] == ["a.txt"])
    atom = group["changes"][0]["atoms"][0]
    kwargs = dict(root=root_str, paths=["a.txt"], expected_revision=plan["observed_change_set_id"],
                  hunk_ids=[atom["hunks"][0]["hunk_id"]])
    held = lease.claim(owner="other-agent", root=root_str, paths=["a.txt"], coordination_id=git_coordination_id(config, root_str))
    assert held["success"], held
    assert not stage_selection(config, engine, lease, **kwargs)["success"]
    assert lease.release(owner="other-agent", lease_id=held["lease_id"])["success"]
    preview = stage_selection(config, engine, lease, **kwargs)
    assert preview["success"], preview
    staged = stage_selection(config, engine, lease, **kwargs, expected_tree=preview["prospective_tree_oid"], apply=True)
    assert staged["success"], staged
    after = engine.split_changes(root_str, None)
    from local_ai_hub.change_commit_journal import CommitJournal
    from local_ai_hub.change_tree_verification import verify_sequence

    sequence = [{"paths": ["a.txt"], "message": "chore: selected hunk"}]
    journal = CommitJournal(tmp_path / "state" / "commit-journal")
    common = dict(root=root_str, paths=["a.txt"], expected_revision=after["observed_change_set_id"],
                  expected_tree=preview["prospective_tree_oid"], sequence=sequence, journal=journal,
                  allow_mixed_staged=True)
    sequence_preview = execute_staged_commit(config, engine, lease, **common,
                                             approved=False, preview_only=True)
    assert sequence_preview["success"], sequence_preview
    manifest = {"environment_id": "c" * 64, "commands": [[
        sys.executable, "-c",
        "from pathlib import Path; assert Path('a.txt').read_text() == 'ONE\\ntwo\\nthree\\nfour\\nfive\\n'; assert Path('b.txt').read_text() == 'old\\n'",
    ]]}
    verified = verify_sequence(root_str, sequence_preview, manifest, journal)
    assert verified["success"], verified
    result = execute_staged_commit(config, engine, lease, **common, approved=True,
                                   preview_digest=sequence_preview["preview_digest"],
                                   verification_manifest=manifest)
    assert result["success"], result
    assert _git(root, "show", "HEAD:a.txt").replace("\r\n", "\n") == "ONE\ntwo\nthree\nfour\nfive"
    assert "FIVE" in (root / "a.txt").read_text(encoding="utf-8")
    assert _git(root, "show", "HEAD:b.txt") == "old"
    assert _git(root, "diff", "--name-only") == "a.txt\nb.txt"


def test_stage_rereads_same_size_same_timestamp_tracked_file(tmp_path):
    import os

    engine, leases = _fixture(tmp_path)
    _git(tmp_path, "config", "core.trustctime", "false")
    file = tmp_path / "a"
    file.write_text("old", encoding="utf-8")
    _git(tmp_path, "add", "a")
    previous = file.stat()
    file.write_text("new", encoding="utf-8")
    os.utime(file, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    kwargs = dict(root=str(tmp_path.resolve()), paths=["a"], expected_revision="a" * 64)
    preview = stage_selection({}, engine, leases, **kwargs)
    assert preview["success"], preview
    result = stage_selection({}, engine, leases, **kwargs, expected_tree=preview["prospective_tree_oid"], apply=True)
    assert result["success"], result
    assert _git(tmp_path, "show", ":a") == "new"
