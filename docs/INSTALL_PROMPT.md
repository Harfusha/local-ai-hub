# Generic Agent Installation & Integration Prompt for Local AI Hub

For tenant-scoped agents, use `local_ai_coord` Agent OS `memory_find` and `memory_record`. Workspace memo actions are operator-only and are not exposed through the MCP coordination schema; a tenant-scoped 403 is final and must not be retried or bypassed.

Durable `local_ai_task(action="submit")` accepts optional string `request_id` as its explicit retry identity. This field belongs only to `submit`; omit it for other actions. The public tool schema and argument validator expose the same input.

The optional model-free claim validator requires explicit inputs: `python tools/validate_t02_acceptance_claims.py <manifest.json> <receipt.json>`. Evidence counts require JSON integers; booleans and floats reject. It does not load historical handoff files or establish current release acceptance; synthetic unit fixtures verify only claim-validation behavior.

Both compact and full `local_ai_status` descriptions advertise the `detail` selector. Use `detail="brief"`, `"cache"`, `"telemetry"`, `"full"`, or an enabled advertised detail; never substitute `action`.

For `local_ai_repo`, omit action-inapplicable fields. A retired field rejects whenever supplied as a non-null value, including empty strings and zero; `null` has omission semantics.

Task memory adoption passes the same resolved repository coordination ID into compilation, record materialization and excluded-memory diagnostics; expiry checks retain the current repository and tenant identity.

Outcome records require a canonical kind (accepted/reverted/corrected/regressed/rejected), unchanged canonical string identities, mapping details and a finite nonnegative numeric timestamp. Direct construction and deserialization require explicit kind, actor and timestamp; empty or malformed kinds never become accepted. Named factories supply their named kind and current timestamp, retain their declared default actor `user`, and treat optional `details=None` as empty metadata. Other supplied types are validated without identity or timestamp coercion.

Agent event deserialization requires canonical `event_id`, `stream_id`, `kind`, `payload`, `idempotency_key`, `actor` and `created_at` fields with their declared types; it never fabricates missing identities or coerces supplied values. Event creation factories generate new identities.

Change intents preserve supplied path/prose text, reject coercive identities or scalar path/symbol collections, and require explicit finite numeric creation time when constructed or deserialized. Completion results require a boolean complete flag, canonical criterion lists, actual VerificationReceipt objects and mapping consistency metadata; invalid fields reject instead of being rewritten or replaced. A complete result requires at least one satisfied criterion, no unsatisfied or stale criteria, and passing receipts with matching task/criterion and evidence IDs. These structural checks do not replace service verification of freshness, revision, ownership or execution provenance.

Consistency-guard repository memory writes and audit reads use the current server-derived project coordination ID and exact tenant; missing identity cannot fall back to a physical-root lookup. Windows isolated-parser workers treat only WerGetFlags ERROR_NOT_FOUND as absent per-process flags before setting NO_UI; other HRESULT failures remain explicit.

Agent scopes use exact enum values global/repository/clone/worktree/branch/task/session. Supplied aliases, case/whitespace variants and unknown/nonstring values reject instead of selecting default authority. Omitted scope retains its declared default; the HTTP memory filter retains empty/absent filter semantics.

Private tool-accounting events carry signed token evidence only; they do not fabricate USD costs with fixed rates. TelemetryStore owns configured channel pricing. Token-efficiency metadata uses canonical parent_task/activity/revision/reuse_state/cache_state fields; retired substitutes are not promoted. Trace metadata setters are set_metadata/reset_metadata only.

Telemetry prices use independent finite nonnegative numeric `cloud_input_token_cost_usd_per_million` and `cloud_output_token_cost_usd_per_million` rates (default 3.0 each; zero remains valid). The combined-rate fallback is removed. Missing channel coverage, inconsistent row accounting, or missing boundary history makes total USD cost unknown; known raw-row channel subtotals remain separate. Cost-bearing daily rollups without channel provenance cannot establish complete pricing. Writer lease identifiers reject scalar coercion; lease paths require a sequence of strings, and corrupt live path scopes fail closed.

Semantic MCP responses require explicit boolean `success`; `answer` is not a `text` alias. Successful compiled task context requires explicit `success=true` and `complete=true` on both the response and nested `task_context`, with string `task_context.text`; flat response text is insufficient. Context delta requests use only `since_hash`; `etag` is output metadata, not an input alias. Internal lexical `RepositoryTools.search` uses `limit`, not `top_k`. RAG/context candidate parameters remain distinct. Blackboard CAS updates accept only nonnegative integer `expected_version` (or omission); the retired `expected_etag` keyword rejects. Sections with different identities cannot merge.

HTTP identity comes from authenticated/configured server state or its stable tokenless principal. Generic HubClient requests use the same route principal selection as the server; a client workspace label cannot select authority, and explicit mismatching tenant overrides reject. Existing per-route defaults and Agent OS root derivation remain unchanged. `X-LocalAI-Tenant` is only a claim; obsolete `X-Tenant-ID` is rejected after host/origin validation and before authorization. Reauthorization clears cached principal/root identity. Agent State client sandbox activation matches the server; enabled sandboxes keep configured-principal, derivation-secret and nonempty allowlist requirements. Repository memory lookup uses server-resolved project identity, never a caller's replacement repository ID. Updating these contracts does not rewrite operator configuration.

Omitted retrieval mode selects `adaptive` consistently in MCP, HTTP context packs, Agent OS context compile, and client/service entry points. `adaptive` is the only accepted context mode; `fast`, `full`, aliases and case variants reject before retrieval. Query, focus, changed paths, or omitted guarded fields never silently select an older mode. Pubsub adapters use the current full poll signature, preserving both sequence and timestamp cursors without adapting old providers or coercing client cursor values.

Event and incident storage accepts only current durable schemas. Older event layouts, payload-version override tables, incident ID fabrication and automatic column upgrades are rejected rather than converted. Current producer definitions govern schema validation; prior fingerprints are not compatibility alternatives. Existing durable data is retained for explicit recovery.

Agent State uses `agent_state.sqlite`; old standalone filenames are never copied or merged automatically. Old-only state or an invalid canonical target hiding an old history is rejected while retaining the files. Archived old files alongside readable canonical state remain untouched. Unsupported durable schemas require explicit operator recovery; disposable derived metadata may rebuild.

Task contracts require a nonempty string `goal`. Persisted title-only or missing-goal contracts are rejected without rewriting their contents. HTTP creation accepts a current contract object or the advertised goal/task shorthand; old intent/title/query coercions are removed. Completion requires the current full verification contract and rejects obsolete evaluator signatures.

Persistent Biome lint uses only the reviewed Windows Biome 2.5.15 foreground-server protocol. The Hub verifies named-pipe ownership against its retained process, bounds source reads and IPC, and retains ownership when cleanup is unconfirmed. Unsupported versions/platforms return explicit unsupported results; they never adopt or stop a shared daemon. Installed behavior and performance require separate validation.

`secret_scan` history coverage is bounded to textual changed lines in the requested reachable `HEAD` commits (default 20, integer depth 1..100). It is not a scan of all refs or every historical tree. Shared time, byte, line and finding limits, omitted merge/binary patches, malformed provenance or incomplete process capture prevent a complete/clean claim. History findings retain commit, path, added/removed status and exact hunk line; credential values stay masked.

Use only canonical advertised actions and fields. Short action aliases and the `local_ai_status.action` selector are rejected; status uses `detail`. Each HTTP operation has one canonical route, with distinct operations retaining their own routes. For MCP `secret_scan`, `staged=true` requests history; omit `path` for the whole repository or supply a literal path filter. `query`/`task` are not path aliases or history controls. HTTP accepts only the boolean `scan_git_history` field and validates supplied history depth without coercion. Capability grants cannot authorize after expiration or with malformed expiry; delegation preserves denials and cannot exceed remaining parent depth. Do not add legacy behavior, migration shims or backward-compatibility fallbacks.

Repo file operations use `path`: required for `ast_outline`, `profile_digest`, and `generate_types`; optional for `affected_tests`, `code_invariants`, `schema_inspect`, and `complexity`, retaining their documented repository defaults. `declaration` requires its symbol in `query`, with an optional `path` filter. `ast_refactor` requires `old_symbol` and `new_symbol`; `query`, `task`, and `diff` do not supply rename names. `context_compile` and `verify_completion` require `task_id`. Supplied alternate query/task/path inputs reject in these operation contracts, including alongside canonical values. `generate_types` accepts no `diff` and remains read-only. RAG and Work action names require exact advertised strings in both direct wrappers and MCP calls; no whitespace, case, or hyphen normalization occurs.

`local_ai_repo` accepts canonical `root`, `query`, and `changed_paths`; its retired `cwd`, `symbol`, `paths`, and `files` keyword arguments are absent from the public schema and reject at the raw MCP boundary. Other tools retain their distinct current fields. Relation actions now share strict bounded `limit`/`offset` validation in the operation schema as well as dispatch.

For MCP `callers`, `callees`, and `implementations`, supply the symbol through `query` and pagination through integer `limit`/`offset` (defaults 24/0; limit at most 200, offset + limit at most 2048). `symbol`, `task`, and `max_tokens` are not aliases; `path` is only an implementations filter. Direct HTTP relation defaults remain limit 50 and offset 0. Whole relation records survive projection and the final MCP wire budget; a smaller prefix reports its actual count and known continuation, while first-item overflow returns 413. Exact totals are emitted only when established; missing totals or continuation do not establish completeness. Indexed coverage describes indexed edges with freshness not checked. Unavailable-index Python fallback is bounded, syntactic, and reports incomplete/unsupported scopes; a known indexed empty result never triggers speculative edges.

HTTP Agent OS blackboard bodies use `board_id`, `section`, `content`, `author`, and `remote_sections`; retired `key`, `value`, `approver`, `sections`, and `record` fields reject even alongside canonical fields. `task_id` remains the task scope identity, and an omitted board ID uses the current task-owned default. Falsey canonical content remains unchanged. Public MCP generic fields map once into HTTP fields; these distinct surface contracts do not authorize alternate HTTP body names.

Agent OS POST action selectors must be strings in exact lowercase underscore syntax; whitespace, hyphens, case normalization and string coercion are rejected before dispatch. HTTP blackboard actions are `update`, `get`, `list`, `merge`, `delete`; public MCP `blackboard_*` actions map to these once. HTTP task cleanup, reaping and dataset selectors are `cleanup_worktree`, `reap_expired`, `curate_dataset`; verification export uses `export`. Alternate HTTP action names are rejected. MCP `task_zombie_reap` requires `task_id` and forwards the resolved repository root. HTTP `reap_expired` admits only one explicit task matching the authenticated root and derived tenant; `auto_recover` must be a boolean. Missing, foreign, or malformed scope cannot trigger global reaping, and a renewed heartbeat remains protected by the store's concurrent-update fence. Current mutation-policy denials still apply. Omitted selectors retain only documented endpoint defaults.

Task create/checkpoint/fail/transition/complete/rollback/resume/heartbeat forward the caller's MCP or HTTP response budget to server-side full-memory preflight before task/event writes or rollback file restoration. Automatic worktree creation prepares and binds exact response metadata before Git mutation; preparation failure does not silently create an ordinary task. Completion preflights the final checkpoint and records `cleanup_pending`/`cleanup_scheduled`; maintenance later removes only eligible clean owned worktrees. A Git creation followed by failed SQLite persistence is an applied/unknown cross-store outcome, never a verified rollback or `operation_not_started=true`. Supervisor locks require current structured ownership proof; model unloading requires a complete canonical inventory with endpoint receipts. A coherent empty inventory does not prove physical VRAM reclamation.

