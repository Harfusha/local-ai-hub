# Local AI Hub 3.0.0 → 4.0.0 migration

This guide describes the planned, reversible migration from the repository's
current `3.0.0` contract to the `4.0.0` contract. The checkout and release
metadata remain `3.0.0` until the 4.0 release is cut; this document is not a
claim that the current installation is already version 4.

## Scope and version transition rules

- Source version before migration: `3.0.0`.
- Target version: `4.0.0` (the release metadata must use the same semver).
- Do not call a 3.0 installation upgraded until package metadata, generated
  artifacts, runtime `/api/status`, and the migration verification checklist
  all report 4.0.
- Never overwrite the only 3.0 state copy. A failed or partial migration must
  be recoverable by restoring the backup and reinstalling 3.0.
- Treat derived indexes, caches, queues, and model downloads as disposable;
  preserve authoritative configuration, Agent OS state, telemetry required by
  retention policy, and any operator-approved evaluation records.
- A 4.0 client must not silently reinterpret a 3.0 response. Use an explicit
  compatibility/degraded result or stop with an actionable error.

## Backup and rollback

1. Stop the Hub and its supervisor. Confirm no model job, command, import, or
   background migration is running.
2. Record the installed package version, active config path, resolved
   `server.state_dir`, enabled features, model aliases, and the output of
   `tools/doctor.py` and `tools/hubctl.py status`.
3. Create a timestamped backup outside the live state directory. Include
   `config.toml`, `defaults.toml` overrides, generated agent artifacts that
   are intentionally managed, and every authoritative database under
   `server.state_dir`.
4. Record file names, byte sizes, and SHA-256 hashes. Do not copy secrets into
   tickets or telemetry; protect the backup with the same access controls as
   the live state.
5. Install 4.0 into a separate environment or staged directory first. Keep
   the 3.0 environment available until post-upgrade verification passes.

Rollback is: stop 4.0, preserve its failure logs and verification evidence,
restore the 3.0 package/config/state backup, restart the 3.0 supervisor, and
rerun the recorded health and smoke checks. Do not delete the failed 4.0 state
before collecting evidence. If a database was changed in place, restore the
whole database backup rather than mixing 3.0 and 4.0 rows.

## State directory and SQLite state

`server.state_dir` is the authority for runtime state. In the current 3.0
contract it contains, among other files, `agent_state.sqlite3`; telemetry,
debug traces, caches, preprocessing artifacts, command state, and other
derived stores may also be present. Resolve the effective path from the
running configuration instead of assuming a default or copying an unrelated
installation directory.

Before first 4.0 start:

- verify the backup manifest and available disk space;
- open/copy databases only while 3.0 is stopped;
- let 4.0 migrate or rebuild one database at a time using its supported schema
  path; never hand-edit SQLite schema in production;
- preserve the original database until integrity and row-level smoke checks
  pass;
- expect disposable indexes/caches to rebuild, but treat loss of task,
  receipt, telemetry, or approved evaluation data as a migration failure;
- check SQLite integrity and confirm no live 3.0 process is writing the same
  state directory.

If the state path is shared by multiple agents or services, migrate it once
under an exclusive maintenance window. Do not run two Hub versions against
the same writable state directory.

## Configuration changes

Start from the 4.0 `defaults.toml`; carry forward only intentional overrides
from the 3.0 `config.toml`. Do not copy a whole generated/default file over the
new defaults. Review at least:

- `[server]` bind, authentication, request/body limits, and `state_dir`;
- `[hardware]`, model tiers, context and concurrency budgets;
- `[scheduler]` and `[commands]` deadlines, coalescing, termination, and
  retry limits;
- `[agent_state]` enablement and retention;
- telemetry/debug-trace retention and privacy limits;
- feature toggles and generated MCP/agent artifacts.

Reject unknown or malformed settings. Regenerate skills, policies, MCP
manifests, and schemas after changing model or feature toggles. Compare the
resolved 3.0 and 4.0 configuration, not only the source TOML, and record each
intentional change. Keep secrets out of the migration record.

## Unified task-context contract

For every non-trivial task, 4.0 clients must obtain and reuse one bounded
task-context pack before planning, editing, review, or testing. The pack must
be associated with an opaque `task_id` and include, when applicable:

`phase`, `focus`, `preload_profile`, `changed_paths`, `base`, `staged`,
`since_hash`, `repo_revision`, `context_id`, `stale`, `evidence_ids`,
`warnings`, `model_warnings`, active checkpoints/leases, acceptance criteria,
and passing verification receipt IDs.

The unified pack combines Agent OS task state, memories/negative knowledge,
leases/checkpoints/receipts, and fresh repository/index evidence. A repo-only
pack is not sufficient when a durable task exists. Preserve evidence IDs and
revision through `local_ai_repo`, `local_ai_task`, command validation, resume,
and completion. Same-revision requests should use a pointer/delta response;
stale or mismatched task context must be rejected or explicitly refreshed.

Migration acceptance requires an end-to-end check that the context endpoint
returns the task's relevant state and that a downstream operation actually
receives the same context identity. A caller that has to manually reconstruct
the pack is not considered migrated.

## Telemetry and schema changes

