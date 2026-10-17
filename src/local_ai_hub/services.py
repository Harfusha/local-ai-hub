from __future__ import annotations

from .json_utils import dumps as json_dumps

import copy
import fnmatch
import hashlib
import itertools
import json
import logging
import math
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import time
import threading
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import asdict
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

from . import __version__
from .artifacts import ArtifactStore
from .budget import chars_for_tokens, estimate_tokens, fit_text
from .cache import MemoryLRUCache, SQLiteCache, TieredCache, SingleFlightCache, SingleFlightGroup, stable_hash
from .conversations import ConversationStore
from .features import rollout_feature_enabled
from .normalizer import normalize_query, postprocess_model_output
from .semantic_cache import SemanticGenerationCache
from .model_policy import ModelExecutionPolicy
from .ollama_subagents import OllamaSubagentCatalog
from .process_utils import canonical_root
from .repo_tools import RepositoryTools
from .search_pagination import MAX_PAGE_SIZE, MAX_PAGE_WINDOW, pagination_bounds_error
from .router import ModelRouter, review_diff_complexity
from .sqlite_support import connect_sqlite
from .adoption_metrics import AdoptionMetricsStore
from .state_paths import configured_state_dir
from .speculative_lint import normalize_changed_paths
from .lint_daemon import RuffDaemonPool, OwnedBiomeDaemonPool
from .async_jobs import current_job_should_stop
from .telemetry import TelemetryStore
from .trace_context import observer
from .treesitter_parser import parse_treesitter

logger = logging.getLogger(__name__)
from .agent_consistency import AdaptiveContextPack, ConsistencyRequest, GuardWarning
from .agent_context import ContextCompiler, ContextRequest
from .agent_events import AgentStateStore
from .semantic_quality import assess_semantic_result
from .prompt_contracts import build_prompt
from .retrieval import (
    fuse_ranked_paths,
    is_source_context_query,
    prioritize_source_context_paths,
    source_context_path_tier,
)


# Keep optional context workers bounded across concurrent requests. Each backend
# gets its own single-worker lane for Serena
# or RAG, and timed-out work cannot cause a new thread per incoming request.
_CONTEXT_BACKEND_POOLS = {
    name: ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"context-{name}")
    for name in ("serena", "rag")
}


def _safe_int(val: Any, default: int, min_val: int | None = None, max_val: int | None = None) -> int:
    if isinstance(val, bool) or val is None:
        return default
    try:
        if isinstance(val, float) and not math.isfinite(val):
            return default
        res = int(val)
    except (ValueError, TypeError, OverflowError):
        return default
    if min_val is not None and res < min_val:
        return min_val
    if max_val is not None and res > max_val:
        return max_val
    return res


def _safe_float(val: Any, default: float, min_val: float | None = None, max_val: float | None = None) -> float:
    if isinstance(val, bool) or val is None:
        return default
    try:
        res = float(val)
        if not math.isfinite(res):
            return default
    except (ValueError, TypeError, OverflowError):
        return default
    if min_val is not None and res < min_val:
        return min_val
    if max_val is not None and res > max_val:
        return max_val
    return res


def is_retryable_local_backend_error(value: Any) -> bool:
    """Recognize transport/runtime failures that must keep async work retryable."""
    if getattr(value, "retryable", None) is True:
        return True
    text = str(value or "").lower()
    return any(marker in text for marker in (
        "winerror 10054", "winerror 10061", "connection reset", "connection refused",
        "connection aborted", "broken pipe", "temporarily unavailable", "ollama unavailable",
        "timed out", "timeout", "eof", "queue limit reached", "queue full", "resource pressure",
    ))


def normalize_generation_cache_prompt(prompt: str) -> str:
    """Normalize only transport-level line endings for exact prompt reuse."""
    return str(prompt).replace("\r\n", "\n").replace("\r", "\n")


def cache_decision_reason(cache_layer: str, *, semantic_query: str) -> str:
    layer = str(cache_layer or "").strip().lower()
    query = str(semantic_query or "").strip()
    if layer == "semantic":
        return "semantic_reuse"
    if layer == "single-flight":
        return "singleflight_reuse"
    if layer == "stale-on-error":
        return "stale_on_error"
    if layer == "ollama" and query:
        return "semantic_not_reused"
    if layer == "ollama":
        return "new_exact_key"
    return "exact_reuse"


def enclosing_symbol_at_line(source: str, path: str, line: int) -> dict[str, Any] | None:
    """Return the smallest existing Tree-sitter symbol spanning one source line."""
    if not isinstance(source, str) or not isinstance(path, str) or "\x00" in path:
        return None
    line_num = _safe_int(line, default=-1)
    if line_num <= 0:
        return None
    try:
        language = Path(path).suffix.lower().lstrip(".")
    except Exception:
        return None
    parsed = parse_treesitter(source, language)
    if not parsed:
        return None
    symbols, _, _ = parsed
    matches = [
        symbol for symbol in symbols
        if int(symbol.get("line", 0) or 0) <= line_num <= int(symbol.get("end_line", 0) or 0)
    ]
    if not matches:
        return None
    symbol = min(matches, key=lambda item: int(item.get("end_line", 0) or 0) - int(item.get("line", 0) or 0))
    return {
        key: symbol[key] for key in ("name", "kind", "line", "end_line", "name_path")
        if key in symbol
    }


_REVIEW_DIFF_MIN_CHUNK_TOKENS = 256
_REVIEW_DIFF_CONTEXT_FRACTION = 0.5
_MAX_REVIEW_DIFF_CHUNKS = 8
_REVIEW_SYNTHESIS_CONTEXT_TOKENS = 6000
_UNIFIED_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
_GUARD_REASON_SECRET_RE = re.compile(
    r"(?i)\b((?:token|api[-_]?key|access[-_]?token|refresh[-_]?token|auth(?:orization)?|bearer|secret|password|passwd|credential|cookie|private[-_]?key)\b\s*[:=]\s*)(?!Bearer\b)([\"']?)([^\"'\s,;]+)\2"
)
_GUARD_REASON_PROMPT_RE = re.compile(r"(?is)\b(?:system\s+|user\s+)?(?:prompt|instructions?)\s*[:=].*$")


def _redact_guard_reason(reason: Any) -> str:
    """Keep a short operator reason without persisting secret or prompt content."""
    text = str(reason or "").replace("\x00", "").strip()
    if not text:
        return ""
    text = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [REDACTED]", text)
    text = _GUARD_REASON_SECRET_RE.sub(lambda match: f"{match.group(1)}[REDACTED]", text)
    text = _GUARD_REASON_PROMPT_RE.sub("prompt: [REDACTED]", text)
    return text[:500]


def _review_text_error(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return "Model returned empty review output."
    text = value.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()

    # Match SUMMARY: with tolerance for markdown headers (#, ##), bullet points (- , * ),
    # bolding (**SUMMARY:** or **SUMMARY**), backticks (`SUMMARY:`), or 1 introductory line.
    match = re.search(
        r"(?:^|\n)(?:#{1,6}\s*)?(?:\*{1,2}|`{1,3})?(?:(?:\d+[\.\)]|[-*+])\s+)?(?:\*{1,2}|`{1,3})?SUMMARY(?:\*{1,2}|`{1,3})?:?[ \t]*(.*)$",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if match is None or match.start() > 250:
        return "Model output did not start with the required SUMMARY: header."
    words = re.findall(r"[^\W\d_]+", match.group(1), flags=re.UNICODE)
    if len(words) < 1:
        return "Model returned an incomplete or malformed review summary."
    return None


def _review_model_identity(value: Any) -> str:
    """Normalize Ollama quantization/instruct tags for tier comparisons."""
    model = str(value or "").strip().casefold()
    return re.sub(r"-(?:instruct|q\d+).*?$", "", model)


def _merge_review_segment_results(
    segment_results: list[dict[str, Any]],
    *,
    label: str,
    task_type: str,
    chunked: bool,
    synthesis_context_budget: int,
    synthesis_task: str,
    max_output_tokens: int,
    complexity: str,
    tenant: str,
    delegate: Any,
    priority: int = 5,
) -> tuple[str, dict[str, Any]]:
    """Return raw review output or a bounded synthesis of chunked results."""
    raw_text = "\n\n".join(
        f"### {label} {index}/{len(segment_results)}\n{str(item.get('text', '')).strip()}"
        for index, item in enumerate(segment_results, start=1)
    )
    if not chunked:
        return str(segment_results[0].get("text", "")), {"enabled": False}

    if estimate_tokens(raw_text) > synthesis_context_budget:
        return raw_text, {"enabled": True, "degraded": True, "error": "Segment findings exceed synthesis budget."}
    try:
        merged = delegate(
            {
                "task_type": task_type,
                "task": synthesis_task,
                "context": raw_text,
                "complexity": complexity,
                "max_tokens": min(max_output_tokens, 1800),
                "priority": int(priority),
            },
            tenant,
        )
        if isinstance(merged, dict) and merged.get("success") is not False:
            output_error = _review_text_error(merged.get("text"))
            if output_error is None:
                return str(merged["text"]), {
                    "enabled": True,
                    "degraded": False,
                    "model": merged.get("model"),
                }
            error = f"Synthesis returned unusable output: {output_error}"
        else:
            error = merged.get("error", "Synthesis returned no text.") if isinstance(merged, dict) else "Synthesis returned no result."
        return raw_text, {"enabled": True, "degraded": True, "error": str(error)}
    except Exception as exc:
        return raw_text, {"enabled": True, "degraded": True, "error": str(exc)}


def _split_review_diff(diff_text: str, max_tokens: int) -> list[str]:
    """Split a unified diff into bounded, file/hunk-aligned review inputs."""
    if not isinstance(diff_text, str) or not diff_text.strip():
        return []
    budget = _safe_int(max_tokens, default=_REVIEW_DIFF_MIN_CHUNK_TOKENS, min_val=_REVIEW_DIFF_MIN_CHUNK_TOKENS)
    sections = [part for part in re.split(r"(?=^diff --git )", diff_text, flags=re.MULTILINE) if part]
    if not sections:
        return [diff_text] if diff_text else []

    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current:
            chunks.append(current)
            current = ""

    for section in sections:
        if estimate_tokens(section) <= budget:
            if current and estimate_tokens(current + section) > budget:
                flush()
            current += section
            continue

        flush()
        chunks.extend(_split_large_review_file(section, budget))
    flush()
    return chunks or [diff_text]


def _split_large_review_file(section: str, budget: int) -> list[str]:
    lines = section.splitlines(keepends=True)
    hunk_starts = [index for index, line in enumerate(lines) if line.startswith("@@ ")]
    if not hunk_starts:
        return [section]

    prefix = "".join(lines[:hunk_starts[0]])
    hunks = [
        "".join(lines[start:end])
        for start, end in zip(hunk_starts, hunk_starts[1:] + [len(lines)])
    ]
    chunks: list[str] = []
    pending_hunks: list[str] = []

    def flush_pending() -> None:
        if pending_hunks:
            chunks.append(prefix + "".join(pending_hunks))
            pending_hunks.clear()

    for hunk in hunks:
        candidate = prefix + "".join(pending_hunks) + hunk
        if estimate_tokens(candidate) <= budget:
            pending_hunks.append(hunk)
            continue

        flush_pending()
        if estimate_tokens(prefix + hunk) <= budget:
            pending_hunks.append(hunk)
        else:
            chunks.extend(_split_large_review_hunk(prefix, hunk, budget))

    flush_pending()
    return chunks or [section]


def _split_large_review_hunk(prefix: str, hunk: str, budget: int) -> list[str]:
    lines = hunk.splitlines(keepends=True)
    if not lines:
        return [prefix + hunk]
    match = _UNIFIED_HUNK_RE.match(lines[0].rstrip("\r\n"))
    if match is None:
        return [prefix + hunk]

    old_start = int(match.group(1))
    old_consumed = 0
    new_start = int(match.group(3))
    new_consumed = 0
    old_count = new_count = 0
    suffix = match.group(5)
    body: list[str] = []
    chunks: list[str] = []

    def render(part: list[str], old_offset: int, new_offset: int, old_lines: int, new_lines: int) -> str:
        header = f"@@ -{old_start + old_offset},{old_lines} +{new_start + new_offset},{new_lines} @@{suffix}\n"
        return prefix + header + "".join(part)

    def flush_body() -> None:
        nonlocal old_consumed, new_consumed, old_count, new_count, body
        if not body:
            return
        chunks.append(render(body, old_consumed, new_consumed, old_count, new_count))
        old_consumed += old_count
        new_consumed += new_count
        old_count = new_count = 0
        body = []

    for line in lines[1:]:
        adds_old = int(line.startswith((" ", "-")))
        adds_new = int(line.startswith((" ", "+")))
        proposed = body + [line]
        candidate = render(proposed, old_consumed, new_consumed, old_count + adds_old, new_count + adds_new)
        if body and estimate_tokens(candidate) > budget:
            flush_body()
        body.append(line)
        old_count += adds_old
        new_count += adds_new
    flush_body()
    return chunks or [prefix + hunk]


def generation_cache_key(
    *,
    model: str,
    prompt: str,
    system: str,
    options: dict[str, Any],
    think: Any,
    execution: Any,
    format: Any = None,
    repository_revision: str = "",
    phase: str = "",
    memory_revision: str = "",
    focus: Any = None,
    preload_profile: str = "",
    project_config_digest: str = "",
    project_namespace: str = "",
) -> str:
    key_data = {
        "model": model,
        "prompt": normalize_generation_cache_prompt(prompt),
        "system": normalize_generation_cache_prompt(system),
        "options": options,
        "think": think,
        "execution": execution,
        "format": format,
        "repository_revision": repository_revision,
        "phase": phase,
        "memory_revision": memory_revision,
        "focus": focus,
        "preload_profile": preload_profile,
        "app_version": __version__,
    }
    if project_config_digest or project_namespace:
        key_data["project_config_digest"] = project_config_digest
        key_data["project_namespace"] = project_namespace
    return stable_hash(key_data)


def normalize_context_for_hash(context: str) -> str:
    """Strip variable whitespace from context to ensure identical code/evidence matches fingerprint."""
    raw = str(context).replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    return "\n".join(lines)
from .resilience import CircuitBreakerRegistry
from .process_utils import hidden_run_kwargs

_GLOBAL_VRAM_LOCK = threading.RLock()


@contextmanager
def vram_priority(is_generation: bool = True):
    """Global lock to serialize heavy batch operations and prioritize LLM inference against VRAM thrashing."""
    with _GLOBAL_VRAM_LOCK:
        yield


def _active_sqlite_databases(state_dir: Path) -> list[Path]:
    legacy_names = {"agent_state.sqlite3", "cache.sqlite3", "leases.sqlite3", "agent_blackboard.sqlite3"}
    recovery_markers = (".path-migration-", ".schema-mismatch-", ".corrupt-")
    return sorted(
        db
        for pattern in ("*.sqlite", "*.sqlite3")
        for db in state_dir.glob(pattern)
        if db.name not in legacy_names and not any(marker in db.name for marker in recovery_markers)
    )


def merge_overlapping_line_ranges(
    ranges: list[tuple[int, int]], *, max_gap: int = 1
) -> list[tuple[int, int]]:
    """Merge overlapping or adjacent line intervals [start, end]."""
    valid = []
    for r in ranges:
        if isinstance(r, (tuple, list)) and len(r) >= 2:
            try:
                s, e = int(r[0]), int(r[1])
                if s > e:
                    s, e = e, s
                valid.append((s, e))
            except (TypeError, ValueError):
                continue
    if not valid:
        return []
    sorted_ranges = sorted(valid, key=lambda item: (item[0], item[1]))
    merged = [sorted_ranges[0]]
    for start, end in sorted_ranges[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end + max_gap:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def merge_overlapping_evidence(
    evidence: list[dict[str, Any]], root: str | Path | None = None
) -> list[dict[str, Any]]:
    """Group evidence by file path and merge overlapping or adjacent line ranges."""
    if not evidence:
        return []

    by_path: dict[str, list[dict[str, Any]]] = {}
    path_keys: list[str] = []

    for item in evidence:
        if not isinstance(item, dict):
            continue
        p = str(item.get("path") or "").strip().replace("\\", "/")
        if not p:
            continue
        if p not in by_path:
            by_path[p] = []
            path_keys.append(p)
        by_path[p].append(dict(item))

    resolved_root = Path(root).expanduser().resolve(strict=False) if root else None
    result: list[dict[str, Any]] = []

    for p in path_keys:
        items = by_path[p]
        if len(items) == 1:
            result.append(items[0])
            continue

        def get_range(it: dict[str, Any]) -> tuple[int, int]:
            s = int(it.get("start_line", 1) or 1)
            e = int(it.get("end_line", s) or s)
            return (min(s, e), max(s, e))

        sorted_items = sorted(items, key=lambda it: get_range(it))

        clusters: list[list[dict[str, Any]]] = []
        for it in sorted_items:
            it_range = get_range(it)
            if not clusters:
                clusters.append([it])
            else:
                cluster = clusters[-1]
                cluster_end = max(get_range(x)[1] for x in cluster)
                if it_range[0] <= cluster_end + 1:
                    cluster.append(it)
                else:
                    clusters.append([it])

        for cluster in clusters:
            if len(cluster) == 1:
                result.append(cluster[0])
                continue

            cluster_start = min(get_range(x)[0] for x in cluster)
            cluster_end = max(get_range(x)[1] for x in cluster)
            max_score = max(float(x.get("score", 0.0) or 0.0) for x in cluster)

            symbols = []
            for x in cluster:
                sym = str(x.get("symbol", "") or "").strip()
                if sym and sym not in symbols:
                    symbols.append(sym)

            merged_symbol = ", ".join(symbols) if symbols else ""

            merged_text = ""
            file_on_disk = (resolved_root / p) if resolved_root else None
            if file_on_disk and file_on_disk.is_file():
                try:
                    all_lines = file_on_disk.read_text(encoding="utf-8", errors="replace").splitlines()
                    slice_lines = all_lines[max(0, cluster_start - 1):cluster_end]
                    merged_text = "\n".join(slice_lines)
                except Exception:
                    merged_text = ""

            if not merged_text:
                line_map: dict[int, str] = {}
                for x in cluster:
                    x_start = get_range(x)[0]
                    x_text = str(x.get("text", x.get("content", "")) or "")
                    x_lines = x_text.splitlines()
                    for idx, line in enumerate(x_lines):
                        line_num = x_start + idx
                        if line_num not in line_map:
                            line_map[line_num] = line
                merged_text = "\n".join(line_map.get(i, "") for i in range(cluster_start, cluster_end + 1))

            best_item = max(cluster, key=lambda x: float(x.get("score", 0.0) or 0.0))
            merged_item = dict(best_item)
            merged_item["start_line"] = cluster_start
            merged_item["end_line"] = cluster_end
            merged_item["score"] = max_score
            merged_item["text"] = merged_text
            if "content" in merged_item:
                merged_item["content"] = merged_text
            if merged_symbol:
                merged_item["symbol"] = merged_symbol
            result.append(merged_item)

    return result


_SOURCE_FOCUS_TERMS = (
    "source", "code", "implementation", "implement", "bug", "fix",
    "refactor", "symbol", "function", "class", "test", "audit",
    "kód", "kod", "oprava",
)
_SOURCE_SUFFIXES = frozenset({
    ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
    ".go", ".rs", ".java", ".kt", ".cs", ".c", ".h", ".cc", ".cpp",
    ".hpp", ".sql", ".html", ".css", ".scss",
})


def _source_focused_query(query: str) -> bool:
    lowered = query.casefold()
    return any(term in lowered for term in _SOURCE_FOCUS_TERMS)


def _context_path_priority(
    relative: str, *, source_focused: bool, override_match: bool,
) -> int:
    if override_match:
        return 0
    if not source_focused:
        return 1
    normalized = relative.replace("\\", "/").casefold()
    parts = normalized.split("/")
    suffix = Path(normalized).suffix
    filename = parts[-1] if parts else ""
    if (
        filename.startswith("test_")
        or filename.endswith("_test.py")
        or any(part in {"test", "tests", "fixture", "fixtures"} for part in parts[:-1])
    ):
        return 2
    if suffix in _SOURCE_SUFFIXES and not any(part in {"docs", "doc", "plans"} for part in parts[:-1]):
        return 1
    if suffix in {".md", ".rst", ".txt"} and any(
        part in {"docs", "doc", "plans", "archive", "archives"}
        for part in parts[:-1]
    ):
        return 3
    return 2


class LocalAIServices:
    commands: Any = None
    task_store: Any = None
    verification_store: Any = None
    incident_store: Any = None
    adoption_metrics: Any = None
    rag: Any = None
    token_router: Any = None
    pipeline: Any = None
    preprocessor: Any = None
    tool_agent: Any = None
    blackboard: Any = None
    agent_state: Any = None
    _VISION_MAX_OUTPUT_TOKENS = 4096
    consistency_guard: Any = None

    @staticmethod
    def merge_overlapping_evidence(evidence: list[dict[str, Any]], root: str | Path | None = None) -> list[dict[str, Any]]:
        return merge_overlapping_evidence(evidence, root=root)

    def __init__(
        self,
        config: dict[str, Any],
        runtime: Any,
        scheduler: Any,
        embeddings: Any,
        artifacts: ArtifactStore,
        telemetry: TelemetryStore,
        repo_tools: RepositoryTools,
        repo_state: Any | None = None,
        code_index: Any | None = None,
        evidence: Any | None = None,
        learner: Any | None = None,
        tuner: Any | None = None,
        deterministic: Any | None = None,
        external_tools: Any | None = None,
    ):
        self.config = config
        self.runtime = runtime
        self.scheduler = scheduler
        self.embeddings = embeddings
        self.artifacts = artifacts
        self.telemetry = telemetry
        self.repo_tools = repo_tools
        if repo_state is None:
            from .repo_state import RepoStateTracker
            repo_state = RepoStateTracker(config)
        self.repo_state = repo_state
        self.code_index = code_index
        self.evidence_store = evidence
        self.learner = learner
        self.tuner = tuner
        self.deterministic = deterministic
        self.external_tools = external_tools
        self.commands: Any | None = None
        lint_config = config.get("speculative_lint", {})
        self._lint_daemons = RuffDaemonPool(
            max_sessions=lint_config.get("max_daemon_sessions", 4),
            idle_ttl=lint_config.get("daemon_idle_ttl_seconds", 300),
        )
        self._biome_daemons = OwnedBiomeDaemonPool(
            max_sessions=lint_config.get("max_daemon_sessions", 4),
            idle_ttl=lint_config.get("daemon_idle_ttl_seconds", 300),
        )
        self.task_store: Any | None = None
        self.verification_store: Any | None = None
        self.incident_store: Any | None = None
        self.adoption_metrics = AdoptionMetricsStore(configured_state_dir(config))
        self.router = ModelRouter(config)
        self.model_policy = ModelExecutionPolicy(config)
        self.profile_catalog = OllamaSubagentCatalog(config)
        self.rag: Any | None = None
        self.token_router: Any | None = None
        self.pipeline: Any | None = None
        self.preprocessor: Any | None = None
        self.tool_agent: Any | None = None
        self.swarm: Any | None = None
        self.blackboard: Any | None = None
        self.agent_state: Any | None = None
        self.consistency_guard: Any | None = None
        self.flight_group = SingleFlightGroup(shards=32, default_timeout_seconds=60.0)

        cache_cfg = config.get("cache", {})
        persistent = SQLiteCache(
            Path(config["server"]["state_dir"]) / "cache.sqlite",
            namespace="generation",
            ttl_seconds=int(cache_cfg.get("generation_ttl_seconds", 7 * 86400)),
            max_entries=int(cache_cfg.get("generation_max_entries", 5000)),
        )
        generation_tier = TieredCache(
            persistent,
            l1_entries=int(cache_cfg.get("l1_generation_entries", 512)),
            l1_ttl_seconds=int(cache_cfg.get("l1_generation_ttl_seconds", 1800)),
        )
        self.generation_cache = SingleFlightCache(generation_tier, enabled=bool(cache_cfg.get("generation", True)), wait_timeout_seconds=float(config.get("resilience", {}).get("singleflight_wait_timeout_seconds", 45)))
        embedding_cache = SQLiteCache(
            Path(config["server"]["state_dir"]) / "cache.sqlite",
            namespace="embeddings",
            ttl_seconds=int(cache_cfg.get("embedding_ttl_seconds", 30 * 86400)),
            max_entries=int(cache_cfg.get("embedding_max_entries", 100000)),
        )
        self.embedding_cache = TieredCache(
            embedding_cache,
            l1_entries=int(cache_cfg.get("l1_embedding_entries", 16384)),
            l1_ttl_seconds=int(cache_cfg.get("l1_embedding_ttl_seconds", 7200)),
        )
        self.embedding_cache_enabled = bool(cache_cfg.get("embeddings", True))
        workspace_cfg = config.get("workspace_cache", {})
        self.repo_cache = TieredCache(
            SQLiteCache(
                Path(config["server"]["state_dir"]) / "cache.sqlite",
                namespace="repo-results",
                ttl_seconds=int(workspace_cfg.get("repo_result_ttl_seconds", 7 * 86400)),
                max_entries=int(workspace_cfg.get("repo_result_max_entries", 20000)),
            ),
            l1_entries=int(cache_cfg.get("l1_repo_entries", 512)),
            l1_ttl_seconds=int(cache_cfg.get("l1_repo_ttl_seconds", 900)),
        )
        self.repo_flight = SingleFlightCache(self.repo_cache, enabled=True, wait_timeout_seconds=float(config.get("resilience", {}).get("singleflight_wait_timeout_seconds", 45)))
        from .context_warmup import ContextWarmup
        self._context_warmup = ContextWarmup()
        self.semantic_cache = SemanticGenerationCache(config, embeddings)
        resilience = config.get("resilience", {})
        self.breakers = CircuitBreakerRegistry(
            failure_threshold=int(resilience.get("circuit_failure_threshold", 3)),
            cooldown_seconds=float(resilience.get("circuit_cooldown_seconds", 20)),
        )
        self.stale_generation_cache = SQLiteCache(
            Path(config["server"]["state_dir"]) / "cache.sqlite",
            namespace="generation-stale",
            ttl_seconds=int(resilience.get("stale_generation_ttl_seconds", 30 * 86400)),
            max_entries=int(resilience.get("stale_generation_max_entries", 10000)),
        )
        self._recent_focus_symbols: dict[str, list[str]] = {}
        self._focus_lock = threading.Lock()
        self._vram_model_lock = threading.RLock()
        self.fallback_count = 0
        self._semantic_lock_guard = threading.Lock()
        self._semantic_scope_locks: dict[str, threading.Lock] = {}
        self._index_refresh_lock = threading.Lock()
        self._index_refresh_state: dict[str, str] = {}
        self._query_expansion_l1 = MemoryLRUCache(1024, ttl_seconds=3600)
        conversation_cfg = config.get("model_conversations", {})
        self.conversations = ConversationStore(
            idle_ttl_seconds=float(conversation_cfg.get("idle_ttl_seconds", 900)),
            max_turns=int(conversation_cfg.get("max_turns", 12)),
            max_conversations=int(conversation_cfg.get("max_conversations", 1000)),
        )

    def set_rag(self, rag: Any) -> None:
        self.rag = rag

    @contextmanager
    def vram_priority(self, is_generation: bool = True):
        """Acquire lock to serialize heavy batch operations and prioritize LLM inference against VRAM thrashing."""
        with self._vram_model_lock:
            yield

    def set_commands(self, commands: Any) -> None:
        self.commands = commands

    def set_task_store(self, task_store: Any) -> None:
        self.task_store = task_store

    def set_verification_store(self, verification_store: Any) -> None:
        self.verification_store = verification_store

    def set_incident_store(self, incident_store: Any) -> None:
        self.incident_store = incident_store

    def set_token_router(self, token_router: Any) -> None:
        self.token_router = token_router

    def set_pipeline(self, pipeline: Any) -> None:
        self.pipeline = pipeline

    def set_preprocessor(self, preprocessor: Any) -> None:
        self.preprocessor = preprocessor

    def set_tool_agent(self, tool_agent: Any) -> None:
        self.tool_agent = tool_agent

    def set_blackboard(self, blackboard: Any) -> None:
        self.blackboard = blackboard

    def set_swarm(self, swarm: Any) -> None:
        self.swarm = swarm

    def set_vram_balancer(self, vram_balancer: Any) -> None:
        self.vram_balancer = vram_balancer

    def set_agent_state(self, store: Any) -> None:
        self.agent_state = store
        from .agent_events import SwarmPubSub
        SwarmPubSub.get_default(state_store=store)

    def set_consistency_guard(self, guard: Any) -> None:
        self.consistency_guard = guard

    @staticmethod
    def _guard_truthy(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() not in {"", "0", "false", "no", "off", "none"}

    def _guard_decision(self, request: ConsistencyRequest, revision: str, *, reason: str = "", approval: Any = "") -> tuple[bool, bool]:
        """Persist bounded operator decisions through the guard's existing memory store."""
        reason_text = str(reason or "").strip()
        if not reason_text and not self._guard_truthy(approval):
            return False, False
        store = getattr(self.consistency_guard, "memory_store", None)
        if store is None or not callable(getattr(store, "record", None)):
            return True, False
        state_store = getattr(store, "state_store", None)
        if state_store is not None and getattr(state_store, "enabled", True) is False:
            return True, False
        if getattr(store, "enabled", True) is False:
            return True, False
        try:
            from .agent_identity import AgentScope
            from .agent_memory import MemoryKind, MemoryRecord

            token = hashlib.sha256(
                f"{request.root}:{request.task_id}:{request.phase}:{revision}:{reason_text}:{approval}".encode("utf-8", "replace")
            ).hexdigest()[:16]
            record = MemoryRecord.create(
                kind=MemoryKind.DECISION,
                scope=AgentScope.REPOSITORY,
                key=f"consistency_decision:{token}",
                value={"approved": self._guard_truthy(approval), "reason": _redact_guard_reason(reason_text)},
                source="consistency_guard",
                repository_revision=revision,
                path_refs=tuple(request.changed_paths),
                related_task=request.task_id or None,
                provenance={"root": request.root, "phase": request.phase, "guard": "agent_consistency"},
            )
            try:
                saved = store.record(record, actor="consistency_guard", idempotency_key=f"consistency-decision:{token}")
            except TypeError:
                saved = store.record(record)
            return True, saved is not None and saved is not False
        except Exception:
            return True, False

    def _guard_existing_approval(self, request: ConsistencyRequest) -> bool:
        store = getattr(self.consistency_guard, "memory_store", None)
        finder = getattr(store, "find", None)
        if not callable(finder) or not request.task_id:
            return False
        try:
            records = finder(root=request.root, limit=12, semantic=False)
        except TypeError:
            try:
                records = finder(limit=12)
            except Exception:
                return False
        except Exception:
            return False
        for record in records or ():
            kind = getattr(getattr(record, "kind", None), "value", getattr(record, "kind", ""))
            value = getattr(record, "value", {})
            provenance = getattr(record, "provenance", {}) or {}
            if kind != "decision" or provenance.get("related_task") != request.task_id:
                continue
            if isinstance(value, dict) and self._guard_truthy(value.get("approved") or value.get("approval")):
                return True
        return False

    def _guard_task_state(self, request: ConsistencyRequest, warnings: tuple[GuardWarning, ...], revision: str) -> tuple[str, bool]:
        store = getattr(self.consistency_guard, "task_store", None)
        if store is None or not request.task_id or not callable(getattr(store, "get", None)):
            return "", False
        try:
            state = store.get(request.task_id)
        except Exception as exc:
            raise RuntimeError("context task state could not be read") from exc
        if state is None:
            raise RuntimeError("context task state is missing")
        status = getattr(getattr(state, "status", None), "value", getattr(state, "status", ""))
        boundary = tuple(item for item in warnings if item.requires_approval or item.severity.lower() in {"boundary", "high", "high-risk"})
        checkpoint_data = getattr(getattr(state, "checkpoint", None), "state_data", {}) or {}
        checkpoint_approval = checkpoint_data.get("approval") or checkpoint_data.get("approved") or checkpoint_data.get("coordinator_decision")
        approved = self._guard_truthy(request.approval) or self._guard_existing_approval(request) or self._guard_truthy(checkpoint_approval)
        if boundary and not approved and status == "active":
            warning_ids = tuple(dict.fromkeys(evidence_id for item in boundary for evidence_id in item.evidence_ids))[:24]
            try:
                from .agent_tasks import TaskCheckpoint, TaskStatus

                store.transition(
                    request.task_id,
                    TaskStatus.WAITING,
                    reason="consistency guard boundary warning",
                    actor="consistency_guard",
                    idempotency_key=f"guard-wait:{request.task_id}:{revision}",
                )
                store.checkpoint(
                    request.task_id,
                    TaskCheckpoint(
                        phase=request.phase,
                        next_action=boundary[0].recommended_action or "obtain approval before continuing",
                        affected_paths=tuple(request.changed_paths),
                        evidence_ids=warning_ids,
                        blockers=tuple(item.code for item in boundary)[:24],
                        state_data={"warning_ids": list(warning_ids), "repository_revision": revision},
                    ),
                    actor="consistency_guard",
                    idempotency_key=f"guard-checkpoint:{request.task_id}:{revision}",
                )
            except Exception as exc:
                raise RuntimeError("context guard checkpoint could not be persisted") from exc
        elif approved and status == "waiting":
            try:
                store.resume(request.task_id, actor="consistency_guard", idempotency_key=f"guard-resume:{request.task_id}:{revision}")
            except Exception as exc:
                raise RuntimeError("context guard resume could not be persisted") from exc
        try:
            refreshed = store.get(request.task_id)
            refreshed_status = getattr(getattr(refreshed, "status", None), "value", getattr(refreshed, "status", ""))
            refreshed_status = str(refreshed_status)
            return refreshed_status, bool(refreshed_status.lower() == "waiting" or (boundary and not approved))
        except Exception as exc:
            raise RuntimeError("refreshed context task state could not be read") from exc

    def _guard_stop_code(self, request: ConsistencyRequest, boundary: bool) -> str:
        """Return terminal stop code when high-risk delivery lacks Agent OS state."""
        if not boundary:
            return ""
        if not request.task_id:
            return "guard_task_id_required"
        agent_state = getattr(self, "agent_state", None)
        if agent_state is not None and getattr(agent_state, "enabled", True) is False:
            return "agent_os_disabled"
        store = getattr(self.consistency_guard, "task_store", None)
        if store is None or getattr(store, "enabled", True) is False:
            return "agent_os_disabled"
        state_store = getattr(store, "state_store", None)
        if state_store is not None and getattr(state_store, "enabled", True) is False:
            return "agent_os_disabled"
        getter = getattr(store, "get", None)
        if not callable(getter):
            return "guard_task_state_unavailable"
        try:
            if getter(request.task_id) is None:
                return "guard_task_state_unavailable"
        except Exception:
            return "guard_task_state_unavailable"
        return ""

    def _touch_project(self, root: str) -> None:
        # Local AI: repository reads refresh only explicitly registered projects.
        if self.preprocessor is not None:
            self.preprocessor.touch_if_registered(root)

    def _repo_cache_state(self, root: str) -> dict[str, Any]:
        """Prefer watcher-backed preprocessing state over spawning Git on hot reads."""
        if self.preprocessor is not None:
            fast = self.preprocessor.cache_fingerprint(root)
            if isinstance(fast, dict) and fast.get("fingerprint"):
                return fast
        return self.repo_state.fingerprint(root)

    def _resident_optimize(self, route: dict[str, Any], task_type_override: str, complexity_override: str) -> dict[str, Any]:
        cfg = self.config.get("routing", {})
        if not cfg.get("prefer_resident_model", True):
            return route
        try:
            active = self.scheduler.status().get("active_model")
        except Exception:
            active = None
        if not active:
            return route

        models = self.config["models"]
        desired = route["model"]
        reason = None
        if route["task_type"] in {"code", "review"}:
            if desired == models.get("fast_code") and active == models.get("heavy_code"):
                # Heavy meets the fast tier quality gate. Once benchmark history exists,
                # keep it resident only when that is actually expected to be faster.
                tuner_ready = bool(self.tuner is not None and self.tuner.ready(str(desired), str(active)))
                if tuner_ready and self.tuner.prefer_resident(str(desired), str(active)):
                    desired = active
                    reason = "resident-heavy-substitutes-fast-autotuned"
            elif desired == models.get("heavy_code") and active == models.get("fast_code"):
                margin = int(cfg.get("resident_fast_margin", 1))
                threshold = int(cfg.get("heavy_min_score", 3))
                # Do not override an explicit heavy request. Only collapse borderline auto-routing.
                borderline = complexity_override == "auto" and route.get("complexity_score", 0) < threshold + margin
                if borderline:
                    tuner_ready = bool(self.tuner is not None and self.tuner.ready(str(desired), str(active)))
                    if tuner_ready and self.tuner.prefer_resident(str(desired), str(active)):
                        desired = active
                        reason = "resident-fast-borderline-heavy-autotuned"
        elif (
            route["task_type"] == "reasoning"
            and cfg.get("reasoning_resident_fallback", False)
            and task_type_override == "auto"
            and active == models.get("heavy_code")
        ):
            desired = active
            reason = "resident-heavy-reasoning-fallback"

        if desired != route["model"]:
            route = dict(route)
            route["original_model"] = route["model"]
            route["model"] = desired
            route["resident_optimization"] = reason
        return route

    def _fallback_models(self, requested: str) -> list[str]:
        cfg = self.config.get("resilience", {})
        if not bool(cfg.get("model_fallback_enabled", True)):
            return []
        models = self.config.get("models", {})
        mapping = {
            models.get("heavy_code"): [models.get("fast_code"), models.get("general")],
            models.get("reasoning"): [models.get("heavy_code"), models.get("fast_code")],
            models.get("fast_code"): [models.get("general")],
            models.get("general"): [models.get("fast_code")],
        }
        out: list[str] = []
        for candidate in mapping.get(requested, []):
            if candidate and candidate != requested and candidate not in out:
                out.append(str(candidate))
        return out[: int(cfg.get("max_model_fallbacks", 2))]

    def _semantic_scope_lock(self, scope: str) -> threading.Lock:
        with self._semantic_lock_guard:
            lock = self._semantic_scope_locks.get(scope)
            if lock is None:
                lock = threading.Lock()
                self._semantic_scope_locks[scope] = lock
                # Bound lock registry; correctness does not depend on preserving old unlocked keys.
                if len(self._semantic_scope_locks) > 2048:
                    for key in list(self._semantic_scope_locks)[:512]:
                        candidate = self._semantic_scope_locks.get(key)
                        if candidate is not None and not candidate.locked():
                            self._semantic_scope_locks.pop(key, None)
            return lock

    def _available_vram_mb(self) -> Any:
        balancer = getattr(self, "vram_balancer", None)
        if not balancer:
            return None
        status = balancer.status()
        if status.get("available", "vram_available_mb" in status):
            return status.get("vram_available_mb")
        return None

    def _observe_tuner_safely(self, model: str, result: dict[str, Any], elapsed_ms: float) -> None:
        try:
            self.tuner.observe(model, result, elapsed_ms)
        except (TypeError, ValueError, OverflowError) as tuner_exc:
            logger.debug(
                "Model tuning observation skipped (%s)",
                type(tuner_exc).__name__,
            )

    def _generate(
        self,
        model: str,
        prompt: str,
        system: str,
        max_tokens: int,
        temperature: float,
        tenant: str,
        source: str,
        priority: int,
        *,
        measured_cloud_context_tokens: int = 0,
        semantic_query: str = "",
        semantic_context_fingerprint: str = "",
        internal: bool = False,
        use_cache: bool = True,
        format: Any = None,
        project_settings: Any | None = None,
        project_role: str = "",
        project_config_digest: str = "",
        project_namespace: str = "",
        repository_revision: str = "",
        trace_system_override: str | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        from .operational_mode import (
            OperationalModeSnapshot,
            load_operational_mode,
            operational_mode_gate_error,
        )

        admission_action = source.split(":", 1)[0].strip().replace("-", "_")
        known_actions = {
            "delegate", "reason", "review", "review_diff", "second_opinion",
            "compress", "route", "batch", "embed", "rerank", "transcribe",
            "vision", "benchmark", "complete_code", "scaffold", "speculative_draft",
            "generate_tests", "solve", "eval_suite", "prompt_eval", "eval_drift",
        }
        if admission_action not in known_actions:
            admission_action = "delegate"
        state_dir = self.config.get("server", {}).get("state_dir")
        if state_dir:
            try:
                mode = load_operational_mode(state_dir)
            except Exception:
                mode = None
            rejection = operational_mode_gate_error(mode, admission_action)
            if rejection is not None:
                return rejection
        trace_system = system if trace_system_override is None else str(trace_system_override)
        mode_pause_result: dict[str, Any] | None = None
        if cancel_event is None:
            cancel_event = threading.Event()
        if project_settings is not None:
            model, project_payload = self.model_policy.apply_project_settings(
                model,
                {"model": model, "system": system},
                settings=project_settings,
                role=project_role,
            )
            system = str(project_payload.get("system", system))
        saving = self.config.get("token_saving", {})
        resilience = self.config.get("resilience", {})
        default_request_timeout = float(self.config.get("server", {}).get("request_timeout_seconds", 300)) + 30.0
        request_timeout = max(0.05, float(resilience.get("scheduler_wait_timeout_seconds", default_request_timeout)))
        request_deadline = time.monotonic() + request_timeout
        max_tokens = max(64, min(int(max_tokens), int(saving.get("max_local_output_tokens", 8192))))
        role = source.rsplit(":", 1)[-1].lower()
        if source == "second-opinion":
            role = "second-opinion"
        vram_free = self._available_vram_mb()
        initial_profile = self.model_policy.profile(
            model, role=role, input_tokens=estimate_tokens(prompt), output_tokens=max_tokens,
            background=source.startswith("preprocess:"),
            vram_free_mb=vram_free,
        )
        prompt_budget = min(int(saving.get("max_local_input_tokens", 56000)), initial_profile.prompt_budget_tokens)
        prepared = fit_text(prompt, prompt_budget)
        base_payload, execution_profile = self.model_policy.apply_payload(
            model,
            {"model": model, "prompt": prepared.text, "system": system, "stream": False,
             "keep_alive": self.config.get("ollama", {}).get("keep_alive", "-1"),
             "options": {"num_predict": max_tokens, "temperature": float(temperature)}},
            role=role, input_tokens=prepared.estimated_tokens, output_tokens=max_tokens,
            background=source.startswith("preprocess:"), preserve_explicit_think=False,
            vram_free_mb=vram_free,
        )
        if format:
            base_payload["format"] = format
        options = dict(base_payload.get("options", {}))
        if not semantic_query and prompt:
            clean_first = re.sub(r"^(TASK|QUESTION|INSTRUCTION|PROMPT|Problem|PROBLEM):\s*", "", prompt.strip(), flags=re.I)
            first_line = clean_first.split("\n\n", 1)[0].splitlines()[0] if clean_first else ""
            if len(first_line.strip()) >= 8:
                semantic_query = normalize_query(first_line.strip())
        elif semantic_query:
            semantic_query = normalize_query(semantic_query)

        execution_scope = {**execution_profile.cache_scope(), "stream_completion_contract": 2}
        norm_context_fp = stable_hash(normalize_context_for_hash(semantic_context_fingerprint)) if semantic_context_fingerprint else "no-context"
        cache_key = generation_cache_key(
            model=model,
            prompt=prepared.text,
            system=system,
            options=options,
            think=base_payload.get("think"),
            execution=execution_scope,
            format=base_payload.get("format"),
            repository_revision=repository_revision,
            project_config_digest=project_config_digest,
            project_namespace=project_namespace,
        )
        semantic_scope_data = {
            "model": model, "system": system, "options": options, "think": base_payload.get("think"), "execution": execution_scope,
            "context": norm_context_fp, "source": source.split(":", 1)[0], "app_version": __version__,
        }
        if project_config_digest or project_namespace:
            semantic_scope_data.update({
                "repository_revision": repository_revision,
                "project_config_digest": project_config_digest,
                "project_namespace": project_namespace,
            })
        semantic_scope = stable_hash(semantic_scope_data)
        started = time.perf_counter()
        cache_layer = "miss"
        semantic_score = 0.0
        requested_model = model

        def compute_inner() -> dict[str, Any]:
            nonlocal semantic_score
            if use_cache and semantic_query:
                semantic, semantic_score = self.semantic_cache.get(semantic_scope, semantic_query)
                if isinstance(semantic, dict):
                    reused = copy.deepcopy(semantic)
                    reused["_lah_cache_origin"] = "semantic"
                    reused["_lah_semantic_similarity"] = semantic_score
                    return reused

            availability = getattr(self.runtime, "is_online", None)
            if callable(availability):
                try:
                    backend_online = bool(availability())
                except Exception:
                    backend_online = True
                if not backend_online:
                    return {
                        "success": False,
                        "unsupported": True,
                        "degraded": True,
                        "terminal": False,
                        "retryable": True,
                        "error_code": "local_backend_unavailable",
                        "error": "No local model backend is currently available; retry after the backend is online.",
                        "model": requested_model,
                    }

            tier_ranks = {"fast_code": 0, "general": 0, "heavy_code": 1, "reasoning": 2}

            def model_tier_rank(candidate_model: str) -> int:
                return max(
                    (rank for role_name, rank in tier_ranks.items()
                     if str(self.config.get("models", {}).get(role_name, "")) == str(candidate_model or "")),
                    default=0,
                )

            requested_rank = model_tier_rank(requested_model)
            # Runtime failover must keep the router's quality floor for this request.
            candidates = [requested_model] + [
                candidate
                for candidate in self._fallback_models(requested_model)
                if model_tier_rank(candidate) >= requested_rank
            ]
            errors: list[str] = []
            attempt_failures: list[dict[str, Any]] = []
            retryable_error = False
            timeout_error = False
            preempted_error = False
            cancel_requested = False
            scheduler_state = ""

            def record_attempt_failures(*, recovered: bool) -> None:
                for failed in attempt_failures:
                    self.telemetry.record_error(
                        "ollama", f"{source}:model_attempt", failed["error"], tenant=tenant,
                        error_type_override=failed["error_type"],
                        error_code_override=failed["error_code"],
                        retryable=failed["retryable"], recovered=recovered,
                    )
            for index, candidate in enumerate(candidates):
                breaker_key = f"model:{candidate}"
                if not self.breakers.allow(breaker_key):
                    errors.append(f"{candidate}: circuit open")
                    self.telemetry.record_stage(tenant=tenant, action=source, stage="model_attempt", model=candidate, success=False, degraded=True, error_type="circuit_open")
                    continue

                def run(candidate_model: str = candidate) -> dict[str, Any]:
                    nonlocal mode_pause_result
                    def cancelled_result() -> dict[str, Any]:
                        return {
                            "success": False, "cancelled": True, "preempted": True,
                            "reason": "cancelled",
                            "error": "conversation generation cancelled for resource release",
                            "model": candidate_model, "terminal": True, "retryable": False,
                            "_cacheable": False,
                        }
                    if cancel_event is not None and cancel_event.is_set():
                        return cancelled_result()
                    # A smart->fast resilience fallback may have a smaller context window
                    # than the originally requested model. Re-fit locally instead of
                    # relying on implicit server truncation or turning an outage into OOM.
                    candidate_hint = self.model_policy.profile(
                        candidate_model, role=role, input_tokens=prepared.estimated_tokens, output_tokens=max_tokens,
                        background=source.startswith("preprocess:"),
                        vram_free_mb=vram_free,
                    )
                    candidate_prepared = fit_text(prepared.text, min(int(saving.get("max_local_input_tokens", 56000)), candidate_hint.prompt_budget_tokens))
                    payload, candidate_profile = self.model_policy.apply_payload(
                        candidate_model,
                        {"model": candidate_model, "prompt": candidate_prepared.text, "system": system, "stream": False,
                         "keep_alive": self.config.get("ollama", {}).get("keep_alive", "-1"),
                         "options": {"num_predict": max_tokens, "temperature": float(temperature)}},
                        role=role, input_tokens=candidate_prepared.estimated_tokens, output_tokens=max_tokens,
                        background=source.startswith("preprocess:"), preserve_explicit_think=False,
                        vram_free_mb=vram_free,
                    )
                    trace_observer = observer()
                    trace_payload = dict(payload)
                    if project_settings is not None or trace_system_override is not None:
                        trace_payload["system"] = trace_system
                    def request_candidate() -> dict[str, Any]:
                        stream = getattr(self.runtime, "request_stream", None)
                        if callable(stream):
                            if trace_observer is not None:
                                trace_observer.model_request(trace_payload)
                            return stream(
                                "/api/generate", payload,
                                trace_observer.output_delta if trace_observer is not None else (lambda _chunk: None),
                                on_thinking=getattr(trace_observer, "thinking_delta", None) if trace_observer is not None else None,
                                timeout=max(0.05, request_deadline - time.monotonic()),
                                deadline=request_deadline,
                                should_stop=cancel_event.is_set,
                            )
                        interruptible = getattr(self.runtime, "request_interruptible", None)
                        if cancel_event is not None and callable(interruptible):
                            if trace_observer is not None:
                                trace_observer.model_request(trace_payload)
                            result = interruptible(
                                "/api/generate", payload, should_stop=cancel_event.is_set,
                                timeout=max(0.05, request_deadline - time.monotonic()),
                                deadline=request_deadline,
                            )
                            if trace_observer is not None and result.get("response"):
                                trace_observer.output_delta(str(result["response"]))
                            return result
                        if trace_observer is not None:
                            trace_observer.model_request(trace_payload)
                            return self.runtime.request_stream(
                                "/api/generate", payload, trace_observer.output_delta,
                                on_thinking=getattr(trace_observer, "thinking_delta", None),
                                timeout=max(0.05, request_deadline - time.monotonic()),
                                deadline=request_deadline,
                                should_stop=cancel_event.is_set,
                            )
                        return self.runtime.request("/api/generate", payload)

                    admission = getattr(self, "inference_admission", None)
                    if callable(admission):
                        # Recheck at backend handoff; scheduler delay can stale the
                        # earlier mode snapshot. Do not hold the mode lock over I/O.
                        with admission(admission_action) as rejection:
                            if rejection is not None:
                                if rejection.get("code") == "operational_mode_blocked":
                                    rejection_mode = OperationalModeSnapshot(
                                        str(rejection.get("operational_mode") or "maintenance"),
                                        int(rejection.get("operational_mode_revision", 0) or 0),
                                        None,
                                        bool(rejection.get("operational_mode_degraded", False)),
                                    )
                                    mode_rejection = operational_mode_gate_error(
                                        rejection_mode, admission_action,
                                    )
                                    if mode_rejection is not None:
                                        mode_pause_result = mode_rejection
                                        return mode_rejection
                                mode_pause_result = rejection
                                return rejection
                            response = request_candidate()
                    else:
                        # Minimal/test runtimes may not provide the shared admission
                        # lock, so refresh the mode immediately before the handoff.
                        try:
                            mode = load_operational_mode(configured_state_dir(self.config, create=False))
                        except Exception:
                            mode = None
                        mode_rejection = operational_mode_gate_error(mode, admission_action)
                        if mode_rejection is not None:
                            mode_pause_result = mode_rejection
                            return mode_rejection
                        response = request_candidate()
                    if response.get("outcome_unknown") or response.get("cleanup_unconfirmed") or response.get("_lah_partial_response"):
                        return {"success": False, "error": response.get("error") or "model response was interrupted",
                                "model": candidate_model, "terminal": True, "retryable": False,
                                "_lah_partial_response": bool(response.get("_lah_partial_response")),
                                "outcome_unknown": bool(response.get("outcome_unknown")),
                                "cleanup_unconfirmed": bool(response.get("cleanup_unconfirmed")),
                                "context_recovery": response.get("context_recovery"),
                                "_lah_retry_count": int(response.get("_lah_retry_count", 0) or 0)}
                    if (cancel_event is not None and cancel_event.is_set()) or response.get("preempted") is True:
                        return cancelled_result()
                    if response.get("_lah_repetition_loop_detected"):
                        return {
                            "success": False,
                            "error": str(response.get("error") or "model output repetition loop detected"),
                            "model": candidate_model,
                            "terminal": True,
                            "retryable": False,
                            "repetition_loop_detected": True,
                            "_lah_repetition_loop_detected": True,
                            "_lah_retry_count": int(response.get("_lah_retry_count", 0) or 0),
                        }
                    if response.get("preempted"):
                        return {
                            "success": False,
                            "error": str(response.get("error") or "model request cancelled"),
                            "model": candidate_model,
                            "preempted": True,
                            "terminal": True,
                            "retryable": False,
                            "error_code": "model_request_cancelled",
                        }
                    if response.get("timed_out"):
                        return {
                            "success": False,
                            "error": str(response.get("error") or "model request deadline exceeded"),
                            "model": candidate_model,
                            "timed_out": True,
                            "terminal": False,
                            "retryable": True,
                            "error_code": "model_request_timeout",
                        }
                    if "error" in response:
                        retryable = is_retryable_local_backend_error(response["error"])
                        return {
                            "success": False, "error": response["error"], "model": candidate_model,
                            "retryable": retryable, "terminal": not retryable,
                            "error_code": "local_backend_transport" if retryable else "local_model_error",
                            "_lah_retry_count": int(response.get("_lah_retry_count", 0) or 0),
                            "_lah_partial_response": bool(response.get("_lah_partial_response")),
                            "outcome_unknown": bool(response.get("outcome_unknown")),
                            "cleanup_unconfirmed": bool(response.get("cleanup_unconfirmed")),
                            "context_recovery": response.get("context_recovery"),
                        }
                    raw_text = response.get("response", "")
                    clean_text, parsed_thinking = postprocess_model_output(raw_text, role=role)
                    thinking = response.get("thinking") or parsed_thinking
                    return {
                        "success": True, "model": candidate_model, "requested_model": requested_model,
                        "text": clean_text, "thinking": thinking,
                        "final_response_produced": bool(clean_text.strip()),
                        "final_response_status": "produced" if clean_text.strip() else "empty",
                        "load_duration_ns": response.get("load_duration", 0), "eval_count": response.get("eval_count", 0),
                        "prompt_eval_count": response.get("prompt_eval_count", 0),
                        "prompt_eval_duration_ns": response.get("prompt_eval_duration", 0),
                        "eval_duration_ns": response.get("eval_duration", 0), "total_duration_ns": response.get("total_duration", 0),
                        "_lah_retry_count": int(response.get("_lah_retry_count", 0) or 0),
                        "execution_profile": candidate_profile.cache_scope(),
                        **({"context_recovery": response["context_recovery"]} if response.get("context_recovery") is not None else {}),
                        "_lah_provider": response.get("_lah_provider", "ollama"),
                        "_lah_cache_origin": "ollama", "fallback_used": candidate_model != requested_model,
                        "_cacheable": candidate_model == requested_model and bool(clean_text.strip()) and not response.get("context_recovery"),
                    }

                try:
                    result = self.scheduler.submit(
                        candidate, tenant, source if index == 0 else f"{source}:fallback", run, priority=priority,
                        wait_timeout=max(0.05, request_deadline - time.monotonic()),
                        cancel_event=cancel_event,
                    )
                except TimeoutError as exc:
                    timeout_error = True
                    retryable_error = True
                    cancel_event.set()
                    result = {
                        "success": False,
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                        "model": candidate,
                        "terminal": False,
                        "retryable": True,
                        "error_code": str(getattr(exc, "error_code", "model_request_timeout")),
                    }
                    job_id = getattr(exc, "job_id", None)
                    if job_id is not None:
                        result["scheduler_job_id"] = int(job_id)
                    state = getattr(exc, "state", "")
                    if state:
                        result["scheduler_state"] = str(state)
                        scheduler_state = str(state)
                    cancel_requested = True
                except Exception as exc:
                    retryable = getattr(exc, "retryable", None)
                    if retryable is None:
                        retryable = is_retryable_local_backend_error(exc)
                    error_code = getattr(exc, "error_code", None)
                    if not error_code:
                        error_code = "local_backend_transport" if retryable else "local_model_error"
                    result = {
                        "success": False, "error": str(exc), "error_type": type(exc).__name__, "model": candidate,
                        "retryable": bool(retryable), "terminal": not bool(retryable),
                        "error_code": str(error_code),
                    }
                    if getattr(exc, "admission", None):
                        result["admission"] = exc.admission
                if mode_pause_result is not None:
                    return mode_pause_result
                retryable_error = retryable_error or bool(result.get("retryable", False))
                if result.get("success"):
                    self.breakers.success(breaker_key)
                    if candidate != requested_model:
                        self.fallback_count += 1
                    record_attempt_failures(recovered=True)
                    return result
                if result.get("_lah_partial_response") or result.get("outcome_unknown") or result.get("cleanup_unconfirmed"):
                    self.breakers.failure(breaker_key)
                    attempt_failures.append({"error": str(result.get("error", "model response interrupted")),
                                             "error_type": "model_attempt_interrupted", "error_code": "model_attempt_interrupted",
                                             "retryable": False})
                    self.telemetry.record_stage(tenant=tenant, action=source, stage="model_attempt", model=candidate,
                                                success=False, degraded=index > 0, error_type="model_attempt_interrupted")
                    record_attempt_failures(recovered=False)
                    return {**result, "terminal": True, "retryable": False, "_cacheable": False}
                if result.get("preempted"):
                    preempted_error = True
                    errors.append(f"{candidate}: {result.get('error') or 'model request cancelled'}")
                    break
                if result.get("timed_out"):
                    timeout_error = True
                self.breakers.failure(breaker_key)
                attempt_error = str(result.get("error", "failed"))
                attempt_retries = int(result.get("_lah_retry_count", 0) or 0)
                self.telemetry.record_stage(tenant=tenant, action=source, stage="model_attempt", model=candidate, success=False, degraded=index > 0, retry_count=attempt_retries, error_type="model_attempt_failed")
                attempt_failures.append({
                    "error": attempt_error,
                    "error_type": str(result.get("error_type", "")),
                    "error_code": str(result.get("error_code", "")),
                    "retryable": bool(result.get("retryable", True)),
                })
                errors.append(f"{candidate}: {attempt_error}")
                if timeout_error:
                    break

            # Same exact prompt may be served stale only as a resilience fallback.
            if use_cache and not preempted_error and not cancel_requested and not timeout_error and bool(resilience.get("serve_stale_on_error", True)):
                stale = self.stale_generation_cache.get(cache_key)
                if isinstance(stale, dict):
                    reused = copy.deepcopy(stale)
                    reused["_lah_cache_origin"] = "stale"
                    reused["stale_fallback"] = True
                    reused["runtime_errors"] = errors[-3:]
                    record_attempt_failures(recovered=True)
                    return reused
            record_attempt_failures(recovered=False)
            failure = {
                "success": False,
                "error": "; ".join(errors) or "all local model attempts failed",
                "model": requested_model,
            }
            if attempt_failures:
                failure["error_type"] = attempt_failures[-1]["error_type"]
                failure["error_code"] = attempt_failures[-1]["error_code"]
            if retryable_error:
                failure.update({"terminal": False, "retryable": True})
            if timeout_error:
                failure["error_code"] = "model_request_timeout"
            if preempted_error:
                failure.update({"terminal": True, "retryable": False, "preempted": True, "error_code": "model_request_cancelled"})
            if cancel_requested:
                failure["cancel_requested"] = True
            if scheduler_state:
                failure["scheduler_state"] = scheduler_state
            return failure

        def compute() -> dict[str, Any]:
            nonlocal semantic_score
            if not semantic_query:
                return compute_inner()
            # Different phrasings with the same strict semantic scope serialize only on a cache miss.
            # The second request rechecks semantic cache after the first completes, coalescing paraphrases.
            with self._semantic_scope_lock(semantic_scope):
                semantic, semantic_score = self.semantic_cache.get(semantic_scope, semantic_query)
                if isinstance(semantic, dict):
                    reused = copy.deepcopy(semantic)
                    reused["_lah_cache_origin"] = "semantic"
                    reused["_lah_semantic_similarity"] = semantic_score
                    return reused
                result = compute_inner()
                if isinstance(result, dict) and result.get("success", "error" not in result) and not result.get("fallback_used", False) and result.get("_cacheable", True) and not result.get("context_recovery"):
                    clean = {k: v for k, v in result.items() if not str(k).startswith("_lah_")}
                    try:
                        self.semantic_cache.set(semantic_scope, semantic_query, clean)
                    except (OSError, sqlite3.Error, ValueError) as cache_exc:
                        logger.debug(
                            "Semantic generation cache write skipped (%s)",
                            type(cache_exc).__name__,
                        )
                return result

        if use_cache:
            raw, cache_hit, coalesced = self.generation_cache.get_or_compute(cache_key, compute)
        else:
            raw, cache_hit, coalesced = compute_inner(), False, False
        if mode_pause_result is not None:
            return mode_pause_result
        origin = str(raw.get("_lah_cache_origin", "")) if isinstance(raw, dict) else ""
        if not use_cache:
            cache_layer = "disabled"
        elif coalesced:
            cache_layer = "single-flight"
        elif cache_hit:
            cache_layer = "exact"
        elif origin == "semantic":
            cache_layer = "semantic"
            semantic_score = float(raw.get("_lah_semantic_similarity", semantic_score) or 0.0)
        elif origin == "stale":
            cache_layer = "stale-on-error"
        else:
            cache_layer = "ollama"

        if use_cache and isinstance(raw, dict) and raw.get("success", "error" not in raw) and origin != "stale" and not raw.get("fallback_used", False) and not raw.get("context_recovery") and raw.get("final_response_produced", True):
            clean_stale = {k: v for k, v in raw.items() if not str(k).startswith("_lah_")}
            try:
                self.stale_generation_cache.set(cache_key, clean_stale)
            except (OSError, sqlite3.Error, ValueError) as cache_exc:
                logger.debug(
                    "Stale generation cache write skipped (%s)",
                    type(cache_exc).__name__,
                )

        result = copy.deepcopy(raw)
        queue_wait_ms = float(result.get("_lah_scheduler_queue_wait_ms", 0) or 0) if cache_layer == "ollama" else 0.0
        service_ms = float(result.get("_lah_scheduler_service_ms", 0) or 0) if cache_layer == "ollama" else 0.0
        retry_count = int(result.get("_lah_retry_count", 0) or 0) if cache_layer == "ollama" else 0
        for internal_key in ["_lah_cache_origin", "_lah_semantic_similarity", "_lah_scheduler_queue_wait_ms", "_lah_scheduler_service_ms", "_lah_scheduler_background", "_lah_retry_count"]:
            result.pop(internal_key, None)
        effective_cache_hit = cache_hit or cache_layer in {"semantic", "single-flight", "stale-on-error"}
        self.telemetry.record_stage(
            tenant=tenant,
            action=source,
            stage="cache_decision",
            success=True,
            error_type="cache_disabled" if not use_cache else cache_decision_reason(cache_layer, semantic_query=semantic_query),
        )
        result["cache_hit"] = effective_cache_hit
        result["cache_layer"] = cache_layer
        result["semantic_similarity"] = round(float(semantic_score), 5) if cache_layer == "semantic" else None
        result["coalesced"] = coalesced
        result["prompt_budget"] = {
            "estimated_tokens": prepared.estimated_tokens, "original_estimated_tokens": prepared.original_tokens,
            "truncated": prepared.truncated,
        }

        full_text = str(result.get("text", ""))
        full_output_tokens = estimate_tokens(full_text)
        provider_usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        try:
            cache_read_tokens = max(0, int(
                result.get("cache_read_tokens", provider_usage.get("cache_read_tokens", 0)) or 0
            ))
        except (TypeError, ValueError, OverflowError):
            cache_read_tokens = 0
        if (not internal) and bool(saving.get("compact_responses", True)):
            result = self.artifacts.compact(result, tenant, source)
        result["latency"] = {
            "queue_wait_ms": round(max(0.0, queue_wait_ms), 1),
            "service_ms": round(max(0.0, service_ms), 1),
        }
        inline_tokens = estimate_tokens(str(result.get("text", "")))
        compact_saved = max(0, full_output_tokens - inline_tokens)
        cached_compute_tokens = (prepared.estimated_tokens + full_output_tokens) if cache_layer in {"exact", "semantic", "single-flight", "stale-on-error"} else 0
        result["token_saving"] = {
            "compact_output_tokens_avoided_est": compact_saved,
            "delegated_cloud_context_tokens_avoided_est": max(0, int(measured_cloud_context_tokens)),
            # Separate from cloud-context savings: these are tokens the local model
            # did not need to process/generate because a cache/single-flight result
            # was reused. Keeping the metric separate prevents double counting.
            "local_compute_tokens_avoided_est": max(0, int(cached_compute_tokens)),
        }

        if self.tuner is not None and cache_layer == "ollama":
            self._observe_tuner_safely(
                str(result.get("model", model)),
                result,
                (time.perf_counter() - started) * 1000,
            )

        success = bool(result.get("success", "error" not in result))
        error_type = "" if success else "model_request_failed"
        self.telemetry.record(
            tenant=tenant, action=source, model=str(result.get("model", model)), cache_hit=effective_cache_hit, coalesced=coalesced,
            cache_layer=cache_layer, input_tokens=prepared.estimated_tokens,
            cache_read_tokens=cache_read_tokens, output_tokens=full_output_tokens,
            task_type=source.split(":", 1)[1] if source.startswith("delegate:") else source.split(":", 1)[0],
            avoided_cloud_tokens=max(0, int(measured_cloud_context_tokens)) + compact_saved,
            duration_ms=(time.perf_counter() - started) * 1000, queue_wait_ms=queue_wait_ms, service_ms=service_ms,
            load_duration_ms=float(result.get("load_duration_ns", 0) or 0) / 1_000_000,
            success=success, fallback_used=bool(result.get("fallback_used", False)), retry_count=retry_count,
            degraded=bool(result.get("stale_fallback", False) or result.get("fallback_used", False)), error_type=error_type,
        )
        if not success:
            self.telemetry.record_error(
                "ollama", source, result.get("error", "model request failed"), tenant=tenant,
                error_type_override=str(result.get("error_type", "")),
                error_code_override=str(result.get("error_code", "")),
                retryable=True,
            )
        return result

    @staticmethod
    def _conversation_user_prompt(task: str, context: str = "") -> str:
        prompt = f"TASK:\n{task}\n"
        if context:
            prompt += f"\nCONTEXT:\n{context}\n"
        return prompt

    @staticmethod
    def _conversation_transcript(messages: list[dict[str, str]], next_user_prompt: str) -> str:
        rendered = []
        for message in messages:
            role = "USER" if message.get("role") == "user" else "ASSISTANT"
            rendered.append(f"{role}:\n{message.get('content', '')}")
        rendered.append(f"USER:\n{next_user_prompt}")
        return "CONVERSATION:\n\n" + "\n\n".join(rendered)

    def _conversation_prompt_limit(self) -> int:
        cfg = self.config.get("model_conversations", {})
        return max(256, int(cfg.get("max_prompt_tokens", self.config.get("token_saving", {}).get("max_local_input_tokens", 56000))))

    def _conversation_error(self, conversation_id: str, error: str) -> dict[str, Any]:
        active = error == "conversation is already running"
        return {
            "success": False,
            "conversation_id": conversation_id,
            "error": error,
            "terminal": not active,
            "retryable": active,
            "in_progress": active,
        }

    @staticmethod
    def _conversation_cancelled(conversation_id: str) -> dict[str, Any]:
        return {
            "success": False, "conversation_id": conversation_id,
            "error": "conversation generation cancelled for resource release",
            "reason": "cancelled", "cancelled": True, "preempted": True,
            "terminal": True, "retryable": False,
        }

    def _start_conversation(
        self,
        *,
        tenant: str,
        prompt: str,
        route: dict[str, Any],
        system: str,
        max_tokens: int,
        temperature: float,
        source: str,
        priority: int,
        trace_system: str | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        if cancel_event is not None and cancel_event.is_set():
            return self._conversation_cancelled("")
        if estimate_tokens(prompt) + estimate_tokens(system) > self._conversation_prompt_limit():
            return self._conversation_error("", "conversation prompt limit exceeded")
        conversation = self.conversations.start_reserved(tenant, {
            "model": route["model"], "system": system,
            "trace_system": system if trace_system is None else trace_system,
            "max_tokens": max_tokens,
            "temperature": temperature, "source": source, "priority": priority,
            "route": dict(route),
        })
        if conversation is None:
            return self._conversation_error("", "conversation capacity reached")
        try:
            result = self._generate(
                route["model"], prompt, system, max_tokens, temperature, tenant, source, priority,
                internal=True, use_cache=False, trace_system_override=trace_system,
                cancel_event=cancel_event,
            )
        except Exception:
            self.conversations.discard(conversation.conversation_id, tenant)
            raise
        if not result.get("success", "error" not in result):
            self.conversations.discard(conversation.conversation_id, tenant)
            return result
        if cancel_event is not None and cancel_event.is_set():
            self.conversations.discard(conversation.conversation_id, tenant)
            return self._conversation_cancelled(conversation.conversation_id)
        if not self.conversations.complete(conversation.conversation_id, tenant, prompt, str(result.get("text", ""))):
            return self._conversation_error(
                conversation.conversation_id,
                "conversation expired or was lost while model was running",
            )
        result["conversation_id"] = conversation.conversation_id
        result["route"] = dict(route)
        return result

    def continue_conversation(
        self, args: dict[str, Any], tenant: str, *, cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        conversation_id = str(args.get("conversation_id", "")).strip()
        task = str(args.get("task", "")).strip()
        if not conversation_id:
            return self._conversation_error("", "conversation_id is required")
        if not task:
            return self._conversation_error(conversation_id, "task is required")
        if cancel_event is not None and cancel_event.is_set():
            return self._conversation_cancelled(conversation_id)
        conversation, error = self.conversations.reserve(conversation_id, tenant)
        if error:
            return self._conversation_error(conversation_id, error)
        assert conversation is not None
        user_prompt = self._conversation_user_prompt(task, str(args.get("context", "")))
        prompt = self._conversation_transcript(conversation.messages, user_prompt)
        settings = conversation.settings
        if estimate_tokens(prompt) + estimate_tokens(str(settings["system"])) > self._conversation_prompt_limit():
            self.conversations.abort(conversation_id, tenant)
            return self._conversation_error(conversation_id, "conversation prompt limit exceeded")
        try:
            result = self._generate(
                str(settings["model"]), prompt, str(settings["system"]), int(settings["max_tokens"]),
                float(settings["temperature"]), tenant, str(settings["source"]), int(settings["priority"]),
                internal=True, use_cache=False,
                trace_system_override=str(settings.get("trace_system", settings["system"])),
                cancel_event=cancel_event,
            )
        except Exception:
            self.conversations.abort(conversation_id, tenant)
            raise
        if not result.get("success", "error" not in result):
            self.conversations.abort(conversation_id, tenant)
            return result
        if cancel_event is not None and cancel_event.is_set():
            self.conversations.abort(conversation_id, tenant)
            return self._conversation_cancelled(conversation_id)
        if not self.conversations.complete(
            conversation_id, tenant, user_prompt, str(result.get("text", "")),
        ):
            return self._conversation_error(
                conversation_id,
                "conversation expired or was lost while model was running",
            )
        result["conversation_id"] = conversation_id
        result["route"] = dict(settings["route"])
        return result

    def _resolve_local_task_project(self, root: Any) -> tuple[Any | None, str, str, str]:
        root_value = str(root or "").strip()
        if not root_value:
            return None, "", "", ""
        try:
            from .project_config import resolve_project_context
            from .state_paths import configured_state_dir

            project = resolve_project_context(
                root_value,
                configured_state_dir(getattr(self, "config", {}), create=False),
            )
        except (OSError, ValueError) as project_exc:
            logger.debug(
                "Project task context unavailable (%s)",
                type(project_exc).__name__,
            )
            return None, "", "", ""

        snapshot = self.repo_tools.git_snapshot(root_value)
        revision = str(getattr(snapshot, "repository_revision", "") or "")[:200]
        namespace = str(project.coordination_id or "")
        return project, project.config_digest, namespace, revision

    def delegate(
        self, args: dict[str, Any], tenant: str, *, cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        if bool(args.get("conversation", False)):
            if str(args.get("profile", "")).strip():
                return self._conversation_error("", "conversations do not support profiles")
            if str(args.get("delivery", "sync")).strip().lower() != "sync":
                return self._conversation_error("", "conversations require delivery=sync")
        if str(args.get("profile", "")).strip():
            return self.delegate_profile(args, tenant)
        project_context, project_config_digest, project_namespace, project_revision = self._resolve_local_task_project(
            args.get("root") or args.get("cwd", "")
        )
        project_settings = project_context.settings if project_context is not None else None
        project_error_codes = getattr(getattr(project_context, "resolution", None), "error_codes", ())
        if not isinstance(project_error_codes, (list, tuple)):
            project_error_codes = ()
        project_warning = ""
        if project_error_codes:
            safe_codes = [
                code[:80] for code in (str(value) for value in project_error_codes[:8])
                if re.fullmatch(r"[A-Za-z0-9_.-]+", code)
            ]
            code_summary = ", ".join(safe_codes)
            project_warning = "Project settings invalid; defaults used" + (f" (codes: {code_summary})" if code_summary else ".")

        def attach_project_warning(result: dict[str, Any]) -> dict[str, Any]:
            if project_warning:
                warnings = result.get("warnings", [])
                warnings = list(warnings) if isinstance(warnings, (list, tuple)) else []
                warnings.append(project_warning)
                result["warnings"] = warnings
            return result

        if "prompt" in args:
            return {"success": False, "error": "delegate accepts task; prompt is not an alias"}
        task = args.get("task", "")
        context_value = args.get("context", "")
        if not isinstance(task, str):
            return {"success": False, "error": "task must be a string"}
        if not isinstance(context_value, str):
            return {"success": False, "error": "context must be a string"}
        if bool(args.get("conversation", False)):
            task = task.strip()
            if not task:
                return self._conversation_error("", "task is required")
        context = context_value
        task_type_override = str(args.get("task_type", "auto"))
        complexity_override = str(args.get("complexity", "auto"))
        route = self.router.classify(task, context, task_type_override, complexity_override)
        route = self._resident_optimize(route, task_type_override, complexity_override)
        try:
            route = self.router.apply_model_override(route, str(args.get("model", "")))
        except ValueError as exc:
            return {"success": False, "error": str(exc), "terminal": True, "retryable": False}
        task_type = route["task_type"]
        if task_type in {"code", "review"}:
            project_role = "heavy_code" if route.get("complexity") == "heavy" else "fast_code"
        elif task_type == "reasoning":
            project_role = "reasoning" if route.get("complexity") == "heavy" else "heavy_code"
        else:
            project_role = "general"
        if project_settings is not None:
            route["model"], _project_payload = self.model_policy.apply_project_settings(
                route["model"], {"model": route["model"]},
                settings=project_settings, role=project_role,
            )
        operation = str(args.get("operation") or task_type).strip().lower()
        package = build_prompt(
            operation=operation,
            model=route["model"],
            role=task_type,
            profile=str(getattr(self, "config", {}).get("_hardware", {}).get("profile", "auto")),
            task=task,
            context=context,
            changed_paths=args.get("changed_paths") or (),
            evidence_ids=args.get("evidence_ids") or (),
            acceptance_criteria=args.get("acceptance_criteria") or (),
            repository_revision=str(args.get("repository_revision", "")),
            static_facts=str(args.get("static_facts", "")),
        )
        system = package.system
        trace_system = system
        # Conversation turns keep the compact transcript protocol so follow-ups
        # remain lossless; the richer static contract lives in the conversation
        # system message and one-shot operations use the full package.user form.
        prompt = self._conversation_user_prompt(task, context) if bool(args.get("conversation", False)) else package.user
        max_tokens = int(args.get("max_tokens", 4096))
        temperature = float(args.get("temperature", 0.15))
        source = f"delegate:{task_type}"
        priority = int(args.get("priority", 5))
        if bool(args.get("conversation", False)):
            if project_settings is not None:
                _conversation_model, project_payload = self.model_policy.apply_project_settings(
                    route["model"], {"model": route["model"], "system": system},
                    settings=project_settings, role=project_role,
                )
                system = str(project_payload.get("system", system))
            result = self._start_conversation(
                tenant=tenant, prompt=prompt, route=route, system=system, max_tokens=max_tokens,
                temperature=temperature, source=source, priority=priority, trace_system=trace_system,
                cancel_event=cancel_event,
            )
            return attach_project_warning(result)
        format_val = args.get("format") or args.get("json_schema")
        result = self._generate(
            route["model"], prompt, system,
            max_tokens, temperature, tenant, source, priority,
            semantic_query=task, semantic_context_fingerprint=stable_hash(context),
            format=format_val,
            project_settings=project_settings,
            project_role=project_role,
            project_config_digest=project_config_digest,
            project_namespace=project_namespace,
            repository_revision=project_revision or str(args.get("repository_revision", "")),
            use_cache=project_context is None or bool(project_namespace),
        )
        result = self._apply_semantic_quality(result, task=task, evidence_paths=args.get("changed_paths") or ())
        result["route"] = route
        return attach_project_warning(result)

    @staticmethod
    def _apply_semantic_quality(result: dict[str, Any], *, task: str, evidence_paths: Any) -> dict[str, Any]:
        """Reject obvious ungrounded model paths while keeping output advisory."""
        if not isinstance(result, dict) or not result.get("success", "error" not in result):
            return result
        paths = evidence_paths if isinstance(evidence_paths, (list, tuple, set)) else ()
        if not paths:
            return result
        quality = assess_semantic_result(task, [str(path) for path in paths], result)
        result["advisory_only"] = True
        result["semantic_quality"] = quality
        if not quality.get("usable", False):
            reason = quality.get("bypass_reason", quality.get("reason", "quality_gate"))
            result["quality_warning"] = f"advisory semantic output requires verification: {reason}"
            result["bypass_reason"] = reason
        return result

    def delegate_profile(self, args: dict[str, Any], tenant: str) -> dict[str, Any]:
        profile_name = str(args.get("profile", "")).strip()
        if not self.profile_catalog.enabled:
            return {"success": False, "unsupported": True, "error": "Ollama subagent profiles disabled"}
        try:
            available = set(str(x) for x in self.runtime.installed_models())
        except Exception:
            available = None
        try:
            profile = self.profile_catalog.resolve(profile_name, available_models=available)
        except ValueError as exc:
            return {"success": False, "unsupported": True, "error": str(exc)}

        root = str(args.get("root", "")).strip()
        task = str(args.get("task", ""))
        if root:
            if self.tool_agent is None:
                return {"success": False, "unsupported": True, "error": "read-only Ollama tool agent unavailable"}
            return self.tool_agent.run_profile(
                profile.name,
                task,
                root,
                tenant,
                workspace=args.get("workspace"),
                seed_context=str(args.get("context", "")),
                priority=int(args.get("priority", 5)),
            )

        context = str(args.get("context", ""))
        candidate = str(args.get("candidate", ""))
        package = build_prompt(
            operation=str(args.get("operation") or profile.role or "delegate"),
            model=profile.model,
            profile=str(getattr(self, "config", {}).get("_hardware", {}).get("profile", "auto")),
            task=task,
            context=context + (f"\nCANDIDATE:\n{candidate}" if candidate else ""),
        )
        result = self._generate(
            profile.model,
            package.user,
            self.profile_catalog.system_contract(profile, task, prompt=package.system),
            int(args.get("max_tokens", 0) or profile.max_tokens),
            profile.temperature,
            tenant,
            f"profile:{profile.name}",
            int(args.get("priority", 5)),
            semantic_query=task,
            semantic_context_fingerprint=stable_hash(context + candidate),
        )
        result.update({
            "profile": profile.name,
            "language": self.profile_catalog.detect_language(task),
            "advisory_only": profile.advisory_only,
            "declared_model": profile.declared_model,
            "resolved_model": profile.model,
            "model_fallback": profile.model_fallback,
            "model_fallback_reason": profile.model_fallback_reason,
            "tools_used": [],
        })
        return result

    def review(self, args: dict[str, Any], tenant: str) -> dict[str, Any]:
        if "context" in args:
            return {"success": False, "error": "review accepts code; context is not an alias"}
        code = args.get("code", "")
        instructions = args.get("instructions", "Review the supplied code or diff and report actionable defects only.")
        if not isinstance(code, str):
            return {"success": False, "error": "code must be a string"}
        if not isinstance(instructions, str):
            return {"success": False, "error": "instructions must be a string"}
        payload = {key: value for key, value in args.items() if key not in {"code", "instructions"}}
        payload["task_type"] = "review"
        payload["task"] = instructions
        payload["context"] = code
        payload["operation"] = str(args.get("operation", "review"))
        payload.setdefault("max_tokens", 4096)
        return self.delegate(payload, tenant)

    def reason(self, args: dict[str, Any], tenant: str) -> dict[str, Any]:
        if "task" in args:
            return {"success": False, "error": "reason accepts problem; task is not an alias"}
        problem = args.get("problem", "")
        if not isinstance(problem, str):
            return {"success": False, "error": "problem must be a string"}
        payload = {key: value for key, value in args.items() if key != "problem"}
        payload["task_type"] = "reasoning"
        payload["task"] = problem
        payload["operation"] = str(args.get("operation", "reason"))
        payload.setdefault("max_tokens", 4096)
        return self.delegate(payload, tenant)

    def distill_command_error(self, failure: dict[str, Any]) -> str:
        """Use the local task route only when command parsing found no coordinates."""
        summary = str(failure.get("summary", "")).strip()[:4000]
        if not summary:
            return ""
        result = self.reason({
            "problem": "Summarize this unstructured command failure in one actionable sentence. Do not invent a file, line, test, or fix.",
            "context": summary,
            "max_tokens": 120,
            "complexity": "simple",
        }, "command-error-distill")
        if not result.get("success", "error" not in result):
            return ""
        return str(result.get("text", "")).strip()[:300]

    def second_opinion(self, args: dict[str, Any], tenant: str) -> dict[str, Any]:
        question = str(args.get("question", ""))
        candidate = str(args.get("candidate", ""))
        context = str(args.get("context", ""))
        focus = str(args.get("focus", "correctness, missing assumptions, edge cases, and alternative explanations"))
        route = self.router.classify(
            f"{question}\n{focus}",
            f"{candidate}\n{context}",
            "reasoning",
            str(args.get("complexity", "auto")),
        )
        model = str(route["model"])
        package = build_prompt(
            operation="second_opinion",
            model=model,
            role="reasoning",
            profile=str(getattr(self, "config", {}).get("_hardware", {}).get("profile", "auto")),
            task=question,
            context=f"CANDIDATE ANSWER / PLAN:\n{candidate}\n\nADDITIONAL CONTEXT:\n{context}",
            changed_paths=args.get("changed_paths") or (),
            static_facts=f"FOCUS: {focus}",
        )
        result = self._generate(
            model, package.user, package.system,
            int(args.get("max_tokens", 4096)), float(args.get("temperature", 0.2)),
            tenant, "second-opinion", int(args.get("priority", 6)),
            semantic_query=f"{question}\n{focus}", semantic_context_fingerprint=stable_hash({"candidate": candidate, "context": context}),
        )
        result = self._apply_semantic_quality(result, task=question, evidence_paths=args.get("changed_paths") or ())
        result["route"] = route
        return result

    def speculative_draft(self, args: dict[str, Any], tenant: str) -> dict[str, Any]:
        """Draft code using fast model and verify against affected tests."""
        aliases = {"prompt", "path", "cwd"} & args.keys()
        if aliases:
            return {"success": False, "error": "speculative_draft rejects aliases: " + ", ".join(sorted(aliases))}
        task = args.get("task", "")
        file_path = args.get("file", "")
        context = args.get("context", "")
        root = args.get("root", ".")
        if not isinstance(task, str) or not isinstance(file_path, str) or not isinstance(context, str) or not isinstance(root, str):
            return {"success": False, "error": "task, file, context, and root must be strings"}
        resolved_root = Path(root).resolve()

        if not task:
            return {"success": False, "error": "task is required"}

        fast_model = str(self.config.get("models", {}).get("fast_code", "qwen2.5-coder:3b"))
        package = build_prompt(
            operation="speculative_draft",
            model=fast_model,
            role="code",
            profile=str(getattr(self, "config", {}).get("_hardware", {}).get("profile", "auto")),
            task=task,
            context=f"FILE: {file_path}\n\n{context}",
            changed_paths=[file_path] if file_path else (),
        )

        gen_result = self._generate(
            fast_model,
            package.user,
            package.system + " Return the minimal valid code or diff only after grounding it in the supplied file and context.",
            int(args.get("max_tokens", 2048)),
            float(args.get("temperature", 0.1)),
            tenant,
            "speculative-draft",
            priority=5,
        )

        draft_value = gen_result.get("text") or gen_result.get("response") or ""
        draft_code = draft_value.strip() if isinstance(draft_value, str) else ""
        if gen_result.get("success") is False:
            return {
                "success": False,
                "model": gen_result.get("model", fast_model),
                "draft": "",
                "verification": {"syntax_valid": False},
                "validated": False,
                "error": str(gen_result.get("error") or "Draft generation failed."),
            }
        if not draft_code:
            return {
                "success": False,
                "model": gen_result.get("model", fast_model),
                "draft": "",
                "verification": {"syntax_valid": False},
                "validated": False,
                "error": "Model returned an empty draft.",
            }
        verification: dict[str, Any] = {"syntax_valid": True}
        if file_path.endswith(".py"):
            import ast
            try:
                clean_code = re.sub(r"^```[\w]*\n", "", draft_code.strip())
                clean_code = re.sub(r"\n```$", "", clean_code)
                ast.parse(clean_code)
                verification["syntax_valid"] = True
            except Exception as e:
                verification["syntax_valid"] = False
                verification["syntax_error"] = str(e)

        if (
            bool(args.get("verify_tests", False))
            and file_path
            and self.commands
            and verification["syntax_valid"]
        ):
            aff = self.affected_tests(str(resolved_root), changed_paths=[file_path])
            if aff.get("suggested_command"):
                cmd_res = self.commands.run(aff["suggested_command"], str(resolved_root), tenant)
                verification["tests_passed"] = bool(cmd_res.get("success"))
                verification["test_summary"] = cmd_res.get("summary", "")

        if bool(args.get("smart_review", False)):
            smart_model = str(self.config.get("models", {}).get("heavy_code", "qwen2.5-coder:3b"))
            review_prompt = f"REVIEW DRAFT IMPLEMENTATION:\nTask: {task}\nDraft Code:\n{draft_code}\nDoes this draft correctly solve the task without syntax or logical bugs? Return a short JSON object: {{\"approved\": true/false, \"confidence\": 0.0-1.0, \"summary\": \"...\"}}"
            review_res = self._generate(
                smart_model,
                review_prompt,
                "You are an expert code reviewer. Return only valid JSON.",
                512,
                0.1,
                tenant,
                "speculative-review",
                priority=6,
            )
            review_text = review_res.get("text") or review_res.get("response") or ""
            verification["smart_review"] = {
                "model": smart_model,
                "response": review_text,
                "approved": "true" in review_text.lower(),
            }

        return {
            "success": True,
            "model": fast_model,
            "draft": draft_code,
            "verification": verification,
            "validated": bool(verification.get("tests_passed")) and verification["syntax_valid"],
            "duration_ms": gen_result.get("duration_ms", 0),
        }

    def speculative_lint(self, args: dict[str, Any], tenant: str) -> dict[str, Any]:
        """Run opt-in, read-only lint against only caller-supplied changed paths."""
        root = str(args.get("root", args.get("cwd", ".")))
        try:
            paths = normalize_changed_paths(root, list(args.get("paths") or []))
        except ValueError as exc:
            return {"success": False, "error": str(exc), "terminal": True, "retryable": False}
        custom = str(args.get("command", "")).strip()
        ruff_executable = shutil.which("ruff")
        lint_config = self.config.get("speculative_lint", {})
        daemon_mode = bool(lint_config.get("daemon_mode", True))
        biome_suffixes = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts", ".json", ".jsonc"}
        biome_executable = (
            shutil.which("biome")
            if not custom and all(Path(path).suffix.lower() in biome_suffixes for path in paths)
            else None
        )
        if custom:
            target_text = " ".join(subprocess.list2cmdline([path]) for path in paths) if os.name == "nt" else " ".join(shlex.quote(path) for path in paths)
            command = custom.replace("{paths}", target_text)
            if command == custom:
                command = f"{custom} {target_text}"
        elif ruff_executable and all(Path(path).suffix.lower() == ".py" for path in paths):
            target_text = " ".join(subprocess.list2cmdline([path]) for path in paths) if os.name == "nt" else " ".join(shlex.quote(path) for path in paths)
            command = f"ruff check {target_text}"
        elif biome_executable and daemon_mode:
            target_text = " ".join(subprocess.list2cmdline([path]) for path in paths) if os.name == "nt" else " ".join(shlex.quote(path) for path in paths)
            command = f"{subprocess.list2cmdline([biome_executable]) if os.name == 'nt' else shlex.quote(biome_executable)} ci {target_text}"
        elif biome_executable:
            target_text = " ".join(subprocess.list2cmdline([path]) for path in paths) if os.name == "nt" else " ".join(shlex.quote(path) for path in paths)
            command = f"{subprocess.list2cmdline([biome_executable]) if os.name == 'nt' else shlex.quote(biome_executable)} ci {target_text}"
        elif shutil.which("eslint"):
            target_text = " ".join(subprocess.list2cmdline([path]) for path in paths) if os.name == "nt" else " ".join(shlex.quote(path) for path in paths)
            command = f"eslint {target_text}"
        else:
            return {"success": False, "error": "no read-only linter found (tried ruff, biome, eslint)", "terminal": True, "retryable": False}
        lowered = command.lower()
        if any(marker in lowered for marker in ("--fix", " -w ", "autopep8", "cargo fix", "gofmt -w")):
            return {"success": False, "error": "speculative lint rejects formatter or auto-fix commands", "terminal": True, "retryable": False}
        biome_daemon = bool(not custom and biome_executable and daemon_mode)
        classification = self.commands.classify(command) if self.commands is not None else {"allowed": False, "class": "unknown"}
        if not classification.get("allowed", False) or classification.get("class") in {"mutating", "dangerous"}:
            return {"success": False, "error": "speculative lint requires an allowed read-only command", "classification": classification, "terminal": True, "retryable": False}
        if not custom and ruff_executable and all(Path(path).suffix.lower() == ".py" for path in paths) and daemon_mode:
            result = self._lint_daemons.run(
                ruff_executable, root, tenant, paths,
                timeout=float(args.get("timeout", self.config.get("speculative_lint", {}).get("timeout_seconds", 120)) or 120),
                should_stop=current_job_should_stop,
            )
            result.update({"paths": paths, "command": command})
            return result
        if biome_daemon:
            daemon_timeout = args["timeout"] if "timeout" in args else lint_config.get("timeout_seconds", 120)
            if (isinstance(daemon_timeout, bool) or not isinstance(daemon_timeout, (int, float))
                    or not math.isfinite(daemon_timeout) or daemon_timeout <= 0):
                return {"success": False, "provider": "biome", "daemon_mode": True,
                        "transport": "owned_foreground_lsp", "error": "Biome timeout must be a positive finite number",
                        "terminal": True, "retryable": False}
            result = self._biome_daemons.run(
                biome_executable, root, tenant, paths,
                timeout=daemon_timeout,
                should_stop=current_job_should_stop,
            )
            result.update({"paths": paths, "command": command})
            return result
        result = self.commands.run(
            command,
            str(Path(root).expanduser().resolve(strict=False)),
            tenant=tenant,
            timeout=int(args.get("timeout", self.config.get("speculative_lint", {}).get("timeout_seconds", 120)) or 120),
            force=True,
            auto_fix=False,
            bypass_cache=True,
        )
        result.update({"read_only": True, "auto_fix": False, "paths": paths, "command": command})
        result.update({"daemon_mode": False, "transport": "one_shot"})
        if biome_executable and not custom:
            result["provider"] = "biome"
        return result

    def close_lint_daemons(self) -> None:
        self._lint_daemons.close()
        self._biome_daemons.close()

    def task_scaffold(self, args: dict[str, Any], tenant: str) -> dict[str, Any]:
        """Generate boilerplate code, DTOs, interfaces, or unit test scaffolds using local model."""
        aliases = {"spec", "task"} & args.keys()
        if aliases:
            return {"success": False, "error": "scaffold rejects aliases: " + ", ".join(sorted(aliases))}
        spec = args.get("prompt", "")
        context = args.get("context", "")
        if not isinstance(spec, str) or not isinstance(context, str):
            return {"success": False, "error": "prompt and context must be strings"}
        language = str(args.get("language", "python"))
        max_tokens = int(args.get("max_tokens", 4096))

        if not spec:
            return {"success": False, "error": "prompt is required"}

        fast_model = str(self.config.get("models", {}).get("fast_code", "qwen2.5-coder:7b"))
        prompt = (
            f"You are a fast code scaffolder. Generate clean, idiomatic {language} code implementing the following specification:\n\n"
            f"SPECIFICATION:\n{spec}\n\n"
        )
        if context:
            prompt += f"CONTEXT / EXISTING CODE:\n{context}\n\n"
        prompt += (
            "REQUIREMENTS:\n"
            "- Emit ONLY valid code with minimal necessary docstrings.\n"
            "- Implement all requested types, data structures, constructors, and method signatures.\n"
            "- Do not include markdown conversational preamble or apologies.\n"
        )
        gen_result = self._generate(
            fast_model,
            prompt,
            "You are a precise code scaffolder. Emit only valid source code.",
            max_tokens,
            float(args.get("temperature", 0.1)),
            tenant,
            "scaffold",
            priority=5,
        )
        if gen_result.get("success") is False:
            return {
                "success": False,
                "code": "",
                "language": language,
                "model": gen_result.get("model", fast_model),
                "tokens_generated": gen_result.get("tokens", 0),
                "validated": False,
                "error": str(gen_result.get("error") or "Code generation failed."),
            }
        draft_value = gen_result.get("text") or gen_result.get("response") or ""
        draft_code = draft_value if isinstance(draft_value, str) else ""
        clean_code = re.sub(r"^```[\w]*\n", "", draft_code.strip())
        clean_code = re.sub(r"\n```$", "", clean_code)
        if not clean_code.strip():
            return {
                "success": False,
                "code": "",
                "language": language,
                "model": gen_result.get("model", fast_model),
                "tokens_generated": gen_result.get("tokens", 0),
                "validated": False,
                "error": "Model returned an empty scaffold.",
            }

        return {
            "success": True,
            "code": clean_code,
            "language": language,
            "model": gen_result.get("model", fast_model),
            "tokens_generated": gen_result.get("tokens", 0),
            "validated": False,
        }

    def vision(
        self,
        args: dict[str, Any],
        tenant: str,
        *,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Multimodal image understanding via local vision model."""
        from .vision_service import VisionService

        return VisionService(
            config=self.config,
            runtime=self.runtime,
            artifacts=self.artifacts,
            model_policy=self.model_policy,
            repo_tools=self.repo_tools,
            max_output_tokens=self._VISION_MAX_OUTPUT_TOKENS,
        ).run(args, tenant, cancel_event=cancel_event)

    def transcribe(
        self,
        args: dict[str, Any],
        tenant: str,
        *,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Transcribe audio to text through the local Whisper CLI."""
        if not isinstance(args, dict):
            return {
                "success": False,
                "audio_path": "",
                "model": "base",
                "reason": "invalid_request",
                "terminal": True,
                "retryable": False,
                "error_code": "invalid_request",
                "error": "Audio transcription request must be an object.",
            }
        import stat

        audio_path = str(args.get("audio", args.get("audio_path", "")))
        model = str(args.get("model") or "base")
        language_arg = args.get("language")
        if language_arg is not None and not isinstance(language_arg, str):
            return {
                "success": False,
                "audio_path": audio_path,
                "model": model,
                "reason": "invalid_language",
                "error": "Language hint must be a string.",
            }
        language = language_arg.strip() if isinstance(language_arg, str) else ""
        if language.casefold() == "auto":
            language = ""

        p = Path(audio_path)
        try:
            p = p.expanduser().resolve(strict=False)
            audio_stat = p.stat()
        except FileNotFoundError:
            return {
                "success": False,
                "audio_path": str(p),
                "model": model,
                "reason": "audio_not_found",
                "error": "Audio file not found.",
            }
        except OSError:
            return {
                "success": False,
                "audio_path": str(p),
                "model": model,
                "reason": "audio_unavailable",
                "degraded": True,
                "error": "Audio path is not accessible.",
            }
        except (RuntimeError, ValueError):
            return {
                "success": False,
                "audio_path": str(p),
                "model": model,
                "reason": "audio_path_invalid",
                "error": "Audio path is invalid.",
            }
        if not stat.S_ISREG(audio_stat.st_mode):
            return {
                "success": False,
                "audio_path": str(p),
                "model": model,
                "reason": "audio_not_regular_file",
                "error": "Audio path does not refer to a regular file.",
            }

        whisper_cmd = shutil.which("whisper")
        if not whisper_cmd:
            return {
                "success": False,
                "audio_path": str(p),
                "model": model,
                "engine": "whisper_cli",
                "reason": "cli_missing",
                "degraded": True,
                "error": "Whisper CLI is not installed or unavailable in PATH.",
            }

        from .whisper_policy import prepare_whisper_model

        transcription_config = self.config.get("transcription", {})
        if not isinstance(transcription_config, dict):
            transcription_config = {}
        policy = prepare_whisper_model(
            model,
            cache_dir=transcription_config.get("cache_dir"),
            allow_downloads=transcription_config.get("allow_model_downloads", False),
            device=transcription_config.get("device", "cpu"),
            cancel_event=cancel_event,
        )
        if not policy.ok:
            return {
                "success": False,
                "audio_path": str(p),
                "model": model,
                "engine": "whisper_cli",
                "reason": policy.reason or "model_unavailable",
                "degraded": policy.reason in {
                    "model_missing",
                    "model_unavailable",
                    "model_corrupt",
                    "model_too_large",
                    "model_verify_timeout",
                },
                "cancelled": policy.reason == "cancelled",
                "terminal": policy.reason != "model_verify_timeout",
                "retryable": policy.reason == "model_verify_timeout",
                "request_not_sent": True,
                "error": policy.error or "Whisper model policy rejected this request.",
            }

        from tempfile import TemporaryDirectory

        from .process_utils import ProcessCancelledError, ProcessCleanupUnverifiedError, run_hidden

        try:
            with TemporaryDirectory(prefix="local-ai-hub-transcribe-") as output_dir:
                cmd = [
                    whisper_cmd,
                    str(p),
                    "--output_format",
                    "json",
                    "--model",
                    policy.cached_model or model,
                    "--model_dir",
                    policy.model_dir,
                    "--device",
                    policy.device,
                    "--output_dir",
                    output_dir,
                ]
                if language:
                    cmd.extend(["--language", language])
                try:
                    proc = run_hidden(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=60,
                        check=False,
                        cancel_event=cancel_event,
                        cancel_grace_seconds=1.0,
                    )
                except FileNotFoundError:
                    return {
                        "success": False,
                        "audio_path": str(p),
                        "model": model,
                        "engine": "whisper_cli",
                        "reason": "cli_missing",
                        "degraded": True,
                        "error": "Whisper CLI became unavailable before it could run.",
                    }
                if proc.returncode != 0:
                    err_text = str(proc.stderr or "").strip() or f"Whisper CLI exited with status {proc.returncode}."
                    return {
                        "success": False,
                        "audio_path": str(p),
                        "model": model,
                        "engine": "whisper_cli",
                        "reason": "process_failed",
                        "returncode": proc.returncode,
                        "error": err_text,
                    }

                output_path = Path(output_dir) / f"{p.stem}.json"
                raw_output = (
                    output_path.read_text(encoding="utf-8", errors="replace")
                    if output_path.is_file()
                    else str(proc.stdout or "")
                )
                try:
                    result = json.loads(raw_output) if raw_output.strip() else {}
                except (json.JSONDecodeError, TypeError):
                    result = {}
                text_value = result.get("text") if isinstance(result, dict) else None
                transcript = text_value.strip() if isinstance(text_value, str) else ""

                def is_audio_decode_skip(value: str) -> bool:
                    return any(
                        line.startswith("Skipping ") and " due to RuntimeError:" in line
                        for line in value.splitlines()
                    )

                if (
                    is_audio_decode_skip(str(proc.stdout or ""))
                    or is_audio_decode_skip(str(proc.stderr or ""))
                    or is_audio_decode_skip(transcript)
                ):
                    return {
                        "success": False,
                        "audio_path": str(p),
                        "model": model,
                        "engine": "whisper_cli",
                        "reason": "invalid_audio",
                        "error": "Whisper CLI could not decode the audio file.",
                    }
                if not transcript:
                    return {
                        "success": False,
                        "audio_path": str(p),
                        "model": model,
                        "engine": "whisper_cli",
                        "reason": "empty_transcript",
                        "error": "Whisper CLI produced no transcript text.",
                    }

                return {
                    "success": True,
                    "text": transcript,
                    "audio_path": str(p),
                    "model": model,
                    "engine": "whisper_cli",
                }
        except ProcessCleanupUnverifiedError:
            raise
        except ProcessCancelledError:
            return {
                "success": False,
                "audio_path": str(p),
                "model": model,
                "engine": "whisper_cli",
                "reason": "cancelled",
                "cancelled": True,
                "terminal": True,
                "retryable": False,
                "error": "Whisper CLI was cancelled for resource release.",
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "audio_path": str(p),
                "model": model,
                "engine": "whisper_cli",
                "reason": "timeout",
                "retryable": True,
                "error": "Whisper CLI timed out before transcription completed.",
            }
        except Exception:
            return {
                "success": False,
                "audio_path": str(p),
                "model": model,
                "engine": "whisper_cli",
                "reason": "process_error",
                "error": "Whisper CLI failed before producing a transcript.",
            }

    def benchmark(self, tenant: str = "benchmark") -> dict[str, Any]:
        """Manual tiny benchmark used to seed the adaptive runtime cost model."""
        models=[]
        for key in ("fast_code","heavy_code","reasoning","general"):
            model=str(self.config.get("models",{}).get(key,"") or "")
            if model and model not in models: models.append(model)
        results=[]
        for model in models:
            started=time.perf_counter()
            def run(m=model):
                payload, _profile = self.model_policy.apply_payload(
                    m, {"model":m,"prompt":"Reply exactly: OK","stream":False,"keep_alive":self.config.get("ollama",{}).get("keep_alive","-1"),"options":{"num_predict":8,"temperature":0}},
                    role="benchmark", input_tokens=4, output_tokens=8, preserve_explicit_think=False,
                )
                return self.runtime.request("/api/generate", payload)
            try:
                raw=self.scheduler.submit(model, tenant, "benchmark", run, priority=2, wait_timeout=float(self.config.get("resilience",{}).get("scheduler_wait_timeout_seconds",330)))
            except Exception as exc:
                raw={"error":str(exc)}
            elapsed=(time.perf_counter()-started)*1000
            success="error" not in raw
            if success and self.tuner is not None:
                try: self.tuner.observe(model, raw, elapsed)
                except Exception: pass
            results.append({"model":model,"success":success,"elapsed_ms":round(elapsed,1),"load_ms":round(float(raw.get("load_duration",0) or 0)/1e6,1),"eval_count":int(raw.get("eval_count",0) or 0)})
        return {"success":all(x["success"] for x in results),"results":results,"autotune":self.tuner.stats() if self.tuner is not None else {"enabled":False}}

    def evaluation(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action", "report")).strip().lower()
        if action == "record":
            try:
                duration_ms = float(payload.get("duration_ms", 0) or 0)
            except (TypeError, ValueError):
                return {"success": False, "error": "duration_ms must be numeric", "terminal": True}
            return self.telemetry.record_evaluation(
                task_id=str(payload.get("task_id", "")),
                cohort=str(payload.get("cohort", "")),
                quality_pass=payload.get("quality_pass"),
                test_pass=payload.get("test_pass"),
                duration_ms=duration_ms,
            )
        if action == "report":
            try:
                days = max(1, min(int(payload.get("days", 30) or 30), self.telemetry.rollup_retention_days))
            except (TypeError, ValueError):
                return {"success": False, "error": "days must be an integer", "terminal": True}
            return {"success": True, "evaluation": self.telemetry.report(days).get("evaluation", {})}
        return {"success": False, "error": "unknown evaluation action", "terminal": True}



    @staticmethod
    def _embedding_key(text: str, *, backend: str, model: str, query: bool) -> str:
        return stable_hash({
            "kind": "embedding",
            "backend": backend,
            "model": model,
            "query": bool(query),
            "text": str(text),
            "app_version": __version__,
        })

    @staticmethod
    def _json_embedding(vector: Any) -> list[float]:
        if hasattr(vector, "tolist"):
            vector = vector.tolist()
        return [float(value) for value in vector]

    def embed(self, texts: list[str], tenant: str, priority: int = 3, query: bool = False, background: bool | None = None, wait_timeout: float | None = None) -> dict[str, Any]:
        backend = self.config["models"].get("embedding_backend", "sentence-transformers")
        model = str(self.config.get("models", {}).get("embedding", "qwen3-embedding:0.6b"))
        if not texts:
            return {"success": True, "model": model, "backend": "ollama", "embeddings": []}

        def encode_uncached(batch: list[str]) -> dict[str, Any]:
            if backend in {"sentence-transformers", "openvino"}:
                return self.embeddings.encode(batch, query=query, priority=priority)
            batch_size = int(self.config.get("rag", {}).get("embedding_batch_size", 12))

            def run() -> dict[str, Any]:
                all_vectors: list[list[float]] = []
                for start in range(0, len(batch), batch_size):
                    response = self.runtime.request("/api/embed", {"model": model, "input": batch[start:start + batch_size]})
                    if "error" in response:
                        return {"success": False, "error": response["error"], "model": model}
                    all_vectors.extend(response.get("embeddings", []))
                return {"success": True, "model": model, "backend": "ollama", "embeddings": all_vectors}

            is_bg = background if background is not None else (priority <= 1)
            return self.scheduler.submit(model, tenant, "embed", run, priority=priority, background=is_bg, wait_timeout=wait_timeout)

        cache = getattr(self, "embedding_cache", None)
        cache_enabled = bool(getattr(self, "embedding_cache_enabled", self.config.get("cache", {}).get("embeddings", True)))
        if not cache_enabled or cache is None:
            return encode_uncached(list(texts))

        keys = [self._embedding_key(text, backend=backend, model=model, query=query) for text in texts]
        vectors: list[list[float] | None] = [None] * len(texts)
        missing: dict[str, list[int]] = {}
        for index, key in enumerate(keys):
            cached = cache.get(key)
            if isinstance(cached, list):
                vectors[index] = [float(value) for value in cached]
            else:
                missing.setdefault(key, []).append(index)

        if missing:
            missing_indices = [indices[0] for indices in missing.values()]
            result = encode_uncached([texts[index] for index in missing_indices])
            if not isinstance(result, dict) or not result.get("success"):
                return result if isinstance(result, dict) else {"success": False, "error": "embedding failed"}
            raw_vectors = result.get("embeddings", [])
            if len(raw_vectors) != len(missing_indices):
                return {"success": False, "error": f"embedding count mismatch: {len(raw_vectors)} != {len(missing_indices)}"}
            for vector, key, indices in zip(raw_vectors, missing, missing.values()):
                normalized = self._json_embedding(vector)
                cache.set(key, normalized)
                for index in indices:
                    vectors[index] = normalized
            result = dict(result)
            result["embeddings"] = vectors
            return result

        return {"success": True, "model": model, "backend": backend, "embeddings": vectors}

    def _repo_cached(self, operation: str, root: str, params: dict[str, Any], compute: Any) -> dict[str, Any]:
        # Worktrees/temp repositories can disappear between an agent request and a
        # coalesced background computation. Treat that as a stale input, not a hub 500.
        try:
            self._touch_project(root)
            state = self._repo_cache_state(root) or {}
            fingerprint = state.get("fingerprint")
            if not isinstance(fingerprint, str) or not fingerprint.strip():
                raw = compute()
                hit = coalesced = False
                cache_degraded = True
                cache_reason = "missing_or_invalid_fingerprint"
            else:
                # Physical-root identity isolates clean clones with otherwise
                # identical fingerprints while collapsing lexical aliases.
                key = stable_hash({
                    "op": operation,
                    "root": canonical_root(root),
                    "state": fingerprint,
                    "params": params,
                })
                raw, hit, coalesced = self.repo_flight.get_or_compute(key, compute)
                cache_degraded = bool(state.get("degraded", False))
                cache_reason = state.get("degraded_reason")
        except (FileNotFoundError, ValueError) as exc:
            return {"success": False, "stale_root": True, "error": str(exc), "error_type": type(exc).__name__, "operation": operation}
        if isinstance(raw, dict):
            result = copy.deepcopy(raw)
        elif raw is not None:
            result = {"result": raw, "success": True}
        else:
            result = {"success": False, "error": f"{operation} computation failed"}
        result["workspace_cache"] = {
            "hit": bool(hit), "coalesced": bool(coalesced), "operation": operation,
            "fingerprint": state.get("fingerprint"), "kind": state.get("kind"),
            "degraded": cache_degraded, "reason": cache_reason,
            "stale": bool(state.get("stale", False)),
        }
        # Promote mechanical cache reuse to the common HTTP contract. This lets
        # clients reuse repository answers and makes endpoint cache hit telemetry
        # comparable with generation cache telemetry.
        result["cache_hit"] = bool(hit)
        result["coalesced"] = bool(coalesced)
        result["cache_layer"] = "workspace" if hit else "workspace-miss"
        if isinstance(raw, dict) and "preprocessed_hit" in raw:
            result["preprocessed_hit"] = bool(raw["preprocessed_hit"])
        return result

    def repo_profile(self, root: str) -> dict[str, Any]:
        return self._repo_cached("profile", root, {}, lambda: self.repo_tools.project_profile(root))

    def repo_search(
        self,
        root: str,
        query: str,
        top_k: int = 12,
        context_lines: int | None = None,
        enrich: bool = False,
        path_hints: list[Any] | tuple[Any, ...] | None = None,
        scope: str = "repo_search",
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        page_limit = max(1, int(top_k)) if limit is None else limit
        bounds_error = pagination_bounds_error(page_limit, offset)
        if bounds_error:
            return {
                "success": False,
                "error": bounds_error,
                "status_code": 400,
                "root": root,
                "results": [],
                "total_matches": 0,
                "has_more": False,
                "limit": page_limit if isinstance(page_limit, int) and not isinstance(page_limit, bool) and 1 <= page_limit <= MAX_PAGE_SIZE else None,
                "offset": offset if isinstance(offset, int) and not isinstance(offset, bool) and 0 <= offset < MAX_PAGE_WINDOW else None,
            }
        if enrich and not rollout_feature_enabled(self.config, "enriched_search"):
            return {
                "success": False,
                "unsupported": True,
                "feature": "enriched_search",
                "error": "enriched search is disabled (features.enriched_search=false)",
            }
        # Search itself is case-insensitive and whitespace-tolerant. Use the same
        # canonical form for cache identity so equivalent agent queries reuse work.
        query = normalize_query(query).casefold()
        eff_ctx_lines = int(context_lines) if context_lines is not None else (8 if enrich else None)
        from .project_config import (
            PathHint,
            ProjectConfigError,
            path_is_allowed,
            path_matches_pattern,
            prioritize_paths_with_hints,
            resolve_project_context,
            validate_path_hint,
        )

        try:
            project_context = resolve_project_context(
                root,
                configured_state_dir(getattr(self, "config", {}), create=False),
            )
        except ProjectConfigError as exc:
            return {
                "success": False,
                "root": root,
                "error": f"project configuration is invalid: {exc}",
                "terminal": True,
                "retryable": False,
            }
        if project_context.resolution.error_codes:
            return {
                "success": False,
                "root": root,
                "error": "project_policy_unavailable",
                "results": [],
                "terminal": True,
                "retryable": False,
            }
        try:
            hint_root = Path(root).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            hint_root = None
        # Exact pagination streams Git paths in RepositoryTools. Do not prebuild
        # a repository-sized inventory here; directory hints are ranked by root.
        file_inventory = None
        search_scope = scope if isinstance(scope, str) else "repository_search"
        page_limit = top_k if limit is None else limit
        bounds_error = pagination_bounds_error(page_limit, offset)
        if bounds_error:
            return {"success": False, "error": bounds_error, "status_code": 400,
                    "limit": page_limit if isinstance(page_limit, int) and not isinstance(page_limit, bool) and 1 <= page_limit <= MAX_PAGE_SIZE else None,
                    "offset": offset if isinstance(offset, int) and not isinstance(offset, bool) and 0 <= offset < MAX_PAGE_WINDOW else None,
                    "total_matches": 0, "has_more": False, "results": []}
        request_hints: list[PathHint] = []
        allowed_hint_fields = {
            "path", "purpose", "scope", "evidence_id", "provenance",
            "repository_revision", "config_digest", "expires_at",
        }
        if isinstance(path_hints, (list, tuple)):
            for item in path_hints[:64]:
                if isinstance(item, PathHint):
                    hint = item
                elif isinstance(item, dict) and not (set(item) - allowed_hint_fields):
                    try:
                        hint = PathHint(**item)
                    except TypeError:
                        continue
                else:
                    continue
                if (
                    isinstance(hint.path, str)
                    and isinstance(hint.purpose, str)
                    and isinstance(hint.scope, str)
                    and all(
                        value is None or isinstance(value, str)
                        for value in (
                            hint.evidence_id, hint.provenance,
                            hint.repository_revision, hint.config_digest,
                            hint.expires_at,
                        )
                    )
                ):
                    request_hints.append(hint)
        try:
            workspace_state = self._repo_cache_state(root) or {}
        except Exception:
            workspace_state = {}
        repository_revision = (
            str(workspace_state.get("fingerprint") or "")
            if not workspace_state.get("stale") and not workspace_state.get("degraded")
            else ""
        )
        saved_hints = project_context.path_hints(
            purpose="repository_search",
            scope=search_scope,
            repository_revision=repository_revision,
        )
        effective_hints = [*saved_hints, *request_hints]
        request_hint_digest = stable_hash([
            {
                "path": hint.path,
                "purpose": hint.purpose,
                "scope": hint.scope,
                "evidence_id": hint.evidence_id,
                "provenance": hint.provenance,
                "repository_revision": hint.repository_revision,
                "config_digest": hint.config_digest,
                "expires_at": hint.expires_at,
            }
            for hint in effective_hints
        ])
        if self.learner is not None:
            try: self.learner.record(root, query)
            except Exception: pass
        # Local AI deterministic facts/symbols are the cheapest candidate source.
        paths: list[str] = []
        if self.deterministic is not None:
            try: paths.extend(self.deterministic.related_paths(root, query, max(16, top_k * 3)))
            except (OSError, sqlite3.Error, ValueError) as candidate_exc:
                logger.debug(
                    "Deterministic candidate search skipped (%s)",
                    type(candidate_exc).__name__,
                )
        if self.code_index is not None:
            try:
                for p in self.code_index.related_paths(root, query, max(16, top_k * 3)):
                    if p not in paths: paths.append(p)
            except (OSError, sqlite3.Error, ValueError) as candidate_exc:
                logger.debug(
                    "CodeIndex candidate search skipped (%s)",
                    type(candidate_exc).__name__,
                )
        # Warm preprocessing maintains FTS + semantic cards specifically so agents do
        # not need broad scans. Treat these only as candidates; exact source search
        # remains the fallback when a card/FTS hint produces no matches.
        if self.preprocessor is not None:
            try:
                for p in self.preprocessor.candidate_paths(root, query, max(16, top_k * 3)):
                    if p not in paths:
                        paths.append(p)
            except (OSError, sqlite3.Error, ValueError) as candidate_exc:
                logger.debug(
                    "Preprocessor candidate search skipped (%s)",
                    type(candidate_exc).__name__,
                )
        hinted_search_paths: list[str] = []
        hinted_force_include = False
        force_include_patterns = tuple(project_context.settings.force_include_paths) + tuple(
            pattern
            for pattern, action in project_context.settings.path_overrides.items()
            if action == "include"
        )
        try:
            extension_is_searchable = getattr(
                self.repo_tools, "_path_extension_is_searchable", None
            )
            ignored_dirs = getattr(self.repo_tools, "ignore_dirs", set())
            seen_hint_paths: set[str] = set()
            for hint in effective_hints:
                target = validate_path_hint(
                    hint_root,
                    hint,
                    purpose="repository_search",
                    scope=search_scope,
                    repository_revision=repository_revision,
                    config_digest=project_context.config_digest,
                    learned=bool(hint.evidence_id),
                )
                if target is None:
                    continue
                if target.is_file():
                    candidates = (target,)
                elif target.is_dir():
                    if file_inventory is None:
                        inventory_loader = getattr(self.repo_tools, "_git_files", None)
                        if hint_root is not None and callable(inventory_loader):
                            file_inventory = inventory_loader(hint_root)
                    if file_inventory is not None:
                        def under_hint_directory():
                            for raw_candidate in file_inventory:
                                try:
                                    candidate = Path(raw_candidate).resolve(strict=False)
                                    candidate.relative_to(hint_root)
                                except (OSError, RuntimeError, ValueError):
                                    continue
                                if candidate == target or target in candidate.parents:
                                    yield candidate
                        candidates = under_hint_directory()
                    else:
                        def walk_hint_directory():
                            count = 0
                            for item in target.rglob("*"):
                                if item.is_file():
                                    yield item
                                    count += 1
                                    if count >= 64:
                                        break
                        candidates = walk_hint_directory()
                for candidate in candidates:
                    try:
                        relative_path = candidate.relative_to(hint_root)
                        relative = relative_path.as_posix()
                        size_bytes = candidate.stat().st_size
                    except (OSError, RuntimeError, ValueError):
                        continue
                    if callable(extension_is_searchable) and not extension_is_searchable(
                        candidate, project_settings=project_context.settings,
                    ):
                        continue
                    soft_ignored = any(
                        part.lower() in ignored_dirs for part in relative_path.parts[:-1]
                    )
                    if not path_is_allowed(
                        hint_root,
                        candidate,
                        project_context.settings,
                        phase="search",
                        soft_ignored=soft_ignored,
                        size_bytes=size_bytes,
                    ):
                        continue
                    hinted_force_include = hinted_force_include or soft_ignored
                    if relative not in seen_hint_paths:
                        hinted_search_paths.append(relative)
                        seen_hint_paths.add(relative)
                    if len(hinted_search_paths) >= 64:
                        break
                if len(hinted_search_paths) >= 64:
                    break
        except (KeyError, OSError, RuntimeError, TypeError, ValueError):
            # Hints enrich bounded targeted search; invalid policy never blocks normal search.
            hinted_search_paths = []
            hinted_force_include = False
        paths = list(dict.fromkeys([*hinted_search_paths, *paths]))

        def compute() -> dict[str, Any]:
            override_patterns = tuple(
                pattern
                for pattern, action in project_context.settings.path_overrides.items()
                if action == "include"
            )

            def matching_hint_roots(hints: list[PathHint], *, learned: bool) -> tuple[Path, ...]:
                if hint_root is None:
                    return ()
                roots: list[Path] = []
                for hint in hints:
                    target = validate_path_hint(
                        hint_root,
                        hint,
                        purpose="repository_search",
                        scope=search_scope,
                        repository_revision=repository_revision,
                        config_digest=project_context.config_digest,
                        learned=learned,
                    )
                    if target is not None:
                        roots.append(target)
                return tuple(roots)

            configured_hints = [
                PathHint(path=path, purpose="repository_search", scope=search_scope)
                for path in project_context.settings.entry_points
            ]
            # Saved hints are validated in the learned mode used by
            # ProjectContext.prioritize_paths; configured entry points are not.
            durable_hint_roots = (
                *matching_hint_roots(saved_hints, learned=True),
                *matching_hint_roots(configured_hints, learned=False),
            )
            request_hint_roots = matching_hint_roots(request_hints, learned=False)

            source_focused = _source_focused_query(query)

            def path_priority(relative: str) -> tuple[int, int, int]:
                candidate = (hint_root / relative).resolve(strict=False) if hint_root else None

                def matches(roots: tuple[Path, ...]) -> bool:
                    return bool(candidate and any(
                        candidate == root or root in candidate.parents for root in roots
                    ))

                override_match = any(
                    path_matches_pattern(relative, pattern) for pattern in override_patterns
                )
                return (
                    0 if matches(request_hint_roots) else 1,
                    0 if matches(durable_hint_roots) else 1,
                    _context_path_priority(
                        relative,
                        source_focused=source_focused,
                        override_match=override_match,
                    ),
                )

            full_result = self.repo_tools.search(
                root, query, context_lines=eff_ctx_lines,
                project_settings=project_context.settings,
                git_inventory=file_inventory,
                limit=page_limit,
                offset=offset,
                exact_count=True,
                force_include_paths=list(force_include_patterns),
                path_priority=path_priority,
            )
            if not isinstance(full_result, dict) or not full_result.get("success", True):
                result = dict(full_result) if isinstance(full_result, dict) else {
                    "success": False, "error": "repository search failed"
                }
                result["preprocessed_hit"] = False
                return result

            combined: list[dict[str, Any]] = []
            seen_hits: set[tuple[str, int]] = set()
            for source in (full_result,):
                source_hits = source.get("results", []) if isinstance(source, dict) else []
                if not isinstance(source_hits, list):
                    continue
                for item in source_hits:
                    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                        continue
                    try:
                        line_number = int(item.get("start_line", 0) or 0)
                    except (TypeError, ValueError):
                        line_number = 0
                    key = (item["path"], line_number)
                    if key not in seen_hits:
                        combined.append(dict(item))
                        seen_hits.add(key)

            base = Path(root).expanduser().resolve(strict=True)
            allowed_results: list[dict[str, Any]] = []
            extension_is_searchable = getattr(
                self.repo_tools, "_path_extension_is_searchable", None
            )
            for item in combined:
                relative = str(item.get("path") or "").replace("\\", "/")
                if not relative:
                    continue
                target = (base / relative).resolve(strict=False)
                try:
                    target.relative_to(base)
                    size_bytes = target.stat().st_size
                except (OSError, RuntimeError, ValueError):
                    continue
                if callable(extension_is_searchable) and not extension_is_searchable(
                    target, project_settings=project_context.settings,
                ):
                    continue
                if not path_is_allowed(
                    base,
                    target,
                    project_context.settings,
                    phase="search",
                    hard_denied=bool(item.get("hard_denied", False)),
                    binary=bool(item.get("binary", False)),
                    size_bytes=size_bytes,
                ):
                    continue
                item["path"] = target.relative_to(base).as_posix()
                allowed_results.append(item)

            override_patterns = tuple(
                pattern
                for pattern, action in project_context.settings.path_overrides.items()
                if action == "include"
            )
            override_order = sorted(
                allowed_results,
                key=lambda item: not any(
                    path_matches_pattern(str(item["path"]), pattern)
                    for pattern in override_patterns
                ),
            )
            candidate_paths = [str(item["path"]) for item in override_order]
            configured_usage = project_context.prioritize_paths(
                candidate_paths,
                purpose="repository_search",
                scope=search_scope,
                repository_revision=repository_revision,
                path_hints=(),
            )
            request_usage = prioritize_paths_with_hints(
                base,
                configured_usage.paths,
                request_hints,
                purpose="repository_search",
                scope=search_scope,
                repository_revision=repository_revision,
                config_digest=project_context.config_digest,
            )
            hint_used = configured_usage.hint_used or request_usage.hint_used
            hint_fallback_used = (
                configured_usage.fallback_used or request_usage.fallback_used
            ) and not hint_used
            path_rank = {path: rank for rank, path in enumerate(request_usage.paths)}
            allowed_results.sort(
                key=lambda item: path_rank.get(str(item["path"]), len(path_rank))
            )
            result = dict(full_result)
            count_is_exact = (
                full_result.get("count_exact") is True
                and isinstance(full_result.get("total_matches"), int)
                and not isinstance(full_result.get("total_matches"), bool)
            )
            if not count_is_exact:
                return {
                    "success": False,
                    "error": "repository search could not produce an exact match count",
                    "status_code": 503,
                    "preprocessed_hit": False,
                    "results": [],
                }
            total_matches = int(full_result["total_matches"])
            source_page = full_result.get("results", [])
            if not isinstance(source_page, list) or len(allowed_results) != len(source_page):
                return {
                    "success": False,
                    "error": "repository search filters disagreed while materializing the exact page",
                    "status_code": 503,
                    "preprocessed_hit": False,
                    "results": [],
                }
            result["total_matches"] = total_matches
            result["matches_count"] = total_matches
            result["count_exact"] = count_is_exact
            result["offset"] = offset
            result["limit"] = page_limit
            page_results = allowed_results
            result["results"] = page_results
            result["has_more"] = (
                offset + len(page_results) < total_matches
                if count_is_exact
                else True if offset + len(page_results) < len(allowed_results) else None
            )
            result["truncated"] = False
            result["preprocessed_hit"] = bool(
                paths
                and any(str(item.get("path")) in set(paths) for item in allowed_results)
            )
            result["path_hint_usage"] = {
                "hint_used": hint_used,
                "fallback_used": hint_fallback_used,
                "hint_helped": None,
            }
            if enrich:
                result["enriched"] = True
                for hit in result.get("results", []):
                    rel = str(hit.get("path") or "")
                    target = (base / rel).resolve()
                    try:
                        target.relative_to(base)
                        if target.is_file() and target.stat().st_size <= 512_000:
                            symbol = enclosing_symbol_at_line(
                                target.read_text(encoding="utf-8", errors="replace"), rel,
                                int(hit.get("start_line", 0) or 0),
                            )
                            if symbol:
                                hit["enclosing_symbol"] = symbol
                    except (OSError, ValueError):
                        continue
            # Exact search snippets become immutable evidence so agent projections can
            # send coordinates first and raw source only for the top few hits.
            if self.evidence_store is not None and isinstance(result.get("results"), list):
                try:
                    result = dict(result)
                    stored_results = self.evidence_store.put_many(
                        str(result.get("root", root)), result["results"]
                    )
                    receipts_complete = all(
                        isinstance(item, dict)
                        and (
                            not any(item.get(field) for field in ("text", "raw", "content"))
                            or bool(item.get("evidence_id"))
                        )
                        for item in stored_results
                    )
                    result["results"] = stored_results
                    result["progressive_disclosure"] = receipts_complete
                except (OSError, sqlite3.Error, ValueError) as store_exc:
                    logger.debug(
                        "Repository search evidence persistence skipped (%s)",
                        type(store_exc).__name__,
                    )
                    result = dict(result)
                    result["progressive_disclosure"] = False
            return result
        return self._repo_cached(
            "search",
            root,
            {
                "query": query,
                "top_k": top_k,
                "limit": page_limit,
                "offset": offset,
                "ci": paths[:24],
                "ctx": eff_ctx_lines,
                "scope": search_scope,
                "config_digest": project_context.config_digest,
                "path_hints_digest": request_hint_digest,
            },
            compute,
        )

    def _refresh_changed_intelligence(self, root: str) -> None:
        """Synchronize only Git-changed files before serving a cache-miss intelligence query.

        Preprocessing remains the bulk indexer. This foreground safety net prevents a
        just-edited file from forcing a full rebuild or returning stale deterministic
        facts while the background pipeline is still catching up.
        """
        try:
            state = self._repo_cache_state(root)
            # Background preprocessing owns incremental index updates while active.
            # Do not duplicate that work synchronously inside a foreground query;
            # the durable index is safer than making the feature wait on a large batch.
            if state.get("kind") == "preprocessed-watcher":
                return
            fp = str(state.get("fingerprint") or "")
            base = Path(root).expanduser().resolve()
            root_key = str(base)
            with self._index_refresh_lock:
                if fp and self._index_refresh_state.get(root_key) == fp:
                    return
            paths = [str(x) for x in state.get("changed_paths", [])][:256]
            if not paths:
                with self._index_refresh_lock:
                    if fp:
                        self._index_refresh_state[root_key] = fp
                return
            existing: list[tuple[str, str]] = []
            missing: list[str] = []
            for rel in paths:
                try:
                    target = (base / rel).resolve(strict=False)
                    target.relative_to(base)
                except (OSError, RuntimeError, ValueError) as path_exc:
                    logger.debug(
                        "Changed-file path skipped (%s)",
                        type(path_exc).__name__,
                    )
                    continue
                if target.is_file():
                    try:
                        existing.append((rel, self.repo_tools._hash_file_only(target)))
                    except (OSError, ValueError) as hash_exc:
                        logger.debug(
                            "Changed-file hash skipped (%s)",
                            type(hash_exc).__name__,
                        )
                else:
                    missing.append(rel)
            if self.code_index is not None:
                if existing and hasattr(self.code_index, "update_files_batch"):
                    self.code_index.update_files_batch(str(base), existing)
                for rel in missing:
                    try:
                        self.code_index.update_file(str(base), rel)
                    except (OSError, sqlite3.Error, ValueError) as index_exc:
                        logger.debug(
                            "CodeIndex changed-file update skipped (%s)",
                            type(index_exc).__name__,
                        )
            if self.deterministic is not None:
                if existing and hasattr(self.deterministic, "update_files_batch"):
                    self.deterministic.update_files_batch(str(base), existing)
                for rel in missing:
                    try:
                        self.deterministic.update_file(str(base), rel)
                    except (OSError, sqlite3.Error, ValueError) as index_exc:
                        logger.debug(
                            "Deterministic changed-file update skipped (%s)",
                            type(index_exc).__name__,
                        )
            with self._index_refresh_lock:
                if fp:
                    self._index_refresh_state[root_key] = fp
                    if len(self._index_refresh_state) > 256:
                        self._index_refresh_state.pop(next(iter(self._index_refresh_state)), None)
        except (OSError, sqlite3.Error, ValueError) as refresh_exc:
            # Query correctness still falls back to the last durable index plus exact
            # lexical/source tools; this accelerator must never turn a query into 500.
            logger.debug(
                "Changed-file intelligence refresh skipped (%s)",
                type(refresh_exc).__name__,
            )
            return

    def deterministic_query(self, root: str, query: str, limit: int = 24) -> dict[str, Any]:
        if self.deterministic is None:
            return {"success": False, "error": "deterministic engine unavailable", "confidence": 0.0}
        if self.learner is not None:
            try: self.learner.record(root, query)
            except Exception: pass
        try:
            canonical = {
                "intent": self.deterministic.classify_intent(query).get("intent", "general"),
                "terms": sorted(set(self.deterministic._terms(query))),
                "limit": limit,
            }
        except Exception:
            canonical = {"query": " ".join(query.lower().split()), "limit": limit}
        def compute() -> dict[str, Any]:
            self._refresh_changed_intelligence(root)
            return self.deterministic.query(root, query, limit)
        return self._repo_cached("deterministic", root, canonical, compute)

    def code_query(self, root: str, query: str, limit: int = 24, include_code: bool = False, offset: int = 0) -> dict[str, Any]:
        bounds_error = pagination_bounds_error(limit, offset)
        if bounds_error:
            return {"success": False, "error": bounds_error, "status_code": 400,
                    "limit": limit if isinstance(limit, int) and not isinstance(limit, bool) and 1 <= limit <= MAX_PAGE_SIZE else None,
                    "offset": offset if isinstance(offset, int) and not isinstance(offset, bool) and 0 <= offset < MAX_PAGE_WINDOW else None,
                    "total_matches": 0, "has_more": False, "symbols": []}
        if self.code_index is None:
            return {"success": False, "error": "code index unavailable", "status_code": 503, "limit": limit, "offset": offset, "total_matches": 0, "has_more": False, "symbols": []}
        if self.learner is not None:
            try: self.learner.record(root, query)
            except Exception: pass
        try:
            # Exact identifier lookup differs from a token-equivalent fuzzy
            # query (generate_tests versus generate tests).
            canonical = {"query": query, "terms": sorted(set(self.code_index._query_terms(query))), "limit": limit, "offset": offset, "include_code": include_code}
        except Exception:
            canonical = {"query": " ".join(query.lower().split()), "limit": limit, "offset": offset, "include_code": include_code}
        def compute() -> dict[str, Any]:
            self._refresh_changed_intelligence(root)
            res = self.code_index.query(root, query, limit=limit, offset=offset)
            if isinstance(res, dict):
                res["preprocessed_hit"] = bool(res.get("success") and res.get("symbols"))
                if include_code and res.get("symbols") and self.repo_tools is not None:
                    for sym in res["symbols"][:5]:
                        fp = sym.get("file") or sym.get("path")
                        sl = int(sym.get("line") or 1)
                        el = int(sym.get("end_line") or (sl + 30))
                        if fp:
                            slice_res = self.repo_tools.file_slice(root, fp, start_line=sl, end_line=min(el, sl + 60), max_chars=2500)
                            if slice_res.get("success"):
                                sym["code"] = slice_res.get("text")
            return res
        return self._repo_cached("code-index", root, canonical, compute)

    def repo_investigate(
        self,
        root: str,
        query: str,
        path: str = "",
        include_code: bool = True,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Single-roundtrip smart investigation for cloud models."""
        cq_res = self.code_query(root, query, limit=limit, include_code=include_code)
        symbols = cq_res.get("symbols", []) if isinstance(cq_res, dict) else []

        search_hits = []
        if len(symbols) < 2:
            s_res = self.repo_search(root, query, top_k=limit)
            if isinstance(s_res, dict):
                search_hits = s_res.get("results", []) or s_res.get("hits", [])
                if include_code and self.repo_tools is not None:
                    for hit in search_hits[:3]:
                        h_path = hit.get("path") or hit.get("file")
                        h_line = int(hit.get("line") or 1)
                        if h_path:
                            sl_res = self.repo_tools.file_slice(root, h_path, start_line=max(1, h_line - 5), end_line=h_line + 30, max_chars=2000)
                            if sl_res.get("success"):
                                hit["code"] = sl_res.get("text")

        primary_sym = symbols[0].get("name", "") if symbols else (search_hits[0].get("name", "") if search_hits else query)
        callers: list[dict[str, Any]] = []
        if primary_sym and self.code_index is not None:
            try:
                ref_res = self.code_index.find_referencing_symbols(root, primary_sym)
                if isinstance(ref_res, dict) and ref_res.get("success"):
                    callers = ref_res.get("references", [])[:10]
            except (OSError, sqlite3.Error, ValueError) as reference_exc:
                logger.debug(
                    "Repository investigation references skipped (%s)",
                    type(reference_exc).__name__,
                )

        related_tests: list[str] = []
        try:
            target_files = [s.get("file") for s in symbols if s.get("file")]
            if target_files:
                aff_res = self.affected_tests(root, changed_paths=target_files)
                if isinstance(aff_res, dict):
                    related_tests = aff_res.get("test_files", [])[:5]
        except (OSError, sqlite3.Error, ValueError) as tests_exc:
            logger.debug(
                "Related test lookup skipped (%s)",
                type(tests_exc).__name__,
            )

        return {
            "success": True,
            "query": query,
            "root": root,
            "primary_symbol": primary_sym,
            "symbols": symbols[:limit],
            "search_hits": search_hits[:limit] if not symbols else [],
            "callers": callers[:10],
            "related_tests": related_tests,
            "cascade_layers": ["code_index", "tests"] if symbols else ["search", "tests"],
        }

    def repo_diagnose(self, root: str, text: str) -> dict[str, Any]:
        """Parse stack traces / crash logs and fetch inline code snippets for each frame."""
        resolved_root = canonical_root(root)
        if not Path(resolved_root).is_dir():
            return {"success": False, "error": "Root directory does not exist"}

        if not text or not text.strip():
            return {"success": False, "error": "No traceback or error log text provided"}

        py_pat = re.compile(r'File "(?P<file>[^"]+)", line (?P<line>\d+)(?:, in (?P<func>\w+))?')
        js_pat = re.compile(r'at\s+(?:(?P<func>[^\s(]+)\s+\()?(?P<file>[^:()\s]+):(?P<line>\d+):(?P<col>\d+)\)?')
        cs_pat = re.compile(r'at\s+(?P<func>[^\s]+)\s+in\s+(?P<file>[^:]+):line\s+(?P<line>\d+)')
        go_pat = re.compile(r'(?P<file>[^\s:]+\.go):(?P<line>\d+)(?:\s+\+0x[0-9a-f]+)?')
        rs_pat = re.compile(r'at\s+(?P<file>[^:]+\.rs):(?P<line>\d+):(?P<col>\d+)')
        gen_pat = re.compile(r'(?P<file>[a-zA-Z0-9_./\\-]+\.[a-zA-Z0-9_]+):(?P<line>\d+)')

        raw_frames: list[dict[str, Any]] = []
        lines = text.splitlines()

        error_type = ""
        error_message = ""
        for line in reversed(lines):
            line_str = line.strip()
            if not line_str:
                continue
            err_m = re.search(r'\b(?P<type>[A-Z][A-Za-z0-9_]*(?:Error|Exception|Panic|Failure))\s*:\s*(?P<msg>.*)', line_str)
            if err_m:
                error_type = err_m.group("type")
                error_message = err_m.group("msg").strip()
                break
            if line_str.startswith("AssertionError") or line_str.startswith("FAILED") or line_str.startswith("panic:"):
                parts = line_str.split(":", 1)
                error_type = parts[0].strip()
                error_message = parts[1].strip() if len(parts) > 1 else ""
                break

        for line in lines:
            m = py_pat.search(line) or js_pat.search(line) or cs_pat.search(line) or rs_pat.search(line) or go_pat.search(line) or gen_pat.search(line)
            if m:
                d = m.groupdict()
                raw_frames.append({
                    "file": d.get("file", "").replace("\\", "/").strip(),
                    "line": int(d.get("line", 1)),
                    "function": d.get("func", ""),
                })

        base_path = Path(resolved_root)
        processed_frames: list[dict[str, Any]] = []
        seen = set()

        for f in raw_frames:
            f_str = f["file"]
            ln = f["line"]
            target = (base_path / f_str).resolve(strict=False)
            if not target.is_file() and Path(f_str).is_file():
                target = Path(f_str).resolve(strict=False)

            try:
                rel = target.relative_to(base_path).as_posix()
            except ValueError:
                rel = f_str

            key = (rel, ln)
            if key in seen:
                continue
            seen.add(key)

            snippet = ""
            if target.is_file():
                slice_res = self.repo_tools.file_slice(resolved_root, rel, start_line=max(1, ln - 4), end_line=ln + 4, max_chars=1200)
                if slice_res.get("success"):
                    snippet = slice_res.get("text", "")

            processed_frames.append({
                "file": rel,
                "line": ln,
                "function": f.get("function", ""),
                "in_project": target.is_file(),
                "snippet": snippet,
            })

        project_frames = [pf for pf in processed_frames if pf["in_project"]]
        root_cause = project_frames[-1] if project_frames else (processed_frames[-1] if processed_frames else None)

        return {
            "success": True,
            "root": resolved_root,
            "error_type": error_type or "UnknownError",
            "error_message": error_message,
            "frames_count": len(processed_frames),
            "project_frames_count": len(project_frames),
            "frames": processed_frames,
            "root_cause": root_cause,
        }

    def repo_briefing(self, root: str) -> dict[str, Any]:
        """Produce an ultra-compact (<300 token) project orientation snapshot for cloud models."""
        resolved_root = canonical_root(root)
        base = Path(resolved_root)
        if not base.is_dir():
            return {"success": False, "error": "Root directory does not exist"}

        manifests: list[str] = []
        stack_types: list[str] = []
        test_commands: list[str] = []

        if (base / "pyproject.toml").is_file() or (base / "setup.py").is_file() or (base / "requirements.txt").is_file():
            stack_types.append("Python")
            manifests.extend([m for m in ("pyproject.toml", "setup.py", "requirements.txt") if (base / m).is_file()])
            test_commands.append("pytest")
        if (base / "package.json").is_file():
            stack_types.append("TypeScript/JavaScript")
            manifests.append("package.json")
            test_commands.append("npm test")
        if any(base.glob("*.csproj")) or any(base.glob("*.sln")):
            stack_types.append("C# / .NET")
            test_commands.append("dotnet test")
        if (base / "Cargo.toml").is_file():
            stack_types.append("Rust")
            manifests.append("Cargo.toml")
            test_commands.append("cargo test")
        if (base / "go.mod").is_file():
            stack_types.append("Go")
            manifests.append("go.mod")
            test_commands.append("go test ./...")

        common_entries = [
            "src/main.py", "main.py", "app.py", "src/index.ts", "src/index.js",
            "Program.cs", "main.go", "src/main.rs"
        ]
        entry_points = [e for e in common_entries if (base / e).is_file()]

        branch = "unknown"
        dirty_files = 0
        recent_commits: list[str] = []
        try:
            from .process_utils import hidden_run_kwargs
            cp_branch = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=str(base), capture_output=True, text=True, check=False, timeout=2, **hidden_run_kwargs()
            )
            if cp_branch.returncode == 0:
                branch = cp_branch.stdout.strip()

            cp_status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(base), capture_output=True, text=True, check=False, timeout=2, **hidden_run_kwargs()
            )
            if cp_status.returncode == 0:
                dirty_files = len([l for l in cp_status.stdout.splitlines() if l.strip()])

            cp_log = subprocess.run(
                ["git", "log", "-n", "3", "--oneline"],
                cwd=str(base), capture_output=True, text=True, check=False, timeout=2, **hidden_run_kwargs()
            )
            if cp_log.returncode == 0:
                recent_commits = [l.strip() for l in cp_log.stdout.splitlines() if l.strip()]
        except Exception:
            pass

        active_task = None
        task_store = getattr(self, "task_store", None)
        if task_store is not None:
            try:
                active_task = task_store.get_active_task()
            except Exception:
                active_task = None

        brief_card = (
            f"**Repo**: {base.name} | **Branch**: {branch} ({dirty_files} dirty)\n"
            f"**Stack**: {', '.join(stack_types) or 'Generic'} | **Manifests**: {', '.join(manifests) or 'None'}\n"
            f"**Test Runner**: {', '.join(test_commands) or 'None'}\n"
            f"**Entrypoints**: {', '.join(entry_points) or 'None'}\n"
            f"**Recent**: {recent_commits[0] if recent_commits else 'No git history'}"
        )

        return {
            "success": True,
            "root": resolved_root,
            "repo_name": base.name,
            "stack": stack_types,
            "manifests": manifests,
            "test_commands": test_commands,
            "entry_points": entry_points,
            "git": {
                "branch": branch,
                "dirty_files": dirty_files,
                "recent_commits": recent_commits,
            },
            "active_task": active_task,
            "markdown_card": brief_card,
        }

    def repo_map(self, root: str, max_symbols: int = 120) -> dict[str, Any]:
        def compute() -> dict[str, Any]:
            indexed_paths = None
            if self.preprocessor is not None:
                try:
                    indexed_paths = self.preprocessor.indexed_paths(root)
                except Exception:
                    indexed_paths = None
            if indexed_paths:
                res = self.repo_tools.repo_map(root, max_symbols, paths=indexed_paths)
                if isinstance(res, dict):
                    res["preprocessed_hit"] = True
                return res
            res = self.repo_tools.repo_map(root, max_symbols)
            if isinstance(res, dict):
                res["preprocessed_hit"] = False
            return res

        return self._repo_cached("map", root, {"max_symbols": max_symbols}, compute)

    def deterministic_operation(self, operation: str, root: str, params: dict[str, Any], compute: Any) -> dict[str, Any]:
        """Cache expensive deterministic analyses by repository fingerprint.

        These operations are pure derived views of repository state. Sharing the same
        cache with search/context prevents dashboard, MCP and local-model callers from
        independently repeating AST/security/test/dependency scans.
        """
        def wrapped_compute() -> dict[str, Any]:
            res = compute()
            if isinstance(res, dict):
                res["preprocessed_hit"] = bool(res.get("success", True))
            return res
        return self._repo_cached(f"det:{operation}", root, params, wrapped_compute)

    def _repository_test_impact_service(self):
        from .repository_test_impact import RepositoryTestImpactService

        return RepositoryTestImpactService(
            self.deterministic,
            self.deterministic_operation,
        )

    def test_matrix(self, root: str) -> dict[str, Any]:
        return self._repository_test_impact_service().test_matrix(root)

    def affected_tests(
        self,
        root: str,
        changed_paths: list[str] | None = None,
        base: str = "HEAD",
        path_hints: list[Any] | tuple[Any, ...] | None = None,
    ) -> dict[str, Any]:
        from .project_config import (
            PathHint,
            path_is_allowed,
            path_matches_pattern,
            resolve_project_context,
        )

        context = resolve_project_context(root, configured_state_dir(self.config))
        request_hints: list[PathHint] = []
        if isinstance(path_hints, (list, tuple)):
            for item in path_hints[:64]:
                if isinstance(item, PathHint):
                    request_hints.append(item)
                elif isinstance(item, dict):
                    allowed_fields = {
                        "path",
                        "purpose",
                        "scope",
                        "evidence_id",
                        "provenance",
                        "repository_revision",
                        "config_digest",
                        "expires_at",
                    }
                    if set(item) - allowed_fields:
                        continue
                    try:
                        request_hints.append(
                            PathHint(**{
                                key: value
                                for key, value in item.items()
                                if key in allowed_fields
                            })
                        )
                    except TypeError:
                        continue
        request_hints = [
            hint
            for hint in request_hints
            if isinstance(hint.path, str)
            and isinstance(hint.purpose, str)
            and isinstance(hint.scope, str)
            and all(
                value is None or isinstance(value, str)
                for value in (
                    hint.evidence_id,
                    hint.provenance,
                    hint.repository_revision,
                    hint.config_digest,
                    hint.expires_at,
                )
            )
        ]
        hint_digest = stable_hash([asdict(hint) for hint in request_hints])
        params = {
            "changed_paths": None if changed_paths is None else list(changed_paths),
            "base": base,
            "project_config_digest": context.config_digest,
            "path_hints_digest": hint_digest,
        }
        result = self._repository_test_impact_service().affected_tests(
            root,
            changed_paths,
            base,
            params,
        )
        if not isinstance(result, dict) or not result.get("success", True):
            return result
        workspace_state = result.get("workspace_cache", {})
        repository_revision = (
            str(workspace_state.get("fingerprint", ""))
            if isinstance(workspace_state, dict)
            and not workspace_state.get("stale")
            and not workspace_state.get("degraded")
            else ""
        )

        candidates = [
            path for path in result.get("test_files", []) if isinstance(path, str)
        ]
        changed_for_mapping = changed_paths or result.get("changed_files", [])
        changed_for_graph = sorted(
            {
                path.replace("\\", "/").lstrip("./")
                for path in changed_for_mapping
                if isinstance(path, str) and path
            }
        )
        graph_complete = False
        graph_tests: list[str] = []
        graph_missing_candidates = 0
        try:
            impact = (
                self.code_index.impact(root, changed_for_graph, max_dependents=100)
                if self.code_index is not None and changed_for_graph
                else None
            )
            if isinstance(impact, dict):
                likely_dependents = impact.get("likely_dependents", [])
                suggested_tests = impact.get("suggested_tests", [])
                confidence = impact.get("confidence")
                graph_complete = (
                    impact.get("success") is True
                    and isinstance(confidence, (int, float))
                    and not isinstance(confidence, bool)
                    and math.isfinite(float(confidence))
                    and float(confidence) >= 0.94
                    and impact.get("indexed_changed_files") == len(changed_for_graph)
                    and impact.get("changed_files_count") == len(changed_for_graph)
                    and isinstance(likely_dependents, list)
                    and len(likely_dependents) < 100
                    and isinstance(suggested_tests, list)
                    and len(suggested_tests) < 20
                )
                if graph_complete:
                    for item in suggested_tests:
                        candidate = item.get("path") if isinstance(item, dict) else None
                        if isinstance(candidate, str):
                            graph_tests.append(candidate.replace("\\", "/"))
                    for item in likely_dependents:
                        candidate = item.get("path") if isinstance(item, dict) else None
                        if (
                            isinstance(candidate, str)
                            and self.code_index._is_test_path(candidate)
                        ):
                            graph_tests.append(candidate.replace("\\", "/"))
                    graph_tests = list(dict.fromkeys(graph_tests))
                    graph_missing_candidates = len(set(graph_tests) - set(candidates))
                    candidates.extend(
                        path for path in graph_tests if path not in candidates
                    )
        except Exception:
            graph_complete = False
        selection_uncertain = not graph_complete
        matrix: dict[str, Any] | None = None
        complete_matrix_paths: list[str] = []
        if selection_uncertain:
            matrix = self.test_matrix(root)
            for item in matrix.get("test_files", []):
                candidate = item.get("path") if isinstance(item, dict) else item
                if isinstance(candidate, str):
                    complete_matrix_paths.append(candidate)
            candidates.extend(complete_matrix_paths)
            if not complete_matrix_paths:
                candidates = []
        target_patterns = tuple(
            target_pattern
            for source_pattern, targets in context.settings.affected_tests_mapping.items()
            if any(
                isinstance(changed_path, str)
                and path_matches_pattern(changed_path, source_pattern)
                for changed_path in changed_for_mapping
            )
            for target_pattern in targets
        )
        if target_patterns:
            if matrix is None:
                matrix = self.test_matrix(root)
            for item in matrix.get("test_files", []):
                candidate = item.get("path") if isinstance(item, dict) else item
                if (
                    isinstance(candidate, str)
                    and any(
                        path_matches_pattern(candidate, pattern)
                        for pattern in target_patterns
                    )
                ):
                    candidates.append(candidate)
        candidates = list(dict.fromkeys(candidates))
        usage = context.prioritize_paths(
            candidates,
            purpose="affected_tests",
            scope="run_affected",
            repository_revision=repository_revision,
            path_hints=tuple(request_hints),
        )
        allowed_tests: list[str] = []
        for candidate in usage.paths:
            try:
                file_size = (Path(root) / candidate).stat().st_size
            except OSError:
                file_size = None
            if path_is_allowed(
                root,
                candidate,
                context.settings,
                phase="test",
                size_bytes=file_size,
            ):
                allowed_tests.append(candidate)

        result = dict(result)
        from .test_selection import affected_test_command, canonical_runner, compatible_tests
        framework = canonical_runner(result.get("framework", "unknown"))
        allowed_tests, incompatible_tests = compatible_tests(allowed_tests, framework)
        result["test_files"] = allowed_tests
        result["excluded_incompatible_tests"] = list(dict.fromkeys(
            [*result.get("excluded_incompatible_tests", []), *incompatible_tests]
        ))
        suggested_command = affected_test_command(allowed_tests, framework)
        result["suggested_command"] = suggested_command
        result["project_config_digest"] = context.config_digest
        if graph_complete:
            result["dependency_graph_complete"] = True
            result["dependency_graph_test_count"] = len(graph_tests)
            result["dependency_graph_missing_candidates"] = graph_missing_candidates
        if selection_uncertain:
            result["selection_uncertain"] = True
            result["selection_fallback"] = (
                "complete_test_matrix"
                if complete_matrix_paths
                else "unavailable_test_matrix"
            )
        result["path_hint_usage"] = {
            "hint_used": usage.hint_used,
            "fallback_used": usage.fallback_used,
            "hint_helped": usage.hint_helped,
        }
        return result

    def repo_topology(self, root: str) -> dict[str, Any]:
        return self.deterministic_operation("repo-topology", root, {}, lambda: self.deterministic.repo_topology(root))

    def ast_rename(self, root: str, file_path: str, old_symbol: str, new_symbol: str, apply_changes: bool = False) -> dict[str, Any]:
        return self.deterministic.ast_rename(root, file_path, old_symbol, new_symbol, apply_changes=apply_changes)

    def generate_mocks(self, root: str, file_path: str, symbol: str) -> dict[str, Any]:
        return self.deterministic.generate_mocks(root, file_path, symbol)

    def split_changes(self, root: str, changed_files: list[str] | None = None) -> dict[str, Any]:
        return self.deterministic.split_changes(root, changed_files)

    def synthesize_rules(self, root: str, limit: int = 10) -> dict[str, Any]:
        return self.deterministic.synthesize_rules(root, limit)

    def code_invariants(self, root: str, path: str | None = None) -> dict[str, Any]:
        return self.deterministic.code_invariants(root, path)

    def generate_dataset(self, root: str, schema_or_model: Any, count: int = 10, format: str = "json") -> dict[str, Any]:
        return self.deterministic.generate_dataset(root, schema_or_model, count=count, format=format)

    def profile_digest(self, profile_path: str, top_n: int = 15) -> dict[str, Any]:
        return self.deterministic.profile_digest(profile_path, top_n=top_n)

    def worktree_lease(self, root: str, branch_name: str | None = None, worktree_path: str | None = None) -> dict[str, Any]:
        from .process_utils import create_git_worktree
        return create_git_worktree(root, branch_name=branch_name, worktree_path=worktree_path)

    def worktree_release(self, root: str, worktree_path: str, delete_branch: bool = True, branch_name: str | None = None, *, worktree_id: str = "") -> dict[str, Any]:
        from .process_utils import remove_git_worktree
        return remove_git_worktree(root, worktree_path, delete_branch=delete_branch, branch_name=branch_name, worktree_id=worktree_id)

    def list_worktrees(self, root: str) -> dict[str, Any]:
        from .process_utils import list_git_worktrees
        return list_git_worktrees(root)

    def prune_worktrees(self, root: str) -> dict[str, Any]:
        from .process_utils import prune_git_worktrees
        return prune_git_worktrees(root)


    def spawn_daemon(
        self,
        command: str | list[str],
        cwd: str,
        name: str = "",
        env: dict[str, str] | None = None,
        *,
        task_id: str = "",
    ) -> dict[str, Any]:
        if not self.commands:
            return {"success": False, "error": "command broker unavailable"}
        return self.commands.spawn_daemon(command, cwd, name=name, env=env, task_id=task_id)

    def daemon_status(
        self, daemon_id: str | None = None, *, task_id: str = ""
    ) -> dict[str, Any]:
        if not self.commands:
            return {"success": False, "error": "command broker unavailable"}
        if not task_id:
            return {
                "success": False,
                "error": "daemon status requires a registered task id",
                "policy_blocked": True,
                "terminal": True,
                "retryable": False,
            }
        denied = self._authorize_command_action(
            "daemon_status", endpoint="services.daemon_status", task_id=task_id
        )
        if denied is not None:
            return denied
        return self.commands.daemon_status(daemon_id, task_id=task_id)

    def stop_daemon(self, daemon_id: str, *, task_id: str = "") -> dict[str, Any]:
        if not self.commands:
            return {"success": False, "error": "command broker unavailable"}
        return self.commands.stop_daemon(daemon_id, task_id=task_id)

    def lint_fix(self, root: str, command: str | None = None, paths: list[str] | None = None, tenant: str = "agent", timeout: int | None = None) -> dict[str, Any]:
        if not self.commands:
            return {"success": False, "error": "command broker unavailable"}
        return self.commands.lint_fix(root, command=command, paths=paths, tenant=tenant, timeout=timeout)

    def http_probe(self, url: str, expected_status: int = 200, json_path: str | None = None, timeout: float = 5.0, headers: dict[str, str] | None = None) -> dict[str, Any]:
        if not self.commands:
            return {"success": False, "error": "command broker unavailable"}
        return self.commands.http_probe(url, expected_status=expected_status, json_path=json_path, timeout=timeout, headers=headers)

    def security_audit(self, root: str, limit: int = 200) -> dict[str, Any]:
        return self.deterministic_operation("security-audit", root, {"limit": int(limit)}, lambda: self.deterministic.security_audit(root, int(limit)))

    def ast_outline(self, root: str, path: str) -> dict[str, Any]:
        return self.deterministic_operation("ast-outline", root, {"path": path}, lambda: self.deterministic.ast_outline(root, path))

    def batch_replace(self, root: str, edits: list[dict[str, Any]], dry_run: bool = False) -> dict[str, Any]:
        if not rollout_feature_enabled(self.config, "batch_replacement"):
            return {
                "success": False,
                "unsupported": True,
                "feature": "batch_replacement",
                "error": "batch replacement is disabled (features.batch_replacement=false)",
            }
        if not self.deterministic:
            return {"success": False, "error": "deterministic engine disabled"}
        return self.deterministic.batch_replace(root, edits, dry_run=dry_run)

    def refactor_impact(self, root: str, file_path: str, symbol: str) -> dict[str, Any]:
        return self.deterministic_operation("refactor-impact", root, {"file": file_path, "symbol": symbol}, lambda: self.deterministic.refactor_impact(root, file_path, symbol))

    def resolve_imports(self, root: str, symbols: list[str], language: str = "auto") -> dict[str, Any]:
        # Revalidate source hashes rather than reuse workspace-only export proof.
        return self.deterministic.resolve_imports(root, symbols, language)

    def callers(self, root: str, symbol: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        bounds_error = pagination_bounds_error(limit, offset)
        if bounds_error:
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": bounds_error}
        if not isinstance(symbol, str) or not symbol.strip():
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": "symbol must be a non-empty string"}
        if self.code_index is not None:
            ci_res = self.code_index.find_callers(root, symbol, limit, offset)
            if ci_res.get("success"):
                if ci_res.get("count", 0) > 0 or ci_res.get("index_available") is not False:
                    return ci_res
        return self.deterministic_operation(
            "callers", root, {"symbol": symbol, "limit": limit, "offset": offset},
            lambda: self.deterministic.find_callers(root, symbol, limit, offset),
        )

    def callees(self, root: str, symbol: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        bounds_error = pagination_bounds_error(limit, offset)
        if bounds_error:
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": bounds_error}
        if not isinstance(symbol, str) or not symbol.strip():
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": "symbol must be a non-empty string"}
        if self.code_index is not None:
            ci_res = self.code_index.find_callees(root, symbol, limit, offset)
            if ci_res.get("success"):
                if ci_res.get("count", 0) > 0 or ci_res.get("index_available") is not False:
                    return ci_res
        return self.deterministic_operation(
            "callees", root, {"symbol": symbol, "limit": limit, "offset": offset},
            lambda: self.deterministic.find_callees(root, symbol, limit, offset),
        )

    def dead_code(self, root: str, limit: int = 200) -> dict[str, Any]:
        return self.deterministic_operation("dead-code", root, {"limit": int(limit)}, lambda: getattr(self.deterministic, "find_dead_code", getattr(self.deterministic, "detect_dead_code", None))(root, int(limit)))

    def secret_scan(self, root: str, path: str | None = None, scan_git_history: bool = False, commit_depth: int = 20) -> dict[str, Any]:
        return self.deterministic_operation("secret-scan", root, {"path": path, "git": scan_git_history, "depth": commit_depth}, lambda: self.deterministic.secret_scan(root, path, scan_git_history=scan_git_history, commit_depth=commit_depth))

    def schema_inspect(self, root: str, db_path: str | None = None) -> dict[str, Any]:
        return self.deterministic_operation("schema-inspect", root, {"db_path": db_path}, lambda: self.deterministic.schema_inspect(root, db_path))

    def explain_query(self, root: str, query: str, db_path: str | None = None) -> dict[str, Any]:
        return self.deterministic_operation("explain-query", root, {"query": query, "db_path": db_path}, lambda: self.deterministic.explain_query(root, query, db_path))

    def env_compat(self, root: str) -> dict[str, Any]:
        return self.deterministic_operation("env-compat", root, {}, lambda: self.deterministic.env_compat(root))

    def circular_dependencies(self, root: str, language: str = "python") -> dict[str, Any]:
        return self.deterministic_operation("circular-dependencies", root, {"language": language}, lambda: self.deterministic.find_circular_dependencies(root, language))

    def generate_types(self, root: str, path: str) -> dict[str, Any]:
        return self.deterministic_operation("generate-types", root, {"path": path}, lambda: self.deterministic.generate_types(root, path))

    def code_complexity(
        self, root: str, path: str | None = None, max_results: int = 20, include_tests: bool = False
    ) -> dict[str, Any]:
        return self.deterministic_operation(
            "code-complexity", root,
            {"path": path, "max": max_results, "include_tests": include_tests},
            lambda: self.deterministic.code_complexity(root, path, max_results, include_tests),
        )

    def extract_api_spec(self, root: str, framework: str | None = None) -> dict[str, Any]:
        return self.deterministic_operation("extract-api-spec", root, {"framework": framework}, lambda: self.deterministic.extract_api_spec(root, framework))

    def slice_dependency_graph(self, root: str, symbol: str, path: str | None = None, depth: int = 2) -> dict[str, Any]:
        return self.deterministic_operation("slice-dependency-graph", root, {"symbol": symbol, "path": path, "depth": depth}, lambda: self.deterministic.slice_dependency_graph(root, symbol, path, depth))

    def migration_drift(self, root: str, db_path: str | None = None) -> dict[str, Any]:
        return self.deterministic_operation("migration-drift", root, {"db_path": db_path}, lambda: self.deterministic.migration_drift(root, db_path))

    def package_audit(self, root: str, lockfile_path: str | None = None) -> dict[str, Any]:
        return self.deterministic_operation("package-audit", root, {"lockfile": lockfile_path}, lambda: self.deterministic.package_audit(root, lockfile_path))

    def structural_search(self, root: str, pattern: str, path: str | None = None, max_results: int = 30) -> dict[str, Any]:
        return self.deterministic_operation("structural-search", root, {"pattern": pattern, "path": path, "max_results": max_results}, lambda: self.deterministic.structural_search(root, pattern, path=path, max_results=max_results))

    def context_budget(self, root: str, files: list[str] | None = None, max_tokens: int = 4000) -> dict[str, Any]:
        return self.deterministic_operation("context-budget", root, {"files": files, "max_tokens": max_tokens}, lambda: self.deterministic.context_budget(root, files=files, max_tokens=max_tokens))

    def git_diff(self, root: str, path: str | None = None, staged: bool = False, max_lines: int = 1000,
                 *, rev1: str | None = None, rev2: str | None = None) -> dict[str, Any]:
        if rev1 is not None or rev2 is not None:
            # Moving refs must be pinned afresh, not served from a workspace-only cache.
            return self.deterministic.git_diff(root, path=path, staged=staged, max_lines=max_lines, rev1=rev1, rev2=rev2)
        return self.deterministic_operation("git-diff", root, {"path": path, "staged": staged, "max_lines": max_lines}, lambda: self.deterministic.git_diff(root, path=path, staged=staged, max_lines=max_lines))

    def git_history_search(
        self,
        root: str,
        query: str,
        max_commits: int = 20,
        *,
        author: str | None = None,
        since: str | None = None,
        until: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "query": query,
            "max_commits": max_commits,
            "author": author,
            "since": since,
            "until": until,
            "path": path,
        }
        return self.deterministic_operation(
            "git-history-search", root, params,
            lambda: self.deterministic.git_history_search(
                root, query, max_commits=max_commits,
                author=author, since=since, until=until, path=path,
            ),
        )

    def find_hotspots(self, root: str, days: int = 30, limit: int = 20) -> dict[str, Any]:
        return self.deterministic_operation(
            "find-hotspots", root,
            {"days": days, "limit": limit, "algorithm": "git-recency-half-life-90d-v1"},
            lambda: self.deterministic.find_hotspots(root, days=days, limit=limit),
        )

    def generate_tests_for_diff(self, root: str, diff: str | None = None, path: str | None = None) -> dict[str, Any]:
        return self.deterministic_operation("generate-tests-for-diff", root, {"diff": bool(diff), "path": path}, lambda: self.deterministic.generate_tests_for_diff(root, diff=diff, path=path))

    def cross_repo_contract(self, backend_root: str, frontend_root: str) -> dict[str, Any]:
        return self.deterministic_operation("cross-repo-contract", backend_root, {"frontend_root": frontend_root}, lambda: self.deterministic.cross_repo_contract(backend_root, frontend_root))

    def mock_server_start(self, root: str = ".", spec_path: str | None = None, port: int = 0) -> dict[str, Any]:
        if not self.commands:
            return {"success": False, "error": "command broker unavailable"}
        return self.commands.mock_server_start(root, spec_path=spec_path, port=port)

    def mock_server_stop(self, port: int = 11440) -> dict[str, Any]:
        if not self.commands:
            return {"success": False, "error": "command broker unavailable"}
        return self.commands.mock_server_stop(port)

    def mock_server_status(self, port: int = 11440) -> dict[str, Any]:
        if not self.commands:
            return {"success": False, "error": "command broker unavailable"}
        return self.commands.mock_server_status(port)


    def diff_hunk_stage(self, root: str, patch: str) -> dict[str, Any]:
        if not self.commands:
            return {"success": False, "error": "command broker unavailable"}
        return self.commands.diff_hunk_stage(root, patch)

    def test_flaky_detect(self, root: str, command: str, runs: int = 5, timeout: int = 30, timeout_per_run: int | None = None) -> dict[str, Any]:
        if not self.commands:
            return {"success": False, "error": "command broker unavailable"}
        effective_timeout = timeout_per_run if timeout_per_run is not None else timeout
        return self.commands.test_flaky_detect(root, command, runs=runs, timeout_per_run=effective_timeout)

    def webhook_replay(self, url: str, payload: dict[str, Any] | str, secret: str = "", signature_header: str = "X-Hub-Signature-256", timeout: float = 10.0) -> dict[str, Any]:
        if not self.commands:
            return {"success": False, "error": "command broker unavailable"}
        return self.commands.webhook_replay(url, payload, secret=secret, signature_header=signature_header, timeout=timeout)

    def stash_save(self, root: str, message: str = "local_ai_hub_stash") -> dict[str, Any]:
        if not self.commands:
            return {"success": False, "error": "command broker unavailable"}
        return self.commands.stash_save(root, message=message)

    def stash_restore(self, root: str) -> dict[str, Any]:
        if not self.commands:
            return {"success": False, "error": "command broker unavailable"}
        return self.commands.stash_restore(root)

    def record_mock(self, url: str, cassette_name: str) -> dict[str, Any]:
        if not self.commands:
            return {"success": False, "error": "command broker unavailable"}
        return self.commands.record_mock(url, cassette_name)

    def replay_mock(self, cassette_name: str) -> dict[str, Any]:
        if not self.commands:
            return {"success": False, "error": "command broker unavailable"}
        return self.commands.replay_mock(cassette_name)

    def simulate_merge(self, root: str, source_branch: str, target_branch: str = "HEAD") -> dict[str, Any]:
        from .process_utils import simulate_git_merge
        return simulate_git_merge(self._root(root), source_branch, target_branch=target_branch)

    def pubsub_publish(self, topic: str, message: dict[str, Any] | str, sender: str = "agent") -> dict[str, Any]:
        from .agent_events import SwarmPubSub
        return SwarmPubSub.get_default(state_store=self.agent_state).publish(topic, message, sender=sender)

    def pubsub_poll(
        self,
        topic: str,
        since_timestamp: float = 0.0,
        limit: int = 50,
        after_seq: int = 0,
    ) -> dict[str, Any]:
        from .agent_events import SwarmPubSub
        bus = SwarmPubSub.get_default(state_store=self.agent_state)
        return bus.poll(
            topic,
            since_timestamp=since_timestamp,
            limit=limit,
            after_seq=after_seq,
        )

    def synthesize_commit(self, root: str, hint: str = "", task_id: str = "") -> dict[str, Any]:
        tasks_data: list[dict[str, Any]] = []
        receipts_data: list[dict[str, Any]] = []

        if self.task_store is not None:
            if task_id:
                t = self.task_store.get(task_id)
                if t:
                    tasks_data.append(t.to_dict())
            else:
                active = self.task_store.list_tasks(status=None, limit=5)
                for t in active:
                    tasks_data.append(t.to_dict())

        if self.verification_store is not None:
            tids = [task_id] if task_id else [str(t.get("task_id")) for t in tasks_data if t.get("task_id")]
            for tid in tids[:5]:
                comp = self.verification_store.completion(tid)
                for r in comp.receipts:
                    if r.passed:
                        receipts_data.append(r.to_dict())

        params = {"hint": hint, "task_id": task_id, "tasks_count": len(tasks_data), "receipts_count": len(receipts_data)}
        return self.deterministic_operation(
            "commit-synthesis",
            root,
            params,
            lambda: self.deterministic.synthesize_commit(
                root, hint, task_id=task_id, tasks=tasks_data, receipts=receipts_data
            ),
        )

    def code_inspect_symbol(self, root: str, symbol: str) -> dict[str, Any]:
        if self.code_index is None:
            return {"success": False, "error": "code index disabled"}
        return self._repo_cached("ci:inspect_symbol", root, {"symbol": symbol}, lambda: self.code_index.inspect_symbol(root, symbol))

    def code_find_symbol(self, root: str, pattern: str, depth: int = 0, include_body: bool = False, include_info: bool = True, relative_path: str | None = None, limit: int = 30) -> dict[str, Any]:
        if self.code_index is None:
            return {"success": False, "error": "code index disabled"}
        params = {"pattern": pattern, "depth": depth, "include_body": include_body, "include_info": include_info, "path": relative_path, "limit": limit}
        return self._repo_cached("ci:find_symbol", root, params, lambda: self.code_index.find_symbol(root, pattern, depth=depth, include_body=include_body, include_info=include_info, relative_path=relative_path, limit=limit))

    def code_find_declaration(self, root: str, symbol: str, path: str | None = None) -> dict[str, Any]:
        if self.code_index is None:
            return {"success": False, "error": "code index disabled"}
        return self._repo_cached("ci:find_declaration", root, {"symbol": symbol, "path": path}, lambda: self.code_index.find_declaration(root, symbol, path=path))

    def code_find_implementations(self, root: str, symbol: str, path: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        if self.code_index is None:
            return {"success": False, "error": "code index disabled"}
        bounds_error = pagination_bounds_error(limit, offset)
        if bounds_error:
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": bounds_error}
        return self._repo_cached(
            "ci:find_implementations", root,
            {"symbol": symbol, "path": path, "limit": limit, "offset": offset},
            lambda: self.code_index.find_implementations(root, symbol, path=path, limit=limit, offset=offset),
        )

    def code_find_referencing_symbols(self, root: str, symbol: str, path: str | None = None) -> dict[str, Any]:
        if self.code_index is None:
            return {"success": False, "error": "code index disabled"}
        return self._repo_cached("ci:find_referencing_symbols", root, {"symbol": symbol, "path": path}, lambda: self.code_index.find_referencing_symbols(root, symbol, path=path))

    def code_symbols_overview(self, root: str, path: str, depth: int = 1) -> dict[str, Any]:
        if self.code_index is None:
            return {"success": False, "error": "code index disabled"}
        return self._repo_cached("ci:symbols_overview", root, {"path": path, "depth": depth}, lambda: self.code_index.get_symbols_overview(root, path, depth=depth))

    def code_diagnostics(self, root: str, path: str) -> dict[str, Any]:
        if self.code_index is None:
            return {"success": False, "error": "code index disabled"}
        return self._repo_cached("ci:diagnostics", root, {"path": path}, lambda: self.code_index.get_diagnostics_for_file(root, path))

    def audit_dependencies(self, root: str) -> dict[str, Any]:
        if self.deterministic is None:
            return {"success": False, "error": "deterministic engine disabled"}
        return self.deterministic_operation("audit-dependencies", root, {}, lambda: self.deterministic.audit_dependencies(root))

    def symbol_callgraph(self, root: str, symbol: str | None = None, limit: int = 50) -> dict[str, Any]:
        if self.deterministic is None:
            return {"success": False, "error": "deterministic engine disabled"}
        return self.deterministic_operation("symbol-callgraph", root, {"symbol": symbol, "limit": limit}, lambda: self.deterministic.symbol_callgraph(root, symbol, limit))

    def repo_impact(self, root: str, base: str = "HEAD", staged: bool = False, max_symbols: int = 48, max_dependents: int = 30) -> dict[str, Any]:
        def compute() -> dict[str, Any]:
            # Local AI deterministic primary path: refresh only changed files in the code
            # index, then resolve dependents/tests through SQLite refs/edges. A full
            # repository scan is only a bounded fallback for sparse indexes.
            if self.code_index is not None and hasattr(self.code_index, "impact"):
                diff = self.repo_tools.git_diff(root, base, staged, max_tokens=24000)
                if diff.get("terminal"):
                    return diff
                if diff.get("success"):
                    changed = [str(x) for x in diff.get("changed_files", [])]
                    if not changed:
                        return {
                            "success": True, "root": str(Path(root).expanduser().resolve()), "changed_files": [],
                            "changed_symbols": [], "likely_dependents": [], "suggested_tests": [],
                            "risk": {"score": 0, "level": "low", "reasons": ["no changed files"]}, "method": "code-index",
                        }
                    try:
                        indexed = self.code_index.impact(root, changed, max_symbols, max_dependents)
                    except Exception:
                        indexed = {"success": False}
                    if indexed.get("success") and (indexed.get("changed_symbols") or float(indexed.get("confidence", 0.0) or 0.0) >= 0.70):
                        det = {}
                        if self.deterministic is not None:
                            try: det = self.deterministic.diff_facts(str(diff.get("diff", "")))
                            except Exception: det = {}
                        signals = det.get("risk_signals", {}) if isinstance(det, dict) else {}
                        score = 0; reasons: list[str] = []
                        if len(changed) >= 6: score += 2; reasons.append("multi-file change")
                        if det.get("manifest_files"): score += 2; reasons.append("manifest/build metadata changed")
                        if det.get("breaking_changes"): score += 4; reasons.append(f"{len(det['breaking_changes'])} breaking change(s) detected")
                        for key, weight, label in (("security",2,"security-sensitive code"),("concurrency",2,"concurrency-sensitive code"),("database",1,"database/persistence code"),("shell-exec",2,"process/shell execution"),("dynamic-eval",3,"dynamic evaluation")):
                            if int(signals.get(key, 0) or 0): score += weight; reasons.append(label)
                        if len(indexed.get("likely_dependents", [])) >= 10: score += 1; reasons.append("many indexed dependents")
                        if not indexed.get("suggested_tests") and any(Path(x).suffix.lower() in self.repo_tools.extensions for x in changed):
                            score += 1; reasons.append("no indexed tests found")
                        level = "high" if score >= 5 else "medium" if score >= 2 else "low"
                        if not reasons: reasons.append("localized indexed change")
                        return {
                            "success": True, "root": str(Path(root).expanduser().resolve()), "changed_files": changed,
                            "changed_symbols": indexed.get("changed_symbols", []), "likely_dependents": indexed.get("likely_dependents", []),
                            "suggested_tests": indexed.get("suggested_tests", []), "risk": {"score": score, "level": level, "reasons": reasons},
                            "diff_sha256": diff.get("diff_sha256"), "method": "code-index", "index_confidence": indexed.get("confidence", 0.0),
                            "deterministic_diff": det,
                        }
            fallback = self.repo_tools.impact_analysis(root, base, staged, max_symbols, max_dependents)
            if isinstance(fallback, dict): fallback.setdefault("method", "scan-fallback")
            return fallback
        return self._repo_cached(
            "impact", root, {"base": base, "staged": staged, "max_symbols": max_symbols, "max_dependents": max_dependents}, compute,
        )

    def repo_diff(self, root: str, base: str = "HEAD", staged: bool = False, max_tokens: int = 10000) -> dict[str, Any]:
        return self._repo_cached(
            "diff", root, {"base": base, "staged": staged, "max_tokens": max_tokens},
            lambda: self.repo_tools.git_diff(root, base, staged, max_tokens),
        )

    @staticmethod
    def _adaptive_label(value: Any, limit: int = 160) -> str:
        text = str(value or "")[:limit]
        if re.search(r"(?i)(api[_ -]?key|access[_ -]?token|password|secret|authorization|bearer)\s*[:=]", text):
            return "<redacted>"
        return re.sub(r"[^A-Za-z0-9_./:@+ -]", " ", text).strip()[:limit]

    def _adaptive_memory_revision(self, request: ConsistencyRequest) -> str:
        explicit = str(getattr(request, "memory_revision", "") or "")[:200]
        if explicit:
            return explicit
        store = getattr(self.consistency_guard, "memory_store", None)
        for name in ("memory_revision", "revision"):
            value = getattr(store, name, "") if store is not None else ""
            if callable(value):
                try:
                    value = value(request.root)
                except TypeError:
                    value = value()
            if value:
                return str(value)[:200]
        return ""

    def _context_preload_source(self) -> ContextCompiler | None:
        compiler = getattr(self, "context_compiler", None)
        if compiler is not None:
            return compiler
        try:
            compiler = ContextCompiler(
                AgentStateStore(
                    configured_state_dir(getattr(self, "config", {}), create=False) / "agent_state.sqlite",
                    enabled=False,
                ),
                config=getattr(self, "config", {}),
            )
        except Exception:
            return None
        self.context_compiler = compiler
        return compiler

    def _apply_context_preloads(
        self, request: ConsistencyRequest, base: dict[str, Any],
    ) -> tuple[dict[str, Any], tuple[GuardWarning, ...]]:
        compiler = self._context_preload_source()
        if compiler is None:
            return base, ()
        try:
            elements, preload_warnings = compiler.preload_elements(ContextRequest(
                task_id=request.task_id,
                token_budget=max(1, int(request.token_budget)),
                changed_paths=tuple(request.changed_paths or ()),
                root=request.root,
                tenant=request.tenant,
                phase=request.phase,
                focus=tuple(request.focus or ()),
                preload_profile=request.preload_profile,
            ))
        except Exception:
            return base, ()
        if not elements and not preload_warnings:
            return base, ()

        enriched = dict(base)
        evidence = [dict(item) for item in (base.get("evidence") or ()) if isinstance(item, dict)]
        context = str(base.get("context", "") or "").strip()
        for element in elements:
            content = str(element.content or "")
            context = "\n\n".join(item for item in (context, content) if item)
            provenance = dict(element.provenance or {})
            evidence.append({
                "evidence_id": element.element_id,
                "source_kind": element.source_kind,
                "path": provenance.get("path", ""),
                "text": content,
                "reason": element.reason,
            })
        enriched["context"] = context
        enriched["evidence"] = evidence[:64]
        enriched["preload_profile"] = request.preload_profile
        enriched["preload_evidence_ids"] = [element.element_id for element in elements[:32]]
        warning_objects = tuple(
            GuardWarning(
                "warning",
                str(item.get("code", "preload_warning")),
                str(item.get("message", "preload warning")),
                affected_paths=(str(item["path"]),) if item.get("path") else (),
                recommended_action="review configured context preload",
            )
            for item in preload_warnings
            if isinstance(item, dict)
        )
        return enriched, warning_objects

    def _adaptive_relevance(self, request: ConsistencyRequest, evidence: tuple[dict[str, Any], ...], revision: str, memory_revision: str) -> dict[str, Any]:
        guard = self.consistency_guard
        if guard is None or not evidence:
            return {"success": False, "degraded": True, "degraded_reason": "no_authoritative_evidence", "warnings": []}
        try:
            projector = getattr(guard, "structured_evidence", None)
            if callable(projector):
                structured = list(projector(evidence, limit=24))
            else:
                structured = []
                for item in evidence[:24]:
                    if isinstance(item, dict):
                        structured.append({
                            "evidence_id": str(item.get("evidence_id") or item.get("id") or "")[:200],
                            "authority": "deterministic",
                            "path": self._adaptive_label(item.get("path"), 240),
                            "start_line": max(0, int(item.get("start_line", 0) or 0)),
                            "end_line": max(0, int(item.get("end_line", 0) or 0)),
                        })
            structured = [item for item in structured if isinstance(item, dict) and item.get("evidence_id")][:24]
            if not structured:
                return {"success": False, "degraded": True, "degraded_reason": "no_authoritative_evidence", "warnings": []}
            focus = [self._adaptive_label(item, 80) for item in tuple(getattr(request, "focus", ()) or ())[:16]]
            model_focus = ["focus-" + hashlib.sha256(item.encode("utf-8", "replace")).hexdigest()[:12] for item in focus if item]
            phase = self._adaptive_label(request.phase, 80)
            if phase.casefold() not in {"plan", "discover", "edit", "implementation", "review", "test", "handoff"}:
                phase = "other"
            preload_profile = self._adaptive_label(request.preload_profile, 120)
            if preload_profile.casefold() not in {"", "default", "plan", "edit", "review", "test", "handoff"}:
                preload_profile = "profile-" + hashlib.sha256(preload_profile.encode("utf-8", "replace")).hexdigest()[:12]
            payload = {
                "operation": "context_relevance",
                "phase": phase,
                "focus": model_focus,
                "preload_profile": preload_profile,
                "repository_revision": str(revision)[:200],
                "memory_revision": str(memory_revision)[:200],
                "evidence": structured,
                "limits": {"max_selected_evidence": 12, "max_claims": 16, "max_gaps": 16, "max_wording_chars": 1200},
            }
            params = {
                "repository_revision": str(revision)[:200],
                "task_id": request.task_id,
                "session_id": request.session_id,
                "phase": self._adaptive_label(request.phase, 80),
                "memory_revision": str(memory_revision)[:200],
                "focus": tuple(focus),
                "preload_profile": self._adaptive_label(request.preload_profile, 120),
                "changed_paths": tuple(request.changed_paths),
                "query": self._adaptive_label(request.query, 800),
                "retrieval_config_revision": stable_hash({
                    "search": getattr(self, "config", {}).get("search", {}),
                    "features": getattr(self, "config", {}).get("features", {}),
                    "preprocessing": getattr(self, "config", {}).get("preprocessing", {}),
                    "rag": getattr(self, "config", {}).get("rag", {}),
                    "retrieval": getattr(self, "config", {}).get("retrieval", {}),
                    "external_tools": getattr(self, "config", {}).get("external_tools", {}),
                    "code_intelligence": getattr(self, "config", {}).get("code_intelligence", {}),
                }),
                "evidence_ids": tuple(str(item["evidence_id"])[:200] for item in structured),
            }

            def compute() -> dict[str, Any]:
                try:
                    models = getattr(self, "config", {}).get("models", {})
                    model = getattr(self, "config", {}).get("context_relevance_model") or models.get("general") or models.get("fast_code") or "context-relevance"
                    generated = self._generate(
                        str(model),
                        json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
                        "Return JSON only. Use only supplied deterministic evidence IDs. Never invent repository facts, repeat source text, reveal secrets, or use the user prompt as evidence.",
                        min(512, max(64, int(request.token_budget) // 4)),
                        0.0,
                        request.tenant or "context",
                        "context-relevance",
                        4,
                        semantic_query="context relevance",
                        semantic_context_fingerprint=stable_hash(params),
                        internal=True,
                        format={"type": "object"},
                    )
                except Exception:
                    return {"success": False, "degraded": True, "degraded_reason": "model_error", "warnings": []}
                if not isinstance(generated, dict) or not generated.get("success"):
                    return {"success": False, "degraded": True, "degraded_reason": "model_unavailable", "warnings": []}
                raw = generated.get("text") or generated.get("response") or ""
                try:
                    if isinstance(raw, dict):
                        parsed = raw
                    else:
                        text = str(raw).strip()
                        if text.startswith("```"):
                            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S)
                        parsed = json.loads(text)
                    if not isinstance(parsed, dict):
                        raise ValueError("structured response required")
                except Exception:
                    return {"success": False, "degraded": True, "degraded_reason": "invalid_model_output", "warnings": []}
                claims = parsed.get("claims") if isinstance(parsed.get("claims"), list) else []
                postprocess = getattr(guard, "postprocess_model_claims", None)
                if callable(postprocess):
                    checked = postprocess(evidence, claims, request)
                else:
                    checked = {"claims": [], "unknowns": [], "warnings": []}
                authoritative = set(checked.get("authoritative_evidence_ids", ()))
                selected = [str(item)[:200] for item in (parsed.get("selected_evidence_ids") or ()) if str(item) in authoritative][:12]
                gaps = [self._adaptive_label(item, 240) for item in (parsed.get("gaps") or ())][:16]
                wording = self._adaptive_label(parsed.get("wording"), 1200)
                warning_dicts = []
                for warning in checked.get("warnings", ())[:24]:
                    converter = getattr(warning, "to_dict", None)
                    warning_dicts.append(converter() if callable(converter) else dict(warning) if isinstance(warning, dict) else {"code": "unsupported_model_claim", "message": self._adaptive_label(warning, 240)})
                return {
                    "success": True,
                    "selected_evidence_ids": selected,
                    "claims": list(checked.get("claims", ()))[:16],
                    "unknowns": [self._adaptive_label(item, 240) for item in checked.get("unknowns", ())][:16],
                    "gaps": [item for item in gaps if item],
                    "wording": wording,
                    "warnings": warning_dicts[:24],
                }

            return self._repo_cached("adaptive-relevance", request.root, params, compute)
        except Exception:
            return {"success": False, "degraded": True, "degraded_reason": "relevance_error", "warnings": []}

    def schedule_task_context_warmup(self, task: Any, *, root: str, tenant: str,
                                     changed_paths: list[str] | None = None) -> bool:
        """Optional prediction; reuse only the normal adaptive cache and its fences."""
        if not root or not tenant or not (task.contract.acceptance_criteria or changed_paths):
            return False
        if not bool(self.config.get("preprocessing", {}).get("task_context_warmup", True)):
            return False
        if not Path(root).is_absolute() or not Path(root).is_dir() or len(root) > 400:
            return False
        from .operational_mode import load_operational_mode

        def allowed() -> bool:
            return load_operational_mode(configured_state_dir(self.config, create=False)).mode == "active"

        if not allowed():
            return False
        request = ConsistencyRequest(
            root=canonical_root(root), tenant=tenant, task_id=task.task_id,
            query=task.contract.goal, session_id=task.context.session_id,
            changed_paths=tuple(changed_paths or ())[:64], token_budget=4000,
        )
        expected_updated = task.updated_at
        key = stable_hash({"request": request.__dict__, "task_updated_at": expected_updated})

        def warm() -> None:
            if not allowed():
                return
            store = getattr(self, "task_store", None)
            current = store.get(task.task_id) if store is not None else None
            if current is None or current.updated_at != expected_updated:
                return
            if str(getattr(current.status, "value", current.status)) in {"completed", "cancelled", "failed", "abandoned"}:
                return
            self.adaptive_context_pack(request, mode="adaptive")

        return self._context_warmup.submit(key, warm)

    def close_context_warmup(self) -> None:
        worker = getattr(self, "_context_warmup", None)
        if worker is not None:
            worker.close()

    def adaptive_context_pack(self, request: ConsistencyRequest, *, mode: str = "adaptive", since_hash: str = "") -> dict[str, Any]:
        """Build deterministic context plus bounded, soft consistency findings."""
        if not isinstance(request, ConsistencyRequest):
            raise TypeError("guarded context request must be ConsistencyRequest")
        if not isinstance(mode, str) or mode.strip().lower() not in {"adaptive", "fast", "full"}:
            return {
                "success": False, "terminal": True, "retryable": False,
                "error": "context mode must be adaptive, full or fast",
            }
        mode = mode.strip().lower()
        try:
            memory_revision = self._adaptive_memory_revision(request)
        except Exception as exc:
            return {
                "success": False, "terminal": True, "retryable": False,
                "stop_code": "context_memory_revision_unavailable",
                "error": f"context memory revision unavailable: {type(exc).__name__}",
                "context": "", "evidence": [],
            }
        project_config_digest = ""
        retrieval_weights: dict[str, float] = {}
        request_path_hints = tuple(getattr(request, "path_hints", ()))
        request_directory_hints = tuple(getattr(request, "directory_hints", ()))
        request_exclude_paths = tuple(getattr(request, "exclude_paths", ()))
        request_force_include_paths = tuple(getattr(request, "force_include_paths", ()))
        effective_path_hints = request_path_hints
        if mode in {"full", "adaptive"}:
            from .project_config import ProjectConfigError, resolve_project_context

            try:
                project_context = resolve_project_context(
                    request.root,
                    configured_state_dir(getattr(self, "config", {}), create=False),
                )
                project_config_digest = str(project_context.config_digest or "")[:200]
                retrieval_weights = dict(project_context.settings.retrieval_weights)
                from .context_identity import normalize_context_path_hints
                from .task_context import _project_context_hint_groups

                pinned_hints, entry_hints, saved_hints = _project_context_hint_groups(
                    project_context,
                    project_root=Path(request.root).expanduser().resolve(strict=False),
                    repository_revision="",
                    config_digest=project_config_digest,
                )
                effective_path_hints = normalize_context_path_hints(
                    (*pinned_hints, *entry_hints, *request_path_hints, *saved_hints)
                )
            except ProjectConfigError as exc:
                return {
                    "success": False, "terminal": True, "retryable": False,
                    "stop_code": "context_project_config_invalid",
                    "error": f"context project configuration invalid: {type(exc).__name__}",
                    "context": "", "evidence": [],
                }
            except (RuntimeError, ValueError) as exc:
                return {
                    "success": False, "terminal": True, "retryable": False,
                    "stop_code": "context_project_hints_invalid",
                    "error": f"context project hints invalid: {type(exc).__name__}",
                    "context": "", "evidence": [],
                }
        retrieval_config = {
            "search": getattr(self, "config", {}).get("search", {}),
            "features": getattr(self, "config", {}).get("features", {}),
            "preprocessing": getattr(self, "config", {}).get("preprocessing", {}),
            "rag": getattr(self, "config", {}).get("rag", {}),
            "retrieval": getattr(self, "config", {}).get("retrieval", {}),
            "external_tools": getattr(self, "config", {}).get("external_tools", {}),
            "code_intelligence": getattr(self, "config", {}).get("code_intelligence", {}),
            "project_config_digest": project_config_digest,
            "retrieval_weights": retrieval_weights,
        }
        retrieval_config_revision = stable_hash(retrieval_config)
        context_cache_identity = {
            "mode": mode,
            "task_id": request.task_id,
            "session_id": request.session_id,
            "tenant": request.tenant,
            "workspace": request.workspace,
            "phase": request.phase,
            "query": request.query,
            "focus": request.focus,
            "changed_paths": request.changed_paths,
            "path_hints": effective_path_hints,
            "directory_hints": request_directory_hints,
            "exclude_paths": request_exclude_paths,
            "force_include_paths": request_force_include_paths,
            "preload_profile": request.preload_profile,
            "token_budget": request.token_budget,
            "base": request.base,
            "staged": request.staged,
            "memory_revision": memory_revision,
            "retrieval_config_revision": retrieval_config_revision,
            "project_config_digest": project_config_digest,
            "retrieval_weights": retrieval_weights,
            "since_hash": since_hash,
            "approval": request.approval,
            "override_reason": request.override_reason,
        }
        if mode in {"full", "adaptive"}:
            base = self._hybrid_context(
                request.root,
                request.query,
                request.tenant,
                request.workspace or None,
                request.token_budget,
                quality_first=mode == "adaptive",
                context_identity=context_cache_identity,
                path_hints=effective_path_hints if mode == "adaptive" else (),
                directory_hints=request_directory_hints if mode == "adaptive" else (),
                exclude_paths=request_exclude_paths if mode == "adaptive" else (),
                force_include_paths=request_force_include_paths if mode == "adaptive" else (),
                focus=request.focus,
                changed_paths=request.changed_paths,
                retrieval_weights=retrieval_weights if mode == "adaptive" else None,
            )
        else:
            base = self.fast_context(request.root, request.query, request.token_budget)
        if not isinstance(base, dict):
            base = {"success": False, "context": "", "evidence": []}
        else:
            base = dict(base)
        raw_evidence = base.get("evidence")
        if isinstance(raw_evidence, list):
            normalized_evidence = []
            for item in raw_evidence:
                if not isinstance(item, dict):
                    continue
                evidence_item = dict(item)
                if not evidence_item.get("evidence_id"):
                    text_value = evidence_item.get("text", evidence_item.get("content", ""))
                    evidence_item["evidence_id"] = "local-" + stable_hash({
                        "root": canonical_root(request.root),
                        "path": evidence_item.get("path", ""),
                        "symbol": evidence_item.get("symbol", ""),
                        "start_line": evidence_item.get("start_line", evidence_item.get("line", 0)),
                        "end_line": evidence_item.get("end_line", evidence_item.get("start_line", evidence_item.get("line", 0))),
                        "content_hash": evidence_item.get("content_hash") or stable_hash(str(text_value)),
                        "revision": evidence_item.get("repository_revision", evidence_item.get("revision", "")),
                    })[:24]
                normalized_evidence.append(evidence_item)
            base["evidence"] = merge_overlapping_evidence(normalized_evidence, root=request.root)
        base, preload_warnings = self._apply_context_preloads(request, base)
        guard = self.consistency_guard
        if guard is None:
            context_id = stable_hash({
                "root": canonical_root(request.root),
                "repository_revision": base.get("repo_revision", base.get("revision", "")),
                **context_cache_identity,
                "evidence_ids": tuple(str(item.get("evidence_id") or "") for item in base.get("evidence", ()) if isinstance(item, dict)),
                "retrieval_revision": (base.get("retrieval") or {}).get("rag_revision", "") if isinstance(base.get("retrieval"), dict) else "",
            })[:24]
            pack = AdaptiveContextPack(
                context_id=context_id, phase=request.phase, focus=request.focus,
                changed_paths=tuple(request.changed_paths), preload_profile=request.preload_profile,
                memory_revision=memory_revision, warnings=preload_warnings,
            ).to_dict()
            return {**base, "guarded": False, "context_id": context_id, "context_pack": pack}

        revision = ""
        try:
            # Use the bounded worktree fingerprint for guarded provenance.  The
            # GitSnapshot revision is HEAD-only, which makes dirty working-tree
            # receipts look stale even when the indexed evidence is current.
            state = self.repo_state.fingerprint(request.root, force=True)
            if isinstance(state, dict) and not state.get("degraded") and not state.get("stale"):
                revision = str(state.get("fingerprint", "") or "")[:200]
        except Exception:
            pass
        try:
            snapshot = self.repo_tools.git_snapshot(request.root)
            if not revision:
                revision = str(getattr(snapshot, "revision", "") or "")[:200]
            snapshot_paths = tuple(str(path) for path in (getattr(snapshot, "changed_paths", ()) or ()))[:64]
        except Exception:
            snapshot_paths = ()
        evidence = tuple(item for item in (base.get("evidence") or ()) if isinstance(item, dict))[:24]
        changed_paths = tuple(request.changed_paths or base.get("changed_paths") or snapshot_paths)[:64]
        if since_hash and since_hash == revision:
            changed_paths = ()
        contract = guard.build_contract(request)
        candidates = tuple(guard.find_reuse_candidates(request, contract))[:24]
        mappings, mapping_warnings = guard.build_contract_mappings(request, evidence)
        diff: Any = None
        try:
            diff = self.repo_tools.git_diff(request.root, base=request.base, staged=request.staged, max_tokens=request.token_budget)
            if since_hash and isinstance(diff, dict):
                diff = {**diff, "diff_sha256": since_hash}
        except Exception:
            pass
        drift_warnings = guard.check_drift(request, contract, changed_paths, diff)
        warnings = tuple(dict.fromkeys((*preload_warnings, *mapping_warnings, *drift_warnings)))[:24]
        boundary = any(item.requires_approval or item.severity.lower() in {"boundary", "high", "high-risk"} for item in warnings)
        stop_code = self._guard_stop_code(request, boundary)
        if stop_code:
            warning_payload = [
                warning.to_dict() if hasattr(warning, "to_dict") else dict(warning)
                for warning in warnings
            ]
            return {
                **base,
                "success": False,
                "guarded": True,
                "delivery_mode": mode,
                "terminal": True,
                "retryable": False,
                "stop_code": stop_code,
                "error": f"guarded context stopped: {stop_code}",
                "warnings": warning_payload[:24],
                "repo_revision": revision,
                "changed_paths": list(changed_paths),
                "task_status": "",
                "waiting": False,
            }
        relevance = self._adaptive_relevance(request, evidence, revision, memory_revision)
        retrieval_report = dict(base.get("retrieval") or {})
        backend_states = dict(retrieval_report.get("backend_states") or {})
        model_state = (
            "used" if isinstance(relevance, dict) and relevance.get("success")
            else "skipped" if isinstance(relevance, dict) and relevance.get("degraded_reason") == "no_authoritative_evidence"
            else "degraded"
        )
        backend_states["local_model"] = model_state
        retrieval_report["backend_states"] = dict(sorted(backend_states.items()))
        retrieval_report["used_backends"] = sorted(name for name, state in backend_states.items() if state == "used")
        retrieval_report["skipped_backends"] = sorted(name for name, state in backend_states.items() if state == "skipped")
        retrieval_report["degraded_backends"] = sorted(name for name, state in backend_states.items() if state == "degraded")
        base["retrieval"] = retrieval_report
        metric = getattr(guard, "record_metric", None)
        if callable(metric):
            if since_hash and since_hash == revision:
                metric("duplicate_context_reuse")
            if not isinstance(relevance, dict) or not relevance.get("success"):
                metric("degraded_local_model_fallback")
            relevance_warnings = tuple(relevance.get("warnings", ())) if isinstance(relevance, dict) else ()
            for warning in relevance_warnings:
                severity = getattr(warning, "severity", None)
                if severity is None and isinstance(warning, dict):
                    severity = warning.get("severity", "warning")
                metric("warning", severity=str(severity or "warning"))
        model_warnings = tuple(relevance.get("warnings", ()))[:24] if isinstance(relevance, dict) else ()
        pack = AdaptiveContextPack(
            contract=contract,
            reuse_candidates=candidates,
            mappings=tuple(mappings),
            warnings=warnings,
            evidence=evidence,
            repo_revision=revision,
            changed_paths=changed_paths,
            stale=False,
            context_id=stable_hash({
                "root": canonical_root(request.root),
                "repository_revision": revision,
                "changed_paths": changed_paths,
                **context_cache_identity,
                "evidence_ids": tuple(str(item.get("evidence_id") or "") for item in evidence if isinstance(item, dict)),
                "retrieval_revision": (base.get("retrieval") or {}).get("rag_revision", "") if isinstance(base.get("retrieval"), dict) else "",
            })[:24],
            phase=request.phase,
            focus=request.focus,
            preload_profile=request.preload_profile,
            memory_revision=memory_revision,
            model_warnings=model_warnings,
        )
        pack_data = pack.to_dict()
        unchanged = bool(since_hash and since_hash == revision)
        ordinary = any(not (item.requires_approval or item.severity.lower() in {"boundary", "high", "high-risk"}) for item in warnings)
        decision_recorded, decision_persisted = self._guard_decision(request, revision, reason=request.override_reason, approval=request.approval)
        if (str(request.override_reason or "").strip() or self._guard_truthy(request.approval)) and not decision_persisted:
            return {
                **base, "success": False, "terminal": True, "retryable": False,
                "stop_code": "context_decision_persistence_failed",
                "error": "context decision could not be persisted", "context": "", "evidence": [],
            }
        try:
            task_status, waiting = self._guard_task_state(request, warnings, revision)
        except Exception as exc:
            return {
                **base, "success": False, "terminal": True, "retryable": False,
                "stop_code": "context_task_state_unavailable",
                "error": f"context task state unavailable: {type(exc).__name__}",
                "context": "", "evidence": [],
            }
        approved = self._guard_truthy(request.approval) or self._guard_existing_approval(request)
        if str(task_status).lower() == "waiting":
            approved = False
        result = dict(base)
        result.update({
            "query": request.query,
            "guarded": True,
            "delivery_mode": mode,
            "adaptive_context_pack": pack_data,
            "context_pack": pack_data,
            "contract": pack_data["contract"],
            "reuse": pack_data["reuse_candidates"],
            "reuse_candidates": pack_data["reuse_candidates"],
            "mappings": pack_data["mappings"],
            "warnings": [*pack_data["warnings"], *list(model_warnings)][:24],
            "evidence_ids": list(dict.fromkeys(item.get("evidence_id", "") for item in evidence if item.get("evidence_id")))[:24],
            "warning_ids": list(dict.fromkeys(
                evidence_id
                for item in (*warnings, *model_warnings)
                for evidence_id in (item.evidence_ids if hasattr(item, "evidence_ids") else item.get("evidence_ids", ()) if isinstance(item, dict) else ())
            ))[:24],
            "model_warnings": list(model_warnings),
            "relevance": {
                key: relevance.get(key)
                for key in ("selected_evidence_ids", "claims", "unknowns", "gaps", "wording")
                if isinstance(relevance, dict) and key in relevance
            },
            "model_degraded": bool(not isinstance(relevance, dict) or not relevance.get("success")),
            "model_degraded_reason": str(relevance.get("degraded_reason", ""))[:120] if isinstance(relevance, dict) else "relevance_error",
            "repo_revision": revision,
            "unchanged": unchanged,
            "reuse_pointer": pack.context_id if unchanged else "",
            "memory_revision": memory_revision,
            "changed_paths": list(changed_paths),
            "since_hash": str(since_hash)[:200],
            "delta_from": str(since_hash)[:200] if since_hash else "",
            "requires_override": bool(ordinary and not str(request.override_reason or "").strip() and not approved),
            "requires_approval": bool(boundary and not approved),
            "decision_recorded": bool(decision_recorded),
            "decision_persisted": bool(decision_persisted),
            "task_status": task_status,
            "waiting": bool(waiting),
        })
        snapshotter = getattr(getattr(self, "telemetry", None), "record_snapshot", None)
        metrics_getter = getattr(guard, "metrics_snapshot", None)
        if callable(snapshotter) and callable(metrics_getter):
            try:
                snapshotter("consistency_guard", metrics_getter())
            except Exception:
                pass
        return result

    def fast_context(self, root: str, query: str, max_tokens: int) -> dict[str, Any]:
        """Return bounded deterministic context when foreground SLO excludes hybrid retrieval."""
        if self.deterministic is None:
            return {"success": False, "terminal": True, "retryable": False, "error": "deterministic context is unavailable"}
        dcfg = self.config.get("deterministic", {})
        char_budget = min(int(dcfg.get("context_max_chars", 5200)), max(900, int(max_tokens) * 4))
        packed = self._repo_cached(
            "fast-context", root,
            {"query": query, "max_chars": char_budget, "raw": int(dcfg.get("context_raw_evidence", 5))},
            lambda: self.deterministic.context_pack(
                root, query, max_chars=char_budget,
                max_raw_evidence=int(dcfg.get("context_raw_evidence", 5)),
            ),
        )
        if isinstance(packed, dict):
            packed["context_source"] = "deterministic-fast"
            packed["degraded"] = True
            packed["continuation"] = {
                "available": True, "mode": "adaptive",
                "hint": "Retry the adaptive context pack when deterministic-only context is insufficient.",
            }
        return packed

    def _hybrid_context(
        self,
        root: str,
        query: str,
        tenant: str,
        workspace: str | None,
        max_tokens: int,
        *,
        quality_first: bool = False,
        context_identity: dict[str, Any] | None = None,
        path_hints: tuple[dict[str, str], ...] = (),
        directory_hints: tuple[str, ...] = (),
        exclude_paths: tuple[str, ...] = (),
        force_include_paths: tuple[str, ...] = (),
        focus: tuple[str, ...] = (),
        changed_paths: tuple[str, ...] = (),
        retrieval_weights: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        resolved_root = Path(root).expanduser().resolve(strict=False)
        if not resolved_root.is_dir():
            return {
                "success": False,
                "root": str(resolved_root),
                "query": query,
                "stale_root": True,
                "degraded": True,
                "error_type": "ValueError",
                "error": f"root directory does not exist: {resolved_root}",
                "context": "",
                "evidence": [],
            }
        if quality_first and "project_config_digest" not in (context_identity or {}):
            from .project_config import ProjectConfigError, resolve_project_context

            try:
                project_context = resolve_project_context(
                    resolved_root,
                    configured_state_dir(getattr(self, "config", {}), create=False),
                )
                project_config_digest = str(project_context.config_digest or "")[:200]
                configured_weights = dict(project_context.settings.retrieval_weights)
                if retrieval_weights is None:
                    retrieval_weights = configured_weights
                from .context_identity import normalize_context_path_hints
                from .task_context import _project_context_hint_groups

                pinned_hints, entry_hints, saved_hints = _project_context_hint_groups(
                    project_context,
                    project_root=resolved_root,
                    repository_revision="",
                    config_digest=project_config_digest,
                )
                path_hints = normalize_context_path_hints(
                    (*pinned_hints, *entry_hints, *path_hints, *saved_hints)
                )
                identity = dict(context_identity or {})
                identity.update({
                    "path_hints": path_hints,
                    "project_config_digest": project_config_digest,
                    "retrieval_weights": retrieval_weights or {},
                    "directory_hints": directory_hints,
                    "exclude_paths": exclude_paths,
                    "force_include_paths": force_include_paths,
                    "focus": focus,
                    "changed_paths": changed_paths,
                })
                try:
                    from .agent_consistency import ConsistencyRequest

                    memory_revision = self._adaptive_memory_revision(ConsistencyRequest(
                        root=str(resolved_root), query=query, tenant=tenant,
                        workspace=workspace or "", token_budget=max_tokens,
                    ))
                except Exception:
                    memory_revision = ""
                identity["memory_revision"] = memory_revision
                context_identity = identity
            except ProjectConfigError as exc:
                return {
                    "success": False, "terminal": True, "retryable": False,
                    "stop_code": "context_project_config_invalid",
                    "error": f"context project configuration invalid: {type(exc).__name__}",
                    "context": "", "evidence": [],
                }
            except (RuntimeError, ValueError) as exc:
                return {
                    "success": False, "terminal": True, "retryable": False,
                    "stop_code": "context_project_hints_invalid",
                    "error": f"context project hints invalid: {type(exc).__name__}",
                    "context": "", "evidence": [],
                }
        # Deterministic fallback remains internal to adaptive retrieval. The adaptive
        # path bypasses this early return so independent backends can cross-check the pack.
        if self.deterministic is not None and not quality_first:
            try:
                det = self.deterministic_query(root, query, 30)
                dcfg = self.config.get("deterministic", {})
                enough = (
                    det.get("success")
                    and float(det.get("confidence", 0.0) or 0.0) >= float(dcfg.get("context_confidence", 0.80))
                    and bool(det.get("facts") or det.get("dependencies") or det.get("scripts") or det.get("evidence") or det.get("code_index"))
                )
                if enough:
                    char_budget = min(
                        int(dcfg.get("context_max_chars", 5200)),
                        max(900, int(max_tokens) * 4),
                    )
                    packed = self._repo_cached(
                        "deterministic-context", root,
                        {"query": query, "max_chars": char_budget, "raw": int(dcfg.get("context_raw_evidence", 5))},
                        lambda: self.deterministic.context_pack(
                            root, query, max_chars=char_budget,
                            max_raw_evidence=int(dcfg.get("context_raw_evidence", 5)),
                        ),
                    )
                    if isinstance(packed, dict):
                        packed["context_source"] = "deterministic"
                    return packed
            except Exception:
                pass
        rag_enabled = self.rag is not None and self.config.get("features", {}).get("rag", True)
        try:
            rag_revision = self.rag.revision(tenant, workspace or self.rag.workspace_id(root)) if rag_enabled else None
            rag_revision_available = not rag_enabled or bool(str(rag_revision or "").strip())
        except Exception:
            # RAG is optional. Its revision store failing must not prevent the
            # deterministic and lexical context path from serving the request.
            rag_revision = None
            rag_revision_available = not rag_enabled
        compute = lambda: self._hybrid_context_uncached(
            root, query, tenant, workspace, max_tokens, quality_first=quality_first,
            rag_revision=str(rag_revision or ""), rag_revision_available=rag_revision_available,
            path_hints=path_hints, directory_hints=directory_hints,
            exclude_paths=exclude_paths, force_include_paths=force_include_paths,
            focus=focus, changed_paths=changed_paths,
            retrieval_weights=retrieval_weights,
        )
        if rag_enabled and not rag_revision_available:
            result = compute()
            if isinstance(result, dict):
                result["workspace_cache"] = {"hit": False, "coalesced": False, "degraded": True, "stale": False, "kind": "rag-revision-unavailable"}
                result["cache_hit"] = False
                result["coalesced"] = False
                result["cache_layer"] = "workspace-bypassed"
        else:
            result = self._repo_cached(
                "hybrid-context", root,
                {
                    "query": query,
                    "workspace": workspace,
                    "max_tokens": max_tokens,
                    "rag_revision": rag_revision,
                    "quality_first": quality_first,
                    "context_identity": context_identity or {},
                    "path_hints": path_hints,
                    "directory_hints": directory_hints,
                    "exclude_paths": exclude_paths,
                    "force_include_paths": force_include_paths,
                    "retrieval_weights": retrieval_weights or {},
                },
                compute,
            )
        if isinstance(result, dict): result.setdefault("context_source", "adaptive-hybrid" if quality_first else "hybrid")
        return result

    @staticmethod
    def _rrf_fuse(lexical_ranked: list[str], vector_ranked: list[str], k: int = 60) -> list[tuple[str, float]]:
        """Reciprocal Rank Fusion: RRF(d) = sum(1 / (k + rank_i(d)))."""
        scores: dict[str, float] = {}
        for rank, item in enumerate(lexical_ranked):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank + 1)
        for rank, item in enumerate(vector_ranked):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank + 1)
        return sorted(scores.items(), key=lambda x: x[1], reverse=True)

    @staticmethod
    def _external_candidate_paths(root: str, payload: Any) -> list[str]:
        """Extract safe, existing repository-relative paths from backend payloads."""
        root_path = Path(root).resolve(strict=False)
        path_keys = {"path", "relative_path", "file_path", "filename", "module_path", "source_path"}
        found: list[str] = []
        visited = 0

        def add_path(raw_path: str | Path) -> None:
            candidate_text = str(raw_path).strip()
            candidate = Path(candidate_text).expanduser()
            if not candidate.is_absolute():
                candidate = root_path / Path(candidate_text.replace("\\", "/"))
            try:
                resolved = candidate.resolve(strict=False)
                resolved.relative_to(root_path)
                if resolved.is_file():
                    relative = resolved.relative_to(root_path).as_posix()
                    if relative not in found:
                        found.append(relative)
            except (OSError, ValueError):
                pass

        def visit(value: Any) -> None:
            nonlocal visited
            if visited >= 500:
                return
            visited += 1
            if isinstance(value, dict):
                for key, item in value.items():
                    if str(key).lower() in path_keys and isinstance(item, (str, Path)):
                        add_path(item)
                    else:
                        if (
                            isinstance(key, str)
                            and ("/" in key or "\\" in key)
                            and isinstance(item, (dict, list, tuple))
                        ):
                            add_path(key)
                        visit(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    visit(item)

        visit(payload)
        return found

    def _external_context_candidates(
        self, root: str, query: str, *, timeout_budget: float | None = None
    ) -> tuple[dict[str, list[str]], list[str], dict[str, str]]:
        """Query optional structural backends concurrently; degrade per backend."""
        groups: dict[str, list[str]] = {}
        warnings: list[str] = []
        states: dict[str, str] = {}
        external = getattr(self, "external_tools", None)
        if external is None:
            return groups, warnings, {"serena": "skipped"}
        if getattr(external, "serena_enabled", True) is False:
            return groups, warnings, {"serena": "skipped"}
        try:
            terms = list(self.repo_tools.search_terms(query))[:8]
        except Exception:
            terms = []
        anchor_query = (terms[0] if terms else str(query)[:80]).strip()
        surface_match = re.search(re.escape(anchor_query), str(query), flags=re.IGNORECASE)
        if surface_match:
            anchor_query = surface_match.group(0)
        if not anchor_query:
            return groups, warnings, {"serena": "skipped"}

        def run(backend: str) -> tuple[str, list[str], str | None]:
            try:
                call_kwargs: dict[str, Any] = {"backend": backend, "action": "search", "limit": 12}
                try:
                    import inspect
                    sig = inspect.signature(external.query).parameters
                    if "soft_timeout" in sig:
                        call_kwargs["soft_timeout"] = timeout
                    elif "timeout" in sig:
                        call_kwargs["timeout"] = timeout
                except Exception:
                    pass
                response = external.query(root, anchor_query, **call_kwargs)
                if not isinstance(response, dict):
                    return backend, [], f"{backend} malformed response"
                if response.get("success") is False:
                    return backend, [], f"{backend} unavailable"
                result_keys = ("result", "results", "data", "matches", "items", "paths", "symbols")
                result_key = next((key for key in result_keys if key in response), None)
                payload = response.get(result_key) if result_key else None
                if result_key is None or not isinstance(payload, (dict, list, tuple)):
                    return backend, [], f"{backend} malformed response"
                return backend, self._external_candidate_paths(root, response), None
            except Exception as exc:
                return backend, [], f"{backend} degraded: {type(exc).__name__}"

        search_cfg = getattr(self, "config", {}).get("search", {})
        configured_timeout = search_cfg.get("context_backend_timeout_seconds")
        timeout = configured_timeout if configured_timeout is not None else 3.0
        try:
            timeout = max(0.05, min(float(timeout), 120.0))
        except (TypeError, ValueError):
            timeout = 3.0
        if timeout_budget is not None:
            try:
                timeout = min(timeout, max(0.0, float(timeout_budget)))
            except (TypeError, ValueError, OverflowError):
                timeout = 0.0
        if timeout <= 0.0:
            return groups, warnings, {"serena": "skipped"}
        futures = {
            _CONTEXT_BACKEND_POOLS[backend].submit(run, backend): backend
            for backend in ("serena",)
        }
        done, pending = wait(futures, timeout=timeout)
        for future in done:
            backend = futures[future]
            try:
                backend, paths, warning = future.result()
            except Exception as exc:
                paths, warning = [], f"{backend} degraded: {type(exc).__name__}"
            states[backend] = "degraded" if warning else "used"
            if paths:
                groups[backend] = paths
            if warning:
                warnings.append(warning)
        for future in pending:
            backend = futures[future]
            future.cancel()
            states[backend] = "degraded"
            warnings.append(f"{backend} timeout")
        # Cancellation is best-effort for a running thread. The persistent
        # per-backend lane bounds stragglers without delaying this request.
        return groups, warnings, states

    @staticmethod
    def _adaptive_builtin_confidence(
        deterministic_result: dict[str, Any] | None,
        path_groups: dict[str, list[str]],
    ) -> float:
        """Require deterministic confidence plus independent index agreement."""
        if not isinstance(deterministic_result, dict) or deterministic_result.get("success") is not True:
            return 0.0
        if not any(
            deterministic_result.get(key)
            for key in ("facts", "dependencies", "scripts", "evidence", "code_index", "test_candidates")
        ):
            return 0.0
        try:
            confidence = float(deterministic_result.get("confidence", 0.0))
        except (TypeError, ValueError, OverflowError):
            return 0.0
        if not 0.0 <= confidence <= 1.0:
            return 0.0
        deterministic_paths = {str(path) for path in path_groups.get("deterministic", []) if path}
        indexed_paths = {str(path) for path in path_groups.get("code_index", []) if path}
        union = deterministic_paths | indexed_paths
        agreement = len(deterministic_paths & indexed_paths) / len(union) if union else 0.0
        return min(confidence, agreement)

    def _hybrid_context_uncached(
        self,
        root: str,
        query: str,
        tenant: str,
        workspace: str | None,
        max_tokens: int,
        *,
        quality_first: bool = False,
        rag_revision: str = "",
        rag_revision_available: bool = True,
        path_hints: tuple[dict[str, str], ...] = (),
        directory_hints: tuple[str, ...] = (),
        exclude_paths: tuple[str, ...] = (),
        force_include_paths: tuple[str, ...] = (),
        focus: tuple[str, ...] = (),
        changed_paths: tuple[str, ...] = (),
        retrieval_weights: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        search_cfg = self.config.get("search", {})

        def bounded_timeout(key: str, default: float) -> float:
            try:
                return max(0.05, min(float(search_cfg.get(key, default)), 120.0))
            except (TypeError, ValueError, OverflowError):
                return default

        backend_deadline = started_at + max(
            bounded_timeout("context_backend_timeout_seconds", 3.0),
            bounded_timeout("context_rag_timeout_seconds", 3.0),
        )
        if self.learner is not None:
            try: self.learner.record(root, query)
            except Exception: pass
        target_workspace = workspace
        rag_setup_error: str | None = None
        if self.rag is not None and self.config.get("features", {}).get("rag", True) and not target_workspace:
            try:
                candidate = self.rag.workspace_id(root)
                known = {
                    str(item.get("workspace", ""))
                    for item in self.rag.list_workspaces(tenant)
                    if isinstance(item, dict)
                }
                if candidate in known:
                    target_workspace = candidate
            except Exception as exc:
                rag_setup_error = f"rag workspace unavailable: {type(exc).__name__}"

        rag_configured = self.rag is not None and self.config.get("features", {}).get("rag", True)
        retrieval_warnings: list[str] = [rag_setup_error] if rag_setup_error else []
        if rag_configured and not rag_revision_available:
            retrieval_warnings.append("rag revision unavailable; cache bypassed")
        rag_pool = None
        rag_future = None
        semantic_fraction = max(0.0, min(float(search_cfg.get("semantic_fraction", 0.35)), 0.7))
        lexical_tokens = max_tokens if not target_workspace else max(512, int(max_tokens * (1.0 - semantic_fraction)))
        # Local AI: deterministic/semantic paths are ranking hints only. Keep lexical
        # search repository-wide so one hit in a hinted file cannot hide other candidates.
        candidate_paths: list[str] = []
        path_groups: dict[str, list[str]] = {}
        backend_states: dict[str, str] = {}
        deterministic_result: dict[str, Any] | None = None
        # Prioritize files explicitly named in the query/task (e.g. AGENTS.md, src/main.py)
        root_path = Path(root)
        explicit_paths: list[str] = []
        for token in query.split():
            clean_tok = token.strip("`'\"(),:;[]{}*")
            if clean_tok and ("." in clean_tok or "/" in clean_tok or "\\" in clean_tok):
                try:
                    rel_p = clean_tok.replace("\\", "/").lstrip("./")
                    if (root_path / rel_p).exists() and rel_p not in explicit_paths:
                        explicit_paths.append(rel_p)
                except Exception:
                    pass
        if explicit_paths:
            path_groups["explicit"] = explicit_paths
        if self.deterministic is not None:
            try:
                if quality_first:
                    try:
                        deterministic_result = self.deterministic_query(root, query, 30)
                    except Exception:
                        deterministic_result = None
                related_kwargs: dict[str, Any] = {"limit": 28}
                if deterministic_result is not None:
                    try:
                        import inspect

                        parameters = inspect.signature(self.deterministic.related_paths).parameters
                        if "result" in parameters or any(
                            parameter.kind == parameter.VAR_KEYWORD for parameter in parameters.values()
                        ):
                            related_kwargs["result"] = deterministic_result
                    except Exception:
                        pass
                path_groups["deterministic"] = list(self.deterministic.related_paths(root, query, **related_kwargs))
                backend_states["deterministic"] = "used"
            except Exception as exc:
                backend_states["deterministic"] = "degraded"
                retrieval_warnings.append(f"deterministic degraded: {type(exc).__name__}")
        else:
            backend_states["deterministic"] = "skipped"
        if self.code_index is not None:
            try:
                path_groups["code_index"] = list(self.code_index.related_paths(root, query, limit=24))
                backend_states["code_index"] = "used"
            except Exception as exc:
                backend_states["code_index"] = "degraded"
                retrieval_warnings.append(f"code_index degraded: {type(exc).__name__}")
        else:
            backend_states["code_index"] = "skipped"
        if self.preprocessor is not None:
            try:
                path_groups["preprocessor"] = list(self.preprocessor.candidate_paths(
                    root, query, limit=max(12, int(self.config.get("preprocessing", {}).get("lookup_file_cards", 5)) * 4)
                ))
                backend_states["preprocessor"] = "used"
            except Exception:
                # Keep already-resolved deterministic/code-index candidates. One
                # optional preprocessing failure must not force a full repository scan.
                backend_states["preprocessor"] = "degraded"
                retrieval_warnings.append("preprocessor degraded")
        else:
            backend_states["preprocessor"] = "skipped"
        confidence = self._adaptive_builtin_confidence(deterministic_result, path_groups) if quality_first else 0.0
        try:
            confidence_threshold = max(
                0.0,
                min(float(self.config.get("deterministic", {}).get("context_confidence", 0.80)), 1.0),
            )
        except (TypeError, ValueError, OverflowError):
            confidence_threshold = 0.80
        confident_builtin = quality_first and confidence >= confidence_threshold
        remaining_budget = max(0.0, backend_deadline - time.perf_counter())
        request_optional = not confident_builtin
        rag_ready = bool(
            rag_configured and target_workspace and query.strip() and rag_revision_available
        )
        requested_backends: list[str] = []
        external_tools = getattr(self, "external_tools", None)
        serena_enabled = external_tools is not None and getattr(external_tools, "serena_enabled", True) is not False
        if quality_first and request_optional and serena_enabled:
            requested_backends.append("serena")
        if rag_ready and request_optional:
            requested_backends.append("rag")
        if rag_ready and request_optional and remaining_budget > 0.0:
            rag_pool = _CONTEXT_BACKEND_POOLS["rag"]
            reranker_obj = getattr(self, "reranker", None) or getattr(getattr(self, "rag", None), "reranker", None)
            active_device = str(getattr(reranker_obj, "active_device", "") or getattr(reranker_obj, "device", "") or "").strip().lower()
            rag_use_reranker = (
                bool(self.config.get("rag", {}).get("use_reranker", True))
                and not (reranker_obj and active_device == "cpu")
            )
            rag_future = rag_pool.submit(
                self.rag.search, query, tenant, target_workspace,
                top_k=10, use_reranker=rag_use_reranker,
            )
        elif rag_ready and request_optional:
            backend_states["rag"] = "skipped"
        elif rag_configured and not rag_revision_available:
            backend_states["rag"] = "degraded"
        else:
            backend_states["rag"] = "skipped"
        if confident_builtin:
            backend_states["serena"] = "skipped"
        elif quality_first and remaining_budget <= 0.0:
            backend_states["serena"] = "skipped"
        elif quality_first:
            external_groups, external_warnings, external_states = self._external_context_candidates(
                root, query, timeout_budget=remaining_budget,
            )
            path_groups.update(external_groups)
            backend_states.update(external_states)
            retrieval_warnings.extend(external_warnings)
        else:
            backend_states.update({"serena": "skipped", "rag": "skipped"})
        selected_backends = requested_backends if remaining_budget > 0.0 else []
        if confident_builtin:
            selection_decision = "builtin_confident"
        elif requested_backends and remaining_budget <= 0.0:
            selection_decision = "deadline_exhausted"
        elif selected_backends:
            selection_decision = "optional_backends_selected"
        else:
            selection_decision = "no_optional_backend_available"
        backend_selection = {
            "decision": selection_decision,
            "confidence": round(confidence, 4),
            "threshold": round(confidence_threshold, 4),
            "selected_backends": selected_backends,
            "remaining_budget_ms": round(remaining_budget * 1000, 3),
        }
        hinted_paths = [
            str(item.get("path", "")) if isinstance(item, dict) else item
            for item in path_hints
            if (isinstance(item, dict) and item.get("path")) or isinstance(item, str)
        ]
        if hinted_paths:
            path_groups["project_hints"] = hinted_paths
        if directory_hints:
            path_groups["directory_hints"] = list(directory_hints)
        if force_include_paths:
            path_groups["force_include"] = list(force_include_paths)

        def path_matches(path: str, patterns: tuple[str, ...]) -> bool:
            normalized = path.replace("\\", "/").strip("/").casefold()
            basename = normalized.rsplit("/", 1)[-1]
            for pattern in patterns:
                pattern = pattern.replace("\\", "/").strip("/").casefold()
                if not pattern:
                    continue
                if any(char in pattern for char in "*?["):
                    if fnmatch.fnmatchcase(normalized, pattern) or fnmatch.fnmatchcase(basename, pattern):
                        return True
                elif normalized == pattern or normalized.startswith(pattern + "/"):
                    return True
            return False

        def excluded_path(path: str) -> bool:
            return path_matches(path, exclude_paths)

        def safe_relative_candidate(raw_path: Any, base_path: Path) -> str | None:
            value = str(raw_path or "").strip()
            if not value:
                return None
            try:
                candidate = Path(value)
                candidate = candidate if candidate.is_absolute() else base_path / candidate
                lexical_relative = candidate.relative_to(base_path)
                if ".." in lexical_relative.parts:
                    return None
                current = base_path
                for part in lexical_relative.parts:
                    current = current / part
                    if current.is_symlink():
                        return None
                resolved = candidate.resolve(strict=False)
                relative = resolved.relative_to(base_path)
            except (OSError, RuntimeError, ValueError):
                return None
            normalized = relative.as_posix().strip("/")
            return normalized if normalized and normalized != "." else None

        inventory_candidate_limit = 512
        inventory_scan_limit = 4096
        try:
            fallback_scan_limit = max(1, min(512, int(search_cfg.get("context_fallback_scan_limit", 512))))
        except (TypeError, ValueError, OverflowError):
            fallback_scan_limit = 512
        path_inventory_state = "skipped"
        recall_paths: tuple[str, ...] = ()
        path_controls_active = bool(
            path_hints or directory_hints or exclude_paths or force_include_paths or focus or changed_paths
        )
        forced_candidate_paths: tuple[str, ...] = ()
        if path_controls_active:
            base_path = Path(root).expanduser().resolve(strict=False)
            forced_candidate_paths = tuple(dict.fromkeys(
                path for raw_path in force_include_paths
                if (path := safe_relative_candidate(raw_path, base_path))
            ))
            raw_inventory: Any = None
            inventory_source = ""
            indexed_paths = getattr(self.preprocessor, "indexed_paths", None)
            if callable(indexed_paths):
                try:
                    raw_inventory = indexed_paths(root)
                    inventory_source = "preprocessor"
                    path_inventory_state = "used"
                except Exception as exc:
                    retrieval_warnings.append(f"path inventory unavailable: {type(exc).__name__}")
            indexes_available = any(
                backend_states.get(name) == "used"
                for name in ("deterministic", "code_index", "preprocessor")
            )
            if raw_inventory is None and indexes_available:
                # Existing ranked backend results remain the bounded index candidate set.
                raw_inventory = ()
                path_inventory_state = "degraded"
                retrieval_warnings.append("path inventory unavailable; using ranked index candidates")
            elif (
                raw_inventory is not None
                and hasattr(raw_inventory, "__len__")
                and len(raw_inventory) == 0
                and not bool(getattr(self.preprocessor, "enabled", True))
            ):
                # A disabled preprocessor may expose an empty inventory method,
                # but that is not an indexed proof that the repository is empty.
                raw_inventory = self.repo_tools.iter_files(str(base_path))
                inventory_source = "filesystem_fallback"
                path_inventory_state = "degraded"
                retrieval_warnings.append("preprocessor disabled; using bounded filesystem fallback")
            elif raw_inventory is None:
                raw_inventory = self.repo_tools.iter_files(str(base_path))
                inventory_source = "filesystem_fallback"
                path_inventory_state = "degraded"
                retrieval_warnings.append("path inventory unavailable; bounded filesystem fallback")

            scan_limit = fallback_scan_limit if inventory_source == "filesystem_fallback" else inventory_scan_limit
            scope_patterns = tuple(dict.fromkeys((
                *hinted_paths, *directory_hints, *force_include_paths, *changed_paths,
            )))
            focus_terms = tuple(dict.fromkeys(
                term.casefold()
                for value in focus
                for term in re.findall(r"[a-zA-Z0-9_]{3,}", str(value))
            ))
            selected_inventory: list[str] = []
            other_inventory: list[str] = []
            inspected_count = 0
            try:
                for inspected, raw_path in enumerate(itertools.islice(raw_inventory, scan_limit)):
                    inspected_count = inspected + 1
                    candidate = safe_relative_candidate(raw_path, base_path)
                    if candidate is None:
                        continue
                    in_scope = (
                        not scope_patterns and not focus_terms
                    ) or path_matches(candidate, scope_patterns) or any(
                        term in candidate.casefold() for term in focus_terms
                    )
                    target = selected_inventory if in_scope else other_inventory
                    if candidate not in target and len(target) < inventory_candidate_limit:
                        target.append(candidate)
                    if len(selected_inventory) >= inventory_candidate_limit:
                        break
                if inventory_source == "filesystem_fallback" and inspected_count >= scan_limit:
                    retrieval_warnings.append("filesystem fallback candidate limit reached")
                if inventory_source != "filesystem_fallback" and inspected_count >= scan_limit:
                    raw_size = len(raw_inventory) if hasattr(raw_inventory, "__len__") else None
                    if raw_size is None or raw_size > scan_limit:
                        retrieval_warnings.append("indexed path candidate scan reached its bound")
                        path_inventory_state = "degraded"
            except Exception as exc:
                path_inventory_state = "degraded"
                retrieval_warnings.append(f"path inventory scan degraded: {type(exc).__name__}")
            recall_paths = tuple((
                *selected_inventory,
                *other_inventory[:max(0, inventory_candidate_limit - len(selected_inventory))],
            ))
            normalized_directories = tuple(dict.fromkeys(
                path for raw_path in directory_hints
                if (path := safe_relative_candidate(raw_path, base_path))
            ))
            if normalized_directories:
                directory_candidates = tuple(
                    candidate for candidate in recall_paths
                    if path_matches(candidate, normalized_directories)
                )
                if directory_candidates:
                    path_groups["directory_hints"] = list(directory_candidates)
            backend_states["path_inventory"] = path_inventory_state

        base_path = Path(root).expanduser().resolve(strict=False)
        forced_candidate_paths = tuple(dict.fromkeys((
            *forced_candidate_paths,
            *(path for raw_path in force_include_paths
              if (path := safe_relative_candidate(raw_path, base_path))),
        )))
        # Every backend and request hint is normalized against the same repository root.
        path_groups = {
            backend: list(dict.fromkeys(
                path for raw_path in paths
                if (path := safe_relative_candidate(raw_path, base_path))
            ))
            for backend, paths in path_groups.items()
        }
        if exclude_paths:
            path_groups = {
                backend: [path for path in paths if not excluded_path(path)]
                for backend, paths in path_groups.items()
            }
        changed_candidate_paths = tuple(dict.fromkeys(
            path for raw_path in changed_paths
            if (path := safe_relative_candidate(raw_path, Path(root).expanduser().resolve(strict=False)))
            and not excluded_path(path)
        ))
        all_candidate_paths = tuple(dict.fromkeys((
            *(path for paths in path_groups.values() for path in paths), *recall_paths,
            *changed_candidate_paths,
        )))
        focus_terms = tuple(dict.fromkeys(
            term.casefold()
            for value in focus
            for term in re.findall(r"[a-zA-Z0-9_]{3,}", str(value))
        ))
        focus_candidate_paths = tuple(
            path for path in all_candidate_paths
            if any(term in path.casefold() for term in focus_terms)
            and not excluded_path(path)
        )
        if changed_candidate_paths:
            path_groups["changed_paths"] = list(changed_candidate_paths)
        if focus_candidate_paths:
            path_groups["task_focus"] = list(focus_candidate_paths)
        pinned_paths = tuple(
            path
            for item in path_hints[:64]
            if isinstance(item, dict)
            and item.get("provenance") == "project_config:pinned_context"
            and isinstance(item.get("path"), str)
            and (path := safe_relative_candidate(item["path"], base_path))
        )
        source_priority_paths = tuple(dict.fromkeys((
            *pinned_paths, *forced_candidate_paths, *changed_candidate_paths, *focus_candidate_paths,
            *(path for raw_path in explicit_paths if (path := safe_relative_candidate(raw_path, base_path))),
        )))
        source_query = is_source_context_query(query)
        if source_query:
            path_groups = {
                backend: prioritize_source_context_paths(
                    paths, query, priority_paths=source_priority_paths,
                )
                for backend, paths in path_groups.items()
            }
        fused_candidates = fuse_ranked_paths(
            path_groups, limit=256 if source_query else 64, max_per_path=2,
        )
        if source_query:
            priority_keys = {path.casefold() for path in source_priority_paths}
            fused_candidates.sort(key=lambda item: (
                0 if item[0].replace("\\", "/").casefold() in priority_keys
                else 1 + source_context_path_tier(item[0]),
                -item[1],
                item[0],
            ))
            fused_candidates = fused_candidates[:64]
        # Pins survive ranking limits, but never become force-include authorization.
        candidate_paths = list(dict.fromkeys((
            *pinned_paths,
            *forced_candidate_paths,
            *changed_candidate_paths,
            *focus_candidate_paths,
            *(path for path, _score in fused_candidates),
            *recall_paths,
        )))
        candidate_paths = [
            path for raw_path in candidate_paths
            if (path := safe_relative_candidate(raw_path, base_path))
            and not excluded_path(path)
            and not ((base_path / path).is_dir() and any(
                candidate.startswith(path.rstrip("/") + "/") for candidate in recall_paths
            ))
        ]
        candidate_paths = candidate_paths[:inventory_candidate_limit]
        try:
            lexical_candidate_limit = max(1, min(64, int(search_cfg.get("context_top_k", 14))))
        except (TypeError, ValueError, OverflowError):
            lexical_candidate_limit = 14
        if path_controls_active and path_inventory_state != "used" and len(candidate_paths) < lexical_candidate_limit:
            # Hints bias candidate ordering; they must not turn a bounded adaptive
            # lookup into a search restricted to hinted paths. Fill sparse indexed
            # candidates with a bounded lexical pass, then apply explicit excludes.
            try:
                completion = self.repo_tools.search(
                    root,
                    query,
                    limit=lexical_candidate_limit,
                )
                if isinstance(completion, dict) and completion.get("success"):
                    candidate_paths.extend(
                        path
                        for item in completion.get("results", [])
                        if isinstance(item, dict)
                        and isinstance(item.get("path"), str)
                        and item.get("path")
                        and (path := safe_relative_candidate(item["path"], base_path))
                        and not excluded_path(path)
                    )
                    candidate_paths = list(dict.fromkeys(candidate_paths))
                else:
                    retrieval_warnings.append("lexical completeness pass unavailable")
            except Exception as exc:
                retrieval_warnings.append(f"lexical completeness pass degraded: {type(exc).__name__}")
        try:
            # A single backend path is only a ranking hint; preserve broad lexical
            # recall until retrieval has produced multiple bounded candidates.
            if candidate_paths and (path_controls_active or len(candidate_paths) > 1):
                candidate_paths = list(dict.fromkeys(candidate_paths))
                pack_kwargs: dict[str, Any] = {
                    "max_tokens": lexical_tokens,
                    "top_k": int(search_cfg.get("context_top_k", 14)),
                }
                if path_hints or directory_hints or exclude_paths or force_include_paths:
                    hinted_directories = tuple(dict.fromkeys((
                        *directory_hints,
                        *hinted_paths,
                    )))
                    pack_kwargs.update({
                        "directory_hints": hinted_directories,
                        "exclude_paths": exclude_paths,
                        "force_include_paths": force_include_paths,
                    })
                if source_query:
                    try:
                        import inspect

                        pack_signature = inspect.signature(self.repo_tools.context_pack_paths).parameters
                        supports_priority_paths = "priority_paths" in pack_signature or any(
                            parameter.kind == parameter.VAR_KEYWORD
                            for parameter in pack_signature.values()
                        )
                    except (TypeError, ValueError):
                        supports_priority_paths = False
                    if supports_priority_paths:
                        pack_kwargs["priority_paths"] = list(source_priority_paths)
                lexical = self.repo_tools.context_pack_paths(
                    root, query, candidate_paths, **pack_kwargs,
                )
            elif path_controls_active:
                lexical = {
                    "success": True, "root": str(root_path), "context": "", "evidence": [],
                    "scanned_files": 0, "targeted": True,
                }
            else:
                lexical = self.repo_tools.context_pack(
                    root, query, max_tokens=lexical_tokens,
                    top_k=int(search_cfg.get("context_top_k", 14)),
                )
        except Exception as exc:
            lexical = {"success": False, "error": f"lexical backend degraded: {type(exc).__name__}"}
        if not isinstance(lexical, dict) or not isinstance(lexical.get("evidence", []), list):
            lexical = {"success": False, "error": "lexical backend malformed response"}
        if not lexical.get("success"):
            if not quality_first:
                return lexical
            backend_states["lexical"] = "degraded"
            retrieval_warnings.append(str(lexical.get("error", "lexical backend unavailable"))[:240])
            lexical = {
                "success": True,
                "root": str(root_path),
                "context": "",
                "evidence": [],
                "scanned_files": 0,
            }
        else:
            backend_states["lexical"] = "used"
        evidence = list(lexical.get("evidence", []))
        path_groups["lexical"] = [str(item.get("path")) for item in evidence if item.get("path")]
        baseline_fused_evidence = fuse_ranked_paths(
            path_groups, limit=max(24, len(evidence)), max_per_path=2,
        )
        fused_evidence = baseline_fused_evidence
        if retrieval_weights:
            selected_paths = {path for path, _score in baseline_fused_evidence}
            selected_groups = {
                source: [path for path in paths if path in selected_paths]
                for source, paths in path_groups.items()
            }
            fused_evidence = fuse_ranked_paths(
                selected_groups,
                limit=max(1, len(selected_paths)),
                max_per_path=max(1, len(selected_paths)),
                source_weights=retrieval_weights,
            )
        evidence_rank = {path: rank for rank, (path, _score) in enumerate(fused_evidence)}
        if source_query:
            priority_keys = {path.replace("\\", "/").casefold() for path in source_priority_paths}

            def final_evidence_rank(item: dict[str, Any]) -> tuple[int, int, int, str]:
                path = str(item.get("path", ""))
                normalized_path = path.replace("\\", "/").casefold()
                return (
                    0 if normalized_path in priority_keys else 1,
                    source_context_path_tier(path),
                    evidence_rank.get(path, 999),
                    path,
                )

            evidence.sort(key=final_evidence_rank)
        else:
            evidence.sort(key=lambda item: (
                evidence_rank.get(str(item.get("path", "")), 999),
                str(item.get("path", "")),
            ))
        if self.evidence_store is not None:
            try:
                stored_evidence = self.evidence_store.put_many(str(lexical.get("root", root)), evidence)
            except Exception as exc:
                return {
                    "success": False, "terminal": True, "retryable": False,
                    "stop_code": "context_evidence_persistence_failed",
                    "error": f"context evidence persistence failed: {type(exc).__name__}",
                    "root": str(root), "query": query, "context": "", "evidence": [],
                }
            if not isinstance(stored_evidence, (list, tuple)) or any(
                not isinstance(item, dict) or not str(item.get("evidence_id") or "").strip()
                for item in stored_evidence
            ):
                return {
                    "success": False, "terminal": True, "retryable": False,
                    "stop_code": "context_evidence_receipt_incomplete",
                    "error": "context evidence receipt is missing or incomplete",
                    "root": str(root), "query": query, "context": "", "evidence": [],
                }
            evidence = list(stored_evidence)
        else:
            traceable: list[dict[str, Any]] = []
            for item in evidence:
                if not isinstance(item, dict):
                    continue
                traced = dict(item)
                if not str(traced.get("evidence_id") or "").strip():
                    traced["evidence_id"] = "local-" + stable_hash({
                        "root": canonical_root(str(lexical.get("root", root))),
                        "path": str(traced.get("path") or ""),
                        "symbol": str(traced.get("symbol") or ""),
                        "start_line": traced.get("start_line", 0),
                        "end_line": traced.get("end_line", 0),
                        "content_hash": traced.get("content_hash") or stable_hash(str(traced.get("text") or "")),
                    })[:24]
                traceable.append(traced)
            evidence = traceable
        context = str(lexical.get("context", ""))
        # Keep the already budgeted, exact lexical rendering intact; only move
        # its complete snippet blocks into the same order as their evidence.
        rendered_positions: list[tuple[int, int]] = []
        used_positions: set[int] = set()
        for evidence_index, item in enumerate(evidence):
            if not isinstance(item, dict) or not item.get("path"):
                rendered_positions = []
                break
            header = (
                f"--- {item['path']}:{item.get('start_line')}-{item.get('end_line')} "
                f"score={item.get('score')} ---\n"
            )
            position = context.find(header)
            while position in used_positions and position >= 0:
                position = context.find(header, position + 1)
            if position < 0:
                rendered_positions = []
                break
            rendered_positions.append((evidence_index, position))
            used_positions.add(position)
        source_order = sorted(rendered_positions, key=lambda item: item[1])
        if rendered_positions and len(rendered_positions) == len(evidence) and source_order[0][1] == 0:
            blocks: dict[int, str] = {}
            for offset, (evidence_index, start) in enumerate(source_order):
                end = source_order[offset + 1][1] if offset + 1 < len(source_order) else len(context)
                blocks[evidence_index] = context[start:end]
            context = "".join(blocks[index] for index in range(len(evidence)))
        semantic_used = False
        semantic_candidate_count = 0
        semantic_included_count = 0
        semantic_omitted_count = 0
        semantic_truncated_count = 0
        semantic_malformed_count = 0
        semantic_declared_hash_count = 0
        semantic_backend_truncated: bool | None = None
        semantic_backend_coverage_complete: bool | None = None
        per_path: dict[str, int] = {}
        for item in evidence:
            path = str(item.get("path", ""))
            per_path[path] = per_path.get(path, 0) + 1
        max_per_file = max(1, int(search_cfg.get("max_snippets_per_file", 3)))

        if rag_future is not None and rag_pool is not None:
            rag_timeout = min(
                bounded_timeout("context_rag_timeout_seconds", 3.0),
                max(0.0, backend_deadline - time.perf_counter()),
            )
            rag_done, rag_pending = wait((rag_future,), timeout=rag_timeout)
            if rag_pending:
                rag_future.cancel()
                rr = None
                backend_states["rag"] = "degraded"
                retrieval_warnings.append("rag timeout")
            else:
                try:
                    rr = rag_future.result()
                except Exception as exc:
                    rr = None
                    backend_states["rag"] = "degraded"
                    retrieval_warnings.append(f"rag degraded: {type(exc).__name__}")
        else:
            rr = None
            if rag_setup_error:
                backend_states["rag"] = "degraded"
            else:
                backend_states["rag"] = "skipped"
        if rag_future is not None:
            from .token_router import strip_boilerplate
            if isinstance(rr, dict) and rr.get("success") and isinstance(rr.get("results"), list):
                raw_results = rr["results"]
                if isinstance(rr.get("truncated"), bool):
                    semantic_backend_truncated = rr["truncated"]
                raw_backend_coverage = rr.get("coverage")
                if isinstance(raw_backend_coverage, dict) and isinstance(raw_backend_coverage.get("complete"), bool):
                    semantic_backend_coverage_complete = raw_backend_coverage["complete"]
                sorted_results_input = []
                malformed_results = False
                for item in raw_results:
                    if not isinstance(item, dict) or not str(item.get("path") or "").strip():
                        malformed_results = True
                        semantic_malformed_count += 1
                        continue
                    rag_path = str(item.get("path", "")).replace("\\", "/").strip("/")
                    if excluded_path(rag_path):
                        continue
                    try:
                        chunk_no = int(item.get("chunk_no", 0))
                    except (TypeError, ValueError, OverflowError):
                        malformed_results = True
                        semantic_malformed_count += 1
                        continue
                    if not isinstance(item.get("text", ""), str):
                        malformed_results = True
                        semantic_malformed_count += 1
                        continue
                    sorted_results_input.append({**item, "chunk_no": chunk_no})
                if malformed_results:
                    backend_states["rag"] = "degraded"
                    retrieval_warnings.append("rag malformed result entries")
                elif backend_states.get("rag") != "degraded" and rag_revision_available:
                    backend_states["rag"] = "used"
                elif not rag_revision_available:
                    backend_states["rag"] = "degraded"
                # RRF candidate ordering
                lex_paths = [str(e.get("path")) for e in evidence if e.get("path")]
                vec_paths = [str(r.get("path")) for r in sorted_results_input]
                path_groups["lexical"] = lex_paths
                path_groups["rag"] = vec_paths
                fused_order = [p for p, _score in fuse_ranked_paths(path_groups, limit=64, max_per_path=2)]
                fused_rank = {p: i for i, p in enumerate(fused_order)}
                sorted_results = sorted(sorted_results_input, key=lambda item: fused_rank.get(str(item.get("path", "")), 999))
                semantic_candidate_count = len(sorted_results)
                remaining = max(0, chars_for_tokens(max_tokens) - len(context))
                seen_chunks: set[tuple[str, int]] = set()
                for result_index, item in enumerate(sorted_results):
                    path = str(item.get("path", ""))
                    chunk_no = int(item.get("chunk_no", 0))
                    key = (path, chunk_no)
                    if key in seen_chunks or per_path.get(path, 0) >= max_per_file:
                        semantic_omitted_count += 1
                        continue
                    seen_chunks.add(key)
                    clean_text = strip_boilerplate(str(item.get("text", "")))
                    rendered = f"\n--- semantic {path} chunk={chunk_no} ---\n{clean_text}\n"
                    if len(rendered) > remaining:
                        if remaining > 400:
                            rendered = rendered[:remaining] + "\n[semantic snippet truncated]\n"
                            semantic_truncated_count += 1
                        else:
                            semantic_omitted_count += len(sorted_results) - result_index
                            break
                    context += rendered
                    remaining -= len(rendered)
                    per_path[path] = per_path.get(path, 0) + 1
                    semantic_used = True
                    rag_evidence = {
                        "evidence_id": str(item.get("evidence_id") or "rag-" + stable_hash({"root": str(root_path), "path": path, "chunk_no": chunk_no, "content_hash": item.get("content_hash"), "revision": item.get("revision")})[:24]),
                        "path": path, "chunk_no": chunk_no, "semantic": True,
                        "revision": str(item.get("revision") or item.get("repository_revision") or item.get("content_hash") or "")[:200],
                        "content_hash": item.get("content_hash"),
                    }
                    for field in ("symbol", "start_line", "end_line", "repository_revision"):
                        if field in item:
                            rag_evidence[field] = item[field]
                    evidence.append(rag_evidence)
                    semantic_included_count += 1
                    if item.get("content_hash"):
                        semantic_declared_hash_count += 1
                    if remaining <= 0:
                        semantic_omitted_count += len(sorted_results) - result_index - 1
                        break
            elif backend_states.get("rag") != "degraded":
                backend_states["rag"] = "degraded" if rr is not None else "skipped"
                if backend_states["rag"] == "degraded":
                    retrieval_warnings.append("rag unavailable or malformed response")
        else:
            backend_states["rag"] = "degraded" if rag_setup_error or (rag_configured and not rag_revision_available) else "skipped"
        evidence_paths = [str(item.get("path") or "") for item in evidence if isinstance(item, dict) and item.get("path")]
        path_backend_counts: dict[str, int] = {}
        for backend_paths in path_groups.values():
            for candidate in set(backend_paths):
                path_backend_counts[candidate] = path_backend_counts.get(candidate, 0) + 1
        lexical_coverage = lexical.get("coverage")
        lexical_freshness = lexical.get("freshness")
        lexical_truncation = lexical.get("truncation")
        lexical_metadata = {
            "coverage": dict(lexical_coverage) if isinstance(lexical_coverage, dict) else {
                "scope": "unknown", "complete": False,
            },
            "freshness": dict(lexical_freshness) if isinstance(lexical_freshness, dict) else {
                "scope": "unknown", "status": "not_reported", "complete": False,
            },
            "truncated": lexical.get("truncated") if isinstance(lexical.get("truncated"), bool) else None,
            "truncation": dict(lexical_truncation) if isinstance(lexical_truncation, dict) else {
                "status": "unknown", "complete": False,
            },
        }
        semantic_metadata = {
            "coverage": {
                "scope": "returned_rag_candidates",
                "candidate_count": semantic_candidate_count,
                "included_evidence_count": semantic_included_count,
                "omitted_chunk_count": semantic_omitted_count,
                "malformed_chunk_count": semantic_malformed_count,
                "complete": semantic_candidate_count > 0 and semantic_omitted_count == 0 and semantic_truncated_count == 0 and semantic_malformed_count == 0 and semantic_backend_truncated is not True and semantic_backend_coverage_complete is not False,
            },
            "freshness": {
                "scope": "included_semantic_evidence",
                "status": "not_checked" if semantic_included_count else "not_available",
                "checked_chunks": 0,
                "declared_hash_chunks": semantic_declared_hash_count,
                "complete": False,
            },
            "truncated": (
                semantic_truncated_count > 0 or semantic_omitted_count > 0 or semantic_backend_truncated is True or semantic_backend_coverage_complete is False
                if semantic_candidate_count > 0 or semantic_backend_truncated is not None or semantic_backend_coverage_complete is not None else None
            ),
            "truncation": {
                "status": "truncated" if semantic_truncated_count or semantic_omitted_count or semantic_backend_truncated is True or semantic_backend_coverage_complete is False else "none_observed" if semantic_candidate_count else "not_available",
                "rendered_truncated_chunks": semantic_truncated_count,
                "omitted_chunks": semantic_omitted_count,
                "backend_reported_truncated": semantic_backend_truncated,
                "backend_coverage_complete": semantic_backend_coverage_complete,
                "complete": semantic_candidate_count > 0 and semantic_truncated_count == 0 and semantic_omitted_count == 0 and semantic_backend_truncated is not True and semantic_backend_coverage_complete is not False,
            },
        }
        fallbacks = [
            {"backend": name, "fallback": "lexical"}
            for name, state in sorted(backend_states.items())
            if name != "lexical" and state == "degraded" and backend_states.get("lexical") == "used"
        ]
        return {
            "success": True, "root": lexical["root"], "query": query, "context": context,
            "evidence": evidence, "estimated_tokens": estimate_tokens(context),
            "scanned_files": lexical.get("scanned_files", 0), "semantic_used": semantic_used,
            **({"degraded": True, "degraded_reason": "bounded_path_candidate_fallback"}
               if path_inventory_state == "degraded" else {}),
            "context_budget_tokens": max_tokens,
            "retrieval": {
                "quality_first": bool(quality_first),
                "rag_revision": str(rag_revision)[:200],
                "backends": sorted(path_groups),
                "used_backends": sorted(name for name, state in backend_states.items() if state == "used"),
                "skipped_backends": sorted(name for name, state in backend_states.items() if state == "skipped"),
                "degraded_backends": sorted(name for name, state in backend_states.items() if state == "degraded"),
                "backend_states": dict(sorted(backend_states.items())),
                "backend_selection": backend_selection,
                "fallbacks": fallbacks,
                "lexical": lexical_metadata,
                "semantic": semantic_metadata,
                "warnings": list(dict.fromkeys(retrieval_warnings))[:8],
                "fused_paths": [path for path, _score in fuse_ranked_paths(path_groups, limit=24, max_per_path=2)],
                "quality": {
                    "candidate_count": len(candidate_paths),
                    "evidence_count": len(evidence),
                    "file_coverage": len(set(evidence_paths)),
                    "cross_backend_agreement_count": sum(1 for count in path_backend_counts.values() if count > 1),
                },
                "latency_ms": round((time.perf_counter() - started_at) * 1000, 3),
            },
        }

    def delegate_repo(self, args: dict[str, Any], tenant: str) -> dict[str, Any]:
        if str(args.get("profile", "")).strip():
            return self.delegate_profile(args, tenant)
        root = str(args.get("root", "."))
        task = str(args.get("task", ""))
        requested_context_tokens = int(args.get("context_tokens", 0) or 0)
        if requested_context_tokens > 0:
            max_context_tokens = requested_context_tokens
        else:
            initial_route = self.router.classify(
                task, "", str(args.get("task_type", "auto")), str(args.get("complexity", "auto"))
            )
            workflow = self.config.get("workflow", {})
            if initial_route.get("complexity") == "heavy":
                max_context_tokens = int(workflow.get("heavy_repo_context_tokens", 4200))
            else:
                max_context_tokens = int(workflow.get("fast_repo_context_tokens", 2200))
        packed = self._hybrid_context(root, task, tenant, args.get("workspace"), max_context_tokens)
        if not packed.get("success"):
            return packed
        payload = {
            "task": task,
            "context": packed.get("context", ""),
            "task_type": str(args.get("task_type", "auto")),
            "complexity": str(args.get("complexity", "auto")),
            "max_tokens": int(args.get("max_tokens", 4096)),
            "priority": int(args.get("priority", 5)),
            # Packed local context is a diagnostic, not proof of cloud-side input
            # avoided: the agent may have used RG or another narrower tool.
        }
        result = self.delegate(payload, tenant)
        result["repo_context"] = {
            "root": packed.get("root", root), "evidence": packed.get("evidence", []),
            "local_context_tokens": packed.get("estimated_tokens", 0), "semantic_used": bool(packed.get("semantic_used", False)),
            "scanned_files": packed.get("scanned_files", 0),
        }
        return result

    def solve_repo(self, args: dict[str, Any], tenant: str) -> dict[str, Any]:
        if self.pipeline is None:
            return self.delegate_repo(args, tenant)
        return self.pipeline.solve_repo(args, tenant)

    def route_context(self, args: dict[str, Any], tenant: str) -> dict[str, Any]:
        if self.token_router is None:
            return {"success": False, "error": "lossless token router unavailable"}
        if "task" in args or "context" in args:
            return {
                "success": False,
                "error": "route accepts query and text; task and context are not aliases",
            }
        query = args.get("query", "")
        text = args.get("text", "")
        if not isinstance(query, str):
            return {"success": False, "error": "query must be a string"}
        if not isinstance(text, str):
            return {"success": False, "error": "text must be a string"}
        path = args.get("path")
        if path is not None and not isinstance(path, str):
            return {"success": False, "error": "path must be a string"}
        label = args.get("label")
        if label is not None and not isinstance(label, str):
            return {"success": False, "error": "label must be a string"}
        if path:
            root = args.get("root", ".")
            if not isinstance(root, str):
                return {"success": False, "error": "root must be a string"}
            return self.token_router.route_file(root, path, query, tenant)
        return self.token_router.route_text(text, query, tenant, path=label)

    def review_diff(self, args: dict[str, Any], tenant: str) -> dict[str, Any]:
        diff = self.repo_diff(
            str(args.get("root", ".")), str(args.get("base", "HEAD")), bool(args.get("staged", False)),
            max_tokens=int(args.get("diff_tokens", self.config.get("token_saving", {}).get("max_diff_tokens", 8000))),
        )
        if not diff.get("success"):
            return diff
        if not diff.get("diff", "").strip():
            return {"success": True, "text": "No diff to review.", "changed_files": [], "diff_truncated": False}
        det_diff = {}
        if self.deterministic is not None:
            try:
                det_diff = self.deterministic.diff_facts(str(diff.get("diff", "")))
            except Exception:
                det_diff = {}
        instructions = str(args.get("instructions", "Review this git diff for actionable defects, regressions, security/concurrency issues and missing tests. Cite changed files/hunks."))
        det_hint = ""
        if det_diff:
            det_hint = "\nDETERMINISTIC DIFF METADATA (facts only, verify semantics in the diff):\n" + json_dumps(det_diff, ensure_ascii=False, separators=(",", ":"))[:1800] + "\n"
            if det_diff.get("breaking_changes"):
                det_hint += "\nPOTENTIAL BREAKING CHANGES DETECTED:\n"
                for bc in det_diff["breaking_changes"][:10]:
                    det_hint += f"- [{bc.get('type')}] {bc.get('symbol')} in {bc.get('file')}: {bc.get('description')}\n"

        regressions: list[dict[str, Any]] = []
        incident_store = getattr(self, "incident_store", None)
        if incident_store is not None and diff.get("changed_files"):
            try:
                found = incident_store.find_regressions(diff["changed_files"])
                if isinstance(found, list):
                    regressions = [r for r in found if isinstance(r, dict)]
            except Exception:
                regressions = []
        if regressions:
            det_hint += "\nAUTO-REGRESSION WATCHDOG (verified fixes from prior incidents affecting changed files):\n"
            for reg in regressions[:5]:
                aff = ", ".join(reg.get("affected_paths", []))
                det_hint += f"- [PRIOR VERIFIED FIX] {reg.get('error_class')} in {aff}: {reg.get('verified_fix')}\n"

        if args.get("mode") == "ast" or str(args.get("instructions", "")).strip().lower() == "ast":
            return {
                "success": True,
                "mode": "ast",
                "changed_files": diff.get("changed_files", []),
                "diff_facts": det_diff,
                "breaking_changes": det_diff.get("breaking_changes", []),
                "regressions": regressions,
                "summary": f"AST Diff Summary: {len(diff.get('changed_files', []))} files, {det_diff.get('added_lines_count', 0)} additions, {det_diff.get('deleted_lines_count', 0)} deletions across {det_diff.get('hunks_count', 0)} hunks. {len(det_diff.get('breaking_changes', []))} potential breaking changes.",
            }

        # Keep non-diff prompt material bounded too; metadata descriptions and custom
        # instructions can otherwise undo the per-segment input limit.
        instructions = fit_text(instructions, 600).text
        det_hint = fit_text(det_hint, 700).text if det_hint else ""

        diff_text = str(diff["diff"])
        complexity_hint = review_diff_complexity(args, det_diff, diff)
        full_route = self.router.classify(
            instructions + det_hint, diff_text, "review", complexity_hint
        )
        full_route = self._resident_optimize(full_route, "review", complexity_hint)
        review_model = str(full_route.get("model", ""))
        selected_tier = self.model_policy.tier_for(review_model)
        complexity = (
            "heavy" if selected_tier == "smart"
            else "fast" if selected_tier in {"fast", "background"}
            else str(full_route.get("complexity", "fast"))
        )
        max_output_tokens = max(64, int(args.get("max_tokens", 1800)))
        vram_free_mb = None
        try:
            if getattr(self, "vram_balancer", None):
                vram_status = self.vram_balancer.status()
                if vram_status.get("available", "vram_available_mb" in vram_status):
                    vram_free_mb = vram_status.get("vram_available_mb")
        except Exception:
            vram_free_mb = None
        profile = self.model_policy.profile(
            review_model,
            role="review",
            input_tokens=estimate_tokens(instructions + det_hint + diff_text),
            output_tokens=max_output_tokens,
            vram_free_mb=vram_free_mb,
        )
        configured_input_budget = max(
            _REVIEW_DIFF_MIN_CHUNK_TOKENS,
            int(self.config.get("token_saving", {}).get("max_local_input_tokens", 56000)),
        )
        effective_prompt_budget_tokens = min(configured_input_budget, profile.prompt_budget_tokens)
        task_budget = max(128, int(effective_prompt_budget_tokens * 0.15))
        review_task = fit_text(instructions + det_hint, task_budget).text
        prompt_overhead = estimate_tokens(f"TASK:\n{review_task}\n\nCONTEXT:\n") + 64
        synthesis_task = fit_text(
            "SYNTHESIZE REVIEW FINDINGS ONLY. Merge duplicate findings and keep distinct actionable findings. "
            "Preserve file paths, hunk/line references, severity and uncertainty. Do not re-review the source, "
            "invent new findings, or discard a finding unless supplied findings show it is a duplicate or false positive. "
            f"Return a concise final review.\n\nReview goal: {review_task}",
            task_budget,
        ).text
        synthesis_prompt_overhead = estimate_tokens(f"TASK:\n{synthesis_task}\n\nCONTEXT:\n") + 64
        synthesis_context_budget = max(
            0,
            min(
                _REVIEW_SYNTHESIS_CONTEXT_TOKENS,
                int(effective_prompt_budget_tokens * _REVIEW_DIFF_CONTEXT_FRACTION),
                effective_prompt_budget_tokens - synthesis_prompt_overhead,
            ),
        )
        review_chunk_token_budget = min(
            int(effective_prompt_budget_tokens * _REVIEW_DIFF_CONTEXT_FRACTION),
            effective_prompt_budget_tokens - prompt_overhead,
        )
        if review_chunk_token_budget < _REVIEW_DIFF_MIN_CHUNK_TOKENS:
            return {
                "success": False,
                "error": "The selected model's prompt budget is too small for a safe diff review.",
                "changed_files": diff.get("changed_files", []),
                "effective_prompt_budget_tokens": effective_prompt_budget_tokens,
            }

        review_chunks = _split_review_diff(diff_text, max_tokens=review_chunk_token_budget)
        largest_review_chunk_tokens = max(estimate_tokens(chunk) for chunk in review_chunks)
        if largest_review_chunk_tokens > review_chunk_token_budget:
            return {
                "success": False,
                "error": (
                    f"A diff fragment exceeds the {review_chunk_token_budget}-token review budget and cannot be split safely. "
                    "Narrow the diff or exclude generated/minified files."
                ),
                "changed_files": diff.get("changed_files", []),
                "diff_truncated": bool(diff.get("truncated", False)),
                "largest_review_chunk_tokens": largest_review_chunk_tokens,
                "review_chunk_token_budget": review_chunk_token_budget,
            }
        max_review_chunks = _MAX_REVIEW_DIFF_CHUNKS
        if bool(args.get("_async_job")):
            max_review_chunks = max(
                _MAX_REVIEW_DIFF_CHUNKS,
                int(self.config.get("review", {}).get("max_async_chunks", 32)),
            )
        if len(review_chunks) > max_review_chunks:
            return {
                "success": False,
                "error": (
                    f"Review requires {len(review_chunks)} segments; the safe limit is "
                    f"{max_review_chunks}. Narrow the diff or lower diff_tokens."
                ),
                "changed_files": diff.get("changed_files", []),
                "diff_truncated": bool(diff.get("truncated", False)),
                "review_chunks": len(review_chunks),
            }
        chunked = len(review_chunks) > 1
        if chunked:
            header_tokens = sum(
                estimate_tokens(f"### Counter-review segment {index}/{len(review_chunks)}\n") + 2
                for index in range(1, len(review_chunks) + 1)
            )
            per_chunk_output_tokens = min(
                max_output_tokens,
                700,
                max(64, (synthesis_context_budget - header_tokens - 64) // len(review_chunks)),
            )
        else:
            per_chunk_output_tokens = max_output_tokens
        review_payloads: list[dict[str, Any]] = []
        primary_results: list[dict[str, Any]] = []
        format_recovery_used = False
        format_recoveries: list[dict[str, Any]] = []
        for index, review_code in enumerate(review_chunks, start=1):
            task = review_task
            if chunked:
                task += (
                    f"\n\nThis is review segment {index}/{len(review_chunks)} of one diff. "
                    "Review only the changed code shown in this segment; other segments are reviewed separately. "
                    "Ground each finding in the displayed file and hunk."
                )
            review_payload = {
                "task_type": "review",
                "operation": "review_diff",
                "task": task,
                "context": review_code,
                "changed_paths": diff.get("changed_files", []),
                "static_facts": det_hint,
                "complexity": complexity,
                "max_tokens": per_chunk_output_tokens,
                "priority": int(args.get("priority", 5)),
            }
            review_payloads.append(review_payload)
            response = self.delegate(review_payload, tenant)
            if not isinstance(response, dict) or response.get("success") is False:
                if len(review_chunks) == 1 and isinstance(response, dict):
                    return response
                return {
                    "success": False,
                    "error": f"Review segment {index}/{len(review_chunks)} failed.",
                    "failed_segment": index,
                    "partial_reviews": [str(item.get("text", "")) for item in primary_results],
                }
            output_error = _review_text_error(response.get("text"))
            if output_error:
                if format_recovery_used:
                    return {
                        "success": False,
                        "error": f"Review segment {index}/{len(review_chunks)} returned unusable output after the single format-recovery attempt: {output_error}",
                        "failed_segment": index,
                        "model": response.get("model"),
                        "attempted_models": [str(response.get("model") or "")],
                        "invalid_model_output": True,
                        "partial_reviews": [str(item.get("text", "")) for item in primary_results],
                    }
                format_recovery_used = True
                primary_model = str(response.get("model") or "").strip()
                models = self.config.get("models", {})
                fast_model = str(models.get("fast_code") or "").strip() if isinstance(models, dict) else ""
                heavy_model = str(models.get("heavy_code") or "").strip() if isinstance(models, dict) else ""
                retry_model = fast_model or heavy_model or primary_model
                if (
                    fast_model
                    and heavy_model
                    and primary_model
                    and _review_model_identity(primary_model) == _review_model_identity(fast_model)
                ):
                    retry_model = heavy_model
                retry_payload = dict(review_payload)
                if retry_model:
                    retry_payload["model"] = retry_model
                retry_payload["task"] = (
                    f"{review_payload.get('task', review_task)}\n\nFORMAT RECOVERY: The previous response was unusable ({output_error}). "
                    "Review this diff again. Return plain text whose first line begins `SUMMARY:` followed by at least two words. "
                    "Then list only actionable defects, or write `- None.` when there are none. Do not emit fragments or markdown fences."
                )
                try:
                    retry_response = self.delegate(retry_payload, tenant)
                except Exception as exc:
                    return {
                        "success": False,
                        "error": f"Review segment {index}/{len(review_chunks)} format recovery failed: {exc}",
                        "failed_segment": index,
                        "model": retry_model or primary_model or None,
                        "attempted_models": [model for model in (primary_model, retry_model) if model],
                        "invalid_model_output": True,
                        "partial_reviews": [str(item.get("text", "")) for item in primary_results],
                    }
                retry_error = (
                    _review_text_error(retry_response.get("text"))
                    if isinstance(retry_response, dict) and retry_response.get("success") is not False
                    else "fallback model did not return a successful review"
                )
                if retry_error:
                    retry_model_returned = (
                        str(retry_response.get("model") or retry_model or "").strip()
                        if isinstance(retry_response, dict)
                        else retry_model
                    )
                    return {
                        "success": False,
                        "error": f"Review segment {index}/{len(review_chunks)} remained unusable after format recovery: {retry_error}",
                        "failed_segment": index,
                        "model": retry_model_returned or primary_model or None,
                        "attempted_models": [model for model in (primary_model, retry_model_returned) if model],
                        "invalid_model_output": True,
                        "partial_reviews": [str(item.get("text", "")) for item in primary_results],
                    }
                response = retry_response
                format_recoveries.append({
                    "segment": index,
                    "from_model": primary_model or None,
                    "to_model": str(response.get("model") or retry_model or "").strip() or None,
                })
            primary_results.append(response)

        result = dict(primary_results[0])
        if format_recoveries:
            result["degraded"] = True
            result["format_recoveries"] = format_recoveries

        merge_options = {
            "chunked": chunked,
            "synthesis_context_budget": synthesis_context_budget,
            "synthesis_task": synthesis_task,
            "max_output_tokens": max_output_tokens,
            "complexity": complexity,
            "tenant": tenant,
            "delegate": self.delegate,
            "priority": int(args.get("priority", 5)),
        }
        result["text"], result["review_synthesis"] = _merge_review_segment_results(
            primary_results, label="Review segment", task_type="review", **merge_options
        )
        if result["review_synthesis"].get("model"):
            result["model"] = result["review_synthesis"]["model"]

        # Multi-model consensus review for high-risk breaking changes or when explicitly requested
        consensus_requested = bool(args.get("consensus", False))
        auto_consensus = args.get("consensus") is None and bool(det_diff.get("breaking_changes"))

        if consensus_requested or auto_consensus:
            try:
                secondary_results = []
                for review_payload in review_payloads:
                    sec_payload = dict(review_payload)
                    sec_payload["task_type"] = "reasoning"
                    sec_payload["task"] = (
                        "CRITICAL COUNTER-REVIEW / CONSENSUS AUDIT:\n"
                        "Analyze the shown diff segment independently and verify potential defects or breaking changes. "
                        "Confirm genuine issues and flag false positives.\n\n"
                        + str(review_payload["task"])
                    )
                    sec_result = self.delegate(sec_payload, tenant)
                    if not isinstance(sec_result, dict) or sec_result.get("success") is False:
                        raise ValueError(f"Counter-review segment {len(secondary_results) + 1} failed.")
                    output_error = _review_text_error(sec_result.get("text"))
                    if output_error:
                        raise ValueError(
                            f"Counter-review segment {len(secondary_results) + 1} returned unusable output: {output_error}"
                        )
                    secondary_results.append(sec_result)
                if secondary_results:
                    secondary_text, secondary_synthesis = _merge_review_segment_results(
                        secondary_results,
                        label="Counter-review segment",
                        task_type="reasoning",
                        **merge_options,
                    )
                    result["consensus"] = {
                        "enabled": True,
                        "triggered_by": "explicit" if consensus_requested else "breaking_changes",
                        "primary_model": result.get("model", "primary"),
                        "secondary_model": secondary_results[0].get("model", "secondary"),
                        "secondary_review": secondary_text,
                        "synthesis": secondary_synthesis,
                    }
                    result["text"] = str(result.get("text", "")) + "\n\n### Consensus / Counter-Review Findings:\n" + secondary_text
            except Exception as exc:
                result["consensus"] = {"enabled": True, "degraded": True, "error": str(exc)}

        if regressions:
            result["regressions"] = regressions
        result["diff"] = {
            "changed_files": diff["changed_files"],
            "truncated": diff["truncated"],
            "local_diff_tokens": diff["estimated_tokens"],
            "original_diff_tokens": diff["original_estimated_tokens"],
            "deterministic": det_diff,
            "review_chunks": len(review_chunks),
            "effective_prompt_budget_tokens": effective_prompt_budget_tokens,
            "review_chunk_token_budget": review_chunk_token_budget,
            "review_chunk_context_fraction": _REVIEW_DIFF_CONTEXT_FRACTION,
            "review_segment_output_budget_tokens": per_chunk_output_tokens,
            "review_synthesis_context_budget_tokens": synthesis_context_budget,
            "review_model": review_model,
            "largest_review_chunk_tokens": largest_review_chunk_tokens,
        }
        return result

    def compress(self, args: dict[str, Any], tenant: str) -> dict[str, Any]:
        text = str(args.get("text", ""))
        instruction = str(args.get("instruction", "Compress this while preserving facts, identifiers, numbers, decisions, errors and uncertainty."))
        target_tokens = max(128, int(args.get("target_tokens", 900)))
        if not text.strip():
            return {"success": True, "text": "", "input_tokens": 0}

        # Local AI deterministic compressor handles logs/repetitive diagnostics without
        # spending any local-model inference. Narrative text falls through to Ollama.
        if self.deterministic is not None and bool(self.config.get("deterministic", {}).get("compression", True)):
            try:
                det = self.deterministic.compress_text(text, target_tokens)
            except Exception:
                det = {"success": False}
            if det.get("success") and float(det.get("confidence", 0.0)) >= float(self.config.get("deterministic", {}).get("compression_confidence", 0.88)):
                det["compression"] = {
                    "input_tokens_est": estimate_tokens(text),
                    "output_tokens_est": estimate_tokens(str(det.get("text", ""))),
                    "chunks": 0, "method": "deterministic-script", "ollama_calls": 0,
                }
                return det

        chunk_tokens = int(self.config.get("token_saving", {}).get("compression_chunk_tokens", 4800))
        chunk_chars = chars_for_tokens(chunk_tokens)
        chunks = [text[i:i + chunk_chars] for i in range(0, len(text), chunk_chars)]
        summaries: list[str] = []
        per_chunk_out = max(180, min(700, target_tokens // max(1, len(chunks)) + 120))
        general_model = str(self.config.get("models", {}).get("general", self.config.get("models", {}).get("fast_code", "qwen2.5-coder:7b")))
        for index, chunk in enumerate(chunks):
            package = build_prompt(
                operation="compress",
                model=general_model,
                profile=str(getattr(self, "config", {}).get("_hardware", {}).get("profile", "auto")),
                task=f"{instruction}\nChunk {index + 1}/{len(chunks)}",
                context=chunk,
            )
            result = self._generate(
                general_model, package.user,
                package.system,
                per_chunk_out, 0.1, tenant, "compress:map", int(args.get("priority", 4)),
                internal=True,
            )
            if not result.get("success"):
                return result
            summaries.append(str(result.get("text", "")))

        combined = "\n\n".join(summaries)
        if len(chunks) > 1 or estimate_tokens(combined) > target_tokens:
            package = build_prompt(
                operation="compress",
                model=general_model,
                profile=str(getattr(self, "config", {}).get("_hardware", {}).get("profile", "auto")),
                task=f"{instruction}\nTarget: <= {target_tokens} estimated tokens.",
                context=combined,
            )
            final = self._generate(
                general_model,
                package.user,
                package.system,
                target_tokens, 0.1, tenant, "compress:reduce", int(args.get("priority", 4)),
                internal=True,
            )
        else:
            final = {"success": True, "model": general_model, "text": combined}
        final["compression"] = {
            "input_tokens_est": estimate_tokens(text),
            "output_tokens_est": estimate_tokens(str(final.get("text", ""))),
            "chunks": len(chunks),
        }
        return self.artifacts.compact(final, tenant, "compress")

    def complete_code(self, args: dict[str, Any], tenant: str) -> dict[str, Any]:
        """Low-latency FIM (Fill-In-The-Middle) code completion for tab auto-complete."""
        prefix = str(args.get("prefix", ""))
        suffix = str(args.get("suffix", ""))
        max_tokens = min(256, max(8, int(args.get("max_tokens", 80))))
        model = str(self.config.get("models", {}).get("fast_code", "qwen2.5-coder:3b"))

        # Standard Qwen FIM prompt template
        prompt = f"<|fim_prefix|>{prefix[-3000:]}<|fim_suffix|>{suffix[:1500]}<|fim_middle|>"
        payload = {
            "model": model,
            "prompt": prompt,
            "raw": True,
            "options": {
                "num_predict": max_tokens,
                "temperature": 0.0,
                "stop": ["<|fim_prefix|>", "<|fim_suffix|>", "<|fim_middle|>", "<|endoftext|>", "<|file_separator|>"],
            },
        }
        cache_key = stable_hash({"complete_code": True, "model": model, "prompt": prompt, "max_tokens": max_tokens})
        def compute() -> dict[str, Any]:
            res = self.scheduler.submit(model, tenant, "complete_code", lambda: self.runtime.request("/api/generate", payload, timeout=6.0))
            if isinstance(res, dict) and "error" in res:
                return {"success": False, "error": res["error"], "validated": False}
            response_value = res.get("response") if isinstance(res, dict) else None
            if not isinstance(response_value, str) or not response_value.strip():
                return {
                    "success": False,
                    "error": "Model returned an empty completion.",
                    "validated": False,
                }
            return {
                "success": True,
                "model": model,
                "completion": response_value,
                "validated": False,
            }
        raw, hit, coalesced = self.generation_cache.get_or_compute(cache_key, compute)
        result = copy.deepcopy(raw)
        result["cache_hit"] = hit or coalesced
        return result

    DOMAIN_SYNONYMS = {
        "save": ["Save", "Store", "Persist", "Write", "Dump"],
        "load": ["Load", "Read", "Fetch", "Get", "Parse"],
        "database": ["SQLite", "Database", "ExecuteQuery", "Connection", "Transaction", "Query"],
        "auth": ["Auth", "Login", "Token", "User", "Session", "Authenticate", "Permission"],
        "api": ["Endpoint", "Route", "Handler", "Request", "Response", "Client"],
        "cache": ["Cache", "LRU", "Evict", "TTL", "Hit", "Miss"],
        "config": ["Config", "Settings", "Options", "Environment", "Params"],
        "test": ["Test", "Assert", "Fixture", "Mock", "Suite"],
        "logging": ["Logger", "Log", "Info", "Warning", "Error", "Debug"],
        "event": ["Event", "Emit", "Subscribe", "Publish", "Listener", "Handler"],
    }

    def _record_symbol_focus(self, tenant: str, symbols: list[str]) -> None:
        if not symbols:
            return
        with self._focus_lock:
            current = self._recent_focus_symbols.setdefault(tenant, [])
            for s in symbols:
                if s and len(s) >= 3 and s not in current:
                    current.insert(0, s)
            self._recent_focus_symbols[tenant] = current[:16]
            if len(self._recent_focus_symbols) > 256:
                for k in list(self._recent_focus_symbols.keys())[:-128]:
                    self._recent_focus_symbols.pop(k, None)

    def expand_query(self, query: str, tenant: str = "generic") -> list[str]:
        """Expand natural language query terms with code synonyms, domain keywords, and recent conversation focus."""
        cache_key = f"{tenant}:{query.strip().lower()}"
        if hasattr(self, "_query_expansion_l1"):
            cached = self._query_expansion_l1.get(cache_key)
            if cached is not None:
                return list(cached)
        terms = re.findall(r"[A-Za-z0-9_]{3,}", query.lower())
        synonyms: list[str] = list(terms)
        for t in terms:
            if t in self.DOMAIN_SYNONYMS:
                synonyms.extend(self.DOMAIN_SYNONYMS[t])
        
        # Multi-turn context bonus: if query is brief/contextual, add recently investigated AST symbols
        with self._focus_lock:
            recent = list(self._recent_focus_symbols.get(tenant, []))
        if recent and len(terms) <= 4:
            synonyms.extend(recent[:4])
            
        # Record newly identified proper-case or identifier symbols as focus
        explicit_symbols = [w for w in re.findall(r"\b[A-Z][A-Za-z0-9_]{3,}\b", query)]
        if explicit_symbols:
            self._record_symbol_focus(tenant, explicit_symbols)
            
        result = list(dict.fromkeys(synonyms))
        if hasattr(self, "_query_expansion_l1"):
            self._query_expansion_l1.set(cache_key, result)
        return result

    def generate_tests(self, payload: dict[str, Any], tenant: str) -> dict[str, Any]:
        """Generate complete unit test code for a symbol or file."""
        symbol = str(payload.get("symbol", ""))
        code_context = str(payload.get("code", ""))
        framework = str(payload.get("framework", "auto")).lower()
        path = str(payload.get("path", payload.get("file", "")))
        root = str(payload.get("root", "."))

        if not code_context and symbol and self.code_index is not None:
            try:
                sym_info = self.code_index.inspect_symbol(root, symbol)
                if sym_info.get("success"):
                    code_context = sym_info.get("snippet", "")
                    if not path:
                        path = sym_info.get("path", "")
            except Exception:
                pass

        if not framework or framework == "auto":
            if path.endswith(".cs"):
                framework = "nunit"
            elif path.endswith(".py"):
                framework = "pytest"
            elif path.endswith((".ts", ".js", ".tsx", ".jsx")):
                framework = "jest"
            else:
                framework = "pytest"

        if payload.get("fast_scaffold") or payload.get("template_only") or payload.get("deterministic"):
            clean_sym = re.sub(r"[^A-Za-z0-9_]", "_", symbol) or "target"
            pending_reason = "Replace scaffold with behavior-based assertions before enabling this test."
            if framework == "pytest":
                scaffold = (
                    "import pytest\n\n"
                    f"@pytest.mark.skip(reason={json.dumps(pending_reason, separators=(',', ':'))})\n"
                    f"def test_{clean_sym}_basic():\n"
                    f"    raise NotImplementedError({json.dumps(pending_reason, separators=(',', ':'))})\n"
                )
            elif framework == "nunit":
                scaffold = (
                    "using NUnit.Framework;\n\n"
                    f"[TestFixture]\npublic class {clean_sym}Tests {{\n"
                    f"    [Test]\n    [Ignore({json.dumps(pending_reason, separators=(',', ':'))})]\n"
                    f"    public void Test_{clean_sym}_Basic() {{\n"
                    f"        Assert.Fail({json.dumps(pending_reason, separators=(',', ':'))});\n"
                    "    }\n}\n"
                )
            elif framework == "jest":
                scaffold = (
                    f"describe({json.dumps(symbol, separators=(',', ':'))}, () => {{\n"
                    f"    test.todo({json.dumps(pending_reason, separators=(',', ':'))});\n"
                    "});\n"
                )
            else:
                scaffold = (
                    f"def test_{clean_sym}():\n"
                    f"    raise NotImplementedError({json.dumps(pending_reason, separators=(',', ':'))})\n"
                )
            return {
                "success": True,
                "framework": framework,
                "target_symbol": symbol,
                "scaffold": scaffold,
                "test_code": scaffold,
                "method": "fast-scaffold",
                "complete": False,
                "requires_review": True,
            }

        prompt = (
            f"Generate high-quality unit tests using framework: {framework}.\n"
            f"Target symbol: {symbol}\n"
            f"Source code / context:\n```\n{code_context[:4000]}\n```\n\n"
            f"Requirements:\n"
            f"1. Write complete, compilable test methods with assertions.\n"
            f"2. Cover edge cases and normal flow.\n"
            f"3. Return ONLY clean source code inside a code block, no chat."
        )

        fast_model = str(self.config.get("models", {}).get("fast_code", "qwen2.5-coder:3b"))
        res = self._generate(
            fast_model,
            prompt,
            "You are an expert test engineer writing concise, robust unit tests.",
            512,
            0.1,
            tenant,
            "generate_tests",
            4,
        )
        if not res.get("success"):
            return res

        return {
            "success": True,
            "framework": framework,
            "target_symbol": symbol,
            "test_code": res.get("text", ""),
        }

    def validate_patch(self, payload: dict[str, Any], tenant: str) -> dict[str, Any]:
        """Validate whether a diff patch applies cleanly and preserves valid syntax."""
        diff_text = str(payload.get("patch", payload.get("diff", "")))
        if not diff_text.strip():
            return {"success": False, "error": "empty patch"}

        affected_files: list[str] = []
        errors: list[str] = []
        previous_old: str | None = None
        hunks = 0

        def patch_path(raw: str) -> str | None:
            value = raw.strip().split("\t", 1)[0].replace("\\", "/")
            if value == "/dev/null":
                return value
            if value.startswith(("a/", "b/")):
                value = value[2:]
            parts = value.split("/")
            if not value or value.startswith("/") or any(part in {"", ".", ".."} for part in parts):
                return None
            return value

        for line in diff_text.splitlines():
            if line.startswith("--- "):
                previous_old = patch_path(line[4:])
                if previous_old is None:
                    errors.append("invalid old patch path")
            elif line.startswith("+++ "):
                current = patch_path(line[4:])
                if previous_old is None or current is None:
                    errors.append("patch file header is malformed")
                elif current != "/dev/null":
                    affected_files.append(current)
                previous_old = None
            elif line.startswith("@@ "):
                if not re.match(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@", line):
                    errors.append("invalid hunk header")
                else:
                    hunks += 1

        if previous_old is not None:
            errors.append("patch has an unpaired file header")
        if not affected_files:
            errors.append("patch changes no files")
        if not hunks:
            errors.append("patch contains no hunks")
        valid = not errors
        applicability_checked = False
        if valid and payload.get("root"):
            root = Path(str(payload["root"])).expanduser().resolve()
            applicability_checked = True
            if not root.is_dir():
                errors.append("patch root directory does not exist")
            else:
                try:
                    timeout = 8.0 if self is None else max(1.0, min(30.0, float(self.config.get("commands", {}).get("patch_check_timeout_seconds", 8.0))))
                    checked = subprocess.run(
                        ["git", "-C", str(root), "apply", "--check", "--"], input=diff_text, capture_output=True,
                        timeout=timeout, check=False, **hidden_run_kwargs(text=True),
                    )
                    if checked.returncode != 0:
                        errors.append((checked.stderr or checked.stdout or "git apply --check failed").strip()[:500])
                except FileNotFoundError:
                    errors.append("git is unavailable for applicability check")
                except subprocess.TimeoutExpired:
                    errors.append("git apply --check timed out")
            valid = not errors

        return {
            "success": valid,
            "valid": valid,
            "syntax_valid": valid,
            "applicability_checked": applicability_checked,
            "files_affected": list(dict.fromkeys(affected_files)),
            "errors": errors,
            "message": f"Patch syntax {'is valid' if valid else 'is invalid'}; applicability {'was checked' if applicability_checked else 'was not checked'}.",
        }

    def preprocess(self, args: dict[str, Any]) -> dict[str, Any]:
        action = str(args.get("action", "status")).strip().lower().replace("-", "_")
        root = str(args.get("root", "."))
        if action in {"start", "register", "preprocess", "refresh", "force_refresh", "resume"}:
            from .operational_mode import load_operational_mode, operational_mode_gate_error

            state_dir = self.config.get("server", {}).get("state_dir")
            if state_dir:
                mode = load_operational_mode(state_dir)
                rejection = operational_mode_gate_error(mode, "preprocess")
                if rejection is not None:
                    return rejection
        if self.preprocessor is None:
            return {"success": False, "error": "project preprocessor unavailable", "terminal": True, "retryable": False}
        if action in {"start", "register", "preprocess"}:
            return self.preprocessor.register(
                root, source="agent",
                is_worktree=bool(args.get("is_worktree", False)),
                parent_root=args.get("parent_root") or None,
            )
        if action in {"refresh", "force_refresh"}:
            return self.preprocessor.refresh(root)
        if action == "pause":
            return self.preprocessor.pause(root if args.get("root") else None)
        if action == "resume":
            return self.preprocessor.resume(root if args.get("root") else None)
        if action in {"cancel", "stop"}:
            return self.preprocessor.cancel(root)
        if action in {"unregister", "remove", "delete"}:
            return self.preprocessor.unregister(root, purge_data=bool(args.get("purge_data", False)))
        if action in {"prune", "cleanup_deleted", "cleanup"}:
            return self.preprocessor.cleanup_deleted_projects()
        if action in {"cleanup_orphans", "cleanup_orphaned_indexes"}:
            return self.preprocessor.cleanup_orphaned_indexes()
        if action in {"status", "get"}:
            return self.preprocessor.status(root if args.get("root") else None)
        if action in {"lookup", "context"}:
            return self.preprocessor.lookup(root, str(args.get("query", "")), int(args.get("limit", 5)))
        return {"success": False, "error": f"unknown preprocess action: {action}", "terminal": True, "retryable": False}

    def _authorize_command_action(
        self, action: str, *, endpoint: str, task_id: str = ""
    ) -> dict[str, Any] | None:
        broker = self.commands
        authorize = getattr(broker, "authorize_auxiliary_action", None) if broker is not None else None
        if not callable(authorize):
            policy = {
                "success": False,
                "allowed": False,
                "requires_approval": True,
                "reason": "auxiliary action policy boundary unavailable",
                "owner": "agent_policy",
                "side_effect_class": "unknown",
                "terminal": True,
                "retryable": False,
            }
        else:
            aliases = {
                "auto_fix": "repair_loop",
                "repair": "repair_loop",
                "mock_server": "mock_server_start",
                "test_flaky_detect": "flaky_detect",
            }
            policy = authorize(
                aliases.get(action, action), endpoint=endpoint, task_id=task_id
            )
        if policy.get("allowed", False):
            return None
        return {
            "success": False,
            "error": policy.get("reason", "command action denied by policy"),
            "policy": policy,
            "policy_blocked": True,
            "terminal": True,
            "retryable": False,
        }

    def command(
        self, args: dict[str, Any], tenant: str, *, request_cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        if self.commands is None:
            return {"success": False, "error": "command broker unavailable"}
        action = str(args.get("action", "run")).strip().lower().replace("-", "_")
        if bool(args.get("rollback_on_failure", False)) and (action != "run" or bool(args.get("auto_fix", False))):
            return {
                "success": False,
                "error": "rollback_on_failure is supported only for direct run actions",
                "rollback_unsupported_action": True,
                "terminal": True,
                "retryable": False,
            }
        denied = self._authorize_command_action(
            action,
            endpoint="services.command",
            task_id=str(args.get("task_id", "")),
        )
        if denied is not None:
            return denied

        stream_id = str(args.get("stream_id") or (f"cmd:{args.get('task_id')}" if args.get("task_id") else "") or (f"cmd:{tenant}" if args.get("stream") else ""))
        log_callback = None
        if stream_id and self.agent_state is not None and getattr(self.agent_state, "enabled", False):
            def _log_cb(st: str, line: str) -> None:
                try:
                    from .agent_events import AgentEvent
                    self.agent_state.append(AgentEvent.create(
                        stream_id=stream_id,
                        kind="command.log",
                        payload={"stream": st, "chunk": line},
                        actor=tenant,
                    ))
                except Exception:
                    pass
            log_callback = _log_cb

        if action == "patch_and_verify":
            return self.commands.patch_and_verify(
                str(args.get("patch", "")),
                str(args.get("cwd", args.get("root", "."))),
                tenant,
                command=str(args.get("command", "")),
                criterion=str(args.get("criterion", "")),
                task_id=str(args.get("task_id", "")),
                timeout=int(args.get("timeout", 0) or 0) or None,
                auto_rollback=bool(args.get("auto_rollback", True)),
                log_callback=log_callback,
            )
        if action == "preflight":
            raw_paths = args.get("paths") or args.get("files")
            paths_list = [str(p) for p in raw_paths] if isinstance(raw_paths, list) else ([str(raw_paths)] if raw_paths else None)
            return self.commands.preflight(
                str(args.get("cwd", args.get("root", "."))),
                tenant,
                paths=paths_list,
                timeout=int(args.get("timeout", 10) or 10),
            )
        if action in {"repair_loop", "auto_fix"}:
            return self.commands.repair_loop(
                str(args.get("command", "")), str(args.get("cwd", args.get("root", "."))), tenant,
                timeout=int(args.get("timeout", 0) or 0) or None,
                task_id=str(args.get("task_id", "")), criterion=str(args.get("criterion", "")),
                max_attempts=int(args.get("max_attempts", 3)),
                fix_generator=self._synthesize_repair_patch,
                log_callback=log_callback,
            )
        if action == "run":
            fence_kwargs = (
                {"_work_attempt_fence": args["writer_fence"]}
                if args.get("writer_fence") is not None else {}
            )
            if request_cancel_event is not None:
                fence_kwargs["request_cancel_event"] = request_cancel_event
            if args.get("env"):
                fence_kwargs["env"] = args["env"]
            if args.get("stdin") is not None:
                fence_kwargs["stdin"] = args["stdin"]
            elif args.get("input") is not None:
                fence_kwargs["stdin"] = args["input"]
            return self.commands.run(
                str(args.get("command", "")), str(args.get("cwd", args.get("root", "."))), tenant,
                timeout=int(args.get("timeout", 0) or 0) or None, force=bool(args.get("force", False)),
                task_id=str(args.get("task_id", "")), criterion=str(args.get("criterion", "")),
                record_verification=bool(args.get("record_verification", True)),
                auto_fix=bool(args.get("auto_fix", False)),
                fix_generator=self._synthesize_repair_patch if bool(args.get("auto_fix", False)) else None,
                log_callback=log_callback,
                snapshot=bool(args.get("snapshot", False)),
                rollback_on_failure=bool(args.get("rollback_on_failure", False)),
                rollback_paths=args.get("paths") if isinstance(args.get("paths"), list) else None,
                **fence_kwargs,
            )
        if action == "run_affected":
            root = str(args.get("cwd", args.get("root", ".")))
            aff = self.affected_tests(
                root,
                changed_paths=args.get("paths"),
                path_hints=args.get("path_hints"),
            )
            if not isinstance(aff, dict) or not aff.get("success", True):
                return aff if isinstance(aff, dict) else {"success": False, "error": "affected-test selection returned no result"}
            cmd = aff.get("suggested_command", "")
            if not cmd:
                if aff.get("excluded_incompatible_tests"):
                    return {
                        "success": False,
                        "error": "No affected tests are compatible with the detected runner",
                        "affected_tests_summary": aff,
                    }
                if aff.get("selection_uncertain"):
                    fallback = aff.get("selection_fallback")
                    error = (
                        "affected test selection is uncertain and no complete test matrix is available"
                        if fallback == "unavailable_test_matrix"
                        else "affected test selection is uncertain and no allowed test command is available"
                    )
                    return {
                        "success": False,
                        "error": error,
                        "selection_uncertain": True,
                        "changed_files": aff.get("changed_files", []),
                    }
                return {
                    "success": True,
                    "message": "No affected tests found for current changes",
                    "changed_files": aff.get("changed_files", []),
                    "test_files": aff.get("test_files", []),
                }
            run_res = self.commands.run(
                cmd, root, tenant,
                timeout=int(args.get("timeout", 0) or 0) or None,
                force=bool(args.get("force", False)),
                task_id=str(args.get("task_id", "")),
                criterion=str(args.get("criterion", "")),
                log_callback=log_callback,
            )
            run_res["affected_tests_summary"] = aff
            return run_res
        if action == "format":
            root = str(args.get("cwd", args.get("root", ".")))
            return self.commands.format(root, paths=args.get("paths"), tenant=tenant, timeout=int(args.get("timeout", 0) or 0) or None)
        if action == "cancel":
            return self.commands.cancel(
                str(args.get("command", "")), str(args.get("cwd", args.get("root", "."))), tenant,
                execution_id=str(args.get("execution_id", "")),
            )
        if action == "classify":
            return {"success": True, "classification": self.commands.classify(str(args.get("command", "")))}
        if action == "stats":
            return {"success": True, "stats": self.commands.stats()}
        if action == "discover":
            root = str(args.get("root", args.get("cwd", ".")))
            profile = self.repo_profile(root)
            deterministic = self.deterministic_query(root, "test lint build validation commands dependencies", 40) if self.deterministic is not None else {}
            scripts = deterministic.get("scripts", []) if isinstance(deterministic, dict) else []
            return {
                "success": bool(profile.get("success")),
                "validation_commands": profile.get("validation_commands", []),
                "manifest_scripts": scripts[:20],
                "profile_cache": profile.get("workspace_cache"),
                "deterministic": bool(scripts),
            }
        if action == "lint_fix":
            return self.lint_fix(str(args.get("cwd", args.get("root", "."))), command=args.get("command"), paths=args.get("paths"), tenant=tenant, timeout=args.get("timeout"))
        if action == "spawn_daemon":
            daemon_command = args.get("argv") if args.get("argv") is not None else str(args.get("command", ""))
            return self.spawn_daemon(
                daemon_command,
                str(args.get("cwd", args.get("root", "."))),
                name=str(args.get("name", "")),
                env=args.get("env"),
                task_id=str(args.get("task_id", "")),
            )
        if action == "daemon_status":
            task_id = str(args.get("task_id", ""))
            if not task_id:
                return {
                    "success": False,
                    "error": "daemon status requires a registered task id",
                    "policy_blocked": True,
                    "terminal": True,
                    "retryable": False,
                }
            daemon_id = args.get("daemon_id", args.get("command"))
            return self.commands.daemon_status(daemon_id, task_id=task_id)
        if action == "stop_daemon":
            return self.stop_daemon(
                str(args.get("daemon_id", args.get("task_id", args.get("command", "")))),
                task_id=str(args.get("task_id", "")),
            )
        if action == "http_probe":
            exp_status = int(args.get("expected_status", 200)) if str(args.get("expected_status", "")).isdigit() else (int(args.get("task_id", 200)) if str(args.get("task_id", "")).isdigit() else 200)
            return self.http_probe(str(args.get("url", args.get("command", ""))), expected_status=exp_status, json_path=args.get("json_path", args.get("criterion")), timeout=float(args.get("timeout", 5.0) or 5.0), headers=args.get("headers"))
        if action == "stash_save":
            return self.stash_save(str(args.get("cwd", args.get("root", "."))), message=str(args.get("criterion", args.get("command", "local_ai_hub_stash")) or "local_ai_hub_stash"))
        if action == "stash_restore":
            return self.stash_restore(str(args.get("cwd", args.get("root", "."))))
        if action == "record_mock":
            return self.record_mock(str(args.get("command", "")), str(args.get("task_id", args.get("criterion", "default_cassette"))))
        if action == "replay_mock":
            return self.replay_mock(str(args.get("command", args.get("task_id", "default_cassette"))))
        if action == "diff_hunk_stage":
            return self.diff_hunk_stage(str(args.get("cwd", args.get("root", "."))), str(args.get("patch", args.get("command", ""))))
        if action in {"flaky_detect", "test_flaky_detect"}:
            return self.test_flaky_detect(str(args.get("cwd", args.get("root", "."))), str(args.get("command", "")), runs=int(args.get("runs", 5)), timeout=int(args.get("timeout", 30)))
        if action == "webhook_replay":
            return self.webhook_replay(str(args.get("url", args.get("command", ""))), args.get("payload", {}), secret=str(args.get("secret", "")), signature_header=str(args.get("signature_header", "X-Hub-Signature-256")), timeout=float(args.get("timeout", 10.0)))
        return {"success": False, "error": f"unknown command action: {action}"}

    def _synthesize_repair_patch(self, command: str, cwd: str, failure_result: dict[str, Any]) -> dict[str, str] | None:
        """Use verified remediation or one bounded local diagnostic for a failed command."""
        if not failure_result or failure_result.get("success"):
            return None
        rem = failure_result.get("remediation") or {}
        if rem.get("verified_fix") and isinstance(rem["verified_fix"], dict):
            return {str(k): str(v) for k, v in rem["verified_fix"].items()}
        features = self.config.get("features", {})
        if not isinstance(features, dict) or not bool(features.get("tasks", True)):
            return None
        if not rollout_feature_enabled(self.config, "local_diagnostic_dispatch"):
            failure_result["local_diagnostic_dispatch"] = {
                "available": False,
                "unsupported": True,
                "feature": "local_diagnostic_dispatch",
                "error": "local diagnostic dispatch is disabled (features.local_diagnostic_dispatch=false)",
            }
            return None
        summary = failure_result.get("failure_summary") or {}
        if not isinstance(summary, dict):
            summary = {}
        confidence = 0.95 if summary.get("path") and summary.get("line") else 0.70 if summary.get("path") else 0.25
        artifact_id = str(failure_result.get("artifact_id") or "")
        preview = str(failure_result.get("preview") or "")[:800]
        # Parsed failures are deterministic enough to avoid local inference. Local
        # diagnosis is read-only and never returns a mutation candidate; repair still
        # needs a verified deterministic fix.
        if confidence >= 0.50 or not artifact_id or not preview or not self._is_bounded_diagnostic_command(command):
            return None
        model = self.config.get("models", {}).get("heavy_code", "qwen2.5-coder:7b")
        prompt = (
            f"Investigate this low-confidence command failure in {cwd}:\nCommand: {command}\n"
            f"Failure summary: {json_dumps(summary, sort_keys=True)}\n"
            f"Artifact reference: {artifact_id}\nFailure preview:\n{preview}\n"
            "Do not request or infer raw command logs; use only this bounded preview.\n"
            "Return only a short JSON diagnosis. Do not propose edits, patches, commands, architecture, or security work."
        )
        try:
            res = self.proxy_request("/api/generate", {
                "model": model,
                "prompt": prompt,
                "format": {
                    "type": "object",
                    "properties": {"diagnosis": {"type": "string"}},
                    "required": ["diagnosis"],
                    "additionalProperties": False,
                },
                "options": {"num_predict": 320},
            }, "hub", "local_ai_task", diagnostic_timeout_seconds=20)
            raw_text = str(res.get("response", "")).strip()
            parsed = json.loads(raw_text)
            diagnosis = str(parsed.get("diagnosis", "")).strip()[:600] if isinstance(parsed, dict) else ""
            if diagnosis:
                failure_result["local_diagnostic"] = diagnosis
        except Exception:
            pass
        return None

    @staticmethod
    def _is_bounded_diagnostic_command(command: str) -> bool:
        """Allow only direct, non-mutating validation commands for L1 diagnosis."""
        normalized = command.strip().lower()
        if not normalized or any(char in normalized for char in "|&;><\n\r"):
            return False
        mutation = r"(?:fix|write|apply|update|install|delete)"
        if re.search(rf"(?:^|\s)--{mutation}(?:[-_][a-z0-9]+)*(?:\s|=|$)", normalized):
            return False
        # `normalized` is lowercase, so this also rejects Jest's --updateSnapshot.
        if re.search(r"(?:^|\s)--(?:snapshot[-_]?update|update(?:[-_]?snapshot)?s?)(?:\s|=|$)", normalized):
            return False
        if re.search(rf"(?:^|\s)--(?:snapshot|golden|inline[-_]?snapshot)[-_]{mutation}(?:[-_][a-z0-9]+)*(?:\s|=|$)", normalized):
            return False
        if re.search(rf"(?:^|\s)--(?:snapshots?|goldens?|inline[-_]?snapshot)(?:\s|=){mutation}(?:\s|$)", normalized):
            return False
        if re.search(r"(?:^|\s)-u(?:\s|=|$)", normalized):
            return False
        python = r"(?:python(?:\.exe)?|py(?:\.exe)?)"
        patterns = (
            rf"^{python}\s+(?:-[a-z0-9_-]+\s+)*-m\s+(?:pytest|unittest|mypy|pyright|ruff|flake8)(?:\s|$)",
            r"^(?:pytest|unittest|mypy|pyright|ruff|flake8|eslint|tsc)(?:\s|$)",
            r"^(?:npm|pnpm|yarn)\s+test(?:\s|$)",
            r"^(?:go|cargo|dotnet|gradle|mvn)\s+test(?:\s|$)",
        )
        return any(re.match(pattern, normalized) is not None for pattern in patterns)

    @staticmethod
    def _proxy_timeout_seconds(config: dict[str, Any], diagnostic_timeout_seconds: float | None = None) -> float:
        """Keep normal proxy timeouts intact; cap only explicit diagnostic calls."""
        if diagnostic_timeout_seconds is not None:
            return min(60.0, max(1.0, float(diagnostic_timeout_seconds)))
        return max(1.0, float(config.get("server", {}).get("request_timeout_seconds", 300)))

    def proxy_request(
        self,
        endpoint: str,
        payload: dict[str, Any],
        tenant: str,
        source: str,
        *,
        diagnostic_timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        if payload.get("stream") is True:
            return {"success": False, "error": "streaming is intentionally disabled through the affinity queue"}
        model = str(payload.get("model") or self.config.get("models", {}).get("general", "qwen2.5-coder:7b"))
        clean = dict(payload)
        clean.pop("_hub_timeout_seconds", None)
        has_diagnostic_cap = diagnostic_timeout_seconds is not None
        request_timeout = self._proxy_timeout_seconds(self.config, diagnostic_timeout_seconds)
        clean["stream"] = False
        clean.setdefault("keep_alive", self.config.get("ollama", {}).get("keep_alive", "-1"))
        clean.pop("priority", None)
        proxy_profile = None
        semantic_query = ""
        if endpoint in {"/api/generate", "/api/chat"}:
            promptish = clean.get("prompt", clean.get("messages", []))
            if isinstance(promptish, str) and len(promptish.strip()) >= 8:
                semantic_query = promptish.strip()
            elif isinstance(promptish, list) and promptish:
                last_msg = promptish[-1]
                if isinstance(last_msg, dict) and isinstance(last_msg.get("content"), str):
                    semantic_query = last_msg.get("content", "").strip()

            input_tokens = estimate_tokens(json_dumps(promptish, ensure_ascii=False, default=str) if not isinstance(promptish, str) else promptish)
            opts = clean.get("options", {}) if isinstance(clean.get("options"), dict) else {}
            output_tokens = int(opts.get("num_predict", 0) or 0)
            clean, proxy_profile = self.model_policy.apply_payload(
                model, clean, role="proxy", input_tokens=input_tokens, output_tokens=output_tokens,
                preserve_explicit_think=True,
            )
            # Pre-flight context compaction & ceiling clamp
            if proxy_profile is not None and input_tokens > proxy_profile.prompt_budget_tokens:
                budget = proxy_profile.prompt_budget_tokens
                if isinstance(clean.get("prompt"), str):
                    p_text = clean["prompt"]
                    target_chars = max(500, int(budget * 3.5))
                    if len(p_text) > target_chars:
                        head_len = int(target_chars * 0.4)
                        tail_len = int(target_chars * 0.4)
                        clean["prompt"] = (
                            p_text[:head_len]
                            + "\n\n[...context compacted by Local AI Hub for model budget...]\n\n"
                            + p_text[-tail_len:]
                        )
                elif isinstance(clean.get("messages"), list) and len(clean["messages"]) > 2:
                    msgs = list(clean["messages"])
                    system_msgs = [m for m in msgs if m.get("role") == "system"]
                    other_msgs = [m for m in msgs if m.get("role") != "system"]
                    while other_msgs and estimate_tokens(json_dumps(system_msgs + other_msgs)) > budget:
                        if len(other_msgs) <= 1:
                            break
                        other_msgs.pop(0)
                    # KV-Cache prefix stabilization: ensure system message content is canonical and placed first
                    for sm in system_msgs:
                        if isinstance(sm.get("content"), str):
                            sm["content"] = sm["content"].replace("\r\n", "\n").strip()
                    clean["messages"] = system_msgs + other_msgs

        if self.semantic_cache.enabled and len(semantic_query) >= 8:
            sem_scope = stable_hash({"proxy": endpoint, "model": model, "system": clean.get("system", "")})
            sem_val, sem_score = self.semantic_cache.get(sem_scope, semantic_query)
            if isinstance(sem_val, dict):
                res = copy.deepcopy(sem_val)
                res["_local_ai_cache"] = {"hit": True, "coalesced": False, "layer": "semantic", "similarity": sem_score}
                if proxy_profile is not None:
                    res["_local_ai_execution"] = proxy_profile.cache_scope()
                return res

        key = stable_hash({"proxy": endpoint, "payload": clean, "app_version": __version__})

        def compute() -> dict[str, Any]:
            submit_kwargs: dict[str, Any] = {"priority": int(payload.get("priority", 5))}
            if has_diagnostic_cap:
                submit_kwargs["wait_timeout"] = request_timeout
            return self.scheduler.submit(
                model, tenant, source, lambda: self.runtime.request(endpoint, clean, timeout=request_timeout),
                **submit_kwargs,
            )

        raw, hit, coalesced = self.generation_cache.get_or_compute(key, compute)
        result = copy.deepcopy(raw)
        result["_local_ai_cache"] = {"hit": hit, "coalesced": coalesced, "layer": "exact" if hit else "single-flight" if coalesced else "ollama"}
        if proxy_profile is not None:
            result["_local_ai_execution"] = proxy_profile.cache_scope()

        if self.semantic_cache.enabled and len(semantic_query) >= 8 and isinstance(result, dict) and result.get("success", "error" not in result):
            try:
                sem_scope = stable_hash({"proxy": endpoint, "model": model, "system": clean.get("system", "")})
                self.semantic_cache.set(sem_scope, semantic_query, result)
            except Exception:
                pass

        return result

    def batch_delegate(self, args: dict[str, Any], tenant: str) -> dict[str, Any]:
        tasks = args.get("tasks", [])
        if not isinstance(tasks, list) or not tasks:
            return {
                "success": False,
                "error": "tasks must be a non-empty array",
                "terminal": True,
                "retryable": False,
                "request_not_sent": True,
                "input_count": len(tasks) if isinstance(tasks, list) else 0,
                "accepted_count": 0,
                "rejected_count": 0,
                "rejected_indices": [],
                "results": [],
            }
        input_count = len(tasks)
        if input_count > 16:
            return {
                "success": False,
                "error": "batch exceeds the maximum of 16 tasks",
                "terminal": True,
                "retryable": False,
                "request_not_sent": True,
                "input_count": input_count,
                "accepted_count": 0,
                "rejected_count": input_count,
                "rejected_range": {"start": 0, "end_exclusive": input_count},
                "rejected_indices": list(range(min(input_count, 64))),
                "rejected_indices_truncated": input_count > 64,
                "results": [],
            }
        prepared: list[tuple[int, str, dict[str, Any]]] = []
        for i, raw in enumerate(tasks):
            item = raw if isinstance(raw, dict) else {"task": str(raw)}
            route = self.router.classify(str(item.get("task", "")), str(item.get("context", "")), str(item.get("task_type", "auto")), str(item.get("complexity", "auto")))
            prepared.append((i, route["model"], item))
        # Group work by intended model and start with the currently resident model when possible.
        try:
            active = self.scheduler.status().get("active_model")
        except Exception:
            active = None
        prepared.sort(key=lambda item: (0 if item[1] == active else 1, item[1], item[0]))
        results: dict[int, dict[str, Any]] = {}
        default_priority = int(args.get("priority", 5))
        inherited_root = args.get("root") or args.get("cwd")
        from .async_jobs import report_job_progress
        for i, _model, item in prepared:
            item = dict(item)
            item.setdefault("priority", default_priority)
            if inherited_root and not item.get("root") and not item.get("cwd"):
                item["root"] = inherited_root
            try:
                results[i] = self.delegate(item, tenant)
            except Exception as exc:
                results[i] = {
                    "success": False,
                    "error": f"batch item failed ({type(exc).__name__})",
                }
            report_job_progress(100.0 * len(results) / len(prepared), f"batch:{len(results)}/{len(prepared)}")
        return {
            "success": all(r.get("success", False) for r in results.values()),
            "input_count": input_count,
            "accepted_count": input_count,
            "rejected_count": 0,
            "rejected_indices": [],
            "results": [results[i] for i in range(input_count)],
        }

    def optimize_databases(self) -> dict[str, Any]:
        """Checkpoint WAL files and run SQLite's optimize pragma for each store."""
        state_dir = Path(self.config["server"]["state_dir"])
        db_files = _active_sqlite_databases(state_dir)
        details = []
        bytes_freed = 0
        succeeded = 0
        for db in db_files:
            try:
                before_size = db.stat().st_size
                with closing(connect_sqlite(db, timeout_seconds=10.0)) as con:
                    checkpoint = con.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                    checkpoint_result = checkpoint.fetchone()
                    if checkpoint_result and checkpoint_result[0]:
                        raise RuntimeError("WAL checkpoint remained busy")
                    con.execute("PRAGMA optimize;")
                after_size = db.stat().st_size
                freed = max(0, before_size - after_size)
                bytes_freed += freed
                succeeded += 1
                details.append({"db": db.name, "success": True, "before_kb": before_size // 1024, "after_kb": after_size // 1024, "freed_kb": freed // 1024})
            except Exception as exc:
                details.append({"db": db.name, "success": False, "error": f"{type(exc).__name__}: {str(exc)[:400]}"})
        attempted = len(db_files)
        failed = attempted - succeeded
        return {
            "success": failed == 0,
            "partial": succeeded > 0 and failed > 0,
            **({"error": f"{failed} of {attempted} database maintenance operations failed"} if failed else {}),
            "databases_attempted": attempted,
            "databases_succeeded": succeeded,
            "databases_failed": failed,
            "databases_optimized": succeeded,
            "total_freed_kb": bytes_freed // 1024,
            "details": details,
        }

    def purge_stale_cache(self, days: int = 7) -> dict[str, Any]:
        """Purge cache entries older than N days to free disk space."""
        state_dir = Path(self.config["server"]["state_dir"])
        cutoff = time.time() - (days * 86400)
        cache_db = state_dir / "cache.sqlite"
        deleted_entries = 0
        if cache_db.is_file():
            try:
                with closing(connect_sqlite(cache_db, timeout_seconds=10.0)) as con:
                    cur = con.execute("DELETE FROM cache_entries WHERE accessed_at < ?", (cutoff,))
                    deleted_entries = cur.rowcount
                    con.commit()
                    con.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except Exception as exc:
                return {"success": False, "error": str(exc)}
        return {"success": True, "purged_entries": deleted_entries, "days_threshold": days}

    def resolve_all_errors(self, *, timeout_seconds: float = 2.0) -> dict[str, Any]:
        """Acknowledge and resolve all operational failures, crashes, errors, and agent incidents."""
        deadline = time.monotonic() + max(0.001, min(10.0, float(timeout_seconds)))

        def remaining() -> float:
            budget = deadline - time.monotonic()
            if budget <= 0:
                raise TimeoutError("error resolution time budget exceeded")
            return budget

        telemetry_res: dict[str, Any] = {}
        retryable = False
        if self.telemetry:
            try:
                telemetry_res = self.telemetry.resolve_errors(timeout_seconds=remaining())
            except TimeoutError:
                telemetry_res = {"success": False, "retryable": True, "error": "telemetry resolution time budget exceeded"}
            except Exception as exc:
                telemetry_res = {"success": False, "error_type": type(exc).__name__}
            retryable = bool(telemetry_res.get("retryable"))

        resolved_incidents = 0
        if self.incident_store:
            try:
                resolved_incidents = self.incident_store.resolve_all(
                    verified_fix="Resolved by operator",
                    root_cause="Operator manual resolve",
                    timeout_seconds=remaining(),
                )
            except TimeoutError:
                resolved_incidents = -1
                retryable = True
            except Exception:
                resolved_incidents = -1

        success = telemetry_res.get("success", True) is not False and resolved_incidents >= 0
        if not success:
            return {"success": False, "degraded": True, "retryable": retryable,
                    "telemetry": telemetry_res, "resolved_incidents": resolved_incidents}
        try:
            state_dir = Path(self.config["server"]["state_dir"])
            sup_status_path = state_dir / "supervisor.status.json"
            if sup_status_path.exists():
                raw = json.loads(sup_status_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    raw["restarts"] = 0
                    raw["last_error"] = ""
                    sup_status_path.write_text(json_dumps(raw, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

        return {
            "success": True,
            "telemetry": telemetry_res,
            "resolved_incidents": resolved_incidents,
        }

    def run_doctor(self) -> dict[str, Any]:
        """Run comprehensive system, GPU, model, and database diagnostics."""
        from .gpu_monitor import get_gpu_telemetry
        from .llama_cpp_runtime import llama_cpp_backend_selection
        checks = []

        selected = llama_cpp_backend_selection(self.config)
        if selected == "disabled":
            checks.append({"component": "Inference Backend", "status": "OFF", "detail": "Ollama and llama.cpp are disabled."})
        elif selected == "ollama":
            online = self.runtime.is_online()
            checks.append({"component": "Inference Backend (Ollama)", "status": "OK" if online else "FAIL", "detail": f"Installed models: {len(self.runtime.installed_models())}"})
        else:
            online = self.runtime.llama_cpp.is_online()
            runtime_status = self.runtime.llama_cpp_managed.status() if selected == "llama.cpp (managed)" else {}
            mode = str(runtime_status.get("mode", "") or "device unreported")
            detail = f"Selected provider: {selected}; server {'online' if online else 'unavailable'}"
            if selected == "llama.cpp (managed)":
                detail += f"; execution device: {mode}"
                if not online and runtime_status.get("last_error"):
                    detail += f"; {runtime_status['last_error']}"
            checks.append({"component": "Inference Backend (llama.cpp)", "status": "OK" if online else "FAIL", "detail": detail})
        
        gpu = get_gpu_telemetry()
        checks.append({
            "component": "NVIDIA GPU",
            "status": "OK" if gpu.get("available") else "WARN",
            "detail": f"{gpu.get('gpu_name', 'N/A')} · {gpu.get('vram_used_mb', 0):.0f} / {gpu.get('vram_total_mb', 0):.0f} MB VRAM ({gpu.get('temperature_c', 0)}°C)"
        })
        
        state_dir = Path(self.config["server"]["state_dir"])
        dbs = _active_sqlite_databases(state_dir)
        checks.append({"component": "SQLite Databases", "status": "OK", "detail": f"{len(dbs)} active databases in {state_dir.name}"})
        
        prep_status = self.preprocessor.status() if self.preprocessor else {}
        checks.append({"component": "Preprocessor", "status": "OK" if prep_status.get("enabled") else "OFF", "detail": f"{len(prep_status.get('projects', []))} projects tracked"})
        
        return {"success": True, "timestamp": time.time(), "checks": checks}

    def eval_suite(self, payload: dict[str, Any], tenant: str = "default") -> dict[str, Any]:
        """Run bounded local agent benchmark evaluation test cases."""
        suite_name = str(payload.get("suite_name", "default"))
        requested_model = str(payload.get("model") or getattr(self, "config", {}).get("models", {}).get("fast_code", "qwen2.5-coder:3b"))
        benchmark_kind = str(payload.get("benchmark_kind", "text") or "text").strip().lower()
        cases = payload.get("cases") or [
            {"id": "c1", "input": "def add(a, b):", "expected": "return a + b"},
            {"id": "c2", "input": "def is_even(n):", "expected": "return n % 2 == 0"},
        ]
        configured_roles = tuple(
            str(role)
            for role, model in (getattr(self, "config", {}).get("models", {}) or {}).items()
            if str(model or "") == requested_model and str(role) not in {"embedding", "embedding_backend", "embedding_device", "reranker", "reranker_backend", "reranker_device"}
        )
        vision_only = bool(configured_roles) and all(role == "vision" for role in configured_roles)
        if vision_only and benchmark_kind != "vision":
            mismatch_cases = []
            for case in cases:
                case_id = str(case.get("id", "case"))
                mismatch_cases.append({
                    "case_id": case_id,
                    "model": requested_model,
                    "status": "role_mismatch",
                    "passed": False,
                    "error": f"model is configured only for vision role: {', '.join(configured_roles)}",
                    "response_chars": 0,
                    "response_tokens_est": 0,
                    "response_sha256": hashlib.sha256(b"").hexdigest(),
                    "response_preview": "",
                    "response_preview_truncated": False,
                    "duration_ms": 0.0,
                })
            return {
                "success": True,
                "suite": suite_name,
                "model": requested_model,
                "model_roles": list(configured_roles),
                "benchmark_kind": benchmark_kind,
                "summary": {
                    "total": len(cases),
                    "passed": 0,
                    "failed": len(cases),
                    "pass_rate": 0.0,
                    "execution_failures": 0,
                    "benchmark_valid": False,
                    "role_mismatch": True,
                },
                "cases": mismatch_cases,
            }
        results = []
        passed = 0
        execution_failures = 0
        for case in cases:
            c_id = str(case.get("id", "case"))
            c_in = str(case.get("input", ""))
            c_exp = str(case.get("expected", ""))
            started = time.perf_counter()
            try:
                response = self.runtime.request("/api/generate", {
                    "model": requested_model,
                    "prompt": c_in,
                    "system": "Return the shortest correct answer containing the requested completion. Output only the answer; no greeting, explanation, or generic advice.",
                    "stream": False,
                    # Evaluation cases measure visible task output, not hidden
                    # reasoning.  Without this, Qwen3.5 can consume the whole
                    # small eval budget in `thinking` and look like a bad model.
                    "think": False,
                    "options": {"num_predict": 128, "temperature": 0.0},
                })
                response = response if isinstance(response, dict) else {"error": "runtime returned a non-object response"}
                error = str(response.get("error", "") or "")
                response_text = str(response.get("response", response.get("text", "")) or "")
                message = response.get("message")
                if not response_text and isinstance(message, dict):
                    response_text = str(message.get("content", "") or "")
                is_pass = bool(c_exp and not error and c_exp in response_text)
                if error:
                    execution_failures += 1
                    lowered = error.lower()
                    status = "unavailable" if any(marker in lowered for marker in ("404", "not found", "unavailable", "no route")) else "error"
                else:
                    status = "passed" if is_pass else "failed"
                lowered_text = response_text.casefold()
                generic_markers = ("certainly!", "below is", "here is", "this function", "hope this helps")
                generic_filler = any(marker in lowered_text for marker in generic_markers)
                concise_limit = max(240, len(c_exp) * 6)
                style_quality = {
                    "contains_expected": is_pass,
                    "exact_expected": response_text.strip() == c_exp.strip(),
                    "generic_filler": generic_filler,
                    "concise": len(response_text.strip()) <= concise_limit,
                    "quality_pass": bool(is_pass and not generic_filler and len(response_text.strip()) <= concise_limit),
                }
                result = {
                    "case_id": c_id,
                    "model": requested_model,
                    "passed": is_pass,
                    "status": status,
                    "response_chars": len(response_text),
                    "response_tokens_est": estimate_tokens(response_text),
                    "response_sha256": hashlib.sha256(response_text.encode("utf-8")).hexdigest(),
                    "response_preview": response_text[:240],
                    "response_preview_truncated": len(response_text) > 240,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "style_quality": style_quality,
                }
                if error:
                    result["error"] = error
            except Exception as exc:
                is_pass = False
                execution_failures += 1
                result = {
                    "case_id": c_id,
                    "model": requested_model,
                    "passed": False,
                    "status": "error",
                    "error": str(exc),
                    "response_chars": 0,
                    "response_tokens_est": 0,
                    "response_sha256": hashlib.sha256(b"").hexdigest(),
                    "response_preview": "",
                    "response_preview_truncated": False,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                }
            results.append(result)
            if is_pass:
                passed += 1

        quality_passed = sum(
            1 for item in results
            if isinstance(item, dict) and bool((item.get("style_quality") or {}).get("quality_pass"))
        )
        return {
            "success": True,
            "suite": suite_name,
            "model": requested_model,
            "model_roles": list(configured_roles),
            "benchmark_kind": benchmark_kind,
            "summary": {
                "total": len(cases),
                "passed": passed,
                "failed": len(cases) - passed,
                "pass_rate": round(passed / max(1, len(cases)), 2),
                "execution_failures": execution_failures,
                "benchmark_valid": True,
                "role_mismatch": False,
                "quality_passed": quality_passed,
                "quality_pass_rate": round(quality_passed / max(1, len(cases)), 2),
            },
            "cases": results,
        }

    def prompt_eval(self, payload: dict[str, Any], tenant: str = "default") -> dict[str, Any]:
        """Evaluate and render dynamic prompt templates with variable substitution and token estimation."""
        template = str(payload.get("template", ""))
        variables = payload.get("variables", {}) if isinstance(payload.get("variables"), dict) else {}
        rendered = template
        for k, v in variables.items():
            rendered = rendered.replace(f"{{{{{k}}}}}", str(v))
            rendered = rendered.replace(f"{{{k}}}", str(v))

        token_est = estimate_tokens(rendered)
        return {
            "success": True,
            "template": template,
            "rendered_prompt": rendered,
            "token_estimate": token_est,
            "variables_applied": list(variables.keys()),
        }

    def eval_drift(self, payload: dict[str, Any], tenant: str = "default") -> dict[str, Any]:
        """Track accuracy and regression drift across benchmark runs."""
        suite_name = str(payload.get("suite_name", "default"))
        history_file = Path(self.state_dir) / "eval_history.json"
        
        history: dict[str, Any] = {}
        if history_file.is_file():
            try:
                history = json.loads(history_file.read_text(encoding="utf-8"))
            except Exception:
                history = {}

        if "current" in payload and isinstance(payload["current"], dict):
            current = payload["current"]
        else:
            current = self.eval_suite(payload, tenant)

        current_summary = current.get("summary", {})
        curr_rate = float(current_summary.get("pass_rate", 0.0))
        
        prev_entry = history.get(suite_name)
        if prev_entry:
            prev_rate = float(prev_entry.get("summary", {}).get("pass_rate", 0.0))
            delta = round(curr_rate - prev_rate, 3)
            if delta > 0.01:
                status = "improved"
            elif delta < -0.01:
                status = "regressed"
            else:
                status = "stable"
        else:
            prev_rate = curr_rate
            delta = 0.0
            status = "baseline"

        history[suite_name] = {
            "timestamp": time.time(),
            "summary": current_summary,
            "cases": current.get("cases", []),
        }
        try:
            from .process_utils import atomic_write_file
            atomic_write_file(history_file, json_dumps(history, indent=2))
        except Exception:
            pass

        return {
            "success": True,
            "suite": suite_name,
            "status": status,
            "current_pass_rate": curr_rate,
            "previous_pass_rate": prev_rate,
            "drift_delta": delta,
            "summary": current_summary,
        }