VRAM pressure policy requires coherent measured usage and capacity for the same memory pool. Unavailable, malformed or inventory-only samples yield conservative unknown pressure. Raw reported usage remains separate from `policy_pressure_pct`, `policy_headroom_mb`, `policy_measurement_basis` and `policy_pressure_is_derived`; zero reported usage cannot cancel a higher measured pressure bound. RuntimeTuner rejects invalid measurements before updating profiles and uses the configured state directory (a private process fallback for partial configuration).

Use this prompt with any AI coding agent (Claude Code, Codex, Cursor, Windsurf, Gemini, Roo, GitHub Copilot) in any repository to bootstrap Local AI Hub, configure background services and MCP, and integrate the tool and token economy policies into repository instructions.

## Current security and tool contract

Static `security_audit` reports findings, HIGH release blockers, triage status and scan coverage separately. A test path alone never dismisses a credential-like value; such findings remain untriaged. MEDIUM findings prevent an `is_clean=true` verdict. Limits, unreadable/oversized sources, parse failures and time/byte bounds make the scan incomplete. Counts describe visited project-filtered inventory entries; unknown total eligibility is explicit. Source credential values are omitted from ordinary finding snippets. Coverage and decision fields survive response compaction; this static report is not live exploit or whole-repository release proof.

Artifact text reads require a matching canonical paging sidecar and use one snapshot with incremental SQLite reads of at most 64 KiB per block, retaining only bounded requested spans. Missing or invalid sidecars fail closed; an oversized sidecar may be re-derived from source text for that response only, without writes. Unicode and NUL remain intact; reads do not write paging metadata. A shared five-second read deadline covers section discovery and retrieval. Section names are capped at 50 / 512 characters, with explicit omission metadata; JSON section parsing admits at most 1,000,000 source bytes and rejects duplicate keys. Derived sidecar metadata is capped before materialization; startup indexing admits at most 128 bodies of at most 1,000,000 bytes each. Core IDs, tenant bindings and binary contents remain durable. Binary artifact responses require kind, encoding, checksum, SHA-256 and identity. Text offsets and lengths require strict integers; section windows stop at their own boundaries. Runtime memory/latency acceptance remains separately required.

Whisper CLI transcription requires approved cached checkpoint bytes by default. `transcription.allow_model_downloads=true` is an explicit operator opt-in for missing/corrupt weights; truthy non-boolean values do not authorize downloads. The optional `transcription.cache_dir` overrides the upstream XDG/home cache. Cached official checkpoints are verified with cancellation, a 30-second hash deadline and a 5-GiB size cap; aliases use canonical filenames. The CLI receives a verified local path and explicit `--device cpu`; non-CPU device requests are rejected until a separate admission path exists. Existing process timeout and tree cleanup remain in force. Native Whisper/WER, device resource use and real cache behavior still require separate validation.

On Windows, command strings use native Unicode `CommandLineToArgvW` parsing with matching `LocalFree` cleanup. Inline values such as `--junitxml="C:/path with spaces/report.xml"` reach the child without literal wrapping quotes. Internal structured invocations retain argv boundaries and serialize with Windows quoting; literal arguments should use structured argv rather than shell syntax. Native argument parsing does not grant execution authorization.

`generate_types` accepts only `root` and `path`, returns stub text, and never writes `.pyi` files. Resolved source paths stay inside the selected repository root and reads are bounded. Batch delegation accepts at most 16 tasks and rejects a larger batch before routing or execution, with exact counts and bounded rejection details. SQLite maintenance reports attempted/succeeded/failed stores and partial failures; it performs checkpoints and `PRAGMA optimize`, without promising VACUUM.

Use `local_ai_artifact(action="source", path="src/example.py", line_start=1, line_end=5)` for exact workspace source lines. Relative and absolute paths must resolve inside the adapter workspace. This read-only action caps each file at 4 MiB, each range at 200 lines, and returned text at `max_chars` (512–12000); it returns the source SHA-256 and actual returned line range. `line_end=0` selects up to 80 lines from `line_start`. Text truncation is explicit; aggregate response compaction must return the exact selected text or an error. Artifact `get`/`slice` remain artifact-ID operations; undocumented `start_line`/`end_line` source aliases are not published. Malformed output-envelope fields produce a typed, nonretryable contract error naming the field; unknown boolean values are never silently converted to false.

Command execution is fail-closed: `allowed=false` is always rejected before cache reuse or process creation, including legacy `policy_blocking=false`. Unknown commands default to denied; explicit `commands.allow_unknown=true` does not authorize host execution. They also require mutation permission, a task-owned worktree, declared paths, a current work-attempt fence, and the private transaction boundary. Operator configuration is not rewritten when updating packaged defaults.

Transport clients defer hardware inventory when `hardware.auto_tune=false`; servers still inventory devices, and automatic tuning preserves its hardware-derived overlay. On Windows, a newly started shared supervisor receives a retained Job Object handle so it survives adapter exit; failed startup uses the owned Job Object to clean up descendants.

Loopback connection establishment uses the smaller of `client.health_timeout_seconds` and the remaining request deadline. After connecting, response reads retain the remaining request deadline; an absent listener cannot consume that response budget before autostart.

Compact context responses retain exact evidence citations and original success/error decisions.

Archived source copies under docs/integration/archive are excluded from current-source indexing; ordinary documentation remains searchable. Code-index pages may return fewer complete symbols than requested to fit the wire budget; follow next_offset when has_more is true. Unknown optional stale flags are omitted; consult freshness status instead of assuming current data. Complexity and secret scans report their bounded scope and incomplete coverage; success alone is not whole-repository acceptance. Source excerpts in `evidence.raw` stay behind evidence IDs for `local_ai_artifact`; they do not consume the protected metadata budget.

Hugging Face embeddings and rerankers load cached model files offline by default. Set `models.allow_hf_downloads=true` only with explicit operator approval for missing model downloads; a cache error alone never authorizes a network retry. Existing cached CPU fallback models remain available without this opt-in.

Local AI Hub has no remote-access or remote-control mode. HTTP binds only to `127.0.0.1`; HubClient and supervisor probes always target `127.0.0.1`. The dashboard and stdio MCP adapter use loopback HTTP only as same-machine transport. Remote host, client-host, and origin overrides are rejected. Protected routes require credentials and route permissions. `security.api_token` uses coarse `api_token_permissions`; `security.supervisor_token` grants administrative read/write only; `security.action_tokens` map exact actions to credentials; `security.users` maps users to unique tokens, exact resource scopes, and optional tenants. Credential values must be unique and redacted from diagnostics. `client.startup_wait_seconds` defaults to `30.0`.

`local_ai_repo` validates actions against its supported registry. `skeletonize` transforms supplied source text only; it does not inspect a repository. `generate_tests_for_diff` returns manual, skipped test scaffolds; it is not test-pass evidence. `local_ai_status` telemetry, agent-state, and `traces` details avoid the live-status request; `traces` accepts bounded `min_duration_ms` and `trace_action` filters.

MCP parameters are strict and canonical. For `local_ai_command`, `root` scopes the repository independently from `cwd`, `paths` is the only path-list field, `stdin` is the only stdin field, and `format` requires nonempty `paths`; retired aliases and positional compatibility forms reject. For `local_ai_repo`, use `root`, `query`, and `changed_paths`; retired `cwd`, `paths`, `files`, and `symbol` aliases reject. On `/api/context/pack`, presence of `changed_paths` or `focus` requests guarded handling, including an empty list; explicit `guarded` values must be boolean.

`local_ai_command` accepts optional `env` as a mapping from variable names to string values. MCP publishes string-valued entries, and the command broker applies overrides to the child process while preserving its existing name, count, and value validation. Keep values short and task-specific; do not put credentials in prompts or repository files.

For `local_ai_command(action="flaky_detect")`, `runs` is an integer execution count with minimum `1` and default `5`; MCP clients validate the published schema, and the command endpoint receives the selected count.

## Development workflow (binding)

Follow [`docs/superpowers/specs/2026-10-07-simplified-worktree-integration.md`](superpowers/specs/2026-10-07-simplified-worktree-integration.md). The primary agent owns audits, implementation, and integration; do not create audit handoffs, ZIPs, custom owner packets, or routine fingerprints/hash cascades. Work in current `master` by default. Create branches/worktrees only for necessary isolation or genuinely independent parallel implementation. Integrate small verified units into `master` promptly. Preserve all unmerged work; inspect and record every remaining change before recoverable archival. This rule supersedes older delegation and handoff wording below.

Operator maintenance: error resolution shares a bounded deadline and rolls back failed SQLite writes. Exhausted SQLite busy/locked errors at an HTTP request boundary return HTTP 503 with `success:false`, `degraded:true`, and `error:"database_locked"`. GET responses are retryable; POST responses set `outcome_unknown=true`, `terminal=true`, and `retryable=false` because a shared boundary cannot prove whether an action already took effect. Failed writes remain failures and never claim an in-memory substitute or SQLite commit. A rejected authorization audit blocks a mutating admin action; its failed result audit returns HTTP 503 with `outcome_unknown=true` and `retryable=false`, because the action may already have completed. Never replay it automatically. Authorized reads remain available with observability disabled. Scoped Agent OS status reports readiness only, not global task/memory counts. Ordinary agent responses must not include operator diagnostics by default.

Gaming unload uses GET `/api/ps` before and after POST `/api/generate` with `keep_alive=0`, sharing one cancellation/deadline budget. Empty verified inventory is not proof of physical VRAM reclamation. Task completion rejects malformed checkpoint generations, including boolean values that Python otherwise compares equal to integers.

Memory bundle imports require the complete current record schema and explicit record IDs; invalid records reject without metadata-dropping fallbacks. Repository records require tenant and repository identity. Project imports rebind identity to the resolved target repository; standalone imports preserve their explicit identity. HTTP scoped-memory reads and mutations resolve repository identity on the server and use the same bound task identity. Session selectors remain distinct from tenant identity; conflicting session selectors reject. Obsolete derived code-index schemas use cache archival and rebuild, never in-place column migration or row backfill.

Agent OS memory adoption must be verified through the actual MCP transport after installation:
new/resumed tasks receive a small relevant advisory bundle with memory IDs, origin, scope,
version and validity, without requiring an extra `memory_find` or `extra_fields` call.
Checkpoints cite used IDs or a non-empty reason for not using relevant items; volatile facts
must be checked against current source. `memory_context` is server-managed, never caller-editable.
An unavailable lookup returns a bounded warning and does not block the task. Verify the full
serialized memory/response budget, not content-only estimates. Automatic guard proposals stay
`CANDIDATE`; only explicitly approved guard decisions become `CONFIRMED`. Manual operator facts
remain supported. Never automatically retain chats, source/prompt/model-output fields, secrets
or personal data. Reconnect existing MCP adapters after upgrading; passing store/HTTP tests
alone does not prove that the agent received the bundle or used it.

Routing source contract: hardware profile selects role targets; `router.apply_model_override` rejects overrides below the configured quality floor. Model names are routing targets, not proof of installed models; pulls remain opt-in. Semantic local tasks stay on-demand after deterministic/indexed evidence; cloud reasoning and planning never require a mandatory local handoff.

