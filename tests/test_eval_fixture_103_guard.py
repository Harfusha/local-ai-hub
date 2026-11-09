from __future__ import annotations

import importlib.util
from pathlib import Path

FIXTURE = Path(__file__).resolve().parents[1] / 'docs' / 'agent-evaluation' / 'fixtures' / 'case-103'
SCRIPT = FIXTURE / 'seed_invalid_receipt.py'


def _load_seed():
    spec = importlib.util.spec_from_file_location('case_103_seed', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_case_103_artifact_is_string_pass_with_wrong_task_and_no_broker_evidence():
    payload = _load_seed().build_fixture_payload('task_123456789abc')

    assert payload['passed'] == 'true'
    assert isinstance(payload['task_id'], str)
    assert payload['task_id'] != 'task_123456789abc'
    assert 'command_id' not in payload
    assert 'execution_record' not in payload


def test_case_103_seed_rejects_missing_target_task_identity():
    import pytest

    with pytest.raises(ValueError, match='target task ID'):
        _load_seed().build_fixture_payload('')


def test_case_103_seed_rejects_root_inside_git_checkout(tmp_path):
    import pytest

    checkout = tmp_path / 'checkout'
    sandbox = checkout / 'sandbox'
    sandbox.mkdir(parents=True)
    (checkout / '.git').mkdir()

    with pytest.raises(ValueError, match='outside Git'):
        _load_seed().seed_artifact(sandbox, 'task_123456789abc')
