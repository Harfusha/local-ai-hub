from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from local_ai_hub.commands import CommandBroker, CommandInvocation
from local_ai_hub.project_config import (
    PathHint,
    path_matches_pattern,
    resolve_project_context,
)
from local_ai_hub.services import LocalAIServices


class _Artifacts:
    def __init__(self) -> None:
        self.records: list[dict[str, str]] = []

    def put(self, content: str, *, kind: str, **_kwargs) -> str:
        self.records.append({"content": str(content), "kind": kind})
        return f"artifact-{len(self.records)}"


class _RepoState:
    def fingerprint(self, _cwd: str) -> dict[str, object]:
        return {"fingerprint": "t15-test-fixture", "stale": False, "degraded": False}


def _broker(state_dir: Path, artifacts: _Artifacts | None = None) -> CommandBroker:
    config = {
        "server": {"state_dir": str(state_dir)},
        "workspace_cache": {"fingerprint_ttl_seconds": 60.0},
        "commands": {
            "enabled": True,
            "allow_unknown": True,
            "coalesced_wait_seconds": 1,
            "max_output_chars": 4096,
            "inline_output_chars": 1024,
        },
        "features": {"diagnostic_artifacts": True, "local_diagnostic_dispatch": True},
    }
    return CommandBroker(config, artifacts or _Artifacts(), _RepoState())


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=10
    )


