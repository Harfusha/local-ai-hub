# T04 explicit request-ID root-current handoff

Date: 2026-10-01 (Europe/Prague)

Candidate worktree: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`
Candidate HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`
Root target: `C:\Users\Adam\.local-ai-hub`, HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
No root writes.

## Scope and root-current disposition

User-approved T04 symbols only: `HubClient._valid_request_id`, explicit `request_id` validation, request/post signatures, request-ID header assignment, and forwarding from `post` to `request`. Excluded T07 uncertain-retry/replay-result code, caller submit passthrough, and shared fixtures.

A deterministic source comparison found the following allowed pieces identical between T04 candidate and current root: `_valid_request_id` body; `request` signature; invalid-ID guard; `X-LocalAI-Request-ID` header value; `post` signature; explicit-ID forwarding call. Root also already has both focused test selectors below. Therefore the root-current patch for this exact scope is empty: no T04 source/test hunk needs transfer, and copying broader `client.py` would risk replacing T07/T21-owned behavior. Full-file hashes differ because those files include other work:

- Candidate client: `B582F3DD53B656A7CD56E3D0A4E35F3E099D22452CD7D9060C8FAEFBE3294144`
- Current root client: `DDB55EDA5F1949B19A876106E056A0C92992AA4D00BF711D85EFB67D3809A562`
- Candidate transport tests: `777CC424B651130DC96FE4D2EAC21FE6E4C152E1C19C46F18EAE380587F588F3`
- Current root transport tests: `03000F1016075FC4B4025F9185CFFB471043663028F04496B0CD4F42D5EA06A0`

T07 coordination: T07 confirmed its overlap is the uncertain-retry response branch and JSON import; it does not edit T04 fixtures. T07 owns the uncertain-retry transport-result branch and import-only helper change in this overlap. T07 confirmed its current worktree does not include `test_transport_write_failure_marks_outcome_unknown` or `test_safe_posts_with_distinct_explicit_request_ids_do_not_coalesce`, and does not edit T04 fixtures. T04 excludes both tests from this hunk-only slice: the first covers T07 replay-result behavior; the second covers coalescing outside the approved validation/header/signature scope. No shared fixture was changed.

## Exact candidate validation

Command:

```powershell
$env:PYTHONPATH='C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub\src'; python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_transport.py::test_post_rejects_malformed_request_ids_before_network tests/test_client_transport.py::test_post_uses_explicit_request_id_across_safe_retry
```

Result: **2 passed in 2.01s**, exit 0. First selector proves invalid IDs fail before network; second proves the supplied ID reaches the request header and stays stable across the existing safe retry. No retry/replay-result code or fixture was edited.

Existing focused transport receipt with 16 request-ID/transport selectors is in `artifacts/t04-client-transport-e2e-current-receipt.md`; it records the exact two groups and candidate-only results. `git diff --check` passed for the current candidate (LF/CRLF advisories only).

## Integration handoff

No patch file is emitted for this slice because the allowed root-current delta is empty. T20 may rely on the current root implementation and existing selectors. T04 made no root write and does not claim root runtime acceptance.
