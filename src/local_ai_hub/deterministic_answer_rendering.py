from __future__ import annotations

from typing import Any


def render_deterministic_answer(result: dict[str, Any], max_items: int = 16) -> str:
    """Render a terse deterministic answer without invoking any model."""
    intent = str(result.get("intent", "general"))
    lines: list[str] = []
    if intent == "dependencies":
        for x in result.get("dependencies", [])[:max_items]:
            version = f" {x.get('version')}" if x.get("version") else ""
            lines.append(f"- {x.get('name')}{version} [{x.get('scope','')}] — {x.get('source','')}")
    elif intent == "commands":
        for x in result.get("scripts", [])[:max_items]:
            lines.append(f"- {x.get('purpose','script')}: {x.get('name')} → {x.get('command')}")
    elif intent == "tests":
        for p in result.get("test_candidates", [])[:max_items]:
            lines.append(f"- {p}")
        for x in result.get("facts", [])[:max_items-len(lines)]:
            if x.get("path") not in {p[2:] if p.startswith('- ') else p for p in lines}:
                lines.append(f"- {x.get('path')}")
    elif intent in {"symbols", "callers", "references"}:
        graph = result.get("code_index", {}) if isinstance(result.get("code_index"), dict) else {}
        if intent == "callers":
            for x in graph.get("callers", [])[:max_items]:
                lines.append(f"- {x.get('caller')} calls {x.get('callee')} — {x.get('path')}:{x.get('line')}")
        for x in graph.get("symbols", [])[:max_items]:
            lines.append(f"- definition {x.get('name')} — {x.get('path')}:{x.get('line')}")
        group = graph.get("references", []) if intent != "symbols" else []
        for x in group[:max(0, max_items-len(lines))]:
            lines.append(f"- reference {x.get('name')} — {x.get('path')}:{x.get('line')}")
        for x in graph.get("edges", [])[:max(0, max_items-len(lines))]:
            lines.append(f"- {x.get('src')} {x.get('kind')} {x.get('dst')} — {x.get('path')}:{x.get('line')}")
    else:
        for x in result.get("facts", [])[:max_items]:
            label = x.get("name") or x.get("kind")
            value = x.get("value")
            suffix = f" = {value}" if value and value != label else ""
            lines.append(f"- {x.get('kind')}: {label}{suffix} — {x.get('path')}:{x.get('line')}")
        if not lines:
            graph = result.get("code_index", {}) if isinstance(result.get("code_index"), dict) else {}
            for x in graph.get("symbols", [])[:max_items]:
                lines.append(f"- definition {x.get('name')} — {x.get('path')}:{x.get('line')}")
    if not lines:
        return "No deterministic match found."
    return "\n".join(lines)