4.0 telemetry must remain metadata-only: never persist prompts, source text,
model output, secrets, or absolute paths. Preserve privacy-safe aggregates
and make schema/version changes explicit. At minimum, validate continuity for:

- operation/tool/action, intent, outcome, error and retryable state;
- duration, queue wait, service time, p95/p99 cohorts, cache/coalescing;
- raw/projected/saved response estimates, truncation and avoided payload;
- input, cached-input, output, reasoning-output and token-budget fields when
  available from the provider;
- task/cohort IDs for paired quality and latency evaluation, without prompts.

Export or snapshot 3.0 telemetry before migration if it is operationally
needed. Do not assume cached input means no cost or no context duplication.
Verify that old rows are either migrated by a documented schema path or
retained as read-only historical data. Check both process-scoped post-upgrade
telemetry and the rolling window; a green health endpoint alone is not proof.

## Agent OS tasks and receipts

Before cutover, list active tasks, leases, checkpoints, incidents, memories,
negative knowledge, and verification receipts. Close or explicitly carry
forward stale/planned tasks; do not silently discard them. Export only approved
records and preserve their scopes.

For each migrated task, verify:

- the task contract and acceptance criteria survive;
- `task_id`, owner, phase, next action, affected paths, and evidence IDs are
  stable or have a documented mapping;
- passing receipts retain criterion, command/evidence ID, revision, and
  observed time;
- `verify_completion` still refuses completion when a required criterion lacks
  a passing receipt;
- disabled Agent OS remains an intentional stateless mode rather than a
  silent data-loss fallback.

Do not mark the migration task complete until the post-upgrade receipts pass.

## Model quality registry

4.0 model changes require a versioned quality registry. Each candidate records
an opaque candidate ID, model/route, prompt or evaluation-suite version,
hardware profile, latency budget, evaluation cohort, quality result, test
result, and approval state. Do not store prompts or source payloads in the
registry.

Use states `candidate`, `champion`, and `rejected`. Promotion requires a
reproducible evaluation receipt and a quality floor covering grounded
relevance, schema adherence, abstention on missing evidence, hallucinated
paths/identifiers, valid/invalid input discrimination, latency, and resource
pressure. A generic or irrelevant local-model answer is a failed evaluation,
not evidence for promotion. Keep the 3.0 champion available until 4.0 has a
paired no-regression result; bypass or degrade to deterministic evidence when
the quality gate fails.

## Command transport compatibility

Preserve the existing bounded command contract during rollout. Classify or
discover unfamiliar commands before execution; keep policy rejection terminal.
Carry the same logical request ID on the single permitted transport retry,
honor `retry_after_seconds`, and reuse `cache_hit`/`coalesced` results instead
of submitting duplicates. Respect caller and server timeout ceilings, bounded
stdout/stderr capture, cancellation, and process-tree cleanup.

Test both MCP and HTTP callers, including PowerShell/Windows argument
serialization, nested repository roots, Unicode paths, empty output, non-zero
exit, timeout, retryable overload, duplicate request ID, and stale task
context. A command broker success is not a project-test success; retain the
actual test receipt.

## Staged rollout

1. **Offline rehearsal:** restore a copy of 3.0 state, run the migration in an
   isolated 4.0 environment, and compare manifests, schemas, context packs,
   and receipts.
2. **Canary:** route one low-risk agent/root or a hub-off comparison cohort to
   4.0. Keep 3.0 available and cap model, command, queue, context, and token
   budgets.
3. **Observe:** require healthy startup, no privacy violations, bounded queue
   age, no retry storm, context continuity, passing focused tests, quality
   floor, and no material p95/p99 regression.
4. **Expand:** increase scope in explicit steps, recording cohort, revision,
   operator, and receipts at each checkpoint.
5. **Finalize:** switch the default only after all acceptance criteria pass and
   the rollback window is documented. Retain the signed backup and manifest
   for the agreed retention period.

Stop and roll back on state corruption, missing receipts/tasks, context
  mismatch, privacy failure, invalid model output, transport retry storm,
  unbounded queue growth, or a material quality/latency regression.

## Post-upgrade verification

Run and retain bounded evidence for:

- package/release metadata and generated artifact version `4.0.0`;
- `tools/doctor.py`, `tools/hubctl.py status`, `/health`, capabilities, and
  authenticated status/telemetry endpoints;
- SQLite integrity and state-directory manifest comparison;
- task-context compile plus downstream propagation with a real task ID;
- Agent OS task, checkpoint, receipt, resume, and completion gates;
- telemetry schema, privacy fields, process cohort, cache/delta accounting;
- model registry evaluation, rejected-output handling, and champion fallback;
- MCP/HTTP command transport compatibility and one bounded failure path;
- focused project tests, release checks, and clean shutdown/restart.

Record command IDs, evidence IDs, revisions, receipt IDs, warnings, and exact
versions. Do not claim migration success from source presence, a green liveness
endpoint, or a Hub operation alone. If any required evidence is missing, keep
the rollout in canary/blocked state and retain the 3.0 rollback path.

## Concerns and explicit non-claims

This guide is a migration contract and operator runbook, not a promise that
every 4.0 implementation detail already exists in the current 3.0 checkout.
The current metadata still declares `3.0.0`; model quality promotion,
unified context propagation, schema migration, and rollout gates must be
verified against the released 4.0 implementation before production use.
