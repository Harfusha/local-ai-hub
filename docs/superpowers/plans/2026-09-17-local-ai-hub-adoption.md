# Local AI Hub Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Make Local AI Hub the observable, safe first choice for repository navigation, commands, artifacts, local diagnosis, and durable work without breaking the typed MCP surface.

**Architecture:** Keep existing tools and typed action literals. Add routing guidance, capability-health telemetry, and bounded artifact/diagnostic flows behind existing actions and feature flags. Native tools remain available only after a recorded terminal Hub failure.

**Tech Stack:** Python 3.11+, FastMCP, SQLite state under server.state_dir, pytest, existing dashboard and deterministic index.

---

## Baseline and scope

Current dirty changes add local_ai_repo(batch_replace), opt-in enriched search, batch-replace safety tests, and bytecode-free Python preflight. Keep them as the baseline.

Do not remove _resolve_action aliases in this work. They are existing public behaviour, not introduced by the batch-replace diff. Removing them is a breaking API decision outside this plan.

Preserve every unrelated dirty path and the untracked 2026-09-17-agent-efficiency-observability-design.md. Do not reset, stage, edit, or commit those paths.

### Task 1: Complete batch-replace contract

**Files:**
- Modify: src/local_ai_hub/mcp_server.py
- Modify: src/local_ai_hub/deterministic.py
- Modify: tests/test_mcp_agent_routing.py
- Modify: tests/test_new_capabilities_and_hardening.py
- Modify: docs/INSTALL_PROMPT.md
- Modify: docs/UPDATE_PROMPT.md

- [ ] Add a failing test for a separate dry_run parameter:

    result = local_ai_mcp.local_ai_repo(
        action="batch_replace", root=str(ROOT), edits=edits, dry_run=True
    )
    assert captured["dry_run"] is True
    assert "staged" not in captured

- [ ] Run python -m pytest -q tests/test_mcp_agent_routing.py -k batch_replace. Expect failure because local_ai_repo has no dry_run parameter.
- [ ] Add dry_run: bool = False beside edits in local_ai_repo. Forward only bool(dry_run) to /api/code/batch_replace. Retain the non-empty edits guard and explicit RepoAction literal.
- [ ] Keep compile(new_text, str(fpath), "exec") preflight. Add a syntax-failure-after-later-edit test proving neither target changes. Add concurrent-call coverage only if DeterministicEngine already has one file-operation lock.
- [ ] Run python -m pytest -q tests/test_mcp_agent_routing.py tests/test_new_capabilities_and_hardening.py. Expect PASS. Run git diff --check over only Task 1 files.
- [ ] Update both canonical prompts with exact-match, dry-run, rollback, and no-auto-commit rules. Stage only Task 1 files; commit with feat: harden batch repository replacement.

### Task 2: Make routing discoverable without schema loss

**Files:**
- Modify: src/local_ai_hub/mcp_server.py
- Modify: tests/test_mcp_agent_routing.py
- Modify: docs/INSTALL_PROMPT.md
- Modify: docs/UPDATE_PROMPT.md

- [ ] Add failing description tests:

    assert "repository navigation" in _desc_repo().lower()
    assert "terminal" in _desc_command().lower()
    assert "checkpoint" in _desc_coord().lower()
    assert "local diagnosis" in _desc_task().lower()

- [ ] Run python -m pytest -q tests/test_mcp_agent_routing.py -k descriptions. Expect failure.
- [ ] Add one stable intent line to each public tool description: navigation/symbol/impact=repo; exact source or log slice=artifact; command/test/lint/build=command; ownership/checkpoint/receipt=coord; local diagnosis/boilerplate/second opinion=task; closed low-risk work=work.
- [ ] Preserve all action literals, action aliases, and input types. Do not add schema modes, action aliases, or an untyped fallback.
- [ ] Mirror the compact map in INSTALL_PROMPT.md and UPDATE_PROMPT.md. State native fallback requires terminal, non-retryable Hub failure; mutations never use cache or single-flight.
- [ ] Run python -m pytest -q tests/test_mcp_agent_routing.py. Expect PASS. Commit only Task 2 files with docs: clarify hub routing boundaries.

### Task 3: Add privacy-safe capability health telemetry

**Files:**
- Create: src/local_ai_hub/adoption_metrics.py
- Modify: src/local_ai_hub/services.py
- Modify: src/local_ai_hub/commands.py
- Modify: src/local_ai_hub/mcp_server.py
- Modify: src/local_ai_hub/dashboard.py
- Create: tests/test_adoption_metrics.py
- Modify: docs/INSTALL_PROMPT.md
- Modify: docs/UPDATE_PROMPT.md

- [ ] Add failing store tests using records shaped as:

    record = {
        "intent": "navigation", "tool": "local_ai_repo",
        "action": "search", "outcome": "used",
        "fallback_reason": "", "duration_ms": 12, "output_chars": 640,
    }

  Assert no prompts, source, secrets, or absolute paths persist. Assert daily aggregates report used, bypassed, blocked, failed, and dormant.
