# T13 root-current conversation and Whisper cancellation port — 2026-10-01

This is the symbol-level port for the remaining HTTP cancellation seams. It is scoped to `http_server.py`, `services.py`, `preprocess.py`, and `background_gpu.py`. Root stays untouched; T20 applies the patch.

Superseded by the consolidated receipt in `handoff/T13-mode-matrix-and-T04-compat-2026-10-01.md`.

Current regenerated patch: `handoff/T13-rootcurrent-mode-cancellation-regenerated.patch`
SHA-256: `036DD510B7A20FBECFBEA8B456A0249826A5A1CFE24EA95F5C24103199636D55`

Current root already contains remaining mode/cancellation hunks in its inherited working-tree state. Regenerated patch excludes those inherited changes and contains only the missing HTTP admission receipt source field.

Root preimage SHA-256 used to produce and check it:

- `src/local_ai_hub/http_server.py`: `15F497AEFDE4E2EDFF4D8B6BA158C87FF70731C7F40762F10BE64445646F9278`
- `src/local_ai_hub/services.py`: `1556EDBE4336E1D0FECDAC86D79593AB6F62BE12A1F13841537CAC453721DCC1`
- `src/local_ai_hub/preprocess.py`: `14CDD83395263470DE8468A907045C083C9DA54127490CED4B81C5696716AD69`
- `src/local_ai_hub/background_gpu.py`: `B47DA57DBD8640F4C37CA3840818705772CBD861C0C87176ED3971C0B4806BB5`

Port details:

- Track in-flight synchronous conversation and Whisper requests; signal cancellation on gaming transition; bound the drain wait; skip runtime/accelerator release while any inference or preprocessing remains active.
- Reject reactivation before persisting active mode while a conversation or Whisper cleanup remains active. Root's current mode guard and stale-revision check remain in place; persisted `success`/`mode` fields are not repurposed for cancellation outcomes.
- Thread `cancel_event` through service generation and conversation reservation methods. Late canceled conversation output discards/aborts its reservation. Cleanup-unverified Whisper processes retain the active registry entry until confirmed exit.
- Recheck operational mode at queued model runtime handoffs. Failed/unreadable mode state blocks inference.

Verification:

- Regenerated root-current patch and T04/app patch combinations: both apply orders passed on isolated root copies; no root write performed.
- Candidate overlay AST: `http_server.py`, `services.py`, `preprocess.py`, `background_gpu.py` — all parsed.
- Isolated fake tests: `python -B -m pytest -q --tb=short tests/test_t13_cancellation_seams.py tests/test_t13_inference_start_gate.py tests/test_whisper_cancellation.py` — `12 passed in 0.66s`; no GPU or server ports. New gaming requests skip legacy handlers without cancellation support; reactivation checks active cleanup before mode persistence.

Additional isolated conversation acceptance: `python -B -m pytest -q --tb=short tests/test_conversations.py` — `23 passed in 0.48s`; this suite uses in-process stores/services and no shared server port.\n\nThis is T13 scoped evidence only. It does not close T13 full acceptance or replace T20 root integration/full-suite acceptance.


