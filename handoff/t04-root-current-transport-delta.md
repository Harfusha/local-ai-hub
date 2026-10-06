# T04 root-current transport delta

Prepared in T04 worktree only. Root checkout unchanged.

- T04 base: `3658d5056354849ddf17883ed04f807f16cc44c1`
- Root target base: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`
- Root preimage SHA-256: `src/local_ai_hub/client.py` `393791DFC87F64247DB675B1E76C86DF6B4C666B937B70CAD2A55FC7BE44502C`; `src/local_ai_hub/inprocess_transport.py` `AED6A4B8B3F04A3AC0977CFA6D1618FF316441D9ED0E8ED976E234BBF3250C38`.
- Client patch `artifacts/t04-root-current-transport-20261003.patch`: SHA-256 `1A0C8743DB9C7C4CACD3F7C1E41D02DC0BF184E4F7297F19623BEA0D2425F291`.
- Adapter patch `artifacts/t04-root-current-inprocess-adapter-20261003.patch`: SHA-256 `A8972E806708868B77C50969E492E42121B755CE7C636EF3A3A5E093E12AA7A0`.
- Test patch `artifacts/t04-root-current-transport-tests-20261003.patch`: SHA-256 `585D20F8055842823D50EEEA79514C26DDDCDC55C8BDA7125D31F5C42B1BEF7`.

Review fixes: pooled fixture now selects pooled transport; in-process adapter accepts cooperative cancellation and reports dispatched work as uncertain; connect failures before successful connection classify as not sent; custom transports retain `request_not_sent` attribute compatibility. Explicit request ID, bounded deadline, retry/autostart and cancellation-aware singleflight remain covered. T21 path-hints and T13 operational mode excluded.

Focused command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t04_inprocess_transport_acceptance.py tests/test_inprocess_transport.py tests/test_client_transport.py tests/test_t04_client_retry_acceptance.py tests/test_t04_client_request_id_http.py`

Result: **54 passed in 6.17s**, exit 0. No full suite. Combined root-current `git apply --check` for all three patches passes. `git diff --check` passes with existing LF-to-CRLF warnings. Patches not applied to root; root source hashes still match preimages. Test slot released to T01.
