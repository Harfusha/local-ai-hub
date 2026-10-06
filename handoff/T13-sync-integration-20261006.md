# T13 checkout reconciliation — 2026-10-06

## Scope and fixed references

- Assigned checkout: `C:/Users/Adam/.codex/worktrees/t13-operational-mode/.local-ai-hub` only.
- Ready merge branch: `codex/sync-t13-operational-mode-20261006`.
- Pinned start master: `ca2f86237b1f8ac9ce4f576a308b65b94a24a69c`; later shared-master movement is deliberately ignored.
- Original existing dirty checkpoint: `af119626136735d3da847247916d4e4c01e670ed`, retained unchanged at `codex/checkpoint-t13-operational-mode-dirty-20261006` and `codex/checkpoint-t13-operational-mode-original-head-20261006`.
- Original pre-checkpoint parent: `6050c41ce5510a6de3eaeb674a180560ea404f24` remains reachable through those references.
- Complete source/test/doc/handoff checkpoint: `4aa2edef`, retained at `codex/checkpoint-t13-operational-mode-all-source-20261006` (1,363 formerly untracked files).
- Pin also retained at `codex/checkpoint-t13-operational-mode-pinned-master-20261006`.
- No shared master/root checkout writes, push, stash, reset, clean, new worktree or new chat.

## Conflict decisions

Conflicting implementations were reviewed by hunk and behavior. The pinned master implementation is authoritative where the old T13 candidate and master implement incompatible protocols. Materialization uses coherent file context after review, rather than combining incompatible function signatures, snapshot formats and helper ownership. Exact paths, hunk counts, hashes and reasons are in `T13-sync-conflict-decisions-20261006.json`.

Master retains per-action inference admission, caller/generated request-ID provenance, delayed dispatch cancellation, audited action authorization, bounded request validation, recovery journaling, optional debug persistence, model lifecycle ownership, interruptible unload deadlines, timestamped cross-process mode persistence, project routing and Whisper JSON validation. Gemini setup/preprocessing changes and removal of managed CodeGraph remain. The standalone `.codegraphcontext` scan exclusion remains for safety. HTTP context-pack behavior is exactly the pinned master implementation; T14 is not redesigned.

Non-conflicting T13 source and tests remain merged. Old incompatible candidate implementations and assertions are not erased: all are committed in `4aa2edef`, including handoff source copies and patches. They are historical evidence, not current runtime acceptance.

Three reviewed T13 safety hunks remain on top of the coherent master async manager: submission acquires the existing mode-transition lock before the manager lock; cancellation verifies the tenant-owned nonterminal row in a SQLite write transaction before removing its timer; shutdown includes resource-release workers in its existing bounded join and clears release waiters. Master response schemas, per-action admission and caller-provenance rules remain intact. These are reconciliation of existing behavior, not new features.

## Runtime/artifact exclusion manifest

All exclusions stay on disk; no deletion. Pre-merge ignored inventory:

- 829 bytecode files (`__pycache__`, `*.py[cod]`).
- Five pytest cache files.
- Three ignored logs.
- Five Serena files: `.serena/.gitignore`, `.serena/cache/python/document_symbols.pkl`, `.serena/cache/python/raw_document_symbols.pkl`, `.serena/project.local.yml`, `.serena/project.yml`.
- Two pre-existing nested checkout artifacts are preserved outside staging: `handoff/T13-root-current-scratch-20261002/apply-check/` and `handoff/T13-root-current-scratch-20261002/apply-check-no-migration/`.
- New targeted-check temporary state/logs, if produced, belong only inside this checkout under `.t13-sync-validation/` and are excluded from commits.
- Runtime state, caches, generated local configuration, database files and user configuration are excluded by repository policy.

## Outstanding behavior and validation

This is a committed reconciliation, not a feature-completion or release claim. Older T13 candidate assertions may target the superseded mode schema, `/api/mode` mutation instead of `/api/admin/mode`, `resources` result nesting, accelerator release helpers or timeout-only unload signatures. Such unfinished source/tests/docs are committed and explicitly retained; no new feature work is undertaken to make historical expectations pass.

