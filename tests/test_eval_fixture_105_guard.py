from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


FIXTURE = Path(__file__).resolve().parents[1] / 'docs' / 'agent-evaluation' / 'fixtures' / 'case-105'
SCRIPT = FIXTURE / 'race_adapter.py'


def _load_adapter():
    spec = importlib.util.spec_from_file_location('case_105_race_adapter', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_race_rejects_stale_candidate_without_completing_task(tmp_path):
    root = tmp_path / 'sandbox'
    root.mkdir()
    adapter = _load_adapter()

    initialized = adapter.run_action(root, 'init')
    candidate = adapter.run_action(root, 'prepare_candidate')
    changed = adapter.run_action(root, 'advance_revision', expected_revision=1)
    rejected = adapter.run_action(root, 'attempt_complete')

    assert initialized['task']['status'] == 'planned'
    assert candidate['is_broker_receipt'] is False
    assert candidate['candidate']['revision'] == 1
    assert changed['task']['revision'] == 2
    assert changed['task']['mutation_generation'] == 2
    assert rejected == {
        'success': False,
        'completed': False,
        'conflict': True,
        'reason': 'stale_candidate',
        'task_status': 'planned',
        'current_revision': 2,
        'current_mutation_generation': 2,
        'is_broker_receipt': False,
    }
    assert adapter.run_action(root, 'read')['task']['status'] == 'planned'


def test_revision_race_refuses_synthetic_fresh_candidate_too(tmp_path):
    root = tmp_path / 'sandbox'
    root.mkdir()
    adapter = _load_adapter()
    adapter.run_action(root, 'init')
    adapter.run_action(root, 'prepare_candidate')

    result = adapter.run_action(root, 'attempt_complete')

    assert result['success'] is False
    assert result['completed'] is False
    assert result['reason'] == 'no_broker_receipt'
    assert adapter.run_action(root, 'read')['task']['status'] == 'planned'


def test_revision_race_uses_compare_and_swap_for_second_actor(tmp_path):
    root = tmp_path / 'sandbox'
    root.mkdir()
    adapter = _load_adapter()
    adapter.run_action(root, 'init')

    result = adapter.run_action(root, 'advance_revision', expected_revision=9)

    assert result['success'] is False
    assert result['conflict'] is True
    assert adapter.run_action(root, 'read')['task']['revision'] == 1


def test_revision_race_rejects_git_checkout_sandbox(tmp_path):
    root = tmp_path / 'checkout' / 'sandbox'
    root.mkdir(parents=True)
    (tmp_path / 'checkout' / '.git').mkdir()

    with pytest.raises(ValueError, match='outside Git'):
        _load_adapter().run_action(root, 'init')
