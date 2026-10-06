# T13 operational-mode source review — 2026-10-02

## Finding and source-only fix

Owner: T13 candidate. Files:

- `src/local_ai_hub/operational_mode.py`, SHA-256 `4F065BD44116054929F788EB47958A8EC32D420FD889744AEF5C52EED7188BF0`
- `tests/test_operational_mode.py`, SHA-256 `F8D33E47F793ACB25E7FEF7C69621B9BD1C4E5828C544CC8C74010EA9EBFFF26`

Receipt mapper previously classified `success=True`, `unloaded=[]`, `verified=True`, `remaining=["fast:latest"]` as `not_applicable` with reason `no_configured_models_loaded`, despite the remaining-model inventory. Tightened the branch so `not_applicable` requires an empty verified remaining list; the inconsistent receipt now maps to `partial`, with `success=False`. Added this case to `test_gaming_ollama_release_maps_owner_receipts_without_inventing_success`.

## Validation

- Syntax-only AST parse of both changed files: **PASS**.
- AST/source review passed; the exact selector was submitted once on T20 slot09 through `local_ai_command` after root hash pins matched. Hub returned **UNKNOWN**, request `req_31241f6fa3a3`; execution cannot be confirmed. No retry or native fallback.
- Slot receipt: `handoff/T13-slot09-unknown-20261002.md`, SHA-256 `D5BAD5F70A9065CBEF73B64E565A4165A726694D2840BC15049226E6FC6B1C6E`.
- Exact selector command submitted:

```text
python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_operational_mode.py::test_gaming_ollama_release_maps_owner_receipts_without_inventing_success
```

## Acceptance boundary

- Source behavior and regression case are prepared, but acceptance remains **UNKNOWN** until a newly authorized safe validation path is provided. The exact request was not retried.
- Runtime Ollama unload and CUDA/physical VRAM reclamation are **NOT VERIFIED** by source inspection or unit selectors. Code deliberately reports `physical_vram_reclaimed=False`; runtime proof needs a live Ollama inventory plus CUDA/device evidence.
- Existing T13 end-to-end goal remains blocked on the focused selector and valid T19 full-suite receipt.

## Offline persistence/restart review

- Owner scope: `tools/hubctl.py`, `src/local_ai_hub/operational_mode.py`, and T13-owned hubctl acceptance tests. Source review found no missing production branch: offline hubctl uses `set_operational_mode`; state writes serialize through the per-path thread lock plus cross-process file lock, write/fsync a unique sibling temp file, then replace atomically. Reads reload the file rather than relying on process cache. Online transition failures do not fall back locally.
- Coverage gap: existing `test_mode_command_persists_any_mode_when_hub_is_offline` reloads from the same process only. Added `test_offline_hubctl_mode_survives_fresh_process_restart` to spawn a clean reader process and assert persisted mode, revision, and degraded status.
- Test file SHA-256 `8CF303E41288F32E98356F65351480B96B2D4F17DB860D51E6FC64692B270560`.
- AST parse and `git diff --check` passed. Selector remains unrun pending T20 serial validation slot:

```text
python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_hubctl_operational_mode.py::test_offline_hubctl_mode_survives_fresh_process_restart
```
- No production source change from this review. No test, runtime, Ollama, or CUDA claim made.
