# T12 routing/batching receipt — 2026-10-06

## Candidate scope

- Worktree: `C:\Users\Adam\.codex\worktrees\4816\.local-ai-hub`
- Candidate HEAD: `933c0129079fcc0c894a71fe842cbbb5e6ad7285`
- Master comparison: `b947d76fdfb7ed592b72e55587d5c83cfa352c35`
- Repository fingerprint during test run: `0bea1d32108955c044d01477485fcc3297356cc3884a0e14e7c06ce289f2ba9f`
- No source or test file was edited in this continuation. Shared `services.py` untouched.

## Focused batching receipt

Command, routed through `local_ai_command`:

`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t12_runtime_scenarios.py tests/test_tiered_ollama_runtime.py -k 'batch'`

Result: **2 passed, 33 deselected in 0.19s**, exit 0.

SHA-256 before and after test run matched:

| Role | Path | SHA-256 |
|---|---|---|
| T12 scenarios | `tests/test_t12_runtime_scenarios.py` | `E7742A708554858A9A94FD4F58125B12FFBE7E0B94D874C3868FE47D05AE64F9` |
| Tiered runtime tests | `tests/test_tiered_ollama_runtime.py` | `E50E87D7F3268D7AC01AD9C8F7A9A4E9F1142115F130A786EB6FDC1298854686` |
| Scheduler source | `src/local_ai_hub/scheduler.py` | `7E012E058D8AE213C50866D2E937F147C5C6871EECF8AD55FA1D273805ACC91D` |
| Tiered runtime source | `src/local_ai_hub/tiered_ollama.py` | `C21644B24CB996FD682A1D7EEE11C5B3FD2763597891AFA0F427D3208E04F5FB` |

These are candidate contract tests; they do not prove live batch latency or physical VRAM.

## Live latency and VRAM

**NOT VERIFIED.** Latest bounded status reported `active_model: null`, queue/inflight 0, VRAM pressure `nominal`. No installed-model inventory or live inference receipt was available for this run. Prior `local_ai_task(action="hardware_benchmark")` failed with `AttributeError: '_InterruptibleSocketReader' object has no attribute 'peek'`; it was not repeated. No cold/warm/model-switch latency or VRAM measurement is claimed.

## Ownership

Existing source/test changes are inherited or mixed-owner. This receipt is the only file authored in this continuation. No root/master change, model pull, or installation.
