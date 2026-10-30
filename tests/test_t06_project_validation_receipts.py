from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

project_config = pytest.importorskip("local_ai_hub.project_config")
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract
from local_ai_hub.app import LocalAIApp


def _write_project(tmp_path: Path) -> tuple[LocalAIApp, Path, str]:
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "empty_tests").mkdir()
    (repo / "lint_target.py").write_text("value = 1\n", encoding="utf-8")
    (repo / "tests" / "test_smoke.py").write_text("def test_smoke():\n    assert 1 == 1\n", encoding="utf-8")
    token = "private-project-command-value"
    exe = json.dumps(sys.executable)
    (repo / ".local-ai.toml").write_text(
        f"[commands.test]\nargv = [{exe}, \"-m\", \"pytest\", \"-q\"]\n"
        "[commands.test.env]\nT06_PRIVATE = \"${T06_PRIVATE}\"\n"
        f"[commands.lint]\nargv = [{exe}, \"-m\", \"pyflakes\", \"lint_target.py\"]\n"
        "[commands.lint.env]\nT06_PRIVATE = \"${T06_PRIVATE}\"\n"
        f"[commands.empty_test]\nargv = [{exe}, \"-m\", \"pytest\", \"-q\", \"empty_tests\"]\n"
        '[commands.badlint]\nargv = ["echo", "lint"]\n'
        '[verification_rules]\nrequired_commands = ["test", "lint"]\n',
        encoding="utf-8",
    )
    state_dir = tmp_path / "state"
    config_path = tmp_path / "hub.toml"
    config_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11498\nstate_dir = "{state_dir.as_posix()}"\n'
        "\n[agent_state]\nenabled = true\n",
        encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    task_id = "t06-project-validation"
    app.agent_tasks.create(
        GoalContract(goal="validate project", acceptance_criteria=("test", "lint")),
        ScopeContext(task_id=task_id, repository_id=str(repo)),
        task_id=task_id,
        actor="agent",
        repo_root=str(repo),
    )
    return app, repo, task_id


def _proof(app: LocalAIApp, result: dict) -> dict:
    artifact = app.artifacts.get(
        result["verification_evidence_id"], max_chars=50_000
    )
    assert artifact["success"] is True, artifact
    return json.loads(artifact["text"])


