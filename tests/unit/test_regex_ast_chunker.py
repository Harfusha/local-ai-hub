from __future__ import annotations

import pytest

from local_ai_hub.rag import RAGStore, _regex_ast_chunks


@pytest.mark.parametrize(
    ("language", "source"),
    [
        (
            "typescript",
            "import { value } from './module';\n"
            "export function first(input: string) {\n"
            "  const template = `literal } ${input}`;\n"
            "  // comment with }\n  if (input) { nested(); }\n  return template;\n}\n"
            "const second = () => { return /[{}]/.test('x'); };\nexport const tail = 1;\n",
        ),
        (
            "c_sharp",
            "using System;\npublic class Worker {\n"
            "  public string Run(string input) {\n"
            "    var normal = \"}\"; var verbatim = @\"}}\";\n"
            "    var raw = \"\"\"} {\"\"\"; /* brace { comment } */\n"
            "    if (input != null) { return normal; }\n"
            "    return verbatim;\n  }\n}\n// trailing code\n",
        ),
        (
            "go",
            "package sample\nfunc Run(input string) string {\n"
            "  raw := `}`; /* brace } in comment */ if input != \"\" { return raw }; return input\n}\n",
        ),
        (
            "rust",
            "use std::fmt;\nfn run<'a>(input: &'a str) -> String {\n"
            "  let raw = r###\"} {\"###; // } comment\n"
            "  if !input.is_empty() { return raw.into(); }\n  raw.into()\n}\n",
        ),
    ],
)
def test_lexical_chunks_keep_balanced_blocks_and_reconstruct_source(language, source) -> None:
    chunks = _regex_ast_chunks(source, language, size=32)

    assert chunks
    assert "".join(chunks) == source
    unit_marker = {
        "typescript": "export function first(input: string)",
        "c_sharp": "public class Worker {",
        "go": "func Run(input string) string {",
        "rust": "fn run<'a>(input: &'a str) -> String {",
    }[language]
    unit = next(chunk for chunk in chunks if unit_marker in chunk)
    assert unit.rstrip().endswith("}")


def test_oversized_function_body_remains_one_complete_chunk() -> None:
    body = "x" * 500
    source = f"fn large() {{\n{body}\n}}\nfn next() {{ ok(); }}"

    chunks = _regex_ast_chunks(source, "rust", size=48)

    assert "".join(chunks) == source
    assert any("fn large() {" in chunk and body in chunk and "fn next()" not in chunk for chunk in chunks)
    assert any("fn next() { ok(); }" in chunk for chunk in chunks)


def test_adjacent_small_functions_pack_without_splitting_units() -> None:
    source = "".join(f"fn f{index}() {{ work_{index}(); }}\n" for index in range(20))

    chunks = _regex_ast_chunks(source, "rust", size=100)

    assert "".join(chunks) == source
    assert len(chunks) < 20
    for chunk in chunks:
        assert chunk.count("fn f") == chunk.count("}")
        assert "{ work_" in chunk


@pytest.mark.parametrize("language", ["typescript", "go"])
def test_long_braceless_source_is_returned_once(language) -> None:
    source = "const value = 1;\n" * 20 if language == "typescript" else "package p\n" + "var value = 1\n" * 20

    chunks = _regex_ast_chunks(source, language, size=16)

    assert chunks == [source]


def test_unprovable_braceless_tail_is_not_split() -> None:
    tail = "const compute = (value: number) => value + 1;\n" * 8
    source = "function ready() { return true; }\n" + tail

    chunks = _regex_ast_chunks(source, "typescript", size=24)

    assert "".join(chunks) == source
    assert chunks[-1] == tail


def test_rust_lifetime_after_nonzero_prefix_does_not_shift_brace_scan() -> None:
    source = "// prefix\nfn borrow<'a>(value: &'a str) -> &'a str { value }\n"

    chunks = _regex_ast_chunks(source, "rust", size=12)

    assert "".join(chunks) == source
    assert any("fn borrow<'a>" in chunk and "{ value }" in chunk for chunk in chunks)


def test_typescript_structural_return_type_keeps_function_together() -> None:
    source = "function shape(): { x: number } { return { x: 1 }; }\n"

    chunks = _regex_ast_chunks(source, "typescript", size=12)

    assert chunks == [source]


def test_long_typescript_structural_return_header_uses_bounded_fallback() -> None:
    parameters = ", ".join(f"arg{index}: number" for index in range(80))
    source = f"function shape({parameters}): {{ x: number }} {{ return {{ x: 1 }}; }}\n"

    chunks = _regex_ast_chunks(source, "typescript", size=48)

    assert chunks == [source]


def test_ambiguous_csharp_interpolation_keeps_source_together() -> None:
    source = 'class C { string M() { return $"{Call(\"}\")}"; } }\n'

    chunks = _regex_ast_chunks(source, "c_sharp", size=12)

    assert chunks == [source]


@pytest.mark.parametrize("prefix", ['$@"', '@$"', '$"""'])
def test_csharp_interpolated_prefixes_are_detected_before_string_scanning(prefix) -> None:
    source = f'class C {{ string M() {{ return {prefix}{{Call("}}")}}"; }} }}\n'

    chunks = _regex_ast_chunks(source, "c_sharp", size=12)

    assert chunks == [source]


def test_nested_typescript_template_inside_interpolation_keeps_source_whole() -> None:
    source = "const render = (name: string) => `outer ${`inner } ${name}`} done`;\n"

    chunks = _regex_ast_chunks(source, "typescript", size=12)

    assert chunks == [source]


def test_tree_sitter_absence_dispatches_to_lexical_chunker(monkeypatch) -> None:
    store = RAGStore.__new__(RAGStore)
    store.config = {"rag": {"chunk_chars": 40, "chunk_overlap_chars": 0}}
    monkeypatch.setattr(store, "_ast_chunks", lambda *_args: [])
    source = "package p\nfunc run() {\n" + "  work();\n" * 20 + "}\n"

    chunks = store._chunks(source, "file.go")

    assert "".join(chunks) == source
    assert any("func run() {" in chunk and "}" in chunk for chunk in chunks)
