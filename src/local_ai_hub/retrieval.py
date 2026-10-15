from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
import math
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
        weight = backend_weights.get(str(source), 0.75)
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
