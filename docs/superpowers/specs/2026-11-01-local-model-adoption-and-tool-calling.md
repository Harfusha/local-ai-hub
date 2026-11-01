# Local model adoption and tool calling

Status: implementation in progress, 2026-11-01. Model downloads remain opt-in; live RTX 5070 Ti acceptance is deferred.

Backend availability derives from explicit `ollama.enabled`, independently of `server.auto_start_ollama`: an externally managed server can provide model tools without process autostart. Configuration alone is not a health or installed-model check; a running Hub must load the changed code before this behavior is active.

An explicitly configured external llama.cpp `auto` route is not restricted to Intel GPUs; admission still requires the router's authorized loopback endpoint and runtime health checks. Feature exposure does not assert that the configured endpoint is reachable.

Work validation must never fabricate a broker receipt from a successful exit code or command ID. An unmodified `execute` work order may forward a receipt only after matching it to the broker's durable scoped execution record. For task-bound `bounded` edits, a fenced mutation barrier couples each patch to a task generation; an eligible test can produce a genuine broker receipt for that generation. The broker persists it without mapping it to task completion. The handoff remains `needs_agent` for primary review. An `execute` order missing a post-patch receipt retains the patch with its completion gate unsatisfied.

The broker and both work modes must reject verification when timeout, cancellation, interactive abort, unknown or in-progress outcome, unconfirmed process cleanup, incomplete output capture, or unconfirmed callback delivery is reported. A success flag and zero exit code cannot override an uncertain state; malformed uncertainty flags and contradictory success/exit codes fail closed without retrying an uncertain command.

If a bounded validation returns as the work order is cancelled or its deadline expires, retain the broker's actual result separately from the work outcome. A cancelled handoff links a bounded local validation artifact when persistence succeeds and explicitly reports an artifact persistence failure otherwise; neither case records a verification receipt or implies completion.

The existing repository delegation path passes the work order's supplied evidence together with retrieved repository context as untrusted context, and binds downstream model/project policy to the requested root. The model's existing prompt budget still applies; inclusion before generation is not proof that an arbitrarily large context fits the selected model.

An edit step receives bounded prior inspection evidence as well as its own retrieved context. Inspection evidence carries the work-order mutation generation and is marked stale after a later edit; clipped sections are marked as truncated. These are data for the local model, never an extension of file, command or tool permissions.

Completed bounded edit steps retain per-attempt model names and fallback flags only when explicitly reported by the service response. If a bounded step fails after it starts, the failure artifact records its ID, kind, `success=false`, and any model observations already obtained. Missing or malformed values remain null; a route or configuration value cannot fill them. Each observation has `identity_verified=false`: a reported name alone does not establish the serving backend, digest, live inference, model quality or benchmark eligibility.

## Goal and boundaries

Increase useful, measurable local-model participation in normal agent work, while keeping speed, answer quality and clear ownership. Optimize the `high` profile for a desktop RTX 5070 Ti with 16 GB VRAM after the card is installed and detected. A larger model is not assumed better; favor models up to 14B parameters subject to actual measurements.

The primary agent owns task selection, permissions, diff and test review, integration and final decisions. A bounded implementation order may delegate edits and approved tests through the existing `local_ai_work` executor. Security and architecture decisions, uncontrolled mutations and open-ended coding remain outside local autonomy. Keep exact indexed evidence and tests authoritative. Do not install or pull models without explicit user opt-in; preserve the configured preprocessing provider. Single-owner installation, no tenant identities or retired compatibility routes.

## Bounded implementation order

The allowed-file list uses the existing broker's patch-path rules, including rejection of Git metadata and platform-specific unsafe paths. On Windows, reserved device names, ambiguous trailing dots/spaces, alternate streams, invalid characters and case-variant duplicates are rejected before an order is queued. The broker, path confinement and writer fencing still independently enforce their existing checks.

On Windows, bounded patch application additionally pins existing ancestor directories without delete sharing from before the snapshot through Git apply and postimage verification, and refuses reparse points. Rollback and crash recovery also pin ancestor directories and open existing target files without write or delete sharing; verification, restoration and deletion use those same handles. Restoring a missing file uses exclusive creation. A bounded Windows patch creating a file requires its parent directories to exist; a missing parent fails explicitly without creating it. The pin is Windows-specific: existing non-Windows path checks and cooperative writer fences do not by themselves prove protection against an unrelated process racing a path replacement.

