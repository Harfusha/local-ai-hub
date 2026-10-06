# T19 O4 CLI Partial-Cleanup Projection — 2026-10-01

## Ownership and boundaries

Explicit O4 assignment: T19 owns only `tools/hubctl.py` mode-change CLI projection for `runtime_unload`, `accelerator_release`, and `job_cancellation`, including summary and exit result, plus partial-cleanup regressions in `tests/test_hubctl_mode.py`. T18 owns dashboard display only. T13 owns mode persistence/transition; no backend change is in this O4 patch. T20 owns root integration and the post-patch test slot.

Root `HEAD` observed during patch preparation: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. Root `tools/hubctl.py` has inherited dirty CLI/config/offline changes; root `tests/test_hubctl_mode.py` exists untracked. Patch was generated from those current root working files and changes only the two assigned paths. No root files were written.

## Patch

Path: `handoff/T19-O4-cli-partial-cleanup.patch`  
SHA-256: `10094346520185d56945e2937c8b00b69691ac4cc36dc1636d1a306a6ed81260`

Patch adds `_activity_mode_transition_failures` and changes only `main`'s mode-change result projection. A persisted mode with incomplete cleanup prints `Mode persisted as ...`, lists failed cleanup operations on stderr, and returns `1`; complete transitions keep existing success output and return `0`. Gaming requires successful runtime unload and accelerator release. Gaming/maintenance report a present failed `job_cancellation` outcome. Backend source emits `job_cancellation` on failure only; it emits both gaming cleanup result objects.

Regression changes update the existing runtime-unload failure case to expect nonzero partial status, then cover accelerator-release failure, gaming/maintenance job-cancellation failure, and absence of the all-clear message.

## Validation and handoff

Exact read-only root check: `git -C 'C:\Users\Adam\.local-ai-hub' apply --check --whitespace=error 'C:\Users\Adam\.codex\worktrees\t19-docs-rollout\.local-ai-hub\handoff\T19-O4-cli-partial-cleanup.patch'`  
Result: exit code `0`. `git apply --stat` reports only `tests/test_hubctl_mode.py` and `tools/hubctl.py`.

Tests/builds: not run. Requested T20 selector after integration: `python -B -m pytest -q tests/test_hubctl_mode.py`.

T13 seam notification sent successfully; message preserves the backend contract and assigns only CLI projection to T19. T20 notification attempt returned `no rollout found for thread id`; patch remains available at the path above for T20 integration.

Matching prompt parity remains statically verified in `T19-docs-static-acceptance-20261001.md`. Clean-host package acceptance, T08 recovery, and T20 release acceptance remain open.
