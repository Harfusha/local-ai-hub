# T18 root-current integration manifest — 2026-10-02 v1

## Scope

Prepared from candidate worktree `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub`, HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`. Candidate contained mixed dirty work from other owners; this manifest includes only T18 telemetry artifacts and review receipts. No root files or cros-owner source/test files changed.

## T18 patch artifact and current integration state

- Patch: `handoff/T18-telemetry-flush-retry-20261002-v1.patch`
- SHA-256: `09BBC8E951F5DE8654C40F19E9120AE8C800D3621DDF6F902D411A49DBFE400F`
- Patch paths only: `src/local_ai_hub/telemetry.py`, `tests/test_telemetry_flush_retry_t18.py`.
- Candidate source SHA-256: `B58636B4FDD994279C5BA2659A80FCF87D4C7233AF3D7337FB7CCB1685D5E338`.
- Candidate new test SHA-256: `5D584579BF3927A4D93EAE2EB8EC97DEF3C16720A84EFA48C2276DAB317C83EC`.
- Original privacy test remains unchanged; SHA-256 `A33405560C715B20A621A243CBA6B26451FC38DB0CB1EDA43957ED978DAB3917`.
- T20 reported this patch applied to root. Reported root telemetry post-image SHA-256: `59A8F461CCF11C09526624EDEBD4D4FD99FB314935BE893BBFCE052CAF09281B`; root new test SHA-256: `D1FFDFB7BDB48870286B697AC374F4C9E18B9F5ACFBAB627ABD6DFF3394A8A13`. Do not apply the patch again.
- Earlier classification patch `handoff/T18-telemetry-error-class-sqlite-test-fix-20261001-v1.patch`, SHA-256 `BF45D78C0215F14FE6E7E8AB91A501DFA205CC4E31AFDC8CECF9FE1625F0934B`, is covered by prior T20 root-current pinned evidence; it is not a new pending patch.

## Validation receipts

Candidate full T18 selector plus retry regression: `66 passed in 19.83s`. Candidate strict telemetry selector: `10 passed in 6.33s`. Retention selector: `1 passed in 0.41s`.

Additional candidate dashboard/status selectors:

- Dashboard degraded/transition selector: `5 passed in 0.61s`.
- Status dependency degradation/deadline selector: `6 passed in 0.69s` (five node IDs, six parametrized cases).

T20 root regression command:

```text
C:\Python313\python.exe -B -m pytest -q -p no:cacheprovider --tb=short tests/test_telemetry_flush_retry_t18.py
```

Result reported by T20: `1 passed in 1.21s`. Root original privacy test after the fix and complete root release acceptance remain T20-owned and outstanding.

Candidate patch reverse-apply check and `git diff --check -- src/local_ai_hub/telemetry.py tests/test_telemetry_flush_retry_t18.py` both exited 0. These checks do not validate root state.

## Handoffs

- Coverage review: `handoff/T18-coverage-review-20261002-v1.md`, SHA-256 `4C0C646F43DAC36003F35720513B62A46941FFD9EA814597633D9D84E42D595E`.
- Candidate acceptance checkpoint: `handoff/T18-resume-checkpoint-20261002-v6.md`.
- Root admin/status acceptance receipts: `handoff/T18-status-dashboard-admin-acceptance-20261001-v1.md`.

T18 candidate scope is complete. Only root original privacy regression and T20 overall release review remain as integration dependencies. No root test ran during this handoff preparation.