Local model routing starts from `[hardware].profile="auto"`; hardware detection or an explicit profile selects a role map, then user overrides apply. Model `qwen2.5-coder:1.5b` is preprocessing-only. In order `background_code/fast_code/heavy_code/reasoning/general/vision`: cpu=`qwen2.5-coder:3b/qwen2.5-coder:3b/qwen2.5-coder:7b/qwen3.5:9b/qwen2.5-coder:7b/qwen3-vl:4b`; integrated=`qwen2.5-coder:3b/qwen2.5-coder:3b/qwen2.5-coder:7b/qwen3.5:9b/qwen2.5-coder:7b/qwen3-vl:4b`; low=`qwen2.5-coder:3b/qwen2.5-coder:3b/qwen2.5-coder:7b/qwen3.5:9b/qwen2.5-coder:7b/qwen3-vl:4b`; balanced=`qwen2.5-coder:3b/qwen2.5-coder:3b/qwen2.5-coder:7b/qwen3.5:9b/qwen2.5-coder:7b/qwen3.5:9b`; high=`qwen2.5-coder:3b/qwen2.5-coder:3b/qwen2.5-coder:7b/qwen3.5:9b/qwen3.5:9b/qwen3.5:9b`; max=`qwen2.5-coder:3b/qwen2.5-coder:3b/qwen3.5:9b/qwen3.5:9b/qwen3.5:9b/qwen3.5:9b`. Ordinary reasoning uses `heavy_code`; only heavy reasoning uses `reasoning`. These are routing targets, not proof that models are installed; model pulls remain opt-in. Run deterministic and indexed Hub actions first for exact facts, symbols, diff and tests; use `local_ai_task` for semantic generation, exploration, reasoning, review, independent second opinions and compression.

Before changing model routing or claiming a model switch is safe, measure supported hardware/backend cohorts and attach revision-bound quality, latency, and VRAM evidence before and after. Model output is advisory, not verification.


Pinned-source limitation (master `2458f72c`, 2026-10-06): routing quality floors, operational modes, and client identity/transport safeguards are source contracts, not deployed runtime proof. HTTP root authorization and complete maintenance isolation remain separate acceptance gaps. Preserve the configured preprocessing provider. This pinned source has no Gemini preprocessing provider implementation; Gemini agent manifests do not prove such support. Do not invent, install, or infer a Gemini preprocessing implementation. Prior candidate instructions and receipts in `handoff/` and checkpoint history are historical, not current acceptance. Configuration and the returned response-budget envelope are authoritative; generated prose may retain an older budget value.
---

```markdown
# TASK: Install, Verify, and Integrate Local AI Hub in Environment & Repository

You are an autonomous AI engineering agent. Your task is to install and configure **Local AI Hub** on this system (if not already installed or running), verify all components (service, configured local backends, token economy suite, code intelligence), ensure MCP integration, and inject the canonical tool and token economy policies into this repository's agent instructions. Ollama is disabled unless explicitly opted in.

Hub adoption telemetry is aggregate-only: retain normalized tool/action/intent/outcome plus time, latency, and output-size buckets. Never send prompts, source, secrets, absolute paths, or raw request records. Mark a bypass only when the client explicitly signals one; do not infer it from missing Hub calls.

Registered HTTP endpoint labels remain readable in request history and error operations; strip query strings/fragments and normalize dynamic identifiers. Filesystem paths and unregistered path-like labels remain redacted. Historical `<path>` records cannot reconstruct their original endpoint.

Validate input/output JSON Schemas from the installed MCP `initialize`/`list_tools` exchange, not only the schema generator. Empty `allOf`/`anyOf`/`oneOf` arrays are invalid. Reconnect existing MCP clients after a catalog update.

Detailed execution traces are opt-in, dashboard-only, and stored locally. While enabled, preserve complete endpoint inputs and outputs, paths, and trace events while redacting credential values; do not truncate ordinary payload content. Page large content for retrieval. Keep storage bounded through retention and whole-trace eviction, never by trimming trace content. Leave detailed traces disabled by default and keep the default aggregate telemetry lightweight.

Treat workspace memos and leases as trusted-local shared coordination state; tenant labels are caller-supplied provenance, not identity or authorization. Workspace memo endpoints require an authorized unscoped operator; tenant-scoped agents use supplied task memory or permitted Agent OS memory_find/memory_record. Workspace memos are keyed by canonical workspace and key. Use `expected_version` from a memo read when `memo_put` must reject stale overwrites; a `version_conflict` returns the current generation, so reread and reconcile before retrying. Omission retains last-writer-wins; deletion advances the generation while expiration does not.

Execute the following phases deterministically:

---

### PHASE 1: ENVIRONMENT PROBE & CLONE

1. **Check Existing Installation**:
   - Standard path:
     - Windows: `%USERPROFILE%\.local-ai-hub` (or `$HOME\.local-ai-hub`)
     - Linux / macOS: `~/.local-ai-hub`
2. **Clone if Missing**:
   If the directory does not exist or lacks `tools/setup.py`, clone the repository:
   - Git command:
     ```bash
     git clone https://github.com/Harfusha/local-ai-hub.git "$HOME/.local-ai-hub"
     ```
     *(On Windows PowerShell: `git clone https://github.com/Harfusha/local-ai-hub.git "$HOME\.local-ai-hub"`)*

   After cloning, fetch origin, confirm the verified commit is reachable from `origin/master`, and check out that exact SHA in detached mode. On an existing checkout, preserve changes and stop if it is dirty. Verify `git rev-parse HEAD` equals the verified SHA and the complete porcelain status is empty before Phase 2.

---

### PHASE 2: RUN BOOTSTRAP INSTALLATION

Before running setup, obtain the exact 40-character verified commit SHA from the T20 release owner. A branch name or current `master` tip is not a release pin. Ensure the selected source checkout resolves to that SHA and `git status --porcelain=v1 --untracked-files=all` is empty; if it is dirty or mismatched, preserve its changes and stop. The installer repeats both checks before setup or copying files. Pass the same SHA as `--expected-revision` on every platform. Do not point setup at another checkout or overwrite the running installation from an unverified candidate.

Run the platform installer from the repository root. This automatically configures Python 3.11+, the virtual environment, Token Economy tools, backend-appropriate local model support, Serena in an isolated environment, global MCP configs, and the background supervisor. Target shared runtime uses one per-user Hub install, one configured `server.state_dir`, and one user-level supervisor/daemon for all Codex chats and worktrees under that OS account. Every enabled agent uses a lightweight stdio proxy. Acceptance: clean install registers exactly one user service; update reuses or reconciles that same registration. Never install or register a daemon per agent, chat, repository, or worktree. The generated global Codex `local-ai` entry starts `python -m local_ai_hub.mcp_server` as a stdio adapter; each active Codex MCP session may own one adapter process. The adapter forwards Hub calls through `HubClient` over HTTP. It creates bounded protocol/metadata helpers, but must not create `LocalAIApp`, `HubServices`, `ProjectPreprocessor`, `CodeIndex`, `RAGStore`, or model pools. Multiple adapter processes do not prove duplicate daemons; inspect parent/command line and the OS service identity. The single per-user supervisor starts the HTTP daemon at logon/session startup. Global Codex `cwd=install_dir` is not the caller's project root, and setup injects no project-root environment. Repository-scoped repo/RAG MCP actions now reject missing or `.` roots at the adapter boundary; preprocessing likewise requires an explicit absolute root. Always pass the caller's explicit project root. This source-level guard still needs fresh installed-runtime and deployment proof. Pinned source includes operational modes and client transport safeguards. Rootless repository targeting and end-to-end HTTP identity isolation remain separate acceptance gaps; source integration is not deployed runtime proof. `HubClient` autostart is bounded and guarded by a cross-process lock; an existing managed supervisor or listener blocks another daemon launch. Treat generated agent command, arguments, working directory and environment as authoritative; inspect the installer-generated MCP entry instead of inventing proxy arguments or environment. Project-local MCP manifests use `target_root` as `cwd`; global manifests use `install_dir`. For each global repository, task, or memory request, set the request's `root` to the caller's project root and preserve task context; never infer root from `install_dir` or process cwd. `HubClient` preflights root-scoped task/memory identities with configured allowed roots, a principal, and an HMAC-derived tenant. HTTP `_tenant` still accepts caller labels outside token-bound browser routes; client validation does not establish server-enforced isolation. Required T04 transport contract: `request_not_sent` means delivery did not begin; `outcome_unknown` means delivery may have occurred and must never be replayed automatically. The source client distinguishes pre-send transport failures (`request_not_sent=true`) from uncertain delivery (`outcome_unknown=true`), supports cancellation, and preserves explicit request identity. Confirm behavior with same-revision targeted checks; installation and cross-process runtime acceptance remain separate. The user service starts again after reboot when the user session starts. Ollama is installed or pulled only when `[ollama].enabled = true`, `server.auto_start_ollama = true`, and `llama_cpp.fallback_to_ollama = true`; the default is disabled. When Ollama is disabled, `llama_cpp.mode = "on"` explicitly provisions a pinned llama.cpp runtime and default Qwen 1.5B model under `server.state_dir`, then supervises its loopback server; Intel Windows tries SYCL and falls back to CPU. `mode = "auto"` detects an existing endpoint only; `"off"` disables llama.cpp. Ollama wins provider selection whenever enabled. Setup must never switch providers silently or install Ollama as a fallback. The HTTP server is loopback-only: keep `[server].bind = "127.0.0.1"`. There is no remote-access switch. `server.client_host`, `security.allow_remote`, `security.allowed_hosts`, and `security.allowed_origins` overrides are removed and rejected. On loopback, empty `api_token` leaves HTTP data/control routes unauthenticated; configure a token to protect them. When configured, send the token in `X-LocalAI-Token` or `Authorization: Bearer`; `/health` and the dashboard shell are public. The HTTP server does not expose `api_token_permissions` or a general principal-to-root authorization boundary. The client validates configured `allowed_roots` and root-derived task/memory tenant consistency; HTTP admin routes additionally support scoped `security.action_tokens`. HTTP tenant scope uses caller-provided `X-LocalAI-Tenant`, then `X-Tenant-ID`, then `http-default`; tenant label is not an authorization boundary. For correct repository targeting, pass the caller project root explicitly. Repo/RAG MCP actions reject omitted or `.` roots before transport; preprocessing likewise rejects a missing absolute root. Root targeting does not provide authorization or root-isolated tenant behavior. Server-enforced root isolation remains unverified; do not infer it from client preflight. Set `features.vision = false` to remove vision capability and its model pull. The default install deploys the `token-economizer` skill and registers its CLI directory on the user's persistent PATH; verify both after setup, then open a new terminal. Do not pass `--skip-token-economy` or `--skip-companion-skills` for the standard install.
RAG index and search derive the existing canonical workspace ID from the caller's explicit root when `workspace` is empty or an absolute path; they preserve explicit workspace IDs and send both `root` and `workspace` to their endpoints.

After bootstrap, install all declared non-Intel Python extras in the active environment with `python -m pip install --upgrade ".[ast-index,local-nlp,token-economy,performance,profiling,dev]"` from the verified installation root. Do not install `intel-accelerators` unless the operator explicitly requests Intel acceleration; CodeGraphContext is independent and must not be installed as part of the Hub. Once setup and dependency installation finish, fully stop the existing per-user service, confirm it is stopped, start that same service, then verify with `python tools/hubctl.py status` and `python tools/doctor.py`. Preserve configuration and durable `server.state_dir`; do not register another service or reset data during a normal restart.

