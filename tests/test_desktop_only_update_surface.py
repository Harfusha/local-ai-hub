from __future__ import annotations

import sys

import pytest

from tools import auto_update, hubctl


def test_retired_dashboard_cli_name_is_rejected(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["hubctl.py", "dashboard"])

    with pytest.raises(SystemExit) as caught:
        hubctl.main()

    assert caught.value.code == 2


def test_retired_dashboard_update_flag_is_rejected(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["auto_update.py", "--dashboard"])

    with pytest.raises(SystemExit) as caught:
        auto_update.main()

    assert caught.value.code == 2


@pytest.mark.parametrize("args", [
    ["changes", "commit-staged", "--root", "."],
    ["changes", "sequence-apply", "--root", ".", "--allow-unverified"],
])
def test_commit_compatibility_bypasses_are_rejected(monkeypatch, args):
    monkeypatch.setattr(sys, "argv", ["hubctl.py", *args])

    with pytest.raises(SystemExit) as caught:
        hubctl.main()

    assert caught.value.code == 2