Pinned-master known inconsistency from source review: `test_codegraph_is_absent_from_hub_runtime_configuration_and_telemetry` forbids every `codegraph` substring, while master deliberately preserves `.codegraphcontext` in scan exclusions. Do not remove the scan exclusion to satisfy that assertion.

Hub terminal failure and native fallback authorization were supplied by the user; no Hub retry or polling. The requested token-economizer `ensure-tools.ps1` is missing at its specified path; the attempted `-PlanOnly` invocation failed without installation or PATH changes. Token-economizer guided bounded reads and focused validation.

Fresh checks and final changed-path inventory are recorded below before committed handoff. No full release suite, real Gemini/Ollama/Whisper run, deployment, physical GPU unload proof or live installed-service validation is claimed.

## Fresh receipts

1. Native focused master checks, `python -B -m pytest -q --tb=short -p no:cacheprovider --basetemp=.t13-sync-validation/master-tests`: `test_operational_mode.py`, `test_preprocess_operational_mode.py`, `test_async_jobs.py`, `test_async_job_reliability_contract.py`, `test_whisper_cancellation.py`, the Gemini setup selector, the no-CodeGraph preprocessing selector, the quoted Unicode diagnostics selector, and `test_t19_codegraph_removal.py`. Result: **76 passed, 1 failed, 15.06 seconds**. Sole failure is the known master substring assertion on `.codegraphcontext`; safety exclusion retained.
2. Native retained-T13 checks, `python -B -m pytest -q --tb=line -p no:cacheprovider --basetemp=.t13-sync-validation/t13-tests`: `test_t13_sync_cancellation.py`, `test_async_operational_mode.py`, `test_t13_inference_start_gate.py`, `test_t13_cancellation_seams.py`, `test_t13_hubctl_offline_persistence.py`, `test_hubctl_operational_mode.py`, `test_operational_mode_http.py`, `test_t13_mode_resume_matrix.py`. Result: **28 passed, 36 failed, 8.86 seconds**; command exit 1. `PYTHONDONTWRITEBYTECODE=1`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `TEMP` and `TMP` set to this checkout's `.t13-sync-validation`. Foreign-tenant cancellation regression passed. No identical test command repeated.
3. `python -B handoff/t13_verify_sync.py`: **118 Python files compiled in memory, zero syntax errors; zero unresolved index entries; source/test/tool whitespace check passed**. No build or compileall and no generated bytecode from this syntax check.
4. Protected files compare exactly with pinned master: HTTP server (including T14 context pack), preprocessing, MCP server, operational-mode module, client, repository scanner, setup/uninstall and canonical install/update prompts. No Gemini/CodeGraph safety regressions introduced in these files. This proves source equality, not runtime acceptance.

Retained-T13 failure detail: one preprocessing test constructs a preprocessor without `state_dir`; eight CLI cases expect old JSON output, offline success or `/api/mode` mutation; remaining 27 HTTP cases expect old authentication/gating statuses, mode endpoints, `resources` nesting or `_empty_torch_cuda_cache`. One mocked transcription thread also reports cancellation timeout and a late `APP.logger` access after fixture teardown. These test/contract gaps are unfinished and remain committed, without suppressing failures or expanding feature work.

Aggregate focused results: **104 passed, 37 failed**. Release acceptance is **NOT VERIFIED**. Historical receipts are not reused as fresh proof.

Changed files versus pinned master: **1,372**, fully listed in `T13-sync-changed-files-20261006.json`. Runtime source changes are confined to `src/local_ai_hub/async_jobs.py` (three retained safety hunks) and `src/local_ai_hub/commands.py` (existing candidate fail-closed repair guard). Remaining changes are tests, source-history handoffs, one plan document and the validation-directory ignore file. Handoff source copies are committed preservation material, not imported runtime modules.
