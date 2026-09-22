# Local AI Hub

Local AI Hub **4.0.0** is a local, deterministic-first tool and inference layer for coding agents such as Codex, Claude Code, Gemini CLI, Cursor, Windsurf, VS Code/Copilot and other MCP clients. Its purpose is to keep repetitive repository discovery, code-relationship analysis, validation, retrieval and bounded local reasoning off the cloud agent's context while sharing the resulting work across agents.

The public interface is intentionally small: **8 MCP tools**. Serena and CodeGraphContext are managed behind that surface by default, so agents gain language-aware symbols and graph relationships without paying for two additional MCP schemas on every turn.

Local AI Hub 4.0 uses one current runtime contract across packaging, HTTP, MCP, telemetry, caches and dashboard state. Token efficiency is accounted end-to-end at the MCP boundary: gross repository/context/output avoidance is measured separately from tool-call and tool-response protocol cost, producing a signed net cloud-token delta. Deterministic/indexed retrieval, context/diff/outline compaction and artifact-backed projection contribute to cloud savings only when an explicit measured baseline exists; diagnostic candidate sizes are not proof that a cloud agent would have read the same payload. Local cache/single-flight reuse is reported separately as local-compute avoidance, and tool-catalog schema exposure is shown as a separate conservative scenario.

## What it does

- deterministic repository facts, symbols, references, manifests, routes, tests and risk signals;
- default adaptive repository context packs before non-trivial planning, edit, review or test, with reuse-first candidates, evidence IDs, guarded override reasons and bounded deterministic/local-model composition;
- managed **Serena** semantic-symbol indexing/querying;
- managed **CodeGraphContext** call/dependency/impact graph indexing/querying;
- checkpointed background preprocessing that warms built-in indexes, Serena, CodeGraph, RAG and compact project cards;
- read-only local-model explorer/worker/critic tools that can use the same Serena/CodeGraph/index/RAG layers;
- durable whole-task orchestration with dependency planning, transactional edits, validation, whole-task verification and compact/lazy handoff;
- local semantic retrieval and reranking with persistent caches plus optional Intel NPU/iGPU OpenVINO acceleration;
- safe cached test/lint/typecheck/build/read command execution;
- exact evidence IDs and artifact-backed large responses;
- model-affinity scheduling, bounded fallbacks and optional local backends (Ollama is disabled by default);
- automatic hardware profile selection across Windows, macOS and Linux, including NVIDIA, AMD, Intel and Apple graphics detection;
- metadata-only telemetry, realtime monitoring and a self-contained dashboard;
- **Agent Operating System**: durable execution state, scoped key-value memory, exact token-bounded context compilation, verification receipts, and negative knowledge incident avoidance;
- **Token Economy Suite**: CLI tools (`tokcount`, `trim-run`, `repo-map`), AST structural search, ANSI-stripped output truncation, and automated context budgeting. See [docs/TOKEN_ECONOMY.md](docs/TOKEN_ECONOMY.md).

## Supported Languages & Frameworks

Local AI Hub features deep static intelligence, deterministic AST extraction, code indexing, test mapping, import resolution, and dependency security audits across modern technology stacks with zero LLM inference:

