from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from local_ai_hub import project_config
from local_ai_hub.cache import stable_hash
from local_ai_hub.commands import CommandBroker, CommandInvocation
from local_ai_hub.project_config import CommandDefinition
from local_ai_hub.repo_state import RepoStateTracker


class _Artifacts:
    def put(self, *_args, **_kwargs):
        return "artifact"


def _broker(state_root: Path) -> CommandBroker:
    config = {
        "server": {"state_dir": str(state_root / "state")},
        "workspace_cache": {"fingerprint_ttl_seconds": 60.0},
        "commands": {
            "enabled": True,
            "allow_unknown": True,
            "coalesced_wait_seconds": 1,
        },
    }
    return CommandBroker(config, _Artifacts(), RepoStateTracker(config))


def test_ordinary_command_cache_key_omits_empty_project_context(tmp_path: Path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    broker.config["commands"]["environment_keys"] = []
    monkeypatch.setattr(
        broker.repo_state, "fingerprint", lambda _cwd: {"fingerprint": "stable"}
    )
    monkeypatch.setattr(broker, "_tool_identity", lambda *_args: "tool")
    command = "python -B -c pass"
    cwd = str(tmp_path)
    classification = {"class": "read_only"}

    key, _ = broker._key(command, cwd, classification)

    assert key == stable_hash(
        {
            "command": command.strip(),
            "cwd": str(Path(cwd).resolve()),
            "class": "read_only",
            "repo": "stable",
            "env": {},
            "python": sys.version_info[:3],
            "tool": "tool",
            "timeout_seconds": 60,
            "policy": {
                "blocking": True,
                "allow_read": True,
                "allow_validation": True,
                "allow_build": True,
                "allow_mutating": False,
                "allow_unknown": True,
                "extra_allowed_tools": [],
            },
        }
    )
    tokens = broker._tokens(command)
    assert broker._attempt_key(command, cwd, timeout=60) == stable_hash(
        {
            "command": " ".join(tokens) if tokens else command.strip(),
            "cwd": str(Path(cwd).resolve()),
            "tool": "tool",
            "timeout_seconds": 60,
            "policy": {
                "blocking": True,
                "allow_read": True,
                "allow_validation": True,
                "allow_build": True,
                "allow_mutating": False,
                "allow_unknown": True,
                "extra_allowed_tools": [],
            },
        }
    )



def _write_project_command(root: Path, *, argv: tuple[str, ...] | None = None) -> None:
    script = (
        "import os,sys; "
        "print('env-ok' if os.environ.get('T15_CHILD_TOKEN') == 'host-secret' "
        "and os.environ.get('T15_PROJECT_TOKEN') == 'host-secret' "
        "and os.environ.get('T15_PROJECT_MODE') == 'test' else 'env-missing'); "
        "print(sys.argv[1] if len(sys.argv) > 1 else 'no-arg')"
    )
    configured_argv = json.dumps(list(argv or (sys.executable, "-c", script)))
    (root / ".local-ai.toml").write_text(
        "[env]\n"
        'T15_PROJECT_MODE = "test"\n'
        'T15_PROJECT_TOKEN = "${T15_HOST_TOKEN}"\n'
        "[commands.check]\n"
        f"argv = {configured_argv}\n"
        "[commands.check.env]\n"
        'T15_CHILD_TOKEN = "${T15_HOST_TOKEN}"\n',
        encoding="utf-8",
    )


def test_resolve_project_command_uses_explicit_typed_alias_without_execution(
    tmp_path: Path, monkeypatch
) -> None:
    _write_project_command(tmp_path)
    monkeypatch.setenv("T15_HOST_TOKEN", "host-secret")
    broker = _broker(tmp_path)
    executed = False

    def forbidden_execute(*_args, **_kwargs):
        nonlocal executed
        executed = True
        raise AssertionError("resolving project config must not execute a command")

    monkeypatch.setattr(broker, "_execute", forbidden_execute)
    resolved = broker._resolve_project_command(
        "check", str(tmp_path), args=["safe;argument"]
    )

    assert isinstance(resolved.command, CommandInvocation)
    assert resolved.command.argv == [
        sys.executable,
        "-c",
        "import os,sys; print('env-ok' if os.environ.get('T15_CHILD_TOKEN') == 'host-secret' and os.environ.get('T15_PROJECT_TOKEN') == 'host-secret' and os.environ.get('T15_PROJECT_MODE') == 'test' else 'env-missing'); print(sys.argv[1] if len(sys.argv) > 1 else 'no-arg')",
        "safe;argument",
    ]
    assert resolved.environment == {
        "T15_CHILD_TOKEN": "host-secret",
        "T15_PROJECT_TOKEN": "host-secret",
        "T15_PROJECT_MODE": "test",
    }
    assert resolved.alias == "check"
    assert executed is False


def test_run_project_command_executes_exact_argv_with_safe_env_reference(
    tmp_path: Path, monkeypatch
) -> None:
    _write_project_command(tmp_path)
    monkeypatch.setenv("T15_HOST_TOKEN", "host-secret")
    broker = _broker(tmp_path)

    result = broker.run_project_command(
        "check", str(tmp_path), args=["safe;argument"], force=True
    )

    assert result["success"] is True
    assert result["stdout"] == "env-ok\nsafe;argument\n"
    assert result["exit_code"] == 0


def test_project_command_environment_values_change_cache_context(
    tmp_path: Path, monkeypatch
) -> None:
    _write_project_command(tmp_path)
    broker = _broker(tmp_path)
    monkeypatch.setenv("T15_HOST_TOKEN", "first-secret")
    first = broker._resolve_project_command("check", str(tmp_path))
    monkeypatch.setenv("T15_HOST_TOKEN", "second-secret")
    second = broker._resolve_project_command("check", str(tmp_path))

    assert second.environment["T15_CHILD_TOKEN"] == "second-secret"
    assert second.environment["T15_PROJECT_TOKEN"] == "second-secret"
    assert first.cache_context != second.cache_context
    assert first.cache_context == stable_hash(
        {
            "alias": "check",
            "config_digest": first.config_digest,
            "environment": {
                "T15_CHILD_TOKEN": "first-secret",
                "T15_PROJECT_TOKEN": "first-secret",
                "T15_PROJECT_MODE": "test",
            },
        }
    )


def test_project_environment_invalidates_suppression_and_success_cache(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    script = "import os; print(os.environ['T15_CHILD_TOKEN'])"
    (project_root / ".local-ai.toml").write_text(
        "[commands.check]\n"
        f"argv = {json.dumps([sys.executable, '-B', '-c', script])}\n"
        "[commands.check.env]\n"
        'T15_CHILD_TOKEN = "${T15_HOST_TOKEN}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("T15_HOST_TOKEN", "first")
    broker = _broker(tmp_path)
    broker.policy_blocking = True
    classify_calls = 0

    def classify(_command: str) -> dict[str, object]:
        nonlocal classify_calls
        classify_calls += 1
        blocked = classify_calls <= 2
        return {
            "class": "unknown",
            "cacheable": not blocked,
            "allowed": not blocked,
            "reason": "test policy",
        }

    monkeypatch.setattr(broker, "classify", classify)

    blocked = broker.run_project_command("check", str(project_root))
    suppressed = broker.run_project_command("check", str(project_root))
    assert blocked["policy_blocked"] is True
    # Authorization is re-evaluated before cache lookup, so a blocked request
    # cannot become a historical suppression-cache hit.
    assert suppressed["policy_blocked"] is True
    assert suppressed.get("suppression_cache_hit") is not True

    monkeypatch.setenv("T15_HOST_TOKEN", "second")
    fresh = broker.run_project_command("check", str(project_root))
    warm = broker.run_project_command("check", str(project_root))
    assert fresh["success"] is True
    assert fresh["stdout"] == "second\n"
    assert fresh.get("suppression_cache_hit") is not True
    assert warm["cache_hit"] is True

    monkeypatch.setenv("T15_HOST_TOKEN", "third")
    changed = broker.run_project_command("check", str(project_root))
    assert changed["success"] is True
    assert changed["stdout"] == "third\n"
    assert changed.get("cache_hit") is not True
    assert classify_calls == 5


def test_unknown_project_command_alias_fails_before_execution(
    tmp_path: Path, monkeypatch
) -> None:
    _write_project_command(tmp_path)
    broker = _broker(tmp_path)
    executed = False

    def forbidden_execute(*_args, **_kwargs):
        nonlocal executed
        executed = True
        raise AssertionError("unknown alias must not execute")

    monkeypatch.setattr(broker, "_execute", forbidden_execute)
    result = broker.run_project_command("missing", str(tmp_path))

    assert result["success"] is False
    assert result["preflight"] is True
    assert result["terminal"] is True
    assert executed is False


@pytest.mark.parametrize("environment_key", ["PATH", "GIT_CONFIG_COUNT", "DYLD_INSERT_LIBRARIES"])
def test_project_command_rejects_unsafe_environment_override_before_execution(
    tmp_path: Path, monkeypatch, environment_key: str
) -> None:
    argv = [sys.executable, "-c", "print('must-not-run')"]
    (tmp_path / ".local-ai.toml").write_text(
        "[commands.check]\n"
        f"argv = {json.dumps(argv)}\n"
        "[commands.check.env]\n"
        f'{environment_key} = "${{T15_HOST_VALUE}}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("T15_HOST_VALUE", "host-value")
    broker = _broker(tmp_path)
    executed = False

    def forbidden_execute(*_args, **_kwargs):
        nonlocal executed
        executed = True
        raise AssertionError("unsafe environment must not execute")

    monkeypatch.setattr(broker, "_execute", forbidden_execute)
    result = broker.run_project_command("check", str(tmp_path))

    assert result["success"] is False
    assert result["project_command_error"] == "invalid_command_environment"
    assert executed is False


def test_string_project_command_is_resolved_exactly_without_runner_guessing(
    tmp_path: Path,
) -> None:
    (tmp_path / ".local-ai.toml").write_text(
        '[commands]\ncheck = "python -m pytest -q"\n', encoding="utf-8"
    )
    broker = _broker(tmp_path)

    resolved = broker._resolve_project_command("check", str(tmp_path))

    assert resolved.command == "python -m pytest -q"
    assert resolved.alias == "check"


def test_project_command_delegates_rollback_scope_to_existing_run(
    tmp_path: Path, monkeypatch
) -> None:
    _write_project_command(tmp_path)
    monkeypatch.setenv("T15_HOST_TOKEN", "host-secret")
    broker = _broker(tmp_path)
    captured: dict = {}

    def capture_run(command, cwd, **kwargs):
        captured.update(command=command, cwd=cwd, kwargs=kwargs)
        return {"success": True}

    monkeypatch.setattr(broker, "run", capture_run)
    result = broker.run_project_command(
        "check",
        str(tmp_path),
        task_id="task-15",
        criterion="command config",
        rollback_on_failure=True,
        rollback_paths=["output.txt"],
    )

    assert result["success"] is True
    assert captured["kwargs"]["rollback_on_failure"] is True
    assert captured["kwargs"]["rollback_paths"] == ["output.txt"]
    assert captured["kwargs"]["task_id"] == "task-15"
    assert captured["kwargs"]["criterion"] == "command config"


def test_project_command_still_obeys_broker_policy(tmp_path: Path, monkeypatch) -> None:
    _write_project_command(tmp_path)
    monkeypatch.setenv("T15_HOST_TOKEN", "host-secret")
    broker = _broker(tmp_path)
    executed = False

    def forbidden_execute(*_args, **_kwargs):
        nonlocal executed
        executed = True
        raise AssertionError("policy-blocked command must not execute")

    monkeypatch.setattr(
        broker,
        "classify",
        lambda _command: {
            "class": "dangerous",
            "cacheable": False,
            "allowed": False,
            "reason": "test policy",
        },
    )
    monkeypatch.setattr(broker, "_execute", forbidden_execute)
    result = broker.run_project_command("check", str(tmp_path))

    assert result["success"] is False
    assert result["policy_blocked"] is True
    assert executed is False


def test_project_command_config_cache_uses_file_signature_invalidation(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config = project / ".local-ai.toml"

    def write_config(message: str) -> None:
        argv = [sys.executable, "-B", "-c", f"print({message!r})"]
        config.write_text(
            "[commands.probe]\nargv = " + json.dumps(argv) + "\n",
            encoding="utf-8",
        )

    write_config("first")
    calls = 0
    original = project_config._git_common_dir

    def counted_common_dir(root: Path):
        nonlocal calls
        if root == project:
            calls += 1
        return original(root)

    monkeypatch.setattr(project_config, "_git_common_dir", counted_common_dir)
    broker = _broker(tmp_path)

    first = broker._resolve_project_command("probe", str(project))
    same = broker._resolve_project_command("probe", str(project))
    assert first.command.argv[-1] == same.command.argv[-1]
    assert calls == 1

    write_config("updated")
    updated = broker._resolve_project_command("probe", str(project))

    assert updated.command.argv[-1] != first.command.argv[-1]
    assert calls == 2


def test_project_command_config_cache_invalidates_negative_lookup(
    tmp_path: Path,
) -> None:
    broker = _broker(tmp_path)
    with pytest.raises(project_config.ProjectConfigError, match="command_alias_not_found"):
        broker._resolve_project_command("probe", str(tmp_path))

    config = tmp_path / ".local-ai.toml"
    config.write_text(
        "[commands.probe]\nargv = "
        + json.dumps([sys.executable, "-B", "-c", "print('ready')"])
        + "\n",
        encoding="utf-8",
    )
    resolved = broker._resolve_project_command("probe", str(tmp_path))

    assert resolved.command.argv[-1] == "print('ready')"


def test_project_command_config_cache_invalidates_on_git_revision(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config = project / ".local-ai.toml"
    argv = [sys.executable, "-B", "-c", "print('stable')"]
    config.write_text(
        "[commands.probe]\nargv = " + json.dumps(argv) + "\n",
        encoding="utf-8",
    )
    (project / "revision.txt").write_text("one\n", encoding="utf-8")

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=project, check=True, capture_output=True, text=True
        )
        return result.stdout.strip()

    git("init", "-q")
    git("config", "user.name", "T15 Fixture")
    git("config", "user.email", "t15@example.invalid")
    git("add", ".local-ai.toml", "revision.txt")
    git("commit", "-qm", "revision one")
    assert git("symbolic-ref", "HEAD").startswith("refs/heads/")
    calls = 0
    original = project_config._git_common_dir

    def counted_common_dir(root: Path):
        nonlocal calls
        if root == project:
            calls += 1
        return original(root)

    monkeypatch.setattr(project_config, "_git_common_dir", counted_common_dir)
    broker = _broker(tmp_path)
    broker._resolve_project_command("probe", str(project))
    broker._resolve_project_command("probe", str(project))
    assert calls == 1

    (project / "revision.txt").write_text("two\n", encoding="utf-8")
    git("add", "revision.txt")
    git("commit", "-qm", "revision two")
    # Other projects can resolve configuration while this broker is exercised.
    project_config._git_common_dir(tmp_path)
    broker._resolve_project_command("probe", str(project))

    assert calls == 2


def test_linked_worktree_config_cache_invalidates_all_config_layers(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "primary"
    linked = tmp_path / "linked"
    primary.mkdir()

    def git(cwd: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
        )
        return result.stdout.strip()

    def write_primary(value: str) -> None:
        (primary / ".local-ai.toml").write_text(
            '[commands.probe]\nargv = ["python", "-c", "print(\'stable\')"]\n'
            f'[env]\nT15_PRIMARY = "{value}"\n',
            encoding="utf-8",
        )

    git(primary, "init", "--quiet")
    git(primary, "config", "user.email", "t15@example.invalid")
    git(primary, "config", "user.name", "T15 Fixture")
    write_primary("primary-one")
    (primary / "revision.txt").write_text("one\n", encoding="utf-8")
    git(primary, "add", "revision.txt")
    git(primary, "commit", "--quiet", "-m", "fixture")
    git(primary, "worktree", "add", "--quiet", "-b", "t15-linked", str(linked), "HEAD")
    head = git(linked, "symbolic-ref", "HEAD")
    assert head == "refs/heads/t15-linked"

    common = Path(git(linked, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = (linked / common).resolve()
    machine_config = common / "info" / "local-ai.toml"
    machine_config.parent.mkdir(parents=True, exist_ok=True)
    machine_config.write_text('[env]\nT15_MACHINE = "machine-one"\n', encoding="utf-8")
    overlay = linked / ".local-ai.worktree.toml"
    overlay.write_text('[env]\nT15_WORKTREE = "worktree-one"\n', encoding="utf-8")

    broker = _broker(tmp_path)
    first = broker._resolve_project_command("probe", str(linked))
    assert first.environment == {
        "T15_PRIMARY": "primary-one",
        "T15_MACHINE": "machine-one",
        "T15_WORKTREE": "worktree-one",
    }

    write_primary("primary-two")
    assert project_config.resolve_project_config(linked).settings.env["T15_PRIMARY"] == "primary-two"
    inherited = broker._resolve_project_command("probe", str(linked))
    assert inherited.environment["T15_PRIMARY"] == "primary-two"
    assert inherited.config_digest != first.config_digest

    machine_config.write_text('[env]\nT15_MACHINE = "machine-two"\n', encoding="utf-8")
    machine = broker._resolve_project_command("probe", str(linked))
    assert machine.environment["T15_MACHINE"] == "machine-two"
    assert machine.config_digest != inherited.config_digest

    overlay.write_text('[env]\nT15_WORKTREE = "worktree-two"\n', encoding="utf-8")
    worktree = broker._resolve_project_command("probe", str(linked))
    assert worktree.environment["T15_WORKTREE"] == "worktree-two"
    assert worktree.config_digest != machine.config_digest
