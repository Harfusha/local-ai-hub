"""Deferred structural AST classification cases; source is never executed."""
from __future__ import annotations

from local_ai_hub.ast_diff import ast_diff, MAX_SOURCE_BYTES


def test_rename_and_reorder_are_separate_from_body_modification():
    before = 'def first():\n    return 1\n\ndef second():\n    return 2\n'
    after = 'def second():\n    return 2\n\ndef renamed():\n    return 1\n'
    result = ast_diff(before, after)
    assert result['success'] is True
    assert result['summary']['renamed'] == 1
    assert result['summary']['reordered'] == 2
    assert result['logic_edits_detected'] is False
    assert result['behavior_equivalence_proven'] is False
    modified = ast_diff('def first():\n    return 1\n', 'def first():\n    return 3\n')
    assert modified['summary']['modified'] == 1
    assert modified['logic_edits_detected'] is True


def test_comments_and_spacing_do_not_create_structural_edits():
    result = ast_diff('value=1\n', '# explanation\nvalue = 1\n')
    assert result['structural_equal'] is True
    assert result['formatting_only'] is True
    assert result['changes'] == []


def test_insertion_does_not_mislabel_surviving_siblings_as_reordered():
    before = 'def first():\n    return 1\ndef second():\n    return 2\n'
    result = ast_diff(before, 'def added():\n    return 3\n' + before)
    assert result['summary'] == {'added': 1}


def test_ambiguous_identical_bodies_are_not_arbitrarily_renamed():
    before = 'def first():\n    return 1\ndef second():\n    return 1\n'
    after = 'def third():\n    return 1\ndef fourth():\n    return 1\n'
    result = ast_diff(before, after)
    assert result['ambiguous_rename_groups'] == 1
    assert result['summary'] == {'removed': 2, 'added': 2}


def test_change_tree_groups_nested_definition_changes():
    result = ast_diff('class Box:\n    def before(self):\n        return 1\n',
                      'class Box:\n    def after(self):\n        return 1\n')
    group = result['tree']['children'][0]
    assert group['scope'] == 'Box'
    assert group['children'][0]['change_types'] == ['renamed']
    assert result['logic_edits_detected'] is False


def test_module_statements_and_invalid_inputs_remain_visible():
    result = ast_diff('setting = 1\n', 'setting = 2\n')
    assert result['summary'] == {'module_modified': 1}
    assert result['logic_edits_detected'] is True
    invalid = ast_diff('value = 1\n', 'def broken(:\n')
    assert invalid['success'] is False
    assert invalid['side'] == 'after'
    oversized = ast_diff(' ' * (MAX_SOURCE_BYTES + 1), '')
    assert oversized['error_code'] == 'ast_diff_input_limit'
