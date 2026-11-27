"""generator.py — Dynamic skill, instruction, and MCP artifact generator.

Inspects the active configuration via FeatureSet and generates:
1. Dynamic SKILL.md and reference docs containing only active tools, actions, and models.
2. Dynamic agent instruction policies (for AGENTS.md, CLAUDE.md, GEMINI.md).
3. Dynamic MCP manifests (mcp-servers.json, vscode-mcp.json) and tool JSON schemas.
"""
from __future__ import annotations

from .json_utils import dumps as json_dumps

import logging
import os
from pathlib import Path
from typing import Any


SINGLE_OWNER_CONTRACT = (
    "Single-owner and repository scope contract: one Local AI Hub installation on one PC serves one human. "
    "Loopback-only Hub access without auth token or tenant partitions. "
    "Repository root scopes all operations. Durable Agent OS tasks, memory and verification receipts."
)


T21_HANDOFF_CONTRACT = """Project configuration and PathHint core: `resolve_project_context(root, state_dir)` provides effective settings. Candidate ranking: `entry_points`, request hints, then saved hints. Verification rules map task criteria to required command receipts before completion."""

T19_RUNTIME_PARITY_CONTRACT = """Installed schema is authoritative. Hub modes: `active`, `gaming`, `maintenance`. For durable work, create and checkpoint an Agent OS task before edits. If live schema lacks an action, use authorized native tool directly. Native fallback after Hub action requires `terminal=true` and `retryable=false`."""

AUTOSETUP_POLICY_BEGIN = "<!-- BEGIN TOKEN ECONOMIZER AUTOSETUP -->"
AUTOSETUP_POLICY_END = "<!-- END TOKEN ECONOMIZER AUTOSETUP -->"
GLOBAL_POLICY_BEGIN = "<!-- BEGIN LOCAL AI HUB TOOL POLICY -->"
GLOBAL_POLICY_END = "<!-- END LOCAL AI HUB TOOL POLICY -->"
TOKEN_ECONOMY_POLICY_BEGIN = "<!-- BEGIN TOKEN ECONOMY POLICY -->"
TOKEN_ECONOMY_POLICY_END = "<!-- END TOKEN ECONOMY POLICY -->"
ANTIGRAVITY_POLICY_BEGIN = "<!-- BEGIN LOCAL AI HUB ANTIGRAVITY SKILLS -->"
ANTIGRAVITY_POLICY_END = "<!-- END LOCAL AI HUB ANTIGRAVITY SKILLS -->"

from local_ai_hub.features import FeatureSet
from local_ai_hub.operation_contracts import (
    operation_contract,
    operation_enabled,
    operation_metadata,
    operation_parameters_schema,
)
from local_ai_hub.prompt_contracts import capability_for


def _reasoning_tier_label(cfg: dict[str, Any], fs: FeatureSet) -> str:
    models = cfg.get("models", {})
    if isinstance(models, dict) and "reasoning" in models:
        return f"`{fs.reasoning_model}`"
    return "the configured hardest-reasoning tier"


def _model_capability_guidance(cfg: dict[str, Any]) -> str:
    models = cfg.get("models", {})
    if not isinstance(models, dict):
        return ""
    seen: set[str] = set()
    parts: list[str] = []
    for role in ("background_code", "fast_code", "heavy_code", "reasoning", "general", "opencode", "vision"):
        model = str(models.get(role, "") or "")
        if not model or model in seen:
            continue
        seen.add(model)
        capability = capability_for(model, role="vision" if role == "vision" else "")
        parts.append(f"`{model}`: {', '.join(capability.can[:4])}; not {', '.join(capability.cannot[:3])}")
    if not parts:
        return ""
    return " Model capability contract: " + " | ".join(parts) + "."


_SEMANTIC_TASK_ACTION_ORDER = (
    "delegate", "explore", "reason", "review", "second_opinion", "compress"
)
_SEMANTIC_TASK_ACTION_GUIDANCE = {
    "delegate": 'Use `local_ai_task(action="delegate")` for bounded implementation or test suggestions.',
    "explore": 'Use `local_ai_task(action="explore")` for bounded semantic exploration.',
    "reason": 'Use `local_ai_task(action="reason")` for bounded reasoning after gathering evidence.',
    "review": 'Use `local_ai_task(action="review")` for an evidence-grounded semantic review.',
    "second_opinion": 'Use `local_ai_task(action="second_opinion")` for independent critique.',
    "compress": 'Use `local_ai_task(action="compress")` for semantic condensation.',
}


def _available_semantic_task_actions(fs: FeatureSet) -> tuple[str, ...]:
    available = set(fs.supported_task_actions())
    return tuple(action for action in _SEMANTIC_TASK_ACTION_ORDER if action in available)


def _semantic_handoff_contract(fs: FeatureSet) -> str:
    semantic_actions = set(_available_semantic_task_actions(fs))
    selector = "|".join(
        f'"{action}"' for action in _SEMANTIC_TASK_ACTION_ORDER
        if action in semantic_actions
    )
    actionable_guidance = (
        " " + " ".join(_SEMANTIC_TASK_ACTION_GUIDANCE[action] for action in _SEMANTIC_TASK_ACTION_ORDER if action in semantic_actions)
        if semantic_actions
        else " No semantic task action is advertised at this profile; do not guess or call hidden actions."
    )
    return (
        "Semantic delegation is on-demand under the active schema and quality gates. "
        + (f"This profile advertises `local_ai_task(action={selector})`; " if selector else "No semantic task action is advertised at this profile; ")
        + "use matching exposed actions by default after deterministic/indexed evidence; cloud planning is never blocked by mandatory local handoffs. "
        "Deterministic/indexed evidence is authoritative; the primary agent accepts."
        + actionable_guidance
        + " Actions unavailable under this profile are omitted."
    )


def _trigger_map_lines(fs: FeatureSet) -> list[str]:
    lines = fs.trigger_map_lines()
    if not fs.status:
        lines = [line for line in lines if "local_ai_status" not in line]
    return lines


def _actions_note(actions: list[str]) -> str:
    """Keep generated tool descriptions aligned with each active action enum."""
    return f" Supported actions: {', '.join(actions)}." if actions else " No actions are enabled."


def _repo_review_guidance(actions: list[str]) -> str:
    """Mention only review actions enabled in the generated repository schema."""
    enabled = [action for action in ("review_diff", "security_audit") if action in actions]
    if not enabled:
        return ""
    choices = " or ".join(f"`{action}`" for action in enabled)
    return f" Before model inference, use {choices} when relevant."


def _supported_repo_action_names(actions: list[str], candidates: tuple[str, ...]) -> str:
    """Return enabled repository action names in stable display order."""
    return ", ".join(action for action in candidates if action in actions)


def _repo_analysis_guidance(actions: list[str]) -> str:
    """Return only enabled context and solve action names for generated guidance."""
    return "/".join(action for action in ("context", "solve") if action in actions)


def _repo_context_note(actions: list[str]) -> str:
    """Describe adaptive context retrieval only when the action is enabled."""
    if "context" in actions:
        return " For substantial work without fresh evidence, use adaptive `context` once with a stable root."
    return " For substantial work without fresh evidence, use available deterministic/indexed retrieval."


def _active_tool_action_lines(fs: FeatureSet) -> list[str]:
    """Render the exact profile-enabled MCP tool/action surface from its schema registry."""
    from .operation_contracts import OPERATION_CONTRACTS, operation_actions, operation_enabled

    lines: list[str] = []
    for tool_name in OPERATION_CONTRACTS:
        if not operation_enabled(fs, tool_name):
            continue
        actions = list(operation_actions(tool_name, fs))
        action_text = ", ".join(f"`{action}`" for action in actions) if actions else "no action selector"
        lines.append(f"- `{tool_name}`: {action_text}")
    return lines


def _categorized_operational_triggers(fs: FeatureSet) -> list[str]:
    """Generate structured operational triggers categorized by developer intent."""
    repo_actions = set(fs.supported_repo_actions()) if fs.repo else set()
    coord_actions = set(fs.supported_coord_actions()) if fs.coord else set()
    task_actions = set(fs.supported_task_actions()) if fs.tasks else set()
    lines: list[str] = [
        "## Categorized Operational Triggers (Prioritize over shell / raw reads)",
        "",
    ]

    # 1. Code Navigation & Structural Search
    nav_items: list[str] = []
    if "callers" in repo_actions:
        nav_items.append('- **Callers & Inbound References**: Trace callers across codebase -> `local_ai_repo(action="callers", query="<name>", root=ABS_ROOT)`')
    if "callees" in repo_actions:
        nav_items.append('- **Callees & Outbound Calls**: Trace function dependencies -> `local_ai_repo(action="callees", query="<name>", root=ABS_ROOT)`')
    if "ast_outline" in repo_actions:
        nav_items.append('- **AST Outline**: Class/function signature summary without dumping source -> `local_ai_repo(action="ast_outline", path="<relpath>", root=ABS_ROOT)`')
    if "declaration" in repo_actions or "implementations" in repo_actions:
        nav_items.append('- **Declarations & Implementations**: Find declarations/subclasses -> `local_ai_repo(action="declaration"|"implementations", query="<name>", root=ABS_ROOT)`')
    if "structural_search" in repo_actions:
        nav_items.append('- **Structural AST Search**: Query code patterns by syntax -> `local_ai_repo(action="structural_search", query="<pattern>", root=ABS_ROOT)`')
    if "code_index" in repo_actions or "search" in repo_actions:
        nav_items.append('- **Fast Symbols & Text**: Bounded symbols/lexical search -> `local_ai_repo(action="code_index"|"search", query="<term>", root=ABS_ROOT)`')

    if nav_items:
        lines.extend(["### 1. Code Navigation & AST Discovery (`local_ai_repo`)", *nav_items, ""])

    # 2. Impact Analysis & Testing
    impact_items: list[str] = []
    if "affected_tests" in repo_actions:
        impact_items.append('- **Affected Tests**: Pinpoint tests impacted by a changed file -> `local_ai_repo(action="affected_tests", path="path/to/file.py", root=ABS_ROOT)`')
    if "refactor_impact" in repo_actions or "impact" in repo_actions:
        impact_items.append('- **Refactoring Blast Radius**: Evaluate symbol usage before edits -> `local_ai_repo(action="refactor_impact", query="<name>", root=ABS_ROOT)`')
    if "generate_tests_for_diff" in repo_actions or "generate_tests" in repo_actions:
        impact_items.append('- **Test Generation**: Scaffold test cases for diff or file -> `local_ai_repo(action="generate_tests_for_diff", root=ABS_ROOT)`')

    if impact_items:
        lines.extend(["### 2. Impact Analysis & Test Scaffolding (`local_ai_repo`)", *impact_items, ""])

    # 3. Code Health, Auditing & Security
    audit_items: list[str] = []
    if "security_audit" in repo_actions or "secret_scan" in repo_actions:
        audit_items.append('- **Security & Secret Scan**: Audit code for CVEs, credentials, and risks -> `local_ai_repo(action="security_audit", root=ABS_ROOT)`')
    if "dead_code" in repo_actions or "reachability_dead_code" in repo_actions:
        audit_items.append('- **Dead Code Detection**: Find unused functions and unreachable code -> `local_ai_repo(action="dead_code", root=ABS_ROOT)`')
    if "circular_dependencies" in repo_actions:
        audit_items.append('- **Circular Dependencies**: Detect module import loops -> `local_ai_repo(action="circular_dependencies", root=ABS_ROOT)`')
    if "complexity" in repo_actions or "hotspots" in repo_actions:
        audit_items.append('- **Complexity & Churn Hotspots**: Rank high-complexity and hotspot files -> `local_ai_repo(action="complexity", root=ABS_ROOT)`')

    if audit_items:
        lines.extend(["### 3. Code Health, Auditing & Security (`local_ai_repo`)", *audit_items, ""])

    # 4. Git Inspection & Commits
    git_items: list[str] = []
    if "git_status" in repo_actions or "git_diff" in repo_actions:
        git_items.append('- **Git Status & Diffs**: Inspect working tree state without shell git -> `local_ai_repo(action="git_status"|"git_diff", root=ABS_ROOT)`')
    if "synthesize_commit" in repo_actions:
        git_items.append('- **Synthesize Commit**: Draft standardized commit message from verified diff -> `local_ai_repo(action="synthesize_commit", root=ABS_ROOT)`')

    if git_items:
        lines.extend(["### 4. Git Inspection & Commits (`local_ai_repo`)", *git_items, ""])

    # 5. Planning & Agent OS Coordination
    coord_items: list[str] = []
    if "plan_board_view" in coord_actions or "plan_list" in coord_actions:
        coord_items.append('- **Mandatory First Entrypoint**: Inspect active plan, status and `spec_refs` -> `local_ai_coord(action="plan_board_view"|"plan_list", root=ABS_ROOT)`')
    if "task_checkpoint" in coord_actions:
        coord_items.append('- **Milestone Progress**: Record checkpoint with affected paths -> `local_ai_coord(action="task_checkpoint", task_id="...", checkpoint={...})`')
    if "memory_find" in coord_actions or "memory_record" in coord_actions:
        coord_items.append('- **Project Memory**: Query or store verified project learnings -> `local_ai_coord(action="memory_find"|"memory_record", root=ABS_ROOT, ...)`')
    if "negative_knowledge_find" in coord_actions:
        coord_items.append('- **Negative Knowledge**: Check known failure modes before repeating mistakes -> `local_ai_coord(action="negative_knowledge_find", query=...)`')

    if coord_items:
        lines.extend(["### 5. Planning & Agent OS Coordination (`local_ai_coord`)", *coord_items, ""])

    # 6. Semantic Review & Local AI Tasks
    task_items: list[str] = []
    if "review" in task_actions:
        task_items.append('- **Adversarial Code Review**: Skeptical review of changes before commit -> `local_ai_task(action="review", ...)`')
    if "reason" in task_actions or "second_opinion" in task_actions:
        task_items.append('- **Local Reasoning / 2nd Opinion**: Bounded local reasoning or alternative perspective -> `local_ai_task(action="reason"|"second_opinion", ...)`')
    if "compress" in task_actions:
        task_items.append('- **Evidence Compression**: Compress voluminous logs/evidence -> `local_ai_task(action="compress", ...)`')

    if task_items:
        lines.extend(["### 6. Semantic Tasks & Review (`local_ai_task`)", *task_items, ""])

    # 7. Exact Slices
    if fs.artifacts:
        lines.extend([
            "### 7. Exact Slices & Artifacts (`local_ai_artifact`)",
            '- **Bounded File Slice**: Read line ranges without full-file dumping -> `local_ai_artifact(action="slice", path="<relpath>", start_line=N, end_line=M, root=ABS_ROOT)`',
            '- **Exact Source**: Use `action="source"` with explicit absolute `root=ABS_ROOT` and `path="<relpath>"`; source roots are never inferred.',
            "",
        ])

    return lines


