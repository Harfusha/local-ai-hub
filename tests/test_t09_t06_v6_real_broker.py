from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import CompletionGateError, GoalContract, TaskStatus
from local_ai_hub.app import LocalAIApp
from local_ai_hub.verification_rules import complete_task_with_project_rules
from t09_project_config_test_fixture import install_t09_project_config_test_fixture


def test_v6_real_broker_project_receipt_and_generic_replay_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_t09_project_config_test_fixture(monkeypatch)
    monkeypatch.setenv("T06_PRIVATE", "private-project-command-value")
    repo = tmp_path / "repo"
    tests = repo / "tests"
    tests.mkdir(parents=True)
    (tests / "test_smoke.py").write_text(
        "def test_smoke():\n    assert 1 == 1\n", encoding="utf-8"
    )
    command_argv = json.dumps(sys.executable)
    (repo / ".local-ai.toml").write_text(
        f"[commands.test]\nargv = [{command_argv}, \"-m\", \"pytest\", \"-q\"]\n"
        "[commands.test.env]\nT06_PRIVATE = \"${T06_PRIVATE}\"\n"
        "[verification_rules]\ntest = [\"test\"]\n",
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
    try:
        task_id = "t09-v6-project-positive"
        app.agent_tasks.create(
            GoalContract(goal="verify project alias", acceptance_criteria=("test",)),
            ScopeContext(task_id=task_id, repository_id=str(repo)),
            task_id=task_id,
            actor="agent",
            repo_root=str(repo),
        )
        positive = app.commands.run_project_command(
            "test", str(repo), task_id=task_id, criterion="test",
            args=["tests/test_smoke.py"], force=True,
        )
        assert positive["success"] is True, positive
        assert positive.get("verification_receipt"), positive
        artifact = app.artifacts.get(
            positive["verification_evidence_id"], max_chars=50_000, tenant="agent"
        )
        assert artifact["success"] is True, artifact
        proof = json.loads(artifact["text"])
        assert proof["project_alias"] == "test"
        assert proof["caller_arguments_sha256"] == hashlib.sha256(
            json.dumps(["tests/test_smoke.py"], ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        expected_environment_sha256 = hashlib.sha256(
            json.dumps(
                {"T06_PRIVATE": "private-project-command-value"},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        assert proof["project_environment_sha256"] == expected_environment_sha256
        binding = {
            key: proof[key]
            for key in (
                "project_alias",
                "project_config_digest",
                "configured_command_sha256",
                "caller_arguments_sha256",
                "command_sha256",
                "project_environment_sha256",
            )
        }
        assert proof["project_execution_binding_sha256"] == hashlib.sha256(
            json.dumps(binding, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        help_result = app.commands.run_project_command(
            "test", str(repo), task_id=task_id, criterion="test",
            args=["--help"], force=True,
        )
        assert help_result["success"] is True, help_result
        assert "verification_receipt" not in help_result
        completed = complete_task_with_project_rules(
            app.agent_tasks,
            app.agent_verification,
            task_id,
            root=repo,
            state_dir=state_dir,
            current_revision=positive["repository_revision"],
        )
        assert completed.status == TaskStatus.COMPLETED

        rejected_task_id = "t09-v6-generic-replay"
        app.agent_tasks.create(
            GoalContract(goal="reject generic proof for configured project rule", acceptance_criteria=("test",)),
            ScopeContext(task_id=rejected_task_id, repository_id=str(repo)),
            task_id=rejected_task_id,
            actor="agent",
            repo_root=str(repo),
        )
        generic = app.commands.run(
            f'{command_argv} -m pytest -q tests/test_smoke.py',
            str(repo), tenant="agent", task_id=rejected_task_id, criterion="test", force=True,
        )
        assert generic["success"] is True, generic
        assert "verification_receipt" not in generic, generic
        with pytest.raises(CompletionGateError, match="verification incomplete"):
            complete_task_with_project_rules(
                app.agent_tasks,
                app.agent_verification,
                rejected_task_id,
                root=repo,
                state_dir=state_dir,
                current_revision=generic["repository_revision"],
            )
    finally:
        app.close()
