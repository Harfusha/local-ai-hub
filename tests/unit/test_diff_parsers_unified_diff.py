"""Deferred selected hunks from gemini/wave-8-task-82; preserve public API scope."""
import pytest

from local_ai_hub import diff_parsers


@pytest.mark.parametrize("parser,line,name", [
    (diff_parsers.extract_py_diff_defs, "def public(value):", "public"),
    (diff_parsers.extract_ts_diff_defs, "export function public(value: string) {}", "public"),
    (diff_parsers.extract_cs_diff_defs, "public class Widget {}", "Widget"),
    (diff_parsers.extract_go_diff_defs, "func Public(value string) {}", "Public"),
    (diff_parsers.extract_rust_diff_defs, "pub fn public() {}", "public"),
])
@pytest.mark.parametrize("prefix", ["+", "-", " ", ""])
def test_public_definitions_accept_unified_content_prefix(parser, line, name, prefix):
    assert name in parser([prefix + line])


def test_python_multiline_signature_strips_each_diff_prefix():
    result = diff_parsers.extract_py_diff_defs(["+def public(", "+    value,", "+    optional=1", "+):"])
    assert result["public"]["pos_args"] == ["value", "optional"]
    assert result["public"]["required_count"] == 1


def test_headers_and_non_exported_typescript_do_not_expand_public_api():
    assert diff_parsers.extract_py_diff_defs(["+++def fake():", "---def removed():", "@@ def header():"]) == {}
    assert diff_parsers.extract_ts_diff_defs(["+function internal() {}", "-class Internal {}"] ) == {}