def context_pack_guidance() -> str:
    """Compact contract for the guarded repository-context operation."""
    return (
        " Reuse fresh sufficient repository evidence. For exact facts, use bounded indexed/source lookup directly; do not preprocess or compile adaptive context first. "
        'When non-trivial planning, editing, review or testing lacks sufficient fresh evidence, call `local_ai_repo(action="context", mode="adaptive")` once before native broad discovery. '
        "On first stable-root work, inspect repository config and derive only evidenced exclusions, uncommon extensions, pinned documentation, and entry points; preserve defaults, then preprocess once to register. "
        "Preprocess only when the root is unindexed or its evidence is stale; never wait, poll or force-refresh preprocessing. Its adaptive orchestrator fuses deterministic and "
        "indexed evidence with Serena, the built-in code index, bounded lexical search and RAG when available; "
        "It deduplicates and preserves file diversity. "
        "Send task/context, not grep terms. Reuse candidates first, then carry forward evidence IDs and artifact slices; cite every factual claim. Deterministic/indexed evidence is authoritative; models only rank, select or compress structured evidence. "
        "Guarded scope or drift overrides require an explicit `override_reason` and approval when requested. "
        "Omit raw model/debug fields unless explicitly requested through `extra_fields`; responses remain compact; "
        "aggregate response budget defaults to approximately 3200 tokens. The canonical adaptive context pack is the default."
    )


def context_economy_contract(cfg: dict[str, Any] | None = None) -> str:
    """Single short contract shared by skills, policies, and routing references."""
    features = FeatureSet.from_config(cfg or {})
    budget = 8192
    try:
        section = (cfg or {}).get("mcp", {}).get("response_budget", {})
        budget = int(section.get("default_tokens", budget)) if isinstance(section, dict) else budget
    except (TypeError, ValueError, AttributeError):
        pass
    batch_line = '- Use `local_ai_task(action="batch")` for bounded independent tasks.' if "batch" in features.supported_task_actions() else ''
    return f"""## Context economy contract

- Every Hub response is aggregate-bounded (default ≈{budget} tokens).
- `response_budget.returned_tokens` measures the final serialized response envelope in `estimated_tokens` and stays at or below the requested budget.
- Preserve protected status, error, evidence, and context-identity fields; keep exact detail artifact-backed.
- Claim savings only with a current `baseline_evidence_id`; report signed `token_savings_delta_est`, including negative values; keep `protocol_tokens_est`, `schema_tokens_est`, and `local_compute_reused_tokens_est` separate.
- Reject `max_response_tokens` below 128; never raise the request silently.
- Large task responses: omit `max_response_tokens` unless a cap is needed.
- For a response-budget rejection, reduce the requested envelope or fetch a smaller artifact page/slice; do not replay the same oversized request.
- For Hub outages, native fallback requires explicit `terminal=true` and `retryable=false`.
- If the live MCP schema has no action for an operation, skip Hub and use the authorized native tool directly; no Hub failure or `native_fallback_allowed` signal is needed.
- After calling an advertised Hub action, native fallback requires explicit `terminal=true` and `retryable=false`.
- On `outcome_unknown` or `in_progress`, do independent work; never poll or repeat the identical operation.
- Prefer `response_profile=\"minimal\"`/`\"compact\"`; request only decision-grade fields.
- Pass a stable `reuse_key` for repeated logical queries. Use `response_profile="delta"` when only changes are needed; unchanged calls report `unchanged=true`. Required task memory may remain inline.
{batch_line}
- The Hub keeps a bounded metadata-only context ledger; inspect it only with an explicit cache/status request, never by replaying the whole session.
- Broad native shell reads are guarded by the optional host hook; use bounded limits or Hub repository tools for discovery.
- Commands return status, summary, changed paths, and failures; full stdout/stderr is retrievable only when `output_artifact_id` is returned.
- Reuse fresh sufficient repository evidence; use bounded indexed/source lookup for exact facts. Do not preprocess or compile adaptive context first.
- Do not bypass the budget with native broad reads unless Hub has one bounded terminal failure."""


