from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping


def fuse_ranked_paths(
    groups: Mapping[str, Iterable[str]],
    *,
    limit: int = 24,
    max_per_path: int = 1,
) -> list[tuple[str, float]]:
    """Fuse bounded path rankings from independent retrieval backends.

    Reciprocal-rank fusion rewards agreement without allowing one noisy backend
    to dominate. The returned ordering is deterministic for reproducible packs.
    """
    source_weights = {
        "deterministic": 1.25,
        "code_index": 1.20,
        "serena": 1.15,
        "preprocessor": 1.00,
        "rag": 0.90,
        "lexical": 0.80,
    }
    scores: dict[str, float] = defaultdict(float)
    sources: dict[str, set[str]] = defaultdict(set)
    # Backend results can arrive in different completion orders. Stable source
    # iteration prevents floating-point accumulation from reordering tied paths.
    for source, paths in sorted(groups.items(), key=lambda item: str(item[0])):
        weight = source_weights.get(str(source), 0.75)
        seen: set[str] = set()
        for rank, raw_path in enumerate(paths):
            path = str(raw_path or "").replace("\\", "/").strip()
            if not path or path in seen:
                continue
            seen.add(path)
            scores[path] += weight / (60.0 + rank + 1.0)
            sources[path].add(str(source))

    # Agreement bonus makes independent structural and lexical confirmation win
    # over a single generic text hit.
    for path, backend_names in sources.items():
        scores[path] += min(0.06, max(0, len(backend_names) - 1) * 0.018)

    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    result: list[tuple[str, float]] = []
    per_directory: dict[str, int] = defaultdict(int)
    for path, score in ranked:
        directory = path.rsplit("/", 1)[0] if "/" in path else ""
        if per_directory[directory] >= max(1, max_per_path * 8):
            continue
        per_directory[directory] += 1
        result.append((path, round(score, 6)))
        if len(result) >= max(1, limit):
            break
    return result
