# Local AI Hub 8.1.0 — End-to-End Completion, Stabilization & Verification Design

**Date:** 2026-11-24
**Repository:** `Harfusha/local-ai-hub` (`master`, baseline SHA `718b1eba521069411308b3e6d5e19c6b39db7325`, version `8.1.0`)
**Primary Audit Input:** `LOCAL_AI_HUB_8.1.0_KRITICKY_AUDIT_2026-11-24.md` (LAH-001–LAH-048, A01–A21)
**Status:** Active Execution Blueprint (autonomous `/goal` scope)

---

## 1. Intent & Goals

Transform Local AI Hub 8.1.0 from a `NO-GO` candidate (failing strict release gates, stale CI selectors, mixed AI/deterministic provenance, unbacked migration setup paths, unverified cascade/Laya/RAG/provider claims, and unbounded runtime/telemetry artifacts) into a genuinely stable, secure, deterministic-first, offline-capable, well-typed, benchmarked, and independently verified production system.

All 48 audit items (`LAH-001`–`LAH-048`), all 21 historical audit items (`A01`–`A21`), still-open prior audit/plan requirements, and newly discovered defects (`NEW-*`) are in scope. Work proceeds strictly in dependency stages (`Etapa 0` -> `Etapa 1` -> `Etapa 2` -> `Etapa 3` -> `Etapa 4` -> `Final Audit & Release Readiness`), without skipping P2/P3 optimizations or masking failures.

## 2. Core Architectural Principles & Invariants

1. **Deterministic-First:** Use AST, symbol/call/import graphs, exact lexical matching, Git metadata, static checks, and content-addressed caches before invoking any LLM. AI output is never promoted to deterministic baseline truth.
2. **Local-First & Offline-First:** Core functionality, indexing, lexical/hybrid fallback, deterministic planning, Agent OS, and configured local inference work offline after provisioning. No mandatory external SaaS, remote DB, or silent exfiltration.
3. **Strict Provenance & Epistemic Separation:** Every stored/cached/displayed/delivered fact distinguishes:
   - `deterministic_fact` (AST/parser/git/filesystem)
   - `source_verified_fact` (bounded source span + hash verified)
   - `llm_draft` / `ai_hypothesis`
   - `llm_enriched` (schema-validated, evidence-anchored)
   - `verified_result` (authentic tool/command execution receipt)
4. **Single-Owner Loopback Security Boundary (Realistic Threat Model):** Preserve the intentional tokenless loopback architecture (`127.0.0.1`, no Hub bearer token). Explicitly acknowledge and enforce that loopback proves local host reachability, not caller process/agent identity—therefore root/worktree confinement, command allowlist/authorization, path/symlink/junction checks, capability/approval gates, and writer lease fencing must enforce real invariants server-side. Separate privileged local admin/debug/export/reset controls appropriately and redact sensitive data on export.
5. **Versioned Migrations Only (No Permanent Dual-Read Runtime):** Retired persisted/config formats convert in explicit, ordered, backup-protected, fail-closed migrations before runtime opens state.
6. **Hardware & Resource Discipline:** Reference workstation target is RTX 5070 Ti (16 GB VRAM), Ryzen 7 7800X3D, 32 GB RAM, Windows 11, while preserving CPU/integrated/balanced/high/max profiles and Linux/macOS portability. Support explicit VRAM budget caps (e.g., 12 GB on 16 GB card), single unified resource arbiter, sequential GPU slot discipline by default unless parallelism proves safe and beneficial, and foreground priority over background preprocessing.
7. **Truthful Verification & Non-Inflation:** No test deletion, threshold lowering, silent skip/xfail, fake receipt, or historical-claim carryover. Every item terminates only in `FIXED_AND_VERIFIED`, `ALREADY_SATISFIED_WITH_EVIDENCE`, `NOT_APPLICABLE_WITH_PROOF`, `BLOCKED_WITH_REASON`, or `DEFERRED_BY_OWNER`.

## 3. Baseline Findings at Start (`718b1eba`)