def generate_skill_markdown(cfg: dict[str, Any]) -> str:
    """Generate a dynamic SKILL.md reflecting only enabled tools and models."""
    fs = FeatureSet.from_config(cfg)
    reasoning_tier = _reasoning_tier_label(cfg, fs)

    trigger_map = _trigger_map_lines(fs)
    trigger_lines = "\n".join(trigger_map) if trigger_map else "- (all Hub tools currently disabled in configuration)"
    active_tool_actions = _active_tool_action_lines(fs)
    active_tool_surface = "\n".join(active_tool_actions) if active_tool_actions else "- (all Hub tools currently disabled in configuration)"
    task_action_contract = (
        "For `local_ai_task`, action inputs are strict: `benchmark` reads stored results only; `hardware_benchmark` accepts `model`, `prompt`, `max_tokens`, and `context_tokens` (4096–32768), with no `timeout_seconds`."
        if fs.supported_task_actions()
        else ""
    )
    recipe_lines = "\n".join(fs.recipe_lines())

    # Delegation section
    if fs.tasks and fs.has_any_model():
        delegation_task = (
            f"- {_semantic_handoff_contract(fs)}"
            " Follow the active hardware profile and user overrides; verify model availability and select autonomy by task risk and measured quality."
            " Deterministic/indexed tools remain for exact facts, symbols, diff and tests; they do not replace these semantic tasks."
        )
    else:
        delegation_task = (
            "- Local model inference is disabled; use deterministic/indexed evidence and native reasoning."
        )

    work_delegation = ""
    if fs.work_orchestrator and "submit" in fs.supported_work_actions():
        work_delegation = (
            '- `local_ai_work`: available only on a high/max profile after `features.bounded_local_work=true`, task/model quality evaluation and explicit scope/permission checks; use only for explicitly requested closed delegation. Use `mode="bounded"` for suitable small tasks with exact allowed files, approved commands, explicit permissions, time budget and acceptance criteria. On Windows, bounded patch parent directories must already exist. A patch targeting mixed LF and CRLF within a single file fails visibly. The primary agent reviews the diff, test results and integration. For an order owned by the responding process, timed_out=true with in_progress=true is not a terminal result or permission to retry; cancellation is cooperative and another process may not observe the deadline. Treat output_truncated=true as an incomplete failure, not a usable patch. For `local_ai_coord` claim or release, omit the budget or use max_response_tokens >= 512; a smaller explicit budget rejects before mutation.'
        )
    work_owner_note = "The main agent owns task scope, permissions, diff and test review, and final integration. Never infer tool execution or test success from model prose; verify actual tool results or traces. Missing provenance is unknown."
    # Ownership & tiering bullets
    tiering_bullets: list[str] = [
        "- **Local AI Hub first:** its own precise bounded microtasks, repository facts, indexed search,"
        + (" preprocess," if fs.preprocessing else "")
        + " impact, diff/security review"
        + (", safe commands" if fs.commands else "")
        + (", compression, local-model synthesis and second opinions." if (fs.tasks and fs.has_any_model()) else " and targeted checks."),
        "- **Native Codex subagents:** use only for genuinely independent bounded implementation or explicit user requests; never delegate audits or relay work.",
    ]
    if fs.tasks and fs.has_any_model():
        model_config = cfg.get("models", {}) if isinstance(cfg.get("models", {}), dict) else {}
        reasoning_tier = f"`{fs.reasoning_model}`" if "reasoning" in model_config else "the configured hardest-reasoning tier"
        tiering_bullets.append(
            f"- **Tiered local models:** `{fs.background_model}` for preprocessing, `{fs.fast_model}` for quick/simple requests, "
            f"`{fs.general_model}` for ordinary tasks, `{fs.smart_model}` for more involved work, and {reasoning_tier} for the hardest or highest-risk reasoning."
        )
        tiering_bullets.append(
            "- **Local model routing:** follow the active profile and user overrides, preserve the configured preprocessing provider, and verify installed model availability. Measured task quality and risk govern autonomy. Whisper transcription uses CPU by default; when GPU-only execution is required, set `[transcription].enabled=false` until a GPU-admitted route exists. "
            "Run deterministic/indexed Hub actions first for exact facts, symbols, diff and tests. Use `local_ai_task` for semantic generation, reasoning, review, independent second opinions and semantic compression."
        )
    if fs.rag:
        tiering_bullets.append(
            "- **RAG:** use only when deterministic/indexed evidence is insufficient for a bounded retrieval question. Do not invoke a model to restate facts already available from the hub."
        )
    tiering_section = "\n".join(tiering_bullets)

    ollama_enabled = cfg.get("ollama", {}).get("enabled", False) is True if isinstance(cfg.get("ollama", {}), dict) else False
    manage_ollama = bool(cfg.get("headless", {}).get("manage_ollama", False))
    if not ollama_enabled:
        ollama_ownership_section = (
            "## Ollama process ownership\n\n"
            "Ollama is disabled by policy (`ollama.enabled = false`). Setup and the supervisor must not install, start, pull, or probe Ollama. "
            "Use only an explicitly configured, already-running loopback llama.cpp endpoint when its route is healthy; there is no automatic fallback. `llama_cpp.mode = auto` does not require a particular GPU."
        )
    elif manage_ollama:
        ollama_ownership_section = (
            "## Ollama process ownership\n\n"
            "When `headless.manage_ollama = true`, Ollama is owned by the Local AI Hub supervisor. "
            "Never run `ollama serve` or add a separate Ollama startup task; use `python tools/service.py start|restart`. "
            "The Hub applies the configured profile only to an Ollama process it starts and owns. "
            "An already-running external Ollama is borrowed without takeover; its profile remains unverified. "
            "Set `headless.manage_ollama = false` only when intentionally using an external Ollama owner."
        )
    else:
        ollama_ownership_section = (
            "## Ollama process ownership\n\n"
            "`headless.manage_ollama = false` leaves an explicitly enabled Ollama user-managed. Keep its startup and environment outside the Hub. "
            "`server.auto_start_ollama = false` does not disable an explicitly enabled external backend; verify endpoint health and model availability before inference."
        )

    # Read-only audit contract
    audit_fallback = "- Run bounded validation with the host-native command tool; never repeat identical failing commands."

    # Keep exact lookups cheap and reuse current evidence. Preprocess only to
    # repair a missing or stale index; it is not a mandatory task ritual.
    repo_gate_lines: list[str] = [
        "Reuse fresh sufficient evidence when available. For exact file or symbol lookups, use bounded indexed/source lookup directly; do not preprocess or compile adaptive context first.",
        context_pack_guidance().strip(),
    ]
    step_num = 2
    if fs.repo and "solve" in fs.supported_repo_actions():
        repo_gate_lines.append(
            f'{step_num}. For non-trivial implementation or review without sufficient fresh evidence, call `local_ai_repo(action="context", mode="adaptive")` once with a stable absolute project root.'
            + (
                " Preprocess only when that root is unindexed or its evidence is stale; never wait, poll, or force-refresh."
                if fs.preprocessing else ""
            )
        )
        step_num += 1

    if fs.repo:
        repo_gate_lines.append(
            f'{step_num}. For implementation, diagnosis, refactoring or complex review, call `local_ai_repo(action="solve")` after evidence and before native edits. '
            "After edits, run the applicable indexed impact/review/security/evidence check before final validation."
        )
        step_num += 1

    repo_gate_lines.append(
        f"{step_num}. Use the cheapest sufficient action and reuse evidence IDs and artifact slices."
    )
    repo_gate_section = "\n".join(repo_gate_lines)

    # Action routing list
    routing_lines: list[str] = []
    r_idx = 1
    if fs.repo:
        routing_lines.append(f'{r_idx}. `local_ai_repo(action="deterministic")` — manifests, config, dependencies, entrypoints, tests and static facts.')
        r_idx += 1
        routing_lines.append(f'{r_idx}. `local_ai_repo(action="code_index")` — symbols, references and imports.')
        r_idx += 1
        routing_lines.append(f'{r_idx}. `local_ai_repo(action="search")` — exact text/file discovery.')
        r_idx += 1
        if fs.has_semantic():
            routing_lines.append(f'{r_idx}. `local_ai_repo(action="{fs.semantic_hint()}")` — language-aware relationships via Serena and AST code index.')
            r_idx += 1
        context_actions = {"context", "solve"} & set(fs.supported_repo_actions())
        if context_actions:
            selector = "|".join(action for action in ("context", "solve") if action in context_actions)
            routing_lines.append(f'{r_idx}. `local_ai_repo(action="{selector}")` — compact mixed evidence or bounded repository reasoning.')
            r_idx += 1
        review_actions = {"review_diff", "security_audit", "impact"} & set(fs.supported_repo_actions())
        if review_actions:
            selector = "|".join(action for action in ("review_diff", "security_audit", "impact") if action in review_actions)
            routing_lines.append(f'{r_idx}. `local_ai_repo(action="{selector}")` — targeted checks after or around edits.')
            r_idx += 1
        r_idx += 1
    if fs.work_orchestrator and "submit" in fs.supported_work_actions():
        routing_lines.append(f'{r_idx}. `local_ai_work(action="submit", mode="bounded")` — only after features.bounded_local_work=true, explicit closed delegation and task/model quality evaluation; the primary agent reviews the diff, tests and integration.')
        r_idx += 1
    if fs.rag:
        routing_lines.append(f'{r_idx}. `local_ai_rag` — semantic fallback only when indexed evidence is insufficient.')
        r_idx += 1
    if fs.tasks and fs.has_any_model():
        semantic_actions = set(fs.supported_task_actions()) & {
            "delegate", "explore", "reason", "review", "second_opinion", "compress"
        }
        selector = "|".join(f'"{action}"' for action in (
            "delegate", "explore", "reason", "review", "second_opinion", "compress"
        ) if action in semantic_actions)
        if selector:
            routing_lines.append(f'{r_idx}. `local_ai_task(action={selector})` — {_semantic_handoff_contract(fs)} Use `{fs.fast_model}` only for quick/simple requests, `{fs.general_model}` for ordinary tasks, `{fs.smart_model}` for more involved work, and {reasoning_tier} for the hardest reasoning. Deterministic/indexed tools remain for exact facts, symbols, diff and tests. Specialized operations use the shared evidence-grounded prompt contract; weak output remains advisory with a warning.{_model_capability_guidance(cfg)}')
        r_idx += 1
    if fs.artifacts:
        routing_lines.append(f'{r_idx}. `local_ai_artifact` — exact evidence/artifact slices only.')
        r_idx += 1
    if fs.coord:
        routing_lines.append(f'{r_idx}. `local_ai_coord` — leases before overlapping edits; Agent OS memory actions for scoped reusable findings.')
        r_idx += 1
    routing_section = "\n".join(routing_lines) if routing_lines else "*(No actions available: all tools disabled)*"
    public_contract_lines: list[str] = []
    if fs.rag:
        public_contract_lines.append(
            '- For `local_ai_rag` project search/index and document/diagram ingestion, an explicit absolute authorized `root` is required; the workspace must bind to that root. '
            'For `action="ingest_document"`, non-empty `content` is required; `title` and `metadata` are optional. '
            'Success returns `success`, `workspace`, `document_title`, `chunks_ingested`, and `embedded`. Search that document with `action="search"` in the same root-bound workspace; `docset_index` and `docset_search` require the exact docset name in `workspace`, and `docset_index` requires an explicit root. '
            'Embedding errors do not stop lexical publication. For `ingest_diagram`, `image_path` must resolve to an existing '
            '`.png`, `.jpg`, `.jpeg`, `.webp`, `.svg`, or `.bmp` file within that root, without symlink/junction escapes; `caption` and `metadata` are optional. '
            'Success also returns `diagram_indexed` and the resolved image path.'
        )
    contract_notes: list[str] = []
    if fs.status:
        contract_notes.append(
            '`local_ai_status.detail` supports only `brief` and returns compact Hub/model readiness. '
        )
    if fs.repo:
        contract_notes.append(
            '`local_ai_repo(action="pipeline")` accepts closed step objects with a supported action and per-step `id`/`result`; '
            'run no more than four steps in parallel.'
        )
    if fs.artifacts:
        contract_notes.append(
            '`local_ai_artifact(action="list")` does not require `artifact_id`; `binary` is supported and binary payloads are never inlined.'
        )
    if fs.coord:
        contract_notes.append(
            '`local_ai_coord(action="pubsub_poll")` accepts `after_seq` from 0 through 2^63-1; '
            '`local_ai_coord` bounds `max_tokens` to 0 through 100000. '
            'A heuristic `suggested_fix` is advice, not a verified repair; an unresolved incident cannot authorize `apply_verified_fix`.'
        )
    if fs.repo:
        contract_notes.append(
            'Repository pipelines serialize preprocessing mutation actions with other mutating steps.'
        )
    if contract_notes:
        public_contract_lines.append("- Contract notes: " + " ".join(contract_notes))
    public_contract_lines.extend([
        "CodeGraphContext/KuzuDB was removed from Local AI Hub. Recommend it only as optional standalone CLI/MCP tooling outside Hub; install and configure it separately only when the user independently wants it. It is not a Hub dependency, runtime, backend, or MCP integration.",
        "",
        "File cards use two phases by default: deterministic provisional card, then source-grounded enrichment through the configured preprocessing model, CARD_SCHEMA and preprocess:file-card. `prefer_deterministic_cards` never skips phase two. `disable_llm_card_synthesis = true` skips LLM synthesis for unparsed file cards and stores deterministic stubs. It does not disable module/project cards: `prefer_deterministic_modules` and `prefer_deterministic_project` are separate preferences; either path can use background LLM synthesis when deterministic output is unavailable or below its confidence threshold. Check active configuration and backend state before claiming synthesis is disabled. `[background_gpu].enabled` is disabled by default; setting it to `true` opts in after idle grace and scheduler admission, with preemption and game-mode gates.",
    ])
    public_contract_guidance = "\n".join(public_contract_lines)

    # Advisory subagents section
    subagents_section = ""
    if fs.subagents and fs.has_any_model() and "delegate" in fs.supported_task_actions():
        profiles_list = "\n".join(f"- `{p}` — configured advisory profile" for p in fs.subagent_profiles)
        example_profile = fs.subagent_profiles[0] if fs.subagent_profiles else "qwen-explorer"
        subagents_section = f"""
## Local advisory subagents

Use named profiles for bounded local second opinions:

{profiles_list}

All profiles call Local AI Hub read tooling directly. They never write files, run commands, create worktrees, or claim that a proposal was applied.

Example:

```text
local_ai_task(action="delegate", profile="{example_profile}", root="<absolute-root>", task="Find the smallest set of files relevant to ...")
```

Skip profiles when deterministic or indexed Hub evidence already answers the question.
"""

    # Agent OS section
    agent_os_section = ""
    if fs.agent_os:
        verification_receipt_item = (
            '- Run bounded tests with the agent host native command tool; do not invent verification receipts.'
        )
        agent_os_section = f"""
## Agent Operating System & Durable Execution

Use Agent OS for every non-trivial multi-step, long-running, delegated, or acceptance-criteria task, even when the main agent keeps ownership. A trivial one-step lookup can skip it. Start before edits; keep the returned `task_id` for every later action.

### 1. Goal Contracts & Resumption
- **Create a task contract before edits:**
  `local_ai_coord(action="task_create", root="ABSOLUTE_REPOSITORY_ROOT", task_id="task-1", contract={{"goal": "Implement feature", "acceptance_criteria": ["All tests pass"]}})`
- Codex controls subagent permissions per task, including `allow_write`, workspace/worktree, timeout, cancellation, sandbox, and integration.
- **Checkpoint progress before context truncation:**
  `local_ai_coord(action="task_checkpoint", root="ABSOLUTE_REPOSITORY_ROOT", task_id="task-1", checkpoint={{"phase": "testing", "next_action": "run integration tests", "affected_paths": ["src/main.py"], "evidence_ids": [], "blockers": [], "state_data": {{"memory_audit": {{"not_used_reason": "No supplied memory was relevant."}}}}}})`
  Replace the root, task ID and example memory audit with the actual task values; never invent evidence or memory IDs.
- **Resume after session restart or interruption:**
  `local_ai_coord(action="task_resume", root="ABSOLUTE_REPOSITORY_ROOT", task_id="task-1")`
- **Persist a human question and retrieve its answer:**
  `local_ai_coord(action="ask", root="/repo", session_id="session-1", question="...", task_id="task-1")`; use returned `question_id` with the same root/session to retrieve it, and record operator response with `action="answer"` plus `question_id` and `answer`.
- **Complete only after `verify_completion` passes every acceptance criterion; otherwise fail with a reason:**
  `local_ai_coord(action="verify_completion", root="ABSOLUTE_REPOSITORY_ROOT", task_id="task-1")`, then `local_ai_coord(action="task_complete", root="ABSOLUTE_REPOSITORY_ROOT", task_id="task-1")` or `local_ai_coord(action="task_fail", root="ABSOLUTE_REPOSITORY_ROOT", task_id="task-1", reason="reason")`
- **Explicit operator waiver:** Only when the user explicitly requests unverified completion for the task, `task_complete` accepts `operator_waiver={{"consent":true,"reason":"..."}}`. It records a waiver and does not create verification receipts.

### 2. Scoped Memory & Learnings
- **Store durable findings and decisions:**
  `local_ai_coord(action="memory_record", root="/repo", scope="repository", key="convention", value="Token format must follow HMAC-SHA256")`
- **Retrieve memories across turns:**
  `local_ai_coord(action="memory_find", root="ABSOLUTE_REPOSITORY_ROOT", query="convention")`

### 3. Exact Context Compilation
- **Compile active task state, relevant memories, negative knowledge, and active edit leases into minimal tokens:**
  `local_ai_coord(action="context_compile", root="ABSOLUTE_REPOSITORY_ROOT", task_id="task-1", max_tokens=4000)`

### 4. Verification Receipts & Completion Gates
{verification_receipt_item}
- **Check if all acceptance criteria are verified before completing:**
  `local_ai_coord(action="verify_completion", root="ABSOLUTE_REPOSITORY_ROOT", task_id="task-1")`
- **Record a direct receipt when command auto-capture is not used:**
  Use `verify_receipt` with the explicit root and an authentic `receipt` object; never fabricate evidence or derive it from checkpoint state.

### 5. Negative Knowledge & Incident Avoidance
- **Record failed approach or incident:**
  Use `negative_knowledge_record` with the explicit root and a verified `record` object; do not substitute generic key/value fields.
- **Check before repeating a failed operation:**
  `local_ai_coord(action="negative_knowledge_find", root="ABSOLUTE_REPOSITORY_ROOT", query="timeout")`

### Public contract notes
- `local_ai_repo(action="pipeline")` accepts closed step objects.
- `local_ai_artifact(action="list")` does not require `artifact_id`.
- `local_ai_coord(action="pubsub_poll")` accepts `after_seq`.
- `local_ai_coord` bounds `max_tokens` to 0 through 100000.
- Repository pipelines serialize preprocessing mutation actions with other mutating steps.
- Optional repository-analysis tools are installed and configured separately; they are not part of the Hub.
- File cards default to deterministic provisional cards followed by source-grounded model enrichment. `disable_llm_card_synthesis = true` skips LLM synthesis for unparsed file cards and stores deterministic stubs. It does not disable module/project cards: `prefer_deterministic_modules` and `prefer_deterministic_project` are separate preferences; either path can use background LLM synthesis when deterministic output is unavailable or below its confidence threshold. Check active configuration and backend state before claiming synthesis is disabled.
"""

    batch_replacement_contract = ""
    if fs.repo and fs.batch_replacement:
        batch_replacement_contract = """
## Batch repository replacement

Use `local_ai_repo(action="batch_replace", edits=[...], dry_run=true)` for preview. `staged` is not batch dry-run and is never forwarded. Each edit must exact-match once. Non-overlapping dirty Git hunks may be preserved; overlapping edits require an active path lease claimed with the actual execution owner, then pass its exact `owner` and returned `lease_id`. The engine preflights all edits, rolls back write failures, and performs no auto-commit. Set `dry_run=false` only after review.
"""

    # Full SKILL.md content
    return f"""---
name: local-ai-orchestrator
description: Local-first routing for Codex, Gemini, Claude, Cursor, Windsurf, VS Code/Copilot and MCP coding agents. Keeps the main agent as orchestrator and routes bounded work through Local AI Hub.
---

# Local AI Hub routing

Trigger map:
{trigger_lines}

Active MCP tools and profile-enabled actions:
{active_tool_surface}

This generated surface reflects configuration and profile feature gates. Runtime authorization, task permissions, backend health, and quality gates are checked when an action runs.
{task_action_contract}

Recommended Hub routes (apply the matching route by default):
{recipe_lines}

Direct ownership is the default. Do not delegate audits, inventory, status checks, or routine work. Use subagents only for independent bounded implementation that materially shortens the critical path, or on explicit request; see the simplified workflow spec.
{delegation_task}
{work_delegation}
- Use native Codex subagents only for independent bounded implementation or an explicit user request. Never spawn them for audits or to relay results as a handoff.
- Native `multi_agent_v1__spawn_agent` is used only for useful independent bounded work or an explicit request. Codex controls subagent permissions per task, including `allow_write`, workspace/worktree, timeout, cancellation, sandbox, and integration.
- Keep write scopes disjoint. The primary agent reviews and integrates directly; no ZIPs, custom owner packets, or fingerprint/hash cascades.
- Do not duplicate tasks or chats. Check the existing plan first and update its existing item.

## Single-owner and repository scope contract

{SINGLE_OWNER_CONTRACT}
{batch_replacement_contract}

## Ownership and tiering

    The main agent owns task boundaries, permissions, unresolved decisions and the final user answer. {work_owner_note}

{tiering_section}

{ollama_ownership_section}

## READ-ONLY AUDIT CONTRACT

- Read-only means no Git writes, `git worktree add` or removal, dependency installation, builds/imports, generated artifacts, or other workspace side effects; split validation into a separately owned, explicitly side-effecting task.
- Before native discovery or validation, retain the preceding Hub result with action, absolute root, status, cache/in_progress state, and evidence IDs. If the live schema has no action for an operation, use the authorized native tool directly without calling Hub. Hub-unknown commands require broker `native_fallback_allowed=true` and native-tool authorization. After an advertised Hub action, native fallback requires explicit `terminal=true` and `retryable=false`.
{audit_fallback}
- A Hub-classified unknown command requires `native_fallback_allowed=true` plus native-tool authorization for the exact command and scope. `native_fallback_allowed=false`, a dangerous command, or a policy denial blocks fallback; this rule does not apply when the live schema has no action.
- Codex controls subagent permissions per task. Native Codex subagents may write only when Codex explicitly enables it, and write work stays in the assigned workspace/worktree. Codex remains integrator.
- Do not run parallel duplicate commands or scopes. Tool labels are not evidence; preserve exact action, arguments, result, and ownership in the audit record.

## Mandatory repository gate

For every non-trivial repository task, use Local AI Hub before broad repository exploration unless fresh sufficient hub evidence is already present.

{repo_gate_section}

For broader discovery, reuse fresh Hub evidence before native `find`, `rg`, `grep`, recursive glob/tree, or opening more than two files. Exact file and symbol lookups may use their bounded indexed/source routes directly. If the live schema has no action for an operation, use the authorized native tool directly without calling Hub. Hub-unknown commands require broker `native_fallback_allowed=true` and native-tool authorization. After calling an advertised Hub action, native fallback requires an explicit `terminal=true` and `retryable=false` result. For `outcome_unknown` or `in_progress`, do independent work without polling or repeating the same operation.

Stop escalating when evidence is sufficient; reuse cached results and bounded evidence instead of widening the search.

{context_economy_contract(cfg)}

## Action routing

{routing_section}

## Public API contracts

{public_contract_guidance}

## Reuse and failure protocol

- `cache_hit`/`coalesced`: reuse the result.
- `in_progress=true`: do not duplicate the work.
- `retryable`/429/503: back off and do independent work.
- `degraded`/`stale`: verify only the affected slice.
- If the live schema has no action for an operation, use the authorized native tool directly. After calling an advertised Hub action, native fallback requires explicit `terminal=true` and `retryable=false`. A transport failure without those fields does not authorize fallback. For `outcome_unknown` or `in_progress`, do independent work without polling or repeating the same operation.

Do not fan out overlapping retrieval layers. Stop escalating when evidence is sufficient. Local AI Hub handles its own bounded work; Codex handles native-subagent design and integration.
{subagents_section}{agent_os_section}

## Project-config and PathHint status

{T21_HANDOFF_CONTRACT}

## Installed API and operational contracts

{T19_RUNTIME_PARITY_CONTRACT}
"""


