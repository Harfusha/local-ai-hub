from __future__ import annotations

import json
from pathlib import Path
from local_ai_hub.state_lifecycle import (
    CURRENT_STATE_VERSION,
    STATE_VERSION_FILE,
    ensure_state_version,
    read_state_version,
    write_state_version,
    wipe_disposable_state,
)


def test_fresh_directory_initialization(tmp_path: Path):
    state_dir = tmp_path / "fresh_state"
    res = ensure_state_version(state_dir, target_version=6)

    assert res["status"] == "initialized"
    assert res["version"] == 6
    assert res["wiped"] is False
    assert (state_dir / STATE_VERSION_FILE).is_file()
    assert read_state_version(state_dir) == 6


def test_existing_version_preserved_without_wiping(tmp_path: Path):
    state_dir = tmp_path / "v6_state"
    state_dir.mkdir(parents=True)
    write_state_version(state_dir, version=6)
    dummy_db = state_dir / "cache.sqlite"
    dummy_db.write_bytes(b"some cache")

    res = ensure_state_version(state_dir, target_version=6)
    assert res["status"] == "current"
    assert res["wiped"] is False
    assert dummy_db.exists()
    assert dummy_db.read_bytes() == b"some cache"


def test_legacy_state_auto_wiped_on_upgrade(tmp_path: Path):
    state_dir = tmp_path / "legacy_state"
    state_dir.mkdir(parents=True)

    # Populate legacy databases and lockfiles
    (state_dir / "code-index.sqlite3").write_bytes(b"old code index")
    (state_dir / "cache.sqlite").write_bytes(b"old cache")
    (state_dir / "agent_state.sqlite").write_bytes(b"old agent state")
    (state_dir / ".agent_state.sqlite.plan-sync-0.lock").write_bytes(b"1")
    (state_dir / "diagnostics").mkdir()
    (state_dir / "diagnostics" / "diag.json").write_text("{}", encoding="utf-8")

    # Run ensure_state_version
    res = ensure_state_version(state_dir, target_version=6, auto_wipe=True)

    assert res["status"] == "upgraded_and_wiped"
    assert res["wiped"] is True
    assert res["version"] == 6
    assert read_state_version(state_dir) == 6

    # Disposable files and directories should be wiped
    assert not (state_dir / "code-index.sqlite3").exists()
    assert not (state_dir / "cache.sqlite").exists()
    assert not (state_dir / "agent_state.sqlite").exists()
    assert not (state_dir / ".agent_state.sqlite.plan-sync-0.lock").exists()
    assert not (state_dir / "diagnostics").exists()

    # Verify state_version.json metadata
    ver_data = json.loads((state_dir / STATE_VERSION_FILE).read_text(encoding="utf-8"))
    assert ver_data["version"] == 6
    assert ver_data["clean_slate_wiped"] is True
