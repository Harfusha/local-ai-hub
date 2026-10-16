from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
import math
from pathlib import PurePosixPath
import re


_SOURCE_QUERY = re.compile(
    r"\b(?:source|runtime|implementation|implement|bug|fix|debug|diagnos\w*|"
    r"trace|function|symbol|definition|defined|behavior|code)\b",
    re.IGNORECASE,
)
_DOCUMENT_OBJECT = re.compile(
    r"\b(?:docs?|documentation|readme|guides?|manuals?|reference|prompts?|coverage|plans?|roadmap)\b",
    re.IGNORECASE,
)
_DOCUMENT_ACTION = re.compile(
    r"\b(?:update|edit|write|create|draft|rewrite|explain|summari[sz]e|describe|review|find|show|open|read|document)\b",
    re.IGNORECASE,
)
_DOCUMENT_PATH = re.compile(r"(?:^|\s)[\w./\\-]+\.(?:md|rst|adoc)(?:$|\s)", re.IGNORECASE)
_SOURCE_ACTION = re.compile(
    r"\b(?:implement\w*|fix|debug|diagnos\w*|trace|audit|refactor)\b", re.IGNORECASE,
)
_SOURCE_SUFFIXES = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go",
    ".rs", ".java", ".cs", ".cpp", ".cc", ".c", ".h", ".hpp", ".sql",
}
_CONFIG_SUFFIXES = {".toml", ".yaml", ".yml", ".json"}
_MAX_FUSION_PATHS_PER_GROUP = 4096


def _canonical_fusion_path(value: object) -> str | None:
    if not isinstance(value, str) or "\x00" in value:
        return None
    candidate = value.strip().replace("\\", "/")
    if not candidate:
        return None
    normalized = str(PurePosixPath(candidate))
    return None if normalized in {"", "."} else normalized


def is_source_context_query(query: str) -> bool:
    """Recognize source work while reserving clear documentation requests."""
    text = str(query or "")
    if not _SOURCE_QUERY.search(text):
        return False
    mentions_document = bool(_DOCUMENT_OBJECT.search(text) or _DOCUMENT_PATH.search(text))
    explicit_document_task = (
        mentions_document
        and bool(_DOCUMENT_ACTION.search(text))
        and not bool(_SOURCE_ACTION.search(text))
    )
    path_only_document_query = bool(_DOCUMENT_PATH.search(text)) and len(text.split()) <= 3
    return not (explicit_document_task or path_only_document_query)


def source_context_path_tier(path: str) -> int:
    """Rank current implementation files ahead of ordinary and historical docs."""
    normalized = str(path or "").replace("\\", "/").strip("/").casefold()
    parts = normalized.split("/") if normalized else []
    name = parts[-1] if parts else ""
    historical_doc = (
        name == "api_coverage.md"
        or any(part in {"plan", "plans", "historical", "archive", "archives"} for part in parts[:-1])
    )
    if historical_doc:
        return 2
    suffix = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    if suffix in _SOURCE_SUFFIXES:
        return 0
    runtime_config = (
        suffix in _CONFIG_SUFFIXES
        and (
            (parts and parts[0] in {"config", "configs"})
            or (len(parts) == 1 and name in {
                "config.toml", "config.yaml", "config.yml", "config.json",
                ".gitlab-ci.yml", "azure-pipelines.yml",
            })
            or parts[:2] == [".github", "workflows"]
            or parts[:2] == [".circleci", "config.yml"]
        )
    )
    if runtime_config:
        return 0
    return 1


def prioritize_source_context_paths(
    paths: Iterable[str], query: str, *, priority_paths: Iterable[str] = (),
) -> list[str]:
    """Stably prioritize source paths only for source-intent queries.

    Priority paths represent explicit files, pins, or force-includes and remain
    first even when they are documentation. No path is filtered from the result.
    """
    ordered = list(dict.fromkeys(str(path) for path in paths if str(path)))
    if not is_source_context_query(query):
        return ordered
    priorities = {str(path).replace("\\", "/").casefold() for path in priority_paths}
    ranks = {path: rank for rank, path in enumerate(ordered)}
    return sorted(
        ordered,
        key=lambda path: (
            0 if path.replace("\\", "/").casefold() in priorities else 1 + source_context_path_tier(path),
            ranks[path],
        ),
    )


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
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit must be a positive integer")
    if isinstance(max_per_path, bool) or not isinstance(max_per_path, int) or max_per_path <= 0:
        raise ValueError("max_per_path must be a positive integer")
    if not isinstance(groups, Mapping):
        return []

    backend_weights = {
        "deterministic": 1.25,
        "code_index": 1.20,
        "serena": 1.15,
        "preprocessor": 1.00,
        "rag": 0.90,
        "lexical": 0.80,
    }
    if isinstance(source_weights, Mapping):
        for source, configured in source_weights.items():
            source_name = source if isinstance(source, str) else None
            if source_name is None or source_name in {"deterministic", "code_index"}:
                continue
            if source_name not in backend_weights or isinstance(configured, bool):
                continue
            if isinstance(configured, int):
                if configured not in (0, 1):
                    continue
                weight_scale = float(configured)
            elif isinstance(configured, float):
                if not math.isfinite(configured) or not 0.0 <= configured <= 1.0:
                    continue
                weight_scale = configured
            else:
                continue
            backend_weights[source_name] *= weight_scale
    scores: dict[str, float] = defaultdict(float)
    sources: dict[str, set[str]] = defaultdict(set)
    # Keep cross-backend agreement discoverable even when a path ranks late
    # in one bounded backend response.
    per_backend_cap = _MAX_FUSION_PATHS_PER_GROUP
    # Backend results can arrive in different completion orders. Stable source
    # iteration prevents floating-point accumulation from reordering tied paths.
    for source, paths in sorted(
        ((name, values) for name, values in groups.items() if isinstance(name, str)),
        key=lambda item: item[0],
    ):
        if (
            not isinstance(paths, Iterable)
            or isinstance(paths, (str, bytes, bytearray, Mapping))
        ):
            continue
        weight = backend_weights.get(source, 0.75)
        seen: set[str] = set()
        try:
            iterator = iter(paths)
        except Exception:
            continue
        for rank in range(per_backend_cap):
            try:
                raw_path = next(iterator)
            except StopIteration:
                break
            except Exception:
                break
            path = _canonical_fusion_path(raw_path)
            if path is None or path in seen:
                continue
            seen.add(path)
            scores[path] += weight / (60.0 + rank + 1.0)
            sources[path].add(source)

    # Agreement bonus makes independent structural and lexical confirmation win
    # over a single generic text hit.
    for path, backend_names in sources.items():
        scores[path] += min(0.06, max(0, len(backend_names) - 1) * 0.018)

    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    result: list[tuple[str, float]] = []
    per_directory: dict[str, int] = defaultdict(int)
    for path, score in ranked:
        directory = path.rsplit("/", 1)[0] if "/" in path else ""
        if per_directory[directory] >= max_per_path * 8:
            continue
        per_directory[directory] += 1
        result.append((path, round(score, 6)))
        if len(result) >= limit:
            break
    return result
