from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
import math


def default_backend_weights() -> dict[str, float]:
    """Return default backend weights for reciprocal-rank fusion."""
    return {
        "deterministic": 1.25,
        "code_index": 1.20,
        "serena": 1.15,
        "preprocessor": 1.00,
        "rag": 0.90,
        "lexical": 0.80,
    }


def reciprocal_rank(rank: int, k: float = 60.0) -> float:
    """Compute reciprocal rank score for rank and smoothing constant k."""
    r = rank if isinstance(rank, int) and not isinstance(rank, bool) and rank >= 0 else 0
    k_val = k if isinstance(k, (int, float)) and not isinstance(k, bool) and math.isfinite(k) and k >= 0 else 60.0
    return 1.0 / (k_val + r + 1.0)


def fuse_ranked_paths(
    groups: Mapping[str, Iterable[str]],
    *,
    limit: int = 24,
    max_per_path: int = 1,
    source_weights: Mapping[str, float] | None = None,
) -> list[tuple[str, float]]:
    """Fuse bounded path rankings from independent retrieval backends.

    Reciprocal-rank fusion rewards agreement without allowing one noisy backend
    to dominate. The returned ordering is deterministic for reproducible packs.
    """
    if not isinstance(groups, Mapping) or not groups:
        return []

    lim = limit if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0 else 24
    mpp = max_per_path if isinstance(max_per_path, int) and not isinstance(max_per_path, bool) and max_per_path > 0 else 1

    backend_weights = default_backend_weights()
    if isinstance(source_weights, Mapping):
        for source, configured in source_weights.items():
            if (
                str(source) not in {"deterministic", "code_index"}
                and str(source) in backend_weights
                and not isinstance(configured, bool)
                and isinstance(configured, (int, float))
                and math.isfinite(float(configured))
                and 0.0 <= float(configured) <= 1.0
            ):
                backend_weights[str(source)] *= float(configured)
    scores: dict[str, float] = defaultdict(float)
    sources: dict[str, set[str]] = defaultdict(set)
    # Backend results can arrive in different completion orders. Stable source
    # iteration prevents floating-point accumulation from reordering tied paths.
    for source, paths in sorted(groups.items(), key=lambda item: str(item[0])):
        if paths is None or not isinstance(paths, Iterable) or isinstance(paths, (str, bytes)):
            continue
        weight = backend_weights.get(str(source), 0.75)
        seen: set[str] = set()
        for rank, raw_path in enumerate(paths):
            path = str(raw_path or "").replace("\x00", "").replace("\\", "/").strip()
            if not path or path in seen:
                continue
            seen.add(path)
            scores[path] += weight * reciprocal_rank(rank, 60.0)
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
        if per_directory[directory] >= max(1, mpp * 8):
            continue
        per_directory[directory] += 1
        result.append((path, round(score, 6)))
        if len(result) >= lim:
            break
    return result
