import logging
from types import SimpleNamespace

import pytest

from local_ai_hub.commands import CommandBroker


@pytest.mark.parametrize("error,level", [(OSError, logging.WARNING), (ZeroDivisionError, logging.ERROR)])
def test_receipt_persistence_failures_are_visible_without_fabricated_receipts(tmp_path, caplog, error, level):
    class BrokenArtifacts:
        @property
        def put_json(self):
            raise error("private command payload must not enter logs")

    writes = []
    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}}, BrokenArtifacts())
    broker.set_verification_store(SimpleNamespace(record=lambda receipt: writes.append(receipt)))
    result = {"success": True, "exit_code": 0}

    broker._record_command_verification(
        result, task_id="task-current", criterion="tests", command="python -m pytest",
        command_id="a" * 32, command_digest="b" * 64,
        repository_revision="c" * 64, repository_root=str(tmp_path), duration_ms=1,
    )

    assert writes == []
    assert "verification_receipt" not in result
    assert result["verification_receipt_warning"]
    assert any(record.levelno == level and error.__name__ in record.message for record in caplog.records)
    assert "private command payload" not in caplog.text
