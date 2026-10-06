from __future__ import annotations

import importlib.util
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "rollback_snapshot.py"
COMPLETE_COVERAGE = ("--covers", "code", "config", "state")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_rollback_snapshot_restores_code_config_and_sqlite_state(tmp_path: Path) -> None:
    installation = tmp_path / "installation"
    installation.mkdir()
    (installation / "hub.py").write_text("version = 'old'\n", encoding="utf-8")
    config = tmp_path / "config.toml"
    config.write_text("[server]\nport = 8808\n", encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    database = state / "agent.db"
    seed_wal = (
        "import os, sqlite3, sys; "
        "connection=sqlite3.connect(sys.argv[1]); "
        "connection.execute('PRAGMA journal_mode=WAL'); "
        "connection.execute('PRAGMA wal_autocheckpoint=0'); "
        "connection.execute('CREATE TABLE evidence (evidence_id TEXT PRIMARY KEY, status TEXT)'); "
        "connection.commit(); "
        "connection.execute('INSERT INTO evidence VALUES (?, ?)', ('verified-123', 'passed')); "
        "connection.commit(); os._exit(0)"
    )
    seeded = subprocess.run([sys.executable, "-c", seed_wal, str(database)], capture_output=True, text=True, check=False)
    assert seeded.returncode == 0, seeded.stderr
    assert Path(str(database) + "-wal").is_file()
    assert Path(str(database) + "-shm").is_file()
    snapshot = tmp_path / "dated-backup"
    roots = (
        f"code={installation}",
        f"config={config}",
        f"state={state}",
    )

    created = _run("create", "--output", str(snapshot), *(item for root in roots for item in ("--root", root)), *COMPLETE_COVERAGE, "--service-stopped")
    assert created.returncode == 0, created.stderr
    assert "Complete rollback snapshot verified:" in created.stdout

    (installation / "hub.py").write_text("version = 'new'\n", encoding="utf-8")
    config.write_text("[server]\nport = 9999\n", encoding="utf-8")
    shutil.rmtree(state)
    state.mkdir()
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE upgrade_state (version TEXT)")
        connection.execute("INSERT INTO upgrade_state VALUES ('new')")
        connection.commit()

    restored = _run(
        "restore", "--snapshot", str(snapshot),
        *(item for root in roots for item in ("--root", root)),
        *COMPLETE_COVERAGE,
        "--service-stopped",
    )

    assert restored.returncode == 0, restored.stderr
    assert "Rollback restored and verified." in restored.stdout
    assert (installation / "hub.py").read_text(encoding="utf-8") == "version = 'old'\n"
    assert config.read_text(encoding="utf-8") == "[server]\nport = 8808\n"
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT evidence_id, status FROM evidence").fetchone() == ("verified-123", "passed")
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='upgrade_state'").fetchone() is None

    preserved_installation = list(tmp_path.glob("installation.pre-rollback-*"))
    preserved_config = list(tmp_path.glob("config.toml.pre-rollback-*"))
    preserved_state = list(tmp_path.glob("state.pre-rollback-*"))
    assert len(preserved_installation) == len(preserved_config) == len(preserved_state) == 1
    assert (preserved_installation[0] / "hub.py").read_text(encoding="utf-8") == "version = 'new'\n"
    assert preserved_config[0].read_text(encoding="utf-8") == "[server]\nport = 9999\n"
    with closing(sqlite3.connect(preserved_state[0] / "agent.db")) as connection:
        assert connection.execute("SELECT version FROM upgrade_state").fetchone() == ("new",)


def test_rollback_snapshot_requires_stopped_service_and_rejects_tampered_payload(tmp_path: Path) -> None:
    code = tmp_path / "code"
    code.mkdir()
    source = code / "hub.py"
    source.write_text("version = 'old'\n", encoding="utf-8")
    config = tmp_path / "config.toml"
    config.write_text("[server]\nport = 8808\n", encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    snapshot = tmp_path / "dated-backup"
    roots = (f"code={code}", f"config={config}", f"state={state}")

    refused = _run("create", "--output", str(snapshot), *(item for root in roots for item in ("--root", root)), *COMPLETE_COVERAGE)
    assert refused.returncode == 2
    assert "stop the Hub service" in refused.stderr
    assert not snapshot.exists()

    incomplete = _run("create", "--output", str(snapshot), "--root", roots[0], "--covers", "code", "--service-stopped")
    assert incomplete.returncode == 2
    assert "code, config and state" in incomplete.stderr
    assert not snapshot.exists()

    created = _run("create", "--output", str(snapshot), *(item for root in roots for item in ("--root", root)), *COMPLETE_COVERAGE, "--service-stopped")
    assert created.returncode == 0, created.stderr
    source.write_text("version = 'new'\n", encoding="utf-8")
    (snapshot / "payload" / "000" / "hub.py").write_text("tampered\n", encoding="utf-8")

    refused_restore = _run(
        "restore", "--snapshot", str(snapshot),
        *(item for root in roots for item in ("--root", root)),
        *COMPLETE_COVERAGE, "--service-stopped",
    )

    assert refused_restore.returncode == 2
    assert "integrity check failed" in refused_restore.stderr
    assert source.read_text(encoding="utf-8") == "version = 'new'\n"
    assert not list(tmp_path.glob("code.pre-rollback-*"))


def test_rollback_snapshot_recreates_a_missing_root(tmp_path: Path) -> None:
    installation = tmp_path / "installation"
    installation.mkdir()
    (installation / "hub.py").write_text("version = 'old'\n", encoding="utf-8")
    config = tmp_path / "config.toml"
    config.write_text("[server]\nport = 8808\n", encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    snapshot = tmp_path / "dated-backup"
    roots = (f"code={installation}", f"config={config}", f"state={state}")

    created = _run("create", "--output", str(snapshot), *(item for root in roots for item in ("--root", root)), *COMPLETE_COVERAGE, "--service-stopped")
    assert created.returncode == 0, created.stderr
    shutil.rmtree(installation)

    restored = _run(
        "restore", "--snapshot", str(snapshot),
        *(item for root in roots for item in ("--root", root)),
        *COMPLETE_COVERAGE, "--service-stopped",
    )

    assert restored.returncode == 0, restored.stderr
    assert (installation / "hub.py").read_text(encoding="utf-8") == "version = 'old'\n"


def test_rollback_snapshot_rejects_symlinked_root_ancestor(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    code = actual / "code"
    code.mkdir(parents=True)
    (code / "hub.py").write_text("version = 'old'\n", encoding="utf-8")
    config = actual / "config.toml"
    config.write_text("[server]\nport = 8808\n", encoding="utf-8")
    state = actual / "state"
    state.mkdir()
    redirected = tmp_path / "redirected"
    try:
        redirected.symlink_to(actual, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    snapshot = tmp_path / "dated-backup"
    roots = (f"code={redirected / 'code'}", f"config={redirected / 'config.toml'}", f"state={redirected / 'state'}")
    result = _run(
        "create", "--output", str(snapshot),
        *(item for root in roots for item in ("--root", root)),
        *COMPLETE_COVERAGE, "--service-stopped",
    )

    assert result.returncode == 2
    assert "symlinks or junctions" in result.stderr
    assert not snapshot.exists()


def test_rollback_snapshot_rejects_junctioned_root_ancestor(tmp_path: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows junctions are only available on Windows")
    actual = tmp_path / "actual"
    code = actual / "code"
    code.mkdir(parents=True)
    (code / "hub.py").write_text("version = 'old'\n", encoding="utf-8")
    config = actual / "config.toml"
    config.write_text("[server]\nport = 8808\n", encoding="utf-8")
    state = actual / "state"
    state.mkdir()
    redirected = tmp_path / "redirected"
    created = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(redirected), str(actual)],
        capture_output=True,
        text=True,
        check=False,
    )
    if created.returncode:
        pytest.skip(f"directory junction unavailable: {created.stderr or created.stdout}")

    snapshot = tmp_path / "dated-backup"
    roots = (f"code={redirected / 'code'}", f"config={redirected / 'config.toml'}", f"state={redirected / 'state'}")
    try:
        result = _run(
            "create", "--output", str(snapshot),
            *(item for root in roots for item in ("--root", root)),
            *COMPLETE_COVERAGE, "--service-stopped",
        )
    finally:
        subprocess.run(
            ["cmd.exe", "/d", "/c", "rmdir", str(redirected)],
            capture_output=True,
            text=True,
            check=False,
        )

    assert result.returncode == 2
    assert "symlinks or junctions" in result.stderr
    assert not snapshot.exists()


def test_python311_junction_detector_checks_windows_reparse_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = importlib.util.spec_from_file_location("rollback_snapshot_under_test", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        type(tmp_path),
        "lstat",
        lambda _path: SimpleNamespace(st_file_attributes=0x0400, st_reparse_tag=0xA0000003),
    )

    assert module._is_junction(tmp_path) is True