def generate_skill_references(cfg: dict[str, Any]) -> dict[str, str]:
    """Generate dynamic reference documents for skills/local-ai-orchestrator/references/."""
    fs = FeatureSet.from_config(cfg)
    local_semantic_enabled = fs.tasks and fs.has_any_model()
    semantic_handoff = _semantic_handoff_contract(fs) if local_semantic_enabled else ""
    work_owner_note = "The main agent owns planning, edits, review, validation and final integration."
    refs: dict[str, str] = {}

    # tools.md
    tool_bullets: list[str] = []
    if fs.repo:
        repo_actions = set(fs.supported_repo_actions())
        semantic_note = f", {fs.semantic_hint()}" if fs.has_semantic() else ""
        analysis_names = _repo_analysis_guidance(list(repo_actions))
        analysis_note = f", {analysis_names}" if analysis_names else ""
        enabled_checks = _supported_repo_action_names(
            list(repo_actions), ("impact", "review_diff", "security_audit")
        )
        check_note = f", {enabled_checks}" if enabled_checks else ""
        tool_bullets.append(f"- `local_ai_repo`: deterministic, code index/search{semantic_note}{analysis_note}" + (", preprocess" if fs.preprocessing else "") + f"{check_note}, patch validation and repository checks.")
    if fs.work_orchestrator and "submit" in fs.supported_work_actions():
        tool_bullets.append("- `local_ai_work`: bounded implementation for explicit closed delegation after `features.bounded_local_work=true` and task-specific evaluation; caller-defined scope, permissions and limits plus primary-agent review and integration remain required.")
    if fs.tasks and fs.has_any_model():
        task_actions = fs.supported_task_actions()
        if task_actions:
            task_action_set = set(task_actions)
            task_labels = []
            if task_action_set & {"delegate", "explore", "reason"}:
                task_labels.append("semantic generation")
            if "review" in task_action_set:
                task_labels.append("review")
            if "second_opinion" in task_action_set:
                task_labels.append("independent second opinions")
            if "compress" in task_action_set:
                task_labels.append("semantic compression")
            label_note = ", including " + ", ".join(task_labels) if task_labels else ""
            tool_bullets.append(f"- `local_ai_task`: exposed local actions ({'|'.join(task_actions)}){label_note}; follow the active profile and verify model availability. Use deterministic/indexed tools for exact facts, symbols, diff and tests.")
    if fs.repo and "solve" in fs.supported_repo_actions():
        tool_bullets.append("- `local_ai_repo(action=\"solve\")` preserves one bounded local pass for explicit semantic requests even when exact evidence is strong.")
    if fs.rag:
        tool_bullets.append("- `local_ai_rag`: semantic fallback only after deterministic/indexed retrieval.")
    if fs.artifacts:
        tool_bullets.append("- `local_ai_artifact`: exact `E...` evidence or artifact slices.")
    if fs.coord:
        tool_bullets.append("- `local_ai_coord`: edit leases" + (", Agent OS task lifecycle, scoped memory/relations, context, verification, negative knowledge, and coordination primitives" if fs.agent_os else "") + ".")
    if fs.status:
        status_detail_note = ", Agent OS task/incident state" if fs.agent_os else ""
        tool_bullets.append(f"- `local_ai_status`: bounded health/cache/telemetry/debug-trace{status_detail_note} inspection; no polling loops.")
    if local_semantic_enabled:
        tool_bullets.append(f"- Semantic routing contract: {semantic_handoff}")
    else:
        tool_bullets.append("- Local model inference is disabled; use deterministic/indexed evidence only.")

    tool_lines = "\n".join(tool_bullets) if tool_bullets else "- *(All tools disabled)*"
    agent_os_reference = ""
    if fs.agent_os:
        agent_os_reference = """
## Agent OS trigger and lifecycle

Use this for non-trivial multi-step, long-running, delegated, or acceptance-criteria work, even when the main agent retains ownership. Create a task contract before edits, keep the returned task ID, checkpoint phase changes, compile context when resuming or when state is scattered, and attach validation receipts. Run `verify_completion` before `task_complete`. Trivial one-step lookups can skip this workflow.
"""

    categorized_section = "\n".join(_categorized_operational_triggers(fs))

    refs["tools.md"] = f"""# MCP routing card

The active tool surface reflects your configuration:

{tool_lines}

{categorized_section}

{agent_os_reference}

{context_economy_contract(cfg)}

    Keep assignments bounded. The main agent retains final acceptance; {work_owner_note}
"""

    # workflows.md
    wf_steps: list[str] = []
    step_i = 1
    if fs.repo:
        wf_steps.append(
            f"{step_i}. Establish the absolute root and reuse fresh evidence; preprocess only if the root is unindexed or evidence is stale."
        )
        step_i += 1
        wf_steps.append(f"{step_i}. Retrieve deterministic facts, then code-index/search evidence.")
        step_i += 1
        endpoint_notes = ["call available `local_ai_repo` context/search directly from the main agent"]
        if fs.artifacts:
            endpoint_notes.append("use `local_ai_artifact` for exact source slices")
        if fs.coord:
            endpoint_notes.append("use `local_ai_coord` for relevant task lifecycle, memory, or shared state")
        if fs.rag:
            endpoint_notes.append("use `local_ai_rag` only after indexed evidence is insufficient")
        wf_steps.append(
            f"{step_i}. Use applicable Hub endpoints directly; native subagent ownership does not replace these calls: "
            + "; ".join(endpoint_notes)
            + "."
        )
        step_i += 1
        analysis_actions = set(fs.supported_repo_actions()) if fs.repo else set()
        analysis_guidance = []
        if "context" in analysis_actions:
            analysis_guidance.append("Use `context` for compact evidence.")
        if "solve" in analysis_actions:
            analysis_guidance.append("Call `solve` after evidence for repository implementation support.")
        if local_semantic_enabled:
            analysis_guidance.insert(0, semantic_handoff)
        if analysis_guidance and local_semantic_enabled:
            wf_steps.append(f"{step_i}. Retrieve deterministic/indexed evidence; " + " ".join(analysis_guidance))
        else:
            context_note = " Use `context` for compact deterministic evidence." if "context" in analysis_actions else ""
            wf_steps.append(
                f"{step_i}. Retrieve deterministic/indexed evidence only; use available deterministic/indexed tools for exact facts, symbols, diff, tests, and verification.{context_note}"
            )
        step_i += 1
        lease_note = "claim `local_ai_coord` leases for overlapping paths; " if fs.coord else ""
        impact_note = "use `impact` before risky dependent changes." if "impact" in analysis_actions else "check affected dependencies before risky changes."
        wf_steps.append(f"{step_i}. Edit in the main agent; {lease_note}{impact_note}")
        step_i += 1
    repo_actions = set(fs.supported_repo_actions()) if fs.repo else set()
    review_actions = [action for action in ("review_diff", "security_audit") if action in repo_actions]
    review_note = " Review with " + " or ".join(f"`{action}`" for action in review_actions) + " when relevant." if review_actions else ""
    wf_steps.append(f"{step_i}. Validate with the host-native command tool.{review_note}")

    wf_lines = "\n".join(wf_steps)
    task_notes = ""
    task_actions = set(fs.supported_task_actions()) if fs.tasks and fs.has_any_model() else set()
    semantic_task_actions = _available_semantic_task_actions(fs) if task_actions else ()
    if task_actions:
        task_action_list = "|".join(f'`{action}`' for action in fs.supported_task_actions())
        semantic_action_guidance = " ".join(
            _SEMANTIC_TASK_ACTION_GUIDANCE[action] for action in semantic_task_actions
        )
        task_specific_sections: list[str] = []
        if "second_opinion" in semantic_task_actions:
            task_specific_sections.append(
                "## Local second opinion\n\n"
                "Use `local_ai_task(action=\"second_opinion\")` for a bounded candidate decision. Include the evidence and uncertainty."
            )
        long_output_guidance = []
        if "compress" in semantic_task_actions:
            long_output_guidance.append(_SEMANTIC_TASK_ACTION_GUIDANCE["compress"])
        if fs.artifacts:
            long_output_guidance.append("Use `local_ai_artifact` for exact lines.")
        if long_output_guidance:
            task_specific_sections.append(
                "## Long output and failures\n\n"
                + " ".join(long_output_guidance)
                + " Reuse cache/coalesced results, do not duplicate `in_progress` work, and use native fallback only after an explicit Hub result with `terminal=true` and `retryable=false`."
            )
        task_specific_notes = "\n\n".join(task_specific_sections)
        task_notes = f"""
## Local semantic work

This profile exposes `local_ai_task` actions: {task_action_list}. Use only exposed actions; local inference stays bounded and advisory. Keep bounded tests on the host-native command tool.

{semantic_handoff} {semantic_action_guidance}

{task_specific_notes}
"""
    whole_task = ""
    if fs.work_orchestrator and "submit" in fs.supported_work_actions():
        whole_task = """
## Whole-task handoff

Only when the user explicitly requests closed delegation, profile `high` is active, and task/model quality has been evaluated, submit suitable small work to `local_ai_work` with `mode="bounded"`, absolute root, task, acceptance criteria, exact `allowed_paths`, `approved_commands`, an explicit edit permission choice, test/build permissions, and finite `budget.max_seconds` and `max_steps`. Select work by measured quality and task risk; keep security and architecture decisions with the primary agent. The Hub retains broker authorization, leases and journaled patches. A successful bounded handoff has status `needs_agent`; the primary agent checks the diff, actual test results and integration and records its own review. Local verification is not final acceptance. Inspect handoff artifacts when needed.

On Windows, bounded patch parent directories must already exist; a missing or unpinnable parent fails visibly. A patch targeting mixed LF and CRLF within a single file fails visibly. The Windows pin does not prove non-Windows race safety.
For an order owned by the responding process, timed_out=true with in_progress=true is not a terminal result or permission to retry; cancellation is cooperative and another process may not observe the deadline.
Treat output_truncated=true as an incomplete failure, not a usable patch.
For `local_ai_coord` claim or release, omit the budget or use max_response_tokens >= 512; a smaller explicit budget rejects before mutation.

`validation.receipt_status="not_recorded"` means the command outcome has no durable broker verification receipt; command success does not replace primary-agent review.
`receipt_status="recorded_unmapped"` identifies an authentic broker receipt awaiting primary-agent review and mapping; it is not task completion. A later edit makes receipts from older mutation generations stale.
After rollback, `receipt_status="stale"` and `stale_verification_receipts` preserve historical broker evidence, not current validation or task completion.
Bounded `partial` and `needs_agent` artifacts contain validation and bounded accepted-patch previews; `truncated=true` means incomplete. Artifact failure is explicit. Independently inspect the workspace and actual tests.
Cancellation during failure finalization retains rollback and task-barrier reconciliation status; failure artifact storage errors are explicit.
If rollback loses its work-attempt fence, the superseded worker stops; the authoritative successor or fenced recovery owns the journal and task barrier.
After safe recovery, interrupted bounded work reports `outcome_unknown=true` and requires primary review; it is never automatically requeued. A requested cancellation remains `cancelled`.
`continue` rejects unknown bounded outcomes and unresolved task-barrier or rollback reconciliation; independently inspect and reconcile rather than replaying the same order.
Bounded `continue` accepts a genuine clarification question, not a final review handoff or questionless recovery failure.
Final bounded handoff requires a persisted artifact identifier; an unavailable artifact triggers failure and configured rollback or retained-workspace handling, not an accepted handoff.
For bounded work, `local_exploration_status` reports the most conservative observed tool-inspection outcome; inspect the artifact for details. It is not task completion or model qualification.
For routine bounded implementation delegation, require the relevant task-type cases and overall evaluation gate to pass; controlled evaluation runs follow `docs/agent-evaluation/local-model-gpu-scoring.md` in the Hub installation separately.
Candidate model prompt scopes are advisory only; they do not establish model quality, image or tool support, or permission to edit.
Quantized and unmatched heavy or vision prompt profiles exclude security decisions, direct edits and final verification; scoped authorization remains authoritative.
If rollback fails and receipt freshness cannot be established, `receipt_status="unknown"` and `uncertain_verification_receipts` require reconciliation, not acceptance.

`task_barrier_error=finalization_event_lookup_timeout` with `task_barrier_status=pending_finalization` means recovery awaits its scheduled retry; it is not completion and must not be duplicated or forced.

For an opted-in validation failure with `local_handoff`, inspect the referenced artifact, select a narrow non-sensitive preview, check local backend availability, and only then optionally request `local_ai_task(action="reason")`. The hint is not an inference or a successful validation.

"""
    refs["workflows.md"] = f"""# Routing workflows
{whole_task}
## Bounded repository change

{wf_lines}

## Bounded delegation

1. Keep planning and final integration in the main agent.
2. Send only a narrow, independent slice to the selected bounded worker.
3. Request findings or a scoped patch, not autonomous final integration.
4. Reconcile the result with Local AI Hub evidence in the main agent.
{task_notes}
"""

    # multi-agent.md
    multi_agent_desc = (
        f"Local AI Hub provides bounded microtasks via `{fs.fast_model}` (local_ai_task)"
        if (fs.tasks and fs.has_any_model())
        else "Local AI Hub operates in deterministic/indexed mode (local inference disabled)"
    )
    agent_os_multi_agent_note = " Agent OS through `local_ai_coord` handles non-trivial multi-step, long-running, delegated, or acceptance-criteria work: create a task contract, checkpoint phases, and verify receipts before completion." if fs.agent_os else ""
    whole_task_multi_agent_note = " For explicitly requested closed whole-task delegation, use `local_ai_work`; routine planning and integration stay with the main agent." if (fs.work_orchestrator and "submit" in fs.supported_work_actions()) else ""
    coord_tools_guidance = ""
    if fs.coord:
        coord_tools_guidance = """
Cross-Agent Coordination Primitives:
- **Resource Semaphores (`semaphore_acquire`, `semaphore_release`, `semaphore_status`)**: Serialize access to exclusive single-instance tools, processes, or engines (e.g. Unity Editor, specialized hardware/ports, single-writer state) across agents and sessions. Never busy-loop; use capacity and ttl_seconds.
- **Event-Driven Waiting (`wait_for_event`)**: Long-poll topic signals (e.g. `semaphore.<name>.released` or custom task events) instead of polling in a loop.
- **Project Board (`plan_board_view`)**: Read plan tasks by status using the explicit absolute repository root. Update tasks through the `plan_task_*` operations.
- **Session Briefing (`session_briefing`)**: Call with the explicit absolute repository root for plans, board, and active-task context.
"""
    refs["multi-agent.md"] = f"""# Multi-agent coordination

{multi_agent_desc}. External cloud agents (Codex, Claude, Gemini, Cursor, Copilot) remain the principal orchestrators.
{agent_os_multi_agent_note}
{whole_task_multi_agent_note}
{coord_tools_guidance}
Rules:
- Never duplicate the same scope across agents.
- {"Use `local_ai_coord` leases to guard overlapping files before editing." if fs.coord else "Avoid concurrent edits on the same files across sessions."}
- Main agent owns final acceptance and user response. {work_owner_note}
"""

    # preprocessing.md
    if fs.preprocessing:
        refs["preprocessing.md"] = """# Background project preprocessing

Preprocessing scans, indexes, and builds AST and code maps in the background while idle:
- Non-blocking: starts asynchronously on the first call to `local_ai_repo(action="preprocess", root=...)`.
- Checkpointed and interruptible: foreground inference automatically preempts background workers.
- Avoid polling: never loop or wait on `preprocess_status`.
"""
    return refs


