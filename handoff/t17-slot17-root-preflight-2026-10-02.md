# T17 root test slot 17 preflight — 2026-10-02

## Ownership and queue

- T17 candidate remains `C:\Users\Adam\.codex\worktrees\t17-multimodal-resume\.local-ai-hub`, HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`.
- Root remains T20-owned: `C:\Users\Adam\.local-ai-hub`, HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`.
- Orchestrator queue: slot 17 after T05/12, T03/13, T21/14, T01/15, T08/16. Do not run test until slot 17 is explicitly reached/released.
- Root `src/local_ai_hub/process_utils.py` and `tests/test_process_utils.py` are dirty; preserve their owner changes. No root mutation in preflight.

## Exact preflight completed (read-only)

- Root `tests/test_process_utils.py` SHA-256 `4A22549D9031C648EFE994B47EDCEB7376D19D062A891EDCDC694CC66C06BD95`; equals prepared patch LF-normalized postimage.
- Selector is present at root line 300: `test_run_hidden_cancellation_terminates_tree_and_drains_output`.
- `git apply --reverse --check -- C:\Users\Adam\.codex\worktrees\t17-multimodal-resume\.local-ai-hub\handoff\t17-process-cancellation-drain-test-root-current-v1.patch` exit 0; patch is integrated. Patch SHA-256 `70F70A58FC57CCD319BF2FFD8ADC58D031CAB6D3A5F23EBB1692CD798B90C55B`.
- No test, benchmark, or source command ran. Root HEAD unchanged; only read-only hashes/status/selector lookup performed.

## Slot-17 command — do not run before slot opens

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_process_utils.py::test_run_hidden_cancellation_terminates_tree_and_drains_output
```

After slot opens: reconfirm root test SHA and selector, execute only this selector once, preserve actual output/exit status. Do not run broader tests/benchmark. If result is unexpected, stop and hand exact receipt to T20; do not edit production source before RED receipt.

## Acceptance limits

- This selector proves mocked cancellation/process-tree termination/final stream drain only.
- Browser toolbar `activeTab` gesture, persistent daemon expiry/replay, natural multilingual Whisper WER, and live vision quality remain **NOT VERIFIED**. No test receipt here substitutes for those runtime gates.
- `/api/context/pack` remains outside T17 scope.
