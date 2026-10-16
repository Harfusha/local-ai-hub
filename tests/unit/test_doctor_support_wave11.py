from __future__ import annotations

from pathlib import Path
import pytest

from local_ai_hub.doctor_support import (
    format_doctor_summary,
    installed_models_from_status,
    is_git_precommit_hook_installed,
    managed_serena_executable,
    probe_hub_status,
)


def test_doctor_support_installed_models_strips_null_bytes() -> None:
    # installed_models_from_status strips null bytes
    status = {"installed_models": ["qwen2.5-coder:7b\x00", "  ", None, 123]}
    models = installed_models_from_status(status)
    assert "qwen2.5-coder:7b" in models
    assert "\x00" not in list(models)[0]
    assert "" not in models


def test_doctor_support_managed_serena_executable_null_bytes() -> None:
    # Null bytes in install_dir should not crash with ValueError
    res = managed_serena_executable("C:\\invalid\x00dir", lambda _name: "fallback-serena")
    assert res == "fallback-serena"


def test_doctor_support_probe_hub_status_none_client() -> None:
    # None client should safely return offline probe without raising AttributeError
    probe = probe_hub_status(None)
    assert probe["hub_online"] is False
    assert probe["status_available"] is False
    assert probe["code_intelligence_status"]["reason"] == "hub_offline"


def test_doctor_support_precommit_hook_helpers_and_null_bytes(tmp_path: Path) -> None:
    from local_ai_hub.doctor_support import (
        install_git_precommit_hook,
        uninstall_git_precommit_hook,
    )

    # Null bytes in repo_root for hook installation/removal
    res_install = install_git_precommit_hook("invalid\x00root")
    assert res_install["success"] is False
    assert "invalid" in res_install["error"].lower()

    res_uninstall = uninstall_git_precommit_hook("invalid\x00root")
    assert res_uninstall["success"] is False

    # is_git_precommit_hook_installed
    assert is_git_precommit_hook_installed(tmp_path) is False
    assert is_git_precommit_hook_installed("invalid\x00path") is False
    assert is_git_precommit_hook_installed(None) is False  # type: ignore[arg-type]


def test_doctor_support_format_summary() -> None:
    online_probe = {
        "hub_online": True,
        "status_available": True,
        "status": {"version": "1.0.0"},
        "code_intelligence_status": {"available": True, "reason": None},
    }
    summary = format_doctor_summary(online_probe)
    assert "online" in summary.lower()
    assert "available" in summary.lower()

    offline_probe = {
        "hub_online": False,
        "status_available": False,
        "status": {},
        "code_intelligence_status": {"available": False, "reason": "hub_offline"},
    }
    summary_offline = format_doctor_summary(offline_probe)
    assert "offline" in summary_offline.lower()
