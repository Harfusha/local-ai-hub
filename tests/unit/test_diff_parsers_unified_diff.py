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


def test_python_positional_only_arguments_keep_self_and_default_counts():
    result = diff_parsers.extract_py_diff_defs(["+def method(self, /, required, optional=3):"])
    assert result["method"]["pos_args"] == ["required", "optional"]
    assert result["method"]["required_count"] == 1


def test_python_inline_async_and_class_bodies_keep_original_signatures():
    async_line = '+async def fetch(self, /, item: str = "x:y"): return item'
    class_line = "+class InlineWidget: pass"
    result = diff_parsers.extract_py_diff_defs([async_line, class_line])
    assert result["fetch"]["pos_args"] == ["item"]
    assert result["fetch"]["required_count"] == 0
    assert result["fetch"]["sig"] == async_line[1:]
    assert result["InlineWidget"]["kind"] == "class"
    assert result["InlineWidget"]["sig"] == class_line[1:]


def test_python_missing_header_colon_handles_annotations_dict_strings_and_default_parens():
    line = '+def build(value: dict[str, int] = {"key:part": (1, 2)}, label: str = "left:right")'
    result = diff_parsers.extract_py_diff_defs([line])
    assert result["build"]["pos_args"] == ["value", "label"]
    assert result["build"]["required_count"] == 0
    assert result["build"]["sig"] == line[1:]


def test_headers_and_non_exported_typescript_do_not_expand_public_api():
    assert diff_parsers.extract_py_diff_defs(["+++def fake():", "---def removed():", "@@ def header():"]) == {}
    assert diff_parsers.extract_ts_diff_defs(["+function internal() {}", "-class Internal {}"] ) == {}