Patch preview and application preserve each existing file's uniform LF or CRLF line endings, including when different files in one patch use different endings. They use disposable Git attributes instead of changing repository configuration. A file that itself mixes LF and CRLF is rejected explicitly before patch application; it is not silently normalized.

For a running bounded order, cancellation and its deadline signal the existing broker and model cancellation interfaces. Same-process cancellation signals directly; a bounded monitor observes durable cancellation from other processes. The broker terminates its subprocess on cancellation. When cancellation interrupts an active step, its available unverified model observations are retained in a cancellation artifact; artifact persistence failure is explicit. A late patch is not applied. Cross-process notification is not instantaneous and backend cooperation remains necessary; the command retains its timeout.

The primary agent may choose small fixes, function changes, validation, tests and simple UI work based on task risk and measured model quality, not parameter count alone. The caller supplies an explicit task, acceptance criteria, exact allowed repository-relative files, exact approved validation commands, an explicit edit permission choice, test/build permissions and a finite budget. Validation-only orders can disable edits; create and delete default to disabled. An empty or invalid scope is rejected. Model output cannot extend the scope. Every patch, including repair, is checked before the existing lease, fence and journal apply path. Bounded patches reject binary, rename/copy and permission-change metadata and cannot create symlinks; normal new files require explicit create permission. Every executed validation command is chosen only from the caller's allowlist and still passes the existing command broker; model-planned or discovered commands do not grant permission. A timeout, cancellation, failed validation, unavailable backend or ambiguous output never becomes a successful handoff. The primary agent reviews the resulting diff, test evidence and integration. The mode is available on the existing work executor and does not imply hardware detection, model availability, tool-call proficiency or production quality. Activation and promotion require task-specific evaluation; physical 5070 Ti measurements are deferred.

Submitting a bounded order requires the user's explicit request for closed
delegation. An internally verified bounded order ends in `needs_agent`, retaining the patch
for the primary agent to review; it does not mint a source-review receipt on
behalf of the task owner. Actual test receipts remain subject to the existing
broker and receipt checks. Without a bound task owner, the handoff retains the
broker's test result but leaves the receipt gate incomplete instead of
inventing an owner or receipt. The primary agent records its own review and
decides whether to integrate or reject the result.

Bounded orders do not mint broker verification receipts from command IDs or
model output. Eligible task-bound tests may expose an authentic broker-owned
receipt with `receipt_status="recorded_unmapped"`; it is evidence for the
primary agent to review, not an accepted completion receipt. A later patch makes
older generation receipts stale. When matching durable evidence is unavailable,
including unbound work, the handoff reports that fact rather than inventing a
receipt or treating a command result as one.

## Existing evidence and limitations

