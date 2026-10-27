import json
import subprocess
from types import SimpleNamespace

from local_ai_hub.repo_plan.host_hooks import ensure_codex_superpowers


def _package(tmp_path):
    package = tmp_path / "superpowers"
    (package / ".codex-plugin").mkdir(parents=True)
    (package / ".codex-plugin/plugin.json").write_text('{"name":"superpowers","version":"7.0.1"}')
    (package / "skills/using-superpowers").mkdir(parents=True)
    (package / "skills/using-superpowers/SKILL.md").write_text("instructions")
    return package


def _plugin(package, **overrides):
    entry = {"pluginId": "superpowers@openai-curated-remote", "name": "superpowers",
             "version": "7.0.1", "installed": True, "enabled": True,
             "source": {"source": "local", "path": str(package)}}
    entry.update(overrides)
    return entry


def _runner(monkeypatch, results):
    import local_ai_hub.process_utils as process_utils
    calls = []

    def run(argv, **kwargs):
        calls.append(argv[1:])
        value = results.pop(0)
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(returncode=0, stdout=json.dumps(value), stderr="")

    monkeypatch.setattr(process_utils, "run_hidden", run)
    return calls


def test_enabled_compatible_install_is_reused_without_mutation(tmp_path, monkeypatch):
    exe = tmp_path / "codex.exe"
    exe.touch()
    package = _package(tmp_path)
    calls = _runner(monkeypatch, [{"installed": [_plugin(package)]}])
    result = ensure_codex_superpowers(exe, repo_root=tmp_path)
    assert result["success"] and not result["changed"]
    assert calls == [["plugin", "list", "--json"]]


def test_remote_codex_plugin_checks_its_cache_bytes(tmp_path, monkeypatch):
    exe = tmp_path / "codex.exe"
    exe.touch()
    package = _package(tmp_path)
    cache = tmp_path / "codex-home/plugins/cache/openai-curated-remote/superpowers/7.0.1"
    cache.parent.mkdir(parents=True)
    package.rename(cache)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    calls = _runner(monkeypatch, [{"installed": [_plugin(cache, source={"source": "remote", "id": "example"})]}])
    assert ensure_codex_superpowers(exe, repo_root=tmp_path)["success"]
    assert len(calls) == 1


def test_missing_install_requires_exact_candidate_and_checks_installed_bytes(tmp_path, monkeypatch):
    exe = tmp_path / "codex.exe"
    exe.touch()
    package = _package(tmp_path)
    candidate = _plugin(package, installed=False, enabled=False)
    calls = _runner(monkeypatch, [{"installed": []}, {"installed": [], "available": [candidate]}, {},
                                 {"installed": [_plugin(package)]}])
    result = ensure_codex_superpowers(exe, repo_root=tmp_path)
    assert result["success"] and result["changed"]
    assert calls[2] == ["plugin", "add", "superpowers@openai-curated-remote", "--json"]
    assert len(calls) == 4


def test_existing_incompatible_plugin_is_not_replaced(tmp_path, monkeypatch):
    exe = tmp_path / "codex.exe"
    exe.touch()
    calls = _runner(monkeypatch, [{"installed": [_plugin(tmp_path, version="6.0.0")]}])
    result = ensure_codex_superpowers(exe, repo_root=tmp_path)
    assert not result["success"] and not result["changed"]
    assert len(calls) == 1


def test_disabled_existing_plugin_is_not_overwritten(tmp_path, monkeypatch):
    exe = tmp_path / "codex.exe"
    exe.touch()
    package = _package(tmp_path)
    calls = _runner(monkeypatch, [{"installed": [_plugin(package, enabled=False)]}])
    result = ensure_codex_superpowers(exe, repo_root=tmp_path)
    assert not result["success"] and not result["changed"] and len(calls) == 1


def test_different_marketplace_version_is_not_installed(tmp_path, monkeypatch):
    exe = tmp_path / "codex.exe"
    exe.touch()
    candidate = _plugin(tmp_path, installed=False, enabled=False, version="7.0.2")
    calls = _runner(monkeypatch, [{"installed": []}, {"installed": [], "available": [candidate]}])
    result = ensure_codex_superpowers(exe, repo_root=tmp_path)
    assert not result["success"] and not result["changed"] and len(calls) == 2


def test_install_timeout_does_not_retry_or_claim_result(tmp_path, monkeypatch):
    exe = tmp_path / "codex.exe"
    exe.touch()
    candidate = _plugin(tmp_path, installed=False, enabled=False)
    calls = _runner(monkeypatch, [{"installed": []}, {"installed": [], "available": [candidate]},
                                 subprocess.TimeoutExpired("codex", 60)])
    result = ensure_codex_superpowers(exe, repo_root=tmp_path)
    assert not result["success"] and result["outcome_unknown"]
    assert result["changed"] is None and len(calls) == 3


def test_marketplace_version_change_after_install_is_not_accepted(tmp_path, monkeypatch):
    exe = tmp_path / "codex.exe"
    exe.touch()
    candidate = _plugin(tmp_path, installed=False, enabled=False)
    calls = _runner(monkeypatch, [{"installed": []}, {"installed": [], "available": [candidate]}, {},
                                 {"installed": [_plugin(tmp_path, version="7.0.2")]}])
    result = ensure_codex_superpowers(exe, repo_root=tmp_path)
    assert not result["success"] and result["changed"] is None
    assert result["partial_install_review_required"] and len(calls) == 4
