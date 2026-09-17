from __future__ import annotations

from pathlib import Path
from local_ai_hub.commands import CommandBroker
from local_ai_hub.projection import AgentProjector, _dense_text


class _Artifacts:
    def put(self, content: str, tenant: str, kind: str) -> str:
        return "art-123"


class _MockRepoState:
    def fingerprint(self, cwd: str) -> dict[str, object]:
        return {
            "success": True,
            "root": str(cwd),
            "kind": "git",
            "head": "deadbeef1234",
            "dirty": True,
            "changed_files": 35,
            "changed_paths": [f"file_{i}.py" for i in range(35)],
            "fingerprint": "mock_fingerprint_abc",
        }


def test_command_broker_output_projected_terse(tmp_path: Path):
    broker = CommandBroker(
        config={"server": {"state_dir": str(tmp_path / "state")}, "commands": {"enabled": True}, "features": {"diagnostic_artifacts": True}},
        artifacts=_Artifacts(),
        repo_state=_MockRepoState(),
    )
    raw_res = broker.run("python -c \"print('terse_test')\"", str(tmp_path), tenant="test_agent")

    assert raw_res["success"] is True
    assert raw_res["exit_code"] == 0
    assert "terse_test" in raw_res["stdout"]
    # Internal broker sets repository_revision
    assert raw_res.get("repository_revision") == "mock_fingerprint_abc"

    # Agent projection
    projector = AgentProjector({})
    projected = projector.project(raw_res, agent="generic", task_kind="command")

    # Relevant fields
    assert projected["success"] is True
    assert projected["exit_code"] == 0
    assert "terse_test" in projected["stdout"]
    assert "duration_ms" in projected

    # Irrelevant/bloat fields stripped
    assert "repo_state" not in projected
    assert "classification" not in projected
    assert "timed_out" not in projected
    assert "cancelled" not in projected
    assert "aborted_interactive" not in projected
    assert "output_truncated" not in projected
    assert "cache_hit" not in projected
    assert "coalesced" not in projected
    assert "summary" not in projected


def test_command_broker_output_with_extra_fields(tmp_path: Path):
    broker = CommandBroker(
        config={"server": {"state_dir": str(tmp_path / "state")}, "commands": {"enabled": True}},
        artifacts=_Artifacts(),
        repo_state=_MockRepoState(),
    )
    raw_res = broker.run("python -c \"print('extra_test')\"", str(tmp_path), tenant="test_agent")

    projector = AgentProjector({})
    projected = projector.project(
        raw_res,
        agent="generic",
        task_kind="command",
        extra_fields=["repo_state", "classification"],
    )

    assert "repo_state" in projected
    assert "classification" in projected
    assert len(projected["repo_state"]["changed_paths"]) <= 10


def test_command_broker_failure_terse(tmp_path: Path):
    broker = CommandBroker(
        config={"server": {"state_dir": str(tmp_path / "state")}, "commands": {"enabled": True}},
        artifacts=_Artifacts(),
        repo_state=_MockRepoState(),
    )
    raw_res = broker.run("python -c \"import sys; sys.stderr.write('boom\\n'); sys.exit(2)\"", str(tmp_path), tenant="test_agent")

    projector = AgentProjector({})
    projected = projector.project(raw_res, agent="generic", task_kind="command")

    assert projected["success"] is False
    assert projected["exit_code"] == 2
    assert "boom" in projected["stderr"]
    assert "duration_ms" in projected

    assert "repo_state" not in projected
    assert "classification" not in projected
    assert "timed_out" not in projected
    assert "cancelled" not in projected


def test_command_keeps_moderate_success_output_inline(tmp_path: Path):
    import sys
    broker = CommandBroker(
        config={"server": {"state_dir": str(tmp_path / "state")}, "commands": {"enabled": True}},
        artifacts=_Artifacts(),
        repo_state=_MockRepoState(),
    )
    # A moderate successful result stays inline; artifacts are for bounded failure diagnostics or long output.
    raw_res = broker.run(f'{sys.executable} -c "print(\'x\' * 600)"', str(tmp_path), tenant="test_agent")

    assert raw_res["success"] is True
    assert "artifact_id" not in raw_res
    assert len(raw_res["stdout"]) >= 600

    projector = AgentProjector({})
    projected = projector.project(raw_res, agent="generic", task_kind="command")

    assert projected["success"] is True
    assert "artifact_id" not in projected
    assert "x" * 100 in projected["stdout"]
    assert "[…truncated…]" in projected["stdout"]


def test_dense_text_without_artifact_uses_truncated_marker():
    long_text = "line\n" * 100
    res_with_artifact = _dense_text(long_text, 200, artifact_backed=True)
    assert "[…more available via artifact…]" in res_with_artifact
    assert "[…truncated…]" not in res_with_artifact

    res_without_artifact = _dense_text(long_text, 200, artifact_backed=False)
    assert "[…truncated…]" in res_without_artifact
    assert "[…more available via artifact…]" not in res_without_artifact
