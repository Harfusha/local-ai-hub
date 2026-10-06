# T18 root-current GET /api/live and /api/live/status packet v3

## Scope

T18 dashboard polling and bounded live status: GET handler boundaries for `/api/live` and `/api/live/status`, exact GET registry mappings, existing inline behavior moved into named handlers, and focused contract tests. `/api/context/pack` excluded. No other route or task scope included.

## Immutable candidate packet

Patch: `T18-root-current-live-poll-handler-20261004-v3.patch`
Patch SHA-256: `CB9FF0BBDEF45D27F6182096B81356522B3E133BCBF800FD846B8CAC9C25AB4D`
Base root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`
Candidate HEAD: `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`

| Path | Base preimage SHA-256 | Proposed postimage SHA-256 |
|---|---|---|
| `src/local_ai_hub/http_server.py` | `589C578EA5EB78C3192D3531FB776BF93FD703D9EFAB85B358B04A30891EFF24` | `5FE7F97420A1C22CEC4350F664046B70DA74333943FE14D7DA0AB02107EE0204` |
| `src/local_ai_hub/http_route_registry.py` | `46AD21C6AFB648C2436D207E2BC83491CAFAF718B818F51707502738C372E4BA` | `90F599A9C5501DA17BCC234B008334F5749FB68F829E1CCC3B3819872E6ECF69` |
| `tests/test_http_get_live_t18.py` | absent | `503428E90FF6C52208CBA3B26B18451EC8F19DB7F1FA9FBD323532DED7D2EB9C` |
| `tests/test_http_get_live_status_t18.py` | absent | `15BBBE8A6B3F45F69766F3DD2E26D497D2BD2AB34CCE1D5CF9A49ED3E2A7DBFF` |

## Verification

Candidate selector, run in candidate worktree:

`python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_http_get_live_t18.py tests/test_http_get_live_status_t18.py`

Result: `9 passed in 0.64s`.

Root-current read-only `git apply --check` passed. `git apply --stat` lists exactly the four paths above. No root patch application or root tests performed. Root selector remains held pending zero generic pytest processes and separate explicit T20 GO. Root source currently has unrelated dirty work; recheck preimage hashes before any future application.

Status remains candidate-only; no live service/browser/runtime acceptance claimed. `/api/live/status` included in this packet, but overall T18 acceptance remains open.
