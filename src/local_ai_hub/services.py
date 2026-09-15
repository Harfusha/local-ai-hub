from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import time
import threading
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

from . import __version__
from .artifacts import ArtifactStore
from .budget import chars_for_tokens, estimate_tokens, fit_text
from .cache import MemoryLRUCache, SQLiteCache, TieredCache, SingleFlightCache, SingleFlightGroup, stable_hash
from .conversations import ConversationStore
from .normalizer import normalize_query, postprocess_model_output
from .semantic_cache import SemanticGenerationCache
from .model_policy import ModelExecutionPolicy
from .ollama_subagents import OllamaSubagentCatalog
from .repo_tools import RepositoryTools
from .router import ModelRouter, review_diff_complexity
from .telemetry import TelemetryStore
from .trace_context import observer


def normalize_generation_cache_prompt(prompt: str) -> str:
    """Normalize only transport-level line endings for exact prompt reuse."""
    return str(prompt).replace("\r\n", "\n").replace("\r", "\n")


def cache_decision_reason(cache_layer: str, *, semantic_query: str) -> str:
    if cache_layer == "semantic":
        return "semantic_reuse"
    if cache_layer == "single-flight":
        return "singleflight_reuse"
    if cache_layer == "stale-on-error":
        return "stale_on_error"
    if cache_layer == "ollama" and semantic_query:
        return "semantic_not_reused"
    if cache_layer == "ollama":
        return "new_exact_key"
    return "exact_reuse"


_REVIEW_DIFF_MIN_CHUNK_TOKENS = 256
_REVIEW_DIFF_CONTEXT_FRACTION = 0.5
_MAX_REVIEW_DIFF_CHUNKS = 8
_REVIEW_SYNTHESIS_CONTEXT_TOKENS = 6000
_UNIFIED_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


def _review_text_error(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return "Model returned empty review output."
    text = value.strip()
    match = re.match(r"^(?:\*\*)?SUMMARY(?:\*\*)?:\s*(.*)$", text, re.IGNORECASE | re.DOTALL)
    if match is None:
        return "Model output did not start with the required SUMMARY: header."
    words = re.findall(r"[^\W\d_]+", match.group(1), flags=re.UNICODE)
    if len(words) < 2:
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
    budget = max(_REVIEW_DIFF_MIN_CHUNK_TOKENS, int(max_tokens))
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
) -> str:
    return stable_hash({
        "model": model,
        "prompt": normalize_generation_cache_prompt(prompt),
        "system": normalize_generation_cache_prompt(system),
        "options": options,
        "think": think,
        "execution": execution,
        "format": format,
        "app_version": __version__,
    })


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


