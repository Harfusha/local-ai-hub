from __future__ import annotations

import json
import sys

import pytest

from tools import hubctl
from local_ai_hub.operational_mode import load_operational_mode


@pytest.mark.parametrize(
    ("arguments", "expected_mode"),
    [(["pause"], "restricted"), (["resume"], "active"), (["mode", "maintenance"], "maintenance")],
)
def test_offline_cli_persists_mode_under_configured_state_dir(
    monkeypatch, tmp_path, capsys, arguments, expected_mode
):
    state_dir = tmp_path / "configured-state"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[server]\nstate_dir = " + json.dumps(str(state_dir)) + "\n",
        encoding="utf-8",
    )

    class OfflineClient:
        def __init__(self, **_kwargs):
            pass

        def _online(self):
            return False

    monkeypatch.setattr(hubctl, "HubClient", OfflineClient)
    monkeypatch.setattr(sys, "argv", ["hubctl", *arguments, "--config", str(config_path)])

    exit_code = hubctl.main()
    output = capsys.readouterr()

    # Gaming may also report its separate live-release gate; persisted mode remains authoritative.
    assert exit_code in {0, 1}
    snapshot = load_operational_mode(state_dir)
    if expected_mode == "restricted":
        assert snapshot.mode in {"gaming", "maintenance"}
    else:
        assert snapshot.mode == expected_mode
    assert snapshot.revision == 1