- **CI & Release Checks:** `tools/release_check.py` (strict) fails on tracked `.agents/` directory; CI `fast-contract` references deleted `tests/test_laya_pipeline_shadow.py` (deleted in `6625d19d`); `integration` job can show green when skipped (`RUN_FULL_SUITE != 'true'`); coverage upload/export runs unconditionally on blocked jobs; `native-experiment.yml` had macOS cancelled.
- **Live Runtime State Observed:**
  - Hub v8.1.0 running locally (PID 34852), Ollama online with 15 models (`qwen2.5-coder-prep-v3:0.5b/1.5b`, `qwen2.5-coder-prep-v4:3b`, `qwen2.5-coder:3b/7b/14b`, `qwen3.5:9b-q4_K_M`, `qwen3.5:9b-nvfp4`, `qwen3-vl:4b`, `minicpm-v:8b`, etc.).
  - Live Hub preprocessing stuck in `error` state (`embedding_space_rebuild_required`, 114 consecutive errors, `code_index` 53/2259 files) (**NEW-001**).
  - Live Hub appends MCP telemetry directly into Git-tracked `.local-ai-hub/telemetry/agents.jsonl` (`LAH-005`).
  - `local_ai_coord(action="plan_list", limit=50, response_profile="minimal")` rejects with `max_response_tokens too small` even though `returned_tokens` is 2919 < 4096 (**NEW-002**).
  - `.venv` lacks `mypy` dev package locally (`mypy` runs from system Python 3.13) (**NEW-003**).
- **Static Baseline (`718b1eba`):** `compileall`, `pyflakes`, `ruff`, `mypy` (16 strict files), `npm run typecheck`, `check_dashboard.py` (358 IDs), `sync_prompt_policies.py --check`, `surface_inventory.py --check` (674 rows), `audit_agent_surface.py` pass locally; `pytest --collect-only -q --run-all` collects `18648 tests`.

## 4. Stage Architecture & Exit Gates

