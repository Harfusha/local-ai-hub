import hashlib
import json
from types import SimpleNamespace

import pytest

from local_ai_hub.commands import CommandBroker


@pytest.mark.parametrize("exit_code", [0, False, 0.0, 1])
def test_execution_record_requires_integer_success_exit_code(tmp_path, exit_code):
    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}})
    command_id = "a" * 32
    record = {
        "schema": "command_execution_record.v2", "command_id": command_id,
        "exit_code": exit_code, "cached": False,
    }
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    record["record_sha256"] = hashlib.sha256(encoded).hexdigest()
    broker._persist_command_execution_record(command_id, record)

    actual = broker._get_server_command_execution_record(command_id)

    assert (actual is not None) is (type(exit_code) is int and exit_code == 0)


def test_receipt_requires_json_artifact_provider(tmp_path):
    writes = []
    artifacts = SimpleNamespace(put=lambda *args, **kwargs: writes.append((args, kwargs)))
    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}}, artifacts)
    broker.set_verification_store(SimpleNamespace())
    result = {"success": True, "exit_code": 0}

    broker._record_command_verification(
        result, task_id="task-a", criterion="tests", command="python -m pytest",
        command_id="b" * 32, command_digest="c" * 64,
        repository_revision="d" * 64, repository_root=str(tmp_path), duration_ms=1,
    )

    assert writes == []
    assert "verification_receipt" not in result
    assert result["verification_receipt_warning"]
