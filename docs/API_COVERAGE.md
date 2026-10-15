# API surface coverage

Deterministic source inventory. Status describes static evidence, not runtime health or asserted behavior. Full contracts, fixtures, provenance, and coverage details live in `API_COVERAGE.json`.
Reproduce with `python tools/surface_inventory.py --check --task-id lead-remaining-bundle-20261015`.
<!-- coverage-task-id: lead-remaining-bundle-20261015 -->

| Surface | Name | Evidence status | Owner | Operation ID |
|---|---|---|---|---|
| MCP tool | local_ai_artifact | confirmed | src/local_ai_hub/mcp_server.py | op-727598168e6e |
| MCP tool | local_ai_command | confirmed | src/local_ai_hub/mcp_server.py | op-e283991aaee1 |
| MCP tool | local_ai_coord | confirmed | src/local_ai_hub/mcp_server.py | op-a9ceb516370a |
| MCP tool | local_ai_rag | confirmed | src/local_ai_hub/mcp_server.py | op-df42c60cdaf5 |
| MCP tool | local_ai_repo | confirmed | src/local_ai_hub/mcp_server.py | op-17700f5f21fd |
| MCP tool | local_ai_status | confirmed | src/local_ai_hub/mcp_server.py | op-0faf51b51ecf |
| MCP tool | local_ai_task | conditional | src/local_ai_hub/mcp_server.py | op-7a23fcfac359 |
| MCP tool | local_ai_work | conditional | src/local_ai_hub/mcp_server.py | op-03c0d96ee7cf |
| HTTP GET | / | conditional | src/local_ai_hub/http_server.py | op-800251923dac |
| HTTP GET | /api/adoption | confirmed | src/local_ai_hub/http_server.py | op-d7a085a0f07e |
| HTTP GET | /api/affected_tests | conditional | src/local_ai_hub/http_server.py | op-276bc14ce148 |
| HTTP GET | /api/agent-state/ | confirmed | src/local_ai_hub/http_server.py | op-d736c2ec2b2e |
| HTTP GET | /api/agent-state/blackboard | conditional | src/local_ai_hub/http_server.py | op-66a4a6771935 |
| HTTP GET | /api/agent-state/events | confirmed | src/local_ai_hub/http_server.py | op-dc35212819bb |
| HTTP GET | /api/agent-state/events/stream | conditional | src/local_ai_hub/http_server.py | op-f954480234c9 |
| HTTP GET | /api/agent-state/memory | conditional | src/local_ai_hub/http_server.py | op-d50cc5e721fb |
| HTTP GET | /api/agent-state/swarm | conditional | src/local_ai_hub/http_server.py | op-6668f590a0db |
| HTTP GET | /api/agent-state/swarm/ | conditional | src/local_ai_hub/http_server.py | op-394fd93d45c9 |
| HTTP GET | /api/agent-state/tasks | conditional | src/local_ai_hub/http_server.py | op-8a32e6e43634 |
| HTTP GET | /api/audit/tail | confirmed | src/local_ai_hub/http_server.py | op-8564f8460f97 |
| HTTP GET | /api/audit_dependencies | conditional | src/local_ai_hub/http_server.py | op-63f1b40f1ca1 |
| HTTP GET | /api/benchmark/summary | conditional | src/local_ai_hub/http_server.py | op-92275db2a76f |
| HTTP GET | /api/capabilities | confirmed | src/local_ai_hub/http_server.py | op-e3fae40c6831 |
| HTTP GET | /api/code/ | confirmed | src/local_ai_hub/http_server.py | op-f1c22c8db549 |
| HTTP GET | /api/code/ast_outline | conditional | src/local_ai_hub/http_server.py | op-b86b72558569 |
| HTTP GET | /api/code/diagnostics | confirmed | src/local_ai_hub/http_server.py | op-040fbf32e320 |
| HTTP GET | /api/code/find_declaration | confirmed | src/local_ai_hub/http_server.py | op-338ccba91da8 |
| HTTP GET | /api/code/find_implementations | confirmed | src/local_ai_hub/http_server.py | op-361d491676ae |
| HTTP GET | /api/code/find_referencing_symbols | confirmed | src/local_ai_hub/http_server.py | op-9f097cbb70ef |
| HTTP GET | /api/code/find_symbol | confirmed | src/local_ai_hub/http_server.py | op-f5decba7fa52 |
| HTTP GET | /api/code/symbol | confirmed | src/local_ai_hub/http_server.py | op-d67812412fdd |
| HTTP GET | /api/code/symbols_overview | confirmed | src/local_ai_hub/http_server.py | op-200f5d27bd7e |
| HTTP GET | /api/config | confirmed | src/local_ai_hub/http_server.py | op-3040f64daa5e |
| HTTP GET | /api/coord/worktrees | confirmed | src/local_ai_hub/http_server.py | op-45b35ecfad26 |
| HTTP GET | /api/cross_project_graph | conditional | src/local_ai_hub/http_server.py | op-28839eea6f3a |
| HTTP GET | /api/db/query | confirmed | src/local_ai_hub/http_server.py | op-411b0d6c8d7d |
| HTTP GET | /api/dead_code | conditional | src/local_ai_hub/http_server.py | op-ab65cb38a8d9 |
| HTTP GET | /api/debug-traces | confirmed | src/local_ai_hub/http_server.py | op-ed55074131ef |
| HTTP GET | /api/debug-traces/ | confirmed | src/local_ai_hub/http_server.py | op-f0df3c16f9f5 |
| HTTP GET | /api/doctor | confirmed | src/local_ai_hub/http_server.py | op-2020bc8dc3d7 |
| HTTP GET | /api/git/diff | conditional | src/local_ai_hub/http_server.py | op-17c7e91d83eb |
| HTTP GET | /api/git/history_search | conditional | src/local_ai_hub/http_server.py | op-7a1ad536c026 |
| HTTP GET | /api/git/status | conditional | src/local_ai_hub/http_server.py | op-24f2d752c5cc |
| HTTP GET | /api/git/synthesize_commit | conditional | src/local_ai_hub/http_server.py | op-dd694a634a57 |
| HTTP GET | /api/hardware/gpu | confirmed | src/local_ai_hub/http_server.py | op-de165174a0b1 |
| HTTP GET | /api/hardware/system | confirmed | src/local_ai_hub/http_server.py | op-78ed3cf2876b |
| HTTP GET | /api/leases | confirmed | src/local_ai_hub/http_server.py | op-0d024b687389 |
| HTTP GET | /api/live | confirmed | src/local_ai_hub/http_server.py | op-5d550dcacf01 |
| HTTP GET | /api/live/status | confirmed | src/local_ai_hub/http_server.py | op-4f432e2ad35d |
| HTTP GET | /api/logs/tail | confirmed | src/local_ai_hub/http_server.py | op-6440ec479251 |
| HTTP GET | /api/maintenance/optimize_db | confirmed | src/local_ai_hub/http_server.py | op-621bdf023080 |
| HTTP GET | /api/maintenance/purge_cache | confirmed | src/local_ai_hub/http_server.py | op-eb140867f439 |
| HTTP GET | /api/maintenance/resolve_errors | confirmed | src/local_ai_hub/http_server.py | op-89e99c8cb7f8 |
| HTTP GET | /api/metrics | confirmed | src/local_ai_hub/http_server.py | op-f940fc355dba |
| HTTP GET | /api/mode | confirmed | src/local_ai_hub/http_server.py | op-c34698465c20 |
| HTTP GET | /api/models | confirmed | src/local_ai_hub/http_server.py | op-1f2893c21fba |
| HTTP GET | /api/models/manage | confirmed | src/local_ai_hub/http_server.py | op-e572823b6bae |
| HTTP GET | /api/preprocess | confirmed | src/local_ai_hub/http_server.py | op-225c89bf0910 |
| HTTP GET | /api/preprocess/status | confirmed | src/local_ai_hub/http_server.py | op-311cd897fcfc |
| HTTP GET | /api/rag/workspaces | confirmed | src/local_ai_hub/http_server.py | op-dfdb6971e40c |
| HTTP GET | /api/refactor_impact | conditional | src/local_ai_hub/http_server.py | op-17da2f2b1a1d |
| HTTP GET | /api/repo/ | confirmed | src/local_ai_hub/http_server.py | op-6a713d7296a5 |
| HTTP GET | /api/repo/affected_tests | conditional | src/local_ai_hub/http_server.py | op-d7d905e14f41 |
| HTTP GET | /api/repo/dead_code | conditional | src/local_ai_hub/http_server.py | op-eb50388c805b |
| HTTP GET | /api/repo/state | confirmed | src/local_ai_hub/http_server.py | op-23e12164b1cf |
| HTTP GET | /api/repo/topology | conditional | src/local_ai_hub/http_server.py | op-ac7a6ee911b3 |
| HTTP GET | /api/repo_state | confirmed | src/local_ai_hub/http_server.py | op-d7314ccee6e4 |
| HTTP GET | /api/resolve_imports | conditional | src/local_ai_hub/http_server.py | op-849a83a5277e |
| HTTP GET | /api/security_audit | conditional | src/local_ai_hub/http_server.py | op-6480e3fe705e |
| HTTP GET | /api/status | confirmed | src/local_ai_hub/http_server.py | op-8a8e65599b16 |
| HTTP GET | /api/symbol_callgraph | conditional | src/local_ai_hub/http_server.py | op-0af87238df50 |
| HTTP GET | /api/telemetry/report | confirmed | src/local_ai_hub/http_server.py | op-ff27e5f93735 |
| HTTP GET | /api/telemetry/timeline | confirmed | src/local_ai_hub/http_server.py | op-d7ed59a7d1a4 |
| HTTP GET | /api/test_matrix | conditional | src/local_ai_hub/http_server.py | op-7e21dfa39869 |
| HTTP GET | /api/topology | conditional | src/local_ai_hub/http_server.py | op-c727be129853 |
| HTTP GET | /api/worktrees | confirmed | src/local_ai_hub/http_server.py | op-196f4e5b0242 |
| HTTP GET | /dashboard | conditional | src/local_ai_hub/http_server.py | op-f5f8517aa982 |
| HTTP GET | /favicon.ico | confirmed | src/local_ai_hub/http_server.py | op-85e915b2262e |
| HTTP GET | /health | confirmed | src/local_ai_hub/http_server.py | op-fdaca5a0d036 |
| HTTP GET | /ready | conditional | src/local_ai_hub/http_server.py | op-a5f57d02a8dd |
| HTTP OPTIONS | /api/browser/ | conditional | tools/surface_inventory.py | op-e354e9379c82 |
| HTTP OPTIONS | /api/vision/review | conditional | tools/surface_inventory.py | op-498bfb3d062d |
| HTTP POST | /api/admin/mode | confirmed | src/local_ai_hub/http_server.py | op-8bf1bb5e54e6 |
| HTTP POST | /api/agent-state/ | confirmed | src/local_ai_hub/http_server.py | op-ce9f5c2d1c47 |
| HTTP POST | /api/agent-state/blackboard | confirmed | src/local_ai_hub/http_server.py | op-cba9a800cd60 |
| HTTP POST | /api/agent-state/cleanup | confirmed | src/local_ai_hub/http_server.py | op-79a6996c295f |
| HTTP POST | /api/agent-state/context | confirmed | src/local_ai_hub/http_server.py | op-6329dad96448 |
| HTTP POST | /api/agent-state/events/delta | confirmed | src/local_ai_hub/http_server.py | op-1f8a135931ba |
| HTTP POST | /api/agent-state/incidents | confirmed | src/local_ai_hub/http_server.py | op-7b18455195d1 |
| HTTP POST | /api/agent-state/learning | confirmed | src/local_ai_hub/http_server.py | op-b25abfddc075 |
| HTTP POST | /api/agent-state/memory | confirmed | src/local_ai_hub/http_server.py | op-f47db64095c5 |
| HTTP POST | /api/agent-state/swarm/cancel | confirmed | src/local_ai_hub/http_server.py | op-4175b6a1f931 |
| HTTP POST | /api/agent-state/swarm/dispatch | confirmed | src/local_ai_hub/http_server.py | op-b1b285bc55a8 |
| HTTP POST | /api/agent-state/swarm/step | confirmed | src/local_ai_hub/http_server.py | op-9e0f81d1d7fb |
| HTTP POST | /api/agent-state/tasks | confirmed | src/local_ai_hub/http_server.py | op-847dedba74c4 |
| HTTP POST | /api/agent-state/verification | confirmed | src/local_ai_hub/http_server.py | op-c1d17599d3d9 |
| HTTP POST | /api/artifact/get | confirmed | src/local_ai_hub/http_server.py | op-4208c4f95ada |
| HTTP POST | /api/artifact/list | confirmed | src/local_ai_hub/http_server.py | op-5f24013f1564 |
| HTTP POST | /api/ast_rename | confirmed | src/local_ai_hub/http_server.py | op-5e1bd42312ad |
| HTTP POST | /api/async-jobs | confirmed | src/local_ai_hub/http_server.py | op-9c908d8a47ec |
| HTTP POST | /api/audit_dependencies | confirmed | src/local_ai_hub/http_server.py | op-b52980d206d4 |
| HTTP POST | /api/benchmark | confirmed | src/local_ai_hub/http_server.py | op-d2c3b35b0f60 |
| HTTP POST | /api/benchmark/run | confirmed | src/local_ai_hub/http_server.py | op-3c94f1f1187b |
| HTTP POST | /api/browser/capability | confirmed | src/local_ai_hub/http_server.py | op-0da83b58049e |
| HTTP POST | /api/browser/capture | confirmed | src/local_ai_hub/http_server.py | op-fc062f29cc19 |
| HTTP POST | /api/browser/capture/abandon | confirmed | src/local_ai_hub/http_server.py | op-7cd3d27a3948 |
| HTTP POST | /api/browser/capture/commit | confirmed | src/local_ai_hub/http_server.py | op-483376ef8eb5 |
| HTTP POST | /api/browser/capture/stage | confirmed | src/local_ai_hub/http_server.py | op-4d1662739283 |
| HTTP POST | /api/bundle/export | confirmed | src/local_ai_hub/http_server.py | op-21ec1373e039 |
| HTTP POST | /api/bundle/import | confirmed | src/local_ai_hub/http_server.py | op-e64c615a36e2 |
| HTTP POST | /api/chat | confirmed | src/local_ai_hub/http_server.py | op-168f9dbce8b8 |
| HTTP POST | /api/code-intelligence/control | confirmed | src/local_ai_hub/http_server.py | op-630137102c4b |
| HTTP POST | /api/code-intelligence/query | confirmed | src/local_ai_hub/http_server.py | op-ef992b94de5b |
| HTTP POST | /api/code/ | confirmed | src/local_ai_hub/http_server.py | op-9d31b4f0bf67 |
| HTTP POST | /api/code/ast_outline | confirmed | src/local_ai_hub/http_server.py | op-8cdf62b97a2a |
| HTTP POST | /api/code/ast_rename | confirmed | src/local_ai_hub/http_server.py | op-9a568ca9a62b |
| HTTP POST | /api/code/batch_replace | confirmed | src/local_ai_hub/http_server.py | op-11a0e1ab4ae7 |
| HTTP POST | /api/code/callees | confirmed | src/local_ai_hub/http_server.py | op-a1aaebfd635a |
| HTTP POST | /api/code/declaration | confirmed | src/local_ai_hub/http_server.py | op-b888832c746b |
| HTTP POST | /api/code/diagnostics | confirmed | src/local_ai_hub/http_server.py | op-a80e54057076 |
| HTTP POST | /api/code/find_declaration | confirmed | src/local_ai_hub/http_server.py | op-19432aa6f94b |
| HTTP POST | /api/code/find_implementations | confirmed | src/local_ai_hub/http_server.py | op-9d649e5eea89 |
| HTTP POST | /api/code/find_referencing_symbols | confirmed | src/local_ai_hub/http_server.py | op-4d80ce82548a |
| HTTP POST | /api/code/find_symbol | confirmed | src/local_ai_hub/http_server.py | op-b42b9b6e3ebc |
| HTTP POST | /api/code/generate_mocks | confirmed | src/local_ai_hub/http_server.py | op-2688077c92bc |
| HTTP POST | /api/code/implementations | confirmed | src/local_ai_hub/http_server.py | op-899e8619ee36 |
| HTTP POST | /api/code/symbol | confirmed | src/local_ai_hub/http_server.py | op-ebdc3e262b0d |
| HTTP POST | /api/code/symbols_overview | confirmed | src/local_ai_hub/http_server.py | op-5baa502b7efb |
| HTTP POST | /api/code_invariants | confirmed | src/local_ai_hub/http_server.py | op-1fcdb085e7a7 |
| HTTP POST | /api/command | confirmed | src/local_ai_hub/http_server.py | op-24fe5fc51c7c |
| HTTP POST | /api/command/daemon | confirmed | src/local_ai_hub/http_server.py | op-2b9bc7b00779 |
| HTTP POST | /api/command/diff_hunk_stage | confirmed | src/local_ai_hub/http_server.py | op-d41d3f037ca2 |
| HTTP POST | /api/command/flaky_detect | confirmed | src/local_ai_hub/http_server.py | op-bcd42b64552d |
| HTTP POST | /api/command/http_probe | confirmed | src/local_ai_hub/http_server.py | op-f508ad854097 |
| HTTP POST | /api/command/lint_fix | confirmed | src/local_ai_hub/http_server.py | op-ffc0ff8f6ea6 |
| HTTP POST | /api/command/mock_server | confirmed | src/local_ai_hub/http_server.py | op-21e2955a8e85 |
| HTTP POST | /api/command/preflight | confirmed | src/local_ai_hub/http_server.py | op-9d27ad3768b2 |
| HTTP POST | /api/command/speculative-lint | confirmed | src/local_ai_hub/http_server.py | op-d310ded36aea |
| HTTP POST | /api/command/webhook_replay | confirmed | src/local_ai_hub/http_server.py | op-172b371484b4 |
| HTTP POST | /api/complete | confirmed | src/local_ai_hub/http_server.py | op-236704d6d750 |
| HTTP POST | /api/compress | confirmed | src/local_ai_hub/http_server.py | op-26dfb66d8890 |
| HTTP POST | /api/config/update | confirmed | src/local_ai_hub/http_server.py | op-ff52947bcad7 |
| HTTP POST | /api/context/pack | conditional | tools/surface_inventory.py | op-bc749f02b288 |
| HTTP POST | /api/conversations/continue | confirmed | src/local_ai_hub/http_server.py | op-39cb63957f93 |
| HTTP POST | /api/coord/pubsub_poll | confirmed | src/local_ai_hub/http_server.py | op-db9bf332043e |
| HTTP POST | /api/coord/pubsub_publish | confirmed | src/local_ai_hub/http_server.py | op-746da2e62465 |
| HTTP POST | /api/coord/simulate_merge | confirmed | src/local_ai_hub/http_server.py | op-5bd15143db41 |
| HTTP POST | /api/coord/worktree_lease | confirmed | src/local_ai_hub/http_server.py | op-2d8f98fca770 |
| HTTP POST | /api/coord/worktree_prune | confirmed | src/local_ai_hub/http_server.py | op-a4b060cb7fe2 |
| HTTP POST | /api/coord/worktree_release | confirmed | src/local_ai_hub/http_server.py | op-b1fcb8539149 |
| HTTP POST | /api/coord/worktrees | confirmed | src/local_ai_hub/http_server.py | op-2d46ce218564 |
| HTTP POST | /api/cross_project_graph | confirmed | src/local_ai_hub/http_server.py | op-a61cf80dee38 |
| HTTP POST | /api/cross_project_impact | confirmed | src/local_ai_hub/http_server.py | op-d9106a2518d1 |
| HTTP POST | /api/cross_project_symbols | confirmed | src/local_ai_hub/http_server.py | op-c7dc72b3b4cb |
| HTTP POST | /api/cross_repo_contract | confirmed | src/local_ai_hub/http_server.py | op-740fe3ca36c6 |
| HTTP POST | /api/db/query | confirmed | src/local_ai_hub/http_server.py | op-6de9fa7594c4 |
| HTTP POST | /api/delegate | confirmed | src/local_ai_hub/http_server.py | op-d5d8bbdc9bea |
| HTTP POST | /api/delegate/batch | confirmed | src/local_ai_hub/http_server.py | op-35a099bc5a33 |
| HTTP POST | /api/delegate/repo | confirmed | src/local_ai_hub/http_server.py | op-5ec20d3d74e7 |
| HTTP POST | /api/doctor | confirmed | src/local_ai_hub/http_server.py | op-5bbbe6a2bd65 |
| HTTP POST | /api/embed | confirmed | src/local_ai_hub/http_server.py | op-a3c592c8f3ad |
| HTTP POST | /api/evaluation | confirmed | src/local_ai_hub/http_server.py | op-948b0c8e50c7 |
| HTTP POST | /api/evidence/get | confirmed | src/local_ai_hub/http_server.py | op-6469ce742fd0 |
| HTTP POST | /api/evidence/verify | confirmed | src/local_ai_hub/http_server.py | op-44b829747b5f |
| HTTP POST | /api/generate | confirmed | src/local_ai_hub/http_server.py | op-2ea8e56e70e5 |
| HTTP POST | /api/generate_tests | confirmed | src/local_ai_hub/http_server.py | op-38bfd0cee347 |
| HTTP POST | /api/git/diff | confirmed | src/local_ai_hub/http_server.py | op-3631e7d6a1f4 |
| HTTP POST | /api/git/history_search | confirmed | src/local_ai_hub/http_server.py | op-f94556281c61 |
| HTTP POST | /api/git/status | confirmed | src/local_ai_hub/http_server.py | op-32774709009e |
| HTTP POST | /api/git/synthesize_commit | confirmed | src/local_ai_hub/http_server.py | op-99533a46fb0e |
| HTTP POST | /api/leases/claim | confirmed | src/local_ai_hub/http_server.py | op-17f5543afb5b |
| HTTP POST | /api/leases/claim_batch | confirmed | src/local_ai_hub/http_server.py | op-cf5ba5179dc2 |
| HTTP POST | /api/leases/release | confirmed | src/local_ai_hub/http_server.py | op-4d2be6d29bd6 |
| HTTP POST | /api/leases/renew | confirmed | src/local_ai_hub/http_server.py | op-f15fb6fced56 |
| HTTP POST | /api/maintenance/optimize_db | confirmed | src/local_ai_hub/http_server.py | op-8974a873ebe3 |
| HTTP POST | /api/maintenance/purge_cache | confirmed | src/local_ai_hub/http_server.py | op-0d0d6f0e1bd8 |
| HTTP POST | /api/maintenance/resolve_errors | confirmed | src/local_ai_hub/http_server.py | op-b5d302dc5a8c |
| HTTP POST | /api/memory/ | confirmed | src/local_ai_hub/http_server.py | op-ebab65c87315 |
| HTTP POST | /api/memory/delete | confirmed | src/local_ai_hub/http_server.py | op-26b47beb3268 |
| HTTP POST | /api/memory/get | confirmed | src/local_ai_hub/http_server.py | op-4b6bcb3a0737 |
| HTTP POST | /api/memory/put | confirmed | src/local_ai_hub/http_server.py | op-44a091a9353f |
| HTTP POST | /api/memory/search | confirmed | src/local_ai_hub/http_server.py | op-30f4c47cd58f |
| HTTP POST | /api/models/manage | confirmed | src/local_ai_hub/http_server.py | op-5b6baefe1fcd |
| HTTP POST | /api/patch/validate | confirmed | src/local_ai_hub/http_server.py | op-032c78505fe5 |
| HTTP POST | /api/preprocess | confirmed | src/local_ai_hub/http_server.py | op-4318c2dfdc9c |
| HTTP POST | /api/query/expand | confirmed | src/local_ai_hub/http_server.py | op-f2e4b1cd8a58 |
| HTTP POST | /api/rag/docset/index | confirmed | src/local_ai_hub/http_server.py | op-8b5c15226eaf |
| HTTP POST | /api/rag/docset/search | confirmed | src/local_ai_hub/http_server.py | op-ec2aed3d6a86 |
| HTTP POST | /api/rag/index | confirmed | src/local_ai_hub/http_server.py | op-461b823e9a3a |
| HTTP POST | /api/rag/ingest_diagram | confirmed | src/local_ai_hub/http_server.py | op-2c5367726108 |
| HTTP POST | /api/rag/ingest_document | confirmed | src/local_ai_hub/http_server.py | op-4a5d02312e02 |
| HTTP POST | /api/rag/search | confirmed | src/local_ai_hub/http_server.py | op-0d17f1f3c8b3 |
| HTTP POST | /api/reason | confirmed | src/local_ai_hub/http_server.py | op-751b82cfcb27 |
| HTTP POST | /api/refactor_impact | confirmed | src/local_ai_hub/http_server.py | op-32240eb7fe8c |
| HTTP POST | /api/repo/ | confirmed | src/local_ai_hub/http_server.py | op-2c2f653e5c18 |
| HTTP POST | /api/repo/affected_tests | confirmed | src/local_ai_hub/http_server.py | op-4d9d7656cce3 |
| HTTP POST | /api/repo/api_spec | confirmed | src/local_ai_hub/http_server.py | op-25f1bcf44587 |
| HTTP POST | /api/repo/batch_replace | confirmed | src/local_ai_hub/http_server.py | op-751f0b413fb2 |
| HTTP POST | /api/repo/briefing | confirmed | src/local_ai_hub/http_server.py | op-2901610d221a |
| HTTP POST | /api/repo/call_graph_diff | confirmed | src/local_ai_hub/http_server.py | op-90212203ef29 |
| HTTP POST | /api/repo/callers | confirmed | src/local_ai_hub/http_server.py | op-5b7380bc03a3 |
| HTTP POST | /api/repo/circular_dependencies | confirmed | src/local_ai_hub/http_server.py | op-a30452be984f |
| HTTP POST | /api/repo/code-index | confirmed | src/local_ai_hub/http_server.py | op-142c5f32371e |
| HTTP POST | /api/repo/code_invariants | confirmed | src/local_ai_hub/http_server.py | op-656c9e199f19 |
| HTTP POST | /api/repo/complexity | confirmed | src/local_ai_hub/http_server.py | op-431b8d6ed7e5 |
| HTTP POST | /api/repo/context_budget | confirmed | src/local_ai_hub/http_server.py | op-2db8b276c10d |
| HTTP POST | /api/repo/cross_repo_contract | confirmed | src/local_ai_hub/http_server.py | op-71aa24ce17e3 |
| HTTP POST | /api/repo/dead_code | confirmed | src/local_ai_hub/http_server.py | op-4317da7ae74f |
| HTTP POST | /api/repo/dependency_slice | confirmed | src/local_ai_hub/http_server.py | op-c2de646aa066 |
| HTTP POST | /api/repo/deterministic | confirmed | src/local_ai_hub/http_server.py | op-9d5f3c4fdff0 |
| HTTP POST | /api/repo/diagnose | confirmed | src/local_ai_hub/http_server.py | op-4a46069bdec3 |
| HTTP POST | /api/repo/env_compat | confirmed | src/local_ai_hub/http_server.py | op-01f8620e3ade |
| HTTP POST | /api/repo/explain_query | confirmed | src/local_ai_hub/http_server.py | op-3be355584f66 |
| HTTP POST | /api/repo/generate_dataset | confirmed | src/local_ai_hub/http_server.py | op-3719d2cc84e0 |
| HTTP POST | /api/repo/generate_tests_for_diff | confirmed | src/local_ai_hub/http_server.py | op-f98bc953cbe1 |
| HTTP POST | /api/repo/generate_types | confirmed | src/local_ai_hub/http_server.py | op-6bc8a3978734 |
| HTTP POST | /api/repo/hotspots | confirmed | src/local_ai_hub/http_server.py | op-8f1284076a73 |
| HTTP POST | /api/repo/impact | confirmed | src/local_ai_hub/http_server.py | op-fa743531dea7 |
| HTTP POST | /api/repo/investigate | confirmed | src/local_ai_hub/http_server.py | op-165f8f13c2d9 |
| HTTP POST | /api/repo/map | confirmed | src/local_ai_hub/http_server.py | op-818aacd7413b |
| HTTP POST | /api/repo/migration_drift | confirmed | src/local_ai_hub/http_server.py | op-526633e15c34 |
| HTTP POST | /api/repo/mutation_test | confirmed | src/local_ai_hub/http_server.py | op-1a92aa96c72c |
| HTTP POST | /api/repo/package_audit | confirmed | src/local_ai_hub/http_server.py | op-7f4df4971c79 |
| HTTP POST | /api/repo/profile | confirmed | src/local_ai_hub/http_server.py | op-207799541073 |
| HTTP POST | /api/repo/profile_digest | confirmed | src/local_ai_hub/http_server.py | op-3908ce63a73b |
| HTTP POST | /api/repo/reachability_dead_code | confirmed | src/local_ai_hub/http_server.py | op-0e330665cdc0 |
| HTTP POST | /api/repo/schema_inspect | confirmed | src/local_ai_hub/http_server.py | op-fb0030056179 |
| HTTP POST | /api/repo/secret_scan | confirmed | src/local_ai_hub/http_server.py | op-8c93b8bf6227 |
| HTTP POST | /api/repo/skeletonize | confirmed | src/local_ai_hub/http_server.py | op-37d6251d6d16 |
| HTTP POST | /api/repo/split_changes | confirmed | src/local_ai_hub/http_server.py | op-3c7e123e15dc |
| HTTP POST | /api/repo/state | confirmed | src/local_ai_hub/http_server.py | op-013ed2437667 |
| HTTP POST | /api/repo/structural_search | confirmed | src/local_ai_hub/http_server.py | op-476e8fff5822 |
| HTTP POST | /api/repo/synthesize_rules | confirmed | src/local_ai_hub/http_server.py | op-0c2641994a62 |
| HTTP POST | /api/repo/topology | confirmed | src/local_ai_hub/http_server.py | op-ad2b9b07bba6 |
| HTTP POST | /api/repo/type_stubs | confirmed | src/local_ai_hub/http_server.py | op-19e807602695 |
| HTTP POST | /api/rerank | confirmed | src/local_ai_hub/http_server.py | op-fce52e024a61 |
| HTTP POST | /api/resolve_imports | confirmed | src/local_ai_hub/http_server.py | op-709bba7ad8f5 |
| HTTP POST | /api/review | confirmed | src/local_ai_hub/http_server.py | op-5925b89cf9bc |
| HTTP POST | /api/review/diff | confirmed | src/local_ai_hub/http_server.py | op-4d46d5b43f08 |
| HTTP POST | /api/route | confirmed | src/local_ai_hub/http_server.py | op-683311644cc7 |
| HTTP POST | /api/search | confirmed | src/local_ai_hub/http_server.py | op-1b8b48a627d1 |
| HTTP POST | /api/second-opinion | confirmed | src/local_ai_hub/http_server.py | op-ebb2ebe6e140 |
| HTTP POST | /api/security_audit | confirmed | src/local_ai_hub/http_server.py | op-81f33acaf3d8 |
| HTTP POST | /api/solve/repo | confirmed | src/local_ai_hub/http_server.py | op-2a606207787c |
| HTTP POST | /api/symbol_callgraph | confirmed | src/local_ai_hub/http_server.py | op-e58ad68dbffe |
| HTTP POST | /api/task/browser | confirmed | src/local_ai_hub/http_server.py | op-8948761a660a |
| HTTP POST | /api/task/eval_drift | confirmed | src/local_ai_hub/http_server.py | op-40f51c7256fd |
| HTTP POST | /api/task/eval_suite | confirmed | src/local_ai_hub/http_server.py | op-3c25b5fcf1cb |
| HTTP POST | /api/task/prompt_eval | confirmed | src/local_ai_hub/http_server.py | op-ee30a1d36abb |
| HTTP POST | /api/task/scaffold | confirmed | src/local_ai_hub/http_server.py | op-8e48dce85c3b |
| HTTP POST | /api/task/speculative_draft | confirmed | src/local_ai_hub/http_server.py | op-63d4015d6f27 |
| HTTP POST | /api/task/transcribe | confirmed | src/local_ai_hub/http_server.py | op-65970ac00a0a |
| HTTP POST | /api/task/vision | confirmed | src/local_ai_hub/http_server.py | op-27447492b0ba |
| HTTP POST | /api/telemetry/timeline | confirmed | src/local_ai_hub/http_server.py | op-e7c38a4c7425 |
| HTTP POST | /api/telemetry/tool-accounting | confirmed | src/local_ai_hub/http_server.py | op-04438ec90d60 |
| HTTP POST | /api/test_matrix | confirmed | src/local_ai_hub/http_server.py | op-1321702d7984 |
| HTTP POST | /api/vision | confirmed | src/local_ai_hub/http_server.py | op-8a27267bb6c5 |
| HTTP POST | /api/vision/review | confirmed | src/local_ai_hub/http_server.py | op-e81bbd33a8df |
| HTTP POST | /api/work-orders | confirmed | src/local_ai_hub/http_server.py | op-44a15019a847 |
| MCP action local_ai_artifact | get | confirmed | src/local_ai_hub/generator.py | op-9d00ab4f0eec |
| MCP action local_ai_artifact | list | confirmed | src/local_ai_hub/generator.py | op-901c14322762 |
| MCP action local_ai_artifact | slice | confirmed | src/local_ai_hub/generator.py | op-04d682da59b8 |
| MCP action local_ai_artifact | source | confirmed | src/local_ai_hub/generator.py | op-2a9d5f41932c |
| MCP action local_ai_command | auto_fix | confirmed | src/local_ai_hub/generator.py | op-c16afcb00031 |
| MCP action local_ai_command | cancel | confirmed | src/local_ai_hub/generator.py | op-8f9cbdeb7838 |
| MCP action local_ai_command | classify | confirmed | src/local_ai_hub/generator.py | op-8c646c51607a |
| MCP action local_ai_command | daemon_status | confirmed | src/local_ai_hub/generator.py | op-52ad5f254baf |
| MCP action local_ai_command | diff_hunk_stage | confirmed | src/local_ai_hub/generator.py | op-95ba43dadfda |
| MCP action local_ai_command | discover | confirmed | src/local_ai_hub/generator.py | op-c760b663e705 |
| MCP action local_ai_command | flaky_detect | confirmed | src/local_ai_hub/generator.py | op-064e8d7e0308 |
| MCP action local_ai_command | format | confirmed | src/local_ai_hub/generator.py | op-84a3e533c2da |
| MCP action local_ai_command | http_probe | confirmed | src/local_ai_hub/generator.py | op-346992b617da |
| MCP action local_ai_command | lint_fix | confirmed | src/local_ai_hub/generator.py | op-9785529b4be2 |
| MCP action local_ai_command | mock_server | confirmed | src/local_ai_hub/generator.py | op-e2794dc2eccd |
| MCP action local_ai_command | mock_server_start | confirmed | src/local_ai_hub/generator.py | op-83eaba09cb3e |
| MCP action local_ai_command | mock_server_status | confirmed | src/local_ai_hub/generator.py | op-33527d83c989 |
| MCP action local_ai_command | mock_server_stop | confirmed | src/local_ai_hub/generator.py | op-b78f60063af9 |
| MCP action local_ai_command | patch_and_verify | confirmed | src/local_ai_hub/generator.py | op-f218da19614a |
| MCP action local_ai_command | preflight | confirmed | src/local_ai_hub/generator.py | op-a88baeba8d5f |
| MCP action local_ai_command | record_mock | confirmed | src/local_ai_hub/generator.py | op-efc55f2c2b83 |
| MCP action local_ai_command | repair_loop | confirmed | src/local_ai_hub/generator.py | op-4401d1b8652c |
| MCP action local_ai_command | replay_mock | confirmed | src/local_ai_hub/generator.py | op-554f97a5f960 |
| MCP action local_ai_command | run | confirmed | src/local_ai_hub/generator.py | op-7efad8c86c85 |
| MCP action local_ai_command | run_affected | confirmed | src/local_ai_hub/generator.py | op-413eed45a80f |
| MCP action local_ai_command | spawn_daemon | confirmed | src/local_ai_hub/generator.py | op-41dfaff06094 |
| MCP action local_ai_command | stash_restore | confirmed | src/local_ai_hub/generator.py | op-d9fd4eb82431 |
| MCP action local_ai_command | stash_save | confirmed | src/local_ai_hub/generator.py | op-d52cd6c302b0 |
| MCP action local_ai_command | stats | confirmed | src/local_ai_hub/generator.py | op-411169a33548 |
| MCP action local_ai_command | stop_daemon | confirmed | src/local_ai_hub/generator.py | op-5b53e1c4c62b |
| MCP action local_ai_command | webhook_replay | confirmed | src/local_ai_hub/generator.py | op-d05fcd00013e |
| MCP action local_ai_coord | answer | confirmed | src/local_ai_hub/generator.py | op-428e09b083ce |
| MCP action local_ai_coord | ask | confirmed | src/local_ai_hub/generator.py | op-b8a2064bab16 |
| MCP action local_ai_coord | blackboard_delete | confirmed | src/local_ai_hub/generator.py | op-2d04626be1a8 |
| MCP action local_ai_coord | blackboard_get | confirmed | src/local_ai_hub/generator.py | op-b6818d96d166 |
| MCP action local_ai_coord | blackboard_list | confirmed | src/local_ai_hub/generator.py | op-d138e229e2bb |
| MCP action local_ai_coord | blackboard_merge | confirmed | src/local_ai_hub/generator.py | op-3733f6a6f447 |
| MCP action local_ai_coord | blackboard_update | confirmed | src/local_ai_hub/generator.py | op-eaf280d32e3e |
| MCP action local_ai_coord | claim | confirmed | src/local_ai_hub/generator.py | op-d75292991551 |
| MCP action local_ai_coord | context_compile | confirmed | src/local_ai_hub/generator.py | op-145b6332056b |
| MCP action local_ai_coord | curate_dataset | confirmed | src/local_ai_hub/generator.py | op-26aa09a9ccbf |
| MCP action local_ai_coord | incident_decision | confirmed | src/local_ai_hub/generator.py | op-0d8149da9907 |
| MCP action local_ai_coord | leases | confirmed | src/local_ai_hub/generator.py | op-10fac56595f4 |
| MCP action local_ai_coord | memo_delete | confirmed | src/local_ai_hub/generator.py | op-9c74d0b95011 |
| MCP action local_ai_coord | memo_get | confirmed | src/local_ai_hub/generator.py | op-1cdb78efa2f3 |
| MCP action local_ai_coord | memo_put | confirmed | src/local_ai_hub/generator.py | op-8d8063a2287d |
| MCP action local_ai_coord | memo_search | confirmed | src/local_ai_hub/generator.py | op-19920d549411 |
| MCP action local_ai_coord | memory_find | confirmed | src/local_ai_hub/generator.py | op-0a673cc2e7e9 |
| MCP action local_ai_coord | memory_get | confirmed | src/local_ai_hub/generator.py | op-4c0cbfa154c1 |
| MCP action local_ai_coord | memory_promote | confirmed | src/local_ai_hub/generator.py | op-b0904bf92e19 |
| MCP action local_ai_coord | memory_record | confirmed | src/local_ai_hub/generator.py | op-90b617e52e5c |
| MCP action local_ai_coord | negative_knowledge_find | confirmed | src/local_ai_hub/generator.py | op-d40ecfa5c1c9 |
| MCP action local_ai_coord | negative_knowledge_record | confirmed | src/local_ai_hub/generator.py | op-e7f297ebbc4d |
| MCP action local_ai_coord | pubsub_poll | confirmed | src/local_ai_hub/generator.py | op-2a393f87a6eb |
| MCP action local_ai_coord | pubsub_publish | confirmed | src/local_ai_hub/generator.py | op-436f8605eb22 |
| MCP action local_ai_coord | release | confirmed | src/local_ai_hub/generator.py | op-d77f5aff73c4 |
| MCP action local_ai_coord | renew | confirmed | src/local_ai_hub/generator.py | op-7065e2d1e344 |
| MCP action local_ai_coord | simulate_merge | confirmed | src/local_ai_hub/generator.py | op-9f0ecd3e5dbb |
| MCP action local_ai_coord | swarm_cancel | confirmed | src/local_ai_hub/generator.py | op-01da28d0ec7c |
| MCP action local_ai_coord | swarm_dispatch | confirmed | src/local_ai_hub/generator.py | op-c0c2faa4be1a |
| MCP action local_ai_coord | swarm_list | confirmed | src/local_ai_hub/generator.py | op-7511f0cfcbe8 |
| MCP action local_ai_coord | swarm_status | confirmed | src/local_ai_hub/generator.py | op-a6b9790e10f8 |
| MCP action local_ai_coord | swarm_step | confirmed | src/local_ai_hub/generator.py | op-ab9f50ea291b |
| MCP action local_ai_coord | task_checkpoint | confirmed | src/local_ai_hub/generator.py | op-597632737a1f |
| MCP action local_ai_coord | task_cleanup_worktree | confirmed | src/local_ai_hub/generator.py | op-48c2398729cc |
| MCP action local_ai_coord | task_complete | confirmed | src/local_ai_hub/generator.py | op-c5b7430e6e19 |
| MCP action local_ai_coord | task_create | confirmed | src/local_ai_hub/generator.py | op-34f6791b0c99 |
| MCP action local_ai_coord | task_fail | confirmed | src/local_ai_hub/generator.py | op-111868a18974 |
| MCP action local_ai_coord | task_get | confirmed | src/local_ai_hub/generator.py | op-bd20e27acd1a |
| MCP action local_ai_coord | task_heartbeat | confirmed | src/local_ai_hub/generator.py | op-a0abff80393c |
| MCP action local_ai_coord | task_list | confirmed | src/local_ai_hub/generator.py | op-8151f0572cf1 |
| MCP action local_ai_coord | task_resume | confirmed | src/local_ai_hub/generator.py | op-58eeef28cc8a |
| MCP action local_ai_coord | task_rollback | confirmed | src/local_ai_hub/generator.py | op-28d63e90525c |
| MCP action local_ai_coord | task_sync | confirmed | src/local_ai_hub/generator.py | op-2369ca3978a2 |
| MCP action local_ai_coord | task_transition | confirmed | src/local_ai_hub/generator.py | op-40714898d9dc |
| MCP action local_ai_coord | task_zombie_reap | confirmed | src/local_ai_hub/generator.py | op-12f589687cee |
| MCP action local_ai_coord | verify_completion | confirmed | src/local_ai_hub/generator.py | op-ce3412a5a09a |
| MCP action local_ai_coord | verify_export | confirmed | src/local_ai_hub/generator.py | op-5b7da10041a2 |
| MCP action local_ai_coord | verify_receipt | confirmed | src/local_ai_hub/generator.py | op-e79085266755 |
| MCP action local_ai_coord | worktree_lease | confirmed | src/local_ai_hub/generator.py | op-988171287b30 |
| MCP action local_ai_coord | worktree_release | confirmed | src/local_ai_hub/generator.py | op-fe922ffcaf1a |
| MCP action local_ai_rag | docset_index | confirmed | src/local_ai_hub/generator.py | op-56fa3d2b5426 |
| MCP action local_ai_rag | docset_search | confirmed | src/local_ai_hub/generator.py | op-296b3132f53e |
| MCP action local_ai_rag | index | confirmed | src/local_ai_hub/generator.py | op-4744c4d9beff |
| MCP action local_ai_rag | ingest_diagram | confirmed | src/local_ai_hub/generator.py | op-a498de320401 |
| MCP action local_ai_rag | ingest_document | confirmed | src/local_ai_hub/generator.py | op-16a7dbf63dba |
| MCP action local_ai_rag | list | confirmed | src/local_ai_hub/generator.py | op-b2b613c22314 |
| MCP action local_ai_rag | search | confirmed | src/local_ai_hub/generator.py | op-d2a8a2919302 |
| MCP action local_ai_repo | affected_tests | confirmed | src/local_ai_hub/generator.py | op-2ba38125ca09 |
| MCP action local_ai_repo | api_spec | confirmed | src/local_ai_hub/generator.py | op-ce603c89ab68 |
| MCP action local_ai_repo | ast_outline | confirmed | src/local_ai_hub/generator.py | op-7cd8d96208cc |
| MCP action local_ai_repo | ast_refactor | confirmed | src/local_ai_hub/generator.py | op-555ad85e0a95 |
| MCP action local_ai_repo | audit_dependencies | confirmed | src/local_ai_hub/generator.py | op-afcf8eabc20e |
| MCP action local_ai_repo | batch_replace | confirmed | src/local_ai_hub/generator.py | op-a0f13b3d4716 |
| MCP action local_ai_repo | briefing | confirmed | src/local_ai_hub/generator.py | op-c82fbf325a14 |
| MCP action local_ai_repo | call_graph_diff | confirmed | src/local_ai_hub/generator.py | op-545604db0a99 |
| MCP action local_ai_repo | callees | confirmed | src/local_ai_hub/generator.py | op-a73a0b705bc6 |
| MCP action local_ai_repo | callers | confirmed | src/local_ai_hub/generator.py | op-146536887070 |
| MCP action local_ai_repo | circular_dependencies | confirmed | src/local_ai_hub/generator.py | op-25376f814812 |
| MCP action local_ai_repo | code_index | confirmed | src/local_ai_hub/generator.py | op-0f729b27d60f |
| MCP action local_ai_repo | code_invariants | confirmed | src/local_ai_hub/generator.py | op-9351a713dd98 |
| MCP action local_ai_repo | complexity | confirmed | src/local_ai_hub/generator.py | op-32c3a8859532 |
| MCP action local_ai_repo | context | confirmed | src/local_ai_hub/generator.py | op-2f4f656e18c7 |
| MCP action local_ai_repo | context_budget | confirmed | src/local_ai_hub/generator.py | op-27386c2455aa |
| MCP action local_ai_repo | context_compile | confirmed | src/local_ai_hub/generator.py | op-b03cd7d74967 |
| MCP action local_ai_repo | cross_project_graph | confirmed | src/local_ai_hub/generator.py | op-811b02965b2c |
| MCP action local_ai_repo | cross_project_impact | confirmed | src/local_ai_hub/generator.py | op-365305280163 |
| MCP action local_ai_repo | cross_project_symbols | confirmed | src/local_ai_hub/generator.py | op-63f781fb57b7 |
| MCP action local_ai_repo | cross_repo_contract | confirmed | src/local_ai_hub/generator.py | op-235c77a0f8b6 |
| MCP action local_ai_repo | dead_code | confirmed | src/local_ai_hub/generator.py | op-ad77f70411ee |
| MCP action local_ai_repo | declaration | confirmed | src/local_ai_hub/generator.py | op-30232bb73a3f |
| MCP action local_ai_repo | delegate | confirmed | src/local_ai_hub/generator.py | op-45794746f756 |
| MCP action local_ai_repo | dependency_slice | confirmed | src/local_ai_hub/generator.py | op-e630a70c8f9f |
| MCP action local_ai_repo | deterministic | confirmed | src/local_ai_hub/generator.py | op-8deb0567f819 |
| MCP action local_ai_repo | diagnose | confirmed | src/local_ai_hub/generator.py | op-655fc75fc2bb |
| MCP action local_ai_repo | env_compat | confirmed | src/local_ai_hub/generator.py | op-b8dbb57fa46b |
| MCP action local_ai_repo | explain_query | confirmed | src/local_ai_hub/generator.py | op-c6bdeb575963 |
| MCP action local_ai_repo | generate_dataset | confirmed | src/local_ai_hub/generator.py | op-134b45ead4bd |
| MCP action local_ai_repo | generate_mocks | confirmed | src/local_ai_hub/generator.py | op-73bca8ccc95e |
| MCP action local_ai_repo | generate_tests | confirmed | src/local_ai_hub/generator.py | op-1c407e4109c5 |
| MCP action local_ai_repo | generate_tests_for_diff | confirmed | src/local_ai_hub/generator.py | op-41aaf1d08562 |
| MCP action local_ai_repo | generate_types | confirmed | src/local_ai_hub/generator.py | op-6ceda8616f2e |
| MCP action local_ai_repo | git_diff | confirmed | src/local_ai_hub/generator.py | op-b766ebbbf04b |
| MCP action local_ai_repo | git_history_search | confirmed | src/local_ai_hub/generator.py | op-c3cc602a4fef |
| MCP action local_ai_repo | git_status | confirmed | src/local_ai_hub/generator.py | op-233e6987ed02 |
| MCP action local_ai_repo | hotspots | confirmed | src/local_ai_hub/generator.py | op-d5076c1bc37b |
| MCP action local_ai_repo | impact | confirmed | src/local_ai_hub/generator.py | op-81951f17c43a |
| MCP action local_ai_repo | implementations | confirmed | src/local_ai_hub/generator.py | op-ceab3e1c5af6 |
| MCP action local_ai_repo | intelligence | confirmed | src/local_ai_hub/generator.py | op-f2d29611e85a |
| MCP action local_ai_repo | investigate | confirmed | src/local_ai_hub/generator.py | op-6346bf6420bb |
| MCP action local_ai_repo | map | confirmed | src/local_ai_hub/generator.py | op-ffcc4f1f70ef |
| MCP action local_ai_repo | migration_drift | confirmed | src/local_ai_hub/generator.py | op-b80f01da674b |
| MCP action local_ai_repo | mutation_test | confirmed | src/local_ai_hub/generator.py | op-0edd2f8d89ca |
| MCP action local_ai_repo | package_audit | confirmed | src/local_ai_hub/generator.py | op-02b215fbe3db |
| MCP action local_ai_repo | pipeline | confirmed | src/local_ai_hub/generator.py | op-ecfc63817eac |
| MCP action local_ai_repo | preprocess | confirmed | src/local_ai_hub/generator.py | op-5cf18ee9bcf5 |
| MCP action local_ai_repo | preprocess_cancel | confirmed | src/local_ai_hub/generator.py | op-5a4746bf87f2 |
| MCP action local_ai_repo | preprocess_pause | confirmed | src/local_ai_hub/generator.py | op-96bd158a7579 |
| MCP action local_ai_repo | preprocess_refresh | confirmed | src/local_ai_hub/generator.py | op-585d6718de24 |
| MCP action local_ai_repo | preprocess_resume | confirmed | src/local_ai_hub/generator.py | op-1c42d67cb7cf |
| MCP action local_ai_repo | preprocess_status | confirmed | src/local_ai_hub/generator.py | op-890401ca08bb |
| MCP action local_ai_repo | preprocess_unregister | confirmed | src/local_ai_hub/generator.py | op-a7e2c55578b6 |
| MCP action local_ai_repo | profile | confirmed | src/local_ai_hub/generator.py | op-e74b79bba6b6 |
| MCP action local_ai_repo | profile_digest | confirmed | src/local_ai_hub/generator.py | op-3c533f7ce227 |
| MCP action local_ai_repo | reachability_dead_code | confirmed | src/local_ai_hub/generator.py | op-b100deb3a95f |
| MCP action local_ai_repo | refactor_impact | confirmed | src/local_ai_hub/generator.py | op-adb152093fab |
| MCP action local_ai_repo | repo_state | confirmed | src/local_ai_hub/generator.py | op-01cf5e21142a |
| MCP action local_ai_repo | resolve_imports | confirmed | src/local_ai_hub/generator.py | op-c05e4e00c6b6 |
| MCP action local_ai_repo | review_diff | confirmed | src/local_ai_hub/generator.py | op-44ef3f8ca9f6 |
| MCP action local_ai_repo | route | confirmed | src/local_ai_hub/generator.py | op-7708e75ee0b4 |
| MCP action local_ai_repo | schema_inspect | confirmed | src/local_ai_hub/generator.py | op-0da69bc2fc91 |
| MCP action local_ai_repo | search | confirmed | src/local_ai_hub/generator.py | op-e496067d5e8b |
| MCP action local_ai_repo | secret_scan | confirmed | src/local_ai_hub/generator.py | op-fa5de3b81690 |
| MCP action local_ai_repo | security_audit | confirmed | src/local_ai_hub/generator.py | op-277cafd904c9 |
| MCP action local_ai_repo | semantic | confirmed | src/local_ai_hub/generator.py | op-b90bf404c7ba |
| MCP action local_ai_repo | semantic_diff | confirmed | src/local_ai_hub/generator.py | op-9744eeb7c3cb |
| MCP action local_ai_repo | skeletonize | confirmed | src/local_ai_hub/generator.py | op-0a444fa448c5 |
| MCP action local_ai_repo | solve | confirmed | src/local_ai_hub/generator.py | op-df1164507eed |
| MCP action local_ai_repo | split_changes | confirmed | src/local_ai_hub/generator.py | op-929bf5e6106e |
| MCP action local_ai_repo | structural_search | confirmed | src/local_ai_hub/generator.py | op-f98d38248780 |
| MCP action local_ai_repo | synthesize_commit | confirmed | src/local_ai_hub/generator.py | op-24b5da3a8c9d |
| MCP action local_ai_repo | synthesize_rules | confirmed | src/local_ai_hub/generator.py | op-adf35c87317d |
| MCP action local_ai_repo | test_matrix | confirmed | src/local_ai_hub/generator.py | op-57f5c5d88d5a |
| MCP action local_ai_repo | topology | confirmed | src/local_ai_hub/generator.py | op-fda3cc91631a |
| MCP action local_ai_repo | type_stubs | confirmed | src/local_ai_hub/generator.py | op-a377de8dcebe |
| MCP action local_ai_repo | validate_patch | confirmed | src/local_ai_hub/generator.py | op-76faf5a7f4dd |
| MCP action local_ai_repo | verify | confirmed | src/local_ai_hub/generator.py | op-e0622f29d5f6 |
| MCP action local_ai_repo | verify_completion | confirmed | src/local_ai_hub/generator.py | op-74dae241f438 |
| MCP action local_ai_repo | verify_receipt | confirmed | src/local_ai_hub/generator.py | op-5ed1a86c484c |
| MCP action local_ai_status | agent_state | confirmed | src/local_ai_hub/generator.py | op-6bfb2c2726e6 |
| MCP action local_ai_status | brief | confirmed | src/local_ai_hub/generator.py | op-1f98c119cb01 |
| MCP action local_ai_status | cache | confirmed | src/local_ai_hub/generator.py | op-31a54897476a |
| MCP action local_ai_status | full | confirmed | src/local_ai_hub/generator.py | op-906e50c11083 |
| MCP action local_ai_status | guide | confirmed | src/local_ai_hub/generator.py | op-4561d633a362 |
| MCP action local_ai_status | telemetry | confirmed | src/local_ai_hub/generator.py | op-26dd64d0fd84 |
| MCP action local_ai_status | traces | confirmed | src/local_ai_hub/generator.py | op-c16c1de43359 |
| MCP action schema gap local_ai_command | local_ai_command | confirmed | src/local_ai_hub/mcp_server.py | op-d462ada4b979 |
| MCP action schema gap local_ai_command | speculative_lint | confirmed | src/local_ai_hub/mcp_server.py | op-0401a713d37a |
| MCP action schema gap local_ai_command | start | confirmed | src/local_ai_hub/mcp_server.py | op-0f5c237c9aac |
| MCP action schema gap local_ai_coord | claim_batch | confirmed | src/local_ai_hub/mcp_server.py | op-db688a5eedb4 |
| MCP action schema gap local_ai_coord | delete | confirmed | src/local_ai_hub/mcp_server.py | op-b0d3c8bd69ad |
| MCP action schema gap local_ai_coord | get | confirmed | src/local_ai_hub/mcp_server.py | op-9205ce46f2ca |
| MCP action schema gap local_ai_coord | lease_renew | confirmed | src/local_ai_hub/mcp_server.py | op-ce44f3483a73 |
| MCP action schema gap local_ai_coord | list | confirmed | src/local_ai_hub/mcp_server.py | op-b1cb625a2e0c |
| MCP action schema gap local_ai_coord | local_ai_coord | confirmed | src/local_ai_hub/mcp_server.py | op-34677482e869 |
| MCP action schema gap local_ai_coord | memory_reap | confirmed | src/local_ai_hub/mcp_server.py | op-6b44ba5235e0 |
| MCP action schema gap local_ai_coord | merge | confirmed | src/local_ai_hub/mcp_server.py | op-4ae1b9fe51e3 |
| MCP action schema gap local_ai_coord | relation_find | confirmed | src/local_ai_hub/mcp_server.py | op-b1cf01dbfd56 |
| MCP action schema gap local_ai_coord | relation_record | confirmed | src/local_ai_hub/mcp_server.py | op-82d193562e1f |
| MCP action schema gap local_ai_coord | relation_traverse | confirmed | src/local_ai_hub/mcp_server.py | op-4788e51bcd53 |
| MCP action schema gap local_ai_coord | update | confirmed | src/local_ai_hub/mcp_server.py | op-7895aef1d660 |
| MCP action schema gap local_ai_repo | local_ai_repo | confirmed | src/local_ai_hub/mcp_server.py | op-4ba9ed44d182 |
| MCP action schema gap local_ai_repo | serena | confirmed | src/local_ai_hub/mcp_server.py | op-dcd134194c84 |
| MCP detail local_ai_status | agent_state | confirmed | src/local_ai_hub/generator.py | op-d86b8312410a |
| MCP detail local_ai_status | brief | confirmed | src/local_ai_hub/generator.py | op-54d83bfd1ae2 |
| MCP detail local_ai_status | cache | confirmed | src/local_ai_hub/generator.py | op-5769171dbe53 |
| MCP detail local_ai_status | full | confirmed | src/local_ai_hub/generator.py | op-aed19dce53b0 |
| MCP detail local_ai_status | guide | confirmed | src/local_ai_hub/generator.py | op-055dbb10b5b0 |
| MCP detail local_ai_status | telemetry | confirmed | src/local_ai_hub/generator.py | op-7ff26863f658 |
| MCP detail local_ai_status | traces | confirmed | src/local_ai_hub/generator.py | op-71005242c84b |
| HubClient method | __init__ | confirmed | src/local_ai_hub/client.py | op-d7a30147c276 |
| HubClient method | _drop_connection | confirmed | src/local_ai_hub/client.py | op-cf96fd285a5f |
| HubClient method | close | confirmed | src/local_ai_hub/client.py | op-13bba1f972b1 |
| HubClient method | __del__ | confirmed | src/local_ai_hub/client.py | op-708b6216a4ca |
| HubClient method | _connection | confirmed | src/local_ai_hub/client.py | op-e14d61119f6c |
| HubClient method | _pooled_open | confirmed | src/local_ai_hub/client.py | op-aadf9af3f822 |
| HubClient method | _open | confirmed | src/local_ai_hub/client.py | op-d8ab74fd5f6e |
| HubClient method | _error_response | confirmed | src/local_ai_hub/client.py | op-45a523cd3e5a |
| HubClient method | _invalid_json_response | confirmed | src/local_ai_hub/client.py | op-fc288fc50665 |
| HubClient method | _uncertain_response | confirmed | src/local_ai_hub/client.py | op-776dd082b833 |
| HubClient method | _cancelled_response | confirmed | src/local_ai_hub/client.py | op-f06ccfaa0720 |
| HubClient method | _transport_failure_response | confirmed | src/local_ai_hub/client.py | op-e7c924a89c61 |
| HubClient method | _singleflight | confirmed | src/local_ai_hub/client.py | op-1c3a9bebb29a |
| HubClient method | _online | confirmed | src/local_ai_hub/client.py | op-8b5285dff009 |
| HubClient method | ensure_server | confirmed | src/local_ai_hub/client.py | op-33fa0bd0ca41 |
| HubClient method | _terminal_preflight | confirmed | src/local_ai_hub/client.py | op-fcd240ef7344 |
| HubClient method | _valid_request_id | confirmed | src/local_ai_hub/client.py | op-f3d1a0985411 |
| HubClient method | _valid_tenant | confirmed | src/local_ai_hub/client.py | op-07d7b81c887f |
| HubClient method | _identity_preflight | confirmed | src/local_ai_hub/client.py | op-b84ea840caeb |
| HubClient method | _principal_tenant | confirmed | src/local_ai_hub/client.py | op-2a21a82139a6 |
| HubClient method | _strict_root_path | confirmed | src/local_ai_hub/client.py | op-dc70e9b41823 |
| HubClient method | _root_sandbox_enabled | confirmed | src/local_ai_hub/client.py | op-44f8bb91ed47 |
| HubClient method | _root_scoped_tenant | confirmed | src/local_ai_hub/client.py | op-81855abdf57a |
| HubClient method | _request_tenant | confirmed | src/local_ai_hub/client.py | op-95259001e22f |
| HubClient method | request | confirmed | src/local_ai_hub/client.py | op-571562cfd628 |
| HubClient method | get | confirmed | src/local_ai_hub/client.py | op-a78443a5a2f8 |
| HubClient method | _post_replay_safe | confirmed | src/local_ai_hub/client.py | op-9730f1f02cc6 |
| HubClient method | post | confirmed | src/local_ai_hub/client.py | op-099bd97a5501 |
| HubClient method | status | confirmed | src/local_ai_hub/client.py | op-68f75a1ddc61 |
| HubClient method | callers | confirmed | src/local_ai_hub/client.py | op-2b384e8007ab |
| HubClient method | context_pack | confirmed | src/local_ai_hub/client.py | op-aaed12ba09d3 |
| HubClient method | coord | confirmed | src/local_ai_hub/client.py | op-0306eebe19d1 |
| HubClient method | context_compile | confirmed | src/local_ai_hub/client.py | op-8d57b4edf360 |
| HubClient method | get_evidence | confirmed | src/local_ai_hub/client.py | op-0acbe06866f5 |
| HubClient method | verify_receipt | confirmed | src/local_ai_hub/client.py | op-25d7b33175c7 |
| HubClient method | verify_completion | confirmed | src/local_ai_hub/client.py | op-73ded19fa2e9 |
| HubClient method | create_task | confirmed | src/local_ai_hub/client.py | op-31bd7c83f4c5 |
| HubClient method | get_task | confirmed | src/local_ai_hub/client.py | op-ab82ba2b4469 |
| HubClient method | list_tasks | confirmed | src/local_ai_hub/client.py | op-3cb8642b9083 |
| HubClient method | complete_task | confirmed | src/local_ai_hub/client.py | op-27fa6f2e74c0 |
| HubClient method | fail_task | confirmed | src/local_ai_hub/client.py | op-a9db1194c806 |
| HubClient method | checkpoint_task | confirmed | src/local_ai_hub/client.py | op-6119acf8e2e3 |
| HubClient method | record_memory | confirmed | src/local_ai_hub/client.py | op-74e8e816778c |
| HubClient method | find_memory | confirmed | src/local_ai_hub/client.py | op-1b13a208dc34 |
| HubClient method | submit_async_job | confirmed | src/local_ai_hub/client.py | op-49d2a0be15a0 |
| HubClient method | async_job_status | confirmed | src/local_ai_hub/client.py | op-8b61e0cace53 |
| HubClient method | wait_async_job | confirmed | src/local_ai_hub/client.py | op-0496d7607562 |
| HubClient method | async_job_result | confirmed | src/local_ai_hub/client.py | op-5b6e1e75ca0b |
| HubClient method | cancel_async_job | confirmed | src/local_ai_hub/client.py | op-1be3de23c177 |
| HubClient method | continue_conversation | confirmed | src/local_ai_hub/client.py | op-e6bf1eba39a1 |
| HubClient method | cancel_job | confirmed | src/local_ai_hub/client.py | op-b4bd725b069c |
| HubClient method | doctor | confirmed | src/local_ai_hub/client.py | op-226933155244 |
| HubClient method | logs | confirmed | src/local_ai_hub/client.py | op-519d521fd990 |
| HubClient method | events | confirmed | src/local_ai_hub/client.py | op-fa5298f48b76 |
| HubClient method | stream_events | confirmed | src/local_ai_hub/client.py | op-d78ac208df77 |
| HubClient method | circular_dependencies | confirmed | src/local_ai_hub/client.py | op-289db5bf44ce |
| HubClient method | generate_types | confirmed | src/local_ai_hub/client.py | op-9de0a5065f46 |
| HubClient method | complexity | confirmed | src/local_ai_hub/client.py | op-9af2fb57be23 |
| HubClient method | api_spec | confirmed | src/local_ai_hub/client.py | op-9c46914bd0c6 |
| HubClient method | dependency_slice | confirmed | src/local_ai_hub/client.py | op-4a64733ffc4d |
| HubClient method | migration_drift | confirmed | src/local_ai_hub/client.py | op-6dc182736029 |
| HubClient method | package_audit | confirmed | src/local_ai_hub/client.py | op-cbbd3f3ce4a6 |
| HubClient method | diff_hunk_stage | confirmed | src/local_ai_hub/client.py | op-27028e51190b |
| HubClient method | flaky_detect | confirmed | src/local_ai_hub/client.py | op-a9a455c84b29 |
| HubClient method | webhook_replay | confirmed | src/local_ai_hub/client.py | op-0993dcf8baf7 |
| HubClient method | eval_drift | confirmed | src/local_ai_hub/client.py | op-cb7e356ddb67 |
| HubClient method | git_diff | confirmed | src/local_ai_hub/client.py | op-1d6e9c1ddf9f |
| HubClient method | git_history_search | confirmed | src/local_ai_hub/client.py | op-da9b7de7f941 |
| HubClient method | hotspots | confirmed | src/local_ai_hub/client.py | op-c1f4cd296365 |
| HubClient method | generate_tests_for_diff | confirmed | src/local_ai_hub/client.py | op-c92a5f8ccb31 |
| HubClient method | cross_repo_contract | confirmed | src/local_ai_hub/client.py | op-5cb9f371aa16 |
| HubClient method | mock_server | confirmed | src/local_ai_hub/client.py | op-132900407352 |
| HubClient method | ingest_diagram | confirmed | src/local_ai_hub/client.py | op-b7e195085083 |
| HubClient method | curate_training_dataset | confirmed | src/local_ai_hub/client.py | op-a086395ba65f |
| HubClient target | GET /ready | confirmed | src/local_ai_hub/client.py | op-13bc5694d041 |
| HubClient target | GET /api/live/status?light=1&scope={scope}&detail={detail} | conditional | src/local_ai_hub/client.py | op-67de90c8470e |
| HubClient target | GET /api/debug-traces?{query} | conditional | src/local_ai_hub/client.py | op-59aad9d4989c |
| HubClient target | GET /api/status?detail=agent_state | conditional | src/local_ai_hub/client.py | op-1dbda45ed929 |
| HubClient target | POST /api/repo/callers | confirmed | src/local_ai_hub/client.py | op-c8881ebaac6f |
| HubClient target | POST /api/context/pack | confirmed | src/local_ai_hub/client.py | op-957800987d8a |
| HubClient target | POST /api/agent-state/tasks | confirmed | src/local_ai_hub/client.py | op-8ff639ee98fd |
| HubClient target | POST /api/agent-state/tasks | confirmed | src/local_ai_hub/client.py | op-05519cb0bda2 |
| HubClient target | POST /api/agent-state/memory | confirmed | src/local_ai_hub/client.py | op-ceb3bd26dc5d |
| HubClient target | POST /api/agent-state/incidents | confirmed | src/local_ai_hub/client.py | op-9d2e8c7c5fff |
| HubClient target | POST /api/agent-state/context | confirmed | src/local_ai_hub/client.py | op-645668559c9d |
| HubClient target | POST /api/agent-state/verification | confirmed | src/local_ai_hub/client.py | op-8739b57533bb |
| HubClient target | POST /api/agent-state/verification | confirmed | src/local_ai_hub/client.py | op-12dc510c404b |
| HubClient target | POST /api/agent-state/verification | confirmed | src/local_ai_hub/client.py | op-f6c028a3851b |
| HubClient target | POST /api/agent-state/incidents | confirmed | src/local_ai_hub/client.py | op-50bb1678de07 |
| HubClient target | POST /api/agent-state/incidents | confirmed | src/local_ai_hub/client.py | op-90d40a71354f |
| HubClient target | POST /api/leases/claim_batch | confirmed | src/local_ai_hub/client.py | op-c5b2e5d89db3 |
| HubClient target | POST /api/agent-state/blackboard | confirmed | src/local_ai_hub/client.py | op-25a64fbfedfd |
| HubClient target | POST /api/leases/release | confirmed | src/local_ai_hub/client.py | op-1967f10cce9e |
| HubClient target | GET /api/leases?root={value} | conditional | src/local_ai_hub/client.py | op-f18de06ef38b |
| HubClient target | POST /api/coord/worktree_lease | confirmed | src/local_ai_hub/client.py | op-540f5d4c5fe7 |
| HubClient target | POST /api/coord/worktree_release | confirmed | src/local_ai_hub/client.py | op-388e499ae7a3 |
| HubClient target | POST /api/coord/pubsub_publish | confirmed | src/local_ai_hub/client.py | op-91d988792943 |
| HubClient target | POST /api/coord/pubsub_poll | confirmed | src/local_ai_hub/client.py | op-db3ce93f08f4 |
| HubClient target | POST /api/coord/simulate_merge | confirmed | src/local_ai_hub/client.py | op-5b8700840a7b |
| HubClient target | POST /api/memory/put | confirmed | src/local_ai_hub/client.py | op-dc13f7588b74 |
| HubClient target | POST /api/memory/get | confirmed | src/local_ai_hub/client.py | op-6b6825859012 |
| HubClient target | POST /api/memory/search | confirmed | src/local_ai_hub/client.py | op-4c7c85175c86 |
| HubClient target | POST /api/memory/delete | confirmed | src/local_ai_hub/client.py | op-3a1a72a6651b |
| HubClient target | POST /api/agent-state/context | confirmed | src/local_ai_hub/client.py | op-78996094a2da |
| HubClient target | POST /api/evidence/get | confirmed | src/local_ai_hub/client.py | op-e2cfd2b35745 |
| HubClient target | POST /api/agent-state/verification | confirmed | src/local_ai_hub/client.py | op-601c61cd374a |
| HubClient target | POST /api/agent-state/verification | confirmed | src/local_ai_hub/client.py | op-e609cf679405 |
| HubClient target | POST /api/agent-state/tasks | confirmed | src/local_ai_hub/client.py | op-f7c0921b879e |
| HubClient target | POST /api/agent-state/tasks | confirmed | src/local_ai_hub/client.py | op-bcefa565c564 |
| HubClient target | POST /api/agent-state/tasks | confirmed | src/local_ai_hub/client.py | op-6794262665b6 |
| HubClient target | POST /api/agent-state/tasks | confirmed | src/local_ai_hub/client.py | op-a530dc687c5a |
| HubClient target | POST /api/agent-state/tasks | confirmed | src/local_ai_hub/client.py | op-cf402e4240a2 |
| HubClient target | POST /api/agent-state/tasks | confirmed | src/local_ai_hub/client.py | op-6aa5d6379c1f |
| HubClient target | POST /api/agent-state/memory | confirmed | src/local_ai_hub/client.py | op-528ca37ad47e |
| HubClient target | POST /api/agent-state/memory | confirmed | src/local_ai_hub/client.py | op-e06ddad73a22 |
| HubClient target | POST /api/async-jobs | confirmed | src/local_ai_hub/client.py | op-50434dcfa2b0 |
| HubClient target | POST /api/async-jobs | confirmed | src/local_ai_hub/client.py | op-6349831d854c |
| HubClient target | POST /api/async-jobs | confirmed | src/local_ai_hub/client.py | op-988236325acc |
| HubClient target | POST /api/async-jobs | confirmed | src/local_ai_hub/client.py | op-c4ec66225316 |
| HubClient target | POST /api/async-jobs | confirmed | src/local_ai_hub/client.py | op-7f1ac0af7e2c |
| HubClient target | POST /api/conversations/continue | confirmed | src/local_ai_hub/client.py | op-6e2ee115c74e |
| HubClient target | POST /api/async-jobs | confirmed | src/local_ai_hub/client.py | op-626b8fe1c577 |
| HubClient target | GET /api/doctor | confirmed | src/local_ai_hub/client.py | op-47795aa5e7a2 |
| HubClient target | GET /api/logs/tail?lines={value} | conditional | src/local_ai_hub/client.py | op-01d0a231e719 |
| HubClient target | GET /api/agent-state/events{qs} | conditional | src/local_ai_hub/client.py | op-3f8b4cc8f30a |
| HubClient target | GET /api/agent-state/events/stream | confirmed | src/local_ai_hub/client.py | op-e1e3c4489406 |
| HubClient target | POST /api/repo/circular_dependencies | confirmed | src/local_ai_hub/client.py | op-ecc07b967ce1 |
| HubClient target | POST /api/repo/generate_types | confirmed | src/local_ai_hub/client.py | op-097ecd21b4ac |
| HubClient target | POST /api/repo/complexity | confirmed | src/local_ai_hub/client.py | op-d00635595cd0 |
| HubClient target | POST /api/repo/api_spec | confirmed | src/local_ai_hub/client.py | op-94a1eecf769f |
| HubClient target | POST /api/repo/dependency_slice | confirmed | src/local_ai_hub/client.py | op-f2b185cb2570 |
| HubClient target | POST /api/repo/migration_drift | confirmed | src/local_ai_hub/client.py | op-2b7635f45557 |
| HubClient target | POST /api/repo/package_audit | confirmed | src/local_ai_hub/client.py | op-cbd749119dec |
| HubClient target | POST /api/command/diff_hunk_stage | confirmed | src/local_ai_hub/client.py | op-3e8d067ce97d |
| HubClient target | POST /api/command/flaky_detect | confirmed | src/local_ai_hub/client.py | op-d625a26bf040 |
| HubClient target | POST /api/command/webhook_replay | confirmed | src/local_ai_hub/client.py | op-2d8518d7b54f |
| HubClient target | POST /api/task/eval_drift | confirmed | src/local_ai_hub/client.py | op-15fac55d5eee |
| HubClient target | POST /api/git/diff | confirmed | src/local_ai_hub/client.py | op-33f4b529a2f8 |
| HubClient target | POST /api/git/history_search | confirmed | src/local_ai_hub/client.py | op-358f52686ec2 |
| HubClient target | POST /api/repo/hotspots | confirmed | src/local_ai_hub/client.py | op-ea8e385d3c77 |
| HubClient target | POST /api/repo/generate_tests_for_diff | confirmed | src/local_ai_hub/client.py | op-9cca4a35924f |
| HubClient target | POST /api/repo/cross_repo_contract | confirmed | src/local_ai_hub/client.py | op-6437c39aca49 |
| HubClient target | POST /api/command/mock_server | confirmed | src/local_ai_hub/client.py | op-ef4f85c7e667 |
| HubClient target | POST /api/rag/ingest_diagram | confirmed | src/local_ai_hub/client.py | op-69fef0ffcfae |
| HubClient target | POST /api/agent-state/tasks | confirmed | src/local_ai_hub/client.py | op-c7342144ec03 |
| CLI operation | agent-state | confirmed | tools/hubctl.py | op-7e8d2221e554 |
| CLI operation | clean | confirmed | tools/hubctl.py | op-02e6bf344b35 |
| CLI operation | cleanup | confirmed | tools/hubctl.py | op-78d6f8c8a97e |
| CLI operation | dashboard | confirmed | tools/hubctl.py | op-a7abef5e4884 |
| CLI operation | doctor | confirmed | tools/hubctl.py | op-b33c959eab65 |
| CLI operation | generate | confirmed | tools/hubctl.py | op-53d2882e6404 |
| CLI operation | logs | confirmed | tools/hubctl.py | op-7a6e42f71891 |
| CLI operation | memory | confirmed | tools/hubctl.py | op-ee8a4e3836f2 |
| CLI operation | mode | confirmed | tools/hubctl.py | op-9dc37e51eae5 |
| CLI operation | pause | confirmed | tools/hubctl.py | op-ad185fd1da6f |
| CLI operation | restart | confirmed | tools/hubctl.py | op-ce45818ace8e |
| CLI operation | resume | confirmed | tools/hubctl.py | op-647c5bcf0f71 |
| CLI operation | service-status | confirmed | tools/hubctl.py | op-533e550f0c3e |
| CLI operation | start | confirmed | tools/hubctl.py | op-1726e864fb01 |
| CLI operation | status | confirmed | tools/hubctl.py | op-c91943d94b53 |
| CLI operation | stop | confirmed | tools/hubctl.py | op-ff488b06f3df |
| CLI operation | tasks | confirmed | tools/hubctl.py | op-f4ed611a09db |
| CLI operation | watch | confirmed | tools/hubctl.py | op-d099c05ad03c |

Orphan client targets, unhandled generated MCP actions, source-only MCP tools, dynamic route registry entries, and generated schemas without source registrations fail `--check`.