| Language / Stack | Support Level | Frameworks & Ecosystem | Intelligence & Features |
|---|---|---|---|
| **PHP** | **Tier 1 (First-class)** | Laravel, CakePHP (2.x–5.x), Symfony, WordPress | Namespaces, FQN classes/traits/interfaces/enums, Eloquent ORM (table, fillable, relationships), migrations & columns, Artisan signatures, FormRequests, CakePHP Table/Entity ORM, CakePHP routes & resources, WordPress hooks/filters, `composer.json` (PSR-4 autoload, scripts), `composer.lock` offline CVE audit, PSR import resolution (`use App\Services\Foo;`). |
| **TypeScript / JavaScript** | **Tier 1 (First-class)** | React, Next.js, NestJS, Vue, Svelte, Express, Fastify | Classes, interfaces, type aliases, enums, arrow functions, React components & hooks, Next.js App Router HTTP handlers (`GET`, `POST`), NestJS decorators & routes (`@Controller`, `@Get`), test suites (`describe`, `it`, `test`), `package.json` scripts/dependencies, `package-lock.json` CVE audit, import resolution. |
| **HTML & Templates** | **Tier 1 (First-class)** | HTML5, Blade, CakePHP CTP, Web Components | Form endpoints & HTTP methods (`<form action="..." method="...">`), `<script>` assets, stylesheet links, element IDs, custom web components (`<x-widget>`), Blade directives (`@extends`, `@include`, `@section`, `@livewire`, `@component`). |
| **CSS & Preprocessors** | **Tier 1 (First-class)** | CSS3, SCSS, SASS, LESS | CSS custom properties / variables (`--primary-color`), `@keyframes` animations, `@media` responsive queries, class selectors (`.class-name`). |
| **Python** | **Tier 1 (First-class)** | FastAPI, Flask, Django, Pytest | AST function/class visitor, decorators, dataclasses, async defs, route decorators, test-to-production mapping, circular dependency checker, `pyproject.toml` / `requirements.txt` / `poetry.lock` / `uv.lock` security audit, import resolution. |
| **C# / .NET** | **Tier 1 (First-class)** | Unity Engine, ASP.NET, NUnit | Namespaces, classes, records, interfaces, properties, methods, Unity MonoBehaviour lifecycles (`Awake`, `Start`, `Update`), `[SerializeField]`, `ScriptableObject`, Minimal APIs, `using` import resolution. |
| **Go, Rust, Java, C/C++** | **Tier 2 (Structural)** | Standard idioms & libraries | Generic AST outline, struct/interface/method extraction, `go.mod`, `Cargo.lock` CVE audit. |
| **Infra & DevOps** | **Tier 1 (First-class)** | Docker, Compose, K8s, CI/CD, Terraform | Dockerfile base images & exposed ports, Compose services & healthchecks, GitHub Actions, GitLab CI, Azure Pipelines, K8s manifests, Terraform resources, OpenAPI/Swagger 3.0 route parser. |

## Key Features & Cloud Agent Impact

Local AI Hub is engineered to maximize **Quality**, **Speed**, and **Token Economics** for frontier cloud models (Claude 3.5 Sonnet, GPT-4o, Gemini 1.5 Pro) by executing heavy, repetitive, and deterministic work locally:

