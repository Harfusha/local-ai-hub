# Changelog

## 3.0.0 — 2026-09-08

- One application release contract: Local AI Hub 3.0.0.
- One unversioned internal HTTP namespace under `/api/`; no parallel endpoint aliases.
- Package-native eight-tool MCP server is the only MCP entrypoint.
- Derived Agent OS and telemetry databases use one current schema; non-matching derived state is rebuilt rather than transformed.
- Embedding and reranker caches use one device-qualified key identity and one namespace each.
- End-to-end token accounting uses signed `net_cloud_token_delta_est` as the canonical cloud-efficiency metric, with protocol cost, schema exposure and local-compute reuse reported separately.
- Dashboard HTML owns static labels and layout; JavaScript populates runtime values and state only.
- Historical planning/specification artifacts are not part of the release tree.
