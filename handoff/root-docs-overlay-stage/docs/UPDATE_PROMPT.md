# Generic Agent Update & Upgrade Prompt for Local AI Hub

Use this prompt with any AI coding agent (Claude Code, Codex, Cursor, Windsurf, Gemini, Roo, GitHub Copilot) in any repository to upgrade an existing Local AI Hub installation from V3 to V4 from the canonical `master` branch, upgrade dependencies, restart services, and refresh the repository's instruction policies.

Local model routing starts from `[hardware].profile="auto"`; hardware detection or an explicit profile selects a role map, then user overrides apply only to configured model tiers at or above the routed quality floor. In order `background_code/fast_code/heavy_code/reasoning/general/vision`: integrated=`qwen2.5-coder:0.5b/qwen2.5-coder:1.5b/qwen2.5-coder:3b/qwen2.5-coder:7b/qwen2.5-coder:1.5b/qwen3-vl:4b`; balanced=`qwen2.5-coder:1.5b/qwen2.5-coder:3b/qwen2.5-coder:7b/qwen3.5:9b/qwen2.5-coder:7b/qwen3.5:9b`; high=`qwen2.5-coder:1.5b/qwen2.5-coder:3b/qwen2.5-coder:7b/qwen3.5:9b/qwen3.5:9b/qwen3.5:9b`; max=`qwen2.5-coder:1.5b/qwen2.5-coder:3b/qwen3.5:9b/qwen3.5:9b/qwen3.5:9b/qwen3.5:9b`. Ordinary reasoning uses `heavy_code`; only heavy reasoning uses `reasoning`. These are routing targets, not proof that models are installed; model pulls remain opt-in. Run deterministic and indexed Hub actions first for exact facts, symbols, diff and tests; use `local_ai_task` for semantic generation, exploration, reasoning, review, independent second opinions and compression.
Semantic delegation is optional and on-demand; use it when bounded independent work would add value.

Before changing model routing or claiming a model switch is safe, measure supported hardware/backend cohorts and attach revision-bound quality, latency, and VRAM evidence before and after. Model output is advisory, not verification.

---

