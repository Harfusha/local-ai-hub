"""Coverage must remain truthful when paging strips the original query terms."""
from copy import deepcopy

import pytest

from local_ai_hub.mcp_server import _code_index_page_with_prefix


@pytest.mark.parametrize('query_count', [1, 3, 7])
@pytest.mark.parametrize('returned_count', [1, 3, 5])
def test_page_coverage_keeps_declared_denominator_without_terms(query_count, returned_count):
    terms = [f'term-{index}' for index in range(query_count)]
    symbols = [
        {'name': f'symbol-{index}', 'path': 'source.py', 'matched_terms': list(terms)}
        for index in range(returned_count + 1)
    ]
    raw = {'success': True, 'symbols': symbols, 'has_more': True, 'offset': 4,
           'total_matches': len(symbols), 'coverage': {'query_term_count': query_count}}
    before = deepcopy(raw)
    page = _code_index_page_with_prefix(raw, raw, symbols, returned_count)
    assert raw == before
    assert page['next_offset'] == 4 + returned_count
    assert page['returned_count'] == returned_count
    assert page['coverage']['query_term_count'] == query_count
    assert page['coverage']['matched_term_count'] == query_count
    assert page['coverage']['query_term_coverage'] == 1.0
    assert page['coverage']['coverage_available'] is True


@pytest.mark.parametrize('include_terms', [False, True])
def test_inconsistent_match_count_is_unknown_instead_of_clamped_full_coverage(include_terms):
    symbols = [{'name': 'target', 'path': 'source.py', 'matched_terms': ['one', 'two', 'three']}]
    raw = {'success': True, 'symbols': symbols, 'has_more': True, 'total_matches': 2,
           'coverage': {'query_term_count': 1}}
    if include_terms:
        raw['terms'] = ['one']
    before = deepcopy(raw)
    page = _code_index_page_with_prefix(raw, raw, symbols, 1)
    assert raw == before
    assert page['coverage']['query_term_count'] == 1
    assert page['coverage']['matched_term_count'] == 3
    assert page['coverage']['coverage_available'] is False
    assert page['coverage']['query_term_coverage'] == 0.0
