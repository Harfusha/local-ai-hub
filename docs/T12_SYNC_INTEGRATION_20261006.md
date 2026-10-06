# T12 committed synchronization — 2026-10-06

## Scope and preservation

- Sole writable checkout: `C:/Users/Adam/.codex/worktrees/4816/.local-ai-hub`.
- Reused branch: `codex/sync-4816-20261006`. No root/master writes, push, new worktree, stash, reset, or clean.
- Original HEAD: `72ddb03218ccdb6c9bfcc03d5452cb17ffe8dca1`, already the tracked-dirty checkpoint. Preserved in `refs/worktree/checkpoints/t12-original-20261006`.
- Earlier detached HEAD: `933c0129079fcc0c894a71fe842cbbb5e6ad7285`; preserved in `refs/worktree/checkpoints/t12-pre-dirty-20261006`.
- All-work checkpoint: `d52fd5d818f90f47529ad8777730dab7955c2bf7`, `refs/worktree/checkpoints/t12-all-work-20261006`.
- `6ab3f97c` committed 1,264 ordinary untracked source/test/document/handoff files, including unfinished historical overlays and receipts. Historical receipts remain historical evidence.
- Embedded `.handoff/scratch-root-a411` remains intact. Its ordinary source is committed as `.handoff/T12-scratch-source-preserved-20261006.tar` (487 entries), without Git metadata, caches, state, logs, temporary files, or local configuration. The archive includes its dirty `ollama.py`. No unusable gitlink was committed.
- Runtime/cache exclusions are enumerated by actual directory/glob and file count in `T12_SYNC_RUNTIME_EXCLUSIONS_20261006.json`; excluded bytes remain on disk.
- Native fallback was explicitly authorized after the user's reported terminal Hub failure. Failure action/evidence IDs were not provided; no Hub retry or fabricated Hub receipt.
- Token-economizer bounded slices and compact outputs used. Its required `ensure-tools.ps1` was absent at both installed skill locations; no installation or PATH change occurred.

## Reconciliation decisions

- Initial merge target: actual master `ca2f86237b1f8ac9ce4f576a308b65b94a24a69c`, newer than the supplied `fbc965f5`.
- Reviewed 22 conflict files by hunk; no whole-file ours/theirs replacement.
- Preserved master interruptible DNS/TLS/HTTP handling, strict inventory deadline errors, byte/string stream handling, operational-mode admission recheck, conversation reservation/cancellation, and recovered-error telemetry.
- Removed the older duplicated transport helper block introduced by Git's automatic merge; master transport helpers remain once.
- Preserved T12 scheduler cancellation/deadline propagation, quality-floor fallback restriction, strict backend/endpoint inventories, duplicate served-ID unload by exact endpoint, and tiered receipts without physical VRAM claims.
- Prompt-only project settings retain the host model profile. Master deadline regression test and independent T12 scheduler tests both retained.
- T14 `/api/context/pack` was not redesigned. Preprocessor and CodeGraph removal follow committed master; archived historical source is preservation material, not active implementation.
- No dedicated Gemini preprocessing implementation exists in the inspected committed preprocessing source. No provider was invented or configured. Existing Gemini agent integration and master preprocessing are preserved.
- Benchmark reconciliation preserves master lifecycle/worker/HTTP cleanup safeguards and T12 matrix support; exact verification is recorded below when finished.

## Checks and open behavior

