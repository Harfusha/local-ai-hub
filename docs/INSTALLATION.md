# Installation

## Requirements

- Windows 10/11, current macOS, or a modern Linux distribution.
- Python 3.11–3.14.
- Git is recommended. Ollama is disabled by default and is never required for Hub installation.

## Local API security

The Hub binds to `127.0.0.1` by default. A non-loopback bind requires `security.allow_remote = true` and `security.api_token` with at least 16 characters. On loopback, an empty token leaves HTTP data/control routes unauthenticated; set `security.api_token` to protect them. Send it in `X-LocalAI-Token` or `Authorization: Bearer`; `/health` and the dashboard shell are public. The client validates configured `allowed_roots` and root-derived task/memory tenant consistency. This does not establish a general server-enforced principal-to-root authorization boundary or per-token permissions. Tenant labels are not authorization. See [Security model](SECURITY_MODEL.md) for current behavior and pending T13 scope.

## Bootstrap & One-Command Setup

Tell your AI assistant:
> **"Install Local AI Hub"** *(or "Nainstaluj local ai hub", or run `install.ps1` on Windows / `./install.sh` on macOS/Linux)*

The bootstrap delegates to `tools/setup.py`, creates the user installation/state directories, installs core dependencies, provisions the **Token Economy Suite** (`tokcount`, `trim-run`, `repo-map`, `tiktoken`, `grep-ast`, `files-to-prompt`), registers its CLI directory in the user's persistent `PATH`, probes and installs external CLI helpers (`ripgrep` / `rg`, `fd`, `ast-grep`, `repomix`, `jq`), installs Serena in an isolated environment, configures selected coding agents (Codex, Claude, Gemini, Cursor, Windsurf, and VS Code/Copilot), deploys agent skills, and installs the user service/supervisor. CodeGraphContext is not a Hub dependency or analysis backend; Hub does not install, configure, preprocess, invoke, or report it. Users may install CodeGraphContext separately as optional standalone tooling. Ollama is installed or pulled only when all explicit opt-ins are true: `[ollama].enabled = true`, `server.auto_start_ollama = true`, and `llama_cpp.fallback_to_ollama = true`; the default is disabled. With Ollama disabled, `llama_cpp.mode = "on"` explicitly provisions a pinned llama.cpp runtime and default Qwen 1.5B model under `server.state_dir`; `mode = "auto"` detects an existing endpoint only and `"off"` disables llama.cpp. Ollama takes priority whenever enabled, so setup does not install llama.cpp in that configuration. If the selected endpoint is absent, setup reports it without switching providers or installing Ollama as a fallback. Set `[features].vision = false` to remove vision from generated MCP schemas, instructions, capabilities, runtime routing, and setup model pulls. Open a new terminal after setup for the PATH change to take effect.

When `[ollama].enabled = false` (the default), setup and the supervisor do not install or start Ollama. Use `llama_cpp.mode = "on"` for the managed local server, `"auto"` for an existing loopback endpoint, or `"off"` for no llama.cpp backend. Enable Ollama only when that is the selected provider.

Useful flags: `--profile cpu|integrated|low|balanced|high|max`, `--skip-token-economy`, `--skip-companion-skills`, `--skip-model-pull`, `--skip-tools`, `--skip-agent-config`, and `--skip-service`. `--skip-service` skips per-user service-manager registration, but setup still restarts the Hub as a user process with `hubctl`; it does not suppress Hub startup. Rerunning setup preserves an existing installed configuration unless `--config` is explicitly supplied.

Target shared runtime uses one per-user Hub install, one configured `server.state_dir`, and one user-level supervisor/daemon for all Codex chats and worktrees under that OS account. Every enabled agent uses a lightweight stdio proxy. Acceptance: clean install registers exactly one user service; update reuses or reconciles that same registration. Never install or register a daemon per agent, chat, repository, or worktree. The generated global Codex `local-ai` entry starts `python -m local_ai_hub.mcp_server` as a stdio adapter; each active Codex MCP session may own one adapter process. The adapter forwards Hub calls through `HubClient` over HTTP. It creates bounded protocol/metadata helpers, but must not create `LocalAIApp`, `HubServices`, `ProjectPreprocessor`, `CodeIndex`, `RAGStore`, or model pools. Multiple adapter processes do not prove duplicate daemons; inspect parent/command line and the OS service identity. The single per-user supervisor starts the HTTP daemon at logon/session startup. Global Codex `cwd=install_dir` is not the caller's project root, and setup injects no project-root environment. Current candidate maps missing or `.` roots to the MCP working directory for most repository/RAG actions; preprocessing alone rejects a missing absolute root. Always pass the caller's explicit project root. Release acceptance stays blocked until T03 rejects rootless repository-scoped actions or a tested adapter supplies caller root explicitly. Client identity/transport and operational-mode source contracts do not prove installed runtime acceptance. `HubClient` autostart is bounded and cross-process locked; a managed supervisor, live supervisor PID, or occupied port blocks another daemon launch. Generated agent command, arguments, working directory and environment remain authoritative. Project-local MCP manifests use `target_root` as `cwd`; global manifests use `install_dir`. Every global repository, task, or memory request must set the `root` field to the caller's project root and preserve task context. Both MCP API and `HubClient` send that root explicitly; never infer it from `install_dir` or process cwd. The target server contract requires effective tenant derived from principal and canonical root, with caller metadata used only for consistency. Current client preflight is not proof of server-enforced isolation. Installed auth/lifecycle acceptance requires separate revision-bound runtime evidence. The service manager starts the daemon when the user session starts after reboot (Windows logon task, macOS LaunchAgent, or Linux user service). `--skip-service` leaves only a session process; it does not configure reboot startup.

