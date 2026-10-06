# T12 gaming / VRAM lifecycle root-current evidence — 2026-10-02

## Ownership and boundary

T12 candidate worktree: `C:\Users\Adam\.codex\worktrees\4816\.local-ai-hub`, HEAD `933c0129079fcc0c894a71fe842cbbb5e6ad7285`. This handoff covers T12 model inventory, tiered handoff, unload-before-switch, post-unload admission, and gaming maintenance unload. It does not cover T13 async/conversation lifecycle or shared `services.py`; `/api/context/pack` is untouched.

Root inspected read-only at `C:\Users\Adam\.local-ai-hub`, HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`. Root has dirty changes in `ollama.py`, `llama_cpp.py`, `tiered_ollama.py`, `scheduler.py`, and `tests/test_tiered_ollama_runtime.py`; no root writes were made.

## Root-current patch applicability

The one-file tiered-wrapper patch `handoff/T12-tiered-wrapper-root-current-20261002.patch` has SHA-256 `ABD0E8A67DE3B38AB71E275AAABFFB9132CD2EC82DCE608B31BCEDBBDB3EC6DD`; it changes only `src/local_ai_hub/tiered_ollama.py` (36 insertions, 5 deletions). The corresponding test patch `handoff/T12-tiered-wrapper-tests-root-current-20261002.patch` has SHA-256 `7A2CC279B828D6146B571F3F9BF2E0F490ACB240C7B131FAC58B66FB99A85207`; it changes only `tests/test_tiered_ollama_runtime.py` (73 insertions, 3 deletions).

Read-only `git apply --check --whitespace=error` against current root failed for both patches because their hunks are already present. `git apply --reverse --check --whitespace=error` passed for both. This establishes the exact patch hunks are in root; do not reapply. No merge or root mutation was performed.

Root SHA-256 at review:

- `src/local_ai_hub/ollama.py`: `1C7D6E58234EAD892D42AC9A95818C9690E5162816CA3572DBE9B9BE79D04E42`
- `src/local_ai_hub/llama_cpp.py`: `E300BFBD78376E2B610719DF36009E38B1170F5D5544C6CD27BFCBEC0EA21E11`
- `src/local_ai_hub/tiered_ollama.py`: `FB209A13B54FD8D7A6CC198F49C90C0BE22004BDBE65A7095DAF12916C360DD2`
- `src/local_ai_hub/scheduler.py`: `D728327691E486421E0C661D2C9CBB8EDDF1FDEB7CA9DDAF20B704EBB0376ED1`
- `tests/test_tiered_ollama_runtime.py`: `C02362CEDD4C3378C95CEEA4850FB8291DA5B0293A1FF4D808493FACFF8F8D02`

## Candidate lifecycle evidence

Candidate source/test SHA-256:

- `src/local_ai_hub/ollama.py`: `C0B63E75E5639ACA26619B2718695A6725029A3948ABC7E687A510E3E256EFC4`
- `src/local_ai_hub/llama_cpp.py`: `026A53B11FD4E3FDA46750DEA7BD89378355447BAE85509FE8FA60F5664AC3C1`
- `src/local_ai_hub/tiered_ollama.py`: `C21644B24CB996FD682A1D7EEE11C5B3FD2763597891AFA0F427D3208E04F5FB`
- `src/local_ai_hub/scheduler.py`: `7E012E058D8AE213C50866D2E937F147C5C6871EECF8AD55FA1D273805ACC91D`
- `tests/test_ollama_gaming_mode.py`: `8A6B23620B350523DD1F58E215374C40CBED3A9A0541608F7E51F1E377D7EE3F`
- `tests/test_t12_gaming_pause_loaded_rows.py`: `B4F1E89E33074F66C9728E1AA1AA60492EC29B5B6D48A47DDE1F5E95AE196C47`
- `tests/test_t12_llama_model_inventory.py`: `2A130B82FC4A657B2CE9D9BBA7F948FAEA19000F53A508C45A48CF29D85ECFB0`
- `tests/test_tiered_ollama_runtime.py`: `E50E87D7F3268D7AC01AD9C8F7A9A4E9F1142115F130A786EB6FDC1298854686`

Earlier focused candidate receipt: **61 passed in 6.33 s**. It included the strict Ollama inventory/gaming tests, loaded-row pause/unload tests, Tiered handoff/admission tests, and llama.cpp model inventory tests. Relevant selectors include:

- `test_smart_request_unloads_fast_runner_before_dispatch` — unload before fast→smart tier handoff.
- `test_model_switch_uses_fresh_post_unload_vram_and_records_admission` — fresh VRAM admission after unload.
- `test_gaming_unloads_both_enabled_backends` — maintenance pause unloads both enabled backends.
- strict endpoint inventory and exact owner-routed unload tests — unknown/incomplete inventory stays unverified; duplicate model IDs retain endpoint ownership.

This is offline/mock contract coverage, not a live daemon, physical VRAM, or model-quality receipt. The separate model-free harness receipt `handoff/T12-model-free-offline-20261002-rerun.json` is `synthetic_model_free`, `live_inference=false`, `quality=not_measured`, `vram_bytes=null`; it provides scheduler timing and queue-rejection observations only.

## Open proof

No live model was started or installed. No physical VRAM measurement, live quality evaluation, or T02 paired baseline exists. The T12 deadline selector GO #16 returned `Transport closed` without receipt and remains UNKNOWN; it was not retried. Root-current gaming/tiered selectors still require explicit fresh T20 serial GO before execution.
