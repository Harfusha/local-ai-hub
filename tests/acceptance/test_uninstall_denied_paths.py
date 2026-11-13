from __future__ import annotations

import sys
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import uninstall
from install_ownership import write_install_manifest


def test_uninstall_denials_never_stop_or_delete(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    source = tmp_path / "source"
    source.mkdir()
    unowned = home / ".local-ai-hub"
    unowned.mkdir()
    cases = (
        (home, "home"),
        (Path(source.anchor), "unsafe uninstall path"),
        (source.parent, "unsafe uninstall path"),
        (source, "source"),
        (unowned, "marker"),
    )
    stop_calls: list[Path] = []
    delete_calls: list[Path] = []

    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(uninstall, "configured_install_dir", lambda: unowned)
    monkeypatch.setattr(uninstall, "stop_hub", lambda path: stop_calls.append(path) or uninstall.StopResult("stopped"))
    monkeypatch.setattr(uninstall.shutil, "rmtree", lambda path, **_kwargs: delete_calls.append(Path(path)))
    monkeypatch.setattr(sys, "argv", ["uninstall.py"])

    for target, expected in cases:
        try:
            uninstall.build_uninstall_plan(target, source_root=source, home=home)
        except ValueError as exc:
            assert expected in str(exc).lower() or "unsafe uninstall path" in str(exc).lower()
        else:
            raise AssertionError(f"unsafe target accepted: {target}")

    assert uninstall.main() == 1
    assert stop_calls == []
    assert delete_calls == []
    assert home.is_dir() and source.is_dir() and unowned.is_dir()


def test_uninstall_denies_symlink_target_without_stop_or_delete(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    source = tmp_path / "source"
    install = tmp_path / "install"
    link = tmp_path / "linked-install"
    home.mkdir()
    source.mkdir()
    install.mkdir()
    try:
        link.symlink_to(install, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    stop_calls: list[Path] = []
    delete_calls: list[Path] = []
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(uninstall, "configured_install_dir", lambda: link)
    monkeypatch.setattr(uninstall, "stop_hub", lambda path: stop_calls.append(path) or uninstall.StopResult("stopped"))
    monkeypatch.setattr(uninstall.shutil, "rmtree", lambda path, **_kwargs: delete_calls.append(Path(path)))
    monkeypatch.setattr(sys, "argv", ["uninstall.py"])

    assert uninstall.main() == 1
    assert stop_calls == []
    assert delete_calls == []
    assert install.is_dir() and link.is_symlink()


def test_uninstall_unconfirmed_stop_preserves_owned_tree(tmp_path: Path, monkeypatch) -> None:
    install = tmp_path / "install"
    install.mkdir()
    write_install_manifest(install)
    (install / "sentinel.txt").write_text("keep", encoding="utf-8")
    stop_calls: list[Path] = []
    delete_calls: list[Path] = []
    monkeypatch.setattr(uninstall, "configured_install_dir", lambda: install)
    monkeypatch.setattr(uninstall, "stop_hub", lambda path: stop_calls.append(path) or uninstall.StopResult("unconfirmed"))
    monkeypatch.setattr(uninstall.shutil, "rmtree", lambda path, **_kwargs: delete_calls.append(Path(path)))
    monkeypatch.setattr(sys, "argv", ["uninstall.py"])

    assert uninstall.main() == 1
    assert stop_calls == [install]
    assert delete_calls == []
    assert (install / "sentinel.txt").read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("stop_failure", ["timeout", "stale_pid", "still_running", "nonzero_exit"])
def test_uninstall_stop_failures_never_delete_owned_tree(tmp_path: Path, monkeypatch, stop_failure: str) -> None:
    install = tmp_path / "install"
    (install / "tools").mkdir(parents=True)
    (install / "tools" / "hubctl.py").write_text("# fixture", encoding="utf-8")
    (install / "config.toml").write_text("[server]\n", encoding="utf-8")
    (install / "sentinel.txt").write_text("keep", encoding="utf-8")
    write_install_manifest(install)
    delete_calls: list[Path] = []
    monkeypatch.setattr(uninstall, "configured_install_dir", lambda: install)
    monkeypatch.setattr(uninstall.shutil, "rmtree", lambda path, **_kwargs: delete_calls.append(Path(path)))
    monkeypatch.setattr(sys, "argv", ["uninstall.py"])

    if stop_failure == "stale_pid":
        monkeypatch.setattr(uninstall, "_owned_hub_pids", lambda _install: None)
        run_calls = []
        monkeypatch.setattr(uninstall.subprocess, "run", lambda *_args, **_kwargs: run_calls.append(True))
    elif stop_failure == "timeout":
        monkeypatch.setattr(uninstall, "_owned_hub_pids", lambda _install: [123])
        run_calls = []

        def timeout(*_args, **_kwargs):
            run_calls.append(True)
            raise subprocess.TimeoutExpired("hubctl stop", timeout=10)

        monkeypatch.setattr(uninstall.subprocess, "run", timeout)
    elif stop_failure == "still_running":
        pid_states = iter(([123], [123]))
        monkeypatch.setattr(uninstall, "_owned_hub_pids", lambda _install: next(pid_states))
        run_calls = []

        def reports_success(*_args, **_kwargs):
            run_calls.append(True)
            return subprocess.CompletedProcess(["hubctl", "stop"], 0, stdout="", stderr="")

        monkeypatch.setattr(uninstall.subprocess, "run", reports_success)
    else:
        pid_states = iter(([123], []))
        monkeypatch.setattr(uninstall, "_owned_hub_pids", lambda _install: next(pid_states))
        run_calls = []

        def reports_failure(*_args, **_kwargs):
            run_calls.append(True)
            return subprocess.CompletedProcess(["hubctl", "stop"], 5, stdout="", stderr="stop error")

        monkeypatch.setattr(uninstall.subprocess, "run", reports_failure)

    assert uninstall.main() == 1
    assert delete_calls == []
    assert (install / "sentinel.txt").read_text(encoding="utf-8") == "keep"
    assert len(run_calls) == (0 if stop_failure == "stale_pid" else 1)


@pytest.mark.parametrize(("pid_states", "expected_status"), [([[]], "already_stopped"), ([[123], []], "stopped")])
def test_stop_hub_distinguishes_absent_from_confirmed_stopped_processes(
    tmp_path: Path, monkeypatch, pid_states: list[list[int]], expected_status: str
) -> None:
    install = tmp_path / "install"
    (install / "tools").mkdir(parents=True)
    (install / "tools" / "hubctl.py").write_text("# fixture", encoding="utf-8")
    states = iter(pid_states)
    monkeypatch.setattr(uninstall, "_owned_hub_pids", lambda _install: next(states))
    monkeypatch.setattr(
        uninstall.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(["hubctl", "stop"], 0, stdout="", stderr=""),
    )

    result = uninstall.stop_hub(install)

    assert result.status == expected_status