- [ ] Run python -m pytest -q tests/test_adoption_metrics.py. Expect collection failure.
- [ ] Implement AdoptionMetricsStore with configured_state_dir, connect_sqlite, WAL, parameterized SQL, retention, timestamp/duration/output-size buckets, and redaction before persistence.
- [ ] Inject the store through LocalAIServices. Record used, blocked, and failed at the MCP boundary. Record bypassed only from explicit client fallback reports, never from absence of a Hub call.
- [ ] Add a read-only dashboard panel for seven-day action adoption, blocked reasons, terminal failures, dormant actions, latency buckets, and output-size buckets. Never display raw records.
- [ ] Run python -m pytest -q tests/test_adoption_metrics.py tests/test_mcp_agent_routing.py. Expect PASS. Commit only Task 3 files with feat: add hub adoption telemetry.

### Task 4: Distill test and build failures into artifacts

**Files:**
- Modify: src/local_ai_hub/commands.py
- Modify: src/local_ai_hub/services.py
- Modify: src/local_ai_hub/mcp_server.py
- Modify: tests/test_auto_fix_repair_loop.py
- Modify: tests/test_new_capabilities_and_hardening.py
- Modify: docs/INSTALL_PROMPT.md
- Modify: docs/UPDATE_PROMPT.md

- [ ] Add a synthetic long pytest-failure test. Assert result contains failure_summary, artifact_id, and a bounded preview while the artifact keeps full output.
- [ ] Run python -m pytest -q tests/test_auto_fix_repair_loop.py tests/test_new_capabilities_and_hardening.py -k artifact. Expect failure.
- [ ] In CommandBroker, deterministically extract first failing file, line, test, and assertion; store complete output through the existing artifact facility; return:

    {
        "success": False,
        "failure_summary": {"path": rel_path, "line": line, "message": message},
        "artifact_id": artifact_id,
        "preview": preview,
    }

- [ ] Invoke local_ai_task only when deterministic confidence is low. Pass artifact reference and narrow slice, never full raw output. Preserve raw evidence.
- [ ] Run python -m pytest -q tests/test_auto_fix_repair_loop.py tests/test_new_capabilities_and_hardening.py tests/test_mcp_agent_routing.py. Expect PASS. Commit only Task 4 files with feat: distill command failures into artifacts.

### Task 5: Make durable work and local inference intentional

**Files:**
- Modify: src/local_ai_hub/mcp_server.py
- Modify: src/local_ai_hub/services.py
- Modify: tests/test_mcp_agent_routing.py
- Modify: tests/test_new_capabilities_and_hardening.py
- Modify: docs/INSTALL_PROMPT.md
- Modify: docs/UPDATE_PROMPT.md

- [ ] Add failing routing tests for checkpoint in _desc_coord, closed in _desc_work, and deterministic in _desc_task.
- [ ] Add high-confidence extraction test proving no local-model request. Add low-confidence test proving one bounded local_ai_task request with artifact reference.
- [ ] Run python -m pytest -q tests/test_mcp_agent_routing.py tests/test_new_capabilities_and_hardening.py -k "checkpoint or deterministic or confidence". Expect failure.
- [ ] Implement confidence-gated local task dispatch. Enforce bounded tokens, timeout, structured output, confidence, and artifact references. Never automatically delegate architecture, security, mutations, or open-ended coding.
- [ ] Document task contracts, ownership leases, checkpoints, validation receipts, and completion. Limit local_ai_work to closed low-risk work; exclude micro-edits and live discussion.
- [ ] Run the two Task 5 test files. Expect PASS. Commit only Task 5 files with docs: route durable and local diagnostic work.

### Task 6: Pilot, promote, and roll back by evidence

**Files:**
- Modify: defaults.toml
- Modify: README.md
- Modify: docs/INSTALL_PROMPT.md
- Modify: docs/UPDATE_PROMPT.md
- Modify: tests/test_adoption_metrics.py

- [ ] Add failing tests for disabled-by-default flags covering enriched search, batch replacement, diagnostic artifacts, and L1 distillation. Assert a disabled action returns structured unavailable and performs no partial mutation.
- [ ] Run python -m pytest -q tests/test_adoption_metrics.py -k feature_flag. Expect failure.
- [ ] Add feature flags to defaults.toml. Default risky or cost-bearing capability to disabled. Document 14-day baseline, 10-20% pilot selection outside request path, one-flag rollback, and promotion gates.
- [ ] Promotion requires no increase in terminal failures, native fallback rate, or validation regressions. Never cache or single-flight mutations.
- [ ] Run:

    python tools/release_check.py
    python -m compileall -q src mcp tools tests
    python -m pytest -q
    python tools/selftest.py

  Expect every command exits 0.
- [ ] Stage only Task 6 paths; inspect git diff --cached --check and git diff --cached --name-only; commit with feat: add adoption rollout controls.

## Plan self-review

Task 1 implements current navigation/edit safety work. Task 2 covers routing. Task 3 covers health telemetry. Task 4 covers artifacts and deterministic failure distillation. Task 5 covers coord, work, and local tasks. Task 6 covers flags, pilot, rollback, and release evidence.

No task converts typed actions into strings, disables command safety, caches mutations, auto-commits repository edits, or stores prompts, source, secrets, or full paths in telemetry.