- Targeted runtime/routing/cancellation/inventory checks: **138 passed, 2 failed**, 26.62 seconds. Command: `python -B -m pytest -q -p no:cacheprovider --tb=short --basetemp=state/t12-sync-20261006/check1 tests/test_model_routing.py tests/test_router.py tests/test_model_policy_sampling_floor.py tests/test_t12_project_model_consumer.py tests/test_t12_llama_model_inventory.py tests/test_t12_llama_cpp_transport.py tests/test_ollama_gaming_mode.py tests/test_t12_gaming_pause_loaded_rows.py tests/test_tiered_ollama_runtime.py tests/test_t12_scheduler_cancel_result.py tests/test_t12_semantic_quality_contract.py tests/test_t12_generation_boundary.py tests/test_t12_scheduler_scenarios.py tests/test_vram_balancer.py tests/test_t13_gaming_conversation_release_receipt.py`.
- Open: `test_local_task_resolves_project_model_and_prompt_without_cross_repo_cache_or_trace_leak` sees identical coordination namespaces for its two non-Git fixture directories. Preserve current master identity safety; no redesign to satisfy the fixture.
- Open: `test_t12_preempt_hook_obeys_caller_deadline_before_dispatch` detects a caller waiting beyond its deadline. Scheduler source differs from the original tracked checkpoint only by a loop-variable rename; this unresolved behavior was preserved rather than new scheduler development.
- AST parse: 8 merge-touched modules passed; no duplicate top-level llama transport definitions.
- Scoped `git diff --check` passed for reconciled runtime, listed T12 tests, and three policy documents.
- Prompt, token-budget, CodeGraph packaging/removal, and selected runtime-scenario checks: **45 passed, 1 failed**, 8.95 seconds. Command: `python -B -m pytest -q -p no:cacheprovider --tb=short --basetemp=state/t12-sync-20261006/check2 tests/test_prompt_contracts.py tests/test_token_economy_tools.py tests/test_t19_codegraph_removal.py tests/test_codegraph_package_policy.py tests/test_t12_runtime_scenarios.py -k 'not real and not benchmark'`.
- Open: `test_codegraph_is_absent_from_hub_runtime_configuration_and_telemetry` rejects the retained `.codegraphcontext` ignore-directory string in `repo_tools.py`. That file is byte-identical to initial merge master; no CodeGraph runtime/package module was restored. Other removal/packaging checks passed.
- Checks run with bytecode/cache disabled; TEMP/TMP and pytest basetemp confined to this checkout's ignored `state/t12-sync-20261006/`. No full release suite, live inference, model installation, GPU benchmark, deployment, or release acceptance claimed.
- Live latency/VRAM reclamation, integrated/high/max hardware cohorts, and the missing T02 baseline remain unverified. Historical receipts do not resolve those gaps.

## Final identity and inventory

- Initial resolved merge commit: `a3cc6ea13ee478a182eeadc40eba9679d1524cb2`.
- Follow-up merge target: `419474e41a9df79691671189f5c20f613616f511`. Git merged it without conflicts; no further moving-master chase, per explicit user instruction. Central owner performs final fast-forward/integration.
- The follow-up imports current master identity/memory/receipt and T14 response-budget work intact. No T14 endpoint redesign or safety weakening.
- Benchmark source/test AST parse: **2 passed**. Scoped benchmark `git diff --check`: passed.
- Bounded benchmark check after follow-up: **10 passed, 6 failed, 75 deselected**, 5.50 seconds. Command: `python -B -m pytest -q -p no:cacheprovider --tb=short --basetemp=state/t12-sync-20261006/check3 tests/test_surface_benchmarks.py -k 't12 or cleanup or late_worker or wall_timeout or full_matrix' tests/test_context_pack_snippet_budget.py tests/test_t05_memory_fts_atomicity.py`.
- All six failures occur before benchmark execution: `ValueError: state_dir must be outside the repository`. The user restricted writes to this checkout, so pytest temporary directories stayed under its ignored state directory. Master's external-state guard remains intact. Lifecycle/full-matrix integration acceptance is therefore **NOT VERIFIED** under this constrained check. The global `-k` selector deselected the unrelated context/memory tests; no pass is claimed for them.
- Follow-up scoped whitespace check found inherited master EOF blank lines in `tests/test_agent_memory.py:2521` and `tests/test_agent_memory_http_identity.py:958`; no unrelated reformatting.
- Changed paths versus the pinned master are listed in `T12_SYNC_CHANGED_FILES_20261006.txt`. Archived overlays and dated receipts are ordinary preserved handoff material, not current executable/runtime proof.
- Final acceptance for this task is committed preservation and synchronization, not release readiness. Open runtime/test behavior above remains committed and visible.
