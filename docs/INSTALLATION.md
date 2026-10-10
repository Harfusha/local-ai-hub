# Installation

## Requirements

- Windows 10/11, current macOS, or a modern Linux distribution.
- Python 3.11–3.14.
- Git is recommended. Ollama is disabled by default and is never required for Hub installation.

## Local API security

The Hub binds to `127.0.0.1` by default. Remote binding is unsupported; the HTTP server must bind to `127.0.0.1`. On loopback, set `security.api_token` when trusted local integrations need token authentication. Send it in `X-LocalAI-Token` or `Authorization: Bearer`; `/health` and the dashboard shell are public. The client validates configured `allowed_roots` and root-derived task/memory tenant consistency. This does not establish a general server-enforced principal-to-root authorization boundary or per-token permissions. Tenant labels are not authorization. See [Security model](SECURITY_MODEL.md) for current behavior and pending T13 scope.

## Bootstrap & One-Command Setup

Tell your AI assistant:
> **"Install Local AI Hub"** *(or "Nainstaluj local ai hub", or run `install.ps1` on Windows / `./install.sh` on macOS/Linux)*

The bootstrap delegates to `tools/setup.py`, creates the user installation/state directories, installs core dependencies, provisions the **Token Economy Suite** (`tokcount`, `trim-run`, `repo-map`, `tiktoken`, `grep-ast`, `files-to-prompt`), registers its CLI directory in the user's persistent `PATH`, probes and installs external CLI helpers (`ripgrep` / `rg`, `fd`, `ast-grep`, `repomix`, `jq`), installs Serena in an isolated environment, configures selected coding agents (Codex, Claude, Gemini, Cursor, Windsurf, and VS Code/Copilot), deploys agent skills, and installs the user service/supervisor. CodeGraphContext is not a Hub dependency or analysis backend; Hub does not install, configure, preprocess, invoke, or report it. Users may install CodeGraphContext separately as optional standalone tooling. Ollama is installed or pulled only when all explicit opt-ins are true: `[ollama].enabled = true`, `server.auto_start_ollama = true`, and `llama_cpp.fallback_to_ollama = true`; the default is disabled. With Ollama disabled, `llama_cpp.mode = "on"` explicitly provisions a pinned llama.cpp runtime and default Qwen 1.5B model under `server.state_dir`; `mode = "auto"` detects an existing endpoint only and `"off"` disables llama.cpp. Ollama takes priority whenever enabled, so setup does not install llama.cpp in that configuration. If the selected endpoint is absent, setup reports it without switching providers or installing Ollama as a fallback. Set `[features].vision = false` to remove vision from generated MCP schemas, instructions, capabilities, runtime routing, and setup model pulls. Open a new terminal after setup for the PATH change to take effect.

When `[ollama].enabled = false` (the default), setup and the supervisor do not install or start Ollama. Use `llama_cpp.mode = "on"` for the managed local server, `"auto"` for an existing loopback endpoint, or `"off"` for no llama.cpp backend. Enable Ollama only when that is the selected provider.

Useful flags: `--profile cpu|integrated|low|balanced|high|max`, `--skip-token-economy`, `--skip-companion-skills`, `--skip-model-pull`, `--skip-tools`, `--skip-agent-config`, and `--skip-service`. `--skip-service` skips per-user service-manager registration, but setup still restarts the Hub as a user process with `hubctl`; it does not suppress Hub startup. Rerunning setup preserves an existing installed configuration unless `--config` is explicitly supplied.

