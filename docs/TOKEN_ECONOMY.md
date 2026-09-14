# Token-economy tools

The normal Local AI Hub setup installs the `token-economizer` skill and its CLI dependencies, creates `tokcount`, `trim-run`, and `repo-map`, and adds the Hub virtual-environment scripts to the user's `PATH`. It also attempts to install `ast-grep`, `repomix`, `jq`, `rg`, and `fd` using the available package managers. Restart the agent host after setup so it inherits PATH changes.

Use `tokcount <path>` for token counts, `repo-map [path]` for compact code structure, `grep-ast <pattern> <file>` for AST-aware source lookup, and `files-to-prompt -c <paths...>` for selected source. Use `ast-grep`/`sg`, `rg`, `fd`, and `jq` for bounded search and filtering. Run `repomix --stdout --compress` to keep its output in the terminal stream.

`trim-run` truncates a command's output or reads from stdin. It never invokes a shell. When it wraps a command, it accepts only the explicit read/validation/build allowlist; arbitrary scripts, shell chaining, output-writing flags, and mutating commands are rejected. Examples:

```text
trim-run pytest -q --tb=short
git log -n 5 --oneline | trim-run
```

The Local AI Hub command broker applies the same read-only restrictions to these CLI tools. Check installation and PATH resolution with `python tools/doctor.py`.
