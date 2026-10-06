# T20 root-current integration guide — 2026-10-02

No root changes made. Root HEAD observed: `01df56605ccf484ebfe2808ac60d696c4e81dffc`.

## Preimage pins

| Root path | SHA-256 / state |
|---|---|
| `src/local_ai_hub/operational_mode.py` | `B72023ED7BD029EA747794A02B5C8F6783E6DC592B4BF67542BDEE63F5D1F5A1` |
| `src/local_ai_hub/ollama.py` | `1C7D6E58234EAD892D42AC9A95818C9690E5162816CA3572DBE9B9BE79D04E42` |
| `src/local_ai_hub/http_server.py` | `8443F8E178C717C92C063394C585C8C38721BD18F644DB053DB6EF81A5F0E047` |
| `tests/test_operational_mode.py` | `558A4800F126C0E3D6D2FC724AE137DB0F51BFDDDA4646A861CF1E7F10A8392A` |
| `tests/test_operational_mode_http.py` | absent |
| `tests/test_operational_mode_http_gate.py` | `4985B116CE2A7F12978BB5B2884608BA67D3BD56F0FB7A746AB33F8D7ABE9C6D` |
| `tests/test_t13_ollama_unload_all_models.py` | absent |

Root `operational_mode.py` has no `unload_ollama_models_for_gaming`; root HTTP mode route calls `runtime.unload_configured_models` directly. Root `ollama.py` already imports `math` and has `unload_configured_models`. Root `_require_authorized` permits loopback `GET /api/mode` without token (`local_mode_read`), unlike T13 candidate test's expected 401.

## Patch checksums and dry-run results

- Candidate receipt guard `T13-rootcurrent-unload-receipt-validation-20261002.patch`, SHA-256 `19FA1329F6C7FCC369D13096D6F369C55EEE0B9E4948EE59096221E548C09EEC`: reverse-check passes against candidate; root `git apply --check` fails because root preimage lacks candidate helper/hunks.
- Candidate Ollama import/test `T13-rootcurrent-ollama-unload-20261002.patch`, SHA-256 `98BDEE5C3BC1FDB4D31E0875CFD7D8AD9C24B06806749ABFB9F95D8D54A2BD41`: reverse-check passes against candidate; root already has `import math`, so combined patch is not applicable unchanged.
- Candidate GET auth test `T13-rootcurrent-mode-api-get-auth-20261002.patch`, SHA-256 `C78FDA7D11C5913FF7FC13EE49ED51E0305973F0E0934E8E4D433C61034F1D9E`: reverse-check passes against candidate; root target test file is absent and root loopback policy differs.
- Root-safe addition of the all-model test only: `T20-rootcurrent-ollama-all-models-test-20261002.patch`; `git apply --check` passed against the pinned root. This adds one new test file; it does not change root source.

## Safe sequence for T20

1. Reconfirm root HEAD and dirty paths; preserve all current edits. Do not reset, checkout, stash, or apply to root until T20 approves integration.
2. Apply only the all-model test-only patch to a T20-owned integration worktree after rerunning `git apply --check` against that exact checkout.
3. Do not apply receipt-guard patch as-is. T20 must first decide whether root's direct unload-result path needs T13's normalization; port the guard and malformed-receipt test to root's actual source/test contract if required.
4. Do not apply candidate GET-auth patch as-is. It conflicts with root's loopback `GET /api/mode` exemption. T20 must retain or change that policy explicitly, then add a test matching the chosen contract.
5. Run targeted selectors in the T20 integration checkout only after patch/preimage review. Suggested selectors: `tests/test_t13_ollama_unload_all_models.py::test_gaming_unload_requests_every_loaded_ollama_model_and_verifies_empty_set`, `tests/test_operational_mode.py::test_mode_updates_from_multiple_processes_do_not_lose_revisions`, `tests/test_operational_mode.py::test_mode_replace_retries_windows_sharing_violation`, `tests/test_operational_mode.py::test_mode_replace_sharing_violation_retry_is_bounded`, `tests/test_operational_mode.py::test_mode_update_retries_transient_replace_permission_error`, `tests/test_operational_mode.py::test_http_mode_routes_read_and_update_persisted_mode`, and `tests/test_operational_mode.py::test_http_mode_update_rejects_invalid_and_unauthorized_requests`.

This is integration preparation only. No root selector or runtime unload/VRAM proof was run.
