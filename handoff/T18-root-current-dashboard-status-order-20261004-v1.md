# T18 root-current dashboard/status order packet v1

## Classification

Candidate dashboard/status acceptance passes. Root source already contains both named GET handlers and the correct shared pre-dispatch order; only two focused test assertions needed correction to match T27's documented contract. Assertions are stricter after this change: both `/api/live` and `/api/live/status` now require `auth -> mode -> trace -> query -> dispatch`. No route expectation was weakened.

T27 ownership preserved: no POST route, handler, selector, or route priority changed. `POST /api/context/pack` stays outside registry. T18 route ownership comes from the T18/T31 route-symbol parity map, not generated API owner metadata.

## Root-current packet

Patch: `T18-root-current-dashboard-status-order-20261004-v1.patch`
SHA-256: `758E3B1F4B90320F31B1EA8AA58DFC5D19BB020498E8886A5D95D8E02D0A3A1B`
Root HEAD observed: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`
Candidate HEAD observed: `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`

Root source and registry already match desired implementation and remain unchanged by this packet:
- `src/local_ai_hub/http_server.py`: `5FE7F97420A1C22CEC4350F664046B70DA74333943FE14D7DA0AB02107EE0204`
- `src/local_ai_hub/http_route_registry.py`: `90F599A9C5501DA17BCC234B008334F5749FB68F829E1CCC3B3819872E6ECF69`

| Test path | Root-current preimage SHA-256 | Candidate postimage SHA-256 |
|---|---|---|
| `tests/test_http_get_live_t18.py` | `849B6FD3E5FDA7003FAC2C8B9BE940A079714E6AFB5C211D06B89068F41E869F` | `9486266D933D3FD02195B46838A4CCC75C33CF1A6282D5A1E7499078712D873A` |
| `tests/test_http_get_live_status_t18.py` | `789B207A88F683889B7B72ED8DBCA97D206AFF6025AEDD52A4785F1F31F76B60` | `7985BE9C52C3FDE3F889E7447A8D000A9B12A041116CEAF109F746474A8EEE69` |

Root-current read-only `git apply --check` passed; patch stat lists exactly these two test paths. Patch not applied.

## Candidate-only receipt

Command:

`python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_http_get_live_t18.py tests/test_http_get_live_status_t18.py tests/test_status_snapshot_quality.py::test_status_route_surfaces_structured_probe_failure tests/test_http_post_route_registry_t18.py`

Result: `20 passed in 1.68s`. This includes the T27 POST registry test and one status snapshot regression. The focused live/status tests alone report `9 passed in 0.47s` after order correction.

T20's earlier root receipt remains `8 passed, 1 failed` on the reversed order assertion; no root test was rerun. Root selector is still gated on an explicit T20 serial slot. Candidate HEAD/worktree remains dirty; all pre-existing unrelated dirty and untracked files were preserved.

This closes only candidate dashboard/live-status source acceptance. Root test receipt and runtime/browser/admin acceptance remain open; overall T18 stays OPEN.
