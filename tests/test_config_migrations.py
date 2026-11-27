from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from local_ai_hub.config import ConfigError, load_config
from tools.config_migrations import ConfigMigrationError, run_config_migrations


def test_config_migration_moves_legacy_trace_settings_and_keeps_recovery_copy(tmp_path):
    path = tmp_path / "config.toml"
    original = (
        "# operator note\n[server]\nstate_dir = \"state\"\n\n"
        "[telemetry]\nmode = \"minimal\"\n\n"
        "[debug_traces]\nenabled = true\nmax_sessions = 17\nmax_bytes = 4096\n"
    )
    path.write_text(original, encoding="utf-8")

    result = run_config_migrations(path)

    migrated = tomllib.loads(path.read_text(encoding="utf-8"))
    assert result["status"] == "migrated"
    backup, = result["backups"]
    assert Path(backup).read_text(encoding="utf-8") == original
    assert migrated["telemetry"]["mode"] == "full"
    assert migrated["telemetry"]["max_sessions"] == 17
    assert migrated["telemetry"]["max_bytes"] == 4096
    assert migrated["local_ai_hub"]["config_schema_version"] == 1
    assert "debug_traces" not in migrated
    assert "operator note" in path.read_text(encoding="utf-8")
    assert run_config_migrations(path)["status"] == "current"


def test_config_migration_maps_nested_trace_table_and_respects_explicit_storage_limits(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        "[telemetry]\nmode = \"off\"\nmax_bytes = 2048\n\n"
        "[observability.debug_traces]\nenabled = true\nmax_bytes = 8192\nmax_sessions = 22\n",
        encoding="utf-8",
    )

    run_config_migrations(path)

    migrated = tomllib.loads(path.read_text(encoding="utf-8"))
    assert migrated["telemetry"]["mode"] == "full"
    assert migrated["telemetry"]["max_bytes"] == 2048
    assert "max_sessions" not in migrated["telemetry"]
    assert "debug_traces" not in migrated.get("observability", {})


@pytest.mark.parametrize("source", [
    "[debug_traces]\nenabled = true\nunknown_limit = 1\n",
    "[local_ai_hub]\nconfig_schema_version = 2\n",
    "[local_ai_hub]\nconfig_schema_version = 1\n[debug_traces]\nenabled = true\n",
])
def test_config_migration_fails_closed_without_changing_ambiguous_or_future_config(tmp_path, source):
    path = tmp_path / "config.toml"
    path.write_text(source, encoding="utf-8")

    with pytest.raises(ConfigMigrationError):
        run_config_migrations(path)

    assert path.read_text(encoding="utf-8") == source


def test_current_unversioned_config_is_stamped_with_schema_version(tmp_path):
    path = tmp_path / "config.toml"
    original = '[telemetry]\nmode = "minimal"\n'
    path.write_text(original, encoding="utf-8")

    result = run_config_migrations(path)

    assert result["status"] == "migrated"
    backup, = result["backups"]
    assert Path(backup).read_text(encoding="utf-8") == original
    assert tomllib.loads(path.read_text(encoding="utf-8"))["local_ai_hub"]["config_schema_version"] == 1


def test_config_migration_converts_runtime_override_alongside_base_config(tmp_path):
    path = tmp_path / "config.toml"
    runtime = tmp_path / "config.runtime.toml"
    path.write_text('[server]\nstate_dir = "state"\n', encoding="utf-8")
    runtime.write_text('[debug_traces]\nenabled = true\n', encoding="utf-8")

    result = run_config_migrations(path)

    assert result["status"] == "migrated"
    assert len(result["backups"]) == 2
    assert all(Path(backup).exists() for backup in result["backups"])
    migrated = tomllib.loads(runtime.read_text(encoding="utf-8"))
    assert migrated["telemetry"]["mode"] == "full"
    assert "debug_traces" not in migrated


def test_setup_does_not_migrate_legacy_config_for_fresh_install(tmp_path):
    from tools.setup import select_config_source

    path = tmp_path / "config.toml"
    install = tmp_path / "installed-hub"
    path.write_text(
        f'[setup]\ninstall_dir = "{install.as_posix()}"\n'
        f'[server]\nstate_dir = "{(tmp_path / "state").as_posix()}"\n'
        '[debug_traces]\nenabled = true\n',
        encoding="utf-8",
    )

    original = path.read_text(encoding="utf-8")

    with pytest.raises(ConfigError, match="config_schema_version.*updater"):
        select_config_source(path)

    assert path.read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob("config.toml.backup-config-v0-*"))