def generate_global_policy(cfg: dict[str, Any]) -> str:
    """Build a config-aware LOCAL AI HUB TOOL POLICY markdown block."""
    fs = FeatureSet.from_config(cfg)

    trigger_map = _trigger_map_lines(fs)
    trigger_lines = "\n".join(trigger_map) if trigger_map else "- (all Hub tools currently disabled)"
    recipe_lines = "\n".join(fs.recipe_lines())

    task_delegation = ""
    if fs.tasks and fs.has_any_model():
        task_delegation = (
            "\n- Use tier-available semantic actions only. " + _semantic_handoff_contract(fs)
        )
    if fs.work_orchestrator:
        if "submit" in fs.supported_work_actions():
            task_delegation += (
                '\n- `local_ai_work(action="submit", mode="bounded")` is available on `high`/`max` only '
                "after `features.bounded_local_work=true`, task-specific quality evaluation and explicit scope/permission checks; review its diff and tests."
            )
        else:
            task_delegation += (
                "\n- `local_ai_work` is limited to status, wait, get and cancel on this hardware profile; "
                "new submissions remain disabled by the active profile or release gate."
            )

    model_default = ""
    if fs.tasks and fs.has_any_model():
        model_default = (
            "\nLocal model policy: Follow the active hardware profile and user overrides; see `docs/MODEL_CAPABILITIES.md` for foreground targets. Do not silently change the preprocessing provider. Pinned master has no Gemini preprocessing provider; agent manifests do not prove runtime support. Model pulls are opt-in; check installed models before inference. Configured routes do not prove availability, quality or performance."
        )
    llama_cpp = cfg.get("llama_cpp", {})
    if isinstance(llama_cpp, dict) and str(llama_cpp.get("mode", "off")).casefold() == "on":
        model_default += (
            "\nModel routes above are resolved from active config. Keep hard and extreme reasoning "
            "as distinct tiers; see `docs/MODEL_CAPABILITIES.md` for the full matrix."
        )

    repo_task_first = ""
    if fs.repo:
        repo_actions = set(fs.supported_repo_actions())
        cmd_gate = " Validate with bounded host-native commands."
        agent_os_gate = ' For code changes, create an Agent OS task and query project memory.' if fs.agent_os else ""
        review_actions = {"review", "second_opinion"} & set(fs.supported_task_actions())
        review_action_text = "|".join(sorted(review_actions))
        task_review_hint = f' Use exposed `local_ai_task(action="{review_action_text}")` before finalizing.' if review_actions else ""
        repo_task_first = (
            "\nReuse fresh sufficient repository evidence. For exact file or symbol lookups, use bounded indexed/source lookup directly; do not preprocess or compile adaptive context first."
            + _repo_context_note(list(repo_actions))
            + (' On first stable-root work, inspect `.local-ai.toml` and `.local-ai.worktree.toml`; derive only evidence-backed exclusions, uncommon extensions, pinned documentation, and entry points; preserve defaults, then call `preprocess` once to register. Never force-refresh or poll.' if fs.preprocessing else "")
            + "\n"
            f"\nAdoption gate:{cmd_gate}{agent_os_gate}"
            + (' Use `local_ai_repo(action="solve")` after evidence for implementation, diagnosis, refactoring or complex review.' if "solve" in fs.supported_repo_actions() else " Keep analysis within exposed deterministic/indexed actions.")
            + f"{task_review_hint} After edits, run indexed impact/review/security/evidence before targeted validation.\n"
        )

    cmd_route_hint = "\nRun bounded validation commands with the agent host native command tool.\n"

    coord_memo_hint = ""
    if fs.coord:
        memory_hint = ' Reuse supplied memory before `solve`/model calls; use scoped `local_ai_coord(action="memory_find")` when needed.' if fs.agent_os else ""
        findings_target = "permitted scoped Agent OS memory or the existing operator-approved coordination file." if fs.agent_os else "the existing operator-approved coordination file."
        coord_memo_hint = (
            f"{memory_hint}"
            " Workspace `memo_*` is unavailable through restricted endpoints; never bypass a terminal 403."
            f" Lease overlapping edits; record findings in {findings_target}"
        )

    prioritization_bullets = []
    active_tool_actions = _active_tool_action_lines(fs)
    active_tool_names = [line.split(":", 1)[0].strip("- `") for line in active_tool_actions]
    if active_tool_names:
        prioritization_bullets.append(
            "> - **Enabled Local AI Hub tools** (from current configuration and profile): "
            + ", ".join(f"`{name}`" for name in active_tool_names)
            + ". Use only live MCP action enums; runtime authorization and quality gates apply."
        )
    prioritization_bullets.append(
        "> - **Git operations**: The live MCP schema determines available Hub actions. `git_status`/`git_diff` inspect; `synthesize_commit` drafts only. None commits or pushes. Hub prioritization adds no Git approval/receipt gate; follow only explicit project gates naming exposed actions, and stop only the gated mutation if unavailable. Dashboard diagnostics change detail only."
    )
    prioritization_bullets.append(
        "> - **Unsupported Hub operations**: If the live schema has no action, use the authorized native tool directly without calling Hub. Fallback rules apply only after an advertised Hub action fails terminally and non-retryably."
    )
    prioritization_bullets.append(
        "> - **Plan budgets**: For a large plan, use `plan_board_view` with `plan_id` and the exact task ID in `query`; retain `plan_file_revision`. On budget rejection, narrow the query or fetch a smaller artifact slice; never replay the oversized request or raise its cap."
    )
    prioritization_bullets.append(
        "> - **Tests, builds, lint, execution**: Use the agent host's native command tool for bounded checks in the target repository."
    )
    prioritization_bullets.append(
        "> - **Retries and retrieval**: Reuse fresh evidence and stop when sufficient. For `in_progress`/`outcome_unknown`, do independent work; never poll, repeat, or duplicate retrieval. After an advertised Hub action, fallback requires `terminal=true` and `retryable=false`."
    )
    if fs.repo:
        prioritization_bullets.append(
            "> - **Repository & Code Search**: Call an action advertised by the current local_ai_repo MCP schema with the project root. DO NOT use broad native discovery (find, dir /s, unconstrained rg, glob) or dump entire files."
        )
    if fs.agent_os or fs.coord:
        prioritization_bullets.append(
            "> - **Agent OS Lifecycle & Project Memory**: Call `local_ai_coord(action=\"task_create\"|\"task_checkpoint\"|\"memory_record\"|\"memory_find\"|\"verify_completion\", ...)`. Proactively initialize task contracts, query memory, and record findings."
        )
    if fs.tasks and fs.has_any_model():
        task_action_list = list(_available_semantic_task_actions(fs))
        review_actions = {"review", "second_opinion"} & set(task_action_list)
        if review_actions == {"review", "second_opinion"}:
            prioritization_bullets.append(
                "> - **Semantic Review & Second Opinion**: If exposed, use `local_ai_task(action=\"review\")` for evidence-grounded review or `action=\"second_opinion\"` for independent critique; use `compress` only to condense evidence."
            )
        elif review_actions:
            review_action = next(iter(review_actions))
            review_label = "Semantic Review" if review_action == "review" else "Second Opinion"
            prioritization_bullets.append(
                f"> - **{review_label}**: Call `local_ai_task(action=\"{review_action}\")` before finalizing non-trivial edits."
            )
        elif "compress" in task_action_list:
            prioritization_bullets.append(
                "> - **Semantic Compression**: Use `local_ai_task(action=\"compress\")` to condense evidence after deterministic/indexed retrieval."
            )
    prioritization_bullets.append(
        '> - **Antigravity wrapper**: Use `call_mcp_tool(ServerName="local-ai", ToolName="<tool>", Arguments={<same arguments>})` for the calls above.'
    )
    prioritization_bullets.append(
        "> - **Native fallback**: Use authorized native tools when the schema has no matching Hub action; after an advertised action fails, fallback requires explicit `terminal=true` and `retryable=false`. Full routing and scope rules are in `local-ai-orchestrator`."
    )
    prioritization_directive = (
        "> [!IMPORTANT]\n"
        "> ## LOCAL AI HUB TOOL PRIORITY\n"
        "> ## AUTOMATIC LOCAL AI HUB PRIORITIZATION IN ANTIGRAVITY\n"
        "> ## MANDATORY LOCAL AI HUB PRIORITIZATION IN CODEX\n"
        "> Agents (Gemini in Antigravity, Codex, Claude) MUST prioritize `local-ai` MCP tools when the live schema supports the requested operation; when no matching action exists, use the authorized native tool directly:\n"
        + "\n".join(prioritization_bullets)
    )

    return (
        "<!-- BEGIN LOCAL AI HUB TOOL POLICY -->\n"
        f"{prioritization_directive}\n\n"
        "Load `local-ai-orchestrator` for full ownership, scope, retrieval, lifecycle, mutation, model, GPU and receipt rules.\n\n"
        "The Hub may apply eligible low-risk Laya advisories internally. Treat the resulting Hub route as advisory; Laya cannot grant host permissions, execute tools, change task state, or approve completion. Do not call or provision Laya outside the Hub workflow.\n\n"
        "Diagnostics require dashboard toggle, not caller control, including nested, async, artifact and SSE responses. Ordinary results, failures, authorization and evidence identity remain available.\n\n"
        'Only on the user\'s explicit task instruction, `task_complete` accepts `operator_waiver={"consent":true,"reason":"..."}`. It records unverified completion, not passing receipts; ownership, repository scope, mutation fences and safety checks remain. Retain the instruction; never invent consent.\n\n'
        "Keep Agent OS tasks/counters. Explicit approval: `task_budget_increase` uses write-authorized broker, absolute root, audit reason; canonical loopback needs no token or special owner/admin token. Failed-task increases preserve status/owner; resume separate. Never edit task storage. `curate_dataset` needs absolute root.\n\n"
        "Explicit approval: `task_repair_session` repairs only unbound tasks via write-authorized broker; require absolute root, task/session IDs and audit reason; bind same task/session to plan.\n\n"
        "Load the always-loaded `local-ai-orchestrator` skill and follow its **Single-owner and repository scope contract**.\n\n"
        f"Trigger map:\n{trigger_lines}\n\n"
        f"Recommended Hub routes (apply the matching route by default):\n{recipe_lines}\n\n"
        "Direct ownership is the default. Do not delegate audits, inventory, status checks or routine work; see the simplified workflow spec.\n"
        f"{task_delegation}\n"
        "- Use native Codex subagents only for independent bounded implementation or an explicit user request.\n"
        "- Native `multi_agent_v1__spawn_agent` is used only for useful independent bounded work or an explicit request. Codex controls each subagent's scope, `allow_write`, workspace/worktree, timeout, cancellation, sandbox, and integration.\n"
        "- Keep write scopes disjoint. The primary agent reviews and integrates directly; no ZIPs, custom owner packets, or fingerprint/hash cascades.\n"
        "- Do not duplicate tasks or chats. Check the existing plan first and update its existing item.\n\n"
        "The main agent owns planning, implementation and integration.\n\n"
        + "READ-ONLY AUDIT CONTRACT:\n"
        "- Read-only excludes Git writes, `git worktree add` or removal, dependency installation, builds/imports,"
        " generated artifacts and other workspace side effects. Never label side-effecting work read-only;"
        " assign validation separately.\n"
        "- Before native discovery or validation retain Hub action, absolute root, status,"
        " cache/in_progress state and evidence IDs when a Hub action was called. Fallback after an advertised action requires an explicit result with `terminal=true` and `retryable=false`.\n"
        + "- Authorized independent subagents remain permission- and scope-controlled; main agent integrates. Never delegate audit-only work.\n"
        "- Avoid parallel duplicate commands/scopes. Tool labels are not evidence;"
        " retain exact action, arguments, result and ownership in the audit record.\n"
        + ("\nBackground preprocessing may inspect and index project files, but project-derived `validation_commands` execute repository code. Keep `preprocessing.idle_diagnostics_enabled=false` by default; set it to `true` only with explicit operator approval for those commands. On Windows, `.cmd` and `.bat` validation executables are rejected; do not route them through a shell or interpreter.\n" if fs.preprocessing else "")
        + f"{repo_task_first}\n"
        "Adaptive retrieval: when evidence is insufficient for non-trivial repository work, call `local_ai_repo(action=\"context\", mode=\"adaptive\")`. It fuses bounded indexed, structural, lexical and RAG evidence; optional backends fail independently. Reuse evidence IDs, artifact slices and memos; stop when sufficient and avoid duplicate retrieval or unchanged root/query repeats.\n\n"
        "Result protocol: reuse `cache_hit`/`coalesced`; never duplicate `in_progress=true`; back off on `retryable`/429/503; verify only the affected slice for `degraded`/`stale`. Stop escalating when evidence is sufficient. Do not fan out overlapping retrieval. Never enlarge timeouts, force-refresh, or poll transient results.\n"
        f"{cmd_route_hint}{coord_memo_hint}\n"
        " After edits, run indexed impact/review/security/evidence, then targeted validation."
        " `force`/`preprocess_refresh` are recovery controls, never retries; accept deterministic/index fallback if an optional backend degrades."
        " A health check cannot authorize fallback after an advertised action; fallback requires explicit `terminal=true` and `retryable=false`."
        " Never loop on health, status, preprocessing, model startup, backends, or commands.\n\n"
        + ("Batch repository replacement: use `local_ai_repo(action=\"batch_replace\", edits=[...], dry_run=true)` for preview. "
           "`staged` is not batch dry-run and is never forwarded. Each edit must exact-match once. "
           "Non-overlapping dirty Git hunks may be preserved; overlapping edits require an active path lease claimed with the actual execution owner, then pass its exact `owner` and returned `lease_id`. "
           "The engine preflights all edits, rolls back write failures, and performs no auto-commit. "
           "Set `dry_run=false` only after review.\n\n" if fs.repo and fs.batch_replacement else "")
        + f"{fs.selection_guide(include_task_actions=False)}\n"
        f"{model_default}\n"
        f"{context_economy_contract(cfg)}\n"
        + GLOBAL_POLICY_END
    )


