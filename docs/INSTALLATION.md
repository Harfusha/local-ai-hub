# Installation

## Requirements

- Windows 10/11, current macOS, or a modern Linux distribution.
- Python 3.11–3.14.
- Git is recommended. Ollama is disabled by default and is never required for Hub installation.

## Bootstrap & One-Command Setup

Tell your AI assistant:
> **"Install Local AI Hub"** *(or "Nainstaluj local ai hub", or run `install.ps1` on Windows / `./install.sh` on macOS/Linux)*

The bootstrap delegates to `tools/setup.py`, creates the user installation/state directories, installs core dependencies, provisions the **Token Economy Suite** (`tokcount`, `trim-run`, `repo-map`, `tiktoken`, `grep-ast`, `files-to-prompt`), registers its CLI directory in the user's persistent `PATH`, probes and installs external CLI helpers (`ripgrep` / `rg`, `fd`, `ast-grep`, `repomix`, `jq`), installs Serena in an isolated environment, configures selected coding agents (Codex, Claude, Gemini, Cursor, Windsurf, and VS Code/Copilot), deploys agent skills, and installs the user service/supervisor. CodeGraphContext is not part of Local AI Hub or its setup/runtime; users may install it separately as an optional standalone repository-analysis package. Ollama is installed or pulled only when all explicit opt-ins are true: `[ollama].enabled = true`, `server.auto_start_ollama = true`, and `llama_cpp.fallback_to_ollama = true`; the default is disabled. With Ollama disabled, `llama_cpp.mode = "on"` explicitly provisions a pinned llama.cpp runtime and default Qwen 1.5B model under `server.state_dir`; `mode = "auto"` detects an existing endpoint only and `"off"` disables llama.cpp. Ollama takes priority whenever enabled, so setup does not install llama.cpp in that configuration. If the selected endpoint is absent, setup reports it without switching providers or installing Ollama as a fallback. Set `[features].vision = false` to remove vision from generated MCP schemas, instructions, capabilities, runtime routing, and setup model pulls. Open a new terminal after setup for the PATH change to take effect.

When `[ollama].enabled = false` (the default), setup and the supervisor do not install or start Ollama. Use `llama_cpp.mode = "on"` for the managed local server, `"auto"` for an existing loopback endpoint, or `"off"` for no llama.cpp backend. Enable Ollama only when that is the selected provider.

Profiles: `auto`, `cpu`, `integrated`, `low`, `balanced`, `high`, or `max`. Optional setup flags:

| Flag | Effect |
| --- | --- |
| `--skip-model-pull` | Disable setup-time Ollama model pulls. Managed llama.cpp provisioning is separate. |
| `--skip-local-nlp-preload` | Skip local NLP/OpenVINO model prefetch. Configured optional dependency installation can still run. |
| `--skip-tools` | Skip Serena installation. |
| `--skip-agent-config` | Skip host-agent configuration; generated manifests and schemas are still written. |
| `--skip-service` | Do not install or restart the managed Hub service for this setup run. |
| `--skip-ollama-install` | Do not install Ollama. An existing executable can still start when all explicit Ollama opt-ins are enabled. |
| `--skip-token-economy` | Skip Token Economy packages and external CLI helper probes. |
| `--skip-companion-skills` | Skip installation of companion skills. |

Rerunning setup preserves an existing installed configuration unless `--config` is explicitly supplied.

See [TOKEN_ECONOMY.md](TOKEN_ECONOMY.md) for full details on token optimization.

## Intel integrated GPU / NPU

For LLM generation on an Intel iGPU, install and configure the llama.cpp SYCL router described in [LLAMA_CPP_SYCL.md](LLAMA_CPP_SYCL.md). The installed Hub config routes preprocessing and all generation tiers through that backend when its model aliases are available.

On a supported Intel Core Ultra system, `--profile auto` can select `integrated`. Setup installs `requirements-openvino.txt` only when the active model configuration requests an OpenVINO embedding/reranker backend, or detected Intel NPU/iGPU policy enables it, including an Intel GPU selected by the `integrated` profile, subject to `features.install_openvino_dependencies`, `openvino.enabled`, and `openvino.auto_install`. `features.install_openvino_dependencies` permits that conditional install; it is not an unconditional install switch. NVIDIA-only systems keep SentenceTransformers/Torch retrieval and do not need OpenVINO. The OpenVINO runtime and vendor NPU/GPU drivers are separate concerns: if the driver does not expose `NPU`/`GPU`, Local AI Hub reports that state and falls back to CPU instead of failing startup. Use `python tools/doctor.py` to see the detected hardware, OpenVINO devices and active/fallback backend.

Use `--profile integrated` to force the conservative shared-memory profile on a machine whose firmware/driver metadata prevents reliable auto-detection.
 
## Optional standalone tool: CodeGraphContext

CodeGraphContext is an independent CLI and MCP server. Local AI Hub does not install, configure, invoke, monitor or fall back to it. Hub setup and operation use Hub-managed features such as the built-in code index; CodeGraphContext has its own package, database, configuration and process lifecycle.

Install CodeGraphContext only if you want that separate tool. Use its [official installation guide](https://codegraphcontext.github.io/getting-started/installation/) and, if needed, its [MCP setup guide](https://github.com/CodeGraphContext/CodeGraphContext/blob/main/docs/docs/getting-started/mcp-setup.md). Configure it directly with the agent that should use it; it is not part of the Hub's `local-ai` MCP entry.
 
## Python package

From the repository root, install the core package with `python -m pip install .`. For development, use `python -m pip install ".[dev]"`; to combine development and Token Economy dependencies, use `python -m pip install ".[dev,token-economy]"`. For Python client usage, see [Python SDK](PYTHON_SDK.md). CLI tools `tokcount`, `trim-run`, `repo-map`, and `local-ai-hub` are registered automatically. `local-ai-hub --config /path/config.toml` starts the service.

When `HubClient` has no explicit `config_path`, it uses `LOCAL_AI_CONFIG` when set; otherwise an existing installed home config takes priority, followed by repository-root `config.toml` for a source checkout, then the home config path as the default.

### Optional Python extras

Install one or more extras with `python -m pip install ".[extra-name]"`; combine names with commas, for example `python -m pip install ".[local-nlp,performance]"`. These are package dependencies from `pyproject.toml`; setup-managed tools, agent configuration, and service installation remain separate.

| Extra | Declared packages |
| --- | --- |
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
