# Contributing to Local AI Hub

Local AI Hub is an initial-release codebase. Prefer deletion/simplification over compatibility shims.

## Getting started

`ash
git clone https://github.com/YOUR_GITHUB_USERNAME/local-ai-hub.git
cd local-ai-hub
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements-core.txt
pip install -e ".[dev]"
`

## Before submitting a change

Run the full validation suite locally before opening a PR:

`ash
python -m compileall -q src mcp tools tests
python -m pytest -q
python tools/selftest.py
`

All three commands must pass with no errors.

## Design principles

- Keep the **seven-tool MCP surface compact** — new repository capabilities should go through local_ai_repo or local_ai_command, not a new top-level MCP schema.
- Keep **all waits bounded** — every subprocess, network call and model call must have a finite deadline. No 	ime.sleep in hot paths without a bounded loop.
- Preserve **loopback-first security** — the server must bind to 127.0.0.1 by default. Remote exposure is opt-in and requires an API token.
- **Optional external tooling must fail soft** — Serena, CodeGraphContext and Ollama absence, crash or timeout must degrade cleanly to built-in indexes, never block a request handler.
- **No migration shims** in this initial-release branch. Derived SQLite state is disposable and may be rebuilt.

## Commit messages

Use the imperative mood, present tense:

`
Add bounded retry for external MCP responses
Fix SQLite busy handling in semantic cache
Improve hardware detection for AMD GPUs
`

Keep the subject line under 72 characters. Optionally add a body after a blank line for context.

## Pull request checklist

- [ ] python -m compileall -q src mcp tools tests passes
- [ ] python -m pytest -q passes
- [ ] python tools/selftest.py passes
- [ ] No new MCP tool schemas added without discussion
- [ ] All subprocess/network calls have timeouts
- [ ] Optional backends degrade gracefully (no hard failures for missing Serena/CodeGraph)
- [ ] Updated CHANGELOG.md with a brief entry if user-visible

## Reporting bugs

Open a GitHub issue using the **Bug report** template. Include:
- OS and Python version
- Hub version (python tools/hubctl.py status)
- Minimal reproduction steps
- Relevant log excerpts (redact paths/source if needed)

## Security vulnerabilities

Do **not** open a public issue. Use GitHub's private security advisory feature instead.
See SECURITY.md for details.

## License

By contributing, you agree your changes will be released under the project's MIT license.
