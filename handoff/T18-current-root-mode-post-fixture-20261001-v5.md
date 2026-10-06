# T18 current-root mode POST fixture update

Date: 2026-10-01. Owner: candidate worktree `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub`. Root edits and broad shared tests remain with T20. HUB ignored.

The legacy POST fixture failure came from stale assumptions: async unload helper on the mode module and the pre-T13 setter argument order. Candidate's old test is now replaced with a source-pinned root overlay runner. It does not add a deprecated alias or weaken partial-cleanup assertions. Candidate HTTP production code remains untouched.

The overlay fixture uses the actual current root setter `set_operational_mode(state_dir, mode)` and the current drain/unload contracts: `wait_for_inference_actions(...)`, `runtime.unload_configured_models(timeout_seconds=...)`, followed by verified accelerator release. Its gaming POST asserts a partial runtime unload (`model-a` unloaded, `model-b` failed), both accelerator releases unverified, drained process/conversation/admission fields, and the persisted mode. It also exercises loopback unauthenticated read-only GET, unauthorized action token, valid `mode.control` token, response JSON, and authorization audit. The root dashboard fixture checks badge state, degraded health, partial cleanup feedback and 401/503 UI paths using exact root HTML.

## Fresh root-pinned result

Root source pins used by the passing overlay:

- Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`
- Patch preimage `tests/test_http_operational_mode_t18.py`: `EAAA8F6CB264E9F008A9843F38245C2E574665DA65E24F5AE0EE9F5B113A5268`
- `src/local_ai_hub/http_server.py`: `4B635B978EF556A69863507D9B7672604068997BE32C55CEFA1E1C1CCCC9C8BE`
- `src/local_ai_hub/dashboard.py`: `9FC006FD0F5A3E3EBE2CFA0DA79F8786DFD4CB7BE1AB2CD6599CF7363C51A760`

Exact candidate-worktree command:

```text
$env:T18_ROOT_SOURCE='C:\Users\Adam\.local-ai-hub\src'; $env:T18_ROOT_HTTP_SERVER_SHA256='4B635B978EF556A69863507D9B7672604068997BE32C55CEFA1E1C1CCCC9C8BE'; $env:T18_ROOT_DASHBOARD_SHA256='9FC006FD0F5A3E3EBE2CFA0DA79F8786DFD4CB7BE1AB2CD6599CF7363C51A760'; python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_root_current_mode_overlay_t18.py tests/test_dashboard_mode_playwright_t18.py
```

Result: **2 passed in 4.22s**, exit 0. Each module origin and hash was asserted. HTTP state used `tmp_path`; listener used an ephemeral loopback port. No root checkout test suite or user browser ran.

The old candidate POST selector is replaced with this direct root-contract check:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_http_operational_mode_t18.py::test_admin_mode_post_uses_current_root_setter_and_partial_cleanup_contract
```

Result: **1 passed in 1.95s**, exit 0. This test launches the isolated root mode overlay with live SHA pins. No broad 137-test rerun was done; T20 owns that slot.

## Test-only root patch

The patch applies to the current root worktree with read-only `git apply --check` (exit 0); it was not applied. It replaces the stale root POST fixture and adds the root-pinned mode/DOM fixtures:

- `handoff/T18-root-overlay-dom-test-only-20261001-v2.patch`
- SHA-256: `87ADF207BBA0EF11DDF038142355464758188EB58F2ECB171EF7B323C1D568DA`

Patch paths: `tests/test_http_operational_mode_t18.py`, `tests/test_root_current_mode_overlay_t18.py`, `tests/test_dashboard_mode_playwright_t18.py`, and `tests/fixtures/dashboard_mode_playwright_t18.cjs`. No production files changed. Do not call the earlier 137-passed/1-deselected selector complete; full integrated acceptance still needs T20 receipts.

Candidate artifact SHA-256:

- `tests/test_http_operational_mode_t18.py`: `ADAAE6C4260A6700DB09744764546B10B82CAA7C59242A46A493833946684C72`
- `tests/test_root_current_mode_overlay_t18.py`: `42C9EAE05F83B466D5B98C3B90300FB2F40D63EB2EFEB04209B48ECA678731A3`
- `tests/test_dashboard_mode_playwright_t18.py`: `6A5C513A00B32A9E3F475B4421A93BD37D3864875C823BFAF3235052E1AAE257`
- `tests/fixtures/dashboard_mode_playwright_t18.cjs`: `35BDBB553FEEC9DC7849379F78DA4DC720EC4D5441BFE19D8F49D8B9DC8B7799`
