from __future__ import annotations

import sys
from local_ai_hub.commands import CommandBroker


class _Artifacts:
    def put(self, *_args, **_kwargs):
        return "artifact"


class _RepoState:
    def fingerprint(self, _cwd):
        return {"fingerprint": "stable"}


def _default_broker(tmp_path):
    return CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {"enabled": True},
        },
        _Artifacts(),
        _RepoState(),
    )


def test_command_is_not_blocked_by_default(tmp_path):
    broker = _default_broker(tmp_path)
    res = broker.run(f'{sys.executable} -c "print(123)"', str(tmp_path), "tenant")
    assert res.get("policy_blocked") is not True
    assert res.get("success") is True
    assert "123" in res.get("stdout", "")


def test_error_distillation_on_command_failure(tmp_path):
    broker = _default_broker(tmp_path)
    res = broker.run(f'{sys.executable} -c "raise ValueError(\'custom_failure_test\')"', str(tmp_path), "tenant")
    assert res.get("success") is False
    assert res.get("policy_blocked") is not True
    assert "error_distillation" in res
    assert "custom_failure_test" in res["error_distillation"]
    assert res["artifact_id"] == "artifact"


def test_model_error_distiller_only_runs_when_parser_has_no_diagnostic(tmp_path):
    broker = _default_broker(tmp_path)
    calls = []
    broker.set_error_distiller(lambda payload: calls.append(payload) or "local model summary")

    res = broker.run(f'{sys.executable} -c "print(\'unclassified failure\'); raise SystemExit(7)"', str(tmp_path), "tenant")

    assert res["success"] is False
    assert res["error_distillation"] == "local model summary"
    assert res["error_distillation_source"] == "local_model"
    assert len(calls) == 1


def test_model_error_distiller_skips_structured_parser_result(tmp_path):
    broker = _default_broker(tmp_path)
    broker.set_error_distiller(lambda _payload: (_ for _ in ()).throw(AssertionError("must not run")))

    res = broker.run(f'{sys.executable} -c "raise ValueError(\'parsed failure\')"', str(tmp_path), "tenant")

    assert res["success"] is False
    assert "parsed failure" in res["error_distillation"]
    assert res["error_distillation_source"] == "deterministic"


def test_failed_command_without_artifact_service_still_returns_diagnostics(tmp_path):
    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}, "commands": {"enabled": True}})

    res = broker.run(f'{sys.executable} -c "raise ValueError(\'no artifact service\')"', str(tmp_path), "tenant")

    assert res["success"] is False
    assert "no artifact service" in res["error_distillation"]
    assert "artifact_id" not in res
