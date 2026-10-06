# T04 request-ID transport root-current manifest

Date: 2026-10-02 (Europe/Prague)

## Candidate

- Worktree: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`
- HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`
- Branch: `codex/t04-integration-2b33602`
- Added test: `tests/test_t04_client_request_id_http.py`
- Test SHA-256: `F0C80022420D81C7F78AB4438CDA5B2E8C0C29396426D6E98A5737D4F79D8CC0`
- Focused API client/request-ID transport batch: **39 passed in 4.66s**, exit 0. Exact command and inherited ownership receipt: `artifacts/t04-client-request-id-http-receipt-2026-10-02-v1.md`.

## Root-current patch

- Root HEAD: `01df56605ccf484ebfe2808ac60d696c4e81dffc`.
- Existing root `src/local_ai_hub/client.py` SHA-256: `5518706E0E81623E3FF0184274BD17F18C9BF7F43D9BC4DD37FD754586B0D056`.
- Existing root `tests/test_client_transport.py` SHA-256: `03000F1016075FC4B4025F9185CFFB471043663028F04496B0CD4F42D5EA06A0`.
- At initial handoff creation, root did not yet contain `tests/test_t04_client_request_id_http.py`; later root integration receipt is recorded below.
- Patch: `handoff/t04-client-request-id-http.root-current.patch`.
- Patch SHA-256: `0FDCDA8D586ED1892A97615B53605CECCCE7E22982CB293DC73631E1A16B5FBA`.
- Patch contains only the new test file. It does not replace root client or test hunks.
- At initial handoff creation, `git -C C:\Users\Adam\.local-ai-hub apply --check <patch>` returned **exit 0**. T04 did not apply the patch or run root tests.

## Ownership

T04 dirty source and test state was preserved. Patch adds one standalone T04 test only. Root dirty hunks remain owned by T20 and their source owners. `/api/context/pack` is untouched.

## Root-current integration receipt (2026-10-02)

T20 reports that root integration is present and ran this exact command after its `NO_ACTIVE_TEST_OR_BENCHMARK` guard:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_transport.py tests/test_t04_client_request_id_http.py
```

Result: **28 passed in 3.62s**, exit 0. No benchmark ran. T04 did not rerun root tests.

Read-only root check confirms HEAD remains `01df56605ccf484ebfe2808ac60d696c4e81dffc`; `client.py` and `test_client_transport.py` are dirty under their existing owners; the new test path is present. Root test raw SHA-256 is `E38E06B6860F02E64E5B460DDB18AFE932B8062162F969099CEB11CED691B1CB`; after CRLF-to-LF normalization its content SHA-256 matches the T04 candidate `F0C80022420D81C7F78AB4438CDA5B2E8C0C29396426D6E98A5737D4F79D8CC0`. T04 made no root edits.
