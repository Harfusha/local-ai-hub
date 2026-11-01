from local_ai_hub.tiered_ollama import TieredOllamaRuntime


class _Policy:
    def tier_for(self, model):
        return "smart" if model == "smart-model" else "fast"


class _Runtime:
    def __init__(self, digest, capabilities):
        self.digest = digest
        self.capabilities = capabilities
        self.calls = []

    def model_digest(self, model):
        self.calls.append(("digest", model))
        return self.digest

    def request(self, endpoint, payload=None, timeout=None):
        self.calls.append((endpoint, payload, timeout))
        return {"capabilities": self.capabilities}


def test_metadata_uses_selected_tier_without_handoff():
    tiered = object.__new__(TieredOllamaRuntime)
    tiered.policy = _Policy()
    tiered.fast = _Runtime("f" * 64, [])
    tiered.smart = _Runtime("a" * 64, ["tools"])

    assert tiered.model_digest("smart-model") == "a" * 64
    assert tiered.request("/api/show", {"name": "smart-model"}, 1)["capabilities"] == ["tools"]
    assert tiered.fast.calls == []
    assert tiered.model_digest("fast-model") == "f" * 64
    assert tiered.request("/api/show", {"name": "fast-model"}, 1)["capabilities"] == []


def test_missing_digest_reader_fails_closed():
    tiered = object.__new__(TieredOllamaRuntime)
    tiered.policy = _Policy()
    tiered.smart = object()
    tiered.fast = object()
    assert tiered.model_digest("smart-model") is None