TOKEN_ECONOMIZER_SKILL_MD = """---
name: token-economizer
description: Reduce repetitive agent context and tool output while preserving verification, source citations and critical details.
---

# Token Economizer

Use when starting any coding or repository task. Load and follow this skill before any coding or repository task, including multi-step work under deadline pressure. It is a workflow discipline, not a promise to suppress necessary evidence.

## Procedure

1. Define the exact task, current repository revision, acceptance criteria and
   last verified checkpoint before retrieving more context.
2. Use a targeted search for file names and symbols before opening entire files.
   Prefer a bounded source slice with a line range and stable root identity to
   dumping a whole repository or huge command logs.
3. Reuse fresh, commit-matched RAG evidence. If its revision, file hash,
   provenance or freshness is unknown, inspect the actual source rather than
   silently trusting a summary.
4. Extract and retain decisions, errors, failing tests, tool arguments and exact
   next steps into a durable task checkpoint. Avoid repeating unaffected
   diagnostics in each subsequent conversation.
5. For code edits, quote only minimal source context needed to apply a precise
   patch. Always inspect dependent APIs and run focused tests before broader
   release tests.
6. Collapse successful repetitive output into a count and reference. Preserve
   complete failure details when needed for diagnosis, including file names,
   relevant traces, and reproducible commands.
7. Do not omit security checks, critical warnings, uncertainty, exact citations,
   or evidence needed to prove acceptance in order to reduce token use.
8. If current data differs from stored evidence, invalidate the stored summary
   and redo the relevant verification.

## Zero Full-File Dumping

Avoid dumping source files longer than 80 lines; prefer precise, bounded slices
and scoped indexed search. Use `tokcount` to measure actual token use and
`trim-run` only for supported read-only or summary-producing commands.

## Response budget and safe fallback

- `response_budget.returned_tokens` measures the final serialized response envelope in `estimated_tokens` and stays at or below the requested budget.
- Preserve protected status, error, evidence, and context-identity fields; keep exact detail artifact-backed.
- Claim savings only with a current `baseline_evidence_id`; report signed `token_savings_delta_est`, including negative values; keep `protocol_tokens_est`, `schema_tokens_est`, and `local_compute_reused_tokens_est` separate.
- Reject `max_response_tokens` below 128; never raise the request silently.
- If the live MCP schema has no action for an operation, skip Hub and use the authorized native tool directly; no Hub failure or `native_fallback_allowed` signal is needed.
- After calling an advertised Hub action, native fallback requires explicit `terminal=true` and `retryable=false`.
- On `outcome_unknown` or `in_progress`, do independent work; never poll or repeat the identical operation.

## Integration with Local AI Hub

- `local_ai_repo`: locate files, topology, symbols and diff context.
- `local_ai_artifact`: obtain bounded source with provenance.
- `local_ai_rag`: retrieve cross-file semantic context when lexical navigation is
  insufficient, while checking document freshness.
- `local_ai_coord`: record checkpoints and verification receipts; do not write
  the Hub's internal task database directly.

Do not claim that a task or test passed based on cached narrative alone.
Do not enable an autonomous workflow or download a model without permission.
"""