| Capability / Feature | Core Mechanism | Quality Impact | Speed & Latency Impact | Cloud Context & Cost Savings |
|---|---|---|---|---|
| **Deterministic Code Intelligence** (`local_ai_repo`) | AST parsing, FQN symbol indexing, route & ORM extraction across PHP, JS/TS, Python, C#, HTML, CSS | **100% exact facts**: Eliminates LLM hallucinations for imports, symbol definitions, routes, and DB relationships. | **Sub-millisecond**: Zero network latency; index hits in <5ms vs waiting 5–15s for cloud agent file reads. | **85–95% input token reduction**: Injects targeted symbol cards/fact summaries instead of full 500+ line files. |
| **Adaptive Context Guard** (`local_ai_repo(action="context")`) | Phase/focus/preload-aware bounded pack with reuse candidates, evidence IDs, revision/delta metadata and guarded approvals | Deterministic/indexed evidence stays authoritative; local models rank/compress structured evidence only | Compact default packs before planning, edit, review and test; raw model/debug fields stay opt-in | Avoids duplicate discovery and unsupported repository claims while preserving legacy fast/full callers |
| **Token Economy Suite** (`tokcount`, `trim-run`, `repo-map`, `rg`, `fd`, `ast-grep`, `jq`) | Dedicated CLI tools & wrappers installed into PATH; ANSI stripping, head/tail log truncation, AST outline search | **Eliminates prompt pollution**: Prevents "Lost in the Middle" attention degradation caused by noisy logs and raw file dumps. | **Dramatically faster TTFT**: Cloud models generate answers in seconds when context stays bounded (<15k tokens). | **70–98% output token savings**: Caps bloated build/test logs and API JSON responses to only actionable lines. |
| **Unified 8-Tool MCP Surface** (Managed Serena & CodeGraph) | Serena (LSP) and CodeGraph (call/dependency graph) run under `local_ai_repo` without separate schemas | **Deep graph reasoning**: Agent queries blast-radius impact and cross-file callers before modifying code. | **Pre-indexed & warm**: External tool processes run persistently; no cold-start timeouts during agent turns. | **Saves ~1,500 schema tokens/turn**: Avoids exposing multiple heavy tool schemas on every single agent interaction. |
| **Agent Operating System** (`local_ai_coord`) | Durable execution state, scoped KV memory, negative knowledge incidents, verification receipts, path leases | **Prevents repeated mistakes**: Negative knowledge prevents retrying broken patterns; receipts enforce true test verification. | **Instant resumption**: Restores task state and active memory without re-discovering repository facts. | **Bounded context compilation**: Assembles exact token-budgeted memory slices, preventing runaway session context bloat. |
| **Single-Flight Command Broker** (`local_ai_command`) | Deduplicated test/lint execution, SHA256 caching, ANSI removal, verification receipt generation | **Deterministic verification**: Guarantees identical execution conditions; prevents flaky duplicate runs. | **Instant cache returns (0ms)**: Subsequent test/lint runs in the same workspace state return cached results immediately. | **Avoids 5k–25k rerun tokens**: Keeps massive compiler errors or test suites from repeating across agent iterations. |
| **Optional Local Inference** (`local_ai_task`) | Profile-aware tiers: integrated uses 0.5B preprocessing, 1.5B fast, 3B involved, 7B hard, and Qwen3-VL 4B vision; balanced uses 1.5B preprocessing, 3B fast, 7B ordinary/hard, and 9B extreme/vision through an already-configured local backend | **Advisory second opinion**: Local models review diffs and draft AST fixes without cloud context contamination; deterministic evidence remains authoritative. | **Local concurrency**: Local generation runs in parallel with cloud agent high-level planning. | **100% free (0 cloud tokens)**: Offloads routine microtasks, file summaries, and formatting repairs completely off cloud bills. |
| **Whole-Task Delegation** (`local_ai_work`) | Autonomous closed-loop execution: local plan, transactional patch staging, rollback journal, verification | **Transactional safety**: Automatic rollback on test failure prevents partially broken codebase commits. | **Autonomous iteration**: Iterates through 10–30 test-fix cycles locally without internet or cloud rate limits. | **Massive savings (95%+)**: Compresses multi-turn cloud exchanges (50k–200k tokens, $1–$5) into a single <350 token handoff. |
| **Hardware-Aware Scheduling & NPU Acceleration** | Automatic hardware profiling (`integrated` to `max`), Vulkan/CUDA offloading, Intel NPU OpenVINO retrieval | **Rock-solid stability**: Never crashes host system with OOMs; scheduler throttles background work gracefully. | **NPU/iGPU offload**: Frees primary CPU cores for IDE responsiveness and build tools while searching vectors. | **Zero cloud dependency**: Enables fast local semantic search and embeddings on standard laptops without paid APIs. |

## Installation & One-Command Setup

Tell your AI coding assistant:
> **"Install Local AI Hub"** *(or "Nainstaluj local ai hub")*

Or run the bootstrap installer directly:

### Windows

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

### macOS / Linux

```bash
chmod +x install.sh
./install.sh
```

The bootstrapper finds or installs a suitable Python 3.11+ runtime where the platform package manager permits it, then runs `tools/setup.py`. Setup automatically configures:

- the Local AI Hub virtual environment, core dependencies, and Token Economy Suite (`tokcount`, `trim-run`, `repo-map`);
- external CLI tools (`ripgrep` / `rg`, `fd`, `ast-grep`, `repomix`, `jq`);
- The configured local inference backend and the Qwen capability tiers (`qwen2.5-coder:0.5b`, `qwen2.5-coder:1.5b`, `qwen2.5-coder:3b`, `qwen2.5-coder:7b`, plus balanced-profile `qwen3.5:9b`), plus the default embedding model (`BAAI/bge-small-en-v1.5`);
- Serena and CodeGraphContext in isolated tool environments;
- local SentenceTransformers/reranker dependencies and model cache;
- optional OpenVINO dependencies/models when OpenVINO is configured, NPU hardware is detected, or an Intel GPU is detected with the `integrated` profile, subject to the OpenVINO and feature install flags;
- MCP server registration into Codex, Claude Desktop, Gemini, Cursor, Windsurf, and VS Code/Copilot;
- companion agent skills (`local-ai-orchestrator`, `token-economizer`, `caveman`, `tool-orchestration`, `ollama-quality-routing`) and policies (`LOCAL AI HUB TOOL POLICY`, `TOKEN ECONOMY POLICY`);
- a per-user headless service/supervisor.