```markdown
# TASK: Upgrade Local AI Hub from V3 to V4 and Refresh Repository Instructions

You are an autonomous AI engineering agent. Your task is to upgrade **Local AI Hub** from V3 to V4 on this system using the canonical `master` branch, update dependencies, restart the background service, re-verify health, and refresh the Local AI Hub Tool Policy and Token Economy Policy in this repository.

Preserve privacy-safe adoption telemetry: it contains only normalized aggregate tool/action/intent/outcome, time, latency, and output-size buckets. Never migrate or expose prompts, source, secrets, absolute paths, or raw request records. Bypasses require an explicit client signal.

Follow these execution phases:

---

### PHASE 1: LOCATE INSTALLATION & SELECT VERIFIED RELEASE REVISION

1. **Locate Installation Directory**:
   - Windows: `$HOME\.local-ai-hub` (or `%USERPROFILE%\.local-ai-hub`)
   - Linux / macOS: `~/.local-ai-hub`
2. **Protect Local Changes**:
   - Run `git status --short` before changing branches.
   - If the installation worktree is dirty, preserve the changes and stop for operator review. Never use `git reset --hard`, `git checkout -- .`, or discard local configuration/source changes.
3. **Select the T20-approved release revision**:
   - Obtain exact commit SHA from the T20 release owner; moving `master` is not a release pin.
   - Before fetching or switching, preserve the installation checkout and require `git status --porcelain=v1 --untracked-files=all` to be empty. If dirty, stop; never reset, clean, or overwrite user changes.
   - Fetch canonical origin, verify the SHA is reachable from `origin/master`, then check out that exact SHA (detached checkout is acceptable).
   - Verify `git rev-parse HEAD` equals approved SHA and full porcelain status remains empty before setup.
   - Current `install.ps1`, `install.sh`, and `tools/setup.py` do not accept or enforce `--expected-revision`; manual verification is required.


---

### PHASE 2: RUN UPDATE / RE-SETUP

Run the platform installer with the active hardware profile to apply dependency updates, regenerate MCP schemas/manifests, and update skills. Inspect provider config first: Ollama is selected when `[ollama].enabled = true` and its install/model pulls still require the existing explicit opt-ins (`server.auto_start_ollama = true`, `llama_cpp.fallback_to_ollama = true`). If Ollama is disabled, `llama_cpp.mode = "on"` provisions the pinned llama.cpp runtime and default Qwen 1.5B model under `server.state_dir`; `"auto"` uses only a configured existing endpoint; `"off"` disables it. Never switch providers silently or start `ollama serve` as a fallback. Pull `models.vision` only for an explicitly enabled Ollama backend and `features.vision = true`:

Before updating or rolling back, stop the Hub and back up the installation, `config.toml`, and complete configured `server.state_dir` together; include SQLite `-wal` and `-shm` files. Caches are disposable and do not contain durable tasks, receipts, jobs, memory, or leases. Restore only declared roots and preserve data outside the rollback write set.

- **Windows (PowerShell)**:
  ```powershell
  powershell -ExecutionPolicy Bypass -File "$HOME\.local-ai-hub\install.ps1" -Profile auto
  ```
- **Linux / macOS (Bash)**:
  ```bash
  bash "$HOME/.local-ai-hub/install.sh" --profile auto
  ```

---

Consult [PYTHON_SDK.md](PYTHON_SDK.md) for the current Python API and replay/error contracts.

### PHASE 3: VERIFY SERVICE, MCP, AND HEALTH

1. **Verify Health Endpoint**:
   ```bash
   curl -s http://127.0.0.1:11435/health
   ```
   Must return `{"success":true,"hub_online":true,"version":"..."}`. `/health` proves liveness and package version only. Setup reconciles/restarts the Hub; do not issue a second unconditional restart. Reload the Codex MCP host separately, then verify `tools/list` and one bounded `tools/call`. Capture daemon and adapter PIDs, executable/module paths, and source fingerprints separately; `4.0.0` alone is not revision identity. Never replay `outcome_unknown` automatically.
2. **Run Doctor Diagnostic**:
   - Windows:
     ```powershell
     & "$HOME\.local-ai-hub\.venv\Scripts\python.exe" "$HOME\.local-ai-hub\tools\doctor.py"
     ```
   - Linux / macOS:
     ```bash
     "$HOME/.local-ai-hub/.venv/bin/python" "$HOME/.local-ai-hub/tools/doctor.py"
     ```
3. **Hardware Acceleration Check (iGPU / NPU)**:
   - On Windows Intel systems, managed llama.cpp setup tries SYCL0 and retries on CPU if GPU startup fails. `mode = "auto"` checks an existing endpoint only. Do not set `OLLAMA_VULKAN` for Intel llama.cpp inference.
   - Other supported platforms use the pinned CPU build for managed llama.cpp. NVIDIA/AMD GPU builds require an explicitly configured external endpoint.
   - If an NPU (Intel AI Boost / AMD XDNA) or Intel iGPU is present:
     Ensure OpenVINO dependencies are installed in the venv only when active hardware/configuration selects OpenVINO for embeddings or reranking. Do not install OpenVINO on NVIDIA-only systems merely because the feature permission is true:
     ```powershell
     & "$HOME\.local-ai-hub\.venv\Scripts\pip.exe" install -r "$HOME\.local-ai-hub\requirements-openvino.txt"
     & "$HOME\.local-ai-hub\.venv\Scripts\python.exe" "$HOME\.local-ai-hub\tools\prefetch_openvino.py"
     ```

---

### PHASE 4: REFRESH INSTRUCTIONS IN CURRENT REPOSITORY

Locate active agent instruction files in this repository (`AGENTS.md`, `CLAUDE.md`, `.cursorrules`, `.windsurfrules`, `GEMINI.md`, etc.):
- Replace or sync the `<!-- BEGIN LOCAL AI HUB TOOL POLICY -->` block with the latest policy from `~/.local-ai-hub/generated/agent-policy.md`.
- Replace or sync the `<!-- BEGIN TOKEN ECONOMY POLICY -->` block with the latest policy from `~/.local-ai-hub/generated/token-economy-policy.md`.
- If no instruction file exists, ensure `AGENTS.md` is created with both policy blocks.
- Verify the default setup deploys the `token-economizer` skill and registers the token-tool CLI directory on the user's persistent PATH. Keep the generated policy trigger that requires agents to load this skill before every repository task.
- Ensure the refreshed policy retains this trigger verbatim:
  - Before any repository task, load and follow the `token-economizer` skill when it is installed; this trigger applies even under deadline pressure.
- Use `local_ai_rag` for semantic retrieval only after deterministic and indexed repository evidence is insufficient.
- Preserve the `trim-run` safety boundary: only its bundled token tools and read-only search CLIs may be launched; use `local_ai_command` for tests/builds and arbitrary validation commands.
- For durable work, require one `local_ai_coord(action="task_create")` contract, phase changes through `local_ai_coord(action="task_checkpoint")`, and one bounded wait instead of status polling loops.
- For every non-trivial repository task, after one-time preprocess make `local_ai_repo(action="context", mode="adaptive")` the first useful operation. It accepts the task/context directly and fuses deterministic/indexed evidence, CodeIndex, Serena, bounded lexical search and RAG; it ranks cross-backend agreement, deduplicates, preserves file diversity and degrades optional backends independently. Do not send a hand-built grep-term list or start native search first.
- Keep routing boundaries explicit: repository navigation/symbols/impact=`local_ai_repo`; exact source/log slices=`local_ai_artifact`; test/lint/typecheck/build=`local_ai_command`; task contracts/ownership leases/checkpoints/receipts/receipt-gated completion=`local_ai_coord`; task-wide context=`local_ai_coord(action="context_compile", task_id=...)`; semantic generation/exploration/reasoning/review/second opinion/compression=`local_ai_task(action="delegate"|"explore"|"reason"|"review"|"second_opinion"|"compress", task_id=...)`; deterministic/indexed tools remain for exact facts, symbols, diff and tests; `local_ai_repo(action="solve")` preserves one bounded local pass for explicit semantic wording; failure diagnosis is not automatic: although `features.local_diagnostic_dispatch` is enabled in the installed default profile, use it for one local diagnosis only after low-confidence deterministic command parsing with an artifact reference and narrow preview, never raw logs, architecture, security, mutations, or open-ended coding; closed, verified handoff work=`local_ai_work`, never micro-edits or live discussion.
- Bounded health/cache/telemetry inspection uses `local_ai_status`; never poll. Use only tool names, actions, arguments, defaults, and feature-gated options present in the installed generated schema. The schema is authoritative for the installed version; do not infer support from internal APIs or another release.
- Semantic delegation is on-demand: after deterministic/indexed evidence, use `local_ai_task` selectively for bounded generation, review, independent second opinions, test-log compression, commit message generation, and drafting where helpful. Cloud reasoning and planning are never blocked by mandatory local handoffs. Deterministic/indexed tools remain authoritative for exact facts, symbols, diff and tests. Treat local output as advisory only; queued work, stale context, missing evidence or weak grounding remains visible with explicit metadata and must not be silently discarded. Preserve exceptions for architecture, security, mutations, open-ended coding, exact evidence and verification. Shared specialized prompt contracts and model capability limits live in `docs/MODEL_CAPABILITIES.md`.
- Preserve native fallback gate: only after Hub returns `terminal=true` and `retryable=false`. Mutations never cache or single-flight.
- Keep `features.enriched_search`, `features.batch_replacement`, `features.diagnostic_artifacts`, and `features.local_diagnostic_dispatch` enabled in the installed default profile, while preserving independent rollback switches. Code intelligence also defaults on through `features.code_intelligence`, `code_intelligence.enabled`, and `code_intelligence.serena_enabled`; all three gates must allow Serena use, and an unavailable Serena backend degrades to indexed retrieval. Compare `/api/adoption` token, latency, first-pass validation, terminal failure, and native fallback metrics. Roll back immediately by setting the affected flag to `false`, restarting Hub, and running `python tools/hubctl.py generate`. Malformed values must remain disabled and disabled features must return structured unavailable before work starts. `local_diagnostic_dispatch=true` may retain only bounded failure-preview context for one local diagnosis; it never retains raw output and does not require `diagnostic_artifacts=true`.
- For `batch_replace`, require `features.batch_replacement=true`, then preview with explicit `dry_run=true`; `staged` is not batch dry-run and is never forwarded. Each edit must exact-match once. Keep rollback behavior and never auto-commit replacements. Set `dry_run=false` only after review.

---

### PHASE 5: RE-TRIGGER REPOSITORY PREPROCESSING

Send an asynchronous preprocess request for the current workspace:
- Via MCP tool:
  `local_ai_repo(action="preprocess", root="<CURRENT_WORKSPACE_ROOT>")`
- Or via HTTP loopback:
  ```bash
  curl -s -X POST http://127.0.0.1:11435/api/repo/preprocess \
    -H "Content-Type: application/json" \
    -d "{\"root\": \"$(pwd)\"}"
  ```

---

### PHASE 6: REPORT STATUS

Confirm:
1. Updated Local AI Hub version.
2. Service status (`running`/`healthy`).
3. Summary of instruction files refreshed.
4. Preprocessing status for current repository.
```
### MCP response economy