- `hardware.py:270` selects `high` at 12 GiB and `max` at 20 GiB dedicated VRAM; an override can change the result. Detection, installed models, drivers and GPU behavior on the future 5070 Ti are not yet verified.
- `docs/MODEL_CAPABILITIES.md` documents six roles and advisory model use. It lists profile targets, not live availability. Transcription is a separate CPU-only CLI path.
- `defaults.toml:862` and `tool_agent.py` already describe a bounded read-only local tool loop, default 3 steps and 6 calls; named advisory profiles have separate limits. Audit the actual route and protocol before extending it rather than creating a competing executor.
- `model_policy.py:108` derives tiers partly from the model name; shared model identities can select an unintended tier. Lines 170–220 include free-VRAM caps, reserve and prompt budgets. The configuration alone does not prove the prompt received by inference.
- The dashboard image shows zero MCP counts for selected actions. `endpoint_stats.py:82` also lists uncalled registered actions; `http_server.py:6046` constructs recorded action names. Zero does not establish why counts are zero, or whether HTTP/internal inference occurred. Scope, active state directory, counters, filters, attribution and inference must be reconciled with a controlled request.
- Tool-capable Ollama models can return structured `tool_calls`; the caller must validate and execute the selected tool and send its result back ([Ollama tool calling](https://docs.ollama.com/capabilities/tool-calling)). Model labels alone do not establish capability, correctness or measured speed.

## Highest-value work only

1. **Test-case suggestions:** after concrete task and relevant evidence exist, request a bounded list of behavioral and boundary tests. Return rationale and evidence references. The main agent chooses and runs tests.
2. **Diff review:** for nontrivial changes, run existing `local_ai_task` review on scoped diff and evidence. Return actionable findings with references and uncertainty. Verify references and findings before use. Do not treat no findings as a security or correctness guarantee.
3. **Failure diagnosis:** only when configured and deterministic parsing is insufficient, perform at most one local diagnosis from an authorized artifact reference and narrow preview, never raw unrestricted logs. Return hypotheses, cited evidence and a next check; no command or mutation execution. Current diagnostic dispatch is disabled by default and must remain opt-in until verified.

Use existing actions and prompt contracts wherever possible; no new top-level MCP tool. Existing `reason`, `explore`, `compress`, `second_opinion`, and `vision` remain available but are not new automatic triggers in this scope. No fixed quota or forced inference on trivial work. Exact file lookup, repeated identical calls, unusable backend, privacy restrictions, or no suitable evidence are explicit skip conditions. A model failure never blocks primary work.

## Native tool calling

Reuse the existing local tool-agent executor and root binding. Extend only after verifying its actual backend protocol and current coverage. Provide supported local models structured read-only function schemas, a validated assistant tool-call message, corresponding tool results, and a bounded continuation; preserve reasoning/content fields and tool identifiers as required by the selected backend. Support models without native tools through the existing non-tool advisory route, explicitly marking the fallback. Do not infer support from names or cloud tags: use backend-reported capabilities where reliable, a bounded explicit capability probe or a verified configuration, and cache by model identity/version and backend; unsupported/unknown stays non-tool.

The initial allowlist is only the existing authorized, bounded repository search, code/symbol lookup and source/evidence slice operations. Each invocation rechecks the exact authorized absolute root and relevant workspace/task/session binding; validate names, strict argument schema, path confinement including symlinks/junctions, result size and cancellation before execution. Repo content and tool results are untrusted data, never instructions or permissions. No arbitrary shell, network, writes, broad filesystem, other MCP tools, recursive agent spawning, privileged operations or secret discovery. Do not convert a model request into authority.

Enforce existing or stricter global limits: at most 3 model steps, 6 tool calls total, bounded payload/result bytes and wall time, with cancellation propagated; malformed arguments, unknown tools, repeated calls, exhausted budget and tool failure terminate or return an explicit bounded failure. Never silently retry identical calls, claim a call succeeded, invent tool output or execute parallel requests without independent authorization. Record model requested versus executed calls and failure categories without prompt/code content. Structured JSON format is useful for review and test suggestions but validation must reject malformed or semantically unsupported outputs ([Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs)).

The local tool loop stops on a failed or unknown tool outcome and returns explicit failure counters instead of asking the model to turn missing evidence into a successful answer. Contradictory success plus unknown, pending, cancelled or timed-out flags remains unknown.

The existing loop accepts a stricter parent-supplied model-step limit; the effective limit is included in its cache identity. A limit of one leaves no tool-selection round. This mechanism alone does not activate tool exploration in `local_ai_work` or establish model quality.

An internal parent may also supply an explicit nonempty subset of the role's advertised tools. The loop rejects invalid or expanded lists before dispatch, applies that scope to automatic bootstrap as well, and includes the selected tool contract and parent scope in its cache identity. This is a restriction, not a new authorization grant.

Tool-loop cache identity also includes supplied instruction suffix, a snapshot of bootstrap evidence, the full advisory-profile contract, effective tool settings and the observed Ollama model digest. If model identity is unavailable or a configured external llama.cpp route can serve the model, bypass this cache. Ollama's digest inventory is itself briefly cached; this is not proof of model quality or a target-GPU acceptance result.

## Proposed 16 GB profile and contexts

These are candidates, not an assertion of superiority, installation or full GPU residency. Check current model tags, compatibility, availability and user overrides. Compare on target hardware before promotion:

| Role | Initial candidate | Default / adaptive ceiling (tokens) |
| --- | --- | --- |
| background_code | existing `qwen2.5-coder:3b` | 8192 / 16384 |
| fast_code | `qwen3.5:4b-q4_K_M` | 16384 / 32768 |
| heavy_code | `qwen3.5:9b-q4_K_M` | 32768 / 65536 |
| reasoning | `qwen3.5:9b-q4_K_M` | 32768 / 65536 |
| general | `qwen3.5:9b-q4_K_M` | 32768 / 65536 |
| vision | `gemma4:12b` | 16384 / 32768 |

Do not alter preprocessing as a side effect. Test `qwen2.5-coder:14b`, Qwen 9B Q8, Qwen vision and `Nanbeige4.2-3B` as optional candidates only after source, backend compatibility, licensing and hardware checks. Nanbeige's published agent benchmarks do not demonstrate results in this Hub. `qwen3-coder:30b` and `gpt-oss:20b` are outside the preferred <=14B scope, not automatic defaults. A 128k context is an opt-in benchmark experiment, not a promised default.

Set contexts by requested role and actual input/output needs, with explicit token reserve, true runtime budget, bounded parallelism and available VRAM. Resolve shared-model role collisions without selecting a vision policy merely because a text role shares the model. Show requested, selected and effective context, truncation and fallback; do not silently present capped or shortened input as complete. Use one foreground request as benchmark baseline, then measure parallel 2 and background interference; no claim that advertised 256k fits. Preserve safe VRAM checks and avoid GPU/CPU spill unless disclosed.

The source policy can grow to the configured maximum when the estimated combined input, output and reserve exceed the intermediate context. If even the output, reserve and minimum prompt cannot fit, it rejects the request. Foreground and background generation reserve estimated space for the system text and output schema before fitting the request prompt; oversized fixed inputs fail before inference. These are UTF-8-based token estimates, not model-tokenizer measurements or proof of backend context residency. Target-hardware and backend measurements remain required.

Background generation returns the prompt fitting estimate and truncation flag. File, module and project cards preserve that server-produced information as `_input_prompt_budget`; model-supplied values for this field are discarded. The flag concerns this prompt-fitting step only and does not certify that earlier source selection was complete.

## Adoption, instructions and telemetry

First verify the dashboard against one controlled known MCP request, associated HTTP request and model inference. Report scope, lifetime/window, success, unavailable telemetry, source and identity; distinguish attempted, accepted, inferred, successful, skipped, timed out and failed. Counts must not double count tool calls and inferencing or imply useful output. Existing traces remain metadata-only; no prompts, source code or secrets by default. Attribute latency, queue time, effective context, truncation and skip reason. Report quality via human/test acceptance, not fabricated cost savings or unsupported causal claims. Any savings require existing baseline evidence contract.

Endpoint rows count the actual selected action. A bare tool row is an independent
no-action count, not a rollup of the tool's action rows. Internal model inference
is a different event and must not be inferred from an MCP counter. Event-ID
deduplication is bounded to the newest 100,000 events or seven days; it is not a
permanent exactly-once guarantee. An omitted or relative root is reported in the
unknown/global bucket rather than assigned a guessed project.

After the three workflows pass evaluation, update the generated `AGENTS.md` guidance, MCP descriptions, existing `local-ai-orchestrator` skill, `docs/INSTALL_PROMPT.md`, `docs/UPDATE_PROMPT.md` and model capability documentation together. Short explicit triggers: test suggestions after evidence, review before finalizing a nontrivial diff, and one optional diagnosis for qualifying failures. Preserve project instructions, hard stops and direct ownership. Hooks are optional host-specific observability/reminders only after confirming supported event schema and trust; no silent permission escalation, unconditional blocking or additional mandatory model invocation. On failure or unavailability continue safely with explicit status.

## Acceptance and evaluation

Offline tests cover routing and skip conditions; model-tool round trip and unsupported capabilities; malformed, unauthorized, traversal, repeated, oversized and cancelled calls; prompt injection treated as data; role collisions and effective context; existing diagnostic gate; event attribution and dashboard filters; documentation/prompt parity. Tests use stubs and never download models or require a GPU.

On the installed 5070 Ti, with user-authorized models available, record GPU/driver/Ollama versions, active profile, RAM, selected model tags/digests and settings. Compare old and proposed profiles on a fixed task corpus including diff review, test suggestions, failure diagnosis, tool use and bounded implementation across small fixes, tests and simple UI changes. Measure evidence-grounded correctness, false findings, truncation, median and tail latency, queue time, tokens/s, peak VRAM, GPU residency and throughput at 16k/32k/64k (128k experimental), plus concurrency 1/2 and foreground/background contention. Define corpus and scoring before running; compare paired baseline and candidate. Reject any default with incorrect tool authority, material quality regression, unreported truncation/spill or unacceptable interactive latency. Report actual numbers, failed and skipped cases and environment; no fabricated acceptance or universal speed claims.

## Non-goals

No unscoped repository writes, arbitrary model tool access, guaranteed context fit, runtime downloads, cloud replacement mandate, new telemetry exposing content, automatic hook enforcement, or retrospective claim that screenshot proves underuse. Embeddings/reranker changes, reindexing and GPU transcription are separate work.


## 2026-11-01: qualified bounded inspection update

The bounded work orchestrator can optionally invoke the existing read-only tool agent during inspection. This supersedes any earlier statement that bounded work never invokes the tool loop. It is disabled by default and requires the `high` profile, explicit `work_orchestrator.tool_exploration` configuration and an operator-reviewed qualification for the exact installed model digest. The qualification covers repository inspection only, not autonomous coding quality or GPU acceptance. An unqualified, unavailable, unsupported, expired, truncated or ambiguous record fails closed. The tiered runtime reads the digest and tool capability from the selected serving tier without initiating a handoff; an unavailable tier fails closed. External llama.cpp mappings are also excluded until the serving model identity can be verified.

The qualification artifact has kind `local-tool-qualification`, schema `local_tool_qualification.v1`, fields `model`, `model_digest`, `task_kind` (`repository_inspect`), `operator_reviewed` (true), `critical_failures` (0), and `cases` C1/C2/C3 each containing `status` (`PASS`) and a distinct `artifact_id`. Each referenced `local-model-tool-case` artifact must contain the corresponding complete raw harness result for the same model and digest, and its fixture SHA-256 must match the fixed content for that case. Corpus changes require updating the pinned digests and fresh evaluation; the regression tests bind the pins to the actual fixture content. Each case must report native tool capability without fallback; C1 and C3 must show a delivered search result, and the C3 result must contain the fixed injection fixture. These mechanical checks do not replace manual scoring. These records are operator attestations, not tamper-proof proof of evaluation. The operator can persist manually reviewed records using `python -m tools.qualify_local_tool_model --state-dir ABS_STATE_DIR --c1 C1.json --c2 C2.json --c3 C3.json --ollama-url LOOPBACK_URL --reviewed-all-pass`; use the flag only after scoring all cases PASS with zero critical failures. The command verifies the installed model digest, writes the four artifacts atomically, and does not change configuration. Real, manually scored records are still needed before activation; never treat synthetic tests or generated success flags as model qualification.

Inspection permits only repo search, code index, file slice and evidence retrieval under the existing authorized root; edits and commands remain with the existing bounded work machinery and explicit scope. The loop reserves its worst-case model-call budget and its output is untrusted context for the primary agent. Failure and uncertainty are reported; cancellation/deadline fencing and primary review still apply. Source integration does not restart or activate the installed Hub. GPU measurement remains deferred until the physical upgrade.


## Task-bound bounded mutation barrier

A bounded edit explicitly associated with an Agent OS task requires an active task with matching server-managed root and owner. A fenced task barrier is persisted before source mutation and prevents task completion while rollback remains possible. Handoff or rollback finalizes the barrier under a writer fence. On a conflicting postimage, retain the journal and barrier and expose `task_barrier_status=reconciliation_required`. After interruption, supported journaled rollback can be recovered with a new fenced attempt; ambiguous states remain for primary-agent review. Eligible bounded test commands may return authentic broker receipts recorded without automatically mapping them to task completion; missing or stale evidence remains explicit.


## Terminal handoff recovery

Task-bound bounded handoff records final path postimages before publication. Recovery adopts a pending barrier only for the same work and under the writer fence, confirms every recorded file still matches, and preserves the accepted patch. A mismatch or malformed record remains for agent review. This mechanism does not create verification receipts or waive primary-agent review.

When the task barrier was already released, recovery looks up the exact persisted finalization event by stream, kind, actor and payload, independently of its position in the task history. The indexed lookup is time-bounded. A lookup timeout keeps the handoff pending, exposes `task_barrier_error=finalization_event_lookup_timeout` and schedules a retry; it never establishes success.


## Deferred broker evidence

A task-bound bounded work order may return only an authentic broker-issued test receipt for the current task generation, owner, root and repository revision. The broker stores the receipt without updating the task mapping while the work barrier is present. A later patch invalidates earlier evidence. The primary agent reviews the diff, actual test results and integration before independently accepting any receipt; `recorded_unmapped` is not task completion.
