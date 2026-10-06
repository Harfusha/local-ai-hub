# T21 MCP path-hint test instrumentation handoff — 2026-10-05

Status: candidate-only test fix verified; root-current test-only packet prepared and apply-checked, not applied. Production code untouched.

## Checkout and ownership

- T21 candidate: `C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub`, branch `codex/t21-project-config`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.
- Root current: `C:\Users\Adam\.local-ai-hub`, branch `master`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Sole modified candidate path in this change: `tests/test_mcp_repo_path_hints.py` (untracked T21 test file). Root file is also untracked and was not edited.
- The test now records all mocked `CLIENT.post` calls, selects `/api/search`, and retains the exact existing `path_hints` assertion. No assertion was weakened. No production path changed.

## Root-current test-only packet

- Patch: `handoff/T21-mcp-path-hint-test-instrumentation-root-current-20261005.patch`
- Patch SHA-256: `0298750964F8C8F6B08A66D17E4E45E2283D92F93B69604571E608DF471D28D7`
- Patch bytes: 1,060; stat: one file, 5 insertions / 4 deletions.
- Root test preimage SHA-256: `EF7B66D95D3E011CE28AF3D90668F19417DEECFE0D55B9D51BFFF1B665EC2AF6` (untracked, CRLF).
- Expected root test postimage SHA-256 with original CRLF preserved: `FE960473A4B8CC68233B2701FCD363B000B1B81B4549A7A894CEB3C9C401416B`. This is computed, not observed; patch was not applied.
- Read-only root `git apply --check`: **exit 0**. Root hash remained the preimage.

## Candidate file pins

- Candidate test preimage SHA-256: `FBFC065E534653BFA262A2253AF8BE94751BB8CCC99558D7D27739A554AA5319`.
- Candidate test postimage SHA-256: `744B0609968FC98A715042F138289FE7821C021979C168C272466BD6098F4E70`.
- No other candidate file changed by this test fix.

## Test receipts

Before test instrumentation change, candidate isolated selector: **1 passed in 4.36s**, exit 0. Root had the owner-reported failing wrapper case caused by the telemetry post call overwriting a single captured record.

After change, exact isolated selector:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mcp_repo_path_hints.py::test_repo_search_forwards_known_path_as_scoped_path_hint
```

Result: **1 passed in 2.02s**, exit 0.

Focused project/config/path-hint subset:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_config.py tests/test_project_config_worktrees.py tests/test_project_config_service_integration.py tests/test_t21_project_config_preprocess.py tests/test_project_path_hints.py tests/test_mcp_repo_path_hints.py tests/test_client_path_hints.py
```

Result: **138 passed in 11.79s**, exit 0. Candidate only; no root tests.

## Integration boundary

Root patch remains unapplied. No T14 `/api/context/pack`, T03 schema, or production adapter/source file was changed. Root acceptance remains owner-controlled.