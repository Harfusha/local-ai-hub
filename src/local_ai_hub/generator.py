"""generator.py — Dynamic skill, instruction, and MCP artifact generator.

Inspects the active configuration via FeatureSet and generates:
1. Dynamic SKILL.md and reference docs containing only active tools, actions, and models.
2. Dynamic agent instruction policies (for AGENTS.md, CLAUDE.md, GEMINI.md).
3. Dynamic MCP manifests (mcp-servers.json, vscode-mcp.json) and tool JSON schemas.
"""
from __future__ import annotations

from .json_utils import dumps as json_dumps

import json
import os
from pathlib import Path
from typing import Any

from local_ai_hub.features import FeatureSet


def _reasoning_tier_label(cfg: dict[str, Any], fs: FeatureSet) -> str:
    models = cfg.get("models", {})
    if isinstance(models, dict) and "reasoning" in models:
        return f"`{fs.reasoning_model}`"
    return "the configured hardest-reasoning tier"


def _actions_note(actions: list[str]) -> str:
    """Keep generated tool descriptions aligned with each active action enum."""
    return f" Supported actions: {', '.join(actions)}." if actions else " No actions are enabled."


def context_economy_contract(cfg: dict[str, Any] | None = None) -> str:
    """Single short contract shared by skills, policies, and routing references."""
    features = FeatureSet.from_config(cfg or {})
    budget = 1200
    try:
        section = (cfg or {}).get("mcp", {}).get("response_budget", {})
        budget = int(section.get("default_tokens", budget)) if isinstance(section, dict) else budget
    except (TypeError, ValueError, AttributeError):
        pass
    batch_line = '- Use the existing `local_ai_task(action="batch")` for independent local tasks; keep each item bounded and consume compact per-item results.' if features.tasks else ''
    return f"""## Context economy contract

- Every Hub response is aggregate-bounded (default ≈{budget} tokens); use `max_response_tokens` only when a different bounded size is needed.
- Prefer `response_profile=\"minimal\"`/`\"compact\"`; request only decision-grade fields.
- Pass a stable `reuse_key` for repeated logical queries. Use `response_profile="delta"` when only changes are needed; unchanged calls return a pointer, not missing data.
{batch_line}
- The Hub keeps a bounded metadata-only context ledger; inspect it only with an explicit cache/status request, never by replaying the whole session.
- Broad native shell reads are guarded by the optional host hook; use bounded limits or the Hub command/repository tools for discovery.
- Fetch exact source, logs, or evidence only with `local_ai_artifact` slices. Never ask a broad tool for the same payload twice.
- Commands return status, summary, changed paths, and failures; full stdout/stderr stays artifact-backed.
- Do not bypass the budget with native broad reads unless Hub has one bounded terminal failure."""