Nothing requires administrator/root privileges unless the host package manager itself requires them.

Useful setup overrides:

```bash
python tools/setup.py --profile cpu
python tools/setup.py --profile integrated
python tools/setup.py --profile balanced --skip-model-pull
python tools/setup.py --skip-tools
python tools/setup.py --skip-agent-config --skip-service
python tools/setup.py --generate-only
```

Run `python tools/setup.py --help` for the complete list. Normal setup reruns preserve the configuration already installed in `~/.local-ai-hub`; pass `--config <path>` explicitly when you intend to import/replace it.
Run `python tools/hubctl.py generate` (or `python tools/setup.py --generate-only`) at any time to regenerate dynamic agent skills, instructions, and MCP tool schemas matching your active `config.toml` feature toggles and models.

## Hardware profiles

`[hardware].profile = "auto"` is the default. Detection considers OS, CPU architecture, RAM and available NVIDIA/AMD/Intel/Apple graphics. The selected profile overlays conservative scheduler, context, background-work and batch defaults **before** `config.toml` is merged, so explicit user configuration always wins.

Profiles: `cpu`, `integrated`, `low`, `balanced`, `high`, `max`.

`integrated` is selected for shared-memory iGPUs (for example Intel Arc Graphics on Core Ultra notebooks) instead of sizing the machine from the tiny `AdapterRAM` aperture value reported by Windows. It keeps one LLM/model resident at a time, uses 0.5B only for preprocessing, 1.5B for quick/simple requests, 3B for ordinary and more involved tasks, 7B for hard reasoning, and `qwen3-vl:4b` for vision; it never selects `qwen3.5:9b`. The balanced discrete-GPU profile uses 1.5B for preprocessing, 3B for fast/simple requests, 7B for ordinary/hard work, and promotes only extreme reasoning and vision to `qwen3.5:9b`.

On Intel integrated systems, embeddings/reranking can use OpenVINO in `NPU -> GPU -> CPU` order. This is optional and failure-safe: missing drivers, unsupported model shapes, export failures or an unavailable OpenVINO runtime fall through to the next device and finally CPU. LLM generation is separate; the integrated profile may use an already-running llama.cpp SYCL endpoint, but does not install Ollama or llama.cpp and does not silently fall back to either.

## Configuration

Keep `config.toml` small. `defaults.toml` is the complete reference.

```toml
[hardware]
profile = "auto"
auto_tune = true

[models]
background_code = "qwen2.5-coder:0.5b" # preprocessing only
fast_code = "qwen2.5-coder:1.5b" # quick requests
heavy_code = "qwen2.5-coder:3b" # more involved code tasks
reasoning = "qwen2.5-coder:7b" # hard reasoning; balanced auto profile promotes extreme reasoning to qwen3.5:9b
general = "qwen2.5-coder:3b" # ordinary requests

[code_intelligence]
enabled = true
serena_enabled = true
codegraph_enabled = true
```

To expose Serena/CodeGraph as independent MCP servers as well as through the hub, set `code_intelligence.direct_agent_mcp = true`. The default is `false` to minimize agent schema tokens.

## Agent behavior

The main agent owns task boundaries, permissions, unresolved decisions and the final user answer. For a closed, bounded and independently verifiable repository task, prefer `local_ai_work(action="submit")`: the Hub may own planning, transactional edits, validation and integration inside that declared task until it returns a verified handoff. Use `response_profile="compact"` by default, request only the fields needed for the next decision, and fetch detailed artifacts lazily. Use `local_ai_task(action="delegate"|"explore"|"reason"|"review"|"second_opinion"|"compress")` for bounded semantic generation, exploration, reasoning, review, independent second opinions and compression; use deterministic/indexed tools for exact facts, symbols, diff and tests. Native Codex subagents are for explicit Codex-only work. Never duplicate the same scope across agents.

Setup installs the `local-ai-orchestrator` skill/policy where the host supports it and MCP entries for Codex, Claude, Gemini, Cursor, Windsurf and VS Code/Copilot. Portable manifests are also emitted under `generated/`. The intended order is:

