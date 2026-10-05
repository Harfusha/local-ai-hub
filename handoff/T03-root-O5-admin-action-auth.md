# T03 O5 root-current auth handoff

Root: `C:\Users\Adam\.local-ai-hub`
Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`
Owner checkout: `C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub`

Root stayed read-only. Its `src/local_ai_hub/http_server.py` is already dirty (`05802B7089F6010461FA736EFB11088371025E723BEF5D7E4E3F0A0D6AD762B7`); `tests/test_http_admin_action_auth_t18.py` is untracked and belongs to the existing T18 auth work. No root files were changed.

## Finding and fix

`Handler._authorized()` treated any configured `security.action_tokens` entry as disabling the trusted-loopback fallback when `security.api_token` was empty. That made a local admin request fail because of an unrelated scoped token. The patch keeps scoped tokens for remote requests, keeps loopback trusted-local access when the global token is empty, and records the actor as `local`. Remote requests without a valid token remain unauthorized. Read-only `GET /api/mode` remains accessible on loopback.

Patch: `handoff/T03-root-O5-admin-action-auth.patch`
Patch SHA-256: `3A392F068EB92472EFCAFCEAC6E92EB3DE5D9C781897A5843F2A374C10FEDBFF`

Root source preimage SHA-256: `05802B7089F6010461FA736EFB11088371025E723BEF5D7E4E3F0A0D6AD762B7`
Proposed source postimage SHA-256: `BDA28969BA6B9C0895DE898883E0C093A00EDC557D993259A6CB9BC8A27E32A9`

## Verification

The regression test failed against an overlay restored to the current root source preimage at the local-admin assertion. After applying the proposed source hunk in the overlay:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short -c .t03-root-overlay/o5-root-current/pytest.ini C:\Users\Adam\.local-ai-hub\tests\test_http_admin_action_auth_t18.py .t03-root-overlay/o5-root-current/tests/test_t03_o5_admin_action_auth.py
```

Result: **9 passed in 0.43s** (`execution_id=9b5d6f20d0b04b4aa6fb00dd7b5de075`). The added test file SHA-256 is `916C1D892FFF890B4D840BC4627AF4B6B1B7AD8B7928E82E4F60D16DE062D617`.

`git apply --check --verbose handoff/T03-root-O5-admin-action-auth.patch` from the root checkout: **passed**. Patch is ready for the root owner to apply and rerun there; overlay evidence is not a root-current runtime receipt.
