import hashlib
import json
import subprocess
import sys

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
    monkeypatch.setattr(sys, "argv", ["auto_update.py", "--apply", "--dashboard",
                                    "--expect-version", "6.1.2", "--expect-revision", "a" * 40])
    assert auto_update.main() == 1
    result = json.loads((tmp_path / "auto-update-dashboard.json").read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert "reviewed release changed" in result["error"]