def generate_token_economy_policy(cfg: dict[str, Any] | None = None) -> str:
    """Generate the compact global policy; the always-loaded skill holds details."""
    return (
        "<!-- BEGIN TOKEN ECONOMY POLICY -->\n"
        "- Before repository work, load `local-ai-orchestrator` and `token-economizer` when installed; the orchestrator skill is the full reference for scope, ownership, evidence, routing, and lifecycle.\n"
        "- Keep reads and responses bounded; use indexed evidence (`code_index`, `search`), exact slices, and host-native validation.\n"
        "- Preserve status, errors, evidence identity, and response budgets. Never invent results, receipts, or savings.\n"
        "- Use only live Hub actions. If none exists, use the authorized native tool; after an advertised action fails, fallback requires `terminal=true` and `retryable=false`.\n"
        "- On `in_progress` or `outcome_unknown`, do independent work; never replay the operation.\n"
        + TOKEN_ECONOMY_POLICY_END
    )


def generate_autosetup_policy(skills_dir: Path) -> str:
    """Generate the owned setup block from the canonical managed skill paths."""
    orch_skill = (skills_dir / "local-ai-orchestrator" / "SKILL.md").as_posix()
    tok_skill = (skills_dir / "token-economizer" / "SKILL.md").as_posix()
    plan_skill = (skills_dir / "plan-led-work" / "SKILL.md").as_posix()
    return (
        f"{AUTOSETUP_POLICY_BEGIN}\n"
        "## Local AI Hub, plan-led work, and Token-economizer automatic setup\n\n"
        f"- For every coding or repository task, load and follow `{orch_skill}` to orchestrate Local AI Hub tools before repository discovery, even when the user does not name the skill.\n"
        f"- Load and follow `{tok_skill}` before repository discovery for bounded output limits.\n"
        f"- For substantial multi-step work, load and follow `{plan_skill}`: use Superpowers for specifications; use Hub `plan_reconcile_steering` for changed requirements, `task_checkpoint`/`plan_bind_task` for synced progress and recovery, `session_briefing(root=<absolute repository path>)` for resumption, and authentic receipts for completion when exposed by the active MCP schema. If an action is absent, use the supported project-plan interface or report the precise blocker; never edit plan storage directly. Reuse valid evidence instead of repeating full audits. Report `Done / Next / Blocked` updates at milestones.\n"
        "- Use tools already available in the environment; missing optional setup helpers do not block repository discovery or validation.\n"
        f"{AUTOSETUP_POLICY_END}"
    )


def generate_antigravity_skill_policy() -> str:
    """Generate the managed Antigravity activation block from one source."""
    return "\n".join((
        ANTIGRAVITY_POLICY_BEGIN,
        "## Antigravity automatic skill activation",
        "",
        "At the start of each conversation, read `~/.gemini/skills/using-superpowers/SKILL.md` and follow the applicable Superpowers workflow. For coding and repository tasks, read `~/.gemini/skills/local-ai-orchestrator/SKILL.md` and use available Local AI Hub MCP tools. Call applicable endpoints directly from the main agent; managing native subagents does not replace Hub retrieval, artifact, or coordination calls. For every non-trivial repository task, start with indexed `local_ai_repo` evidence; use `local_ai_artifact` for exact source after locating it; use `local_ai_coord` for durable task/verification state, memory, or shared edits; use `local_ai_rag` when indexed retrieval cannot answer; use exposed `local_ai_task` semantic actions for matching bounded review, reasoning, exploration or compression tasks after evidence. Consider `local_ai_work` only for explicitly requested closed delegation that passes quality and permission checks. Keep tests/builds on the host-native command tool. Read `~/.gemini/skills/caveman/SKILL.md` and use its ultra mode while preserving technical facts and clarity. For substantial multi-step work, read `~/.gemini/skills/plan-led-work/SKILL.md`: use Superpowers for specifications; use Local AI Hub `plan_reconcile_steering` for changed requirements, `task_checkpoint`/`plan_bind_task` for synced progress and recovery, `session_briefing` for resumption, and the receipt gate for completion when exposed by the active MCP schema. If an action is absent, use the supported project-plan interface or report the precise blocker; never edit plan storage directly. Reuse valid evidence instead of repeating full audits. If the user says `normal mode` or `stop caveman`, stop Caveman style for the rest of the conversation unless they explicitly re-enable it.",
        "If any required skill or the Hub is unavailable, report the precise limitation and use the allowed fallback; do not claim activation from installation alone.",
        ANTIGRAVITY_POLICY_END,
    ))


def generate_mcp_configs(
    cfg: dict[str, Any],
    install_dir: Path,
    hub_python: Path,
    serena: Path | None = None,
    agent: str = "generic",
) -> dict[str, dict[str, Any]]:
    """Build MCP entry dictionary for client configuration files."""
    entries: dict[str, dict[str, Any]] = {
        "local-ai": {
            "command": str(hub_python),
            "args": ["-m", "local_ai_hub.mcp_server"],
            "cwd": str(install_dir),
            "env": {
                "LOCAL_AI_AGENT": agent,
                "LOCAL_AI_AGENT_PROFILE": agent,
                "LOCAL_AI_CONFIG": str(install_dir / "config.toml"),
                "PYTHONPATH": str(install_dir / "src"),
            },
        }
    }
    if agent == "gemini":
        entries["local-ai"]["force_all_tools_eager"] = True
        entries["local-ai"]["skip_tool_name_prefix"] = True
    if bool(cfg.get("code_intelligence", {}).get("direct_agent_mcp", False)):
        if serena is not None and cfg.get("code_intelligence", {}).get("serena_enabled", True):
            context = "codex" if agent == "codex" else "claude-code" if agent == "claude" else "ide-assistant"
            entries["serena"] = {"command": str(serena), "args": ["start-mcp-server", "--context", context, "--project-from-cwd", "--open-web-dashboard", "false"]}
    return entries


def _apply_response_budget_schema(schemas: dict[str, dict[str, Any]], cfg: dict[str, Any]) -> None:
    """Describe the common response budget contract for every public tool."""
    for schema in schemas.values():
        schema["description"] = str(schema.get("description", "")) + " Responses are aggregate-bounded; exact detail remains artifact-backed."