After updating, verify the generated schemas under the installation's `generated/` directory expose `max_response_tokens`, `response_profile` (default `"compact"`), and `reuse_key` on the existing Hub tools. These are installation artifacts, not checked-in source files. Treat generator output and configuration as trusted repository inputs; never copy tool fields from untrusted model output. Keep aggregate response budgeting enabled, preserve artifact-backed exact detail, and verify telemetry reports raw/projected/saved response estimates without prompt or source retention.
- `response_budget.returned_tokens` measures the final serialized response envelope in `estimated_tokens` and stays at or below the requested budget.
- Preserve protected status, error, evidence, and context-identity fields; keep exact detail artifact-backed.
- Claim savings only with a current `baseline_evidence_id`; report signed `token_savings_delta_est`, including negative values; keep `protocol_tokens_est`, `schema_tokens_est`, and `local_compute_reused_tokens_est` separate.
- Reject `max_response_tokens` below 128; never raise the request silently.
- Native fallback requires an explicit `terminal=true` and `retryable=false` result.
- On `outcome_unknown` or `in_progress`, do independent work; never poll or repeat the identical operation.

Use only actions and arguments present in the installed generated schema. Schema presence is not authorization: process-lifecycle actions such as `spawn_daemon` require an explicit policy capability grant. Do not infer support for extra fields from similarly named APIs.

