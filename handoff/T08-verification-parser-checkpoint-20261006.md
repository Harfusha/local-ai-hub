# T08 receipt parser and checkpoint error handoff — 2026-10-06

## Scope and synchronization

Assigned checkout: C:/Users/Adam/.codex/worktrees/t13-lifecycle-8429/.local-ai-hub.
Branch: codex/sync-t13-lifecycle-8429-20261006.
Entry HEAD: a1082ceb530b98f9c69ff8027356fb236852ab4a; checkout was clean.
Merged f140b96c4d3a451651436136405de7a931faf533 without reset; merge HEAD 06d2c08c6490ef1411780f3b3dc8beba3dd7ad83.
User corrected the pin before edits to 7729c814bc00343e0e414fee0582c928ddaabb9c; merged it without conflicts; source-work base 912be2e698448f042d72d545ceee447c181491c8.
Git merge commands used -c core.hooksPath=NUL; no hooks or release suite ran. Root checkout/master ref were not written.
Existing T13 audit documents match their previous committed contents. No dirty work discarded; no stash operation.

## Changes

- V04-H018/H020/H021 + V10-H003: VerificationReceipt.from_dict rejects missing/non-exact-bool passed before construction. Explicit mutation_generation must be an int excluding bool and non-negative; absent defaults to zero. No int/falsy coercion. Details may be absent (empty mapping default) or Mapping; explicit null/scalars/arrays rejected with ValueError. Mapping contents are copied into a dict.
- V04-H041: record_change tolerates only KeyError around task generation/checkpoint handling. OSError, ValueError and ConcurrentTaskUpdateError propagate instead of disappearing. Existing change event/projection transaction and collision checks remain untouched.
- Targeted parametrized JSON regressions, optional defaults, Mapping-copy behavior, pre-construction rejection, checkpoint errors/disappearing task, and atomic change collision/generation coverage. Existing parser-only test now expects rejection instead of conversion to False.

No edits to TaskStore, agent_memory.py, http_server.py, async_jobs.py or work orchestrator. H036 remains Russell's ownership. No new generation helper, blocker-preservation redesign, checkpoint ordering change or retry redesign.

## TDD evidence

Terminal Hub failure/native-fallback authority from the existing handoff was reused; no Hub retry/poll or model call. token-economizer and TDD governed narrow reads, surgical edits and observed RED before production code. Missing ensure-tools.ps1 caused no installation/PATH changes.

PowerShell setup for each test run: $env:PYTHONDONTWRITEBYTECODE = '1'. Temporary SQLite/test artifacts are confined to ignored .sync-validation-t08-receipt-* directories in this checkout and remain uncommitted; no deletion.

RED, before source edits:

    python -B -m pytest -q --tb=short -p no:cacheprovider --basetemp=.sync-validation-t08-receipt-red tests/test_agent_verification_input_safety.py

Exit 1: 33 failed, 17 passed in 1.94s. Failures show accepted malformed parser values, invalid input reaching construction, and swallowed checkpoint errors. No collection failure.

GREEN, after minimal source edits:

    python -B -m pytest -q --tb=short -p no:cacheprovider --basetemp=.sync-validation-t08-receipt-green tests/test_agent_verification_input_safety.py

Exit 0: 50 passed in 0.72s.

Final targeted existing/new regressions:

    python -B -m pytest -q --tb=short -p no:cacheprovider --basetemp=.sync-validation-t08-receipt-final tests/test_agent_verification_input_safety.py tests/test_agent_verification.py::test_verification_receipt_parser_requires_explicit_boolean_passed "tests/test_agent_verification.py::test_verifier_projection_rolls_back_when_event_projection_write_fails[change]" tests/test_agent_verification.py::test_recorded_change_advances_generation_and_invalidates_existing_receipt

Exit 0: 57 passed in 1.38s. Includes rollback on rejected event/projection write and stale-generation receipt invalidation.

Standard-library AST comparison against pinned source: only VerificationReceipt.from_dict and VerificationStore.record_change changed. All other function ASTs unchanged, explicitly including __post_init__, create and record_change._do_save. git diff --check passed.

## Integration limits

Unexpected task checkpoint failure now reaches the caller AFTER the existing durable change event/projection has committed. Tests assert this existing ordering; no promise of a combined change/checkpoint transaction or retry-idempotent generation advancement. Missing-task KeyError remains tolerated. H036 and unrelated stash/integration obligations remain unfinished and out of scope.

No full suite, live service, models or release acceptance. Commit SHA and final clean/ancestor checks are reported in chat; this note cannot include its own containing commit SHA.
