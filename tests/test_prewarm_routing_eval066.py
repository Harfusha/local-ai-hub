from types import SimpleNamespace

import pytest

from local_ai_hub.app import _prewarm_route_is_eligible


@pytest.mark.parametrize(
    "mode,ollama_enabled,hardware_enabled,fallback,expected",
    [
        ("off", True, False, False, True),
        ("off", False, False, False, False),
        ("on", True, False, False, False),
        ("auto", True, False, False, False),
        ("on", True, False, True, True),
        ("on", True, True, False, True),
    ],
)
def test_prewarm_distinguishes_disabled_backend(mode, ollama_enabled, hardware_enabled, fallback, expected):
    router = SimpleNamespace(supports_model=lambda model: True, hardware_enabled=lambda: hardware_enabled)
    runtime = SimpleNamespace(
        llama_cpp=router,
        config={"llama_cpp": {"mode": mode, "fallback_to_ollama": fallback},
                "ollama": {"enabled": ollama_enabled}},
    )
    assert _prewarm_route_is_eligible(runtime, "qwen2.5-coder:3b") is expected
