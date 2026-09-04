# Local AI Hub

Local AI Hub **1.5.0** is a local, deterministic-first tool and inference layer for coding agents such as Codex, Claude Code, Gemini CLI, Cursor, Windsurf, VS Code/Copilot and other MCP clients. Its purpose is to keep repetitive repository discovery, code-relationship analysis, validation, retrieval and bounded local reasoning off the cloud agent's context while sharing the resulting work across agents.

The public interface is intentionally small: **7 MCP tools**. Serena and CodeGraphContext are managed behind that surface by default, so agents gain language-aware symbols and graph relationships without paying for two additional MCP schemas on every turn.

Version 1.5 hardens the hub under contention: HTTP admission, model scheduling, Git probing, SQLite stores, external MCP processes and repeatable commands all have bounded concurrency/deadlines or fast retryable fallbacks. Overload is shed instead of turning into restart, thread or duplicate-work storms.

## What it does

- deterministic repository facts, symbols, references, manifests, routes, tests and risk signals;
- managed **Serena** semantic-symbol indexing/querying;
- managed **CodeGraphContext** call/dependency/impact graph indexing/querying;
- checkpointed background preprocessing that warms built-in indexes, Serena, CodeGraph, RAG and compact project cards;
- read-only local-model explorer/worker/critic tools that can use the same Serena/CodeGraph/index/RAG layers;
- CPU semantic retrieval and reranking with persistent caches;
- safe cached test/lint/typecheck/build/read command execution;
- exact evidence IDs and artifact-backed large responses;
- model-affinity scheduling, bounded fallbacks and an optional preemptible background Ollama runtime;
- automatic hardware profile selection across Windows, macOS and Linux, including NVIDIA, AMD, Intel and Apple graphics detection;
- metadata-only telemetry, realtime monitoring and a self-contained dashboard;
- **Agent Operating System**: durable execution state, scoped key-value memory, exact token-bounded context compilation, verification receipts, and negative knowledge incident avoidance.

## Installation

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

The bootstrapper finds or installs a suitable Python 3.11+ runtime where the platform package manager permits it, then runs `tools/setup.py`. Setup can install/prepare:

- the Local AI Hub virtual environment and Python dependencies;
- Ollama when it is missing (unless disabled);
- configured Ollama models;
- Serena and CodeGraphContext in isolated tool environments;
- local SentenceTransformers/reranker dependencies and model cache;
- MCP entries + the tool-first skill/policy for enabled agents;
- a per-user headless service/supervisor.

Nothing requires administrator/root privileges unless the host package manager itself requires them.

Useful setup overrides:

```bash
python tools/setup.py --profile cpu
python tools/setup.py --profile balanced --skip-model-pull
python tools/setup.py --skip-tools
python tools/setup.py --skip-agent-config --skip-service
python tools/setup.py --generate-only
```

Run `python tools/setup.py --help` for the complete list. Normal setup reruns preserve the configuration already installed in `~/.local-ai-hub`; pass `--config <path>` explicitly when you intend to import/replace it.
Run `python tools/hubctl.py generate` (or `python tools/setup.py --generate-only`) at any time to regenerate dynamic agent skills, instructions, and MCP tool schemas matching your active `config.toml` feature toggles and models.

## Hardware profiles

`[hardware].profile = "auto"` is the default. Detection considers OS, CPU architecture, RAM and available NVIDIA/AMD/Intel/Apple graphics. The selected profile overlays conservative scheduler, context, background-work and batch defaults **before** `config.toml` is merged, so explicit user configuration always wins.

Profiles: `cpu`, `low`, `balanced`, `high`, `max`.

They are resource presets, not hardware restrictions. Ollama remains responsible for its platform-specific accelerator backend and CPU/GPU offload behavior.

## Configuration

Keep `config.toml` small. `defaults.toml` is the complete reference.

```toml
[hardware]
profile = "auto"
auto_tune = true

[models]
background_code = "qwen2.5-coder:3b"
fast_code = "qwen2.5-coder:7b"
heavy_code = "qwen3.5:9b"
reasoning = "qwen3.5:9b"

[code_intelligence]
enabled = true
serena_enabled = true
codegraph_enabled = true
```

To expose Serena/CodeGraph as independent MCP servers as well as through the hub, set `code_intelligence.direct_agent_mcp = true`. The default is `false` to minimize agent schema tokens.

## Agent behavior

The main agent owns orchestration and final integration. Delegation is the default for useful bounded independent work after indexed evidence. Use bounded `local_ai_task` for local-model work when local inference is the right fit; use native Codex subagents only for explicit Codex-subagent requests or Codex-only capabilities. Codex controls scope, write access, workspace/worktree, timeout, cancellation and integration. Never duplicate the same scope across agents.

Setup installs the `local-ai-orchestrator` skill/policy where the host supports it and MCP entries for Codex, Claude, Gemini, Cursor, Windsurf and VS Code/Copilot. Portable manifests are also emitted under `generated/`. The intended order is:

1. on first non-trivial use of a stable absolute root, fire-and-forget `local_ai_repo(action="preprocess", root=...)` once; never poll/wait for it;
2. `deterministic` for exact facts, then `code_index`/`search` for symbols/text;
3. `semantic` (Serena) or `graph` (CodeGraphContext) only for relationships that need them;
4. `context`/`solve` for mixed evidence, with RAG/local-model synthesis only after cheaper indexed paths are insufficient;
5. `local_ai_command` for repeatable tests/lint/typecheck/build/read-only commands;
6. exact `E…` evidence/artifact slices only when source text is required;
7. `local_ai_coord` leases/memos for overlapping multi-agent work.

This is intentionally stronger than merely making tools available: installed policies and MCP descriptions enforce the same cheapest-first gate, prohibit preprocessing/status polling, and treat native broad repository exploration as fallback-only after one bounded hub retry.

## Serena + CodeGraph preprocessing

The preprocessor uses durable phases:

`inventory → hash → code_index → deterministic → serena → codegraph → lexical → rag → files → modules → project → hot_queries → complete`

External indexes are revision-tracked. If Serena/CodeGraph is missing, fails, or exceeds a configured timeout, that phase becomes skipped/degraded and preprocessing continues. The hub never waits indefinitely for an external tool. Interactive queries also use timeout-bounded persistent MCP subprocesses with stderr draining, process-tree termination and circuit cooldowns.

## Local-model tools

The local Ollama tool agent can query:

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

- finite scheduler, command, model, single-flight and external-tool deadlines;
- circuit breakers and bounded model/backend fallback;
- stale/deleted temporary repository roots return structured degraded results instead of crashing request handlers;
- child process trees are terminated on timeout;
- client disconnects are treated as normal socket cancellation and do not destabilize the service;
- derived SQLite/cache/index state is disposable and self-rebuildable;
- supervisor recycles a genuinely unhealthy hub with bounded backoff;
- Windows service setup uses a persistent logon task instead of launching a new supervisor every minute;
- `/health` is lightweight and independent of model availability.

No software can guarantee survival of OS, driver, power or hardware failures, but failure modes are bounded and recoverable.

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
