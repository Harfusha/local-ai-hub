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
