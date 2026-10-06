# T18 root-current GET /api/live packet v2

## Scope and ownership

T18 scope: dashboard event polling via `GET /api/live`, its GET-handler registry mapping, and focused source contract tests. `handoff/T18-T31-route-symbol-owner-parity-20261003-v1.md` maps the route to the T18 dashboard event-poll consumer. API metadata row `op-5d550dcacf01` says `Owner task: unassigned`; that field is not ownership proof. No `/api/live/status` mapping is included; that acceptance slice remains open. `/api/context/pack` is excluded.

## Immutable patch

Patch: `T18-root-current-live-poll-handler-20261004-v2.patch`
Patch SHA-256: `49787034D77AFC3D6F0D0A4FB8FCE58D0B827435154369775EB74E6693148BD6`
Root HEAD observed: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`
Candidate HEAD observed: `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`

| Path | Root preimage SHA-256 | Proposed postimage SHA-256 |
|---|---|---|
| `src/local_ai_hub/http_server.py` | `589C578EA5EB78C3192D3531FB776BF93FD703D9EFAB85B358B04A30891EFF24` | `AC6DFA1923E87CB9433519C0B4A9B6F9E7D17A31B86F97885FCDB525708870E4` |
| `src/local_ai_hub/http_route_registry.py` | `46AD21C6AFB648C2436D207E2BC83491CAFAF718B818F51707502738C372E4BA` | `74CA367932B7330EE260D3A5B015DFFF3FEDDC9865AAF25E65B65C951DA29047` |
| `tests/test_http_get_live_t18.py` | absent | `503428E90FF6C52208CBA3B26B18451EC8F19DB7F1FA9FBD323532DED7D2EB9C` |

## Evidence and gate

Candidate-only focused receipt already recorded after the test correction: `python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_http_get_live_t18.py tests/test_http_get_live_status_t18.py` — 9 passed in 0.58s. This is candidate evidence, not root runtime acceptance.

Read-only root `git apply --check` passed against the observed root worktree. `git apply --stat` reports exactly the three paths above. Root `http_server.py` is dirty with extensive unrelated work; no root bytes were written by packet generation. Root selector/tests remain gated: no T02 slot/GO. The single root selector, after explicit release, is `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_http_get_live_t18.py`.

This packet covers only `GET /api/live` code and focused contract. Overall T18 remains open; no runtime service/browser/admin proof is claimed.
