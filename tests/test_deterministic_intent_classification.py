import pytest

from local_ai_hub.deterministic import DeterministicEngine


@pytest.mark.parametrize(
    ("query", "intent", "confidence"),
    [
        ("Who calls validate?", "callers", 0.94),
        ("Find usages of validate", "references", 0.94),
        ("List route endpoints", "routes", 0.94),
        ("Show build command", "commands", 0.94),
        ("Run pytest", "tests", 0.94),
        ("List Cargo dependencies", "dependencies", 0.94),
        ("Explain Docker containers", "infrastructure", 0.94),
        ("Find invalid TOML", "syntax", 0.94),
        ("Show environment settings", "config", 0.94),
        ("Find the bootstrap entrypoint", "entrypoints", 0.94),
        ("Explain token permissions", "security", 0.94),
        ("Find async queue races", "concurrency", 0.94),
        ("Show database migrations", "database", 0.94),
        ("List TODO items", "todos", 0.94),
        ("Explain project architecture", "architecture", 0.94),
        ("Find method definitions", "symbols", 0.94),
        ("Refactor this parser", "implementation", 0.88),
        ("What does this module do?", "general", 0.55),
    ],
)
def test_classify_intent_preserves_rule_results(query: str, intent: str, confidence: float) -> None:
    assert DeterministicEngine.classify_intent(query) == {
        "intent": intent,
        "confidence": confidence,
    }


def test_classify_intent_preserves_rule_priority() -> None:
    assert DeterministicEngine.classify_intent("route test") == {
        "intent": "routes",
        "confidence": 0.94,
    }
