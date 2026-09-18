# Testing and release gate

Run `python tools/release_check.py` first on the clean checkout, then `python -m compileall -q src tools tests`, `python -m pytest -q`, and `python tools/selftest.py`. The release check rejects local config, runtime databases, generated/cache payloads and internal workspaces before packaging. Pytest is configured to fail on resource leaks, unraisable exceptions and unhandled thread exceptions. Dashboard JavaScript is extracted and checked with Node when Node is available.

Regression tests cover configuration/hardware profiles, setup behavior, repository filtering, external MCP transport/session lifecycle, preprocessing controls, deterministic/security/import analysis, code-index queries, cache recovery/LRU, semantic-cache vector decoding, command policy, bundles including binary embeddings/integrity/path limits, dashboard DOM/JS and a real HTTP subprocess with authentication/body limits/security headers/binary bundle upload.

CI runs CPython 3.11–3.14 on Windows, macOS and Linux. A release is packaged only after tests and self-test pass from a clean export; the final ZIP should then be extracted and tested again. Physical GPU/driver permutations cannot be executed in one CI host, so hardware detection/profile behavior is simulated in deterministic tests and platform matrix jobs.

## Frontend vision review

The offline end-to-end contract is covered by `tests/test_frontend_review_e2e.py` and the deterministic page in `tests/fixtures/frontend_review/`. Run it without a browser, Ollama, network, credentials, or GPU:

```powershell
python -m pytest -q tests/test_frontend_review_e2e.py
```

The test feeds a mocked screenshot/evidence bundle through the public frontend-review context builders, maps findings to stable DOM IDs, keeps only relevant bounded coder context, repairs a temporary copy of the fixture, then rechecks the repaired state. The fixture intentionally contains a below-fold mobile CTA, low contrast, an unlabeled icon button, one console error, and a fake authenticated marker with no credentials.

For a real local review, use the current-tab bridge only after explicit user capture. Qwen3-VL:4B is selected through the configured Ollama model; the screenshot remains useful without DOM, while DOM/a11y/styles/runtime data improves finding-to-code mapping.
