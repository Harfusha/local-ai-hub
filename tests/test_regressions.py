from __future__ import annotations

from local_ai_hub.budget import fit_text
from local_ai_hub.commands import CommandBroker
from local_ai_hub.embeddings import EmbeddingModel
from local_ai_hub.token_router import LosslessTokenRouter


def _config(tmp_path):
    return {
        "server": {"state_dir": str(tmp_path)},
        "commands": {"allow_read": True},
        "models": {"embedding": "qwen3-embedding:0.6b", "embedding_backend": "auto"},
        "features": {"rag": True},
    }


def test_fit_text_honors_budget_for_multibyte_text():
    packed = fit_text("\u010d" * 10_000, 64, preserve_tail=False)

    assert packed.estimated_tokens <= 64


def test_command_broker_rejects_ripgrep_preprocessor(tmp_path):
    broker = CommandBroker(_config(tmp_path), artifacts=None, repo_state=None)

    result = broker.classify("rg --pre unsafe-command needle .")

    assert result["allowed"] is False


def test_embedding_auto_backend_requires_qualified_cache(tmp_path):
    class UnqualifiedCache:
        def __init__(self):
            self.get_calls = 0
            self.writes = []

        def get(self, _key):
            self.get_calls += 1
            return [99.0]

        def set(self, key, value):
            self.writes.append((key, value))

    model = EmbeddingModel(_config(tmp_path))
    cache = UnqualifiedCache()
    model.cache = cache
    model._encode_ollama = lambda texts: [[1.0, 2.0] for _ in texts]

    result = model.encode(["same text"])

    assert result["embeddings"] == [[1.0, 2.0]]
    assert cache.get_calls == 0
    assert cache.writes


def test_token_router_scans_recent_log_tail(tmp_path):
    router = LosslessTokenRouter({**_config(tmp_path), "lossless_router": {"max_scan_lines": 200}}, services=None)
    lines = ["normal line\n"] * 300 + ["FATAL: newest failure\n"]

    ranges = router._deterministic_ranges(lines, "fatal failure", "error_log")

    assert any(end >= len(lines) for _start, end, _score in ranges)
