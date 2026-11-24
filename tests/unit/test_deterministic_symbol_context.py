from local_ai_hub.deterministic_symbol_context import build_symbol_context
from local_ai_hub.deterministic import DeterministicEngine


class FakeCodeIndex:
    def __init__(self, symbol_responses=(), query_response=None, raises=False):
        self.symbol_responses = list(symbol_responses)
        self.query_response = query_response or {"symbols": []}
        self.raises = raises
        self.calls = []

    def find_symbol(self, root, query, **kwargs):
        self.calls.append(("find_symbol", root, query, kwargs))
        if self.raises:
            raise RuntimeError("index unavailable")
        if self.symbol_responses:
            return self.symbol_responses.pop(0)
        return {"symbols": []}

    def query(self, root, query, **kwargs):
        self.calls.append(("query", root, query, kwargs))
        return self.query_response


def test_build_symbol_context_renders_at_most_four_children():
    index = FakeCodeIndex([
        {"symbols": [{
            "kind": "function", "name": "run", "name_path": "Worker.run",
            "path": "src/worker.py", "line": 8, "signature": "def run()",
            "children": [{"name": f"child_{n}", "line": n} for n in range(5)],
        }]}
    ])

    rendered, truncated = build_symbol_context(index, "C:/repo", "run", [], 1000, 0)

    assert rendered.startswith("\nHIERARCHICAL SYMBOLS & SIGNATURES:")
    assert "- [function] Worker.run (src/worker.py:8) -> def run()" in rendered
    assert "child_3 (L3)" in rendered
    assert "child_4" not in rendered
    assert truncated is False


def test_build_symbol_context_tries_identifier_terms_before_query_fallback():
    index = FakeCodeIndex([
        {"symbols": []}, {"symbols": [{
            "kind": "class", "name": "Worker", "name_path": "Worker",
            "path": "src/worker.py", "line": 2, "children": [],
        }]},
    ])

    rendered, truncated = build_symbol_context(index, "C:/repo", "find Worker", ["find", "Worker"], 1000, 0)

    assert [call[2] for call in index.calls] == ["find Worker", "find"]
    assert "Worker (src/worker.py:2) -> class Worker" in rendered
    assert truncated is False


def test_build_symbol_context_uses_query_fallback_after_terms():
    index = FakeCodeIndex(query_response={"symbols": [{
        "kind": "variable", "name": "value", "name_path": "module.value",
        "path": "module.py", "line": 4, "children": [],
    }]})

    rendered, truncated = build_symbol_context(index, "C:/repo", "! ?", ["!", "?"], 1000, 0)

    assert index.calls[-1] == ("query", "C:/repo", "! ?", {"limit": 6})
    assert "value (module.py:4) -> variable value" in rendered
    assert truncated is False


def test_build_symbol_context_reuses_precomputed_symbols_without_index_calls():
    index = FakeCodeIndex()
    indexed = {"symbols": [{
        "kind": "function", "name": "run", "name_path": "Worker.run",
        "path": "worker.py", "line": 8, "signature": "def run()",
    }]}

    rendered, truncated = build_symbol_context(
        index, "C:/repo", "run", ["run"], 1000, 0, symbol_result=indexed,
    )

    assert "Worker.run (worker.py:8) -> def run()" in rendered
    assert truncated is False
    assert index.calls == []


def test_build_symbol_context_does_not_repeat_empty_precomputed_search():
    index = FakeCodeIndex()

    rendered, truncated = build_symbol_context(
        index, "C:/repo", "a long natural language query", ["long", "query"],
        1000, 0, symbol_result={"symbols": []},
    )

    assert rendered == ""
    assert truncated is False
    assert index.calls == []


def test_build_symbol_context_reports_budget_omission():
    index = FakeCodeIndex([{"symbols": [{
        "kind": "function", "name": "run", "name_path": "run",
        "path": "app.py", "line": 1, "children": [],
    }]}])

    rendered, truncated = build_symbol_context(index, "C:/repo", "run", [], 10, 0)

    assert rendered == ""
    assert truncated is True


def test_build_symbol_context_swallows_optional_index_errors():
    index = FakeCodeIndex(raises=True)

    rendered, truncated = build_symbol_context(index, "C:/repo", "run", [], 1000, 0)

    assert rendered == ""
    assert truncated is False


def _context_pack_engine(max_chars):
    engine = object.__new__(DeterministicEngine)
    engine.code_index = FakeCodeIndex([{"symbols": [{
        "kind": "function", "name": "run", "name_path": "Worker.run",
        "path": "worker.py", "line": 8, "signature": "def run()", "children": [],
    }]}])
    engine.evidence = None
    engine.query = lambda *_args, **_kwargs: {"evidence": []}
    engine.render_answer = lambda *_args, **_kwargs: "facts"
    engine._root = lambda root: root
    engine._terms = lambda _query: ["run"]
    return engine.context_pack("C:/repo", "run", max_chars=max_chars)


def test_context_pack_appends_symbol_context_when_it_fits():
    result = _context_pack_engine(1000)

    assert "DETERMINISTIC FACTS:\nfacts" in result["context"]
    assert "Worker.run (worker.py:8) -> def run()" in result["context"]
    assert result["truncated"] is False


def test_context_pack_passes_deterministic_symbols_to_builder():
    engine = object.__new__(DeterministicEngine)
    index = FakeCodeIndex()
    engine.code_index = index
    engine.evidence = None
    engine.query = lambda *_args, **_kwargs: {
        "evidence": [],
        "code_index": {"symbols": [{
            "kind": "class", "name": "Worker", "name_path": "Worker",
            "path": "worker.py", "line": 2, "signature": "class Worker",
        }]},
    }
    engine.render_answer = lambda *_args, **_kwargs: "facts"
    engine._root = lambda root: root
    engine._terms = lambda _query: ["Worker"]

    result = engine.context_pack("C:/repo", "Worker", max_chars=1000)

    assert "Worker (worker.py:2) -> class Worker" in result["context"]
    assert index.calls == []


def test_context_pack_marks_symbol_context_omitted_by_budget():
    result = _context_pack_engine(80)

    assert "HIERARCHICAL SYMBOLS & SIGNATURES" not in result["context"]
    assert result["truncated"] is True


def test_context_pack_keeps_optional_symbol_failure_nonfatal():
    engine = object.__new__(DeterministicEngine)
    engine.code_index = FakeCodeIndex()
    engine.evidence = None
    engine.query = lambda *_args, **_kwargs: {"evidence": []}
    engine.render_answer = lambda *_args, **_kwargs: "facts"
    engine._root = lambda root: root
    engine._terms = lambda _query: (_ for _ in ()).throw(RuntimeError("term parse failed"))

    result = engine.context_pack("C:/repo", "run", max_chars=1000)

    assert result["success"] is True
    assert result["context"] == "DETERMINISTIC FACTS:\nfacts"
    assert result["truncated"] is False
