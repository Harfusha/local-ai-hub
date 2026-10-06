from __future__ import annotations

import json
import sys
from pathlib import Path

from tools import hubctl


def test_service_status_honors_explicit_config(tmp_path, monkeypatch, capsys):
    explicit_state = tmp_path / "explicit-state"
    environment_state = tmp_path / "environment-state"
    root_state = tmp_path / "root-state"
    explicit_state.mkdir()
    environment_state.mkdir()
    root_state.mkdir()
    (explicit_state / "supervisor.status.json").write_text(
        json.dumps({"source": "explicit-config"}), encoding="utf-8"
    )
    (environment_state / "supervisor.status.json").write_text(
        json.dumps({"source": "environment-config"}), encoding="utf-8"
    )
    (root_state / "supervisor.status.json").write_text(
        json.dumps({"source": "root-config"}), encoding="utf-8"
    )
    explicit_config = tmp_path / "explicit.toml"
    environment_config = tmp_path / "environment.toml"
    root_config = tmp_path / "root.toml"
    explicit_config.write_text(
        f'[server]\nstate_dir = "{explicit_state.as_posix()}"\n', encoding="utf-8"
    )
    environment_config.write_text(
        f'[server]\nstate_dir = "{environment_state.as_posix()}"\n', encoding="utf-8"
    )
    root_config.write_text(
        f'[server]\nstate_dir = "{root_state.as_posix()}"\n', encoding="utf-8"
    )
    monkeypatch.setattr(hubctl, "ROOT_CONFIG", root_config)
    monkeypatch.setenv("LOCAL_AI_CONFIG", str(environment_config))
    monkeypatch.setattr(
        sys,
        "argv",
        ["hubctl.py", "--config", str(explicit_config), "service-status"],
    )

    assert hubctl.main() == 0

    assert json.loads(capsys.readouterr().out) == {"source": "explicit-config"}
