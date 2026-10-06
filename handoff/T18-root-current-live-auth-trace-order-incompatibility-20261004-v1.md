# T18 root-current auth/trace order incompatibility v1

## Classification

Evidence-backed incompatibility; no source fix. Root-current GET pipeline deliberately authenticates protected endpoints before mode gating and tracing. Candidate test `test_live_status_named_dispatch_stays_after_auth_mode_trace_and_parse` hard-requires the opposite first relation (`trace < auth`). Current root diff explicitly moves `_begin_trace(path)` from before `_require_authorized()` to after authorization and mode rejection. Preserving current root contract while satisfying that assertion would require changing the auth boundary or test expectation. Neither is justified in this packet; test expectation left unchanged.

## Immutable references

This evidence packet adds no source/test patch. Previously prepared code packet: `T18-root-current-live-poll-handler-20261004-v3.patch`, SHA-256 `CB9FF0BBDEF45D27F6182096B81356522B3E133BCBF800FD846B8CAC9C25AB4D`.
Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
Candidate HEAD: `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`.

| Path | Root v3 base preimage | Root v3 postimage/current | Candidate current |
|---|---|---|---|
| `src/local_ai_hub/http_server.py` | `589C578EA5EB78C3192D3531FB776BF93FD703D9EFAB85B358B04A30891EFF24` | `5FE7F97420A1C22CEC4350F664046B70DA74333943FE14D7DA0AB02107EE0204` | `8ED3D8AA38F6C7355AC576CABC15BFE4517959093DC71B874539B85559142F22` |
| `src/local_ai_hub/http_route_registry.py` | `46AD21C6AFB648C2436D207E2BC83491CAFAF718B818F51707502738C372E4BA` | `90F599A9C5501DA17BCC234B008334F5749FB68F829E1CCC3B3819872E6ECF69` | `818CAA5990EA3B9410FBEFFB1A53C1E81A635D677F4D9E1FFC5B11BD4A9B1C56` |
| `tests/test_http_get_live_status_t18.py` | absent | `789B207A88F683889B7B72ED8DBCA97D206AFF6025AEDD52A4785F1F31F76B60` | `15BBBE8A6B3F45F69766F3DD2E26D497D2BD2AB34CCE1D5CF9A49ED3E2A7DBFF` |
| `tests/test_http_get_live_t18.py` | absent | `849B6FD3E5FDA7003FAC2C8B9BE940A079714E6AFB5C211D06B89068F41E869F` | `503428E90FF6C52208CBA3B26B18451EC8F19DB7F1FA9FBD323532DED7D2EB9C` |

Root-current AST line order from source: `_require_authorized` 2105 → `_http_mode_gate_error` 2107 → `_begin_trace` 2111 → `parse_qs` 2112 → `select_get_handler` 2114. Candidate AST: `_begin_trace` 2103 → `_require_authorized` 2110 → `_http_mode_gate_error` 2112 → `parse_qs` 2116 → `select_get_handler` 2118.

Root HEAD before worktree changes had trace before authorization; current worktree diff explicitly removes that call and adds it after authorization and mode gate. Current implementation comment states public dashboard shell has no runtime data while every data/control endpoint remains authenticated. This is evidence for current root intent; it does not establish broader runtime acceptance.

## Selectors and receipts

Candidate-only command: `python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_http_get_live_t18.py tests/test_http_get_live_status_t18.py`
Candidate receipt from current candidate source/tests: `9 passed in 0.64s`.

T20-provided root receipt (not rerun here): same selector, `8 passed, 1 failed in 0.93s`; sole failure was the strict trace-before-auth AST assertion. Root status-test SHA differs from candidate status-test SHA above.

No root writes, root tests, or candidate source/test edits in this follow-up. Existing T20 hold remains; T18 acceptance remains open.
