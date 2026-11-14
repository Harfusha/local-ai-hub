from __future__ import annotations

from collections.abc import Iterable


_INTENT_NOISE: dict[str, frozenset[str]] = {
    "routes": frozenset({"api", "route", "routes", "endpoint", "endpoints", "controller"}),
    "tests": frozenset({"test", "tests", "spec", "specs", "phpunit", "pytest", "jest", "vitest"}),
    "config": frozenset({"config", "configuration", "environment", "settings", "setting", "env"}),
    "commands": frozenset({"command", "commands", "build", "lint", "test", "run", "validation"}),
    "dependencies": frozenset({"dependency", "dependencies", "package", "packages", "composer", "npm", "cargo", "nuget"}),
    "entrypoints": frozenset({"entrypoint", "entry", "point", "startup", "bootstrap", "main"}),
    "syntax": frozenset({"syntax", "parse", "error", "invalid", "json", "toml", "xml"}),
    "infrastructure": frozenset({
        "infrastructure", "docker", "container", "compose", "terraform", "kubernetes", "k8s", "helm",
        "deployment", "deploy", "ci", "pipeline", "job", "jobs", "workflow", "port", "ports",
        "healthcheck", "protobuf", "grpc",
    }),
}


def filter_intent_noise(intent: str, terms: Iterable[str]) -> list[str]:
    """Remove intent-label terms while preserving the content terms and their order."""
    ignored = _INTENT_NOISE.get(intent, frozenset())
    return [term for term in terms if term not in ignored]
