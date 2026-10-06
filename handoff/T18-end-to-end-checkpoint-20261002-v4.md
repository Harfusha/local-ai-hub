# T18 end-to-end checkpoint — 2026-10-02 v4

## Current goal state

Goal remains active in the original T18 worktree. Candidate HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`; source pins still match previous receipts. Mixed dirty files from other owners are unchanged. No `/api/context/pack`, prompt/broker, root, or source changes made in this turn. Local AI Hub unused.

## Root-mode correction

Root `http_server.py` still lacks candidate-only helper `_operational_mode_api`, but root production routes are present: loopback-only unauthenticated GET exception in `_require_authorized`, `GET /api/mode` snapshot handler, and `POST /api/admin/mode` handler. Root SHA-256 `8443F8E178C717C92C063394C585C8C38721BD18F644DB053DB6EF81A5F0E047` at HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`.

The earlier 22 failures running candidate `tests/test_http_operational_mode_t18.py` against root come from a stale test injection seam; they do not prove missing root mode code. Detailed route and selector review: `handoff/T18-root-mode-route-review-20261002-v1.md`, SHA-256 `767E7D39EC3AD3B709BC524DFB2C9C201AFA2DB81DBCD16BD772EB04F11F6C6D`. This supersedes earlier T13-source-missing wording. T13's latest completed work was unrelated async-job handling.

Remaining root-current mode evidence: run actual loopback GET versus remote 401 with current root code; candidate root overlay currently stubs authorization. Root action-token and mode update selectors already exist. T20 still owns overall release acceptance.

## Test-slot gate

T02 thread `01a0d30b-ffee-7fa2-bc6e-f503a4bc18b7` remains active on its baseline worker. A 30-second wait observed it still active, no stdout/stderr and no release. No tests or benchmarks ran this turn.

Existing focused receipts remain candidate `42 passed` and root `48 passed`; neither is full release acceptance. Next: after explicit T02 release, pin current root source and run only the root-mode auth regression plus relevant candidate selectors; hand exact results to T20.
