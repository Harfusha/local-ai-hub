# T04 malformed JSON contract handoff

Root target: `C:\Users\Adam\.local-ai-hub`
Root HEAD at patch validation: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`
T04 candidate HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`

Patch: `handoff/t04-malformed-json-contract.patch`
Patch SHA-256: `7c86c5bf2d5dedba3a65dedf19412d05a9499e31f81a64c6c6fabf4f7eee16d9`
Patch applies cleanly to current root (`git apply --check --whitespace=error`). No root files changed.

T04 candidate changes:
- `src/local_ai_hub/client.py` SHA-256 `04cd4d0ce198c20c7a68357d587f00d91ffe3828c4ad5937e65a7d6fe703ad6e`
- `tests/test_t04_malformed_json_contract.py` SHA-256 `d8974b8b59ff577792a50aa31e83a33959fb820c433a6efaa617de1b9659fde7`

Static checks: test module `ast.parse` passed; scoped `git diff --check` passed. No tests run. Waiting for T20 exclusive test slot.

Queued selectors:
- `test_get_malformed_json_returns_complete_retryable_invalid_response`
- `test_ambiguous_mutating_post_malformed_json_is_unknown_without_replay`
- `test_safe_post_retry_malformed_json_keeps_safe_response_classification`