CodeGraphContext/KuzuDB was removed from Local AI Hub. Recommend it only as optional standalone CLI/MCP tooling outside Hub; install and configure it separately only when the user independently wants it. It is not a Hub dependency, runtime, backend, or MCP integration.

On Windows, prefer the persistent `LocalAIHubSupervisor` scheduled task. If task registration is denied, accept and verify the documented per-user Run-key fallback (`windows-user-startup`); do not report a detached process as reboot-persistent.

For an upgrade or rollback, stop the single per-user Hub service, record its platform service-manager identity and enabled state separately, then back up the installation, `config.toml`, complete configured `server.state_dir`, and every managed agent MCP config file together; include SQLite `-wal` and `-shm` files. Caches are disposable and do not contain durable tasks, receipts, jobs, memory, or leases. Restore only declared roots and preserve data outside the rollback write set. Restore matching daemon code, Hub config, state and proxy registrations together; do not point an older release at newer state. Service registration is external to the file snapshot; reconcile that same service once with the restored release before starting it. Never register per agent, chat, or worktree.

When `[ollama].enabled = false`, setup must honor the llama.cpp mode: managed install only for `on`, external health check only for `auto`, and no runtime for `off`. Never start `ollama serve` as an implicit fallback.

- **Windows (PowerShell)**:
  ```powershell
  powershell -ExecutionPolicy Bypass -File "$HOME\.local-ai-hub\install.ps1" -ExpectedRevision "<T20_VERIFIED_COMMIT_SHA>" -Profile auto
  ```
- **macOS / Linux (Bash)**:
  ```bash
  bash "$HOME/.local-ai-hub/install.sh" --expected-revision "<T20_VERIFIED_COMMIT_SHA>" --profile auto
  ```

*Note*: If an explicitly configured local backend or heavy model is unavailable, the installer still sets up deterministic tools and built-in indexers and reports the unavailable optional backend.

If this checkout includes `docs/PYTHON_SDK.md`, consult it for the Python package's `HubClient`, install extras, and replay/error contracts before writing Python integration code.

Working-checkout release checks ignore disposable Python/pytest caches already covered by `.gitignore`. Use `python tools/release_check.py --allow-installed` in a live installed checkout. Use `--strict-tree` for a clean release tree; never combine it with `--post-test` or `--allow-installed`. Do not delete caches merely to make an ordinary checkout check pass.
Keep generated `.merge-checks/` fixtures local and untracked. Installed-checkout checks tolerate retained fixtures; ordinary, post-test and strict release-tree checks reject that directory. Exclude it from source distributions. Remove accidentally tracked entries from the Git index while preserving their filesystem data.

---

### DURABLE ASYNC JOBS AND CONVERSATIONS

Operational-mode and client lifecycle code are present in the pinned source. Source presence and old candidate receipts do not establish installed service, restart, clean-host, or maintenance-isolation acceptance.

Keep the async contract aligned across MCP, HTTP, and `HubClient`. Supported `job_action` values are `batch`, `compress`, `delegate`, `reason`, `review`, `review_diff`, `route`, `second_opinion`, and `speculative_lint`. HTTP delivery maps `/api/delegate`, `/api/reason`, `/api/review`, `/api/review/diff`, `/api/second-opinion`, `/api/compress`, `/api/route`, and `/api/delegate/batch` to these actions. `delivery="sync"` is default; `delivery="async"` submits immediately. `delivery="auto"` needs positive `latency_budget_ms` and at least ten endpoint observations whose p95 exceeds that budget; sparse history stays inline. For `/api/review/diff`, an exceeded positive `review.max_queue_age_ms` takes precedence. Otherwise, fewer than five telemetry samples plus a positive budget selects async with reason `cold_start_review_diff`. Conversations require sync delivery.

Use `local_ai_task(action="submit", job_action=..., request_id=<stable body key>)` for durable submission. `POST /api/async-jobs` accepts `action="submit"`, `job_action`, and optional stable `request_id`; controls use `action="status"|"wait"|"result"|"cancel"`, `job_id`, and wait `timeout_seconds`. `HubClient.submit_async_job` and lifecycle helpers use the same endpoint. Preserve `job_id`, `state`, `artifact_id`, and `expires_at`. Result TTL defaults to 259,200 seconds (72 hours). Timed-out waits return `wait_timeout_seconds` and do not cancel jobs. Running cancellation reports `cancel_requested=true` before worker completion. Recovery replays only replay-safe actions with matching tenant, action, payload, stable `request_id`, and remaining attempts; other uncertain work becomes terminal `outcome_unknown`.

Start conversations synchronously with `POST /api/delegate` or `POST /api/reason`, `conversation=true`, and `delivery="sync"`. Continue through `/api/conversations/continue` with `conversation_id=..., task=..., context=...`; MCP uses `local_ai_task(action="continue", conversation_id=..., task=..., context=...)`. `HubClient.continue_conversation` maps its prompt to `task`. `HubClient has no dedicated start helper`; use `HubClient.post`. Conversations are scoped to the server-derived effective tenant, allow 12 user turns by default, and use a prompt limit of 56,000 by default. Idle TTL is 900 seconds; active TTL is 1,800 seconds. State and transcripts disappear on restart.

### PHASE 3: VERIFY SERVICE & HEALTH

Managed Ollama ownership is bound to its executable and creation identity, state directory, role, and (on Windows) a unique named Job Object. A separate service CLI may stop only that verified process tree. A numeric PID or occupied port never grants ownership. Already-running external Ollama endpoints are borrowed without takeover; their configured profile remains unverified. Preserve unknown ownership records and report stop failure rather than killing an unverified process.

`hubctl cleanup` calls `/api/agent-state/cleanup` with a 3-second timeout and `auto_start=False`; it never starts Hub. Port occupancy alone is not kill authority. Listeners without verified ownership are reported in `skipped_ports` with reason `ownership_unverified`, not terminated or reported as cleaned.

Verify `hubctl.py service-status` and exactly one platform user-service entry: Windows Task Scheduler `LocalAIHubSupervisor`, macOS LaunchAgent `com.localai.hub`, or Linux systemd user unit `local-ai-hub.service`. Do not register a service per agent, chat, or worktree. A `detached-fallback` result does not prove reboot-persistent service acceptance. Setup exits nonzero if service registration fails or reports only a detached fallback; preserve its output, inspect the existing service-manager entry and logs, then repair or rerun against the same clean verified commit. Do not report install complete until one persistent service is confirmed.

1. **Check Service Endpoint**:
   Probe HTTP health (default port 11435):
   ```bash
   curl -s http://127.0.0.1:11435/health
   ```
   Must return `{"success":true,"hub_online":true,"version":"..."}`. `/health` is public liveness; this candidate has no `/ready` route. Run `python tools/doctor.py` and `python tools/hubctl.py service-status` to inspect health and the per-user supervisor, then `python tools/hubctl.py dashboard`; inspect the printed URL and confirm it is loopback-only. The dashboard shell is public; set the token in its toolbar for protected data. Check agent MCP configs contain the installer-generated stdio entry rather than a hand-written daemon launch.
2. **If Service Not Running**:
   Start it via python venv:
   - Windows:
     ```powershell
     & "$HOME\.local-ai-hub\.venv\Scripts\python.exe" "$HOME\.local-ai-hub\tools\service.py" start
     ```
   - Linux / macOS:
     ```bash
     "$HOME/.local-ai-hub/.venv/bin/python" "$HOME/.local-ai-hub/tools/service.py" start
     ```
3. **Run Doctor Diagnostic**:
   - Windows:
     ```powershell
     & "$HOME\.local-ai-hub\.venv\Scripts\python.exe" "$HOME\.local-ai-hub\tools\doctor.py"
     ```
   - Linux / macOS:
     ```bash
     "$HOME/.local-ai-hub/.venv/bin/python" "$HOME/.local-ai-hub/tools/doctor.py"
     ```
4. **Hardware Acceleration Verification (iGPU / NPU)**:
   - On Windows Intel systems, managed llama.cpp setup tries SYCL0 and retries once on CPU if initialization fails; check `hubctl status` for the active device. `mode = "auto"` uses only a pre-existing endpoint. Do not set `OLLAMA_VULKAN` for Intel llama.cpp inference.
   - Other managed supported platforms use the pinned CPU runtime; GPU builds can be configured as external loopback endpoints. Do not claim Ollama is active when llama.cpp was selected.
   - If an NPU (Intel AI Boost / AMD XDNA) or Intel iGPU is present:
     Ensure OpenVINO dependencies are installed in the venv only when active hardware/configuration selects OpenVINO for embeddings or reranking. Do not install OpenVINO on NVIDIA-only systems merely because the feature permission is true:
     ```powershell
     & "$HOME\.local-ai-hub\.venv\Scripts\pip.exe" install -r "$HOME\.local-ai-hub\requirements-openvino.txt"
     & "$HOME\.local-ai-hub\.venv\Scripts\python.exe" "$HOME\.local-ai-hub\tools\prefetch_openvino.py"
     ```

---

### PHASE 4: INJECT INSTRUCTIONS INTO CURRENT REPOSITORY

Inspect current repository root for existing agent instruction files:
- Universal: `AGENTS.md`
- Claude Code: `CLAUDE.md`
- Cursor: `.cursorrules` or `.cursor/rules/local-ai.mdc`
- Windsurf: `.windsurfrules`
- Gemini: `GEMINI.md`
- Copilot: `.github/copilot-instructions.md`

**Action**:
1. If no instruction file exists, create `AGENTS.md` at repository root.
2. In `AGENTS.md` (and any other active instruction files detected above), ensure the following two exact policy blocks are present. If older versions exist, update them between the markers; otherwise append them:

