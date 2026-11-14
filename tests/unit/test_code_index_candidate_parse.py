import json
from types import SimpleNamespace

from local_ai_hub.code_index_candidate_parse import parse_index_candidate


class FakeCodeIndex:
    def __init__(self):
        self._parse_diagnostic = SimpleNamespace(value={"status": "parsed", "parser": "python"})
        self.parse_calls = []

    def _tree_source_key(self, root, path):
        return f"{root}:{path}"

    def _parse_file_content(self, text, language, *, source_key):
        self.parse_calls.append((text, language, source_key))
        return ([{"name": "run"}], [{"name": "call"}], [{"src": "run", "dst": "call"}])


def test_parse_index_candidate_serializes_fresh_parse_output():
    index = FakeCodeIndex()
    candidate = ("src/mod.py", "digest", "python", ["def run():", "    pass"])

    result = parse_index_candidate(index, candidate, {}, "C:/repo", 12.5, "analyzer-v1")

    assert index.parse_calls == [("def run():\n    pass", "python", "C:/repo:src/mod.py")]
    assert result[:6] == (
        "src/mod.py", "digest", "python", [{"name": "run"}],
        [{"name": "call"}], [{"src": "run", "dst": "call"}],
    )
    assert result[6][:3] == ("digest", "analyzer-v1", "python")
    payload = json.loads(result[6][3])
    assert payload == {
        "symbols": [{"name": "run"}], "refs": [{"name": "call"}],
        "edges": [{"src": "run", "dst": "call"}],
        "parse_outcome": {"status": "parsed", "parser": "python"},
    }
    assert result[6][4] == 12.5


def test_parse_index_candidate_reuses_cached_parse_without_creating_row():
    index = FakeCodeIndex()
    cached = ([{"name": "cached"}], [], [], {"status": "cached"})

    result = parse_index_candidate(
        index, ("src/mod.py", "digest", "python", []),
        {("digest", "python"): cached}, "C:/repo", 12.5, "analyzer-v1",
    )

    assert index.parse_calls == []
    assert result[:6] == ("src/mod.py", "digest", "python", *cached[:3])
    assert result[6] is None