def generate_mcp_tool_schemas(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Generate compact JSON tool schemas for all enabled tools."""
    fs = FeatureSet.from_config(cfg)
    reasoning_tier = _reasoning_tier_label(cfg, fs)
    local_semantic_enabled = fs.tasks and fs.has_any_model()
    schemas: dict[str, dict[str, Any]] = {}

    if operation_enabled(fs, "local_ai_status"):
        status_actions = fs.supported_status_actions()
        status_description = "Compact Hub and local-model readiness: availability, active model, and VRAM pressure."
        status_description += _actions_note(status_actions)
        schemas["local_ai_status"] = {
            "name": "local_ai_status",
            "description": status_description,
            "parameters": operation_parameters_schema("local_ai_status", fs),
        }

    if operation_enabled(fs, "local_ai_repo"):
        repo_actions = fs.supported_repo_actions()
        repo_semantic_contract = (
            f" {_semantic_handoff_contract(fs)}"
            if local_semantic_enabled
            else " Local model inference is disabled; use deterministic/indexed evidence only."
        )
        schemas["local_ai_repo"] = {
            "name": "local_ai_repo",
            "description": "Primary bounded repository worker; use deterministic/indexed evidence first, then semantic/graph as enabled." + _repo_review_guidance(repo_actions) + context_pack_guidance() + repo_semantic_contract + _actions_note(repo_actions),
            "parameters": operation_parameters_schema("local_ai_repo", fs),
        }

    if operation_enabled(fs, "local_ai_task"):
        task_actions = fs.supported_task_actions()
        schemas["local_ai_task"] = {
            "name": "local_ai_task",
            "description": f"Tiered bounded local-model operations using {fs.fast_model} for quick work, {fs.general_model} for ordinary work, {fs.smart_model} for involved work, and {reasoning_tier} for hardest work; use deterministic/indexed tools for exact facts, symbols, diff and tests. {_semantic_handoff_contract(fs)}" + _actions_note(task_actions),
            "parameters": operation_parameters_schema("local_ai_task", fs),
        }

    if operation_enabled(fs, "local_ai_rag"):
        rag_actions = fs.supported_rag_actions()
        schemas["local_ai_rag"] = {
            "name": "local_ai_rag",
            "description": "Fallback semantic retrieval after indexed evidence is insufficient; project search/index and ingestion require an explicit absolute authorized root with a root-bound workspace. Diagram paths stay inside that root. Managed docsets use a separate owner-global namespace and require an explicit workspace name for indexing and search; docset_index also requires root." + _actions_note(rag_actions),
            "parameters": operation_parameters_schema("local_ai_rag", fs),
        }


    if operation_enabled(fs, "local_ai_coord"):
        coord_actions = fs.supported_coord_actions()
        coord_description = "Coordination and leases."
        if fs.agent_os:
            coord_description += " For non-trivial multi-step, long-running, delegated, or acceptance-criteria work, create an Agent OS task, checkpoint progress, compile context when needed, call `verify_completion`, then `task_complete` only when receipts satisfy every criterion. Enabled families include task lifecycle, scoped memory/relations, context, verification, negative knowledge/incidents, blackboard, swarm, worktree leases, pub/sub, merge simulation, and dataset curation."
        coord_description += _actions_note(coord_actions)
        schemas["local_ai_coord"] = {
            "name": "local_ai_coord",
            "description": coord_description,
            "parameters": operation_parameters_schema("local_ai_coord", fs),
        }

    if operation_enabled(fs, "local_ai_work"):
        schemas["local_ai_work"] = {
            "name": "local_ai_work",
            "description": "Delegate, resume, inspect or cancel a complete bounded repository work order with compact verified handoff.",
            "parameters": operation_parameters_schema("local_ai_work", fs),
        }

    artifact_contract = operation_contract("local_ai_artifact")
    if operation_enabled(fs, "local_ai_artifact") and artifact_contract is not None:
        artifact_actions = fs.supported_artifact_actions()
        schemas["local_ai_artifact"] = {
            "name": "local_ai_artifact",
            "description": artifact_contract["description"].format(actions=", ".join(artifact_actions)),
            "parameters": operation_parameters_schema("local_ai_artifact", fs),
            "x-operation-contract": operation_metadata("local_ai_artifact"),
        }

    for tool_name, schema in schemas.items():
        if operation_contract(tool_name) is not None:
            # Tool properties, selectors, requirements, and shared response fields live in one registry.
            schema["parameters"] = operation_parameters_schema(tool_name, fs)
            schema["x-operation-contract"] = operation_metadata(tool_name)

    _apply_response_budget_schema(schemas, cfg)
    return schemas




def generate_antigravity_instructions(cfg: dict[str, Any] | None = None) -> str:
    """Generate high-priority instructions for Gemini / Antigravity MCP directory."""
    fs = FeatureSet.from_config(cfg or {})
    repo_actions = [action for action in ("search", "code_index", "context", "solve") if action in fs.supported_repo_actions()]
    task_actions = list(_available_semantic_task_actions(fs))
    active_tool_actions = _active_tool_action_lines(fs)
    categorized_triggers = _categorized_operational_triggers(fs)
    lines = [
        "# Local AI Hub MCP Instructions for Antigravity & Gemini",
        "",
        "Use local-ai tools for operations supported by the live MCP schema; use native tools when no matching Hub action exists:",
        "- **Run commands, tests, lint, builds**: Use the agent host native command tool for bounded checks in the target repository.",
        "- **Unsupported operation**: If the live MCP schema has no action for the requested operation, skip Hub and use the authorized native tool directly (for example, `git worktree list`). Do not call Hub or wait for a Hub failure signal.",
        "- **Advertised action failure**: After calling a Hub action exposed by the live schema, use native fallback only when the result has `terminal=true` and `retryable=false`.",
    ]
    if repo_actions:
        lines.append(f"- **Search code & repository facts**: Call an advertised local_ai_repo action ({'|'.join(repo_actions)}) with the project root. Avoid unconstrained directory dumping.")
    if task_actions:
        lines.append(f"- **Semantic code review & second opinions**: Call exposed local_ai_task actions ({'|'.join(task_actions)}).")
    if categorized_triggers:
        lines.extend(["", *categorized_triggers])
    if active_tool_actions:
        lines.extend(["", "## Active MCP tools and profile-enabled actions", *active_tool_actions,
                      "", "This generated list reflects configuration and profile feature gates. Runtime authorization, task permissions, backend health, and quality gates are checked when an action runs."])
    if fs.agent_os or fs.coord:
        lines.append("- **Agent OS Lifecycle & durable memory**: Call local_ai_coord task, checkpoint and memory actions available in the current schema.")
    if fs.artifacts:
        lines.append("- **Exact file slices & artifacts**: Call local_ai_artifact actions available in the current schema.")
    lines.extend([
        "",
        "When calling via call_mcp_tool (if tools are lazily loaded):",
        '- ServerName: "local-ai"',
        "- ToolName: exact tool name (e.g. local_ai_repo)",
        '- Arguments: parameter dictionary (e.g. {"action": "search", "query": "symbol", "root": "/absolute/project"})',
    ])
    return "\n".join(lines) + "\n"

def write_all_generated(
    cfg: dict[str, Any],
    target_root: Path | str,
    hub_python: Path | None = None,
    serena: Path | None = None,
) -> dict[str, list[str]]:
    """Generate all skill, instruction, MCP manifest, and schema files into target_root."""
    target_root = Path(target_root).resolve()
    python_bin = hub_python or Path(target_root / ".venv" / ("Scripts/python.exe" if Path(target_root / ".venv" / "Scripts").exists() else "bin/python"))

    results: dict[str, list[str]] = {
        "skill": [],
        "instructions": [],
        "mcp": [],
        "schemas": [],
    }

    # 1. Skill & References
    skill_dir = target_root / "skills" / "local-ai-orchestrator"
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(generate_skill_markdown(cfg).rstrip() + "\n", encoding="utf-8")
    results["skill"].append(str(skill_path))

    refs_dir = skill_dir / "references"
    refs_dir.mkdir(parents=True, exist_ok=True)
    references = generate_skill_references(cfg)
    for ref_name, ref_content in references.items():
        ref_path = refs_dir / ref_name
        ref_path.write_text(ref_content, encoding="utf-8")
        results["skill"].append(str(ref_path))

    tok_skill_dir = target_root / "skills" / "token-economizer"
    tok_skill_dir.mkdir(parents=True, exist_ok=True)
    tok_skill_path = tok_skill_dir / "SKILL.md"
    tok_skill_path.write_text(TOKEN_ECONOMIZER_SKILL_MD, encoding="utf-8")
    results["skill"].append(str(tok_skill_path))

    # 2. Generated agent policy
    gen_dir = target_root / "generated"
    gen_dir.mkdir(parents=True, exist_ok=True)
    p1 = generate_global_policy(cfg)
    p2 = generate_token_economy_policy(cfg)
    total_rule_bytes = len((p1 + "\n\n" + p2).encode("utf-8"))
    if total_rule_bytes > 23900:
        raise ValueError(
            f"Generated policies exceed Antigravity 24KB rule cap ({total_rule_bytes} > 23,900 bytes). "
            "Antigravity will silently truncate rule files larger than 24,000 bytes. Condense policy text."
        )

    policy_path = gen_dir / "agent-policy.md"
    policy_path.write_text(p1 + "\n", encoding="utf-8")
    results["instructions"].append(str(policy_path))

    tok_policy_path = gen_dir / "token-economy-policy.md"
    tok_policy_path.write_text(p2 + "\n", encoding="utf-8")
    results["instructions"].append(str(tok_policy_path))

    # 3. Generated MCP manifests
    generic_mcp = generate_mcp_configs(cfg, target_root, python_bin, serena, "generic")
    vscode_mcp = generate_mcp_configs(cfg, target_root, python_bin, serena, "copilot")
    mcp_servers_path = gen_dir / "mcp-servers.json"
    mcp_servers_path.write_text(json_dumps({"mcpServers": generic_mcp}) + "\n", encoding="utf-8")
    results["mcp"].append(str(mcp_servers_path))

    vscode_mcp_path = gen_dir / "vscode-mcp.json"
    vscode_mcp_path.write_text(json_dumps({"servers": {k: {"type": "stdio", **v} for k, v in vscode_mcp.items()}}) + "\n", encoding="utf-8")
    results["mcp"].append(str(vscode_mcp_path))

    # 4. Generated JSON tool schemas
    schemas_dir = gen_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    # Clean old schemas first
    for old_file in schemas_dir.glob("*.json"):
        try:
            old_file.unlink()
        except OSError:
            pass
    tool_schemas = generate_mcp_tool_schemas(cfg)
    for tool_name, schema in tool_schemas.items():
        tool_file = schemas_dir / f"{tool_name}.json"
        tool_file.write_text(json_dumps(schema) + "\n", encoding="utf-8")
        results["schemas"].append(str(tool_file))

    # 5. Generated Antigravity MCP instructions
    instructions_path = gen_dir / "instructions.md"
    instructions_path.write_text(generate_antigravity_instructions(cfg) + "\n", encoding="utf-8")
    results["instructions"].append(str(instructions_path))

    return results


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys
    from local_ai_hub.config import load_config

    parser = argparse.ArgumentParser(
        prog="python -m local_ai_hub.generator",
        description="Generate dynamic skill, instruction policies, and MCP schemas based on configuration.",
    )
    parser.add_argument(
        "--config",
        default=os.environ.get("LOCAL_AI_CONFIG"),
        help="Path to config.toml. Defaults to standard discovery.",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        default=".",
        help="Directory to write generated artifacts to (default: current directory).",
    )
    parser.add_argument(
        "--python-bin",
        default=None,
        help="Python binary path for MCP server configuration (default: sys.executable).",
    )
    parser.add_argument(
        "--sync-agents",
        action="store_true",
        help="Also configure and sync all discovered agent configurations and MultiGravity profiles.",
    )
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    target = Path(args.output_dir).resolve()
    py_bin = Path(args.python_bin) if args.python_bin else Path(sys.executable)
    res = write_all_generated(cfg, target, py_bin)
    if args.sync_agents:
        try:
            import importlib.util
            setup_path = target / "tools" / "setup.py"
            if not setup_path.exists():
                setup_path = Path(__file__).resolve().parents[2] / "tools" / "setup.py"
            if setup_path.exists():
                spec = importlib.util.spec_from_file_location("_tools_setup", setup_path)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    mod.configure_agents(target, py_bin, None, cfg)
                    res["agents_synced"] = True
        except Exception as exc:
            res["agents_synced_error"] = str(exc)
    output_json = json_dumps({"success": True, "target": str(target), "generated": res}, indent=2, ensure_ascii=False)
    logging.getLogger(__name__).info("Generation complete for %s", target)
    sys.stdout.write(output_json + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
