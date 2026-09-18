# Installation

## Requirements

- Windows 10/11, current macOS, or a modern Linux distribution.
- Python 3.11–3.14.
- Git is recommended. Ollama is optional if local generation is disabled.

## Bootstrap & One-Command Setup

Tell your AI assistant:
> **"Install Local AI Hub"** *(or "Nainstaluj local ai hub", or run `install.ps1` on Windows / `./install.sh` on macOS/Linux)*

The bootstrap delegates to `tools/setup.py`, creates the user installation/state directories, installs core dependencies, provisions the **Token Economy Suite** (`tokcount`, `trim-run`, `repo-map`, `tiktoken`, `grep-ast`, `files-to-prompt`), registers its CLI directory in the user's persistent `PATH`, probes and installs external CLI helpers (`ripgrep` / `rg`, `fd`, `ast-grep`, `repomix`, `jq`), installs Ollama and pulls its models only when `server.auto_start_ollama = true` and `llama_cpp.fallback_to_ollama = true`, installs Serena and CodeGraphContext in isolated environments, configures selected coding agents (Codex, Claude, Gemini, Cursor, Windsurf, and VS Code/Copilot), deploys agent skills (`local-ai-orchestrator`, `token-economizer`, `caveman`, `tool-orchestration`, `ollama-quality-routing`), and installs the user service/supervisor. With an exclusive `llama_cpp.mode = "on"` route and `fallback_to_ollama = false`, Ollama setup and model pulls are skipped. Open a new terminal after setup for the PATH change to take effect.

Useful flags: `--profile cpu|integrated|low|balanced|high|max`, `--skip-token-economy`, `--skip-companion-skills`, `--skip-model-pull`, `--skip-tools`, `--skip-agent-config`, and `--skip-service`. Rerunning setup preserves an existing installed configuration unless `--config` is explicitly supplied.

See [TOKEN_ECONOMY.md](TOKEN_ECONOMY.md) for full details on token optimization.

## Intel integrated GPU / NPU

For LLM generation on an Intel iGPU, install and configure the llama.cpp SYCL router described in [LLAMA_CPP_SYCL.md](LLAMA_CPP_SYCL.md). The installed Hub config routes preprocessing and all generation tiers through that backend when its model aliases are available.

On a supported Intel Core Ultra system, `--profile auto` can select `integrated`. Setup then installs `requirements-openvino.txt` only when the active model configuration requests the OpenVINO embedding/reranker backend. The OpenVINO runtime and vendor NPU/GPU drivers are separate concerns: if the driver does not expose `NPU`/`GPU`, Local AI Hub reports that state and falls back to CPU instead of failing startup. Use `python tools/doctor.py` to see the detected hardware, OpenVINO devices and active/fallback backend.

Use `--profile integrated` to force the conservative shared-memory profile on a machine whose firmware/driver metadata prevents reliable auto-detection.

## Python package

For development/package installation use `pip install .` or `pip install ".[token-economy]"`. CLI tools `tokcount`, `trim-run`, `repo-map`, and `local-ai-hub` are registered automatically. `local-ai-hub --config /path/config.toml` starts the service.

## Verification

Run `python tools/doctor.py`, `python tools/selftest.py`, `python tools/hubctl.py clean`, and `python -m pytest -q`. The lightweight `/health` endpoint must return the same version as the package.
