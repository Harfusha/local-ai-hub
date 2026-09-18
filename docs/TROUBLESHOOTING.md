# Troubleshooting

## Hub will not start
Run `local-ai-hub --version`, then `python tools/doctor.py`. Invalid TOML now fails fast; fix the reported file/key instead of deleting state blindly. Check that the configured port is free.

## Serena/CodeGraph unavailable
Check the code-intelligence status in the dashboard, rediscover executables, then reset sessions. Setup can reinstall isolated tool environments. Deterministic/code-index/search operations should continue while these backends are degraded.

## Context references a deleted temp repository
Use a stable project root. The API returns a structured stale/degraded result rather than crashing; callers should discard the obsolete root.

## Commands are blocked
Use `local_ai_command(action="classify")`. Unknown, mutating, install/deploy/publish/clean and unsafe formatter commands are denied by default. Run intentional mutation directly under user control rather than weakening the hub policy.

## Dashboard authentication
Set the API token in the dashboard toolbar for the current browser session. The token is not placed in the URL.
# Frontend vision review

## Offline fixture test fails

Run `python -m pytest -q tests/test_frontend_review_e2e.py`. It is deliberately independent of Ollama, a GPU, a browser, login state, and network access. If it fails after changing the fixture, preserve the stable `data-testid` hooks and the `element_id` mapping used by the test; do not replace it with a live-browser smoke test.

## Local model unavailable

The offline contract still runs without Ollama. For a live review, start Ollama and ensure the configured `qwen3-vl:4b` model is available. A missing model should be reported as a bounded capability/dependency failure, not silently replaced with a cloud call.

## Current-tab capture errors

Capture is explicit and current-tab bound. Keep the target tab open and on the expected origin, grant only the requested local extension permission, and retry from that tab. The bridge must not navigate, submit forms, perform login, collect cookies, or capture network request bodies. A timeout, navigation race, closed tab, or origin mismatch is expected to fail closed.

## Findings do not map to source

Check that the bundle contains `redaction: "none"`, unique stable DOM `element_id` values, accessibility/computed-style evidence, and bounded runtime references. The coder packet intentionally contains the relevant DOM elements plus their ancestors and only the repository files selected by the repository context step; oversized or malformed context must be fixed at the producer.
