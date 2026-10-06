# T13 root-current inference start gates — 2026-10-01

Scope: close queued-work pause gaps only. Root checkout was not edited.

Root preimage SHA-256 at patch generation:

- `src/local_ai_hub/services.py`: `BAE60B898DB52E078265A2419DC29C3BC08C4311A391279B62C898F7D4C04922`
- `src/local_ai_hub/preprocess.py`: `B507A3554FB13F1B2AB2C1A7AB409A0F64EA883C86C9959778D94D11388F6326`
- `src/local_ai_hub/background_gpu.py`: `B5B5BCEF1B1514A7A0072947315975479CE62A1A607E7DCDFA1BAFFC2CE0A421`

Patch: `handoff/T13-rootcurrent-inference-start-gates.patch`
SHA-256: `BBB940A34C67C9FE5D39D9C9A964A9D6017365688EE5867D6905AE1C80805218`

The patch adds a mode check immediately before service model dispatch, the queued preprocessor fallback dispatch, and the dedicated background GPU worker dispatch. Mode read errors fail closed. `git apply --check` passed against the root preimage above. AST parsing passed for all three transformed source files.

Cheap isolated receipt (no GPU or server ports):

`python -B -m pytest -q --tb=short tests/test_t13_inference_start_gate.py tests/test_whisper_cancellation.py`

Result: `6 passed in 0.34s`. One earlier run exposed only a fake profile missing `prompt_budget_tokens`; the test double was corrected before the passing run.

This does not yet port the root-current conversation/Whisper HTTP lifecycle patch. The earlier route handoff records that its patch was stale and failed apply-check. Candidate worktree has active conversation registry/cancellation and Whisper route cleanup, but a clean root-current patch still needs a symbol-level port that preserves the current root O3 mode revision guard and mode response contract. Do not infer T13 end-to-end acceptance from this receipt.
