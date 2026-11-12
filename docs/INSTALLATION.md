# Installation

## Requirements

- Windows 10/11, current macOS, or a modern Linux distribution.
- Python 3.11–3.14.
- Git is recommended. Ollama is disabled by default and is never required for Hub installation.

## Local API security

The Hub accepts loopback connections only and must bind to `127.0.0.1`. No Hub API token or bearer credential exists; loopback HTTP/MCP calls need no Hub credential. Non-loopback peers are rejected before routing. Same-origin checks protect dashboard mutations. Configured `allowed_roots`, command authorization, capabilities, approvals, leases, rate limits, and audit records continue to constrain operations. Retired token fields reject by presence. See [Security model](SECURITY_MODEL.md).

## Bootstrap & One-Command Setup

Run `install.ps1` on Windows or `./install.sh` on macOS/Linux. A terminal run opens the interactive installer; previous choices are remembered. Pass `--non-interactive` for automation. Full reinstall and recovery steps are documented in [INSTALLER_RECOVERY.md](INSTALLER_RECOVERY.md).

The interactive wizard can enable MCP, skills, and instructions separately for Codex, Claude Code, Gemini CLI, Cursor, Windsurf, and VS Code/Copilot. Per-agent choices are remembered alongside the component selections. When agent setup is disabled, its saved per-agent choices remain available for a later run.

`setup-report.json` records Token Economy dependency and wrapper results, plus whether optional external CLI helpers were detected after setup. If a package manager updated `PATH`, open a new terminal before treating a helper as unavailable.

The model section of `setup-report.json` lists configured Ollama models requested, ready, skipped by choice, or unavailable. It also records managed llama.cpp selection/readiness, per-model NLP/OpenVINO preload outcomes, and whether the configured Laya checkpoint directory is present. Setup does not hash or load the Laya model; the runtime verifies configured file hashes on first eligible inference. Laya packages install only when selected, and setup does not download the checkpoint because configuration requires a locally supplied, hash-pinned directory.

Failures during core runtime installation, state migration, full reinstall, install-payload replacement, model provisioning, service registration, Hub restart, or Codex/Gemini Superpowers setup also produce a `failed` setup report with the failing stage and recovery-guide path. Agent-configuration failures are recorded as partial setup and include the error in `manual_actions`.

Tell your AI assistant:
> **"Install Local AI Hub"** *(or "Nainstaluj local ai hub", or run `install.ps1` on Windows / `./install.sh` on macOS/Linux)*

The bootstrap delegates to `tools/setup.py`, creates the user installation/state directories, installs core dependencies, provisions the **Token Economy Suite** (`tokcount`, `trim-run`, `repo-map`, `tiktoken`, `grep-ast`, `files-to-prompt`), registers its CLI directory in the user's persistent `PATH`, probes and installs external CLI helpers (`ripgrep` / `rg`, `fd`, `ast-grep`, `repomix`, `jq`), installs Serena in an isolated environment, configures selected coding agents (Codex, Claude, Gemini, Cursor, Windsurf, and VS Code/Copilot), deploys agent skills, and installs the user service/supervisor. CodeGraphContext is not a Hub dependency or analysis backend; Hub does not install, configure, preprocess, invoke, or report it. Users may install CodeGraphContext separately as optional standalone tooling. Ollama is installed or pulled only when all explicit opt-ins are true: `[ollama].enabled = true`, `server.auto_start_ollama = true`, and `llama_cpp.fallback_to_ollama = true`; the default is disabled. With Ollama disabled, `llama_cpp.mode = "on"` explicitly provisions a pinned llama.cpp runtime and default Qwen 1.5B model under `server.state_dir`; `mode = "auto"` detects an existing endpoint only and `"off"` disables llama.cpp. Ollama takes priority whenever enabled, so setup does not install llama.cpp in that configuration. If the selected endpoint is absent, setup reports it without switching providers or installing Ollama as a fallback. Set `[features].vision = false` to remove vision from generated MCP schemas, instructions, capabilities, runtime routing, and setup model pulls. Open a new terminal after setup for the PATH change to take effect.

When `[ollama].enabled = false` (the default), setup and the supervisor do not install or start Ollama. Use `llama_cpp.mode = "on"` for the managed local server, `"auto"` for an existing loopback endpoint, or `"off"` for no llama.cpp backend. Enable Ollama only when that is the selected provider.

Useful flags: `--profile cpu|integrated|low|balanced|medium|high|max`, `--skip-token-economy`, `--skip-companion-skills`, `--skip-model-pull`, `--skip-tools`, `--skip-agent-config`, `--skip-service`, `--skip-laya-runtime`, `--skip-ast-index`, `--skip-performance`, and `--skip-profiling`. Explicit skip flags affect only the current run; saved wizard choices remain unchanged. `--skip-service` skips per-user service-manager registration, but setup still restarts the Hub as a user process with `hubctl`; it does not suppress Hub startup. Rerunning setup preserves an existing installed configuration unless `--config` is explicitly supplied.