def test_setup_does_not_treat_a_config_file_as_an_existing_install(tmp_path):
    from tools import setup

    path = tmp_path / "config.toml"
    install = tmp_path / "installed-hub"
    install.mkdir()
    (install / "config.toml").write_text(
        f'[local_ai_hub]\nconfig_schema_version = 1\n[setup]\ninstall_dir = "{install.as_posix()}"\n',
        encoding="utf-8",
    )
    path.write_text(
        f'[setup]\ninstall_dir = "{install.as_posix()}"\n'
        '[debug_traces]\nenabled = true\n',
        encoding="utf-8",
    )
    original = path.read_text(encoding="utf-8")

    with pytest.raises(ConfigError, match="config_schema_version.*updater"):
        setup.select_config_source(path)

    assert path.read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob("config.toml.backup-config-v0-*"))


def test_setup_config_source_migrates_only_for_an_existing_install(tmp_path):
    from tools.setup import select_config_source

    path = tmp_path / "config.toml"
    install = tmp_path / "installed-hub"
    install.mkdir()
    (install / "config.toml").write_text(
        f'[local_ai_hub]\nconfig_schema_version = 1\n[setup]\ninstall_dir = "{install.as_posix()}"\n',
        encoding="utf-8",
    )
    (install / "tools").mkdir()
    (install / "tools" / "service.py").write_text("# existing Hub entrypoint\n", encoding="utf-8")
    path.write_text(
        f'[setup]\ninstall_dir = "{install.as_posix()}"\n'
        f'[server]\nstate_dir = "{(tmp_path / "state").as_posix()}"\n'
        '[debug_traces]\nenabled = true\n',
        encoding="utf-8",
    )

    source, config, resolved_install = select_config_source(path)

    assert source == path
    assert resolved_install == install
    assert config["telemetry"]["mode"] == "full"
    assert "debug_traces" not in tomllib.loads(path.read_text(encoding="utf-8"))


def test_setup_does_not_migrate_when_install_target_config_is_invalid(tmp_path, monkeypatch):
    from tools import setup

    path = tmp_path / "config.toml"
    install = tmp_path / "installed-hub"
    install.mkdir()
    (install / "config.toml").write_text(
        f'[local_ai_hub]\nconfig_schema_version = 1\n[setup]\ninstall_dir = "{install.as_posix()}"\n',
        encoding="utf-8",
    )
    path.write_text('setup = "invalid"\n[debug_traces]\nenabled = true\n', encoding="utf-8")
    original = path.read_text(encoding="utf-8")
    monkeypatch.setattr(setup, "expand", lambda _value: install)

    with pytest.raises(ValueError, match="setup.*table"):
        setup.select_config_source(path)

    assert path.read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob("config.toml.backup-config-v0-*"))


def test_managed_updater_migrates_before_strict_config_load(tmp_path):
    from tools.update_install import configured_state

    install = tmp_path / "installed-hub"
    install.mkdir()
    config = install / "config.toml"
    state = tmp_path / "state"
    config.write_text(
        f'[setup]\ninstall_dir = "{install.as_posix()}"\n'
        f'[server]\nstate_dir = "{state.as_posix()}"\n'
        '[observability.debug_traces]\nenabled = true\n',
        encoding="utf-8",
    )

    assert configured_state(install) == state
    migrated = tomllib.loads(config.read_text(encoding="utf-8"))
    assert migrated["telemetry"]["mode"] == "full"
    assert "debug_traces" not in migrated.get("observability", {})


def test_runtime_rejects_retired_config_table_in_current_schema(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[local_ai_hub]\nconfig_schema_version = 1\n[debug_traces]\nenabled = true\n', encoding="utf-8"
    )

    with pytest.raises(ConfigError, match="is retired"):
        load_config(path, probe_hardware=False)


@pytest.mark.parametrize("unversioned_file", ["config.toml", "config.runtime.toml"])
def test_runtime_rejects_unmigrated_config_sources(tmp_path, unversioned_file):
    path = tmp_path / "config.toml"
    path.write_text('[local_ai_hub]\nconfig_schema_version = 1\n[server]\nport = 11435\n', encoding="utf-8")
    if unversioned_file == "config.toml":
        path.write_text('[server]\nport = 11435\n', encoding="utf-8")
    else:
        path.with_name("config.runtime.toml").write_text('[hardware]\nprofile = "cpu"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="config_schema_version.*updater"):
        load_config(path, probe_hardware=False)

    migrated = run_config_migrations(path)
    assert migrated["status"] == "migrated"
    assert load_config(path, probe_hardware=False)["server"]["port"] == 11435
