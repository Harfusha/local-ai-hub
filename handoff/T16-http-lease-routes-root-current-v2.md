# T16 HTTP lease routes root-current patch v2

Patch: `T16-http-lease-routes-root-current-v2.patch`
SHA-256: `BDEE8419215E3CD4B6EEF473BA41D10C588C9AD2A205FD9EF1D14D8CF7BCB5F3`
Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`
`src/local_ai_hub/http_server.py` preimage SHA-256: `94C44910B04F8909778F926E64D3F857975BAA5738B78979427BACE29AA3EDF3`
Candidate HTTP test SHA-256: `D560EC58FD1250881D6D9241D6B2C6CE8A0E119F87B1C9C1CE809D97954363C2`

GET lease list/waits and POST claim/batch derive namespace server-side. Client `coordination_id` is ignored. Namespace patch v4 supplies required `ScopeLeaseStore` namespace APIs and `waits(..., coordination_id=...)`; apply core v4 first. No lease-store, client, MCP, auth/frontdoor, journal/T18, memory, or context-pack hunk.

Strict `git apply --check --whitespace=error`: exit 0. Composed apply+AST receipt and candidate batch are in namespace v4 manifest. No root writes; T20 owns integration.