During migration or update, rerun setup to refresh the managed Hub MCP entries while preserving unrelated agent entries. Project-local manifests use `target_root` as their working directory; global manifests use the Hub `install_dir`. Every global repository, task, or memory request must set `root` to the caller's project root and preserve task context; never treat `install_dir` as the repository root. Client identity checks do not establish server-enforced effective-tenant isolation. Back up affected agent MCP configuration files with the Hub installation, `config.toml`, and `server.state_dir`. Record the single platform user-service identity and enabled state separately; registration is external to the file snapshot. On rollback, reconcile that same service once with the matching release before starting it; do not register per agent or worktree. See [Operations rollback](OPERATIONS.md#rollback-and-durable-state-recovery) for a matched snapshot and rollback procedure.

See [TOKEN_ECONOMY.md](TOKEN_ECONOMY.md) for full details on token optimization.

## Intel integrated GPU / NPU

For LLM generation on an Intel iGPU, install and configure the llama.cpp SYCL router described in [LLAMA_CPP_SYCL.md](LLAMA_CPP_SYCL.md). The installed Hub config routes preprocessing and all generation tiers through that backend when its model aliases are available.

On a supported Intel Core Ultra system, `--profile auto` can select `integrated`. Setup installs `requirements-openvino.txt` only when the active model configuration requests an OpenVINO embedding/reranker backend, or detected Intel NPU/iGPU policy enables it, including an Intel GPU selected by the `integrated` profile, subject to `features.install_openvino_dependencies`, `openvino.enabled`, and `openvino.auto_install`. `features.install_openvino_dependencies` permits that conditional install; it is not an unconditional install switch. NVIDIA-only systems keep SentenceTransformers/Torch retrieval and do not need OpenVINO. The OpenVINO runtime and vendor NPU/GPU drivers are separate concerns: if the driver does not expose `NPU`/`GPU`, Local AI Hub reports that state and falls back to CPU instead of failing startup. Use `python tools/doctor.py` to see the detected hardware, OpenVINO devices and active/fallback backend.

Use `--profile integrated` to force the conservative shared-memory profile on a machine whose firmware/driver metadata prevents reliable auto-detection.

## Optional standalone tool: CodeGraphContext

CodeGraphContext and KuzuDB are not Hub dependencies or backends; both are separate from Local AI Hub. Any CodeGraphContext installation or MCP setup below is optional standalone tooling outside Hub. Hub does not discover, report, or use the standalone installation.

For users who independently choose standalone CodeGraphContext for deep call-graph analysis, install it directly in the target repository or environment. This is separate from Hub installation:

- **Benefits**: Deep call graphs, caller/callee tracing, blast-radius impact analysis, and dead code detection.
- **Standalone installation**:
  ```bash
  pip install "codegraphcontext[gcf]==0.6.13"
  ```
- **Standalone Agent MCP configuration** (e.g. in `.cursor/mcp.json`, `claude_desktop_config.json`, or Codex configuration). This connects an agent directly to CodeGraphContext; it does not configure Local AI Hub:
  ```json
  {
    "mcpServers": {
      "codegraph": {
        "command": "codegraphcontext",
        "args": ["mcp", "start"]
      }
    }
  }
  ```
- **Local AI Hub analysis**: Built-in AST indexing and symbol analysis remain available independently. CodeGraphContext is not a Hub backend and does not trigger a Hub fallback path.

## Python package

For development/package installation use `pip install .` or `pip install ".[token-economy]"`. CLI tools `tokcount`, `trim-run`, `repo-map`, and `local-ai-hub` are registered automatically. `local-ai-hub --config /path/config.toml` starts the service. See [Python SDK](PYTHON_SDK.md) for the `HubClient` API.

## Verification

Run `python tools/doctor.py`, `python tools/selftest.py`, `python tools/hubctl.py clean`, and `python -m pytest -q`. The lightweight `/health` endpoint must return the same version as the package.
