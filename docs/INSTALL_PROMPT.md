# Local AI Hub installation prompt

Install Local AI Hub using the repository's supported installer for this operating system. Keep the user's existing configuration and merge the generated agent instructions into their existing agent files.

The normal installation must install the `token-economizer` companion skill and token-economy dependencies, create the `tokcount`, `trim-run`, and `repo-map` commands, and add the Hub virtual-environment scripts directory to the user's `PATH`. It also installs the `grep-ast` and `files-to-prompt` CLIs. After installation, start a fresh shell or restart the agent host so it receives the updated `PATH`.

Use these commands by default for bounded repository work: `tokcount`, `repo-map`, `grep-ast`, `files-to-prompt -c`, `ast-grep`/`sg`, `rg`, `fd`, and `jq`. Route repeatable tests and validation through `local_ai_command` when available. `trim-run` may wrap only commands accepted by the safe read/validation/build allowlist; for other output, pipe it into `trim-run` stdin mode. Use `repomix --stdout --compress` so it does not write an output file.

Keep command-broker defaults limited to safe reads, validation, and builds. Do not enable unrestricted commands, unknown executables, or mutation globally to make the tools work. Verify the install with `tools/doctor.py` and `hubctl status`.

Use `qwen2.5-coder:1.5b-instruct-q5_K_M` only for background preprocessing, `qwen2.5-coder:3b-instruct-q5_K_M` as the default fast/general model, and escalate to `qwen2.5-coder:7b-instruct-q5_K_M` only for complex or high-risk work. Keep simple deterministic repository tasks on indexed or deterministic Hub actions; use only model aliases confirmed by Ollama `/api/tags`.
