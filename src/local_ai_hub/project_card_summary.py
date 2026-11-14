"""Pure deterministic project-card summary construction."""

from __future__ import annotations

from typing import Any


def build_project_card_summary(
    profile: dict[str, Any],
    repo_map: dict[str, Any],
    modules: list[dict[str, Any]],
    entry: dict[str, Any],
    config: dict[str, Any],
    security: dict[str, Any],
    concurrency: dict[str, Any],
    database: dict[str, Any],
    infrastructure: dict[str, Any],
    commands: dict[str, Any],
    syntax: dict[str, Any],
) -> dict[str, Any]:
    """Build project navigation fields from deterministic query results."""
    def coords(result: dict[str, Any], limit: int = 20) -> list[str]:
        out: list[str] = []
        for fact in result.get("facts", [])[:limit]:
            text = f"{fact.get('path')}:{fact.get('line')} {fact.get('kind')}={fact.get('name')}"
            if text not in out:
                out.append(text)
        return out

    entry_points = coords(entry, 24)
    testing = [f"{item.get('name')} -> {item.get('command')}" for item in commands.get("scripts", []) if str(item.get("purpose", "")).lower() in {"tests", "test", "lint", "checks", "check", "type-check", "build"}][:30]
    configuration = coords(config, 28)
    data_flow = coords(database, 24)
    security_items = coords(security, 24)
    concurrency_items = coords(concurrency, 24)
    infrastructure_items = coords(infrastructure, 32)
    hot_paths = [str(item.get("module")) for item in modules[:20] if item.get("module")]
    if not hot_paths:
        hot_paths = [str(item[0]) for item in repo_map.get("top_paths", [])[:20] if isinstance(item, (list, tuple)) and item]

    languages = profile.get("languages", [])
    if isinstance(languages, dict):
        languages_text = ", ".join(str(name) for name in list(languages)[:10])
    elif isinstance(languages, list):
        languages_text = ", ".join(str(item.get("language", item)) if isinstance(item, dict) else str(item) for item in languages[:10])
    else:
        languages_text = str(languages or "")
    architecture = f"Deterministic project map: {repo_map.get('files', 0)} indexed source files"
    if languages_text:
        architecture += f"; languages: {languages_text}"
    if hot_paths:
        architecture += "; top modules: " + ", ".join(hot_paths[:10])

    risks: list[str] = []
    if security_items: risks.append("security-sensitive code present")
    if concurrency_items: risks.append("concurrency-sensitive code present")
    if data_flow: risks.append("database/persistence code present")
    if infrastructure_items: risks.append("deployment/infrastructure declarations present")
    if syntax.get("facts"): risks.append(f"{len(syntax['facts'])} parser-detected syntax/config errors")

    evidence_count = sum(len(items) for items in (entry_points, configuration, data_flow, security_items, concurrency_items, infrastructure_items, testing))
    confidence = min(0.97, 0.78 + min(0.17, evidence_count * 0.003) + (0.02 if modules else 0.0))
    card = {
        "architecture": architecture,
        "entry_points": entry_points,
        "hot_paths": hot_paths[:20],
        "testing": testing,
        "configuration": configuration,
        "data_flow": data_flow,
        "security": security_items,
        "concurrency": concurrency_items,
        "infrastructure": infrastructure_items,
        "risks": risks,
    }
    return {"success": True, "deterministic": True, "confidence": round(confidence, 4), "card": card}
