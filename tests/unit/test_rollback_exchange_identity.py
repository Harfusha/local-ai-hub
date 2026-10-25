"""Owned rename changes ctime; other postimage changes must remain fenced."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from local_ai_hub import commands


def _exchange_fixture(monkeypatch, *, tamper=None, before_change=False, tamper_stage=False):
    expected = commands.RollbackPostimage(True, (1, 2, 3, 4, 5, 0o600, "content", "metadata"))
    staged = commands.RollbackPostimage(True, (1, 9, 6, 7, 8, 0o640, "original", "original-meta"))
    entries = {"leaf": expected, "stage": staged}
    if before_change:
        entries["leaf"] = replace(expected, fingerprint=(1, 2, 3, 4, 6, 0o600, "content", "metadata"))
    exchanges = []
    unlinks = []

    def exchange(parent, source, destination):
        exchanges.append((parent, source, destination))
        entries[source], entries[destination] = entries[destination], entries[source]
        for name in (source, destination):
            values = list(entries[name].fingerprint)
            values[4] += 10
            entries[name] = replace(entries[name], fingerprint=tuple(values))
        if tamper is not None and len(exchanges) == 1:
            index, value = tamper
            values = list(entries[source].fingerprint)
            values[index] = value
            entries[source] = replace(entries[source], fingerprint=tuple(values))
        if tamper_stage and len(exchanges) == 1:
            values = list(entries[destination].fingerprint)
            values[6] = "foreign staged replacement"
            entries[destination] = replace(entries[destination], fingerprint=tuple(values))

    monkeypatch.setattr(commands, "_rollback_postimage_at", lambda parent, leaf: entries[leaf])
    monkeypatch.setattr(commands, "_rename_exchange_at", exchange)
    monkeypatch.setattr(commands, "os", SimpleNamespace(**{
        **vars(commands.os), "unlink": lambda name, **kwargs: unlinks.append(name),
    }))
    return expected, entries, exchanges, unlinks


def test_owned_exchange_accepts_only_rename_ctime_change(monkeypatch):
    expected, entries, exchanges, unlinks = _exchange_fixture(monkeypatch)
    commands._restore_existing_rollback_leaf(17, "stage", "leaf", expected)
    assert len(exchanges) == 1
    assert unlinks == ["stage"]
    assert entries["leaf"].fingerprint[6] == "original"


def test_exchange_rejects_ctime_change_before_owned_rename(monkeypatch):
    expected, _, exchanges, unlinks = _exchange_fixture(monkeypatch, before_change=True)
    with pytest.raises(commands._RollbackPostimageChanged, match="before atomic exchange"):
        commands._restore_existing_rollback_leaf(17, "stage", "leaf", expected)
    assert exchanges == []
    assert unlinks == []


@pytest.mark.parametrize("invalid", [
    commands.RollbackPostimage(False, None),
    commands.RollbackPostimage(True, None),
])
def test_after_owned_rename_rejects_missing_or_unsafe_postimages(invalid):
    valid = commands.RollbackPostimage(True, (1, 2, 3, 4, 5, 0o600, "content", "metadata"))
    assert not commands._same_rollback_postimage_after_owned_rename(invalid, valid)
    assert not commands._same_rollback_postimage_after_owned_rename(valid, invalid)


def test_exchange_preserves_entries_when_staged_replacement_also_changes(monkeypatch):
    expected, entries, exchanges, unlinks = _exchange_fixture(
        monkeypatch, tamper=(6, "concurrent content"), tamper_stage=True,
    )
    with pytest.raises(commands._RollbackPostimageChanged) as failure:
        commands._restore_existing_rollback_leaf(17, "stage", "leaf", expected)
    assert failure.value.preserve_temporary is True
    assert len(exchanges) == 1
    assert unlinks == []
    assert entries["leaf"].fingerprint[6] == "foreign staged replacement"
    assert entries["stage"].fingerprint[6] == "concurrent content"


@pytest.mark.parametrize("tamper", [
    (0, 99), (1, 99), (2, 99), (3, 99), (4, 0),
    (5, 0o777), (6, "concurrent content"), (7, "concurrent metadata"),
])
def test_exchange_restores_concurrent_postimage_without_unlink(monkeypatch, tamper):
    expected, entries, exchanges, unlinks = _exchange_fixture(monkeypatch, tamper=tamper)
    with pytest.raises(commands._RollbackPostimageChanged, match="during atomic exchange"):
        commands._restore_existing_rollback_leaf(17, "stage", "leaf", expected)
    assert len(exchanges) == 2
    assert unlinks == []
    index, value = tamper
    assert entries["leaf"].fingerprint[index] == (value + 10 if index == 4 else value)