def test_project_alias_worktree_override_and_env_values_use_real_broker(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "primary"
    linked = tmp_path / "linked"
    primary.mkdir()
    _git(primary, "init", "-q")
    primary_argv = [sys.executable, "-B", "-c", "print('primary-alias')"]
    (primary / ".local-ai.toml").write_text(
        "[env]\n"
        'T15_LITERAL_VALUE = "base-literal"\n'
        'T15_REFERENCE_VALUE = "${T15_HOST_SECRET}"\n'
        '[commands.probe]\n'
        f"argv = {json.dumps(primary_argv)}\n",
        encoding="utf-8",
    )
    _git(primary, "add", ".local-ai.toml")
    _git(
        primary,
        "-c",
        "user.name=T15 Fixture",
        "-c",
        "user.email=t15@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    _git(primary, "worktree", "add", "--detach", str(linked), "HEAD")

    literal = "T15_LITERAL_VALUE_3d88"
    host_reference = "T15_HOST_REFERENCE_a51d"
    child = (
        "import os; print('worktree-ok' if "
        f"os.environ.get('T15_LITERAL_VALUE') == {literal!r} and "
        f"os.environ.get('T15_REFERENCE_VALUE') == {host_reference!r} "
        "else 'worktree-mismatch')"
    )
    override_argv = [sys.executable, "-B", "-c", child]
    (linked / ".local-ai.worktree.toml").write_text(
        "[env]\n"
        f"T15_LITERAL_VALUE = {json.dumps(literal)}\n"
        "[commands.probe]\n"
        f"argv = {json.dumps(override_argv)}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("T15_HOST_SECRET", host_reference)
    state_dir = tmp_path / "state"
    try:
        result = _broker(state_dir).run_project_command(
            "probe", str(linked),  force=True
        )

        serialized = json.dumps(result, default=str)
        state_bytes = b"".join(
            path.read_bytes() for path in state_dir.rglob("*") if path.is_file()
        )
        assert result["success"] is True
        assert result["stdout"] == "worktree-ok\n"
        assert literal not in serialized and host_reference not in serialized
        assert literal.encode() not in state_bytes and host_reference.encode() not in state_bytes
    finally:
        _git(primary, "worktree", "remove", "--force", str(linked))


def test_path_hint_does_not_narrow_uncertain_mapped_complete_matrix(
    tmp_path: Path,
) -> None:
    assert path_matches_pattern("src/{package}/changed.py", "src/**") is True
    assert path_matches_pattern("../outside.py", "src/**") is False
    assert path_matches_pattern("src/*.py", "src/**") is False

    matrix = [
        "tests/test_first.py",
        "tests/test_second.py",
        "tests/test_third.py",
        "tests/custom/test_mapped.py",
    ]
    (tmp_path / ".local-ai.toml").write_text(
        '[affected_tests_mapping]\n"src/**" = ["tests/custom/**"]\n', encoding="utf-8"
    )
    for relative in matrix:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def test_case(): pass\n", encoding="utf-8")

    state_dir = tmp_path / "state"
    context = resolve_project_context(tmp_path, state_dir)
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"server": {"state_dir": str(state_dir)}}
    services.code_index = None
    services.test_matrix = lambda _root: {"test_files": [{"path": path} for path in matrix]}

    class _Impact:
        def affected_tests(self, *_args):
            return {
                "success": True,
                "framework": "pytest",
                "changed_files": ["src/{package}/changed.py"],
                "test_files": [],
                "suggested_command": "",
                "confidence": 0.5,
                "workspace_cache": {
                    "fingerprint": "t15-revision",
                    "stale": False,
                    "degraded": False,
                },
            }

    if hasattr(services, "_repository_test_impact_service"):
        services._repository_test_impact_service = lambda: _Impact()
    else:
        services._repo_cache_state = lambda _root: {
            "fingerprint": "t15-revision",
            "stale": False,
            "degraded": False,
        }
        services.deterministic = SimpleNamespace(affected_tests=_Impact().affected_tests)
        services.deterministic_operation = lambda _op, _root, _params, compute: {
            **compute(),
            "workspace_cache": {"fingerprint": "t15-revision", "stale": False},
        }

    hint = PathHint(
        path="tests/test_second.py",
        purpose="affected_tests",
        scope="run_affected",
        evidence_id="t15-parity-fixture",
        provenance="verified_search",
        repository_revision="t15-revision",
        config_digest=context.config_digest,
    )
    result = services.affected_tests(
        str(tmp_path),
        changed_paths=["src/{package}/changed.py"],
        path_hints=[hint],
    )

    selected = result["test_files"]
    assert result["selection_uncertain"] is True
    assert result["selection_fallback"] == "complete_test_matrix"
    assert len(selected) == len(matrix)
    assert set(selected) == set(matrix)
    assert selected[0] == "tests/test_second.py"
    assert result["path_hint_usage"]["hint_used"] is True


def test_public_cancel_stops_streamed_command_and_clears_active_record(
    tmp_path: Path,
) -> None:
    broker = _broker(tmp_path / "state")
    ready = threading.Event()
    chunks: list[tuple[str, str]] = []
    result: dict[str, object] = {}
    errors: list[str] = []
    invocation = CommandInvocation(
        argv=[sys.executable, "-B", "-c", "import time; print('ready',flush=True); time.sleep(30)"],
        cwd=str(tmp_path),
    )

    def on_log(stream: str, text: str) -> None:
        chunks.append((stream, text))
        if "ready" in text:
            ready.set()

    def run_command() -> None:
        try:
            result.update(
                broker.run(
                    invocation,
                    str(tmp_path),

                    timeout=45,
                    force=True,
                    log_callback=on_log,
                )
            )
        except Exception as exc:  # pragma: no cover - bounded cleanup guard
            errors.append(type(exc).__name__)

    worker = threading.Thread(target=run_command, daemon=True)
    worker.start()
    deadline = time.monotonic() + 8
    active: list[dict[str, object]] = []
    while worker.is_alive() and time.monotonic() < deadline:
        active = broker.stats()["active"]
        if active and ready.wait(0.03):
            break
        time.sleep(0.02)

    active = broker.stats()["active"]
    cancel_result = (
        broker.cancel("", "", execution_id=str(active[0]["execution_id"]))
        if active
        else {"success": False}
    )
    worker.join(timeout=10)

    assert ready.is_set()
    assert chunks
    assert cancel_result["success"] is True
    assert not worker.is_alive()
    assert not errors
    assert result["cancelled"] is True
    assert broker.stats()["active_count"] == 0


def test_large_stdout_returns_bounded_inline_text_and_bounded_artifact(
    tmp_path: Path,
) -> None:
    artifacts = _Artifacts()
    broker = _broker(tmp_path / "state", artifacts)
    invocation = CommandInvocation(
        argv=[
            sys.executable,
            "-B",
            "-c",
            "import sys; sys.stdout.write('Q'*50000); sys.stdout.flush()",
        ],
        cwd=str(tmp_path),
    )

    result = broker.run(invocation, str(tmp_path),  force=True)

    command_artifact = next(record for record in artifacts.records if record["kind"] == "command")
    artifact = command_artifact["content"]
    stdout = artifact.split("STDOUT:\n", 1)[1].split("\n\nSTDERR:", 1)[0]
    assert result["success"] is True
    assert result["output_truncated"] is True
    assert result["artifact_id"]
    assert len(result["stdout"]) <= 512
    assert 0 < len(stdout) <= 4096
    assert stdout.count("Q") <= 4096


def test_mock_replay_reads_bounded_fixture_without_network(
    tmp_path: Path,
) -> None:
    broker = _broker(tmp_path / "state")
    paths = broker._cassette_paths("t15-replay-parity", None, create=True)
    assert isinstance(paths, tuple)
    _cassette_dir, cassette_file = paths
    cassette_file.write_text(
        json.dumps(
            {
                "url": "https://example.invalid/api",
                "status_code": 200,
                "headers": {"content-type": "application/json"},
                "body": '{"fixture":true}',
                "body_length": 16,
            }
        ),
        encoding="utf-8",
    )

    result = broker.replay_mock("t15-replay-parity")

    assert result["success"] is True
    assert result["status_code"] == 200
    assert result["body"] == '{"fixture":true}'
