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


def test_tree_sitter_absence_dispatches_to_lexical_chunker(monkeypatch) -> None:
    store = RAGStore.__new__(RAGStore)
    store.config = {"rag": {"chunk_chars": 40, "chunk_overlap_chars": 0}}
    monkeypatch.setattr(store, "_ast_chunks", lambda *_args: [])
    source = "package p\nfunc run() {\n" + "  work();\n" * 20 + "}\n"

    chunks = store._chunks(source, "file.go")

    assert "".join(chunks) == source
    assert any("func run() {" in chunk and "}" in chunk for chunk in chunks)
