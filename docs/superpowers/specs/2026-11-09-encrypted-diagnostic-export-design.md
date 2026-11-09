# Full Local AI Hub support ZIP

## Intent

Move a useful Local AI Hub support snapshot from a work notebook to a PC for offline diagnosis, tuning, and repair.

## Scope

- One installation-wide export for retained state across all projects; no project selector or root filter.
- Include all Hub-owned operational SQLite databases under the configured state directory using SQLite backup snapshots: telemetry, endpoint statistics, detailed traces, Agent OS task/memory/incident stores, and project indexing/retrieval state when present.
- Include all current and rotated Hub operational logs under the state directory.
- Include active effective Hub configuration in structured form with secret values redacted; include OS, Python, installed component/version, model inventory, and runtime summaries.
- Include the Hub's own source snapshot (source package, tests, tools, docs, prompts, and build/dependency manifests) when a source checkout is available; otherwise include installed Hub package source. Include no other project source.
- Keep request/response payloads subject to existing detailed trace opt-in and retention.
- Exclude model weights, opaque model downloads, environment-variable values, and private-key files. Redact secret-shaped values from the effective configuration. Logs, databases, and traces are complete operational records and may still contain credential-shaped or other private content; warn users to treat the encrypted archive as sensitive.
- Build encrypted ZIP in a temporary file and stream it to the client; do not hold the whole archive or members in RAM. Use ZIP64. Remove temporary files on success, failure, or disconnect.
- Replace the old small limit with a generous configurable limit, default 8 GiB compressed and 64 GiB source. Fail closed with clear size/disk-space errors; never send a partial archive.
- Use AES-256 and BZIP2 level 9. Generate a fresh password, return only with successful download, and never persist it.
- Keep existing project bundle import/export unchanged.

## Acceptance

- All-project manifest lists included/excluded categories, counts, bytes, versions, and redaction status.
- Files and archives beyond 4 GiB work with streamed file I/O.
- Config secrets are redacted; non-secret settings remain usable.
- Telemetry, traces, statistics, Hub operational databases/logs, and Hub source material are included; project source and model weights are excluded.
- Focused tests cover ZIP64/streaming behavior, encryption, redaction, cancellation/cleanup, disk and configured-size limits.
- Dashboard warns that traces, paths, tasks, and memories may contain private content.
- Existing project bundle export remains unchanged.

## Tracking note

User confirmed the scope. `plan_reconcile_steering` could not update this spec because the associated Agent OS task has no bound session; the existing plan task was reopened through `plan_task_edit`.