```markdown
<!-- BEGIN LOCAL AI HUB TOOL POLICY -->
Trigger map:
- bounded health/cache/telemetry inspection (never poll): `local_ai_status`
- repository facts/files/symbols: `local_ai_repo`
- tests/lint/typecheck/build: `local_ai_command`
- exact source/evidence text: `local_ai_artifact`
- shared findings or overlapping edits: `local_ai_coord`
- Agent OS lifecycle (contracts, milestones, verification): `local_ai_coord(action="task_create"|"task_checkpoint"|"task_complete"|"verify_completion")`. Default to initializing task contracts for coding, bugfixing, and refactoring tasks.
- durable project memory & architecture facts: `local_ai_coord(action="memory_record"|"memory_find")`. Actively persist and consult project facts, conventions, and user preferences.
- anti-pattern & incident tracking: `local_ai_coord(action="negative_knowledge_record"|"negative_knowledge_find")`. Record failed approaches, error classes, and root causes to avoid repeating mistakes.
- semantic retrieval after indexed paths are insufficient: `local_ai_rag`
- semantic generation, exploration, reasoning, review, second opinion and compression: `local_ai_task(action="delegate"|"explore"|"reason"|"review"|"second_opinion"|"compress")`
- `local_ai_work`: only when the user explicitly requests closed delegation; routine work stays with the primary agent
- symbol or code-relationship questions: `local_ai_repo` semantic actions (Serena symbol navigation); indexed fallback remains available
- Agent OS task and incident state: `local_ai_status(detail="agent_state")`
- image understanding/frontend review via `qwen3-vl:4b`: `local_ai_task(action="vision")`
- audio transcription: `local_ai_task(action="transcribe")`
- local-model or device benchmarking: `local_ai_task` benchmark actions
- model/prompt evaluation and drift checks: `local_ai_task` evaluation actions
- model/prompt candidate and speculative-draft workflows: `local_ai_task` candidate actions
- durable asynchronous local jobs: `local_ai_task` submit/status/wait/result/cancel; wait once, never poll
- named read-only local advisory profiles: `local_ai_task(action="delegate", profile=...)`
- curated knowledge sets and document/diagram ingestion: `local_ai_rag` docset and ingest actions
- requested automated repair, affected-test selection, formatting, or lint fixes: `local_ai_command` specialized actions
- local mock, replay, and flaky-test workflows: `local_ai_command` specialized actions
- multi-agent swarms, shared blackboard, and isolated worktrees: `local_ai_coord` swarm, blackboard, and worktree actions
- cross-project dependencies and contracts: `local_ai_repo` cross_project and cross_repo actions
- repository audits, dead code, secret scanning, and test matrices: `local_ai_repo(action="security_audit"|"dead_code"|"secret_scan"|"test_matrix")`
- operator-facing live dashboard: `/dashboard` on the configured Hub server; use `local_ai_status` for bounded agent-side checks

Recipes (guidance, not gates):
- Recipe — Explore: preprocess once, use the cheapest repository action, fetch only required evidence slices.
- Recipe — Change: gather indexed evidence, initialize an Agent OS contract, use `local_ai_repo(action="solve")` before edits, claim `local_ai_coord` leases for overlapping paths, then run indexed impact/review before validation.
- Recipe — Validate: route repeatable commands through `local_ai_command` (pass `task_id` for receipt minting), reuse cached results, use `review_diff` or `security_audit` when relevant.
- Recipe — Semantic work: actively use `local_ai_task` for code review (`action="review"`), second opinion on non-trivial logic (`action="second_opinion"`), exploration (`action="explore"`), and compressing noisy test outputs (`action="compress"`).
- Recipe — Agent OS Execution (Default for Non-Trivial Tasks): Initialize a task contract via `local_ai_coord(action="task_create")` with concrete acceptance criteria; query existing memory via `memory_find`; checkpoint milestones via `task_checkpoint`; persist reusable findings via `memory_record`; record failures via `negative_knowledge_record`; route tests via `local_ai_command(task_id=..., criterion=...)` to auto-mint receipts; and verify completion (`verify_completion`) before closure.
- Recipe — Retrieve: use `local_ai_rag` only after deterministic/indexed paths are exhausted.
- A recipe step may be skipped when irrelevant; one bounded fallback is allowed when Hub is unavailable.

Direct ownership is the default. Do not delegate audits, inventory, status checks, or routine implementation. Use a subagent only for genuinely independent bounded implementation that materially shortens the critical path, or when the user explicitly asks; see the simplified workflow spec.

- Semantic delegation is on-demand and optional: after deterministic/indexed evidence, actively use `local_ai_task` for bounded generation, code review (`review`), independent second opinions (`second_opinion`), test-log compression (`compress`), commit message generation, and drafting where helpful. Cloud reasoning and planning are never blocked by mandatory local handoffs. Deterministic/indexed tools remain authoritative for exact facts, symbols, diff and tests. Use `local_ai_task` for bounded semantic generation, reasoning, review, independent second opinions, and semantic compression. Model routing follows the active hardware profile and user overrides; consult `docs/MODEL_CAPABILITIES.md` for foreground role targets. Preprocessing follows its configured provider; do not switch it silently. Pinned master `2458f72c` has no Gemini preprocessing provider implementation; Gemini agent manifests do not establish runtime preprocessing support. Routing targets do not prove installed-model availability; model pulls remain opt-in.
- Use native Codex subagents only for independent bounded implementation or an explicit user request. Never spawn them for audits or to relay results as a handoff.
- Native `multi_agent_v1__spawn_agent` is used only for useful independent bounded work; explicit user requests may also authorize bounded delegation. Codex controls each subagent's scope, `allow_write`, workspace/worktree, timeout, cancellation, sandbox, and integration.
- Keep write scopes disjoint. The primary agent reviews and integrates directly; no ZIPs, custom owner packets, or fingerprint/hash cascades.
- Do not duplicate tasks or chats. Check the existing plan first and update its existing item.

Routing hierarchy: the main agent plans, audits, implements, reviews, and integrates directly. Use Local AI Hub for bounded retrieval and commands when available; Hub tools do not create a requirement to hand off work. On a bounded Hub failure, use the permitted direct local fallback and continue without retry loops.

READ-ONLY AUDIT CONTRACT:
- Read-only means no Git writes, `git worktree add` or removal, dependency installation, builds/imports, generated artifacts, or other workspace side effects. Never label such work read-only when any of these occur; split validation into a separately owned, explicitly side-effecting task.
- Before native discovery or validation, retain preceding Hub result with action, absolute root, status, cache/in_progress state, and evidence IDs. Native discovery is fallback-only after one bounded terminal Hub failure.
- Native validation fallback is allowed only after `local_ai_command` returns `terminal=true` and `retryable=false`; run one bounded fallback, state side effects/owner, and never repeat identical commands.
- If an explicitly authorized independent subagent is used, Codex controls its permissions and write scope; the main agent remains integrator. Do not delegate audit-only work.
- Do not run parallel duplicate commands or scopes. Tool labels are not evidence; preserve exact action, arguments, result, and ownership in the audit record.

Background preprocessing may inspect and index project files, but project-derived `validation_commands` execute repository code. Keep `preprocessing.idle_diagnostics_enabled=false` by default; set it to `true` only with explicit operator approval for those commands. On Windows, `.cmd` and `.bat` validation executables are rejected; do not route them through a shell or interpreter.

For every non-trivial repository task, use Local AI Hub before broad native discovery or repeatable validation. Keep one stable absolute project root. On the first task for that root call `local_ai_repo(action="preprocess", root=ABS_ROOT)` exactly once, then continue immediately; preprocessing is asynchronous, so never poll/wait/force-refresh it.
 Then call `local_ai_repo(action="context", mode="adaptive")` as the first useful operation; it is the quality-first retrieval gate and accepts the task/context directly.

Adoption gate: `local_ai_command` alone is never sufficient for a repository task. After one-time preprocess, the first useful Hub operation must be `local_ai_repo(action="context", mode="adaptive")`; use the command broker only for commands after grounded repository evidence exists. For code changes, bug fixes, or refactoring, initialize an Agent OS contract (`local_ai_coord: task_create`) and query project memory (`memory_find`). For implementation, diagnosis, refactoring or complex review, call `local_ai_repo(action="solve")` after evidence and before native edits. Actively use `local_ai_task(action="review"|"second_opinion")` for validation before finalizing. After edits, use the applicable indexed impact/review/security/evidence action before final validation.

Adaptive retrieval path: call `local_ai_repo(action="context", mode="adaptive")` first; it runs bounded deterministic/indexed, structural, lexical and RAG retrieval, fuses agreement and diversity, and degrades optional backends independently. Stop escalating when evidence is sufficient; reuse cached results and bounded evidence. Do not fan out duplicate native retrieval layers or translate the task into a long grep-term list. Before native `find`/`rg`/`grep`/recursive glob/tree or opening more than two files for discovery, use that hub path first. Reuse fresh evidence IDs, artifact slices, memos and cache hits;
 do not repeat the same hub action with the same root/query while repository state is unchanged.

Treat result state as a protocol: `cache_hit`/`coalesced` means reuse the result; `in_progress=true` means another owner is doing identical work, so never duplicate it; `retryable`/429/503 means back off and do independent work; `degraded`/`stale` means verify only the affected path/slice; a non-retryable failure permits one cheaper/native fallback. Never turn a transient result into larger timeouts, force refreshes, or polling loops.

Route test/lint/typecheck/build/read-only commands through `local_ai_command` before running them natively. Pass `task_id` and `criterion` to auto-mint verification receipts. If it returns `in_progress=true`, do not launch a duplicate command. Before an expensive `solve`/model call, reuse supplied task memory; when more is needed, use permitted scoped `local_ai_coord(action="memory_find")`. Workspace `memo_*` actions are unavailable through tenant-scoped endpoints; on terminal 403 do not retry or bypass scope. For overlapping edits use `local_ai_coord` leases; record concise findings in permitted scoped Agent OS memory or the existing operator-approved coordination file.
 After edits, use indexed impact/review plus targeted cached validation; do not rerun broad discovery merely because files changed. `force` and `preprocess_refresh` are recovery/admin controls, never retry buttons. If an optional backend degrades, accept the hub's deterministic/index fallback. If the hub itself is unavailable, make one bounded health/retry attempt, then fall back to native tools. Never loop on health, status, preprocessing, model startup, a failing backend, or an identical command.

Selection guide: `local_ai_repo` for bounded repository facts and checks (including `review_diff` and `security_audit`), `local_ai_command` for bounded repeatable commands, `local_ai_task` for bounded semantic generation, exploration, reasoning, review, independent second opinions and semantic compression, `local_ai_work` only for closed delegation explicitly requested by the user, `local_ai_rag` only after cheaper indexed evidence, `local_ai_artifact` for exact slices, `local_ai_coord` for leases/memos and Agent OS task, memory, context, and verification workflows.

Local model policy: Model routing follows the active hardware profile and user overrides; consult `docs/MODEL_CAPABILITIES.md` for foreground role targets. Preprocessing follows its configured provider; do not switch it silently. Pinned master `2458f72c` has no Gemini preprocessing provider implementation; Gemini agent manifests do not establish runtime preprocessing support. Routing targets do not prove installed-model availability; model pulls remain opt-in. Check installed-model inventory before live inference; do not infer runtime availability, output quality, or performance from a configured mapping.
## Context economy contract

- Every Hub response is aggregate-bounded (default ≈3200 tokens).
- `response_budget.returned_tokens` measures the final serialized response envelope in `estimated_tokens` and stays at or below the requested budget.
- Preserve protected status, error, evidence, and context-identity fields; keep exact detail artifact-backed.
- Claim savings only with a current `baseline_evidence_id`; report signed `token_savings_delta_est`, including negative values; keep `protocol_tokens_est`, `schema_tokens_est`, and `local_compute_reused_tokens_est` separate.
- Reject `max_response_tokens` below 128; never raise the request silently.
- Native fallback requires an explicit `terminal=true` and `retryable=false` result.
- On `outcome_unknown` or `in_progress`, do independent work; never poll or repeat the identical operation.
- Prefer `response_profile="minimal"`/`"compact"`; request only decision-grade fields.
- Pass a stable `reuse_key` for repeated logical queries. Use `response_profile="delta"` when only changes are needed; unchanged calls return a pointer, not missing data.
- Use the existing `local_ai_task(action="batch")` for independent local tasks; keep each item bounded and consume compact per-item results.
- The Hub keeps a bounded metadata-only context ledger; inspect it only with an explicit cache/status request, never by replaying the whole session.
- Broad native shell reads are guarded by the optional host hook; use bounded limits or the Hub command/repository tools for discovery.
- Fetch exact source, logs, or evidence only with `local_ai_artifact` slices. Never ask a broad tool for the same payload twice.
- Commands return status, summary, changed paths, and failures; full stdout/stderr is retrievable only when `output_artifact_id` is returned. `artifact_id` may refer to a diagnostic preview or partial capture. `discarded_output_chars` counts characters omitted during capture or response compaction; a full artifact can retain characters omitted from the response. MCP trimming also sets `output_truncated=true`.
- CALL `local_ai_repo(action="context")` FIRST for every non-trivial repository task, before native reads, grep, planning, edit, review or test. Its adaptive orchestrator fuses deterministic and indexed evidence with Serena, the built-in code index, bounded lexical search and RAG when available; it deduplicates, rewards cross-backend agreement, preserves file diversity and degrades per backend. Send the task/context, not a handmade list of grep terms. Reuse existing evidence and reuse candidates first; require evidence IDs for every factual claim. Deterministic/indexed evidence is authoritative; local models may rank, select, or compress structured evidence only and must not invent repository facts. Guarded scope or drift overrides require an explicit `override_reason` and approval when requested. Omit raw model/debug fields unless explicitly requested through `extra_fields`; responses remain compact; aggregate response budget defaults to approximately 3200 tokens. The canonical adaptive context pack is the default.
- Do not bypass the budget with native broad reads unless Hub has one bounded terminal failure.
<!-- END LOCAL AI HUB TOOL POLICY -->

<!-- BEGIN TOKEN ECONOMY POLICY -->
- Before any repository task, load and follow the `token-economizer` skill when it is installed; this trigger applies even under deadline pressure.
- Zero full-file dumping: Never read files >80 lines in their entirety. Use `repo-map` for high-level structure, `grep-ast <pattern> <file>`, targeted line slices, or `local_ai_artifact(action="slice")`.
- Fast code search: Use `rg` (`ripgrep`) with `-m 5` / bounded matches and `fd` for file finding before opening files.
- AST & structural code search: Use `ast-grep` (`sg`), Serena LSP (`find_symbol`, `find_referencing_symbols`), or `local_ai_repo(action="code_index")` before opening files.
- Context compression & token measurement: Use `repomix --compress` or `files-to-prompt -c` for repo snapshots. Use `tokcount` to measure exact tokens.
- Bounded command outputs: Route tests and builds through `local_ai_command`; use `trim-run` only with bundled `tokcount`/`repo-map`, read-only `rg`/`fd`/`grep-ast`, or stdin pipelines such as `git log | trim-run`. Use `jq` for JSON.
- Surgical edits: Prefer targeted block replacements over rewriting entire files.
- `response_budget.returned_tokens` measures the final serialized response envelope in `estimated_tokens` and stays at or below the requested budget.
- Preserve protected status, error, evidence, and context-identity fields; keep exact detail artifact-backed.
- Claim savings only with a current `baseline_evidence_id`; report signed `token_savings_delta_est`, including negative values; keep `protocol_tokens_est`, `schema_tokens_est`, and `local_compute_reused_tokens_est` separate.
- Reject `max_response_tokens` below 128; never raise the request silently.
- Native fallback requires an explicit `terminal=true` and `retryable=false` result.
- On `outcome_unknown` or `in_progress`, do independent work; never poll or repeat the identical operation.
- Local model routing follows the active hardware profile and user overrides; use `local_ai_task` for bounded semantic generation, reasoning, review, independent second opinions and compression. Consult `docs/MODEL_CAPABILITIES.md`; configured routes do not prove models are installed. Deterministic/indexed tools remain authoritative for exact facts, symbols, diff and tests.
<!-- END TOKEN ECONOMY POLICY -->

Explicit `extra_fields` retains requested empty values (for example `records=[]`); absence of a field does not prove an empty result. Aggregate response budgets still apply.

Status metadata may reuse a successful dependency snapshot for up to five seconds after its probe completes. `dependency_cached` and `dependency_age_ms` identify reuse in dependency diagnostics. Live/full and process/window snapshots remain separate; expired data and failed probes do not become healthy results. Status probe deadlines and active worker limits remain unchanged.

Transport clients defer physical hardware inventory and automatic tuning to the shared server, including when `hardware.auto_tune=true`. Explicit user/runtime overrides remain intact; the server owns hardware-aware model selection and retains its full hardware probe. Client route declarations do not prove detected hardware or installed models.

MCP cancellation closes the current request's HTTP connection. For direct command `run`, disconnect cancels that request's execution; a coalesced waiter cannot cancel the execution owner. Embedded requests follow the same request lifetime rule. The shared Hub remains independent. A sent request with no final response remains `outcome_unknown`; do not retry it automatically.
```