Target shared runtime uses one per-user Hub install, one configured `server.state_dir`, and one user-level supervisor/daemon for all Codex chats and worktrees under that OS account. Every enabled agent uses a lightweight stdio proxy. Acceptance: clean install registers exactly one user service; update reuses or reconciles that same registration. Never install or register a daemon per agent, chat, repository, or worktree. The generated global Codex `local-ai` entry starts `python -m local_ai_hub.mcp_server` as a stdio adapter; each active Codex MCP session may own one adapter process. The adapter forwards Hub calls through `HubClient` over HTTP. It creates bounded protocol/metadata helpers, but must not create `LocalAIApp`, `HubServices`, `ProjectPreprocessor`, `CodeIndex`, `RAGStore`, or model pools. Multiple adapter processes do not prove duplicate daemons; inspect parent/command line and the OS service identity. The single per-user supervisor starts the HTTP daemon at logon/session startup. Global Codex manifests now inherit the host's project working directory; setup injects no project-root environment. Repository-scoped repo/RAG MCP actions now reject missing or `.` roots at the adapter boundary; preprocessing likewise rejects a missing absolute root. Always pass the caller's explicit project root. Release acceptance still requires installed-runtime and deployment proof for this source-level guard. Client identity/transport and operational-mode source contracts do not prove installed runtime acceptance. `HubClient` autostart is bounded and cross-process locked; a managed supervisor, live supervisor PID, or occupied port blocks another daemon launch. Generated agent command, arguments, working directory and environment remain authoritative. Project-local MCP manifests set `target_root` as `cwd`; global manifests omit `cwd` and inherit the host's project directory. A global request can pass explicit `root` when it targets another project and must preserve task context. Both MCP API and `HubClient` send that root explicitly; never infer it from `install_dir` or process cwd. The target server contract requires effective tenant derived from principal and canonical root, with caller metadata used only for consistency. Current client preflight is not proof of server-enforced isolation. Installed auth/lifecycle acceptance requires separate revision-bound runtime evidence. The service manager starts the daemon when the user session starts after reboot (Windows logon task, macOS LaunchAgent, or Linux user service). `--skip-service` leaves only a session process; it does not configure reboot startup.

During migration or update, rerun setup to refresh the managed Hub MCP entries while preserving unrelated agent entries. Project-local manifests use `target_root` as their working directory; global manifests use the Hub `install_dir`. Every global repository, task, or memory request must set `root` to the caller's project root and preserve task context; never treat `install_dir` as the repository root. Client identity checks do not establish server-enforced effective-tenant isolation. Back up affected agent MCP configuration files with the Hub installation, `config.toml`, and `server.state_dir`. Record the single platform user-service identity and enabled state separately; registration is external to the file snapshot. On rollback, reconcile that same service once with the matching release before starting it; do not register per agent or worktree. See [Operations rollback](OPERATIONS.md#rollback-and-durable-state-recovery) for a matched snapshot and rollback procedure.

See [TOKEN_ECONOMY.md](TOKEN_ECONOMY.md) for full details on token optimization.

## Intel integrated GPU / NPU

For LLM generation on an Intel iGPU, install and configure the llama.cpp SYCL router described in [LLAMA_CPP_SYCL.md](LLAMA_CPP_SYCL.md). The installed Hub config routes preprocessing and all generation tiers through that backend when its model aliases are available.

On a supported Intel Core Ultra system, `--profile auto` can select `integrated`. Setup installs `requirements-openvino.txt` only when the active model configuration requests an OpenVINO embedding/reranker backend, or detected Intel NPU/iGPU policy enables it, including an Intel GPU selected by the `integrated` profile, subject to `features.install_openvino_dependencies`, `openvino.enabled`, and `openvino.auto_install`. `features.install_openvino_dependencies` permits that conditional install; it is not an unconditional install switch. NVIDIA-only systems keep SentenceTransformers/Torch retrieval and do not need OpenVINO. The OpenVINO runtime and vendor NPU/GPU drivers are separate concerns: if the driver does not expose `NPU`/`GPU`, Local AI Hub reports that state and falls back to CPU instead of failing startup. Use `python tools/doctor.py` to see the detected hardware, OpenVINO devices and active/fallback backend.

Use `--profile integrated` to force the conservative shared-memory profile on a machine whose firmware/driver metadata prevents reliable auto-detection.

## Optional standalone tool: CodeGraphContext

CodeGraphContext is an independent CLI and MCP server. Local AI Hub does not install, configure, invoke, monitor or fall back to it. Hub setup and operation use Hub-managed features such as the built-in code index; CodeGraphContext has its own package, database, configuration and process lifecycle.

CodeGraphContext and KuzuDB are not Hub dependencies or backends; users may install them separately as optional standalone tools. To use it separately, install it directly in the target repository or environment only when independently wanted.