class LocalAIServices:
    commands: Any = None
    task_store: Any = None
    verification_store: Any = None
    incident_store: Any = None
    rag: Any = None
    token_router: Any = None
    pipeline: Any = None
    preprocessor: Any = None
    tool_agent: Any = None
    blackboard: Any = None
    agent_state: Any = None

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
        self.task_store: Any | None = None
        self.verification_store: Any | None = None
        self.incident_store: Any | None = None
        self.router = ModelRouter(config)
        self.model_policy = ModelExecutionPolicy(config)
        self.profile_catalog = OllamaSubagentCatalog(config)
        self.rag: Any | None = None
        self.token_router: Any | None = None
        self.pipeline: Any | None = None
        self.preprocessor: Any | None = None
        self.tool_agent: Any | None = None
        self.swarm: Any | None = None
        self.agent_state: Any | None = None
        self.flight_group = SingleFlightGroup(shards=32, default_timeout_seconds=60.0)

        cache_cfg = config.get("cache", {})
        persistent = SQLiteCache(
            Path(config["server"]["state_dir"]) / "cache.sqlite3",
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
        workspace_cfg = config.get("workspace_cache", {})
        self.repo_cache = TieredCache(
            SQLiteCache(
                Path(config["server"]["state_dir"]) / "cache.sqlite3",
                namespace="repo-results",
                ttl_seconds=int(workspace_cfg.get("repo_result_ttl_seconds", 7 * 86400)),
                max_entries=int(workspace_cfg.get("repo_result_max_entries", 20000)),
            ),
            l1_entries=int(cache_cfg.get("l1_repo_entries", 512)),
            l1_ttl_seconds=int(cache_cfg.get("l1_repo_ttl_seconds", 900)),
        )
        self.repo_flight = SingleFlightCache(self.repo_cache, enabled=True, wait_timeout_seconds=float(config.get("resilience", {}).get("singleflight_wait_timeout_seconds", 45)))
        self.semantic_cache = SemanticGenerationCache(config, embeddings)
        resilience = config.get("resilience", {})
        self.breakers = CircuitBreakerRegistry(
            failure_threshold=int(resilience.get("circuit_failure_threshold", 3)),
            cooldown_seconds=float(resilience.get("circuit_cooldown_seconds", 20)),
        )
        self.stale_generation_cache = SQLiteCache(
            Path(config["server"]["state_dir"]) / "cache.sqlite3",
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

    def _touch_project(self, root: str) -> None:
        # Local AI: repository reads refresh only explicitly registered projects.
        if self.preprocessor is not None:
            try:
                self.preprocessor.touch_if_registered(root)
            except Exception:
                pass

    def _repo_cache_state(self, root: str) -> dict[str, Any]:
        """Prefer watcher-backed preprocessing state over spawning Git on hot reads."""
        if self.preprocessor is not None:
            try:
                fast = self.preprocessor.cache_fingerprint(root)
                if isinstance(fast, dict) and fast.get("fingerprint"):
                    return fast
            except Exception:
                pass
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
    ) -> dict[str, Any]:
        saving = self.config.get("token_saving", {})
        resilience = self.config.get("resilience", {})
        max_tokens = max(64, min(int(max_tokens), int(saving.get("max_local_output_tokens", 2400))))
        role = source.rsplit(":", 1)[-1].lower()
        if source == "second-opinion":
            role = "second-opinion"
        vram_free = None
        if getattr(self, "vram_balancer", None):
            try:
                vram_free = self.vram_balancer.status().get("vram_available_mb")
            except Exception:
                pass
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

        execution_scope = execution_profile.cache_scope()
        norm_context_fp = stable_hash(normalize_context_for_hash(semantic_context_fingerprint)) if semantic_context_fingerprint else "no-context"
        cache_key = generation_cache_key(
            model=model,
            prompt=prepared.text,
            system=system,
            options=options,
            think=base_payload.get("think"),
            execution=execution_scope,
            format=base_payload.get("format"),
        )
        semantic_scope = stable_hash({
            "model": model, "system": system, "options": options, "think": base_payload.get("think"), "execution": execution_scope,
            "context": norm_context_fp, "source": source.split(":", 1)[0], "app_version": __version__,
        })
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

            candidates = [requested_model] + self._fallback_models(requested_model)
            errors: list[str] = []
            for index, candidate in enumerate(candidates):
                breaker_key = f"model:{candidate}"
                if not self.breakers.allow(breaker_key):
                    errors.append(f"{candidate}: circuit open")
                    self.telemetry.record_stage(tenant=tenant, action=source, stage="model_attempt", model=candidate, success=False, degraded=True, error_type="circuit_open")
                    continue

                def run(candidate_model: str = candidate) -> dict[str, Any]:
                    # A smart->fast resilience fallback may have a smaller context window
                    # than the originally requested model. Re-fit locally instead of
                    # relying on implicit server truncation or turning an outage into OOM.
                    candidate_hint = self.model_policy.profile(
                        candidate_model, role=role, input_tokens=prepared.estimated_tokens, output_tokens=max_tokens,
                        background=source.startswith("preprocess:"),
                    )
                    candidate_prepared = fit_text(prepared.text, min(int(saving.get("max_local_input_tokens", 56000)), candidate_hint.prompt_budget_tokens))
                    payload, candidate_profile = self.model_policy.apply_payload(
                        candidate_model,
                        {"model": candidate_model, "prompt": candidate_prepared.text, "system": system, "stream": False,
                         "keep_alive": self.config.get("ollama", {}).get("keep_alive", "-1"),
                         "options": {"num_predict": max_tokens, "temperature": float(temperature)}},
                        role=role, input_tokens=candidate_prepared.estimated_tokens, output_tokens=max_tokens,
                        background=source.startswith("preprocess:"), preserve_explicit_think=False,
                    )
                    trace_observer = observer()
                    if trace_observer is not None:
                        trace_observer.model_request(payload)
                        response = self.runtime.request_stream("/api/generate", payload, trace_observer.output_delta)
                    else:
                        response = self.runtime.request("/api/generate", payload)
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
                    if "error" in response:
                        return {"success": False, "error": response["error"], "model": candidate_model, "_lah_retry_count": int(response.get("_lah_retry_count", 0) or 0)}
                    raw_text = response.get("response", "")
                    clean_text, parsed_thinking = postprocess_model_output(raw_text, role=role)
                    thinking = response.get("thinking") or parsed_thinking
                    return {
                        "success": True, "model": candidate_model, "requested_model": requested_model,
                        "text": clean_text, "thinking": thinking,
                        "load_duration_ns": response.get("load_duration", 0), "eval_count": response.get("eval_count", 0),
                        "prompt_eval_count": response.get("prompt_eval_count", 0),
                        "prompt_eval_duration_ns": response.get("prompt_eval_duration", 0),
                        "eval_duration_ns": response.get("eval_duration", 0), "total_duration_ns": response.get("total_duration", 0),
                        "_lah_retry_count": int(response.get("_lah_retry_count", 0) or 0),
                        "execution_profile": candidate_profile.cache_scope(),
                        "_lah_cache_origin": "ollama", "fallback_used": candidate_model != requested_model,
                        "_cacheable": candidate_model == requested_model,
                    }

                try:
                    result = self.scheduler.submit(
                        candidate, tenant, source if index == 0 else f"{source}:fallback", run, priority=priority,
                        wait_timeout=float(resilience.get("scheduler_wait_timeout_seconds", self.config.get("server", {}).get("request_timeout_seconds", 300) + 30)),
                    )
                except Exception as exc:
                    result = {"success": False, "error": str(exc), "model": candidate}
                if result.get("success"):
                    self.breakers.success(breaker_key)
                    if candidate != requested_model:
                        self.fallback_count += 1
                    return result
                self.breakers.failure(breaker_key)
                attempt_error = str(result.get("error", "failed"))
                attempt_retries = int(result.get("_lah_retry_count", 0) or 0)
                self.telemetry.record_stage(tenant=tenant, action=source, stage="model_attempt", model=candidate, success=False, degraded=index > 0, retry_count=attempt_retries, error_type="model_attempt_failed")
                self.telemetry.record_error("ollama", f"{source}:model_attempt", attempt_error, tenant=tenant, retryable=True)
                errors.append(f"{candidate}: {attempt_error}")

            # Same exact prompt may be served stale only as a resilience fallback.
            if use_cache and bool(resilience.get("serve_stale_on_error", True)):
                stale = self.stale_generation_cache.get(cache_key)
                if isinstance(stale, dict):
                    reused = copy.deepcopy(stale)
                    reused["_lah_cache_origin"] = "stale"
                    reused["stale_fallback"] = True
                    reused["runtime_errors"] = errors[-3:]
                    return reused
            return {"success": False, "error": "; ".join(errors) or "all local model attempts failed", "model": requested_model}

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
                if isinstance(result, dict) and result.get("success", "error" not in result) and not result.get("fallback_used", False):
                    clean = {k: v for k, v in result.items() if not str(k).startswith("_lah_")}
                    try:
                        self.semantic_cache.set(semantic_scope, semantic_query, clean)
                    except Exception:
                        pass
                return result

        if use_cache:
            raw, cache_hit, coalesced = self.generation_cache.get_or_compute(cache_key, compute)
        else:
            raw, cache_hit, coalesced = compute_inner(), False, False
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
            if semantic_query and isinstance(raw, dict) and raw.get("success", "error" not in raw):
                clean = {k: v for k, v in raw.items() if not str(k).startswith("_lah_")}
                self.semantic_cache.set(semantic_scope, semantic_query, clean)

        if use_cache and isinstance(raw, dict) and raw.get("success", "error" not in raw) and origin != "stale" and not raw.get("fallback_used", False):
            clean_stale = {k: v for k, v in raw.items() if not str(k).startswith("_lah_")}
            self.stale_generation_cache.set(cache_key, clean_stale)

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
            try:
                self.tuner.observe(str(result.get("model", model)), result, (time.perf_counter() - started) * 1000)
            except Exception:
                pass

        success = bool(result.get("success", "error" not in result))
        error_type = "" if success else "model_request_failed"
        self.telemetry.record(
            tenant=tenant, action=source, model=str(result.get("model", model)), cache_hit=effective_cache_hit, coalesced=coalesced,
            cache_layer=cache_layer, input_tokens=prepared.estimated_tokens, output_tokens=full_output_tokens,
            avoided_cloud_tokens=max(0, int(measured_cloud_context_tokens)) + compact_saved,
            duration_ms=(time.perf_counter() - started) * 1000, queue_wait_ms=queue_wait_ms, service_ms=service_ms,
            load_duration_ms=float(result.get("load_duration_ns", 0) or 0) / 1_000_000,
            success=success, fallback_used=bool(result.get("fallback_used", False)), retry_count=retry_count,
            degraded=bool(result.get("stale_fallback", False) or result.get("fallback_used", False)), error_type=error_type,
        )
        if not success:
            self.telemetry.record_error("ollama", source, result.get("error", "model request failed"), tenant=tenant, retryable=True)
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
    ) -> dict[str, Any]:
        if estimate_tokens(prompt) + estimate_tokens(system) > self._conversation_prompt_limit():
            return self._conversation_error("", "conversation prompt limit exceeded")
        conversation = self.conversations.start(tenant, {
            "model": route["model"], "system": system, "max_tokens": max_tokens,
            "temperature": temperature, "source": source, "priority": priority,
            "route": dict(route),
        })
        self.conversations.reserve(conversation.conversation_id, tenant)
        try:
            result = self._generate(
                route["model"], prompt, system, max_tokens, temperature, tenant, source, priority,
                internal=True, use_cache=False,
            )
        except Exception:
            self.conversations.discard(conversation.conversation_id, tenant)
            raise
        if not result.get("success", "error" not in result):
            self.conversations.discard(conversation.conversation_id, tenant)
            return result
        self.conversations.complete(conversation.conversation_id, tenant, prompt, str(result.get("text", "")))
        result["conversation_id"] = conversation.conversation_id
        result["route"] = dict(route)
        return result

    def continue_conversation(self, args: dict[str, Any], tenant: str) -> dict[str, Any]:
        conversation_id = str(args.get("conversation_id", "")).strip()
        task = str(args.get("task", "")).strip()
        if not conversation_id:
            return self._conversation_error("", "conversation_id is required")
        if not task:
            return self._conversation_error(conversation_id, "task is required")
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
            )
        except Exception:
            self.conversations.abort(conversation_id, tenant)
            raise
        if not result.get("success", "error" not in result):
            self.conversations.abort(conversation_id, tenant)
            return result
        self.conversations.complete(conversation_id, tenant, user_prompt, str(result.get("text", "")))
        result["conversation_id"] = conversation_id
        result["route"] = dict(settings["route"])
        return result

    def delegate(self, args: dict[str, Any], tenant: str) -> dict[str, Any]:
        if bool(args.get("conversation", False)):
            if str(args.get("profile", "")).strip():
                return self._conversation_error("", "conversations do not support profiles")
            if str(args.get("delivery", "sync")).strip().lower() != "sync":
                return self._conversation_error("", "conversations require delivery=sync")
        if str(args.get("profile", "")).strip():
            return self.delegate_profile(args, tenant)
        task = str(args.get("task") or args.get("prompt") or "")
        context = str(args.get("context", ""))
        task_type_override = str(args.get("task_type", "auto"))
        complexity_override = str(args.get("complexity", "auto"))
        route = self.router.classify(task, context, task_type_override, complexity_override)
        route = self._resident_optimize(route, task_type_override, complexity_override)
        try:
            route = self.router.apply_model_override(route, str(args.get("model", "")))
        except ValueError as exc:
            return {"success": False, "error": str(exc), "terminal": True, "retryable": False}
        task_type = route["task_type"]
        system = {
            "code": (
                "You are a precise local coding subagent. Terse technical output only: zero conversational filler, pleasantries, or preamble. "
                "Start with `SUMMARY:` in <=5 dense lines, then only actionable evidence/patch guidance. "
                "Cite supplied file paths/lines when present. Do not restate context, do not invent repository facts, and stop after the useful answer."
            ),
            "review": (
                "You are a defect-first code reviewer. Terse technical output only: zero conversational filler, pleasantries, or preamble. "
                "Start with `SUMMARY:` then report at most 8 actionable findings ordered by severity. "
                "Prioritize correctness, regressions, security/concurrency and missing tests. Cite file/line evidence. No style commentary or praise."
            ),
            "reasoning": (
                "You are a critical engineering reasoning subagent. Terse technical output only: zero conversational filler, pleasantries, or preamble. "
                "Start with `SUMMARY:` in <=5 lines. Then give only key assumptions, "
                "failure modes, tradeoffs and the strongest counterargument. Prefer falsifiable claims over exposition."
            ),
            "general": (
                "You are a local second-brain assistant. Terse technical output only: zero conversational filler, pleasantries, or preamble. "
                "Start with `SUMMARY:` and produce the shortest answer that preserves useful facts, "
                "decisions, identifiers, numbers and uncertainty. Do not repeat the prompt."
            ),
        }[task_type]
        prompt = self._conversation_user_prompt(task, context)
        max_tokens = int(args.get("max_tokens", 1400))
        temperature = float(args.get("temperature", 0.15))
        source = f"delegate:{task_type}"
        priority = int(args.get("priority", 5))
        if bool(args.get("conversation", False)):
            return self._start_conversation(
                tenant=tenant, prompt=prompt, route=route, system=system, max_tokens=max_tokens,
                temperature=temperature, source=source, priority=priority,
            )
        format_val = args.get("format") or args.get("json_schema")
        result = self._generate(
            route["model"], prompt, system,
            max_tokens, temperature, tenant, source, priority,
            semantic_query=task, semantic_context_fingerprint=stable_hash(context),
            format=format_val,
        )
        result["route"] = route
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
        prompt = f"TASK:\n{task}\n"
        if context:
            prompt += f"\nCONTEXT:\n{context}\n"
        if candidate:
            prompt += f"\nCANDIDATE:\n{candidate}\n"
        result = self._generate(
            profile.model,
            prompt,
            self.profile_catalog.system_contract(profile, task),
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
            "model_fallback": profile.model_fallback,
            "tools_used": [],
        })
        return result

    def review(self, args: dict[str, Any], tenant: str) -> dict[str, Any]:
        payload = dict(args)
        payload["task_type"] = "review"
        payload["task"] = str(args.get("instructions", "Review the supplied code or diff and report actionable defects only."))
        payload["context"] = str(args.get("code", args.get("context", "")))
        payload.setdefault("max_tokens", 1700)
        return self.delegate(payload, tenant)

    def reason(self, args: dict[str, Any], tenant: str) -> dict[str, Any]:
        payload = dict(args)
        payload["task_type"] = "reasoning"
        payload["task"] = str(args.get("problem", args.get("task", "")))
        payload.setdefault("max_tokens", 1700)
        return self.delegate(payload, tenant)

    def second_opinion(self, args: dict[str, Any], tenant: str) -> dict[str, Any]:
        question = str(args.get("question", ""))
        candidate = str(args.get("candidate", ""))
        context = str(args.get("context", ""))
        focus = str(args.get("focus", "correctness, missing assumptions, edge cases, and alternative explanations"))
        prompt = (
            f"QUESTION:\n{question}\n\nCANDIDATE ANSWER / PLAN:\n{candidate}\n\n"
            f"ADDITIONAL CONTEXT:\n{context}\n\nFOCUS:\n{focus}\n\n"
            "Independently challenge the candidate. Return only concrete weaknesses, corrections and a stronger conclusion."
        )
        route = self.router.classify(
            f"{question}\n{focus}",
            f"{candidate}\n{context}",
            "reasoning",
            str(args.get("complexity", "auto")),
        )
        model = str(route["model"])
        result = self._generate(
            model, prompt,
            "You are an independent skeptical reviewer. Terse technical output only: zero conversational filler, pleasantries, or preamble. Do not merely agree and do not restate the candidate.",
            int(args.get("max_tokens", 1500)), float(args.get("temperature", 0.2)),
            tenant, "second-opinion", int(args.get("priority", 6)),
            semantic_query=f"{question}\n{focus}", semantic_context_fingerprint=stable_hash({"candidate": candidate, "context": context}),
        )
        result["route"] = route
        return result

    def speculative_draft(self, args: dict[str, Any], tenant: str) -> dict[str, Any]:
        """Draft code using fast model and verify against affected tests."""
        task = str(args.get("task", args.get("prompt", "")))
        file_path = str(args.get("file", args.get("path", "")))
        context = str(args.get("context", ""))
        root = str(args.get("root", args.get("cwd", ".")))
        resolved_root = Path(root).resolve()

        if not task:
            return {"success": False, "error": "task or prompt is required"}

        fast_model = str(self.config.get("models", {}).get("fast_code", "qwen2.5-coder:1.5b"))
        prompt = (
            f"TASK:\n{task}\n\n"
            f"FILE: {file_path}\n\n"
            f"CONTEXT:\n{context}\n\n"
            "Provide the exact implementation code or code replacement. Return ONLY code or diff."
        )

        gen_result = self._generate(
            fast_model,
            prompt,
            "You are a precise, fast coding specialist. Return only valid code without conversational filler.",
            int(args.get("max_tokens", 2048)),
            float(args.get("temperature", 0.1)),
            tenant,
            "speculative-draft",
            priority=5,
        )

        draft_code = gen_result.get("response", "")
        verification: dict[str, Any] = {"syntax_valid": True}
        if file_path.endswith(".py") and draft_code:
            import ast
            try:
                clean_code = re.sub(r"^```[\w]*\n", "", draft_code.strip())
                clean_code = re.sub(r"\n```$", "", clean_code)
                ast.parse(clean_code)
                verification["syntax_valid"] = True
            except Exception as e:
                verification["syntax_valid"] = False
                verification["syntax_error"] = str(e)

        if bool(args.get("verify_tests", False)) and file_path and self.commands:
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
            verification["smart_review"] = {
                "model": smart_model,
                "response": review_res.get("response", ""),
                "approved": "true" in review_res.get("response", "").lower(),
            }

        return {
            "success": True,
            "model": fast_model,
            "draft": draft_code,
            "verification": verification,
            "duration_ms": gen_result.get("duration_ms", 0),
        }

    def vision(self, args: dict[str, Any], tenant: str) -> dict[str, Any]:
        """Multimodal image understanding via local vision model."""
        image_path = str(args.get("image", args.get("image_path", "")))
        prompt = str(args.get("prompt", args.get("task", "Describe this image in detail.")))
        model = str(args.get("model") or self.config.get("models", {}).get("vision", "llava"))

        images = []
        if image_path:
            p = Path(image_path)
            if p.is_file():
                import base64
                try:
                    b64 = base64.b64encode(p.read_bytes()).decode("utf-8")
                    images.append(b64)
                except Exception as e:
                    return {"success": False, "error": f"Failed to read image file: {e}"}
            else:
                images.append(image_path)

        if not images:
            return {"success": False, "error": "image path or base64 data required"}

        payload = {
            "model": model,
            "prompt": prompt,
            "images": images,
            "stream": False,
        }
        try:
            res = self.runtime.request("/api/generate", payload)
            return {
                "success": True,
                "model": model,
                "response": res.get("response", ""),
                "prompt": prompt,
            }
        except Exception as exc:
            return {"success": False, "error": f"Vision model inference failed: {exc}", "model": model}

    def transcribe(self, args: dict[str, Any], tenant: str) -> dict[str, Any]:
        """Transcribe audio recording to text via local Whisper / STT CLI or fallback."""
        audio_path = str(args.get("audio", args.get("audio_path", "")))
        model = str(args.get("model") or "whisper")

        p = Path(audio_path).expanduser().resolve(strict=False)
        if not p.is_file():
            return {"success": False, "error": f"audio file not found: {audio_path}"}

        whisper_cmd = shutil.which("whisper")
        if whisper_cmd:
            cmd = [whisper_cmd, str(p), "--output_format", "txt", "--model", "tiny"]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False, **hidden_run_kwargs())
                if proc.returncode == 0:
                    txt_path = p.with_suffix(".txt")
                    text = txt_path.read_text(encoding="utf-8", errors="replace") if txt_path.exists() else proc.stdout
                    return {
                        "success": True,
                        "text": text.strip(),
                        "audio_path": str(p),
                        "model": model,
                        "engine": "whisper_cli",
                    }
            except Exception:
                pass

        return {
            "success": True,
            "text": f"[Audio transcription registered: {p.name}]",
            "audio_path": str(p),
            "file_size_bytes": p.stat().st_size,
            "format": p.suffix.lstrip("."),
            "model": model,
            "engine": "local_stt_fallback",
            "degraded": True,
            "note": "Local whisper CLI not installed in PATH; audio metadata processed.",
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



    def embed(self, texts: list[str], tenant: str, priority: int = 3, query: bool = False, background: bool | None = None, wait_timeout: float | None = None) -> dict[str, Any]:
        backend = self.config["models"].get("embedding_backend", "sentence-transformers")
        model = str(self.config.get("models", {}).get("embedding", "qwen3-embedding:0.6b"))
        if backend in {"sentence-transformers", "openvino"}:
            return self.embeddings.encode(texts, query=query, priority=priority)

        if not texts:
            return {"success": True, "model": model, "backend": "ollama", "embeddings": []}
        batch_size = int(self.config.get("rag", {}).get("embedding_batch_size", 12))

        def run() -> dict[str, Any]:
            all_vectors: list[list[float]] = []
            for start in range(0, len(texts), batch_size):
                response = self.runtime.request("/api/embed", {"model": model, "input": texts[start:start + batch_size]})
                if "error" in response:
                    return {"success": False, "error": response["error"], "model": model}
                all_vectors.extend(response.get("embeddings", []))
            return {"success": True, "model": model, "backend": "ollama", "embeddings": all_vectors}

        is_bg = background if background is not None else (priority <= 1)
        return self.scheduler.submit(model, tenant, "embed", run, priority=priority, background=is_bg, wait_timeout=wait_timeout)

    def _repo_cached(self, operation: str, root: str, params: dict[str, Any], compute: Any) -> dict[str, Any]:
        # Worktrees/temp repositories can disappear between an agent request and a
        # coalesced background computation. Treat that as a stale input, not a hub 500.
        try:
            self._touch_project(root)
            state = self._repo_cache_state(root) or {}
            key = stable_hash({"op": operation, "state": state.get("fingerprint"), "params": params})
            raw, hit, coalesced = self.repo_flight.get_or_compute(key, compute)
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
            "degraded": bool(state.get("degraded", False)), "stale": bool(state.get("stale", False)),
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

    def repo_search(self, root: str, query: str, top_k: int = 12) -> dict[str, Any]:
        # Search itself is case-insensitive and whitespace-tolerant. Use the same
        # canonical form for cache identity so equivalent agent queries reuse work.
        query = normalize_query(query).casefold()
        if self.learner is not None:
            try: self.learner.record(root, query)
            except Exception: pass
        # Local AI deterministic facts/symbols are the cheapest candidate source.
        paths: list[str] = []
        if self.deterministic is not None:
            try: paths.extend(self.deterministic.related_paths(root, query, max(16, top_k * 3)))
            except Exception: pass
        if self.code_index is not None:
            try:
                for p in self.code_index.related_paths(root, query, max(16, top_k * 3)):
                    if p not in paths: paths.append(p)
            except Exception: pass
        # Warm preprocessing maintains FTS + semantic cards specifically so agents do
        # not need broad scans. Treat these only as candidates; exact source search
        # remains the fallback when a card/FTS hint produces no matches.
        if self.preprocessor is not None:
            try:
                for p in self.preprocessor.candidate_paths(root, query, max(16, top_k * 3)):
                    if p not in paths:
                        paths.append(p)
            except Exception:
                pass
        def compute() -> dict[str, Any]:
            targeted = self.repo_tools.search_paths(root, query, paths, top_k) if paths else {"results": []}
            used_preprocessed = bool(paths and targeted.get("results"))
            result = targeted if targeted.get("results") else self.repo_tools.search(root, query, top_k)
            result["preprocessed_hit"] = used_preprocessed
            # Exact search snippets become immutable evidence so agent projections can
            # send coordinates first and raw source only for the top few hits.
            if self.evidence_store is not None and isinstance(result.get("results"), list):
                try:
                    result = dict(result)
                    result["results"] = self.evidence_store.put_many(str(result.get("root", root)), result["results"])
                    result["progressive_disclosure"] = True
                except Exception:
                    pass
            return result
        return self._repo_cached("search", root, {"query": query, "top_k": top_k, "ci": paths[:24]}, compute)

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
                target = (base / rel).resolve(strict=False)
                try:
                    target.relative_to(base)
                except ValueError:
                    continue
                if target.is_file():
                    try:
                        existing.append((rel, self.repo_tools._hash_file_only(target)))
                    except Exception:
                        pass
                else:
                    missing.append(rel)
            if self.code_index is not None:
                if existing and hasattr(self.code_index, "update_files_batch"):
                    self.code_index.update_files_batch(str(base), existing)
                for rel in missing:
                    try: self.code_index.update_file(str(base), rel)
                    except Exception: pass
            if self.deterministic is not None:
                if existing and hasattr(self.deterministic, "update_files_batch"):
                    self.deterministic.update_files_batch(str(base), existing)
                for rel in missing:
                    try: self.deterministic.update_file(str(base), rel)
                    except Exception: pass
            with self._index_refresh_lock:
                if fp:
                    self._index_refresh_state[root_key] = fp
                    if len(self._index_refresh_state) > 256:
                        self._index_refresh_state.pop(next(iter(self._index_refresh_state)), None)
        except Exception:
            # Query correctness still falls back to the last durable index plus exact
            # lexical/source tools; this accelerator must never turn a query into 500.
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

    def code_query(self, root: str, query: str, limit: int = 20) -> dict[str, Any]:
        if self.code_index is None:
            return {"success": False, "error": "code index unavailable"}
        if self.learner is not None:
            try: self.learner.record(root, query)
            except Exception: pass
        try:
            canonical = {"terms": sorted(set(self.code_index._query_terms(query))), "limit": limit}
        except Exception:
            canonical = {"query": " ".join(query.lower().split()), "limit": limit}
        def compute() -> dict[str, Any]:
            self._refresh_changed_intelligence(root)
            res = self.code_index.query(root, query, limit)
            if isinstance(res, dict):
                res["preprocessed_hit"] = bool(res.get("success") and res.get("symbols"))
            return res
        return self._repo_cached("code-index", root, canonical, compute)

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

    def test_matrix(self, root: str) -> dict[str, Any]:
        return self.deterministic_operation("test-matrix", root, {}, lambda: self.deterministic.test_matrix(root))

    def affected_tests(self, root: str, changed_paths: list[str] | None = None, base: str = "HEAD") -> dict[str, Any]:
        params = {"changed_paths": sorted(changed_paths or []), "base": base}
        return self.deterministic_operation("affected-tests", root, params, lambda: self.deterministic.affected_tests(root, changed_paths, base))

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

    def worktree_release(self, root: str, worktree_path: str, delete_branch: bool = True, branch_name: str | None = None) -> dict[str, Any]:
        from .process_utils import remove_git_worktree
        return remove_git_worktree(root, worktree_path, delete_branch=delete_branch, branch_name=branch_name)

    def list_worktrees(self, root: str) -> dict[str, Any]:
        from .process_utils import list_git_worktrees
        return list_git_worktrees(root)

    def prune_worktrees(self, root: str) -> dict[str, Any]:
        from .process_utils import prune_git_worktrees
        return prune_git_worktrees(root)


    def spawn_daemon(self, command: str, cwd: str, name: str = "", env: dict[str, str] | None = None) -> dict[str, Any]:
        if not self.commands:
            return {"success": False, "error": "command broker unavailable"}
        return self.commands.spawn_daemon(command, cwd, name=name, env=env)

    def daemon_status(self, daemon_id: str | None = None) -> dict[str, Any]:
        if not self.commands:
            return {"success": False, "error": "command broker unavailable"}
        return self.commands.daemon_status(daemon_id)

    def stop_daemon(self, daemon_id: str) -> dict[str, Any]:
        if not self.commands:
            return {"success": False, "error": "command broker unavailable"}
        return self.commands.stop_daemon(daemon_id)

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

    def refactor_impact(self, root: str, file_path: str, symbol: str) -> dict[str, Any]:
        return self.deterministic_operation("refactor-impact", root, {"file": file_path, "symbol": symbol}, lambda: self.deterministic.refactor_impact(root, file_path, symbol))

    def resolve_imports(self, root: str, symbols: list[str], language: str = "auto") -> dict[str, Any]:
        params = {"symbols": sorted(str(x) for x in symbols), "language": language}
        return self.deterministic_operation("resolve-imports", root, params, lambda: self.deterministic.resolve_imports(root, symbols, language))

    def callers(self, root: str, symbol: str, limit: int = 50) -> dict[str, Any]:
        return self.deterministic_operation("callers", root, {"symbol": symbol, "limit": limit}, lambda: self.deterministic.find_callers(root, symbol, limit))

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

    def generate_types(self, root: str, file_path: str, write_stub: bool = False) -> dict[str, Any]:
        return self.deterministic_operation("generate-types", root, {"file": file_path, "write": write_stub}, lambda: self.deterministic.generate_types(root, file_path, write_stub))

    def code_complexity(self, root: str, path: str | None = None, max_results: int = 20) -> dict[str, Any]:
        return self.deterministic_operation("code-complexity", root, {"path": path, "max": max_results}, lambda: self.deterministic.code_complexity(root, path, max_results))

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

    def git_diff(self, root: str, path: str | None = None, staged: bool = False, max_lines: int = 1000) -> dict[str, Any]:
        return self.deterministic_operation("git-diff", root, {"path": path, "staged": staged, "max_lines": max_lines}, lambda: self.deterministic.git_diff(root, path=path, staged=staged, max_lines=max_lines))

    def git_history_search(self, root: str, query: str, max_commits: int = 20) -> dict[str, Any]:
        return self.deterministic_operation("git-history-search", root, {"query": query, "max_commits": max_commits}, lambda: self.deterministic.git_history_search(root, query, max_commits=max_commits))

    def find_hotspots(self, root: str, days: int = 30, limit: int = 20) -> dict[str, Any]:
        return self.deterministic_operation("find-hotspots", root, {"days": days, "limit": limit}, lambda: self.deterministic.find_hotspots(root, days=days, limit=limit))

    def generate_tests_for_diff(self, root: str, diff: str | None = None, path: str | None = None) -> dict[str, Any]:
        return self.deterministic_operation("generate-tests-for-diff", root, {"diff": bool(diff), "path": path}, lambda: self.deterministic.generate_tests_for_diff(root, diff=diff, path=path))

    def cross_repo_contract(self, backend_root: str, frontend_root: str) -> dict[str, Any]:
        return self.deterministic_operation("cross-repo-contract", backend_root, {"frontend_root": frontend_root}, lambda: self.deterministic.cross_repo_contract(backend_root, frontend_root))

    def mock_server_start(self, root: str = ".", spec_path: str | None = None, port: int = 11440) -> dict[str, Any]:
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

    def test_flaky_detect(self, root: str, command: str, runs: int = 5, timeout: int = 30) -> dict[str, Any]:
        if not self.commands:
            return {"success": False, "error": "command broker unavailable"}
        return self.commands.test_flaky_detect(root, command, runs=runs, timeout_per_run=timeout)

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
        return SwarmPubSub.get_default().publish(topic, message, sender=sender)

    def pubsub_poll(self, topic: str, since_timestamp: float = 0.0, limit: int = 50) -> dict[str, Any]:
        from .agent_events import SwarmPubSub
        return SwarmPubSub.get_default().poll(topic, since_timestamp=since_timestamp, limit=limit)

    def synthesize_commit(self, root: str, hint: str = "", task_id: str = "") -> dict[str, Any]:
        tasks_data: list[dict[str, Any]] = []
        receipts_data: list[dict[str, Any]] = []

        if self.task_store is not None:
            try:
                if task_id:
                    t = self.task_store.get(task_id)
                    if t:
                        tasks_data.append(t.to_dict())
                else:
                    active = self.task_store.list_tasks(status=None, limit=5)
                    for t in active:
                        tasks_data.append(t.to_dict())
            except Exception:
                pass

        if self.verification_store is not None:
            try:
                tids = [task_id] if task_id else [str(t.get("task_id")) for t in tasks_data if t.get("task_id")]
                for tid in tids[:5]:
                    comp = self.verification_store.completion(tid)
                    for r in comp.receipts:
                        if r.passed:
                            receipts_data.append(r.to_dict())
            except Exception:
                pass

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

    def code_find_implementations(self, root: str, symbol: str, path: str | None = None) -> dict[str, Any]:
        if self.code_index is None:
            return {"success": False, "error": "code index disabled"}
        return self._repo_cached("ci:find_implementations", root, {"symbol": symbol, "path": path}, lambda: self.code_index.find_implementations(root, symbol, path=path))

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
                diff = self.repo_tools.git_diff(root, base, staged, max_tokens=3500)
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
                "available": True, "mode": "full",
                "hint": "Request context mode=full only when deterministic-fast context is insufficient.",
            }
        return packed

    def _hybrid_context(self, root: str, query: str, tenant: str, workspace: str | None, max_tokens: int) -> dict[str, Any]:
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
        # Local AI enforced deterministic-first fast path. This lives below the MCP/skill
        # layer so even a client that directly asks for context/delegation avoids
        # embeddings/reranking when parser/index evidence is already sufficient.
        if self.deterministic is not None:
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
        rag_revision = self.rag.revision(tenant, workspace or self.rag.workspace_id(root)) if self.rag is not None else None
        result = self._repo_cached(
            "hybrid-context", root,
            {"query": query, "workspace": workspace, "max_tokens": max_tokens, "rag_revision": rag_revision},
            lambda: self._hybrid_context_uncached(root, query, tenant, workspace, max_tokens),
        )
        if isinstance(result, dict): result.setdefault("context_source", "hybrid")
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

    def _hybrid_context_uncached(self, root: str, query: str, tenant: str, workspace: str | None, max_tokens: int) -> dict[str, Any]:
        if self.learner is not None:
            try: self.learner.record(root, query)
            except Exception: pass
        target_workspace = workspace
        if self.rag is not None and self.config.get("features", {}).get("rag", True) and not target_workspace:
            candidate = self.rag.workspace_id(root)
            known = {item["workspace"] for item in self.rag.list_workspaces(tenant)}
            if candidate in known:
                target_workspace = candidate

        search_cfg = self.config.get("search", {})
        semantic_fraction = max(0.0, min(float(search_cfg.get("semantic_fraction", 0.35)), 0.7))
        lexical_tokens = max_tokens if not target_workspace else max(512, int(max_tokens * (1.0 - semantic_fraction)))
        # Local AI: preprocessed deterministic/semantic cards narrow the lexical scan to likely files.
        # This is an optimization hint only; if cards are absent or select nothing,
        # the full lexical search remains the correctness fallback.
        candidate_paths: list[str] = []
        # Prioritize files explicitly named in the query/task (e.g. AGENTS.md, src/main.py)
        root_path = Path(root)
        for token in query.split():
            clean_tok = token.strip("`'\"(),:;[]{}*")
            if clean_tok and ("." in clean_tok or "/" in clean_tok or "\\" in clean_tok):
                try:
                    rel_p = clean_tok.replace("\\", "/").lstrip("./")
                    if (root_path / rel_p).exists() and rel_p not in candidate_paths:
                        candidate_paths.append(rel_p)
                except Exception:
                    pass
        if self.deterministic is not None:
            try: candidate_paths.extend(self.deterministic.related_paths(root, query, limit=28))
            except Exception: pass
        if self.code_index is not None:
            try:
                for p in self.code_index.related_paths(root, query, limit=24):
                    if p not in candidate_paths: candidate_paths.append(p)
            except Exception: pass
        if self.preprocessor is not None:
            try:
                for p in self.preprocessor.candidate_paths(
                    root, query, limit=max(12, int(self.config.get("preprocessing", {}).get("lookup_file_cards", 5)) * 4)
                ):
                    if p not in candidate_paths: candidate_paths.append(p)
            except Exception:
                # Keep already-resolved deterministic/code-index candidates. One
                # optional preprocessing failure must not force a full repository scan.
                pass
        if candidate_paths:
            lexical = self.repo_tools.context_pack_paths(
                root, query, candidate_paths, max_tokens=lexical_tokens,
                top_k=int(search_cfg.get("context_top_k", 14)),
            )
            # If the targeted cards produce no exact evidence, fall back to the
            # complete lexical scan. Cards accelerate; they never become a completeness gate.
            if lexical.get("success") and not lexical.get("evidence"):
                lexical = self.repo_tools.context_pack(
                    root, query, max_tokens=lexical_tokens,
                    top_k=int(search_cfg.get("context_top_k", 14)),
                )
        else:
            lexical = self.repo_tools.context_pack(
                root, query, max_tokens=lexical_tokens,
                top_k=int(search_cfg.get("context_top_k", 14)),
            )
        if not lexical.get("success"):
            return lexical
        evidence = list(lexical.get("evidence", []))
        if self.evidence_store is not None:
            try: evidence = self.evidence_store.put_many(str(lexical.get("root", root)), evidence)
            except Exception: pass
        context = str(lexical.get("context", ""))
        semantic_used = False
        per_path: dict[str, int] = {}
        for item in evidence:
            path = str(item.get("path", ""))
            per_path[path] = per_path.get(path, 0) + 1
        max_per_file = max(1, int(search_cfg.get("max_snippets_per_file", 3)))

        if self.rag is not None and target_workspace:
            from .token_router import strip_boilerplate
            rr = self.rag.search(query, tenant, target_workspace, top_k=10, use_reranker=True)
            if rr.get("success") and rr.get("results"):
                # RRF candidate ordering
                lex_paths = [str(e.get("path")) for e in evidence if e.get("path")]
                vec_paths = [str(r.get("path")) for r in rr["results"] if r.get("path")]
                fused_order = [p for p, _ in self._rrf_fuse(lex_paths, vec_paths)]
                fused_rank = {p: i for i, p in enumerate(fused_order)}
                sorted_results = sorted(rr["results"], key=lambda item: fused_rank.get(str(item.get("path", "")), 999))
                remaining = max(0, chars_for_tokens(max_tokens) - len(context))
                seen_chunks: set[tuple[str, int]] = set()
                for item in sorted_results:
                    path = str(item.get("path", ""))
                    chunk_no = int(item.get("chunk_no", 0))
                    key = (path, chunk_no)
                    if key in seen_chunks or per_path.get(path, 0) >= max_per_file:
                        continue
                    seen_chunks.add(key)
                    clean_text = strip_boilerplate(str(item.get("text", "")))
                    rendered = f"\n--- semantic {path} chunk={chunk_no} ---\n{clean_text}\n"
                    if len(rendered) > remaining:
                        if remaining > 400:
                            rendered = rendered[:remaining] + "\n[semantic snippet truncated]\n"
                        else:
                            break
                    context += rendered
                    remaining -= len(rendered)
                    per_path[path] = per_path.get(path, 0) + 1
                    semantic_used = True
                    evidence.append({
                        "path": path, "chunk_no": chunk_no, "semantic": True,
                        "content_hash": item.get("content_hash"),
                    })
                    if remaining <= 0:
                        break
        return {
            "success": True, "root": lexical["root"], "query": query, "context": context,
            "evidence": evidence, "estimated_tokens": estimate_tokens(context),
            "scanned_files": lexical.get("scanned_files", 0), "semantic_used": semantic_used,
            "context_budget_tokens": max_tokens,
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
            "max_tokens": int(args.get("max_tokens", 1500)),
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
        query = str(args.get("query", args.get("task", "")))
        if args.get("path"):
            return self.token_router.route_file(str(args.get("root", ".")), str(args.get("path")), query, tenant)
        return self.token_router.route_text(str(args.get("text", args.get("context", ""))), query, tenant, path=args.get("label"))

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
            det_hint = "\nDETERMINISTIC DIFF METADATA (facts only, verify semantics in the diff):\n" + json.dumps(det_diff, ensure_ascii=False, separators=(",", ":"))[:1800] + "\n"
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
                vram_free_mb = self.vram_balancer.status().get("vram_available_mb")
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
        if len(review_chunks) > _MAX_REVIEW_DIFF_CHUNKS:
            return {
                "success": False,
                "error": (
                    f"Review requires {len(review_chunks)} segments; the safe limit is "
                    f"{_MAX_REVIEW_DIFF_CHUNKS}. Narrow the diff or lower diff_tokens."
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
                "task": task,
                "context": review_code,
                "complexity": complexity,
                "max_tokens": per_chunk_output_tokens,
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
        general_model = str(self.config.get("models", {}).get("general", self.config.get("models", {}).get("fast_code", "qwen2.5-coder:1.5b")))
        for index, chunk in enumerate(chunks):
            prompt = f"INSTRUCTION:\n{instruction}\n\nCHUNK {index + 1}/{len(chunks)}:\n{chunk}"
            result = self._generate(
                general_model, prompt,
                "Compress aggressively. Preserve only information needed to reconstruct decisions/facts. Use a flat list without nested bullets when useful.",
                per_chunk_out, 0.1, tenant, "compress:map", 4,
                internal=True,
            )
            if not result.get("success"):
                return result
            summaries.append(str(result.get("text", "")))

        combined = "\n\n".join(summaries)
        if len(chunks) > 1 or estimate_tokens(combined) > target_tokens:
            final = self._generate(
                general_model,
                f"TARGET: <= {target_tokens} estimated tokens.\nINSTRUCTION: {instruction}\n\nPARTIAL SUMMARIES:\n{combined}",
                "Merge the partial summaries without duplication. Preserve concrete evidence and uncertainty. Be dense.",
                target_tokens, 0.1, tenant, "compress:reduce", 4,
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
        model = str(self.config.get("models", {}).get("fast_code", "qwen2.5-coder:1.5b"))

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
                return {"success": False, "error": res["error"]}
            completion = str(res.get("response", "")) if isinstance(res, dict) else ""
            return {"success": True, "model": model, "completion": completion}
        raw, hit, coalesced = self.generation_cache.get_or_compute(cache_key, compute)
        result = copy.deepcopy(raw)
        result["cache_hit"] = hit or coalesced
        return result

    DOMAIN_SYNONYMS = {
        "jump": ["PlayerController", "Jump", "AddForce", "isGrounded", "velocity.y"],
        "shoot": ["PlayerCombat", "Shoot", "FireWeapon", "InstantiateProjectile", "Raycast"],
        "save": ["SaveManager", "SaveData", "PlayerPrefs", "JsonUtility", "File.WriteAllText"],
        "load": ["LoadManager", "LoadData", "PlayerPrefs", "JsonUtility", "File.ReadAllText"],
        "health": ["Health", "TakeDamage", "Die", "currentHealth", "maxHealth"],
        "damage": ["TakeDamage", "ApplyDamage", "DamageSource", "HitPoint"],
        "inventory": ["Inventory", "Item", "Slot", "AddItem", "RemoveItem", "ItemStack"],
        "audio": ["AudioSource", "AudioClip", "PlaySound", "SoundManager", "AudioManager"],
        "sound": ["AudioSource", "AudioClip", "PlayOneShot", "SoundManager"],
        "ui": ["Canvas", "Button", "Text", "TMP_Text", "OnClick", "UIController"],
        "movement": ["Move", "MovePosition", "CharacterController", "Rigidbody", "velocity"],
        "input": ["Input", "InputAction", "InputSystem", "KeyCode", "GetKeyDown"],
        "animation": ["Animator", "SetTrigger", "SetBool", "SetFloat", "Animation"],
        "camera": ["Camera", "Cinemachine", "FollowTarget", "LookAt", "Transform"],
        "network": ["NetworkManager", "Rpc", "Cmd", "SyncVar", "ClientRpc", "ServerRpc"],
        "database": ["SQLite", "Database", "ExecuteQuery", "Connection", "Transaction"],
        "auth": ["Auth", "Login", "Token", "User", "Session", "Authenticate"],
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
            if framework == "pytest":
                scaffold = f"import pytest\n\n\ndef test_{clean_sym}_basic():\n    # TODO: verify expected behavior for {symbol}\n    assert True\n"
            elif framework == "nunit":
                scaffold = f"using NUnit.Framework;\n\n[TestFixture]\npublic class {clean_sym}Tests {{\n    [Test]\n    public void Test_{clean_sym}_Basic() {{\n        Assert.Pass();\n    }}\n}}\n"
            elif framework == "jest":
                scaffold = f"describe('{symbol}', () => {{\n    test('basic functionality', () => {{\n        expect(true).toBe(true);\n    }});\n}});\n"
            else:
                scaffold = f"def test_{clean_sym}():\n    assert True\n"
            return {
                "success": True,
                "framework": framework,
                "target_symbol": symbol,
                "scaffold": scaffold,
                "test_code": scaffold,
                "method": "fast-scaffold",
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

        fast_model = str(self.config.get("models", {}).get("fast_code", "qwen2.5-coder:1.5b"))
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
        if self.preprocessor is None:
            return {"success": False, "error": "project preprocessor unavailable"}
        action = str(args.get("action", "status")).strip().lower().replace("-", "_")
        root = str(args.get("root", "."))
        if action in {"start", "register", "preprocess"}:
            return self.preprocessor.register(root, source="agent")
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
        return {"success": False, "error": f"unknown preprocess action: {action}"}

    def command(self, args: dict[str, Any], tenant: str) -> dict[str, Any]:
        if self.commands is None:
            return {"success": False, "error": "command broker unavailable"}
        action = str(args.get("action", "run")).strip().lower().replace("-", "_")

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
            return self.commands.run(
                str(args.get("command", "")), str(args.get("cwd", args.get("root", "."))), tenant,
                timeout=int(args.get("timeout", 0) or 0) or None, force=bool(args.get("force", False)),
                task_id=str(args.get("task_id", "")), criterion=str(args.get("criterion", "")),
                auto_fix=bool(args.get("auto_fix", False)),
                fix_generator=self._synthesize_repair_patch if bool(args.get("auto_fix", False)) else None,
                log_callback=log_callback,
                snapshot=bool(args.get("snapshot", False)),
                rollback_on_failure=bool(args.get("rollback_on_failure", False)),
            )
        if action == "run_affected":
            root = str(args.get("cwd", args.get("root", ".")))
            aff = self.affected_tests(root, changed_paths=args.get("paths"))
            cmd = aff.get("suggested_command", "")
            if not cmd:
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
            return self.spawn_daemon(str(args.get("command", "")), str(args.get("cwd", args.get("root", "."))), name=str(args.get("name", args.get("task_id", ""))), env=args.get("env"))
        if action == "daemon_status":
            return self.daemon_status(args.get("daemon_id", args.get("task_id", args.get("command"))))
        if action == "stop_daemon":
            return self.stop_daemon(str(args.get("daemon_id", args.get("task_id", args.get("command", "")))))
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
        """Synthesize candidate code fix diffs/patches using local fast model or remediation."""
        if not failure_result or failure_result.get("success"):
            return None
        rem = failure_result.get("remediation") or {}
        if rem.get("verified_fix") and isinstance(rem["verified_fix"], dict):
            return {str(k): str(v) for k, v in rem["verified_fix"].items()}
        model = self.config.get("models", {}).get("fast_code", "qwen2.5-coder:1.5b")
        diag = failure_result.get("diagnostics", [])
        stderr = str(failure_result.get("stderr", "") or failure_result.get("error", ""))[:2000]
        prompt = (
            f"Fix this command failure in {cwd}:\nCommand: {command}\nError:\n{stderr}\n"
            f"Diagnostics:\n{json.dumps(diag[:5])}\n"
            "Respond ONLY with a JSON object format: {\"relative_file_path\": \"full corrected file content\"}"
        )
        try:
            res = self.proxy_request("/api/generate", {"model": model, "prompt": prompt, "format": "json"}, "hub", "repair_loop")
            raw_text = str(res.get("response", "")).strip()
            parsed = json.loads(raw_text)
            if isinstance(parsed, dict) and "files" in parsed and isinstance(parsed["files"], dict):
                return {str(k): str(v) for k, v in parsed["files"].items()}
            if isinstance(parsed, dict):
                return {str(k): str(v) for k, v in parsed.items() if isinstance(v, str)}
        except Exception:
            pass
        return None

    def proxy_request(self, endpoint: str, payload: dict[str, Any], tenant: str, source: str) -> dict[str, Any]:
        if payload.get("stream") is True:
            return {"success": False, "error": "streaming is intentionally disabled through the affinity queue"}
        model = str(payload.get("model") or self.config.get("models", {}).get("general", "qwen2.5-coder:1.5b"))
        clean = dict(payload)
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

            input_tokens = estimate_tokens(json.dumps(promptish, ensure_ascii=False, default=str) if not isinstance(promptish, str) else promptish)
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
                    while other_msgs and estimate_tokens(json.dumps(system_msgs + other_msgs)) > budget:
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
            return self.scheduler.submit(
                model, tenant, source, lambda: self.runtime.request(endpoint, clean),
                priority=int(payload.get("priority", 5)),
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
            return {"success": False, "error": "tasks must be a non-empty array"}
        tasks = tasks[:16]
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
        for i, _model, item in prepared:
            results[i] = self.delegate(item, tenant)
        return {"success": all(r.get("success", False) for r in results.values()), "results": [results[i] for i in range(len(results))]}

    def optimize_databases(self) -> dict[str, Any]:
        """Perform WAL checkpointing, page pruning and VACUUM/optimize across all SQLite stores."""
        import sqlite3
        state_dir = Path(self.config["server"]["state_dir"])
        db_files = list(state_dir.glob("*.sqlite3"))
        optimized = []
        bytes_freed = 0
        for db in db_files:
            try:
                before_size = db.stat().st_size
                with closing(sqlite3.connect(str(db), timeout=10.0)) as con:
                    con.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                    con.execute("PRAGMA optimize;")
                after_size = db.stat().st_size
                freed = max(0, before_size - after_size)
                bytes_freed += freed
                optimized.append({"db": db.name, "before_kb": before_size // 1024, "after_kb": after_size // 1024, "freed_kb": freed // 1024})
            except Exception as exc:
                optimized.append({"db": db.name, "error": str(exc)})
        return {
            "success": True,
            "databases_optimized": len(optimized),
            "total_freed_kb": bytes_freed // 1024,
            "details": optimized,
        }

    def purge_stale_cache(self, days: int = 7) -> dict[str, Any]:
        """Purge cache entries older than N days to free disk space."""
        import sqlite3
        state_dir = Path(self.config["server"]["state_dir"])
        cutoff = time.time() - (days * 86400)
        cache_db = state_dir / "cache.sqlite3"
        deleted_entries = 0
        if cache_db.is_file():
            try:
                with closing(sqlite3.connect(str(cache_db), timeout=10.0)) as con:
                    cur = con.execute("DELETE FROM cache_entries WHERE accessed_at < ?", (cutoff,))
                    deleted_entries = cur.rowcount
                    con.commit()
                    con.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except Exception as exc:
                return {"success": False, "error": str(exc)}
        return {"success": True, "purged_entries": deleted_entries, "days_threshold": days}

    def run_doctor(self) -> dict[str, Any]:
        """Run comprehensive system, GPU, model, and database diagnostics."""
        from .gpu_monitor import get_gpu_telemetry
        checks = []
        
        ollama_ok = self.runtime.is_online()
        checks.append({"component": "Ollama Service", "status": "OK" if ollama_ok else "FAIL", "detail": f"Installed models: {len(self.runtime.installed_models())}"})
        
        gpu = get_gpu_telemetry()
        checks.append({
            "component": "NVIDIA GPU",
            "status": "OK" if gpu.get("available") else "WARN",
            "detail": f"{gpu.get('gpu_name', 'N/A')} · {gpu.get('vram_used_mb', 0):.0f} / {gpu.get('vram_total_mb', 0):.0f} MB VRAM ({gpu.get('temperature_c', 0)}°C)"
        })
        
        state_dir = Path(self.config["server"]["state_dir"])
        dbs = list(state_dir.glob("*.sqlite3"))
        checks.append({"component": "SQLite Databases", "status": "OK", "detail": f"{len(dbs)} active databases in {state_dir.name}"})
        
        prep_status = self.preprocessor.status() if self.preprocessor else {}
        checks.append({"component": "Preprocessor", "status": "OK" if prep_status.get("enabled") else "OFF", "detail": f"{len(prep_status.get('projects', []))} projects tracked"})
        
        return {"success": True, "timestamp": time.time(), "checks": checks}

    def eval_suite(self, payload: dict[str, Any], tenant: str = "default") -> dict[str, Any]:
        """Run bounded local agent benchmark evaluation test cases."""
        suite_name = str(payload.get("suite_name", "default"))
        cases = payload.get("cases") or [
            {"id": "c1", "input": "def add(a, b):", "expected": "return a + b"},
            {"id": "c2", "input": "def is_even(n):", "expected": "return n % 2 == 0"},
        ]
        results = []
        passed = 0
        for case in cases:
            c_id = str(case.get("id", "case"))
            c_in = str(case.get("input", ""))
            c_exp = str(case.get("expected", ""))
            try:
                model = str(payload.get("model") or getattr(self, "config", {}).get("models", {}).get("fast_code", "qwen2.5-coder:1.5b"))
                response = self.runtime.request("/api/generate", {
                    "model": model, "prompt": c_in, "stream": False,
                    "options": {"num_predict": 128, "temperature": 0.0},
                })
                is_pass = bool(c_exp and not response.get("error") and c_exp in str(response.get("response", "")))
                result = {"case_id": c_id, "passed": is_pass}
                if response.get("error"):
                    result["error"] = str(response["error"])
            except Exception as exc:
                is_pass = False
                result = {"case_id": c_id, "passed": False, "error": str(exc)}
            results.append(result)
            if is_pass:
                passed += 1

        return {
            "success": True,
            "suite": suite_name,
            "summary": {
                "total": len(cases),
                "passed": passed,
                "failed": len(cases) - passed,
                "pass_rate": round(passed / max(1, len(cases)), 2),
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
            atomic_write_file(history_file, json.dumps(history, indent=2))
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
