# T15 manual synchronization — committed preservation, not acceptance

Date: 2026-10-06. Only checkout: C:/Users/Adam/.codex/worktrees/t15-command-config/.local-ai-hub.
Branch: codex/sync-t15-command-config-20261006.
Incoming master pinned once: f57947215fd48c37f14a7325b4651be836de553f.
No moving master/ref lookup was used as the merge target.
Original HEAD / existing tracked-dirty checkpoint: 997a89a7be26b22a2f9389df29abfa5664165d8d.
Original HEAD ref: codex/checkpoint-t15-command-config-original-head-20261006.
Existing dirty ref: codex/checkpoint-t15-command-config-dirty-20261006.
All-source premerge commit: 388086357ab954fbf208def00ba1ce5a60170598.
All-source ref: codex/checkpoint-t15-command-config-all-source-20261006.
Pinned-master ref: codex/checkpoint-t15-command-config-pinned-master-20261006.

## Preservation and scope

Actual initial ordinary untracked inventory: 65 files, not 17.
Checkpointed 44 original files: 11 Python code/test files and 33 handoff documents, patches and source manifests.
The other 21 JSON historical runtime/benchmark receipts remain untracked, preserved in place; inventory below.
All eight original tracked-dirty files already exist in 997a89a7.
Historical handoff documents/patches/manifests are archived evidence, not current instructions or acceptance proof.
Runtime test state is excluded under state/t15-sync-checks; no cache/runtime state was staged.
No stash, drop, hard reset, clean, push, worktree creation, root checkout edits or master ref writes.
User-authorized native fallback followed the already reported terminal Hub failure; Hub was not retried or polled.
token-economizer bounded reads, surgical patches and compact validation were used.
Its ensure-tools.ps1 -PlanOnly entrypoint was missing; no tooling installation or PATH change occurred.
Native read-only delegation was attempted once, rejected by the agent thread limit; no subagent ran.

## Manual conflict decisions

Reviewed 11 conflicted files by hunks; no whole-file ours/theirs checkout.
commands.py: incoming stable process-tree ownership, fail-closed recovery, tenant/timeout cache identity, private mutation transactions,
bounded output capture, project context/state identity, current environment validation and trusted project verification provenance prevail.
Old numeric PID/PGID signaling, old unpartitioned caches and obsolete daemon tests were superseded by current master behavior.
project_config.py: preserve bounded descriptor reads, containment checks, current namespace/path-hint policy and verification normalization.
services.py merged cleanly; current command consumer and verification wiring retained.
docs/PROJECT_CONFIGURATION.md: remove obsolete proposed-bridge paragraph; retain master integrated completion contract.
tests/test_project_config.py: union the three original overlay/containment regressions with master's size-limit regression.
tests/test_command_cache_singleflight_contract.py: retain one copy of duplicate tests and update two _key stubs for current keyword arguments.
tests/test_project_command_broker.py: expected cache keys retain current tenant and timeout fields; _attempt_key receives required fields.
Mock recorder test keeps master's task authorization and http_probe test boundary; remove stale mock_request assertion.
Benchmark: retain T15 v3 mandatory commands.py SHA pin before API load and preflight measurement;
also retain master's separate concurrency-state broker and cold cache-seed regression.
All active src/ and mcp/ runtime files compare equal to pinned master after resolution.
Preprocess, configuration/dependencies, install/update prompts and /api/context/pack were not redesigned;
the pinned master's Gemini preprocessing and CodeGraph removal are retained unchanged.

## Actual validation and outstanding issues

Checks ran natively in the assigned checkout with PYTHONDONTWRITEBYTECODE=1, TEMP/TMP under state/t15-sync-checks/temp,
pytest -q --tb=short -p no:cacheprovider, and distinct basetemp paths under state/t15-sync-checks.
No full release suite, install, build, benchmark performance run or deployment.

First targeted batch:
tests/test_project_config.py, tests/test_project_command_broker.py,
tests/test_command_cache_singleflight_contract.py, tests/test_benchmark_command_broker.py,
-k "not synthetic_repository_fixture and not preflight_fixture".
Result: 118 passed, 3 failed, 2 deselected, 1 teardown error (26.01s).
The failures were outdated tenant/timeout expectations and _key stubs; these test compatibility defects were corrected.