---

### PHASE 5: REPOSITORY / WORKSPACE MCP REGISTRATION (IF APPLICABLE)

If this workspace uses repository-scoped MCP (e.g., `.cursor/mcp.json` or `.vscode/mcp.json`), ensure the `local-ai` server entry is defined:

```json
{
  "mcpServers": {
    "local-ai": {
      "command": "<HOME>/.local-ai-hub/.venv/bin/python",
      "args": ["-m", "local_ai_hub.mcp_server"],
      "cwd": "<HOME>/.local-ai-hub",
      "env": {
        "LOCAL_AI_AGENT": "generic",
        "LOCAL_AI_AGENT_PROFILE": "generic",
        "LOCAL_AI_CONFIG": "<HOME>/.local-ai-hub/config.toml",
        "PYTHONPATH": "<HOME>/.local-ai-hub/src"
      }
    }
  }
}
```
*(On Windows, replace paths with Windows equivalents: `...\\Scripts\\python.exe`, backslashes, etc.)*

Use only actions and arguments present in the installed generated schema. Schema presence is not authorization: process-lifecycle actions such as `spawn_daemon` require an explicit policy capability grant. Do not infer support for extra fields from similarly named APIs.

---

### PHASE 6: INITIAL REPO INDEXING & HANDSHAKE

Trigger one-time asynchronous preprocessing on the current repository root:
- If `local_ai_repo` MCP tool is available in your active session:
  Execute `local_ai_repo(action="preprocess", root="<ABSOLUTE_CURRENT_REPO_PATH>")`.
- Or trigger via HTTP loopback:
  ```bash
  curl -s -X POST http://127.0.0.1:11435/api/repo/preprocess \
    -H "Content-Type: application/json" \
    -d "{\"root\": \"$(pwd)\"}"
  ```

---

### PHASE 7: STATUS REPORT