Target shared runtime uses one per-user Hub install, one configured `server.state_dir`, and one user-level supervisor/daemon for all Codex chats and worktrees under that OS account. Every enabled agent uses a lightweight stdio proxy. Acceptance: clean install registers exactly one user service; update reuses or reconciles that same registration. Never install or register a daemon per agent, chat, repository, or worktree. The generated global Codex `local-ai` entry starts `python -m local_ai_hub.mcp_server` as a stdio adapter; each active Codex MCP session may own one adapter process. The adapter forwards Hub calls through `HubClient` over HTTP. It creates bounded protocol/metadata helpers, but must not create `LocalAIApp`, `HubServices`, `ProjectPreprocessor`, `CodeIndex`, `RAGStore`, or model pools. Multiple adapter processes do not prove duplicate daemons; inspect parent/command line and the OS service identity. The single per-user supervisor starts the HTTP daemon at logon/session startup. Global Codex manifests now inherit the host's project working directory; setup injects no project-root environment. Repository-scoped repo/RAG MCP actions now reject missing or `.` roots at the adapter boundary; preprocessing likewise rejects a missing absolute root. Always pass the caller's explicit project root. Release acceptance still requires installed-runtime and deployment proof for this source-level guard. Client identity/transport and operational-mode source contracts do not prove installed runtime acceptance. `HubClient` autostart is bounded and cross-process locked; a managed supervisor, live supervisor PID, or occupied port blocks another daemon launch. Generated agent command, arguments, working directory and environment remain authoritative. Project-local MCP manifests set `target_root` as `cwd`; global manifests omit `cwd` and inherit the host's project directory. A global request can pass explicit `root` when it targets another project and must preserve task context. Both MCP API and `HubClient` send that root explicitly; never infer it from `install_dir` or process cwd. Current source uses explicit repository roots and loopback-only access; retired tenant selectors reject by presence. Client preflight and source review do not establish installed-runtime acceptance. Installed lifecycle acceptance requires separate revision-bound runtime evidence. The service manager starts the daemon when the user session starts after reboot (Windows logon task, macOS LaunchAgent, or Linux user service). `--skip-service` leaves only a session process; it does not configure reboot startup.

During migration or update, rerun setup to refresh the managed Hub MCP entries while preserving unrelated agent entries. Project-local manifests use `target_root` as their working directory; global manifests use the Hub `install_dir`. Every global repository, task, or memory request must set `root` to the caller's project root and preserve task context; never treat `install_dir` as the repository root. Client checks supplement server-side root authorization; source changes do not establish installed-runtime acceptance. Back up affected agent MCP configuration files with the Hub installation, `config.toml`, and `server.state_dir`. Record the single platform user-service identity and enabled state separately; registration is external to the file snapshot. On rollback, reconcile that same service once with the matching release before starting it; do not register per agent or worktree. See [Operations rollback](OPERATIONS.md#rollback-and-durable-state-recovery) for a matched snapshot and rollback procedure.

See [TOKEN_ECONOMY.md](TOKEN_ECONOMY.md) for full details on token optimization.

## Intel integrated GPU / NPU

For LLM generation on an Intel iGPU, install and configure the llama.cpp SYCL router described in [LLAMA_CPP_SYCL.md](LLAMA_CPP_SYCL.md). The installed Hub config routes preprocessing and all generation tiers through that backend when its model aliases are available.

On a supported Intel Core Ultra system, `--profile auto` can select `integrated`. Setup installs `requirements-openvino.txt` only when the active model configuration requests an OpenVINO embedding/reranker backend, or detected Intel NPU/iGPU policy enables it, including an Intel GPU selected by the `integrated` profile, subject to `features.install_openvino_dependencies`, `openvino.enabled`, and `openvino.auto_install`. `features.install_openvino_dependencies` permits that conditional install; it is not an unconditional install switch. Embeddings and reranking default to `auto` and try NPU, dedicated GPU, integrated GPU, then CPU. NVIDIA CUDA, supported AMD ROCm, Intel OpenVINO, and ONNX Runtime DirectML routes require their own compatible optional runtime and drivers; Local AI Hub does not install missing provider packages or fetch model weights for route conversion. Provider/model failures fall through to the next route. Use `python tools/doctor.py` to see detected hardware and OpenVINO devices.

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

The installer wizard manages selectable runtime extras: `ast-index`, `local-nlp`, `performance`, and `profiling`. It installs `token-economy`, `laya-runtime`, and `intel-accelerators` through their matching component choices and hardware/configuration checks. These packages are pinned or bounded in `pyproject.toml`; setup reports selected, failed, and skipped components.

The `dev` extra is for Local AI Hub contributors, not the installed Hub service. To add it to a development environment, run `python -m pip install ".[dev]"` from the source root. The `intel-accelerators` extra is installed only for a selected Intel OpenVINO route; drivers and vendor UI steps remain manual. Sentence Transformers ONNX and DirectML are separate optional runtimes. For Windows DirectML, install the Sentence Transformers ONNX extra, then replace its CPU ONNX Runtime package with `onnxruntime-directml`; keep only one ONNX Runtime distribution installed. See the [Sentence Transformers ONNX guide](https://sbert.net/docs/sentence_transformer/usage/efficiency.html#onnx) and [ONNX Runtime DirectML installation guide](https://onnxruntime.ai/docs/install/#install-onnx-runtime-gpu-directml). AMD ROCm and Ryzen AI NPU support is limited to the exact hardware, driver and Windows versions listed by [AMD's compatibility matrix](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityrad/windows/windows_compatibility.html). CodeGraphContext is a separate standalone product, not a Hub extra. After dependency or source updates, fully cycle the existing per-user service (do not create a second one):

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
| `laya-runtime` | `laya`, `vegaml` (only for selected Laya inference) |
| `token-economy` | `tiktoken`, `files-to-prompt`, `grep-ast` |
| `performance` | `orjson`, `msgspec`, `Cython` |
| `native` | `Cython` build dependency; also included in `performance`. The experimental native module is built separately. |
| `profiling` | `py-spy`, `scalene` |
| `dev` | `pytest`, `pyflakes`, `coverage[toml]`, `psutil`, `numpy`, `setuptools`, `wheel` |

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
