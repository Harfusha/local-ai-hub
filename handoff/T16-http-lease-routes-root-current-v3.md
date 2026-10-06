# T16 HTTP lease routes root-current patch v3

Patch: `T16-http-lease-routes-root-current-v3.patch`
SHA-256: `954F126E34DC408F2AF8139E54033F88967EDC2DC072E94F627D70360CCC3AFE`
Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`
`src/local_ai_hub/http_server.py` preimage SHA-256: `94C44910B04F8909778F926E64D3F857975BAA5738B78979427BACE29AA3EDF3`
Candidate HTTP test SHA-256: `D560EC58FD1250881D6D9241D6B2C6CE8A0E119F87B1C9C1CE809D97954363C2`

GET lease list/waits and POST claim/batch derive namespace from server-side `ProjectContext.coordination_id`. Payload `coordination_id` is ignored. Namespace core v4 provides namespace-aware `ScopeLeaseStore` calls including `waits`; apply core v4 first. This patch owns only HTTP resolver imports/helper and those GET/POST callsites plus loopback acceptance test. It does not touch lease store, client/MCP, auth/frontdoor, production journal/T18, memory, or context-pack.

Strict composed `git apply --check --whitespace=error`: core v4 then route v3, pass. AST parse: 10 transformed Python files, pass. Candidate HTTP test is included in the 68-pass batch in core v4 manifest. No root writes; T20 owns integration.
