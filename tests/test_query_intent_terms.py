from __future__ import annotations

from local_ai_hub.query_intent_terms import filter_intent_noise


def test_filter_intent_noise_removes_only_intent_terms_and_preserves_order() -> None:
    terms = ["api", "auth", "routes", "auth"]

    assert filter_intent_noise("routes", terms) == ["auth", "auth"]


def test_filter_intent_noise_keeps_terms_for_unknown_intents() -> None:
    terms = ["custom", "custom", "path"]

    assert filter_intent_noise("custom_intent", terms) == terms