Install CodeGraphContext only if you want that separate tool. Use its [official installation guide](https://codegraphcontext.github.io/getting-started/installation/) and, if needed, its [MCP setup guide](https://github.com/CodeGraphContext/CodeGraphContext/blob/main/docs/docs/getting-started/mcp-setup.md). Configure it directly with the agent that should use it; it is not part of the Hub's `local-ai` MCP entry.

This connects an agent directly to CodeGraphContext; it does not configure Local AI Hub.

## Python package

From the repository root, install the core package with `python -m pip install .`. For development, use `python -m pip install ".[dev]"`; to combine development and Token Economy dependencies, use `python -m pip install ".[dev,token-economy]"`. For Python client usage, see [Python SDK](PYTHON_SDK.md). CLI tools `tokcount`, `trim-run`, `repo-map`, and `local-ai-hub` are registered automatically. `local-ai-hub --config /path/config.toml` starts the service.

When `HubClient` has no explicit `config_path`, it uses `LOCAL_AI_CONFIG` when set; otherwise an existing installed home config takes priority, followed by repository-root `config.toml` for a source checkout, then the home config path as the default.

### Optional Python extras

Install one or more extras with `python -m pip install ".[extra-name]"`; combine names with commas, for example `python -m pip install ".[local-nlp,performance]"`. These are package dependencies from `pyproject.toml`; setup-managed tools, agent configuration, and service installation remain separate.

To provision every declared non-Intel extra in the active Windows Hub environment, run this from the verified installation root after setup:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade ".[ast-index,local-nlp,token-economy,performance,profiling,dev]"
```

This includes NLP/model dependencies and development/profiling tools, so it can consume substantial disk space and may take several minutes. `intel-accelerators` is deliberately excluded; install it only for an Intel OpenVINO/SYCL setup. CodeGraphContext is a separate standalone product, not a Hub extra. After dependency or source updates, fully cycle the existing per-user service (do not create a second one):

```powershell
python tools/service.py stop
python tools/service.py status
python tools/service.py start
python tools/hubctl.py status
python tools/doctor.py
```

Confirm the old daemon stopped before starting, then verify the active version, mode, selected backend, and service identity. Preserve `config.toml` and `server.state_dir`; do not reset durable state as part of a routine restart.

On Windows, the preferred persistent service identity is Task Scheduler task `LocalAIHubSupervisor`. If task registration is blocked, `tools/service.py install` may use the per-user Run-key fallback `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\LocalAIHubSupervisor` (`windows-user-startup`). Verify which identity is active; a detached process alone is not reboot-persistent service registration.

| Extra | Declared packages |
| --- | --- |
| `ast-index` | `tree-sitter-language-pack` |
| `local-nlp` | `sentence-transformers` |
| `intel-accelerators` | `sentence-transformers[openvino]`, `openvino` |
| `token-economy` | `tiktoken`, `files-to-prompt`, `grep-ast` |
| `performance` | `orjson`, `msgspec`, `Cython` |
| `profiling` | `py-spy`, `scalene` |
| `dev` | `pytest`, `pyflakes`, `coverage[toml]` |

## Verification

After setup, activate the installed `.venv` and run from the active installation root:

```text
python tools/doctor.py --json
python tools/hubctl.py status --json
```

The lightweight `/health` endpoint must return the same version as the package. Its default URL is `http://127.0.0.1:11435/health`; use the active config's bind address and port when they differ. From the activated venv, compare the running service and installed package with:

```text
python -c 'import importlib.metadata as m,json,urllib.request; h=json.load(urllib.request.urlopen("http://127.0.0.1:11435/health", timeout=3)); p=m.version("local-ai-hub"); print({"health_version":h["version"],"package_version":p}); assert h["version"] == p'
```

`python tools/selftest.py` and `python -m pytest -q` are source-checkout checks, separate from installed-instance verification. `python tools/hubctl.py clean` removes repository caches and build artifacts; it is not an installation check.

`python tools/release_check.py` ignores disposable `__pycache__`, `.pyc`, `.pyo`, and `.pytest_cache` files in a working checkout; Git already ignores them. Use `--allow-installed` for a live checkout containing managed environments and runtime state. Validate a clean release tree with `--strict-tree`, which rejects these caches and cannot be combined with `--post-test` or `--allow-installed`. Build outputs and unrelated runtime payloads remain checked according to the selected mode.
