# Changelog

## 4.0.0 — 2026-09-21

- Unified task context joins Agent OS state, repository evidence, revisions, freshness and bounded deltas.
- Deterministic quality gates keep local-model output advisory and reject irrelevant, queued, malformed or unverified claims.
- Added shell-safe command transport, review queue SLA, root-family budgets, context reuse and receipt-gated completion.
- Added the 3.0 → 4.0 migration contract and rollback checklist.

## Unreleased

- Register the managed Python package so global CLI commands work outside the checkout.
- Resolve Windows batch executables during setup and preserve user logon startup when Task Scheduler denies registration.
- Initialize tokenizers only when counting tokens, keeping CLI help and unrelated tools offline.
- Recognize generic AMD Radeon Graphics adapters as integrated GPUs.
- Enforce Windows Job Object memory and CPU limits with pointer-sized handles.
- Reject AST outline paths outside the project, including resolved symlink escapes.
- Evaluate benchmark cases against actual model responses instead of reporting unconditional passes.
- Remove shadowed duplicate definitions, unused code and unresolved type annotations flagged by CI.

## 3.0.0 — 2026-09-08

- One application release contract: Local AI Hub 3.0.0.
- One unversioned internal HTTP namespace under `/api/`; no parallel endpoint aliases.
- Package-native eight-tool MCP server is the only MCP entrypoint.
- Derived Agent OS and telemetry databases use one current schema; non-matching derived state is rebuilt rather than transformed.
- Embedding and reranker caches use one device-qualified key identity and one namespace each.
- End-to-end token accounting uses signed `net_cloud_token_delta_est` as the canonical cloud-efficiency metric, with protocol cost, schema exposure and local-compute reuse reported separately.
- Dashboard HTML owns static labels and layout; JavaScript populates runtime values and state only.
- Historical planning/specification artifacts are not part of the release tree.
