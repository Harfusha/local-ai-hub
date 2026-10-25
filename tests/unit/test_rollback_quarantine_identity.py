"""Exercise the POSIX quarantine branch with deterministic owned-rename effects."""
from dataclasses import replace
import stat
from types import SimpleNamespace

import pytest

from local_ai_hub import commands


def _quarantine_fixture(tmp_path, monkeypatch, *, tamper=None, before_change=False, recreate=False):
    expected = commands.RollbackPostimage(True, (1, 2, 3, 4, 5, 0o600, "content", "metadata"))
    entries = {"created.txt": expected}
    if before_change:
        entries["created.txt"] = replace(expected, fingerprint=(1, 2, 3, 4, 6, 0o600, "content", "metadata"))
    renames, unlinks = [], []

    def rename(parent, source, destination):
        assert parent == 17
        if destination in entries:
            raise FileExistsError(destination)
        value = entries.pop(source)
        if value.fingerprint is not None:
            fields = list(value.fingerprint)
            fields[4] += 10
            value = replace(value, fingerprint=tuple(fields))
        renames.append((source, destination))
        if tamper is not None and len(renames) == 1:
            index, changed = tamper
            if index == "safe":
                value = replace(value, safe=changed)
            elif index == "fingerprint":
                value = replace(value, fingerprint=changed)
            else:
                fields = list(value.fingerprint)
                fields[index] = changed
                value = replace(value, fingerprint=tuple(fields))
        entries[destination] = value

    def file_stat(name, **kwargs):
        if name not in entries:
            raise FileNotFoundError(name)
        return SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_nlink=1)

    def unlink(name, **kwargs):
        unlinks.append(name)
        del entries[name]
        if recreate:
            entries["created.txt"] = replace(expected, fingerprint=(1, 99, 3, 4, 30, 0o600, "foreign", "metadata"))

    monkeypatch.setattr(commands, "_acquire_rollback_root", lambda root: 18)
    monkeypatch.setattr(commands, "_close_rollback_root", lambda handle: None)
    monkeypatch.setattr(commands, "_rollback_root_identity", lambda handle: (1, 2))
    monkeypatch.setattr(commands, "_open_rollback_parent_handle", lambda *args, **kwargs: (17, False))
    monkeypatch.setattr(commands, "_rollback_postimage_at", lambda parent, name: entries[name])
    monkeypatch.setattr(commands, "_rename_noreplace_at", rename)
    monkeypatch.setattr(commands, "os", SimpleNamespace(**{
        **vars(commands.os), "name": "posix", "stat": file_stat, "unlink": unlink,
    }))
    snapshot = SimpleNamespace(root=tmp_path.resolve(), root_guard=17, root_identity=(1, 2),
        files={"created.txt": SimpleNamespace(content=None, mode=0o600)},
        postimages={"created.txt": expected})
    return snapshot, entries, renames, unlinks


def test_created_file_quarantine_accepts_only_owned_rename_ctime(tmp_path, monkeypatch):
    snapshot, entries, renames, unlinks = _quarantine_fixture(tmp_path, monkeypatch)
    commands._restore_rollback_scope(str(tmp_path), snapshot)
    assert entries == {}
    assert len(renames) == 1 and unlinks == [renames[0][1]]


def test_quarantine_rejects_ctime_change_before_rename(tmp_path, monkeypatch):
    snapshot, entries, renames, unlinks = _quarantine_fixture(tmp_path, monkeypatch, before_change=True)
    with pytest.raises(OSError, match="rollback skipped"):
        commands._restore_rollback_scope(str(tmp_path), snapshot)
    assert renames == [] and unlinks == [] and "created.txt" in entries


@pytest.mark.parametrize("tamper", [
    (0, 99), (1, 99), (2, 99), (3, 99), (4, 0),
    (5, 0o777), (6, "foreign content"), (7, "foreign metadata"),
    ("safe", False), ("fingerprint", None),
])
def test_quarantine_restores_concurrent_changes_without_unlink(tmp_path, monkeypatch, tamper):
    snapshot, entries, renames, unlinks = _quarantine_fixture(tmp_path, monkeypatch, tamper=tamper)
    with pytest.raises(OSError, match="rollback skipped"):
        commands._restore_rollback_scope(str(tmp_path), snapshot)
    assert len(renames) == 2 and unlinks == []
    assert "created.txt" in entries


def test_quarantine_preserves_new_entry_created_during_owned_delete(tmp_path, monkeypatch):
    snapshot, entries, renames, unlinks = _quarantine_fixture(tmp_path, monkeypatch, recreate=True)
    with pytest.raises(OSError, match="rollback skipped"):
        commands._restore_rollback_scope(str(tmp_path), snapshot)
    assert len(renames) == 1 and unlinks == [renames[0][1]]
    assert entries["created.txt"].fingerprint[6] == "foreign"
