"""Deferred bundle tests; reference accuracy needs installed, cached tokenizer data."""
import hashlib
import sys
from types import SimpleNamespace

import pytest

from local_ai_hub import code_tokens


def test_missing_tokenizer_cache_never_loads_package_or_downloads(tmp_path, monkeypatch):
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path))
    code_tokens.offline_encoding.cache_clear()
    monkeypatch.setitem(sys.modules, "tiktoken", SimpleNamespace(
        Encoding=lambda **_kwargs: pytest.fail("missing cache must not load tokenizer"),
        get_encoding=lambda *_args: pytest.fail("implicit downloads forbidden"),
    ))
    try:
        result = code_tokens.count_code_tokens("def CamelCase(snake_case): return 123456")
        assert result["tokens"] > 0
        assert result["exact"] is False
        assert result["accuracy_bound_verified"] is False
    finally:
        code_tokens.offline_encoding.cache_clear()


def test_corrupt_cache_is_preserved_and_never_triggers_download(tmp_path, monkeypatch):
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path))
    name = "cl100k_base"
    url = f"https://openaipublic.blob.core.windows.net/encodings/{name}.tiktoken"
    target = tmp_path / hashlib.sha1(url.encode(), usedforsecurity=False).hexdigest()
    target.write_bytes(b"corrupt cache")
    code_tokens.offline_encoding.cache_clear()
    try:
        assert code_tokens.offline_encoding(name) is None
        assert target.read_bytes() == b"corrupt cache"
    finally:
        code_tokens.offline_encoding.cache_clear()


@pytest.mark.parametrize("name", ["cl100k_base", "o200k_base"])
def test_offline_code_count_matches_real_reference_within_five_percent(name, monkeypatch):
    code_tokens.offline_encoding.cache_clear()
    tokenizer = code_tokens.offline_encoding(name)
    if tokenizer is None:
        pytest.skip("real cached tokenizer unavailable: accuracy target remains NOT VERIFIED")
    import tiktoken
    import requests

    monkeypatch.setattr(requests, "get", lambda *_args, **_kwargs: pytest.fail("reference must be offline"))
    reference = tiktoken.get_encoding(name)
    cases = [
        "def calculateTotal(snake_case: int) -> int:\n    return snake_case + 123456\n",
        "export async function fetchUser(userId: string) { return await fetch(`/users/${userId}`); }",
        "public sealed class DataStore<T> { public T? GetValue(string key) => default; }",
        "// žluťoučký kůň\nconst emoji = '🚀'; const CJK = '你好世界';\n",
        "literal = '<|endoftext|>'\n" + " " * 80 + "x = 1\r\n",
    ]
    for source in cases:
        expected = len(reference.encode(source, disallowed_special=()))
        actual = code_tokens.count_code_tokens(source, encoding=name)
        assert actual["exact"] is True
        assert abs(actual["tokens"] - expected) / max(1, expected) <= 0.05


def test_context_budget_uses_counter_and_rejects_out_of_root_files(tmp_path, monkeypatch):
    from local_ai_hub.deterministic import DeterministicEngine
    from local_ai_hub.repo_tools import RepositoryTools
    root = tmp_path / "repo"
    root.mkdir()
    (root / "code.py").write_text("def CamelCase(): return 123\n", encoding="utf-8")
    (tmp_path / "foreign.py").write_text("secret = 1", encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path / "state")}, "rag": {"extensions": [".py"]}}
    engine = DeterministicEngine(config, RepositoryTools(config))
    monkeypatch.setattr(code_tokens, "offline_encoding", lambda _name: None)
    try:
        result = engine.context_budget(str(root), ["code.py", "../foreign.py"])
        assert result["total_files"] == 1
        assert result["token_count_provenance"]["exact"] is False
        assert result["complete"] is False
        assert result["omitted_files"][0]["path"] == "../foreign.py"
    finally:
        observer = getattr(engine, "_cache_observer", None)
        if observer is not None:
            observer.close()
