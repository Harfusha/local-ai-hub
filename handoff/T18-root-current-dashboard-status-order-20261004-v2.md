# T18 root-current dashboard/status order packet v2

## Result and classification

Candidate dashboard/live-status source acceptance passes. The two order assertions now enforce T27's shared GET pre-dispatch order `auth -> mode -> trace -> query -> dispatch`; no acceptance condition weakened. Root-current GET source and registry already contain both named handlers and same order. Packet therefore changes only the two focused test assertions.

T27 dispatcher ownership preserved: no POST source, selector, registry, or priority changed. `/api/context/pack` remains inline/out of scope. T18 route ownership is grounded by the T18/T31 route-symbol parity record; generated API owner metadata is not used as ownership evidence.

## Exact root-current packet

Patch: `T18-root-current-dashboard-status-order-20261004-v1.patch`
Patch SHA-256: `758E3B1F4B90320F31B1EA8AA58DFC5D19BB020498E8886A5D95D8E02D0A3A1B`
Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`
Candidate HEAD: `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`

| Path | Root-current preimage SHA-256 | Root-current postimage SHA-256 |
|---|---|---|
| `src/local_ai_hub/http_server.py` | `5FE7F97420A1C22CEC4350F664046B70DA74333943FE14D7DA0AB02107EE0204` | unchanged, same SHA |
| `src/local_ai_hub/http_route_registry.py` | `90F599A9C5501DA17BCC234B008334F5749FB68F829E1CCC3B3819872E6ECF69` | unchanged, same SHA |
| `tests/test_http_get_live_t18.py` | `849B6FD3E5FDA7003FAC2C8B9BE940A079714E6AFB5C211D06B89068F41E869F` | `9486266D933D3FD02195B46838A4CCC75C33CF1A6282D5A1E7499078712D873A` |
| `tests/test_http_get_live_status_t18.py` | `789B207A88F683889B7B72ED8DBCA97D206AFF6025AEDD52A4785F1F31F76B60` | `7985BE9C52C3FDE3F889E7447A8D000A9B12A041116CEAF109F746474A8EEE69` |

Candidate validation pins: `http_server.py` `46DD0B4F35F6596034599AB44116677BAFE93027E56C6A8D6218BFC1FCE07834`; `http_route_registry.py` `818CAA5990EA3B9410FBEFFB1A53C1E81A635D677F4D9E1FFC5B11BD4A9B1C56`.

Read-only root `git apply --check` passed; `git apply --stat` lists exactly the two test paths. Patch not applied.

## Candidate selector receipt

`python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_http_get_live_t18.py tests/test_http_get_live_status_t18.py tests/test_status_snapshot_quality.py::test_status_route_surfaces_structured_probe_failure tests/test_http_post_route_registry_t18.py`

Result: `20 passed in 1.68s`. Live/status tests alone: `9 passed in 0.47s`. Selector includes T27 POST registry test and one status snapshot regression.

T20's earlier root receipt was `8 passed, 1 failed` on the reversed status-order assertion. No root test rerun or root write here. Root selector waits for explicit T20 serial slot. Candidate worktree has extensive pre-existing dirty/untracked state; all preserved.

Candidate dashboard/live-status acceptance done. Root receipt, runtime/browser/admin proof, and overall T18 remain open.
