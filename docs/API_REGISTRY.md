# API contracts and route registry

`src/local_ai_hub/operation_contracts.py` is the source of truth for the seven public MCP tools and their action contracts. It supplies MCP schemas and validates action inputs. Each action records required and non-empty fields, allowed fields, feature requirements, state effects, idempotence, retry safety, replay policy, input/output schemas, and response projection.

`src/local_ai_hub/http_route_registry.py` owns canonical POST route selection. Accepted POST requests pass shared loopback admission, Host/Origin checks, and the local-actor authorization gate. Route branches may add explicit repository, task, or memory scope binders; unobserved route scopes remain unknown. `docs/HTTP_API.md` describes public endpoint behavior; `docs/SECURITY_MODEL.md` describes shared trust and authorization boundaries. A feature gate or action requirement describes availability; it does not grant authorization.

Every catalogued POST route records the shared HTTP authorization layer: `_require_authorized` validates Host/Origin, then `_authorized` admits a loopback client as actor `local`; this layer has no per-user principal or bearer token. Route invariants record exact route selection before body parsing and identity-field rejection. `state_boundary` identifies the single-installation scope, while handler-specific state effects stay unverified until supported by route evidence.

`dispatch_scope_binding` reports binder calls found in the most specific exact-path or path-prefix branch, a matching registered route-ID branch, or a named route handler boundary in `Handler.do_POST`; source references appear on each catalog row. `observed` means the selected branch or named handler invokes the listed helper; it does not prove downstream state effects. `not_observed` means static analysis found no binder there, so route scope remains unknown.

`route_dispatch` records source-backed named handler boundaries, direct `self._handle_post_*` calls, and direct `APP.*` call targets found in those selected path/route-ID branches. It identifies dispatch destinations only; it does not claim transitive state effects, authorization beyond the shared HTTP gate, or complete runtime reachability.

For each POST row, `authorization_boundary` records the common Host/Origin, retired-identity, loopback, audit, and rate-limit gate, plus any route-specific scope-guard call. It does not imply per-user authentication. `scope_boundary` names observed guards and leaves their deeper enforcement unverified; routes with no observed guard remain explicitly unverified. `route_state_boundary` repeats direct dispatch evidence and marks transitive state effects unverified. Top-level `state`/`evidence_status` describe source registration, not successful runtime behavior.

`test_coverage` distinguishes asserted operation tests from metadata-only selectors. Rows without an asserted operation test remain behaviorally unverified; registry parity alone does not satisfy handler request/response acceptance.

Each POST row links `tests/unit/test_canonical_http_routes.py::test_every_registered_post_route_authorizes_before_body_or_dispatch`, which checks that every registered path stops at the shared authorization gate before body parsing or dispatch when authorization fails. This common-gate test does not establish route-specific request/response parity; those operation contracts remain unverified until their own behavior tests exist.

## Generated catalog

`docs/API_COVERAGE.json` is the machine-readable catalog for the seven MCP tools, actions present in the generated schemas, and HTTP routes. It records source and test evidence, access classification, state, scope boundary, request and response contracts, required fields, limits, route targets, authorization identity, feature gates, and known contract gaps. `MCP action schema gap` rows identify dispatch names absent from the generated action enum; they are not exposed actions. `docs/API_COVERAGE.md` is its human-readable surface index.

The catalog is static source/test evidence. A field marked unverified or present in `contract_gaps` remains unknown; registration, schema parity, and source tests do not prove installed runtime behavior. Keep this distinction when extending or reviewing a route.

Regenerate both catalog files after public contract changes, then check for drift:

```powershell
python tools/surface_inventory.py --write-doc
python tools/surface_inventory.py --check
```

## Parity checks

`tests/test_operation_contracts.py` checks action schemas against runtime validation and MCP tool registration. `tests/test_http_route_operation_acceptance.py` exercises HTTP behavior; `tests/unit/test_canonical_http_routes.py` rejects retired aliases and checks route uniqueness. `tests/test_api_registry_documentation.py` checks that the generated catalog covers every registered MCP action and canonical POST route.
