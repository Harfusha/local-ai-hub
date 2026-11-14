from __future__ import annotations

from typing import Any


def classify_deterministic_intent(query: str) -> dict[str, Any]:
    low = query.lower()
    rules = [
        ("callers", ("caller", "callers", "called by", "who calls")),
        ("references", ("reference", "references", "usages", "used by")),
        ("routes", ("route", "routes", "endpoint", "api path", "controller")),
        ("commands", ("command", "commands", "build command", "test command", "lint command", "how to run", "build commands", "lint commands")),
        ("tests", ("test", "tests", "spec", "phpunit", "pytest", "jest", "vitest")),
        ("dependencies", ("dependency", "dependencies", "package", "packages", "composer", "npm", "cargo", "nuget")),
        ("infrastructure", ("docker", "container", "compose", "terraform", "kubernetes", "k8s", "helm", "deployment", "deploy", "github actions", "gitlab ci", "azure pipelines", "ci pipeline", "ci job", "ci jobs", "workflow", "port", "healthcheck", "protobuf", "grpc")),
        ("syntax", ("syntax", "parse error", "invalid json", "invalid toml", "invalid xml")),
        ("config", ("config", "configuration", "environment", " env ", "setting", "settings")),
        ("entrypoints", ("entrypoint", "entry point", "startup", "bootstrap", "main")),
        ("security", ("security", "auth", "authentication", "authorization", "permission", "jwt", "token")),
        ("concurrency", ("concurrency", "thread", "async", "queue", "lock", "race", "deadlock")),
        ("database", ("database", "sql", "query", "repository", "migration", "table")),
        ("todos", ("todo", "fixme", "hack", "xxx")),
        ("architecture", ("architecture", "structure", "modules", "components", "how project works")),
        ("symbols", ("symbol", "definition", "defined", "class", "function", "method")),
    ]
    for intent, needles in rules:
        if any(needle in low for needle in needles):
            return {"intent": intent, "confidence": 0.94}
    mutation = any(
        term in low
        for term in ("fix", "implement", "change", "modify", "refactor", "rewrite", "add", "remove", "patch", "update", "create", "delete")
    )
    if mutation:
        return {"intent": "implementation", "confidence": 0.88}
    return {"intent": "general", "confidence": 0.55}
