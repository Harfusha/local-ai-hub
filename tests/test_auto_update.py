import hashlib
import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from tools import auto_update
from tools.install_ownership import write_install_manifest


def release(tag="v6.1.2", **overrides):
    return {"tag_name": tag, "draft": False, "prerelease": False, "assets": [], **overrides}


@pytest.mark.parametrize("published", [release("v6.1.1"), release("v6.0.0"), release(prerelease=True), release(draft=True)])
def test_check_ignores_non_updates(monkeypatch, published):
    def fetch(url, limit):
        assert url == auto_update.LATEST_URL
        return json.dumps(published).encode()

    monkeypatch.setattr(auto_update, "read_url", fetch)
    assert auto_update.find_update("6.1.1") is None


def test_release_evidence_names_exact_commit_and_wheel(monkeypatch):
    wheel = "local_ai_hub-6.1.2-py3-none-any.whl"
    receipt = json.dumps({"repository_revision": "a" * 40, "success": True, "smoke": "passed",
                          "wheel_file": wheel, "wheel_sha256": "b" * 64}).encode()
    receipt_digest = hashlib.sha256(receipt).hexdigest()
    payload = release(assets=[{"name": "wheel-mcp-smoke.json", "digest": f"sha256:{receipt_digest}"},
                              {"name": wheel, "digest": "sha256:" + "b" * 64}])

    def fetch(url, limit):
        if url == auto_update.LATEST_URL:
            return json.dumps(payload).encode()
        assert url.endswith("/v6.1.2/wheel-mcp-smoke.json")
        return receipt

    monkeypatch.setattr(auto_update, "read_url", fetch)
    update = auto_update.find_update("6.1.1")
    assert (update.tag, update.revision, update.wheel_name) == ("v6.1.2", "a" * 40, wheel)

    payload["assets"][1]["digest"] = "sha256:" + "c" * 64
    with pytest.raises(ValueError, match="wheel digest"):
        auto_update.find_update("6.1.1")