1. on first non-trivial use of a stable absolute root, fire-and-forget `local_ai_repo(action="preprocess", root=...)` once; never poll/wait for it;
2. `deterministic` for exact facts, then `code_index`/`search` for symbols/text;
3. `semantic` (Serena) or `graph` (CodeGraphContext) only for relationships that need them;
4. `context`/`solve` for mixed evidence, with RAG/local-model synthesis only after cheaper indexed paths are insufficient;
5. `local_ai_command` for repeatable tests/lint/typecheck/build/read-only commands;
6. exact `E…` evidence/artifact slices only when source text is required;
7. `local_ai_coord` leases/memos for overlapping multi-agent work;
8. for a closed end-to-end task, `local_ai_work(action="submit")` can replace the manual sequence above and return a compact verified handoff.

This is intentionally stronger than merely making tools available: installed policies and MCP descriptions enforce the same cheapest-first gate, prohibit preprocessing/status polling, and treat native broad repository exploration as fallback-only after one bounded hub retry.

## Whole-task delegation and compact handoff

Example:

```text
local_ai_work(
  action="submit",
  root="<absolute-repository-root>",
  task="Fix preprocessing cache invalidation and add regression tests",
  acceptance_criteria=["unchanged files stay cache hits", "relevant tests pass"],
  response_profile="compact",
  return_fields=["status", "summary", "changed_files", "validation", "risks"],
  max_output_tokens=350,
)
```

Large plans, step logs, diffs and verifier details stay in local artifacts and are fetched only when requested. Work orders are durable, cancellable and resumable; edits use repository-relative patch validation, path leases and an external rollback journal rather than manipulating Git history. Default permissions allow bounded workspace edits/tests/builds but do not grant network access, Git commit or push.

## Serena + CodeGraph preprocessing

The preprocessor uses durable phases:

`inventory → hash → code_index → deterministic → serena → codegraph → lexical → rag → files → modules → project → hot_queries → complete`

External indexes are revision-tracked. If Serena/CodeGraph is missing, fails, or exceeds a configured timeout, that phase becomes skipped/degraded and preprocessing continues. The hub never waits indefinitely for an external tool. Interactive queries also use timeout-bounded persistent MCP subprocesses with stderr draining, process-tree termination and circuit cooldowns.

## Local-model tools

The optional local-model tool agent can query:

- built-in deterministic facts and code index;
- preprocessed cards/context;
- Serena semantic symbols/references;
- CodeGraphContext relationships;
- lexical/RAG candidates;
- exact evidence slices and bounded file reads.

Relationship-heavy tasks are bootstrapped toward CodeGraph and symbol/reference-heavy tasks toward Serena before local generation, reducing model rediscovery.

Named advisory profiles are available through the existing compact MCP surface: `qwen-explorer` for repository reconnaissance, `qwen-drafter` for solution guidance, and `qwen-critic` for independent review. With an absolute repository root, profiles use Local AI Hub read-only tooling directly and never write files or run commands. Example: `local_ai_task(action="delegate", profile="qwen-explorer", root="C:\\project", task="Find the relevant entry points")`.

Portable generated MCP manifests intentionally include only `local-ai` by default. Direct Serena/CodeGraph MCP servers are opt-in.

## Reliability

The hub is designed to degrade instead of wedge:

- finite scheduler, command, model, repository-fingerprint single-flight and external-tool deadlines;
- circuit breakers and bounded model/backend fallback;
- stale/deleted temporary repository roots return structured degraded results instead of crashing request handlers;
- child process trees are terminated on timeout;
- client disconnects are treated as normal socket cancellation and do not destabilize the service;
- derived SQLite/cache/index state is disposable and self-rebuildable;
- supervisor recycles a genuinely unhealthy hub with bounded backoff;
- Windows service setup uses a persistent logon task instead of launching a new supervisor every minute;
- `/health` is lightweight and independent of model availability.

No software can guarantee survival of OS, driver, power or hardware failures, but failure modes are bounded and recoverable.

## Token-efficiency accounting

Local AI Hub accounts for cloud-context savings together with the protocol cost required to obtain them. For every public MCP call the Hub estimates the compact tool name/arguments emitted by the agent and the exact projected response the agent must read. The default headline is therefore:

`net cloud token delta = gross cloud context/output avoided - tool-call tokens - tool-response tokens`

The signed delta can be negative when a tool costs more context than it saves. `gross_*` counters remain available for diagnosis, while `cloud_token_overhead_est` exposes negative cases instead of clamping them away. Enabled-tool schema exposure is reported separately as `tool_schema_tokens_exposure_est` / `net_after_schema_token_delta_est` because different MCP hosts inject and cache schemas differently; it is an upper-bound scenario, not silently charged on every call.

