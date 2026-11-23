import json
from threading import Thread

import pytest

from local_ai_hub.state_lifecycle import read_state_version, write_state_version
from tools import state_migrations, update_install


def layout(root, version):
    for name in ("src", "tools", "skills"):
        directory = root / name
        directory.mkdir(parents=True)
        (directory / "version.txt").write_text(version, encoding="utf-8")
    (root / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n', encoding="utf-8")


@pytest.mark.parametrize("failure", [None, "activation", "migration", "rollback_stop", "missing_step", "backup"])
def test_update_applies_consecutive_steps_or_restores_install(tmp_path, monkeypatch, failure):
    install, source = tmp_path / "install", tmp_path / "source"
    layout(install, "6.1.1")
    layout(source, "6.1.2")
    config = install / "config.toml"
    config.write_bytes(b"# preserve user configuration\r\n")
    venv = install / ".venv"
    venv.mkdir()
    (venv / "runtime.txt").write_text("old", encoding="utf-8")
    state = install / "state"
    state.mkdir()
    payload = state / "records.json"
    payload.write_text(json.dumps({"records": ["original"]}), encoding="utf-8")
    (state / "service.managed").touch()
    write_state_version(state, version=1)
    events = []

    def step(path, number):
        assert events[0] == "stop"
        data = path / "records.json"
        records = json.loads(data.read_text())["records"]
        records.append(str(number))
        data.write_text(json.dumps({"records": records}), encoding="utf-8")
        if failure == "migration" and number == 3:
            raise RuntimeError("second migration failed")

    migrations = tuple(state_migrations.StateMigration(
        number - 1, number, lambda path, n=number: step(path, n),
        lambda path, n=number: json.loads((path / "records.json").read_text())["records"][-1] == str(n),
    ) for number in (2, 3))
    if failure == "missing_step":
        migrations = migrations[:1]
    if failure == "backup":
        def incomplete_backup(path, version):
            partial = path.with_name(f"{path.name}.backup-v{version}-partial")
            partial.mkdir()
            raise OSError("backup copy failed")

        monkeypatch.setattr(state_migrations, "_make_backup", incomplete_backup)
    monkeypatch.setattr(update_install, "configured_state", lambda root: state)
    monkeypatch.setattr(update_install, "inspect_state_migration_path", lambda path: state_migrations.inspect_state_migration_path(
        path, migrations=migrations, target_version=3,
    ))
    monkeypatch.setattr(update_install, "run_state_migrations", lambda path, **kwargs: state_migrations.run_state_migrations(
        path, migrations=migrations, target_version=3, **kwargs,
    ))
    def prepare(*args):
        assert failure != "missing_step"

    monkeypatch.setattr(update_install, "prepare_dependencies", prepare)

    def install_runtime(*args):
        assert (source / "src/version.txt").read_text() == "6.1.2"
        (venv / "runtime.txt").write_text("new", encoding="utf-8")

    def start(*args, restoring=False):
        installed = (install / "src/version.txt").read_text(encoding="utf-8")
        assert restoring is (installed == "6.1.1")
        events.append(f"start {installed}")
        if failure in {"activation", "rollback_stop"} and installed == "6.1.2":
            payload.write_text(json.dumps({"records": ["written by failed candidate"]}), encoding="utf-8")
            raise RuntimeError("candidate health failed")

    def stop(*args, **kwargs):
        events.append("stop")
        if failure == "rollback_stop" and events.count("stop") == 2:
            return False, "could not confirm candidate stop"
        return True, "stopped"

    monkeypatch.setattr(update_install, "install_runtime", install_runtime)
    monkeypatch.setattr(update_install, "start_service", start)
    monkeypatch.setattr(update_install, "stop_existing_runtime", stop)
    if failure == "missing_step":
        with pytest.raises(RuntimeError, match="migration"):
            update_install.install_candidate(source, install, state, tmp_path / "wheel.whl", "6.1.2", "6.1.1")
        assert not events
        assert read_state_version(state) == 1
        assert (install / "src/version.txt").read_text() == "6.1.1"
        return

    result = update_install.install_candidate(source, install, state, tmp_path / "wheel.whl", "6.1.2", "6.1.1")
    assert result["success"] is (failure is None)
    assert config.read_bytes() == b"# preserve user configuration\r\n"
    restored = failure in {"activation", "migration", "backup"}
    assert read_state_version(state) == (1 if restored else 3)
    expected_records = {
        None: ["original", "2", "3"], "activation": ["original"],
        "migration": ["original"], "rollback_stop": ["written by failed candidate"], "backup": ["original"],
    }
    assert json.loads(payload.read_text())["records"] == expected_records[failure]
    assert (venv / "runtime.txt").read_text() == ("old" if restored else "new")
    assert (install / "src/version.txt").read_text() == ("6.1.1" if restored else "6.1.2")
    if restored:
        assert result["previous_install_restored"] is True
        assert "runtime remains stopped" not in result["message"]
    expected_events = {
        None: ["stop", "start 6.1.2"], "activation": ["stop", "start 6.1.2", "stop", "start 6.1.1"],
        "migration": ["stop", "start 6.1.1"], "rollback_stop": ["stop", "start 6.1.2", "stop"],
        "backup": ["stop", "start 6.1.1"],
    }
    assert events == expected_events[failure]
    backup, = state.parent.glob("state.backup-v1-*")
    if failure == "backup":
        assert backup.name.endswith("-partial")
        assert result["backups"] == []
    else:
        assert result["backups"] == [str(backup)]
        assert read_state_version(backup) == 1
        assert json.loads((backup / "records.json").read_text()) == {"records": ["original"]}
    if failure == "rollback_stop":
        assert "rollback blocked" in result["message"]
        assert (update_install.update_recovery_path(install) / ".venv/runtime.txt").read_text() == "old"
        with pytest.raises(RuntimeError, match="previous update requires recovery"):
            with update_install.installation_update_lock(install):
                pass


def test_same_schema_backup_does_not_change_live_state(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    write_state_version(state, version=3)
    (state / "records.json").write_bytes(b"preserve existing data")
    result = state_migrations.run_state_migrations(state, target_version=3, backup_current=True)
    assert result["status"] == "current"
    backup, = state.parent.glob("state.backup-v3-*")
    assert (backup / "records.json").read_bytes() == (state / "records.json").read_bytes()


def test_update_lock_blocks_other_operations(tmp_path):
    install = tmp_path / "install"
    attempted = []

    def contender():
        with pytest.raises(TimeoutError):
            with update_install.installation_update_lock(install, timeout=0):
                pass
        attempted.append(True)

    with update_install.installation_update_lock(install):
        thread = Thread(target=contender)
        thread.start()
        thread.join(timeout=2)
    assert attempted == [True]
