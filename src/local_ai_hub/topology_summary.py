"""Pure Markdown summary construction for repository topology results."""

from __future__ import annotations

from typing import Any


def build_topology_summary_markdown(
    project_name: str,
    pattern: str,
    layers: dict[str, list[str]],
    graph_complete: bool,
    edges: list[dict[str, Any]],
) -> str:
    """Build the bounded human-readable summary without changing graph evidence."""
    lines = [
        f"# Architecture Topology: {project_name}",
        f"**Architecture hypothesis (heuristic)**: {pattern}",
        "", "## Heuristic path labels",
    ]
    for name, paths in layers.items():
        if paths:
            lines.append(f"- **{name.replace('_', ' ').title()}** ({len(paths)}): `{', '.join(paths[:4])}`")
    lines.extend(["", f"## Local Python import graph: {len(edges)} edges; complete={str(graph_complete).lower()}"])
    for edge in edges[:8]:
        lines.append(f"- `{edge['source']}:{edge['line']}` -> `{edge['target']}`")
    return "\n".join(lines)