def generate_skill_markdown(cfg: dict[str, Any]) -> str:
    """Generate a dynamic SKILL.md reflecting only enabled tools and models."""
    fs = FeatureSet.from_config(cfg)
    reasoning_tier = _reasoning_tier_label(cfg, fs)

    trigger_lines = "\n".join(fs.trigger_map_lines()) if fs.trigger_map_lines() else "- (all Hub tools currently disabled in configuration)"
    recipe_lines = "\n".join(fs.recipe_lines())

    # Delegation section
    if fs.tasks and fs.has_any_model():
        delegation_task = (
            f"- Use `local_ai_task` for bounded semantic generation, reasoning, review, independent second opinions, and semantic compression."
            f" Use `{fs.fast_model}` only for quick/simple requests, `{fs.general_model}` for ordinary tasks,"
            f" `{fs.smart_model}` for more involved work, and {reasoning_tier} for the hardest reasoning."
            " Deterministic/indexed tools remain for exact facts, symbols, diff and tests; they do not replace these semantic tasks."
        )
    else:
        delegation_task = (
            "- Local model inference is disabled in this configuration. "
            "Use cloud/native agent reasoning; Local AI Hub operates in deterministic/indexed mode only."
        )

    work_delegation = ""
    if fs.work_orchestrator:
        work_delegation = (
            '- **Closed whole task:** prefer `local_ai_work(action="submit")` when the Hub can own planning, bounded edits, '
            'validation and handoff end-to-end. Use `response_profile="compact"` and request only decision-grade fields; '
            'fetch the artifact only when details are needed.'
        )
    work_owner_note = (
        "A submitted `local_ai_work` order may own its bounded internal planning, edits, validation and integration until handoff."
        if fs.work_orchestrator
        else "The main agent owns planning, edits, validation and final integration."
    )
    # Ownership & tiering bullets
    tiering_bullets: list[str] = [
        "- **Local AI Hub first:** its own precise bounded microtasks, repository facts, indexed search,"
        + (" preprocess," if fs.preprocessing else "")
        + " impact, diff/security review"
        + (", safe commands" if fs.commands else "")
        + (", compression, local-model synthesis and second opinions." if (fs.tasks and fs.has_any_model()) else " and targeted checks."),
        "- **Native Codex subagents:** use only for useful independent bounded work; Codex assigns scope, write permission, workspace/worktree, timeout, sandbox, cancellation and integration.",
    ]
    if fs.tasks and fs.has_any_model():
        model_config = cfg.get("models", {}) if isinstance(cfg.get("models", {}), dict) else {}
        reasoning_tier = f"`{fs.reasoning_model}`" if "reasoning" in model_config else "the configured hardest-reasoning tier"
        tiering_bullets.append(
            f"- **Tiered local models:** `{fs.background_model}` for preprocessing, `{fs.fast_model}` for quick/simple requests, "
            f"`{fs.general_model}` for ordinary tasks, `{fs.smart_model}` for more involved work, and {reasoning_tier} for the hardest or highest-risk reasoning. "
            "Run deterministic/indexed Hub actions first for exact facts, symbols, diff and tests. Use `local_ai_task` for semantic generation, reasoning, review, independent second opinions and semantic compression."
        )
    if fs.rag:
        tiering_bullets.append(
            "- **RAG:** use only when deterministic/indexed evidence is insufficient for a bounded retrieval question. Do not invoke a model to restate facts already available from the hub."
        )
    tiering_section = "\n".join(tiering_bullets)

    # Read-only audit contract
    if fs.commands:
        audit_fallback = (
            "- Native validation fallback is allowed only after `local_ai_command` returns `terminal=true` and `retryable=false`; "
            "run one bounded fallback, state side effects/owner, and never repeat identical commands."
        )
    else:
        audit_fallback = (
            "- Validate changes with bounded native test/lint commands; never repeat identical failing commands."
        )

    # Mandatory repo gate
    repo_gate_lines: list[str] = ["1. Establish one stable **absolute** project root."]
    step_num = 2
    if fs.preprocessing:
        repo_gate_lines.append(
            f"{step_num}. On the first task for that root call `local_ai_repo(action=\"preprocess\", root=ABS_ROOT)` **exactly once**. "
            "Continue immediately; never poll, wait, refresh or force preprocessing."
        )
        step_num += 1

    if fs.commands:
        repo_gate_lines.append(
            f"{step_num}. `local_ai_command` alone is never sufficient for a repository task: "
            "first use the cheapest applicable non-command Hub action, then use the command broker only for commands. "
            'For implementation, diagnosis, refactoring or complex review, call `local_ai_repo(action="solve")` after evidence and before native edits. '
            "After edits, run the applicable indexed impact/review/security/evidence check before final validation."
        )
        step_num += 1
    elif fs.repo:
        repo_gate_lines.append(
            f'{step_num}. For implementation, diagnosis, refactoring or complex review, call `local_ai_repo(action="solve")` after evidence and before native edits. '
            "After edits, run the applicable indexed impact/review/security/evidence check before final validation."
        )
        step_num += 1

    coord_memo_hint = " and coordination memos" if fs.coord else ""
    command_result_hint = ", command results" if fs.commands else ""
    repo_gate_lines.append(
        f"{step_num}. Use the cheapest sufficient action and reuse evidence IDs, artifact slices{command_result_hint}{coord_memo_hint}."
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
            routing_lines.append(f'{r_idx}. `local_ai_repo(action="{fs.semantic_hint()}")` — language-aware relationships via Serena/CodeGraphContext, callers/callees and impact.')
            r_idx += 1
        routing_lines.append(f'{r_idx}. `local_ai_repo(action="context"|"solve")` — compact mixed evidence or bounded repository reasoning.')
        r_idx += 1
        routing_lines.append(f'{r_idx}. `local_ai_repo(action="review_diff"|"security_audit"|"impact")` — targeted checks after or around edits.')
        r_idx += 1
    if fs.work_orchestrator:
        routing_lines.append(f'{r_idx}. `local_ai_work(action="submit")` — delegate one complete bounded repository task; Hub plans a DAG, edits transactionally, validates, verifies, and returns a compact handoff.')
        r_idx += 1
    if fs.rag:
        routing_lines.append(f'{r_idx}. `local_ai_rag` — semantic fallback only when indexed evidence is insufficient.')
        r_idx += 1
    if fs.tasks and fs.has_any_model():
        routing_lines.append(f'{r_idx}. `local_ai_task(action="delegate"|"explore"|"reason"|"review"|"second_opinion"|"compress")` — semantic generation, exploration, reasoning, review, independent second opinions and compression. Use `{fs.fast_model}` only for quick/simple requests, `{fs.general_model}` for ordinary tasks, `{fs.smart_model}` for more involved work, and {reasoning_tier} for the hardest reasoning. Deterministic/indexed tools remain for exact facts, symbols, diff and tests.')
        r_idx += 1
    if fs.commands:
        routing_lines.append(f'{r_idx}. `local_ai_command(action="run")` — tests, lint, typecheck, builds and repeatable read-only commands before native execution.')
        r_idx += 1
    if fs.artifacts:
        routing_lines.append(f'{r_idx}. `local_ai_artifact` — exact evidence/artifact slices only.')
        r_idx += 1
    if fs.coord:
        routing_lines.append(f'{r_idx}. `local_ai_coord` — leases before overlapping edits; memos before repeating investigation.')
        r_idx += 1
    routing_section = "\n".join(routing_lines) if routing_lines else "*(No actions available: all tools disabled)*"

    # Advisory subagents section
    subagents_section = ""
    if fs.subagents and fs.has_any_model():
        profiles_list = "\n".join(f"- `{p}` — configured advisory profile" for p in fs.subagent_profiles)
        example_profile = fs.subagent_profiles[0] if fs.subagent_profiles else "explorer"
        subagents_section = f"""
## Ollama advisory subagents

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
            '- **Run validation commands with automatic receipt capture:**\n'
            '  `local_ai_command(action="run", command="pytest -q", task_id="task-1", criterion="All tests pass")`'
            if fs.commands else
            '- **Record verification receipt directly after native test run:**\n'
            '  `local_ai_repo(action="verify_receipt", receipt={"task_id": "task-1", "criterion": "All tests pass", "passed": True})`'
        )
        agent_os_section = f"""
## Agent Operating System & Durable Execution

Use Agent OS for every non-trivial multi-step, long-running, delegated, or acceptance-criteria task, even when the main agent keeps ownership. A trivial one-step lookup can skip it. Start before edits; keep the returned `task_id` for every later action.

### 1. Goal Contracts & Resumption
- **Create a task contract before edits:**
  `local_ai_coord(action="task_create", task_id="task-1", contract={{"goal": "Implement feature", "acceptance_criteria": ["All tests pass"]}})`
- **Checkpoint progress before context truncation:**
  `local_ai_coord(action="task_checkpoint", task_id="task-1", checkpoint={{"phase": "testing", "next_action": "run integration tests", "affected_paths": ["src/main.py"]}})`
- **Resume after session restart or interruption:**
  `local_ai_coord(action="task_resume", task_id="task-1")`
- **Complete only after `verify_completion` passes every acceptance criterion; otherwise fail with a reason:**
  `local_ai_coord(action="verify_completion", task_id="task-1")`, then `local_ai_coord(action="task_complete", task_id="task-1")` or `local_ai_coord(action="task_fail", task_id="task-1", reason="reason")`

### 2. Scoped Memory & Learnings
- **Store durable findings and decisions:**
  `local_ai_coord(action="memory_record", record={{"kind": "decision", "scope": "repository", "key": "convention", "value": "Token format must follow HMAC-SHA256"}})`
- **Retrieve memories across turns:**
  `local_ai_coord(action="memory_find", query="convention")`

### 3. Exact Context Compilation
- **Compile active task state, relevant memories, negative knowledge, and active edit leases into minimal tokens:**
  `local_ai_coord(action="context_compile", task_id="task-1", max_tokens=4000)`

### 4. Verification Receipts & Completion Gates
{verification_receipt_item}
- **Check if all acceptance criteria are verified before completing:**
  `local_ai_coord(action="verify_completion", task_id="task-1")`
- **Record a direct receipt when command auto-capture is not used:**
  `local_ai_coord(action="verify_receipt", checkpoint={{"task_id": "task-1", "criterion": "All tests pass", "passed": True}})`

### 5. Negative Knowledge & Incident Avoidance
- **Record failed approach or incident:**
  `local_ai_coord(action="negative_knowledge_record", key="timeout", value="build timed out", reason="unindexed lock", status="add index")`
- **Check before repeating a failed operation:**
  `local_ai_coord(action="negative_knowledge_find", query="timeout")`
"""

    # Full SKILL.md content
    return f"""---
name: local-ai-orchestrator
description: Local-first routing for Codex, Gemini, Claude, Cursor, Windsurf, VS Code/Copilot and MCP coding agents. Keeps the main agent as orchestrator and routes bounded work through Local AI Hub.
---

# Local AI Hub routing

Trigger map:
{trigger_lines}

Recipes (guidance, not gates):
{recipe_lines}

Delegation is the default for any task with useful bounded independent work.
{delegation_task}
{work_delegation}
- Use the native Codex `multi_agent_v1__spawn_agent` path only for useful independent bounded work or an explicit Codex-subagent request.
- Codex controls each subagent's scope, `allow_write`, workspace/worktree, timeout, cancellation, sandbox, and integration.
- Do not duplicate the same scope across agents. Keep final decisions, edits, and integration in Codex.
- Skip delegation only for trivial tasks, pure evidence lookups, security/privacy constraints, or no useful independent scope.

## Ownership and tiering

    The main agent owns task boundaries, permissions, unresolved decisions and the final user answer. {work_owner_note}

{tiering_section}

## READ-ONLY AUDIT CONTRACT

- Read-only means no Git writes, `git worktree add` or removal, dependency installation, builds/imports, generated artifacts, or other workspace side effects. Never label such work read-only when any of these occur; split validation into a separately owned, explicitly side-effecting task.
- Before native discovery or validation, retain preceding Hub result with action, absolute root, status, cache/in_progress state, and evidence IDs. Native discovery is fallback-only after one bounded terminal Hub failure.
{audit_fallback}
- Codex controls subagent permissions per task. Native Codex subagents may write only when Codex explicitly enables it, and write work stays in the assigned workspace/worktree. Codex remains integrator.
- Do not run parallel duplicate commands or scopes. Tool labels are not evidence; preserve exact action, arguments, result, and ownership in the audit record.

## Mandatory repository gate

For every non-trivial repository task, use Local AI Hub before broad repository exploration unless fresh sufficient hub evidence is already present.

{repo_gate_section}

Before native `find`, `rg`, `grep`, recursive glob/tree, or opening more than two files for discovery, call the hub first. Native broad discovery is fallback-only after one bounded hub failure.

Stop escalating when evidence is sufficient; reuse cached results and bounded evidence instead of widening the search.

{context_economy_contract(cfg)}

## Action routing

{routing_section}

## Reuse and failure protocol

- `cache_hit`/`coalesced`: reuse the result.
- `in_progress=true`: do not duplicate the work.
- `retryable`/429/503: back off and do independent work.
- `degraded`/`stale`: verify only the affected slice.
- Hub unavailable: one bounded health/retry attempt, then native fallback. Never loop or inflate timeouts.

Do not fan out overlapping retrieval layers. Stop escalating when evidence is sufficient. Local AI Hub handles its own bounded work; Codex handles native-subagent design and integration.
{subagents_section}{agent_os_section}
"""


def generate_skill_references(cfg: dict[str, Any]) -> dict[str, str]:
    """Generate dynamic reference documents for skills/local-ai-orchestrator/references/."""
    fs = FeatureSet.from_config(cfg)
    reasoning_tier = _reasoning_tier_label(cfg, fs)
    work_owner_note = (
        "A submitted `local_ai_work` order may own its bounded internal planning, edits, validation and integration until handoff."
        if fs.work_orchestrator
        else "The main agent owns planning, edits, validation and final integration."
    )
    refs: dict[str, str] = {}

    # tools.md
    tool_bullets: list[str] = []
    if fs.repo:
        semantic_note = f", {fs.semantic_hint()}" if fs.has_semantic() else ""
        tool_bullets.append(f"- `local_ai_repo`: deterministic, code index/search{semantic_note}, context/solve" + (", preprocess" if fs.preprocessing else "") + ", impact, `review_diff`, `security_audit`, patch validation and repository checks.")
    if fs.commands:
        tool_bullets.append("- `local_ai_command`: cached/single-flight safe command broker for tests, lint, typecheck, builds and read-only checks; never the only Hub action for a repository task.")
    if fs.work_orchestrator:
        tool_bullets.append("- `local_ai_work`: durable whole-task orchestration with dependency planning, transactional edits, validation, whole-task verification and compact/lazy handoff.")
    if fs.tasks and fs.has_any_model():
        tool_bullets.append(f"- `local_ai_task`: tiered local-model work (`{fs.fast_model}` quick, `{fs.general_model}` ordinary, `{fs.smart_model}` more involved, {reasoning_tier} hardest) for semantic generation, reasoning, review, independent second opinions and semantic compression; use deterministic/indexed tools for exact facts, symbols, diff and tests. `local_ai_repo(action=\"solve\")` preserves one bounded local pass for explicit semantic requests even when exact evidence is strong.")
    if fs.rag:
        tool_bullets.append("- `local_ai_rag`: semantic fallback only after deterministic/indexed retrieval.")
    if fs.artifacts:
        tool_bullets.append("- `local_ai_artifact`: exact `E...` evidence or artifact slices.")
    if fs.coord:
        tool_bullets.append("- `local_ai_coord`: edit leases and reusable investigation memos" + (", Agent OS task lifecycle, scoped memory/relations, context, verification, negative knowledge, and coordination primitives" if fs.agent_os else "") + ".")
    if fs.status:
        status_detail_note = ", Agent OS task/incident state" if fs.agent_os else ""
        tool_bullets.append(f"- `local_ai_status`: bounded health/cache/telemetry{status_detail_note} inspection; no polling loops.")

    tool_lines = "\n".join(tool_bullets) if tool_bullets else "- *(All tools disabled)*"
    agent_os_reference = ""
    if fs.agent_os:
        agent_os_reference = """
## Agent OS trigger and lifecycle

Use this for non-trivial multi-step, long-running, delegated, or acceptance-criteria work, even when the main agent retains ownership. Create a task contract before edits, keep the returned task ID, checkpoint phase changes, compile context when resuming or when state is scattered, and attach validation receipts. Run `verify_completion` before `task_complete`. Trivial one-step lookups can skip this workflow.
"""

    refs["tools.md"] = f"""# MCP routing card

The active tool surface reflects your configuration:

{tool_lines}

{agent_os_reference}

{context_economy_contract(cfg)}

    Keep assignments bounded. The main agent retains final acceptance; {work_owner_note}
"""

    # workflows.md
    wf_steps: list[str] = []
    step_i = 1
    if fs.repo:
        wf_steps.append(f"{step_i}. Establish the absolute root" + ("; preprocess once." if fs.preprocessing else "."))
        step_i += 1
        wf_steps.append(f"{step_i}. Retrieve deterministic facts, then code-index/search evidence.")
        step_i += 1
        wf_steps.append(f"{step_i}. Use `context` for compact evidence; call `solve` after evidence for repository implementation support. Explicit semantic wording keeps one bounded local pass; use `local_ai_task` directly for semantic generation, exploration, reasoning, review, independent second opinions or semantic compression.")
        step_i += 1
        lease_note = "claim `local_ai_coord` leases for overlapping paths; " if fs.coord else ""
        wf_steps.append(f"{step_i}. Edit in the main agent; {lease_note}use `impact` before risky dependent changes.")
        step_i += 1
    if fs.commands:
        wf_steps.append(f"{step_i}. Validate with `local_ai_command`; review with `review_diff` or `security_audit` when relevant.")
    else:
        wf_steps.append(f"{step_i}. Validate natively; review with `review_diff` or `security_audit` when relevant.")

    wf_lines = "\n".join(wf_steps)
    task_notes = ""
    if fs.tasks and fs.has_any_model():
        task_notes = """
## Local semantic work

Use `local_ai_task(action="delegate")` for bounded creation or implementation guidance, `local_ai_task(action="explore")` for semantic exploration, `local_ai_task(action="reason")` for reasoning, `local_ai_task(action="review")` for a semantic review, `local_ai_task(action="second_opinion")` for independent critique, and `local_ai_task(action="compress")` for semantic condensation. Use `local_ai_repo`, `local_ai_artifact` and `local_ai_command` for exact facts, symbols, diff and tests; those deterministic paths do not replace the semantic worker.

## Local second opinion

Use `local_ai_task(action="second_opinion")` for a bounded candidate decision. Include the evidence and uncertainty.

## Long output and failures

Use `local_ai_task(action="compress")` for semantic condensation and `local_ai_artifact` for exact lines. Reuse cache/coalesced results, do not duplicate `in_progress` work, and make one bounded fallback when the hub is unavailable.
"""
    whole_task = ""
    if fs.work_orchestrator:
        whole_task = """
## Whole-task handoff

Use `local_ai_work(action="submit", root=ABS_ROOT, task="...", response_profile="compact")` when the task is closed, bounded and independently verifiable. The Hub collects deterministic context, plans dependency-ordered steps, leases edited paths, journals mutations, validates each relevant phase, performs whole-task verification against the original request and returns only a compact handoff. Use `work_get` fields/artifacts lazily for details.

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
    refs["multi-agent.md"] = f"""# Multi-agent coordination

{multi_agent_desc}. External cloud agents (Codex, Claude, Gemini, Cursor, Copilot) remain the principal orchestrators.
{agent_os_multi_agent_note}

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
    reasoning_tier = _reasoning_tier_label(cfg, fs)

    trigger_lines = "\n".join(fs.trigger_map_lines()) if fs.trigger_map_lines() else "- (all Hub tools currently disabled)"
    recipe_lines = "\n".join(fs.recipe_lines())

    task_delegation = ""
    if fs.tasks and fs.has_any_model():
        task_delegation = (
            f"\n- Use `local_ai_task` for bounded semantic generation, reasoning, review, independent second opinions, and semantic compression."
            f" Use `{fs.fast_model}` only for quick/simple requests, `{fs.general_model}` for ordinary tasks,"
            f" `{fs.smart_model}` for more involved work, and {reasoning_tier} for the hardest reasoning."
            " Deterministic/indexed tools remain for exact facts, symbols, diff and tests; they do not replace these semantic tasks."
        )

    model_default = ""
    if fs.tasks and fs.has_any_model():
        model_default = (
            f"\nLocal model policy: `{fs.background_model}` is preprocessing-only, `{fs.fast_model}` handles quick/simple tasks,"
            f" `{fs.general_model}` handles ordinary tasks, `{fs.smart_model}` handles more involved work, and {reasoning_tier} handles the hardest or highest-risk reasoning."
            " Use deterministic and indexed Hub actions first for exact facts, symbols, diff and tests. For semantic generation, reasoning, review, independent second opinions and semantic compression, call `local_ai_task`."
        )

    repo_task_first = ""
    if fs.repo:
        prep_call = ' On the first task for that root call `local_ai_repo(action="preprocess", root=ABS_ROOT)` exactly once, then continue immediately; preprocessing is asynchronous, so never poll/wait/force-refresh it.' if fs.preprocessing else ""
        cmd_gate = ' `local_ai_command` alone is never sufficient for a repository task. The first useful Hub operation must be `local_ai_repo` (preprocess plus the cheapest applicable deterministic/code-index/search/context action); use the command broker only for commands, after repository evidence exists.' if fs.commands else ""
        repo_task_first = (
            "\nFor every non-trivial repository task, use Local AI Hub before broad native discovery or repeatable validation."
            f" Keep one stable absolute project root.{prep_call}\n"
            f"\nAdoption gate:{cmd_gate}"
            ' For implementation, diagnosis, refactoring or complex review, call `local_ai_repo(action="solve")` after evidence'
            " and before native edits. After edits, use the applicable indexed impact/review/security/evidence action before final validation.\n"
        )

    cmd_route_hint = ""
    if fs.commands:
        cmd_route_hint = (
            "\nRoute test/lint/typecheck/build/read-only commands through `local_ai_command` before running them natively."
            " If it returns `in_progress=true`, do not launch a duplicate command."
        )

    coord_memo_hint = ""
    if fs.coord:
        coord_memo_hint = (
            " Before an expensive `solve`/model call, search coordination memos for reusable findings."
            " For overlapping multi-agent edits use `local_ai_coord` leases and store concise reusable discoveries as memos."
        )

    return (
        "<!-- BEGIN LOCAL AI HUB TOOL POLICY -->\n"
        f"Trigger map:\n{trigger_lines}\n\n"
        f"Recipes (guidance, not gates):\n{recipe_lines}\n\n"
        "Delegation is the default for any task with useful bounded independent work.\n"
        f"{task_delegation}\n"
        "- Use the native Codex `multi_agent_v1__spawn_agent` path only for useful independent bounded work or an explicit Codex-subagent request.\n"
        "- Codex controls each subagent's scope, `allow_write`, workspace/worktree, timeout, cancellation, sandbox, and integration.\n"
        "- Do not duplicate the same scope across agents. Keep final decisions, edits, and integration in Codex.\n"
        "- Skip delegation only for trivial tasks, pure evidence lookups, security/privacy constraints, or no useful independent scope.\n\n"
        "Routing hierarchy: the main agent is the orchestrator, planner, integrator and final owner."
        " Use Local AI Hub first for its own precise, bounded microtasks: deterministic facts, indexed/search retrieval,"
        + (" preprocess artifacts," if fs.preprocessing else "")
        + " targeted impact/review/security checks"
        + (", safe commands" if fs.commands else "")
        + (", compression, local-model synthesis and second opinions." if (fs.tasks and fs.has_any_model()) else " and targeted checks.")
        + " Native `multi_agent_v1__spawn_agent` is used only for useful independent bounded work"
        " or an explicit Codex-subagent request. It is not routed or managed by Local AI Hub.\n\n"
        "READ-ONLY AUDIT CONTRACT:\n"
        "- Read-only means no Git writes, `git worktree add` or removal, dependency installation, builds/imports,"
        " generated artifacts, or other workspace side effects. Never label such work read-only when any of these occur;"
        " split validation into a separately owned, explicitly side-effecting task.\n"
        "- Before native discovery or validation, retain preceding Hub result with action, absolute root, status,"
        " cache/in_progress state, and evidence IDs. Native discovery is fallback-only after one bounded terminal Hub failure.\n"
        + ("- Native validation fallback is allowed only after `local_ai_command` returns `terminal=true` and `retryable=false`; run one bounded fallback, state side effects/owner, and never repeat identical commands.\n" if fs.commands else "")
        + "- Codex controls subagent permissions per task. Native Codex subagents may write only when Codex explicitly"
        " enables it, and write work stays in the assigned workspace/worktree. Codex remains integrator.\n"
        "- Do not run parallel duplicate commands or scopes. Tool labels are not evidence;"
        " preserve exact action, arguments, result, and ownership in the audit record.\n"
        f"{repo_task_first}\n"
        f"Cheapest path: {fs.cheapest_path_hint()}.\n"
        " Stop escalating as soon as a cheaper layer provides enough evidence."
        " Do not fan out overlapping retrieval layers in parallel for the same question."
        " Before native `find`/`rg`/`grep`/recursive glob/tree or opening more than two files for discovery, use that hub path first."
        " Reuse fresh evidence IDs, artifact slices, memos and cache hits;\n"
        " do not repeat the same hub action with the same root/query while repository state is unchanged.\n\n"
        "Treat result state as a protocol: `cache_hit`/`coalesced` means reuse the result;"
        " `in_progress=true` means another owner is doing identical work, so never duplicate it;"
        " `retryable`/429/503 means back off and do independent work;"
        " `degraded`/`stale` means verify only the affected path/slice;"
        " a non-retryable failure permits one cheaper/native fallback."
        " Never turn a transient result into larger timeouts, force refreshes, or polling loops.\n"
        f"{cmd_route_hint}{coord_memo_hint}\n"
        " After edits, use indexed impact/review plus targeted cached validation;"
        " do not rerun broad discovery merely because files changed."
        " `force` and `preprocess_refresh` are recovery/admin controls, never retry buttons."
        " If an optional backend degrades, accept the hub's deterministic/index fallback."
        " If the hub itself is unavailable, make one bounded health/retry attempt, then fall back to native tools."
        " Never loop on health, status, preprocessing, model startup, a failing backend, or an identical command.\n\n"
        + ("Batch repository replacement: use `local_ai_repo(action=\"batch_replace\", edits=[...], dry_run=true)` for preview. "
           "`staged` is not batch dry-run and is never forwarded. Each edit must exact-match once. "
           "The engine preflights all edits, rolls back write failures, and performs no auto-commit. "
           "Set `dry_run=false` only after review.\n\n" if fs.repo and fs.batch_replacement else "")
        + f"{fs.selection_guide()}\n"
        f"{model_default}\n"
        f"{context_economy_contract(cfg)}\n"
        "<!-- END LOCAL AI HUB TOOL POLICY -->"
    )


TOKEN_ECONOMIZER_SKILL_MD = """---
name: token-economizer
description: Use when starting any coding or repository task involving source discovery, file reading, tests, command output, or code review.
---

# Token Economizer

Load and follow this skill before any coding or repository task. Apply its discovery, reading, and output limits even when a task is urgent; use the token-economy tools whenever they are available.

## Available Token-Saving Tooling

1. **`tokcount <path|stdin>`**:
   - Computes exact token count (o200k/Astra, cl100k/Codex) for any file, folder, or pipe.
   - Example: `tokcount src/` or `git diff | tokcount`

2. **`trim-run [-n 40] <command>` / `cmd | trim-run`**:
   - Safe output wrapper: allows bundled `tokcount`/`repo-map` and read-only `rg`/`fd`/`grep-ast` commands; it also trims stdin pipelines. It never runs arbitrary shell commands.
   - Example: `repo-map . | trim-run -n 40` or `git log | trim-run`

3. **`repo-map [dir] [-n 200]`**:
   - Generates high-density AST skeleton (classes, methods, signatures) of the whole repo using Tree-sitter / grep-ast without reading file bodies.

4. **`grep-ast <pattern> <file>`**:
   - AST-aware search: returns matching lines with parent class/function scope instead of dumping the file.

5. **`ast-grep scan --pattern '<pattern>'` (or `sg`)**:
   - Fast structural AST search across codebase without loading files into context.

6. **`repomix --compress --output <file>`**:
   - Packs repo with comment stripping, blank line removal, Tree-sitter compression, and token counts.

7. **`files-to-prompt -c <paths...>`**:
   - Formats selected files into structured LLM XML without shell overhead.

8. **`local_ai_artifact(action="slice")`**:
   - Fetches exact slice of a file (e.g. lines 120-160) without reading entire file.

9. **`local_ai_command`**:
   - Bounded command runner with automatic ANSI stripping and failure compression.

10. **`rg` (`ripgrep`)**:
    - Fast regex code search: always bound matches with `-m <N>` or `--max-columns <N>` to avoid context floods.

11. **`fd` (`fd-find`)**:
    - Fast file/dir discovery: use `fd <pattern> -d <depth>` instead of wide recursive trees.

12. **`jq <filter>`**:
    - Stream JSON filter: slice and project only necessary fields from API responses or command outputs (`cmd | jq '...'`).

## Rules of Engagement

### 1. Zero Full-File Dumping
- **NEVER** use `cat`, `type`, `Get-Content` or unconstrained reads on files larger than 80 lines.
- Use `repo-map` or `grep-ast` for orientation.
- Use `rg -m 5` or `fd` for bounded targeted search instead of unconstrained directory scans.
- Use targeted line ranges (`view_file` with `StartLine`/`EndLine`) or `local_ai_artifact(action="slice")`.
- Use **Serena** (`find_symbol`, `find_referencing_symbols`) or `ast-grep` before opening files.

### 2. Bounded Command & Test Outputs
- **NEVER** run verbose build/test commands raw into context.
- Route tests/builds through `local_ai_command`; use `trim-run` only with bundled `tokcount`/`repo-map`, read-only `rg`/`fd`/`grep-ast`, or to trim stdin pipelines.
- Filter large JSON outputs with `jq` to extract only relevant fields before returning to LLM.
- Use minimal test flags: `pytest -q --tb=short`, `dotnet test --verbosity quiet`.
- Use compact git commands: `git status -s`, `git diff --stat`, `git log -n 5 --oneline`.

### 3. Surgical Edits (Diffs Over Rewrites)
- Prefer single-block replacements (`replace_file_content` / targeted patches) over rewriting entire files.
- Do not recite or parrot existing file contents before or after changes.

### 4. Offload to Local Model (Ollama / Local AI Hub)
- For microtasks (summarization, lint fixing, boilerplate, second opinion), delegate to local inference:
- Use `qwen2.5-coder:1.5b` for quick local work, `qwen2.5-coder:3b` for complex tasks, and `qwen2.5-coder:7b` for the hardest reasoning; reserve `qwen2.5-coder:0.5b` for preprocessing.
  - Zero cloud tokens consumed.

### 5. Concise Output (Caveman Protocol)
- Omit conversational filler, decorative preambles, and post-execution summaries of obvious changes.
- Focus strictly on file links, diff summaries, and failure diagnostics.

### 6. MCP Response Economy
- Hub responses are aggregate-bounded; use `max_response_tokens` only for a bounded exception.
- Prefer compact/minimal profiles, stable `reuse_key` values, cache reuse, and artifact slices.
- Keep command output at summary/status level; fetch exact logs only when needed.
"""


def generate_token_economy_policy(cfg: dict[str, Any] | None = None) -> str:
    """Generate the standard TOKEN ECONOMY POLICY block."""
    fast_model = "qwen2.5-coder:1.5b"
    if cfg:
        try:
            fs = FeatureSet.from_config(cfg)
            if fs.fast_model:
                fast_model = fs.fast_model
        except Exception:
            pass
    return (
        "<!-- BEGIN TOKEN ECONOMY POLICY -->\n"
        "- Before any repository task, load and follow the `token-economizer` skill when it is installed; this trigger applies even under deadline pressure.\n"
        "- Zero full-file dumping: Never read files >80 lines in their entirety. Use `repo-map` for high-level structure, `grep-ast <pattern> <file>`, targeted line slices, or `local_ai_artifact(action=\"slice\")`.\n"
        "- Fast code search: Use `rg` (`ripgrep`) with `-m 5` / bounded matches and `fd` for file finding before opening files.\n"
        "- AST & structural code search: Use `ast-grep` (`sg`), Serena LSP (`find_symbol`, `find_referencing_symbols`), or `local_ai_repo(action=\"code_index\")` before opening files.\n"
        "- Context compression & token measurement: Use `repomix --compress` or `files-to-prompt -c` for repo snapshots. Use `tokcount` to measure exact tokens.\n"
        "- Bounded command outputs: Route tests and builds through `local_ai_command`; use `trim-run` only with bundled `tokcount`/`repo-map`, read-only `rg`/`fd`/`grep-ast`, or stdin pipelines such as `git log | trim-run`. Use `jq` for JSON.\n"
        "- Surgical edits: Prefer targeted block replacements over rewriting entire files.\n"
        f"- Local model delegation: Use `local_ai_task` for bounded semantic generation, reasoning, review, independent second opinions and compression; use `{fast_model}` only for quick/simple microtasks and configured higher tiers for ordinary, involved and hardest work. Deterministic/indexed tools remain for exact facts, symbols, diff and tests.\n"
        "<!-- END TOKEN ECONOMY POLICY -->"
    )


def generate_mcp_configs(
    cfg: dict[str, Any],
    install_dir: Path,
    hub_python: Path,
    serena: Path | None = None,
    codegraph: Path | None = None,
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
    if bool(cfg.get("code_intelligence", {}).get("direct_agent_mcp", False)):
        if serena is not None and cfg.get("code_intelligence", {}).get("serena_enabled", True):
            context = "codex" if agent == "codex" else "claude-code" if agent == "claude" else "ide-assistant"
            entries["serena"] = {"command": str(serena), "args": ["start-mcp-server", "--context", context, "--project-from-cwd", "--open-web-dashboard", "false"]}
        if codegraph is not None and cfg.get("code_intelligence", {}).get("codegraph_enabled", True):
            entries["codegraph"] = {"command": str(codegraph), "args": ["mcp", "start"]}
    return entries


def _apply_response_budget_schema(schemas: dict[str, dict[str, Any]], cfg: dict[str, Any]) -> None:
    """Add one compact response contract to every enabled public tool."""
    fields = {
        "max_response_tokens": {"type": "integer", "minimum": 0, "default": 0},
        "response_profile": {"type": "string", "enum": ["minimal", "compact", "standard", "debug", "delta"], "default": ""},
        "reuse_key": {"type": "string", "default": ""},
    }
    for schema in schemas.values():
        params = schema.setdefault("parameters", {})
        props = params.setdefault("properties", {})
        for name, spec in fields.items():
            props.setdefault(name, dict(spec))
        schema["description"] = str(schema.get("description", "")) + " Responses are aggregate-bounded; exact detail remains artifact-backed."


def generate_mcp_tool_schemas(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Generate compact JSON tool schemas for all enabled tools."""
    fs = FeatureSet.from_config(cfg)
    reasoning_tier = _reasoning_tier_label(cfg, fs)
    schemas: dict[str, dict[str, Any]] = {}

    if fs.status:
        status_description = "Health, queue, and token-saving status. detail: brief, cache, telemetry, full, agent_state."
        if fs.agent_os:
            status_description += " `agent_state` summarizes durable Agent OS task state."
        status_description += _actions_note(["brief", "cache", "telemetry", "full", "agent_state"])
        schemas["local_ai_status"] = {
            "name": "local_ai_status",
            "description": status_description,
            "parameters": {
                "type": "object",
                "properties": {
                    "detail": {"type": "string", "enum": ["brief", "cache", "telemetry", "full", "agent_state"], "default": "brief"},
                    "scope": {"type": "string", "enum": ["process", "window"], "default": "process"},
                    "extra_fields": {"type": "array", "items": {"type": "string"}},
                },
            },
        }

    if fs.repo:
        repo_actions = fs.supported_repo_actions()
        schemas["local_ai_repo"] = {
            "name": "local_ai_repo",
            "description": "Primary bounded repository worker; use deterministic/indexed evidence first, then semantic/graph as enabled; use review_diff/security_audit before model inference." + _actions_note(repo_actions),
            "parameters": {
                "type": "object",
                "required": ["action"],
                "properties": {
                    "action": {"type": "string", "enum": repo_actions},
                    "root": {"type": "string", "default": "."},
                    "query": {"type": "string", "default": ""},
                    "path": {"type": "string", "default": ""},
                    "task": {"type": "string", "default": ""},
                    "task_id": {"type": "string", "default": ""},
                    "base": {"type": "string", "default": "HEAD"},
                    "staged": {"type": "boolean", "default": False},
                    "mode": {"type": "string", "default": "adaptive"},
                    "language": {"type": "string", "default": "auto"},
                    "relation": {"type": "string", "default": ""},
                    "profile": {"type": "string", "default": ""},
                    "max_tokens": {"type": "integer", "default": 0},
                    "diff": {"type": "string", "default": ""},
                    "workspace": {"type": "string", "default": ""},
                    "evidence": {"type": "array", "items": {"type": "object"}},
                    "receipt": {"type": "object"},
                    "extra_fields": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
        if fs.batch_replacement:
            schemas["local_ai_repo"]["parameters"]["properties"].update({
                "dry_run": {"type": "boolean", "default": False},
                "edits": {"type": "array", "items": {"type": "object"}},
            })

    if fs.tasks and fs.has_any_model():
        task_actions = fs.supported_task_actions()
        schemas["local_ai_task"] = {
            "name": "local_ai_task",
            "description": f"Tiered bounded local-model work ({fs.fast_model} quick, {fs.general_model} ordinary, {fs.smart_model} more involved, {reasoning_tier} hardest) for semantic generation, reasoning, review, independent second opinions and semantic compression; use deterministic/indexed tools for exact facts, symbols, diff and tests." + _actions_note(task_actions),
            "parameters": {
                "type": "object",
                "required": ["action"],
                "properties": {
                    "action": {"type": "string", "enum": task_actions},
                    "task": {"type": "string", "default": ""},
                    "context": {"type": "string", "default": ""},
                    "root": {"type": "string", "default": ""},
                    "profile": {"type": "string", "default": ""},
                    "delivery": {"type": "string", "enum": ["sync", "async", "auto"], "default": "sync"},
                    "complexity": {"type": "string", "default": "auto"},
                    "max_tokens": {"type": "integer", "default": 0},
                    "conversation": {"type": "boolean", "default": False},
                    "conversation_id": {"type": "string", "default": ""},
                    "prompt": {"type": "string", "default": ""},
                    "model": {"type": "string", "default": ""},
                    "candidate": {"type": "string", "default": ""},
                    "image_artifact_id": {"type": "string", "default": ""},
                    "screenshot_artifact_id": {"type": "string", "default": ""},
                    "bundle_artifact_id": {"type": "string", "default": ""},
                    "dom_artifact_id": {"type": "string", "default": ""},
                    "accessibility_artifact_id": {"type": "string", "default": ""},
                    "computed_styles_artifact_id": {"type": "string", "default": ""},
                    "runtime_artifact_id": {"type": "string", "default": ""},
                    "network_artifact_id": {"type": "string", "default": ""},
                    "source": {"type": "string", "default": ""},
                    "cloud_fallback": {"type": "boolean", "default": False},
                    "dom": {"type": ["string", "object"]},
                    "accessibility": {"type": ["string", "object"]},
                    "computed_styles": {"type": ["string", "object"]},
                    "runtime": {"type": ["string", "object"]},
                    "bundle": {"type": ["string", "object"]},
                    "html": {"type": "string"},
                    "accessibility_snapshot": {"type": ["string", "object"]},
                    "computed_style_data": {"type": ["string", "object"]},
                    "runtime_context": {"type": ["string", "object"]},
                    "viewport": {"type": "object"},
                    "page": {"type": "object"},
                    "tasks": {"type": "array", "items": {"type": "object"}},
                    "latency_budget_ms": {"type": "number", "default": 0},
                    "job_action": {"type": "string", "default": "reason"},
                    "job_id": {"type": "string", "default": ""},
                    "timeout_seconds": {"type": "number", "default": 90},
                    "evaluation_task_id": {"type": "string", "default": ""},
                    "evaluation_cohort": {"type": "string", "default": ""},
                    "quality_pass": {"type": ["boolean", "null"]},
                    "test_pass": {"type": ["boolean", "null"]},
                    "evaluation_duration_ms": {"type": "number", "default": 0},
                    "evaluation_days": {"type": "integer", "default": 30},
                    "workspace": {"type": "string", "default": ""},
                    "approver": {"type": "string", "default": ""},
                    "candidate_data": {"type": "object"},
                    "format": {"type": ["string", "object"]},
                    "json_schema": {"type": "object"},
                    "extra_fields": {"type": "array", "items": {"type": "string"}},
                },
            },
        }

    if fs.rag:
        rag_actions = fs.supported_rag_actions()
        schemas["local_ai_rag"] = {
            "name": "local_ai_rag",
            "description": "Fallback semantic retrieval after indexed evidence is insufficient; also supports managed docsets and document/diagram ingestion." + _actions_note(rag_actions),
            "parameters": {
                "type": "object",
                "required": ["action"],
                "properties": {
                    "action": {"type": "string", "enum": rag_actions},
                    "query": {"type": "string", "default": ""},
                    "root": {"type": "string", "default": "."},
                    "top_k": {"type": "integer", "default": 6},
                    "workspace": {"type": "string", "default": ""},
                    "extra_fields": {"type": "array", "items": {"type": "string"}},
                },
            },
        }

    if fs.commands:
        command_actions = fs.supported_command_actions()
        schemas["local_ai_command"] = {
            "name": "local_ai_command",
            "description": "Safe CLI broker for validation and enabled repair, affected-test, format/lint-fix, mock, and replay workflows." + _actions_note(command_actions),
            "parameters": {
                "type": "object",
                "required": ["action"],
                "properties": {
                    "action": {"type": "string", "enum": command_actions},
                    "command": {"type": "string", "default": ""},
                    "cwd": {"type": "string", "default": "."},
                    "task_id": {"type": "string", "default": ""},
                    "criterion": {"type": "string", "default": ""},
                    "timeout": {"type": "integer", "default": 0},
                    "stream": {"type": "boolean", "default": False},
                    "stream_id": {"type": "string", "default": ""},
                    "force": {"type": "boolean", "default": False},
                    "auto_fix": {"type": "boolean", "default": False},
                    "max_attempts": {"type": "integer", "default": 3},
                    "snapshot": {"type": "boolean", "default": False},
                    "rollback_on_failure": {"type": "boolean", "default": False},
                    "extra_fields": {"type": "array", "items": {"type": "string"}},
                },
            },
        }

    if fs.coord:
        coord_actions = fs.supported_coord_actions()
        coord_description = "Coordination, leases, and reusable memos."
        if fs.agent_os:
            coord_description += " For non-trivial multi-step, long-running, delegated, or acceptance-criteria work, create an Agent OS task, checkpoint progress, compile context when needed, call `verify_completion`, then `task_complete` only when receipts satisfy every criterion. Enabled families include task lifecycle, scoped memory/relations, context, verification, negative knowledge/incidents, blackboard, swarm, worktree leases, pub/sub, merge simulation, and dataset curation."
        coord_description += _actions_note(coord_actions)
        schemas["local_ai_coord"] = {
            "name": "local_ai_coord",
            "description": coord_description,
            "parameters": {
                "type": "object",
                "required": ["action"],
                "properties": {
                    "action": {"type": "string", "enum": coord_actions},
                    "root": {"type": "string", "default": "."},
                    "paths": {"type": "array", "items": {"type": "string"}},
                    "lease_id": {"type": "string", "default": ""},
                    "task_id": {"type": "string", "default": ""},
                    "key": {"type": "string", "default": ""},
                    "value": {"type": "string", "default": ""},
                    "query": {"type": "string", "default": ""},
                    "command": {"type": "string", "default": ""},
                    "ttl_seconds": {"type": "integer", "default": 0},
                    "max_tokens": {"type": "integer", "default": 0},
                    "task": {"type": "string", "default": ""},
                    "contract": {"type": "object"},
                    "checkpoint": {"type": "object"},
                    "status": {"type": "string", "default": ""},
                    "reason": {"type": "string", "default": ""},
                    "record": {"type": "object"},
                    "record_id": {"type": "string", "default": ""},
                    "target_scope": {"type": "string", "default": ""},
                    "approver": {"type": "string", "default": ""},
                    "fingerprint": {"type": "object"},
                    "tool_outcome": {"type": "object"},
                    "extra_fields": {"type": "array", "items": {"type": "string"}},
                },
            },
        }

    if fs.work_orchestrator:
        schemas["local_ai_work"] = {
            "name": "local_ai_work",
            "description": "Delegate, resume, inspect or cancel a complete bounded repository work order with compact verified handoff.",
            "parameters": {
                "type": "object",
                "required": ["action"],
                "properties": {
                    "action": {"type": "string", "enum": ["submit", "status", "wait", "get", "cancel", "continue"]},
                    "root": {"type": "string", "default": ""},
                    "task": {"type": "string", "default": ""},
                    "work_id": {"type": "string", "default": ""},
                    "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                    "constraints": {"type": "array", "items": {"type": "string"}},
                    "mode": {"type": "string", "enum": ["execute", "plan", "plan_only", "dry_run"], "default": "execute"},
                    "permissions": {"type": "object"},
                    "budget": {"type": "object"},
                    "timeout_seconds": {"type": "number", "default": 90},
                    "answer": {"type": "string", "default": ""},
                    "response_profile": {"type": "string", "enum": ["minimal", "compact", "standard", "debug", "delta"], "default": "compact"},
                    "return_fields": {"type": "array", "items": {"type": "string"}},
                    "max_output_tokens": {"type": "integer", "default": 0},
                    "keep_failed_workspace": {"type": "boolean", "default": False},
                },
            },
        }

    if fs.artifacts:
        schemas["local_ai_artifact"] = {
            "name": "local_ai_artifact",
            "description": "Exact evidence or artifact slice fetcher.",
            "parameters": {
                "type": "object",
                "required": ["artifact_id"],
                "properties": {
                    "artifact_id": {"type": "string"},
                    "section": {"type": "string", "default": ""},
                    "offset": {"type": "integer", "default": 0},
                    "max_chars": {"type": "integer", "default": 4000},
                    "extra_fields": {"type": "array", "items": {"type": "string"}},
                },
            },
        }

    _apply_response_budget_schema(schemas, cfg)
    return schemas


def write_all_generated(
    cfg: dict[str, Any],
    target_root: Path,
    hub_python: Path | None = None,
    serena: Path | None = None,
    codegraph: Path | None = None,
) -> dict[str, list[str]]:
    """Generate all skill, instruction, MCP manifest, and schema files into target_root."""
    target_root = target_root.resolve()
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
    policy_path = gen_dir / "agent-policy.md"
    policy_path.write_text(generate_global_policy(cfg) + "\n", encoding="utf-8")
    results["instructions"].append(str(policy_path))

    tok_policy_path = gen_dir / "token-economy-policy.md"
    tok_policy_path.write_text(generate_token_economy_policy(cfg) + "\n", encoding="utf-8")
    results["instructions"].append(str(tok_policy_path))

    # 3. Generated MCP manifests
    generic_mcp = generate_mcp_configs(cfg, target_root, python_bin, serena, codegraph, "generic")
    vscode_mcp = generate_mcp_configs(cfg, target_root, python_bin, serena, codegraph, "copilot")
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
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    target = Path(args.output_dir).resolve()
    py_bin = Path(args.python_bin) if args.python_bin else Path(sys.executable)
    res = write_all_generated(cfg, target, py_bin)
    print(json_dumps({"success": True, "target": str(target), "generated": res}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
