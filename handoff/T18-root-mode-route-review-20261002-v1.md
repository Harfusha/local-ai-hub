# T18 root mode-route reconciliation — 2026-10-02 v1

## Correction to earlier blocker

Earlier handoff `T18-root-current-acceptance-20261002-v2.md` called root mode API absent because `_operational_mode_api` was absent. That conclusion was too broad. Root `http_server.py` at HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`, SHA-256 `8443F8E178C717C92C063394C585C8C38721BD18F644DB053DB6EF81A5F0E047`, contains inline current handlers:

- `_http_admin_action` classifies GET `/api/mode` as `status.read` and POST `/api/admin/mode` as `mode.control` (around lines 253–288).
- `_require_authorized` exempts loopback GET `/api/mode` after normal auth denial (around lines 1463–1484).
- `Handler.do_GET` returns the persisted `load_operational_mode(...)` snapshot for `/api/mode` (around lines 2055–2056).
- `Handler.do_POST` handles `/api/admin/mode` (from line 2741).

Root therefore has production mode routes. No T13 source transplant is indicated by this evidence.

## Why previous root selector failed

Candidate `tests/test_http_operational_mode_t18.py` monkeypatches `http_server._operational_mode_api`, a candidate-only seam absent from root. Its 22 root failures do not establish missing root behavior. Root direct suite has `tests/test_operational_mode.py::test_http_mode_routes_read_and_update_persisted_mode` and `::test_http_mode_update_rejects_invalid_and_unauthorized_requests`. Root action-token suite has `tests/test_http_admin_action_auth_t18.py::test_mode_control_action_token_authorizes_only_remote_mode_update` and `::test_empty_token_policy_uses_actual_loopback_client_address`.

The candidate root-current overlay `tests/test_root_current_mode_overlay_t18.py::test_current_root_mode_read_auth_post_and_json_envelope` pins root source and exercises actual root GET/POST handlers, but stubs `_require_authorized`; it does not prove the loopback auth exception.

## Remaining exact root-current selector

After T02 explicitly releases its only test slot, run a focused root-current selector covering:

1. Root `tests/test_operational_mode.py::test_http_mode_routes_read_and_update_persisted_mode`.
2. Root `tests/test_operational_mode.py::test_http_mode_update_rejects_invalid_and_unauthorized_requests`.
3. Root `tests/test_http_admin_action_auth_t18.py::test_mode_control_action_token_authorizes_only_remote_mode_update`.
4. Root `tests/test_http_admin_action_auth_t18.py::test_empty_token_policy_uses_actual_loopback_client_address`.
5. A pinned root-current regression for configured API token + unauthenticated loopback GET `/api/mode` allowed, remote GET denied. Existing candidate mode test has this behavior but relies on `_operational_mode_api`; adapt the root-current test seam or add a separate root overlay test after slot release.
6. Root dashboard transition/error tests already present in the earlier 48-pass receipt; refresh those only if T20 changes their pinned sources.

No tests or benchmarks ran for this reconciliation because T02 slot remains active. No root or source file changed. T20 full root release acceptance remains separate.
