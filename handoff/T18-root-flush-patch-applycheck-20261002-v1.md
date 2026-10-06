# T18 root patch apply-check — 2026-10-02 v1

## Command

Executed from `C:\Users\Adam\.local-ai-hub` against current root working tree:

```text
git apply --check --whitespace=error C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub\handoff\T18-telemetry-flush-retry-20261002-v1.patch
```

Exit code: `0`. Patch SHA-256: `09BBC8E951F5DE8654C40F19E9120AE8C800D3621DDF6F902D411A49DBFE400F`.

## Exact current-root pre/post state

| Item | Before check | After check |
|---|---|---|
| Root HEAD | `01df56605ccf484ebfe2808ac60d696c4e81dffc` | `01df56605ccf484ebfe2808ac60d696c4e81dffc` |
| `src/local_ai_hub/telemetry.py` SHA-256 | `191DC35FEC06D804261D14BDA91837FBD088FEE82FE8B6A8BB6D266AAE2E10E5` | `191DC35FEC06D804261D14BDA91837FBD088FEE82FE8B6A8BB6D266AAE2E10E5` |
| Scoped Git status | `M src/local_ai_hub/telemetry.py` | `M src/local_ai_hub/telemetry.py` |
| `tests/test_telemetry_flush_retry_t18.py` | absent | absent |

No root file, index entry, or HEAD changed. No test ran.

## Proposed post-image hashes (not applied)

Both source hunks matched exactly once in the current root file. Applying them in memory while preserving current CRLF endings gives proposed `src/local_ai_hub/telemetry.py` SHA-256 `59A8F461CCF11C09526624EDEBD4D4FD99FB314935BE893BBFCE052CAF09281B`. This is a calculated post-image only; root remains at the pre-check hash above.

The patch adds new `tests/test_telemetry_flush_retry_t18.py`; current root preimage is absent. Patch payload file SHA-256 is `5D584579BF3927A4D93EAE2EB8EC97DEF3C16720A84EFA48C2276DAB317C83EC` (working-tree line-ending conversion, if any, is not applied or claimed).

Root current preimage was dirty before check. T20 owns any apply, integration, or tests. T18 did not modify root.