USD savings use separate configurable rates: saved cloud input tokens are priced with `token_saving.cloud_input_token_cost_usd_per_million`, and saved cloud output tokens with `token_saving.cloud_output_token_cost_usd_per_million`. Tool responses are treated as cloud input cost and tool calls as cloud output cost. The same additive-safe baseline selection applies here, so overlapping input/output counters are not charged twice. The blended rate remains available for telemetry rows that predate channel-specific counters.

Savings sources are intentionally deduplicated: overlapping input-side transformations (for example raw source → deterministic outline → packed context) compete for the strongest measured counterfactual source baseline rather than being summed. The packed/projected tool response is then charged exactly once as actual agent-read cost. Response compaction is reported separately and is used as the headline baseline only when no stronger upstream source baseline exists, preventing raw → packed → projected double counting. Cache/single-flight reuse is tracked as `local_compute_tokens_avoided_est` and is not added to cloud-context savings. Telemetry stores only bounded numeric/category metadata; tool arguments, source, prompts and tool output are never persisted by the accounting path.

## Dashboard and diagnostics

Dashboard: `http://127.0.0.1:11435/dashboard`

It shows hub/Ollama state, Agent OS tasks/memory records, selected hardware profile, CPU/RAM/graphics, scheduler/model activity, preprocessing progress including Serena/CodeGraph phases, code-intelligence backend status, cache/token-saving counters and metadata-only activity/error telemetry.

```bash
python tools/doctor.py
python tools/hubctl.py status
python tools/hubctl.py tasks
python tools/hubctl.py memory
python tools/hubctl.py doctor
python tools/hubctl.py logs --limit 50
python tools/hubctl.py watch
python tools/telemetry_report.py --days 30
```

## Evidence-gated rollout controls

Cost-bearing adoption capabilities are disabled by default: `features.enriched_search`, `features.batch_replacement`, `features.diagnostic_artifacts`, and `features.local_diagnostic_dispatch`. Set only one flag to literal TOML `true` for a 10–20% suitable-task pilot. Other values, including strings such as `"true"`, remain disabled.

Capture a 14-day read-only baseline first. Compare the pilot with `/api/adoption` for token reduction, latency, first-pass validation, terminal Hub failures, and native fallback rate. Promote a flag only when quality does not regress and the measured benefit persists. Roll back immediately by setting that flag to `false`, restarting the Hub, and regenerating agent instructions with `python tools/hubctl.py generate`. Disabled features return a structured unavailable result before search enrichment, replacement writes, artifact persistence, or local diagnostic dispatch can begin. A `local_diagnostic_dispatch` pilot alone stores only its bounded failure preview as context; it never stores raw command output and does not require `diagnostic_artifacts=true`.

## Security and privacy

The server binds to loopback by default. Non-loopback exposure fails closed unless remote access is explicitly enabled and an API token is configured. Multi-tenant scheduling is fairness, **not** security isolation.

Observability is metadata-only: prompts, source code and model output are not stored in the telemetry database. Runtime indexes/RAG necessarily contain local repository-derived state and remain under the configured local state directory.

See `SECURITY.md` for reporting and deployment guidance.

## Documentation

- `docs/ARCHITECTURE.md` — system layers and failure model
- `docs/INSTALLATION.md` — platform installation and verification
- `docs/CONFIGURATION.md` — configuration/hardware/code-intelligence settings
- `docs/MCP_AND_AGENTS.md` — tool-first agent routing
- `docs/HTTP_API.md` — HTTP contracts
- `docs/DASHBOARD.md` — operator UI
- `docs/OPERATIONS.md` — service operations and recovery
- `docs/SECURITY_MODEL.md` — trust boundaries
- `docs/TESTING.md` — test/release gate
- `docs/TROUBLESHOOTING.md` — common failures

## Development

```bash
python -m venv .venv
# activate it, then:
pip install -r requirements-core.txt
pip install -e ".[dev]"
python -m pytest -q
python tools/selftest.py
```

See `AGENTS.md` and `CONTRIBUTING.md` for contributor rules.

## License

See `LICENSE`. Third-party tools/models keep their upstream licenses; see `THIRD_PARTY.md`.
