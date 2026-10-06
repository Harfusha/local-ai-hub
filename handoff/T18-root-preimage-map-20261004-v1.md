# T18 root preimage map — 2026-10-04

Read-only pins. No patch applied to root.

| Path | Root preimage | Candidate reviewed state | Integration note |
|---|---|---|---|
| `src/local_ai_hub/http_server.py` | SHA-256 `C97AA26A4D84BE35FE7BFA1A18FDBB5AE9A5BA393F73D541D38E3F2DCB33D93D` | SHA-256 `8EC06E4BCCC9285B3D58F2D8A63DB1E830D91574090812DEACE5308612EA5A95` | Divergent files (root 313821 bytes, candidate 283749 bytes); do not apply candidate whole-file diff. Requires owner-aware transplant against fresh root source. |
| `src/local_ai_hub/http_route_registry.py` | Absent | SHA-256 `FD9D37489F0C6C2875E1E605865A2C369B939E102FEBC67AAC7A53E1EC5AC62C` | New candidate registry; root insertion not prepared. |
| `tests/test_http_post_route_registry_t18.py` | Absent | SHA-256 `5F33CF69599CE84EA2131ED6E8942174040BB98CABE7AC27411324DF621C6D69` | Candidate-only focused tests. |
| `docs/API_COVERAGE.md` | SHA-256 `66B5C89FE088021E5D32FEebd1bf953edffad729ec16a55e2b814dc9dacc40f0` | Candidate crosswalk records 222 rows; root has 223. | Owner metadata remains `unassigned`; no ownership inferred. |

Root HEAD at capture: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`. Root source has pre-existing dirty state. This map is evidence only; no root tests or writes.
