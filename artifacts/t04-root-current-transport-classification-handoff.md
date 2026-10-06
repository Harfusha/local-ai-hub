# T04 root-current transport-classification handoff

Date: 2026-10-01 (Europe/Prague)

T04 candidate: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`, HEAD `3658d5056354849ddf17883ed04f807f16cc44c1`.
Root target: `C:\Users\Adam\.local-ai-hub`, HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
Root was not modified.

## T04-only patch

Patch: `handoff/t04-root-current-transport-classification.patch`
SHA-256: `7FC09745E399D76DADF0EB808327EA01980E6CC1C29713C0B30CEE75BAAD17BC`

Test-only patch adds exactly:
- `test_transport_connection_refusal_marks_request_not_sent`
- `test_transport_other_connect_failure_is_not_classified_as_request_not_sent`

Imports are local inside these tests to avoid touching the shared module import hunk. No fixtures or assertions changed. T07 confirmed no ownership of these selectors and no T04 fixture edits. The T07 uncertain-retry/replay-result branch and write-failure selector are excluded. The separate explicit-ID coalescing selector is out of this T04 scope.

Root-current compatibility: `git apply --check --whitespace=error` passed against the current root worktree. Current root `tests/test_client_transport.py` SHA-256: `03000F1016075FC4B4025F9185CFFB471043663028F04496B0CD4F42D5EA06A0`. Current root `client.py` SHA-256: `DDB55EDA5F1949B19A876106E056A0C92992AA4D00BF711D85EFB67D3809A562`. `HubClient._transport_failure_response` AST is identical between candidate and root, so no source hunk is required for these tests.

## Validation status

After T02 released the shared test slot, the exact candidate command ran:

```powershell
$env:PYTHONPATH='C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub\src'; python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_transport.py::test_transport_connection_refusal_marks_request_not_sent tests/test_client_transport.py::test_transport_other_connect_failure_is_not_classified_as_request_not_sent
```

Candidate result: **2 passed in 1.83s**, exit 0.

The exact root patch was then reconstructed as a temporary test-file overlay outside the root checkout and run against root `src/` with `-B`, `-p no:cacheprovider`, and the root `pyproject.toml`. Root HEAD was `98a9a1a7611af574caf20a88620c4aa3eb2e918a`; result: **2 passed in 14.95s**, exit 0. `TemporaryDirectory` removed the overlay; root source/test files were not written. This is root-current overlay evidence, not an applied root patch.

Candidate and root results both support the two T04 selectors. T20 owns applying/integrating the patch; no root integration write is claimed.