- **Etapa 0 — Restore CI & Release Credibility (`LAH-001`–`LAH-004`, `LAH-021`, `LAH-037`, `A02`, `A09`, `A15`, `NEW-003`):** Resolve `.agents/` contract cleanly, fix/replace `test_laya_pipeline_shadow.py` coverage + add CI selector preflight manifest validation, eliminate false-green skipped jobs & fake coverage export failures, harden `NO_TEST_CACHE=1` / `--run-all` / cache invalidation, and establish SHA-bound machine-readable acceptance ledger in `tools/generate_audit_acceptance.py` + `audit_acceptance.json`.
- **Etapa 1 — Data Protection, Security & Operational Reliability (`LAH-005`, `LAH-015`–`LAH-018`, `LAH-022`–`LAH-024`, `LAH-026`–`LAH-029`, `LAH-035`–`LAH-036`, `A01`, `A04`, `A05`, `A13`, `A16`, `A17`, `A21`):** Untrack/isolate runtime telemetry & `.ownership/rollback` safely (with secret scan & zero history rewrite), enforce recoverable backups/atomic staging/journal GC in setup & migrations, disable `trust_remote_code` by default & separate offline runtime from download provisioning, clarify & verify loopback/IPC security boundaries, verify full wheel/sdist assets (including `grammars/*.gbnf` if shipped) & Python 3.11–3.14 matrix, verify full update/rollback/uninstall fault injection, enforce universal root/worktree confinement, harden command broker process-tree execution & env/sandbox isolation, prove SQLite/lease/fence crash consistency, propagate single monotonic deadlines/cancellation end-to-end, harden minimal vs full telemetry + export redaction, and harden browser bridge untrusted DOM/privacy controls.
- **Etapa 2 — Correct Local AI, Preprocessing, RAG & Agent Integrations (`LAH-006`–`LAH-014`, `LAH-025`, `LAH-030`–`LAH-034`, `LAH-039`–`LAH-040`, `A03`, `A06`, `A07`, `A10`, `A12`, `A14`, `A18`, `A19`, `NEW-001`, `NEW-002`):** Separate `llm_draft` vs `deterministic_fact`, fix cascade off/fallback policy & complete canonical pipeline fingerprints, eliminate silent draft swallows & false 15% diff claims, separate `estimated_speedup` vs `measured_speedup` & validate speculative token prefix invariants, replace Laya BoW semantic replay with scoped exact-key/hybrid candidate similarity & thread-safe single-map cache, separate Laya predictions from verified ground truth (`LAH-014`) + implement calibrated `off`/`shadow`/`advisory`/`active` modes (`LAH-032`), fix RAG post-reset indexing/coverage & golden CZ/EN retrieval metrics + diagnose/fix live `embedding_space_rebuild_required` loop (`NEW-001`), enforce real VRAM admission with 12 GB cap & single-slot GPU policy (`LAH-030`) + measure cascade vs one-pass cost (`LAH-031`), verify real provider E2E/handshake/config (`Codex`, `Antigravity`, `OpenCode`, `Claude`, etc.), bind completion receipts strictly to executed tool diffs/commits (`LAH-034`), zero contract registry drift (`LAH-039`), and clarify/verify Native SimHash status (`LAH-040`).
- **Etapa 3 — Architecture, Type Safety & Maintainability (`LAH-019`–`LAH-020`, `LAH-038`, `LAH-046`–`LAH-047`, `A08`, `A11`, `A20`):** Expand strict `mypy` cleanly across core boundary & domain modules (schema/command/migrations/scheduler/RPC/Laya DTOs) + incremental Ruff rules (`B`, `S`, `I`, `UP`, `SIM` scoped), decompose oversized modules by real transaction/domain boundaries (`agent_memory.py`, `scheduler.py`, `async_jobs.py`, `laya_candidates.py`, `client.py`, `generator.py`, `operation_contracts.py`, `ui_static/dashboard.html`) with DAG cycle-check test, harden dashboard (`npm ci`, deterministic build, XSS sanitization, 10k timeline virtualization/pagination, SSE reconnect, accessible nav), complete local observability with correlation IDs & phase timings (`LAH-046`), and integrate unified `audit`/`doctor --verify` evidence engine (`LAH-047`).
- **Etapa 4 — Performance Optimizations & High-Value Extensions (`LAH-041`–`LAH-045`, `LAH-048`):** Unify existing scheduler/VRAM balancer/GPU manager into a single resource arbiter (`LAH-041`), deliver empirical token-saving context planner (`LAH-042`, A/B benchmark targeting >=20% context reduction on eligible tasks without correctness loss), complete fast local Laya decision cycle for drift/next-tool/clarify (`LAH-043`), upgrade dependency-aware incremental preprocessing + PHP/CakePHP/Python/TS/JS symbol/call graphs + CZ/EN retrieval (`LAH-044`), build unified offline-first pinned Model Registry & benchmark-backed provisioning (`LAH-045`), and minimize agent surface tokens via profile-scoped discovery & host-capable hooks (`LAH-048`).
- **Final Verification & Independent Critical Audit:** Run every verification command cleanly with `NO_TEST_CACHE=1` and `--run-all`, wheel/sdist build & isolated venv smoke, live runtime/provider/benchmark verification, update `audit_acceptance.json` and `FINAL_IMPLEMENTATION_REPORT.md`, commit logically on clean branch/master, perform an independent adversarial review pass, and verify exact final commit SHA.

## 5. Evidence & Rollout Policy

- Existing Hub plans (`plan_e2840d6c5f47`, `plan_3a1fdfc49ddf`, `plan_5edb272644b5`, `plan_4fc62af31642`, `plan_382d8377f040`, etc.) are reconciled into one master execution plan `plan_lah_8_1_0_completion` so no completed work is repeated and no open requirement is lost.
- Large test/benchmark/JUnit/coverage artifacts are stored outside tracked Git source trees (in `artifacts/` gitignored or scratch/evidence store) and referenced by SHA-256 hash inside `audit_acceptance.json`.
