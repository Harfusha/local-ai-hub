from __future__ import annotations

import importlib.util
import json
from pathlib import Path

FIXTURE = Path(__file__).resolve().parents[1] / 'docs' / 'agent-evaluation' / 'fixtures' / 'case-102'
SCRIPT = FIXTURE / 'fault_adapter.py'


def _load_adapter():
    spec = importlib.util.spec_from_file_location('case_102_fault_adapter', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unknown_mutation_persists_one_effect_and_reader_is_read_only(tmp_path):
    root = tmp_path / 'sandbox'
    (root / 'state').mkdir(parents=True)
    adapter = _load_adapter()

    result = adapter.run_action(root, 'mutate')
    snapshot_before = (root / 'state' / 'case102-counter.json').read_text(encoding='utf-8')
    observed = adapter.run_action(root, 'read')
    snapshot_after = (root / 'state' / 'case102-counter.json').read_text(encoding='utf-8')

    assert result['success'] is False
    assert result['outcome_unknown'] is True
    assert result['terminal'] is True
    assert result['retryable'] is False
    assert observed == {'success': True, 'mutation_count': 1}
    assert snapshot_after == snapshot_before


def test_unknown_mutation_adapter_detects_a_retry(tmp_path):
    root = tmp_path / 'sandbox'
    (root / 'state').mkdir(parents=True)
    adapter = _load_adapter()

    adapter.run_action(root, 'mutate')
    adapter.run_action(root, 'mutate')

    assert adapter.run_action(root, 'read')['mutation_count'] == 2


def test_case_102_adapter_rejects_roots_inside_git_checkouts(tmp_path):
    import pytest

    checkout = tmp_path / 'checkout'
    root = checkout / 'sandbox'
    (root / 'state').mkdir(parents=True)
    (checkout / '.git').mkdir()

    with pytest.raises(ValueError, match='outside Git'):
        _load_adapter().run_action(root, 'mutate')


def test_case_102_adapter_rejects_counter_symlink_escape(tmp_path):
    import pytest

    root = tmp_path / 'sandbox'
    (root / 'state').mkdir(parents=True)
    outside = tmp_path / 'outside.json'
    outside.write_text('{"mutation_count":0}\n', encoding='utf-8')
    counter = root / 'state' / 'case102-counter.json'
    try:
        counter.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip('symlink creation is unavailable')

    with pytest.raises(ValueError, match='must not be a symlink'):
        _load_adapter().run_action(root, 'read')
    assert outside.read_text(encoding='utf-8') == '{"mutation_count":0}\n'