def test_structured_project_validation_binds_args_and_private_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("T06_PRIVATE", "private-project-command-value")
    app, repo, task_id = _write_project(tmp_path)
    try:
        context = project_config.resolve_project_context(repo, app.config["server"]["state_dir"])
        positive = app.commands.run_project_command(
            "test", str(repo), task_id=task_id, criterion="test",
            args=["tests/test_smoke.py"], force=True,
        )
        assert positive["success"] is True, positive
        assert positive.get("verification_receipt"), positive
        typed_receipt = positive["verification_receipt"]
        assert typed_receipt["owner"] == "agent"
        assert typed_receipt["mutation_generation"] == 0
        assert typed_receipt["evidence_type"] == "test"
        assert typed_receipt["repository_revision"] == positive["repository_revision"]
        proof = _proof(app, positive)
        assert proof["project_alias"] == "test"
        assert proof["project_config_digest"] == context.config_digest
        assert proof["command_classification"] == "test"
        assert len(proof["command_sha256"]) == 64
        assert all(character in "0123456789abcdef" for character in proof["command_sha256"])
        assert proof["project_environment_sha256"] == hashlib.sha256(
            json.dumps(
                {"T06_PRIVATE": "private-project-command-value"},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        assert proof["configured_command_sha256"]
        assert proof["caller_arguments_sha256"] == hashlib.sha256(
            json.dumps(["tests/test_smoke.py"], separators=(",", ":")).encode()
        ).hexdigest()
        assert "private-project-command-value" not in json.dumps(proof)
        binding = {
            key: proof[key]
            for key in (
                "project_alias", "project_config_digest", "configured_command_sha256",
                "caller_arguments_sha256", "command_sha256", "project_environment_sha256",
            )
        }
        assert proof["project_execution_binding_sha256"] == hashlib.sha256(
            json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        project_context = project_config.resolve_project_context(
            repo, app.config["server"]["state_dir"]
        )
        configured_result = app.agent_verification.completion(
            task_id,
            current_revision=positive["repository_revision"],
            current_mutation_generation=0,
            verification_rules=project_context.settings.verification_rules,
            configured_criteria=tuple(project_context.settings.commands),
        )
        assert "test" in configured_result.satisfied_criteria, configured_result
        assert "lint" in configured_result.unsatisfied_criteria, configured_result

        help_result = app.commands.run_project_command(
            "test", str(repo), task_id=task_id, criterion="test",
            args=["--help"], force=True,
        )
        assert help_result["success"] is True, help_result
        assert "verification_receipt" not in help_result

        version_result = app.commands.run_project_command(
            "test", str(repo), task_id=task_id, criterion="test",
            args=["-V"], force=True,
        )
        assert version_result["success"] is True, version_result
        assert "verification_receipt" not in version_result

        collect_only = app.commands.run_project_command(
            "test", str(repo), task_id=task_id, criterion="test",
            args=["-o", "addopts=--collect-only", "tests/test_smoke.py"], force=True,
        )
        assert collect_only["success"] is True, collect_only
        assert "test_smoke.py::test_smoke" in collect_only.get("stdout", "")
        assert "verification_receipt" not in collect_only

        verbose = app.commands.run_project_command(
            "test", str(repo), task_id=task_id, criterion="test",
            args=["-v", "tests/test_smoke.py"], force=True,
        )
        assert verbose["success"] is True, verbose
        assert verbose.get("verification_receipt"), verbose
        verbose_proof = _proof(app, verbose)
        assert verbose_proof["caller_arguments_sha256"] == hashlib.sha256(
            json.dumps(["-v", "tests/test_smoke.py"], separators=(",", ":")).encode()
        ).hexdigest()

        empty_suite = app.commands.run_project_command(
            "empty_test", str(repo), task_id=task_id, criterion="empty_test", force=True,
        )
        assert empty_suite["success"] is False, empty_suite
        assert empty_suite["exit_code"] == 5
        assert "verification_receipt" not in empty_suite

        generic_command = f'"{sys.executable}" -m pytest -q tests/test_smoke.py'
        generic = app.commands.run(
            generic_command,
            str(repo), task_id=task_id, criterion="generic_test", force=True,
        )
        assert generic["success"] is True, generic
        assert generic.get("verification_receipt"), generic
        generic_receipt = generic["verification_receipt"]
        assert generic_receipt["owner"] == "agent"
        assert generic_receipt["mutation_generation"] == 0
        assert generic_receipt["evidence_type"] == "test"
        generic_proof = _proof(app, generic)
        assert generic_proof["command_classification"] == "test"
        assert generic_proof["command_sha256"] == hashlib.sha256(
            generic_command.encode()
        ).hexdigest()
        assert "command" not in generic_proof
        assert "project_alias" not in generic_proof
        assert "project_execution_binding_sha256" not in generic_proof

        fake_test = app.commands.run(
            f'"{sys.executable}" -c "print(\'pytest\')"',
            str(repo), task_id=task_id, criterion="test", force=True,
        )
        assert fake_test["success"] is True, fake_test
        assert "verification_receipt" not in fake_test

        bad_lint = app.commands.run_project_command(
            "badlint", str(repo), task_id=task_id, criterion="badlint", force=True,
        )
        assert "verification_receipt" not in bad_lint

        lint = app.commands.run_project_command(
            "lint", str(repo), task_id=task_id, criterion="lint", force=True,
        )
        assert lint["success"] is True, lint
        lint_proof = _proof(app, lint)
        assert lint_proof["command_classification"] == "source_review"
        assert lint_proof["project_alias"] == "lint"
        completion = app.agent_verification.completion(
            task_id,
            current_revision=lint["repository_revision"],
            current_mutation_generation=0,
            verification_rules=project_context.settings.verification_rules,
            configured_criteria=tuple(project_context.settings.commands),
        )
        assert completion.complete is True, completion
    finally:
        app.close()


def test_generic_test_receipt_cannot_satisfy_configured_alias_rule(
    tmp_path: Path,
) -> None:
    app, repo, task_id = _write_project(tmp_path)
    try:
        config_path = repo / ".local-ai.toml"
        config_path.write_text(
            config_path.read_text(encoding="utf-8").replace(
                'required_commands = ["test", "lint"]', 'test = ["test"]'
            ),
            encoding="utf-8",
        )
        generic = app.commands.run(
            f'"{sys.executable}" -m pytest -q tests/test_smoke.py',
            str(repo), task_id=task_id, criterion="test", force=True,
        )
        assert generic["success"] is True, generic
        assert "verification_receipt" not in generic
    finally:
        app.close()
