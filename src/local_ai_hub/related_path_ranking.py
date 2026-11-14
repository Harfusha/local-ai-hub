from __future__ import annotations

from collections import defaultdict
from typing import Any


def rank_related_paths(result: dict[str, Any], limit: int = 24) -> list[str]:
    """Rank paths from deterministic facts, graph references, and test candidates."""
    scores: dict[str, int] = defaultdict(int)
    for item in result.get("facts", []):
        path = str(item.get("path", ""))
        scores[path] += 4
    graph = result.get("code_index", {}) if isinstance(result.get("code_index"), dict) else {}
    for group, weight in ((graph.get("symbols", []), 4), (graph.get("references", []), 2), (graph.get("edges", []), 1)):
        for item in group or []:
            path = str(item.get("path", ""))
            scores[path] += weight
    for path in result.get("test_candidates", []):
        scores[str(path)] += 3
    return [path for path, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit] if path]