### Adaptive context and supported capabilities

Call `local_ai_repo(action="context", mode="adaptive")` first after one-time asynchronous preprocessing. Send the task/context directly with the stable absolute root; reuse candidates and evidence IDs before new abstractions. Supply the current phase (`plan`, `discover`, `edit`, `implementation`, `review`, `test`, or `handoff`), plus `task_id`, `focus`, and `preload_profile` when known. Deterministic/indexed evidence remains authoritative; optional Serena/RAG backends enrich it and degrade independently. Models may rank or compress grounded evidence; they cannot invent repository facts.

`/api/context/pack` defaults to `adaptive`; explicit `fast` and `full` remain supported. HTTP guarded requests activate through `guarded=true`, `task_id`, `phase`, or `session_id`; MCP guard-only fields require `guarded=true`, `task_id`, or `phase`. `focus` and `changed_paths` are lists; `approval` is boolean or string and `override_reason` is a string. MCP `max_tokens` and `token_budget` must agree when both are nonzero. Scope/drift overrides need a reason and approval when requested. Raw model/debug detail remains opt-in through `extra_fields`.

Repository-only context can use the available bounded retrieval result when optional backends degrade. A pack requested with `task_id` requires a complete task-context receipt: missing/unavailable compilation returns `context_task_context_unavailable`; missing, stale, or incomplete provenance returns `context_task_context_incomplete`. Do not present either as successful task context or repeat/poll the same operation. Consume `task_context`, `context_id`/`task_context_id`, `etag`, revision, freshness, omitted sections and `next_action` where returned; keep partial/stale context explicit.