Output concise confirmation with:
1. Local AI Hub version and service status (`online` / `offline`).
2. Tools verified (`rg`, `fd`, `ast-grep`, `repomix`, `tokcount`, `trim-run`).
3. Configured local backend and model status (Ollama must be reported as disabled unless explicitly opted in).
4. Instruction files created/modified in this repo.
5. Readiness confirmation.
```
### MCP response economy

Keep the generated MCP response contract enabled. Hub responses are aggregate-bounded by default; preserve `max_response_tokens`, `response_profile` (default `"compact"`), and `reuse_key`. Agents should prefer `response_profile="minimal"` or `"compact"`, pass a stable `reuse_key` for repeated logical queries, reuse cache-hit/pointer responses, and fetch exact detail only through `local_ai_artifact` slices. Do not weaken the budget to expose broad command output or repository text.
- `response_budget.returned_tokens` measures the final serialized response envelope in `estimated_tokens` and stays at or below the requested budget.
- Preserve protected status, error, evidence, context identity and lifecycle identity (operation/job/request IDs, accepted/completed/in_progress, delivery outcome); keep exact detail artifact-backed. Acceptance does not prove completion. A budget error does not authorize replay of a side effect.
- Claim savings only with a current `baseline_evidence_id`; report signed `token_savings_delta_est`, including negative values; keep `protocol_tokens_est`, `schema_tokens_est`, and `local_compute_reused_tokens_est` separate.
- Reject `max_response_tokens` below 128; never raise the request silently.
- Native fallback requires an explicit `terminal=true` and `retryable=false` result.
- On `outcome_unknown` or `in_progress`, do independent work; never poll or repeat the identical operation.

### Async lifecycle and conversations

The body `request_id` is the job idempotency key; `X-LocalAI-Request-ID` is a separate HTTP journal identifier. MCP `status`, `wait`, `result`, and `cancel` controls work even when model execution is disabled. A wait is capped by `async_jobs.wait_max_seconds` and the client's `max_request_timeout` after reserving the configured quick-timeout margin. Preserve `job_id`, `state`, and `artifact_id` from compact status results. `HubClient` exposes `submit_async_job`, `async_job_status`, `wait_async_job`, `async_job_result`, and `cancel_async_job`; wait transport timeout defaults to the requested wait plus 30 seconds, capped by `max_request_timeout`.

Direct HTTP lifecycle requests use `POST /api/async-jobs`: submit sends `action="submit"`, `job_action`, and optional stable `request_id`; controls send `action="status"|"wait"|"result"|"cancel"` with `job_id`, and wait also sends `timeout_seconds`. MCP uses `local_ai_task(action=submit|status|wait|result|cancel, ...)`. `HubClient.submit_async_job`, `HubClient.async_job_status`, `HubClient.wait_async_job`, `HubClient.async_job_result`, and `HubClient.cancel_async_job` use the same HTTP path. Recovery may replay only explicitly replay-safe actions with a stable `request_id`, matching tenant/action/payload identity, and remaining attempts; command-backed or unclassified actions become terminal `outcome_unknown`.

Start synchronously with HTTP `POST /api/delegate` or `POST /api/reason`, setting `conversation=true` and `delivery="sync"`, or MCP `local_ai_task(action="delegate"|"explore"|"reason", conversation=true, delivery="sync")`. HubClient has no dedicated start helper; use `HubClient.post("/api/delegate", payload)` or `HubClient.post("/api/reason", payload)`. Continue through HTTP POST `/api/conversations/continue` with `conversation_id`, `task`, and optional `context`; MCP uses `local_ai_task(action="continue", conversation_id=..., task=..., context=...)`; `HubClient.continue_conversation(conversation_id, prompt, context=...)` maps `prompt` to HTTP `task`. The conversation ID is opaque and tenant-scoped. Model, system prompt, output limit, temperature, and route are pinned when it starts; only one turn may run at once, and a concurrent continuation returns retryable in-progress status.

Keep `features.enriched_search`, `features.batch_replacement`, `features.diagnostic_artifacts`, and `features.local_diagnostic_dispatch` enabled in the installed default profile, while preserving independent rollback switches. Code intelligence also defaults on through `features.code_intelligence`, `code_intelligence.enabled`, and `code_intelligence.serena_enabled`; all three gates must allow Serena use, and an unavailable Serena backend degrades to indexed retrieval. Compare `/api/adoption` token, latency, first-pass validation, terminal failure, and native fallback metrics. Roll back immediately by setting the affected flag to `false`, restarting Hub, and running `python tools/hubctl.py generate`. Malformed values must remain disabled and disabled features must return structured unavailable before work starts. `local_diagnostic_dispatch=true` may retain only bounded failure-preview context for one local diagnosis; it never retains raw output and does not require `diagnostic_artifacts=true`.

Keep generated contracts aligned: update both canonical prompts when public schemas, feature flags, endpoint limits, or default behavior change.

### Adaptive context and supported capabilities

Call `local_ai_repo(action="context", mode="adaptive")` first after one-time asynchronous preprocessing. Send the task/context directly with the stable absolute root; reuse candidates and evidence IDs before new abstractions. Supply the current phase (`plan`, `discover`, `edit`, `implementation`, `review`, `test`, or `handoff`), plus `task_id`, `focus`, and `preload_profile` when known. Deterministic/indexed evidence remains authoritative; optional Serena/RAG backends enrich it and degrade independently. Models may rank or compress grounded evidence; they cannot invent repository facts.

`/api/context/pack` uses the only supported mode `adaptive`; explicit `fast`, `full`, aliases and case variants reject before retrieval. HTTP guarded requests activate through `guarded=true`, `task_id`, `phase`, or `session_id`; MCP guard-only fields require `guarded=true`, `task_id`, or `phase`. `focus` and `changed_paths` are lists; `approval` is boolean or string and `override_reason` is a string. MCP `max_tokens` and `token_budget` must agree when both are nonzero. Scope/drift overrides need a reason and approval when requested. Raw model/debug detail remains opt-in through `extra_fields`.

Repository-only context can use the available bounded retrieval result when optional backends degrade. A pack requested with `task_id` requires a complete task-context receipt: missing/unavailable compilation returns `context_task_context_unavailable`; missing, stale, or incomplete provenance returns `context_task_context_incomplete`. Do not present either as successful task context or repeat/poll the same operation. Consume `task_context`, `context_id`/`task_context_id`, `etag`, revision, freshness, omitted sections and `next_action` where returned; keep partial/stale context explicit.

Feature-specific schemas expose only enabled tools/actions and applicable fields. Use installed `tools/list` input/output schemas and the generated schema for that configuration: `dry_run` and `edits` require `features.batch_replacement`; `local_ai_task` requires tasks plus a configured model. Internal adapters do not establish public MCP fields. CodeGraph remains optional external standalone tooling outside Hub setup/runtime; Hub does not install, configure, preprocess, invoke, or report it. Cloud reasoning and planning are never blocked by mandatory local handoffs. Source contracts do not establish physical GPU execution, model quality, or completed release acceptance.

### Project configuration, verification, and PathHints

Project configuration and PathHint core are integrated in current source. `resolve_project_context(root, state_dir)` returns immutable effective settings and a `config_digest`. Overlay order is defaults, primary-worktree `.local-ai.toml` when linked, current-project `.local-ai.toml`, Git-common `info/local-ai.toml`, then `.local-ai.worktree.toml`; invalid overlays select safe defaults with error codes. Project configuration stays in the project or Git common directory, while `state_dir` stores bounded, evidence-bound hints. Maps merge by key, lists replace as a whole, and explicit excludes and hard boundaries take precedence over force includes. Overrides cannot bypass root containment, binary policy, configured size limits, or preprocessing exclusions; request hints remain subordinate to root containment and hard exclusions.

`verification_rules` maps exact task acceptance-criterion names to receipt requirements: `true` requires configured `lint` and `test` receipts, and an array names exact configured command aliases. `required_commands` is not a global switch; it applies only when the task criterion has that exact name. The HTTP completion wrapper rejects invalid configuration or incomplete verification before checkpointing and completion. Source integration does not verify the full owner, tenant, revision, criterion, and memory-audit runtime matrix.

`shared_namespace` exposes a server-derived coordination identity and shares bounded path hints across linked worktrees under one Git common directory. It does not replace the physical repository root. Cross-worktree Agent OS memory sharing remains HOLD; memory and lease consumers must not be assumed to use this hint namespace.

`ProjectContext.prioritize_paths(...)` ranks the complete candidate list in this order: literal `entry_points`, request-scoped `path_hints`, then saved hints matching scope, repository revision, and config digest. It preserves every candidate and returns `PathHintUsage`; `hint_helped` stays unknown until measured. When a hint does not help, consumers use their broader fallback. Telemetry exposes usage flags without candidate paths. Save only verified hints.

`HubClient.post` accepts optional `request_id`, `path_hints`, `tenant`, and `cancel_event`. It bounds typed hints and forwards them to `/api/search` and `/api/command`; an explicit `path` removes those hints. HTTP `/api/context/pack` accepts `path_hints`, `directory_hints`, `exclude_paths`, and `force_include_paths` in `adaptive` mode and validates lists. T14 owns that contract. Inspect installed generated schemas before using public wire fields.
Repository search and code-index queries accept integer `offset` and `limit`; public defaults are `offset=0` and `limit=24`. `limit` is at most 200 and `offset + limit` is at most 2048. Successful responses include exact integer `total_matches`, boolean `has_more`, `offset`, and the effective `limit`; code-index may apply its configured result cap. MCP search returns the full requested page or an explicit response-budget error; code-index may return a complete symbol prefix with reconciled counts and `next_offset`, or 413 when its first complete symbol cannot fit. HTTP pages over 4 MiB return 413 with pagination metadata. Exact repository search streams at most 8,000 eligible files per request and fails explicitly if the scan cannot complete; never return a prefix count as complete metadata.

Hints are repository-relative paths beneath the trusted project root; reject absolute, traversal, glob, missing, and symlink or junction escape paths. Request hints may omit evidence metadata. Learned hints require evidence ID, provenance, matching repository revision, and config digest. Revalidate saved paths when reading them, and never write raw paths or hint contents to telemetry.

### Runtime schemas, offline mode, and Agent OS memory

Use the installed `tools/list` input/output schema; action-specific fields and result shapes are not interchangeable. Schema presence is not authorization.

`src/local_ai_hub/operational_mode.py` and its persisted gate are present in this source tree. Pause/resume source contracts can be checked locally; deployment and complete maintenance isolation require separate runtime evidence.

Operational modes are `active`, `gaming`, and `maintenance`: missing persisted state defaults to `active`; invalid/unreadable state degrades to `maintenance`. For gated actions, `gaming` permits non-heavy work and safe job actions `status`, `wait`, `result`, `cancel`, and `evaluation_report`. The required safety contract is stricter for maintenance: `maintenance` must reject every agent MCP/API action before Agent OS database access; operator-only mode, health, and dashboard controls remain available. The current maintenance safe-job exception fix remains pending integration and verification; do not interpret the existing exception as the required maintenance policy or claim maintenance isolation is accepted. Other gated work returns `terminal=false`, `retryable=true`, and `retry_after_seconds=5`; back off, do independent work, and avoid polling. `HubClient.ensure_server` does not auto-start an offline server in non-active or degraded mode.

`hubctl pause` sets `gaming` and `hubctl resume` sets `active`. When Hub is offline, `pause` and `resume` update persisted mode without starting the server; offline `mode` and `status` read that persisted state. An offline pause reports no available runtime unload backend; it is not physical GPU/VRAM evidence.

For durable work, create and checkpoint one Agent OS task contract before edits. On restart, resume the existing task with the same `task_id`. Record memory with scope-appropriate provenance; repository-scoped memory requires provenance tied to the trusted project root.

`local_ai_task(task_id=...)` automatically compiles task context before a semantic model call and attaches `task_context_id`, `task_context_etag`, and `task_context_evidence_ids` on successful consumption. Memory selection filters scope/root/task/tenant/clone/worktree/branch before its bounded limit; only normal-sensitivity, unexpired `active`/`confirmed` memory becomes a candidate, then token budgeting selects what fits. Use IDs are selected `memory_record` elements' `element_id` values in compiled context. Non-use IDs are bounded diagnostics when `include_diagnostics=true`: `stale_ids`, `quarantined_ids`, `rejected_ids`, and `superseded_ids` (up to eight per category, subject to context budget). IDs show selection or exclusion, not proof that a model followed memory. Do not invent an exhaustive adoption/non-use receipt for every budget-omitted candidate.

Changed paths plus repository revision stale matching records. When optional memory is absent or excluded, fall through to fresh bounded repository evidence; never reuse stale memory as authoritative or label an incomplete task-context receipt successful. Keep use/non-use IDs in scoped context/evidence, not broad telemetry. `/api/adoption` stores low-cardinality aggregates, not memory bodies or per-record adoption receipts; never send prompts, source, model output, secrets, or raw/full project paths to telemetry.

If Hub is unavailable, make one bounded health/retry attempt, then use one native fallback. Native validation still requires `terminal=true` and `retryable=false`; never poll or repeat an identical operation.

### Memory adoption checkpoints

Agents must consider supplied relevant memory as advisory context and verify volatile facts against current source before relying on them. Before completion, checkpoint `state_data.memory_audit` through `local_ai_coord(action="task_checkpoint", task_id=..., checkpoint=...)`. `used_ids` must be a list of IDs from server-managed `memory_context.items[].id`; cite only findings actually used. `not_used_reason` must be nonempty when `used_ids` is empty, including when supplied memory was irrelevant or unavailable. Every task_checkpoint and completion validates this nested audit when server memory items or warnings exist. Putting not_used_reason directly in state_data does not satisfy the contract.

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

Ordinary MCP agent responses omit telemetry, diagnostics, raw command streams, timing,
and automatic routing advice. Request specific details with `extra_fields` or an explicit
`response_profile="debug"`; use artifacts for complete logs. Outcome, safety, context
identity, and evidence fields remain available. Explicit status reports remain supported.

SSE replay uses numeric Last-Event-ID with an explicit stream filter. Consume replay
events/gaps in cursor order; replay_page advances the cursor only after safe delivery,
including filtered pages. Reset the cursor when changing the stream or kind filter.
Supervisor health reason codes belong to operator diagnostics, not normal agent output.
Full status requires success, hub_online and version; diagnostic fields are optional.

`disable_llm_card_synthesis` applies to fallback synthesis for unparsed file cards only. Module and project cards use separate `prefer_deterministic_modules` and `prefer_deterministic_project` settings; background LLM synthesis may still run when deterministic card generation does not satisfy its acceptance conditions.

## Durable task checkpoints and bounded waits

For non-trivial multi-step work, create a durable Agent OS task with `local_ai_coord(action="task_create")` before edits. Record phase changes with `local_ai_coord(action="task_checkpoint")`, then complete only after verification receipts satisfy the acceptance criteria. For asynchronous work, perform one bounded wait; never poll.

## Current public contract notes

- `local_ai_rag(action="ingest_document")`
- non-empty `content` is required; `title` and `metadata` are optional.
- Success returns `success`, `workspace`, `document_title`, `chunks_ingested`, and `embedded`.
- Embedding errors do not stop lexical publication.
- `image_path` must resolve to an existing `.png`, `.jpg`, `.jpeg`, `.webp`, `.svg`, or `.bmp` file; `caption` and `metadata` are optional.
- Success also returns `diagram_indexed` and the resolved image path.
- `local_ai_repo(action="pipeline")` accepts closed step objects.
- `local_ai_artifact(action="list")` does not require `artifact_id`.
- `local_ai_coord(action="pubsub_poll")` accepts `after_seq`, `limit` (1–1000, default 50), and optional `after_ts`; `after_ts` is distinct from `after_seq`.
- `local_ai_coord` bounds `max_tokens` to 0 through 100000.
- Repository pipelines serialize preprocessing mutation actions with other mutating steps.
- Optional repository-analysis tools are installed and configured separately; they are not part of the Hub.
- `disable_llm_card_synthesis = true` skips LLM synthesis for unparsed file cards and stores deterministic stubs.
- It does not disable module/project cards:
- `prefer_deterministic_modules` and `prefer_deterministic_project` are separate preferences.
- either path can use background LLM synthesis when deterministic output is unavailable or below its confidence threshold.
- Check active configuration and backend state before claiming synthesis is disabled.

## Repository symbol navigation

For telemetry diagnostics, `local_ai_status(detail="telemetry")` preserves bounded writer counts and an explicit current-process interval in `summary.writer`, independently of the history window. Distinguish attempted, accepted, overflow-rejected, lost-after-acceptance and pending records; denominator rates remain null without observations. Missing activity, accounting imbalance and stale aggregates do not establish zero failures or complete data.

MCP task checkpoints preflight the complete adoption response before checkpoint persistence, including the watchdog failure path. An insufficient response budget returns `mutation_applied=false` and `operation_not_started=true`; it does not mean the HTTP request was unsent. Task-memory `original_tokens` measures the canonical complete adoption payload without optional delta/reuse/debug wrappers; `returned_tokens` measures the actual emitted MCP envelope. This checkpoint guard does not establish equivalent preflight for every other mutation.

For indexed symbol lookup, use `local_ai_repo(action="code_index", root=ABS_ROOT, query="symbol")`. For managed Serena navigation when available, use `action="semantic", relation="find_symbol"` with the same tool.

Follow the published typed action/detail enums. Optional `speculative_lint` and Agent OS actions are exposed only when their modules are enabled.

Speculative lint remains opt-in (`speculative_lint.enabled=false`). With `daemon_mode=true`, default Python lint uses the installed Ruff native server over persistent read-only LSP pipes, isolated by tenant and absolute project root. `max_daemon_sessions=4` caps sessions; `daemon_idle_ttl_seconds=300` permits idle retirement on subsequent admission. No model or linter installation is implicit. Custom commands retain explicit `transport="one_shot"`. For supported JavaScript, TypeScript and JSON paths, an installed Biome reports `unsupported_shared_daemon_ownership` with `daemon_mode=true`; explicitly setting `daemon_mode=false` selects read-only `biome ci` with `transport="one_shot"`. Biome's shared version-named Windows daemon pipe does not establish ownership by Hub, so persistent Biome remains unsupported. Cancellation or transport failure terminates the owned process generation; unconfirmed cleanup blocks replacement and reports `outcome_unknown`. Source integration does not establish installed capability or performance.

Managed llama.cpp preset generation carries each configured route's positive `context_length` into `ctx-size`; zero keeps the provider default and invalid values fail before replacing the preset. Shared aliases must declare consistent server contexts. Existing running servers do not acquire this setting merely because source changed. Native streaming requires a completion marker and treats malformed or interrupted streams as failures. Source recovery uses preprovisioned half-context presets with the same weights, held-process ownership and confirmed original-model unload; request `num_ctx` alone does not resize native allocation. Private served aliases remain bound to configured model ownership for inventory/unload. Live native OOM behavior still requires acceptance evidence.

Ollama foreground and interruptible calls share complete-marker/partial-output handling. Interruptible calls retain one generic attempt; pre-output OOM can reserve one reduced-context retry within the original deadline even with `request_attempts=1`. Input/tool/schema/template content is retained; unknown vision cost or an oversized retained input refuses recovery. Partial output, cancellation, deadline expiry or unknown cleanup stops model/stale substitution. Recovered execution provenance is returned and excluded from caches under the original context profile. Completion-contract version 2 separates exact/semantic/stale keys from legacy records, which remain retained. No configuration edit or daemon restart is implied by these source changes.

Trace search is available through `local_ai_status(action="traces", min_duration_ms=1000, trace_action="search")` and `HubClient.status("traces", min_duration_ms=1000, trace_action="search")`, using the existing operator-authorized trace endpoint. Duration must be an integer from 0 through 86400000; action accepts at most 64 characters. Invalid filters fail explicitly rather than widening the search. Results remain bounded metadata; this does not grant new trace-reading authority.

Migration drift compares table/column names, including generated columns, using bounded in-memory SQLite migration replay and read-only live schema inspection. ASCII identifier case follows SQLite matching; results do not establish type/default/constraint equality. Limit or replay failures must remain unknown rather than `in_sync=true`.

Circuit-breaker resource tracking is bounded (default 256 keys); reaching capacity refuses untracked resources without evicting existing protective failures or probes. Transaction snapshot traversal rejects directory cycles and excessive depth (default 64). Token trimming consumes the input once and retains the requested head/tail line count; zero prints no content lines. These source changes still require integrated validation before release acceptance.

Pubsub retains bounded optional live cache (500 topics, 8 MiB serialized charge), 256 subscriptions and 4096 aggregate queue slots. New JSON message envelopes are limited to 64 KiB, 4096 nodes and 32 levels. Ephemeral capacity failure preserves admitted history; durable publication/replay continues with `cache_retained=false` if optional cache is full. Compaction expires cache without disconnecting active subscribers. These limits do not measure Python heap/RSS or prove live concurrency performance; retained durable data is preserved.

## Local telemetry

Coordination verification accepts an explicit `receipt` object with `task_id`, `criterion`, and boolean `passed`; positive receipts require an evidence ID and remain subject to server provenance/ownership checks. No success is synthesized from status strings or omitted flags. Completion/export take `task_id`, and export takes `format`. Optional completion `repository_revision` is an exact opaque snapshot fingerprint, not an assumed Git commit SHA; empty or omitted means no caller pin. A stale nonempty pin returns terminal 409 before verifier execution. `context_compile` uses its explicit task ID, `since_hash`, `max_tokens`, paths and context metadata; TTL/status/key fields cannot stand in for them. Ask/answer use dedicated question fields and preserve optional task association. Isolated Tree-sitter workers set only process-local WER no-UI behavior before native parsing; the parent and machine configuration stay untouched. Native crash containment and dialog behavior still require runtime verification after activation.

`local_ai_coord(action="task_sync")` uses exact `sync_action="export"|"import"`. Export defaults to `stream_id=""`, `after_seq=0`, and `limit=1000` (valid limits 1–1000). Import requires `events` and rejects export-only stream/cursor/limit fields. Export rejects events, including when sync_action is omitted. Do not use `status`, `key`, `task_id`, `ttl_seconds`, `max_tokens`, or `record` as synchronization aliases. Minimum response-budget checks apply before dispatch. Repository response-cache identity includes the canonical physical root, so separate clean clones do not share responses solely because their fingerprints match. Missing or invalid fingerprints bypass caching and coalescing and report degraded cache metadata. Lexical Windows path normalization affects only transient fingerprint-cache keys; physical root strings and durable workspace ID hashing retain their current contracts.

Task actions accept one input per meaning: `hardware_benchmark` uses `prompt`; `speculative_draft` uses `task` and `candidate` as the file; `vision` uses `prompt` and `candidate` as the image while retaining distinct artifact/browser evidence inputs; `transcribe` uses `candidate` as the audio path. `eval_suite` and `eval_drift` use `task` as the suite name (omission selects `default`). `prompt_eval` uses `prompt` and the `candidate_data` variables object; an explicit empty object stays empty. `complete_code` uses optional `prompt` prefix and `candidate` suffix. `scaffold` uses `prompt`, `context`, and `language`; `auto` selects Python. `candidate_create` requires an explicit `candidate_data` object; `candidate_promote` requires explicit `candidate` ID and `approver`, subject to the existing server checks. Alternate overloaded fields are rejected; do not infer a promotion approver or fabricate candidate versions in a client wrapper.

`git_history_search` uses a required literal `query`, optional literal `author` and repository-relative `path`, optional ISO `since`/`until` dates or RFC3339 timestamps with timezone, and `max_commits` from 1 to 100 (MCP default 50). Date-only bounds cover the UTC day. Author filtering includes the Git author header, including email; regex metacharacters remain literal. `hotspots` uses `days` from 1 to 3650 (default 30) and `limit` from 1 to 50 (default 20); `diff` and `max_tokens` are rejected. Scores use commit churn with a 90-day half-life. Both analyses report incomplete coverage when limits, malformed output, file changes or deadlines prevent full analysis; no completeness may be inferred from a nonempty result. Hotspot complexity reads are bounded, identity-checked current files. The obsolete root/days-only hotspot cache is removed; repository fingerprint caching remains.

Repository context uses `query` for the task description; `solve` and `delegate` use `task`. Do not substitute these fields. Cross-project graph/symbol/impact actions are `cross_project_graph`, `cross_project_symbols`, and `cross_project_impact`; `cross_repo_contract` is a separate backend/frontend contract operation. `synthesize_commit` accepts an optional explicit `task_id`; no task-name inference occurs. `generate_tests_for_diff` accepts `diff` and optional `path`; omission uses the current Git diff. Regex RAG chunking for TypeScript, C#, Go and Rust preserves complete lexical units and leaves ambiguous syntax whole; it is not resolved AST evidence. Test matrix rows require current bounded filesystem reads; detected source cases are not collected or executed test results, and coverage describes the iterator scope only.

On Windows Python 3.13+, native Tree-sitter parsing runs in an isolated worker. A worker crash, timeout, or execution failure disables further worker dispatch for that Hub process lifetime; later calls report the disabling cause and use the existing deterministic fallback. Do not recreate the worker repeatedly or execute the native parser in the main process after failure. This containment does not establish that the underlying native crash is repaired. Source changes require activation before they affect an already running Hub.

Basic aggregate telemetry remains enabled locally. Detailed request traces are disabled by default and can be toggled live in the dashboard. When enabled, they retain complete endpoint input/output locally, including sensitive values, within configured size and retention limits. Local telemetry and trace details stay on this device; only normal agent responses requested by cloud agents leave it.

Install updates stage and verify payloads before swapping files. Existing-runtime stop uses the installed config and must be confirmed; failed or unknown stop blocks replacement and startup. File rollback can leave the runtime stopped and must be reported separately. Shared skills are replaced or removed only when their Hub ownership hash matches; preserve unmanaged or user-modified trees and report conflicts.

Canonical coordination inputs: blackboard update uses content, author and optional expected_version; merge uses remote_sections. Board IDs retain the task_id-scoped default. Pubsub publish uses topic/message/publisher and preserves null or falsey JSON; poll uses after_seq, limit (1–1000, default 50) and optional after_ts, distinct from sequence. `limit` is accepted only by task_sync and pubsub_poll among coordination actions. Swarm uses goal/target_paths/test_command/author, swarm_id/role/swarm_action/payload, and state for listing. Worktree actions use branch/worktree_path/worktree_id/delete_branch; omitted delete_branch remains true and explicit false is preserved. Simulated merge uses source_branch/target_branch. Dataset curation uses output_path/min_receipts/format (default jsonl); verification export defaults to markdown. Retired generic key/value/query/status aliases cannot substitute for these fields. Incident decision uses fingerprint/state_revision; negative-knowledge recording takes an explicit record object and finding takes query/limit (1–100, default 100). Incident records accept strict signed or unsigned 32-bit process exit codes, including Windows access violations. Root and tenant cannot be overridden inside the record. Generic SDK coordination follows these canonical verification and incident inputs. Source integration alone does not activate running processes or establish runtime acceptance.

Path fusion canonicalizes redundant dot/separator spellings before cross-backend agreement, preserving case, UNC prefixes and parent segments. limit and max_per_path require positive integers; coercive legacy values are rejected. Each optional backend is sampled up to a fixed 4096 entries independently of output limit; malformed groups or iterator failures leave other backends available. This is bounded candidate ranking, not a claim of exhaustive corpus coverage or measured relevance/performance.

Tiered cache nonempty batches require the current L2 set_many API. Providers without that callable batch method reject before L1/L2 writes or coordinator acquisition; there is no per-entry compatibility fallback. Empty batches remain no-ops. Existing supported SQLite batch transactions and coordinator failure recovery are retained; live correctness and performance still require final integrated validation.

Capability grants require canonical string identities, immutable internal capability sets and JSON-array allow/deny inputs; scalar coercions and invalid/nonfinite expiry reject. Explicit deny remains authoritative. Verification receipt passed flags are booleans, generations are nonnegative integers, and observed/expiry timestamps are finite numbers; invalid expiry never becomes unlimited validity. These source changes require integrated validation before acceptance.