Second targeted batch:
three initially failing cache tests, three original config regressions,
tenant/timeout cache partition, overlapping calls, uncertain-result cache exclusion,
tests/test_project_config_service_integration.py filtered with -k "not repo_search and not search_paths".
Result: 11 passed, 3 failed, 13 deselected (3.79s). All three initially failing tests now pass.
Open: test_overlapping_repeatable_calls_execute_once_and_return_same_result expects waiter cache_hit=False; observed True.
Open: test_run_affected_applies_project_mapping_and_path_hints_safely lacks affected_tests_summary.
Open: test_run_affected_fails_closed_when_uncertain_and_test_matrix_missing lacks selection_uncertain.
Both failing test modules and the entire active runtime are source-identical to pinned master.
That is source parity, not a separately executed master baseline or a root-cause diagnosis; no safety behavior was weakened to pass tests.
Remaining restored paired/root-parity harnesses were only syntax checked; old pins/receipts do not certify this merged checkout.
The synthetic repository fixture and real preflight benchmark tests were deliberately deselected.
No live Gemini/model inference, daemon recovery, browser/API deployment, performance or full-release acceptance was established.

AST parsing of 13 restored/touched Python files passed, without bytecode writes.
Working-tree git diff --check passed after merge cleanup.
The staged comparison includes archived patch text with historical trailing whitespace; those original artifacts were preserved verbatim.
The broad staged comparison against old HEAD also reports incoming master's historical snapshot whitespace; no unrelated cleanup was made.
Active source/test/tool/document changes are checked separately against pinned master.
Merge target is the pinned SHA; final ancestry, unresolved-index and tracked-clean checks accompany the committed handoff.

## Files changed versus pinned master (before this integration note)

- handoff/T15-benchmark-runner-v2-owner-patch-20261002.patch
- handoff/T15-pinned-source-manifest-20261002.json
- handoff/t15-acceptance.manifest.json
- handoff/t15-acceptance.patch
- handoff/t15-benchmark-runbook.md
- handoff/t15-command-broker-benchmark-runbook.md
- handoff/t15-command-receipt-opt-out-design.md
- handoff/t15-config-read-hardening.patch
- handoff/t15-env-cache-invalidation-v6.patch
- handoff/t15-execute-compat-followup.manifest.json
- handoff/t15-execute-compat-followup.patch
- handoff/t15-merge-ready-handoff.md
- handoff/t15-owner-hunk-map.md
- handoff/t15-process-group-recovery-approval.md
- handoff/t15-process-group-recovery-review-receipt-20261002.md
- handoff/t15-project-command-alias.manifest.json
- handoff/t15-project-command-alias.patch
- handoff/t15-root-cache-bypass-guards.patch
- handoff/t15-root-cache-env-runtime-v3.patch
- handoff/t15-root-cache-ttl-env-v1.patch
- handoff/t15-root-cache-ttl-env-v2.patch
- handoff/t15-root-cache-ttl-env-v4.patch
- handoff/t15-root-cache-ttl-zero-v5.patch
- handoff/t15-root-compatible-handoff.md
- handoff/t15-root-compatible.patch
- handoff/t15-root-current-cache-only-v1.patch
- handoff/t15-root-current-cache-only-v2.patch
- handoff/t15-root-current-paired-benchmark-acceptance-checklist-20261002.md
- handoff/t15-root-current-parity-tests.patch
- handoff/t15-source-pin-slot-audit-20261002.md
- handoff/t15-stream-preflight.patch
- handoff/t21-command-consumer.manifest.json
- handoff/t21-command-consumer.patch
- tests/test_benchmark_command_broker.py
- tests/test_command_cache_singleflight_contract.py
- tests/test_project_command_broker.py
- tests/test_project_config.py
- tests/test_t15_paired_benchmark_contract.py
- tests/test_t15_root_parity_acceptance.py
- tools/benchmark_command_broker.py
- tools/prepare_command_broker_fixtures.py
- tools/t15_config_parity_microbench.py
- tools/t15_paired_benchmark.py
- tools/t15_root_cache_isolated_acceptance_v1.py

## Original untracked runtime receipts preserved on disk

- handoff/t15-acceptance-evidence.json
- handoff/t15-benchmark-pin-preflight.json
- handoff/t15-cache-config-invalidation-receipt.json
- handoff/t15-command-broker-baseline.json
- handoff/t15-command-broker-candidate.json
- handoff/t15-config-parity-microbench-slot-v1.json
- handoff/t15-config-parity-microbench.json
- handoff/t15-consumer-behavior-receipt.json
- handoff/t15-correctness-slot08-receipt-20261002.json
- handoff/t15-env-cache-invalidation-v6.json
- handoff/t15-paired-harness-synthetic-v1.json
- handoff/t15-paired-harness-synthetic-v2.json
- handoff/t15-paired-harness-synthetic-v3.json
- handoff/t15-root-cache-env-runtime-v3.json
- handoff/t15-root-cache-ttl-env-v1.json
- handoff/t15-root-cache-ttl-env-v2.json
- handoff/t15-root-cache-ttl-env-v4-head-correction.json
- handoff/t15-root-cache-ttl-env-v4.json
- handoff/t15-root-cache-ttl-zero-v5.json
- handoff/t15-root-current-cache-only-v2.json
- handoff/t15-root-current-parity-receipt.json