Feature-specific schemas expose only enabled tools/actions and applicable fields. Use installed `tools/list` input/output schemas and the generated schema for that configuration: `dry_run` and `edits` require `features.batch_replacement`; `local_ai_task` requires tasks plus a configured model. Internal adapters do not establish public MCP fields. CodeGraph remains optional external standalone tooling outside Hub setup/runtime; see [INSTALLATION.md](INSTALLATION.md#optional-standalone-tool-codegraphcontext) for independent installation. Cloud reasoning and planning are never blocked by mandatory local handoffs. Source contracts do not establish physical GPU execution, model quality, or completed release acceptance.

### Project configuration, verification, and PathHints

Project configuration and PathHint core are integrated in current source. `resolve_project_context(root, state_dir)` returns immutable effective settings and a `config_digest`. Overlay order is defaults, primary-worktree `.local-ai.toml` when linked, current-project `.local-ai.toml`, Git-common `info/local-ai.toml`, then `.local-ai.worktree.toml`; invalid overlays select safe defaults with error codes. Project configuration stays in the project or Git common directory, while `state_dir` stores bounded, evidence-bound hints. Maps merge by key, lists replace as a whole, and explicit excludes and hard boundaries take precedence over force includes. Overrides cannot bypass root containment, binary policy, configured size limits, or preprocessing exclusions; request hints remain subordinate to root containment and hard exclusions.

`verification_rules` maps exact task acceptance-criterion names to receipt requirements: `true` requires configured `lint` and `test` receipts, and an array names exact configured command aliases. `required_commands` is not a global switch; it applies only when the task criterion has that exact name. The HTTP completion wrapper rejects invalid configuration or incomplete verification before checkpointing and completion. Source integration does not verify the full owner, tenant, revision, criterion, and memory-audit runtime matrix.

`shared_namespace` exposes a server-derived coordination identity and shares bounded path hints across linked worktrees under one Git common directory. It does not replace the physical repository root. Cross-worktree Agent OS memory sharing remains HOLD; memory and lease consumers must not be assumed to use this hint namespace.

`ProjectContext.prioritize_paths(...)` ranks the complete candidate list in this order: literal `entry_points`, request-scoped `path_hints`, then saved hints matching scope, repository revision, and config digest. It preserves every candidate and returns `PathHintUsage`; `hint_helped` stays unknown until measured. When a hint does not help, consumers use their broader fallback. Telemetry exposes usage flags without candidate paths. Save only verified hints.

`HubClient.post` forwards typed hints to `/api/search` and `/api/command` when no explicit `path` is supplied; an explicit path removes hints. HTTP `/api/context/pack` accepts `path_hints`, `directory_hints`, `exclude_paths`, and `force_include_paths` only in `adaptive` mode and validates them as lists. Current internal MCP adapters accept path controls, while generated public schema support must be checked in the installed `tools/list`; do not infer public wire support from internal methods.

Hints are repository-relative paths beneath the trusted project root; reject absolute, traversal, glob, missing, and symlink or junction escape paths. Request hints may omit evidence metadata. Learned hints require evidence ID, provenance, matching repository revision, and config digest. Revalidate saved paths when reading them, and never write raw paths or hint contents to telemetry.

### Runtime schemas, offline mode, and Agent OS memory

Use the installed `tools/list` input/output schema; action-specific fields and result shapes are not interchangeable. Schema presence is not authorization.

Operational modes are `active`, `gaming`, and `maintenance`: missing persisted state defaults to `active`; invalid/unreadable state degrades to `maintenance`. For gated actions, `gaming` permits non-heavy work and safe job actions `status`, `wait`, `result`, `cancel`, and `evaluation_report`. The required safety contract is stricter for maintenance: `maintenance` must reject every agent MCP/API action before Agent OS database access; operator-only mode, health, and dashboard controls remain available. The current maintenance safe-job exception fix remains pending integration and verification; do not interpret the existing exception as the required maintenance policy or claim maintenance isolation is accepted. Other gated work returns `terminal=false`, `retryable=true`, and `retry_after_seconds=5`; back off, do independent work, and avoid polling. `HubClient.ensure_server` does not auto-start an offline server in non-active or degraded mode.

`hubctl pause` sets `gaming` and `hubctl resume` sets `active`. When Hub is offline, `pause` and `resume` update persisted mode without starting the server; offline `mode` and `status` read that persisted state. An offline pause reports no available runtime unload backend; it is not physical GPU/VRAM evidence.

For durable work, create and checkpoint one Agent OS task contract before edits. On restart, resume the existing task with the same `task_id`. Record memory with scope-appropriate provenance; repository-scoped memory requires provenance tied to the trusted project root.

`local_ai_task(task_id=...)` automatically compiles task context before a semantic model call and attaches `task_context_id`, `task_context_etag`, and `task_context_evidence_ids` on successful consumption. Memory selection filters scope/root/task/tenant/clone/worktree/branch before its bounded limit; only normal-sensitivity, unexpired `active`/`confirmed` memory becomes a candidate, then token budgeting selects what fits. Use IDs are selected `memory_record` elements' `element_id` values in compiled context. Non-use IDs are bounded diagnostics when `include_diagnostics=true`: `stale_ids`, `quarantined_ids`, `rejected_ids`, `superseded_ids`, and `legacy_unscoped_ids` (up to eight per category, subject to context budget). IDs show selection or exclusion, not proof that a model followed memory. Do not invent an exhaustive adoption/non-use receipt for every budget-omitted candidate.

Changed paths plus repository revision stale matching records. When optional memory is absent or excluded, fall through to fresh bounded repository evidence; never reuse stale memory as authoritative or label an incomplete task-context receipt successful. Keep use/non-use IDs in scoped context/evidence, not broad telemetry. `/api/adoption` stores low-cardinality aggregates, not memory bodies or per-record adoption receipts; never send prompts, source, model output, secrets, or raw/full project paths to telemetry.

If Hub is unavailable, make one bounded health/retry attempt, then use one native fallback. Native validation still requires `terminal=true` and `retryable=false`; never poll or repeat an identical operation.

### Memory adoption checkpoints

Agents must consider supplied relevant memory as advisory context and verify volatile facts against current source before relying on them. Before completion, checkpoint `state_data.memory_audit` through `local_ai_coord(action="task_checkpoint", task_id=..., checkpoint=...)`. `used_ids` must be a list of IDs from server-managed `memory_context.items[].id`; cite only findings actually used. `not_used_reason` must be nonempty when `used_ids` is empty, including when supplied memory was irrelevant or unavailable. Completion validates the audit when server memory items or warnings exist.

Normal `memory_record` elements use the raw record ID as `element_id`; TaskStore supplies the same ID in its memory items. Check the current server item allowlist before citing IDs. Do not invent IDs or copy `preload_memory_*` IDs into the audit. Do not replace or modify server-managed `memory_context`. Selection diagnostics alone do not establish use, and excluded IDs are not the checkpoint audit's used-ID allowlist.

For used volatile items, provide `source_checks` keyed by each used volatile record ID; each check needs nonempty `source` or an `evidence_ids` list containing a nonempty string. Record a real current-source check, not placeholder evidence. The completion gate checks audit shape and supplied-ID membership; it does not prove that a model followed memory or that a source reference is true.

Checkpoint payload examples below go in the `checkpoint` argument. Replace example IDs with exact currently supplied item IDs and source/evidence placeholders with verified current facts. Example use of a non-volatile supplied finding:

```json
{"state_data":{"memory_audit":{"used_ids":["supplied-record-id"]}}}
```

Example use of a volatile supplied finding, checked against current source:

```json
{"state_data":{"memory_audit":{"used_ids":["supplied-volatile-id"],"source_checks":{"supplied-volatile-id":{"source":"verified-current-source-reference","evidence_ids":["verified-current-evidence-id"]}}}}}
```

Example non-use:

```json
{"state_data":{"memory_audit":{"used_ids":[],"not_used_reason":"Supplied memory was reviewed but did not support this task."}}}
```

Save only confirmed reusable findings with scope-appropriate provenance and evidence. Never store chat history, prompts, source text, model output, secrets, or personal data. Use existing installed-schema memory actions: inspect the scoped prior record with `memory_get`, record a confirmed correction through `memory_record`, and use `memory_delete` only with the verified explicit scope identity when removal is appropriate. For corrections, preserve original source, provenance, evidence and prior-record linkage in the existing record/provenance workflow; no new memory store or invented correction alias. Keep unavailable/stale memory explicit, use fresh bounded source evidence, and record a truthful non-use reason rather than inventing use.

### Document and diagram ingestion

Document ingestion requires nonempty `content`; `title` and `metadata` are optional. On success it returns `success: true`, `workspace`, `document_title`, `chunks_ingested`, and `embedded` (`true` when at least one chunk has an embedding). Embedding failures do not stop lexical publication; chunks without embeddings remain searchable lexically. These methods do not return `embedding_status`, `ingest_publish_failed`, or a `retryable` flag.

Diagram ingestion requires an existing `image_path` with a supported image extension (`.png`, `.jpg`, `.jpeg`, `.webp`, `.svg`, or `.bmp`); `caption` and `metadata` are optional. Success adds `diagram_indexed` and the resolved `image_path` to the document result.

### LLM card synthesis scope

`disable_llm_card_synthesis` applies to fallback synthesis for unparsed file cards only. Module and project cards use separate `prefer_deterministic_modules` and `prefer_deterministic_project` settings; background LLM synthesis may still run when deterministic card generation does not satisfy its acceptance conditions.
