# Contributing to Local AI Hub

Local AI Hub 3.0 is the sole supported application contract. Prefer one direct implementation over parallel aliases or alternate historical paths.

## Getting started

```bash
git clone https://github.com/local-ai-hub/local-ai-hub.git
cd local-ai-hub
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements-core.txt
pip install -e ".[dev]"
```

## Before submitting a change

Run the full validation suite locally before opening a PR:

```bash
python -m compileall -q src tools tests
python -m pytest -q
python tools/selftest.py
python tools/hubctl.py generate
```

All commands must pass with no errors.

## Design principles

- Keep the **eight-tool MCP surface compact**. `local_ai_work` is the deliberate high-level whole-task boundary; do not expose planner/executor internals as additional top-level tools. New lower-level repository capabilities should normally extend existing actions.
- Keep **all waits bounded** — every subprocess, network call and model call must have a finite deadline. No `time.sleep` in hot paths without a bounded loop.
- Preserve **loopback-first security** — the server must bind to 127.0.0.1 by default. Remote exposure is opt-in and requires an API token.
- **Optional external tooling must fail soft** — Serena, CodeGraphContext and Ollama absence, crash or timeout must degrade cleanly to built-in indexes, never block a request handler.
- **One current state contract** — derived SQLite state is disposable and is rebuilt when it does not match the current schema.

## Commit messages

Use the imperative mood, present tense:

```text
Add bounded retry for external MCP responses
Fix SQLite busy handling in semantic cache
Improve hardware detection for AMD GPUs
```

Keep the subject line under 72 characters. Optionally add a body after a blank line for context.

## Pull request checklist

- [ ] python -m compileall -q src tools tests passes
- [ ] python -m pytest -q passes
- [ ] python tools/selftest.py passes
- [ ] python tools/hubctl.py generate passes
- [ ] No new top-level MCP tool schemas added without a documented surface/agent-token justification
- [ ] All subprocess/network calls have timeouts
- [ ] Optional backends degrade gracefully (no hard failures for missing Serena/CodeGraph)
- [ ] Updated CHANGELOG.md with a brief entry if user-visible
- [ ] Maintained/synced agent prompts in `docs/INSTALL_PROMPT.md` and `docs/UPDATE_PROMPT.md` for any policy, tool, or behavior updates

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
