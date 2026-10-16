import pytest
from local_ai_hub.normalizer import (
    normalize_query,
    tokenize_query_terms,
    postprocess_patch,
    postprocess_model_output,
)


def test_tokenize_query_terms_invalid_types_and_overflow():
    # min_len or max_terms as invalid type or float inf must not raise TypeError / OverflowError
    terms = tokenize_query_terms("foo bar baz qux", min_len="bad", max_terms=float("inf"))
    assert len(terms) > 0

    terms2 = tokenize_query_terms("foo bar baz qux", min_len=None, max_terms=None)
    assert len(terms2) > 0

    terms3 = tokenize_query_terms("foo bar baz qux", min_len=True, max_terms=True)
    assert len(terms3) > 0


def test_tokenize_query_terms_custom_stop_words_types():
    # custom_stop_words not iterable or containing uppercase
    terms = tokenize_query_terms("foo bar baz", custom_stop_words=12345)
    assert "foo" in terms

    terms2 = tokenize_query_terms("foo bar baz", custom_stop_words={"FOO"})
    assert "foo" not in terms2


def test_normalize_query_null_bytes_and_types():
    # Null bytes must be stripped
    norm = normalize_query("hello\x00world\x00test")
    assert "\x00" not in norm
    assert "helloworld" in norm or "hello world" in norm

    # Boolean query
    assert normalize_query(True) == "" or "True" in normalize_query(True)


def test_postprocess_patch_boolean_and_types():
    # Booleans or non-string must return empty string
    assert postprocess_patch(True) == ""
    assert postprocess_patch(False) == ""
    assert postprocess_patch(None) == ""
