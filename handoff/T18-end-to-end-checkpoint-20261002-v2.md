# T18 end-to-end checkpoint — 2026-10-02 v2

## Current state

Active T18 goal continues in candidate worktree `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub`, HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`. All mixed dirty changes remain. No source/test edits this continuation. No Local AI Hub, prompt/broker file, or `/api/context/pack` access.

T02 owns the only test/benchmark slot. The latest process check found no running pytest, but no explicit slot release arrived; therefore no test or benchmark ran in this continuation.

## Bounded static review

- T18 flush patch applies in reverse to candidate with exit 0. Candidate scoped `git diff --check -- src/local_ai_hub/telemetry.py src/local_ai_hub/dashboard.py` exits 0.
- Safe error message stores allowlisted reason and sanitized exception type; raw exception text never enters that message. Error codes accept only bounded integer `status_code`, `errno`, or `code`; code affects the stable fingerprint. Existing privacy selectors assert same numeric code groups together, different code creates a different fingerprint, and prompt/source/token/path sentinels do not persist.
- Dashboard transition projection confirms persisted mode separately from follow-up work; it surfaces runtime-unload, accelerator-release, and job-cancellation failures, then polls pending unload state.
- No new T18 candidate defect or missing acceptance selector found by this bounded review. Existing candidate tests remain the latest executable receipt, not release acceptance.

## Exact owned patches and pins

- Telemetry retry patch SHA-256 `09BBC8E951F5DE8654C40F19E9120AE8C800D3621DDF6F902D411A49DBFE400F`; source pin `B58636B4FDD994279C5BA2659A80FCF87D4C7233AF3D7337FB7CCB1685D5E338`; test pin `5D584579BF3927A4D93EAE2EB8EC97DEF3C16720A84EFA48C2276DAB317C83EC`.
- Error-class patch SHA-256 `BF45D78C0215F14FE6E7E8AB91A501DFA205CC4E31AFDC8CECF9FE1625F0934B`.
- Operator-display patch SHA-256 `C65C257D082B180B908F6DCAC49DB09CA0131BF05E290D353CD7D9F9DCB579CC`.
- Candidate focused receipt: 42 passed in 18.85s; exact command is in `T18-resume-checkpoint-20261002-v7.md`.
- Root focused receipt: 48 passed in 10.31s; exact command/diffs are in `T18-root-current-acceptance-20261002-v2.md`.

## Integration dependencies

Root operational-mode API `_operational_mode_api` remains absent; root reproduction and test result are documented in root-current manifest v2. T13 owns mode production; do not transplant candidate mode route. T20 owns full root release review. Re-run targeted acceptance only after T02 explicitly releases the slot.
