# Local AI Hub update prompt

Update Local AI Hub with the repository's supported installer. Preserve the user's current configuration and unrelated agent instructions, then regenerate and merge the current Hub policy and companion skills.

Ensure the update refreshes the token-economizer skill, its dependencies, CLI wrappers, and the user's `PATH` entry for the Hub virtual-environment scripts directory. The command broker should allow the bundled read-only token-economy CLIs and `trim-run` only when it wraps an explicitly safe read/validation/build command. Keep `repomix` in stdout mode and keep mutating or unknown commands disabled by default.

Preserve model routing defaults: use `qwen2.5-coder:1.5b-instruct-q5_K_M` only for background preprocessing, `qwen2.5-coder:3b-instruct-q5_K_M` as the default fast/general model, and escalate to `qwen2.5-coder:7b-instruct-q5_K_M` only for complex or high-risk work. Keep simple deterministic repository tasks on indexed or deterministic Hub actions; verify aliases against Ollama `/api/tags`.

After the update, start a fresh shell or restart the agent host to pick up `PATH`, then verify with `tools/doctor.py`, `hubctl status`, and the repository's prescribed validation commands.