@pytest.mark.parametrize("nested", [False, True])
def test_managed_target_refuses_checkout_even_with_ownership(tmp_path, nested):
    target = tmp_path / "managed" if nested else tmp_path
    target.mkdir(exist_ok=True)
    write_install_manifest(target)
    (tmp_path / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
    with pytest.raises(ValueError, match="checkout"):
        auto_update.managed_target(target)


def test_checkout_must_match_verified_commit_before_using_new_code(tmp_path, monkeypatch):
    release = auto_update.Release("v6.1.2", "a" * 40, "wheel.whl", "b" * 64)
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return type("Result", (), {"stdout": "c" * 40 + "\n"})()

    monkeypatch.setattr(auto_update.subprocess, "run", run)
    with pytest.raises(ValueError, match="verified commit"):
        auto_update.checkout_release(release, tmp_path / "source")
    assert all("checkout" not in command for command in commands)


def test_git_checkout_preserves_source_for_exact_release(tmp_path, monkeypatch):
    origin = tmp_path / "origin"
    origin.mkdir()

    def git(*args):
        return subprocess.run(["git", *args], cwd=origin, check=True, capture_output=True, text=True).stdout.strip()

    git("init", "-q")
    (origin / "pyproject.toml").write_text('[project]\nversion = "6.1.2"\n', encoding="utf-8")
    (origin / "RELEASE.json").write_text('{"version":"6.1.2","status":"production-ready"}', encoding="utf-8")
    git("add", "pyproject.toml", "RELEASE.json")
    git("-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "release")
    git("tag", "v6.1.2")
    release = auto_update.Release("v6.1.2", git("rev-parse", "HEAD"), "unused.whl", "b" * 64)
    monkeypatch.setattr(auto_update, "GIT_URL", origin.as_uri())
    target = tmp_path / "candidate"
    auto_update.checkout_release(release, target)
    assert (target / "RELEASE.json").read_bytes() == (origin / "RELEASE.json").read_bytes()


def test_dashboard_stale_release_is_persisted_without_installing(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_update, "ROOT", tmp_path)
    monkeypatch.setattr(auto_update, "managed_target", lambda root: None)
    monkeypatch.setattr(auto_update, "installed_version", lambda root: "6.1.1")
    monkeypatch.setattr(auto_update, "find_update", lambda current: auto_update.Release("v6.1.2", "b" * 40, "unused", "c" * 64))
    monkeypatch.setattr(auto_update, "apply_update", lambda *args: pytest.fail("stale release was applied"))
    monkeypatch.setattr(sys, "prefix", sys.base_prefix)
    monkeypatch.setattr(sys, "argv", ["auto_update.py", "--apply",
                                    "--expect-version", "6.1.2", "--expect-revision", "a" * 40])
    assert auto_update.main() == 1
    result = json.loads((tmp_path / "auto-update-report.json").read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert "reviewed release changed" in result["error"]


@pytest.mark.parametrize("publish_error", [False, True])
def test_dashboard_attempt_covers_final_report(tmp_path, monkeypatch, publish_error):
    target = tmp_path / "install"
    target.mkdir()
    report = target / "auto-update-report.json"
    stage = auto_update._attempt_path(target)
    wheel = b"synthetic wheel"
    release = auto_update.Release("v6.1.2", "a" * 40, "fixture.whl", hashlib.sha256(wheel).hexdigest())
    write_report = auto_update.write_install_report
    checks = []

    def checkout(_release, destination):
        tools = destination / "tools"
        tools.mkdir(parents=True)
        (tools / "update_install.py").write_text(
            "from pathlib import Path\nimport sys\n"
            "Path(sys.argv[-1]).write_text('{\"success\": true}', encoding='utf-8')\n",
            encoding="utf-8",
        )
        git_object = destination / ".git" / "objects" / "fixture"
        git_object.parent.mkdir(parents=True)
        git_object.write_bytes(b"fixture Git object")
        git_object.chmod(stat.S_IREAD)

    def find_update(current):
        checks.append(current)
        return release if len(checks) == 1 else None

    def publish(path, payload):
        if path == report and payload["status"] == "installed":
            if publish_error:
                raise OSError("injected report write failure")
            write_report(path, payload)
            assert auto_update.main() == 1
            return
        write_report(path, payload)

    monkeypatch.setattr(auto_update, "ROOT", target)
    monkeypatch.setattr(auto_update, "managed_target", lambda _root: None)
    monkeypatch.setattr(auto_update, "installed_version", lambda _root: "6.1.1")
    monkeypatch.setattr(auto_update, "find_update", find_update)
    monkeypatch.setattr(auto_update, "checkout_release", checkout)
    monkeypatch.setattr(auto_update, "read_url", lambda *_args: wheel)
    monkeypatch.setattr(auto_update, "write_install_report", publish)
    monkeypatch.setattr(sys, "prefix", sys.base_prefix)
    monkeypatch.setattr(sys, "argv", [
        "auto_update.py", "--apply", "--expect-version", release.version,
        "--expect-revision", release.revision,
    ])

    assert auto_update.main() == int(publish_error)
    if publish_error:
        assert json.loads((stage / "result.json").read_text(encoding="utf-8")) == {"success": True}
        assert (stage / "installer.log").is_file()
        assert auto_update.main() == 1
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == ("installing" if publish_error else "installed")
    assert checks == ["6.1.1"]
    assert stage.exists() is publish_error


def test_installer_can_finish_after_observation_timeout_without_replaying(tmp_path, monkeypatch):
    target = tmp_path / "install"
    target.mkdir()
    wheel = b"synthetic wheel"
    release = auto_update.Release("v6.1.2", "a" * 40, "fixture.whl", hashlib.sha256(wheel).hexdigest())
    fetched = []

    def checkout(_release, destination):
        fetched.append(destination)
        tools = destination / "tools"
        tools.mkdir(parents=True)
        (tools / "update_install.py").write_text(
            "from pathlib import Path\nimport sys, time\n"
            "time.sleep(0.3)\n"
            "report = Path(sys.argv[-1])\n"
            "temporary = report.with_suffix('.tmp')\n"
            "temporary.write_text('{\"success\": true}', encoding='utf-8')\n"
            "temporary.replace(report)\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(auto_update, "checkout_release", checkout)
    monkeypatch.setattr(auto_update, "read_url", lambda *_args: wheel)
    monkeypatch.setattr(auto_update, "_INSTALLER_WAIT_SECONDS", 0.01, raising=False)
    original_popen = subprocess.Popen
    installers = []

    def spawn(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        installers.append(process)
        return process

    monkeypatch.setattr(auto_update.subprocess, "Popen", spawn)
    result = auto_update.apply_update(release, "6.1.1", target)
    assert result["success"] is False and result["outcome_unknown"] is True
    assert result["retryable"] is False
    stage = Path(result["attempt_directory"])
    assert (stage / release.wheel_name).read_bytes() == wheel
    report = stage / "result.json"
    installer, = installers
    assert installer.wait(timeout=15) == 0
    assert json.loads(report.read_text(encoding="utf-8")) == {"success": True}
    with pytest.raises(ValueError, match="previous update attempt"):
        auto_update.apply_update(release, "6.1.1", target)
    assert fetched == [stage / "source"]
    report_path = target / "auto-update-report.json"
    report_path.write_text(json.dumps(result), encoding="utf-8")
    previous_report = report_path.read_bytes()
    monkeypatch.setattr(auto_update, "ROOT", target)
    monkeypatch.setattr(auto_update, "managed_target", lambda _root: None)
    monkeypatch.setattr(auto_update, "find_update", lambda _version: pytest.fail("attempt was replayed"))
    monkeypatch.setattr(sys, "prefix", sys.base_prefix)
    monkeypatch.setattr(sys, "argv", [
        "auto_update.py", "--apply", "--expect-version", release.version,
        "--expect-revision", release.revision,
    ])
    assert auto_update.main() == 1
    assert report_path.read_bytes() == previous_report


@pytest.mark.parametrize(("payload", "exit_code", "known"), [
    (None, 0, False), ("{bad", 0, False), ('{"success": false}', 0, False),
    ('{"success": false}', 2, False), ('{"success": false, "outcome_unknown": true}', 1, False),
    ('{"success": true}', 0, True), ('{"success": false}', 1, True),
])
def test_installer_only_releases_attempt_directory_after_consistent_completion(
    tmp_path, monkeypatch, payload, exit_code, known,
):
    target = tmp_path / "install"
    target.mkdir()
    wheel = b"synthetic wheel"
    release = auto_update.Release("v6.1.2", "a" * 40, "fixture.whl", hashlib.sha256(wheel).hexdigest())
    checkouts = []

    def checkout(_release, destination):
        checkouts.append(destination)
        tools = destination / "tools"
        tools.mkdir(parents=True)
        (tools / "update_install.py").write_text(
            "from pathlib import Path\nimport sys\n" +
            (f"Path(sys.argv[-1]).write_text({payload!r}, encoding='utf-8')\n" if payload is not None else "")
            + f"sys.exit({exit_code})\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(auto_update, "checkout_release", checkout)
    monkeypatch.setattr(auto_update, "read_url", lambda *_args: wheel)

    result = auto_update.apply_update(release, "6.1.1", target)

    assert result["success"] is (known and exit_code == 0)
    assert bool(result.get("outcome_unknown")) is not known
    assert checkouts[0].parent.exists() is not known
