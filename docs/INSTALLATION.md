# Installation

## Requirements

- Windows 10/11, current macOS, or a modern Linux distribution.
- Python 3.11–3.14.
- Git is recommended. Ollama is optional if local generation is disabled.

## Bootstrap

Windows: `install.ps1`. macOS/Linux: `./install.sh`. The bootstrap delegates to `tools/setup.py`, creates the user installation/state directories, installs core dependencies, optionally installs/pulls Ollama models, installs Serena and CodeGraphContext in isolated environments, configures selected coding agents (Codex, Claude, Gemini, Cursor, Windsurf and VS Code/Copilot), and installs the user service/supervisor.

Useful flags: `--profile cpu|low|balanced|high|max`, `--skip-model-pull`, `--skip-tools`, `--skip-agent-config`, and `--skip-service`. Rerunning setup preserves an existing installed configuration unless `--config` is explicitly supplied.

## Python package

For development/package installation use `pip install .` or an emitted wheel. `local-ai-hub --config /path/config.toml` starts the service.

## Verification

Run `python tools/doctor.py`, `python tools/selftest.py`, and `python -m pytest -q`. The lightweight `/health` endpoint must return the same version as the package.
