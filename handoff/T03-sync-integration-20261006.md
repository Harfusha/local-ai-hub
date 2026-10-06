# T03 checkout synchronization — 2026-10-06

Synchronization complete; functional acceptance remains partial.

## Ownership and preservation

- Assigned checkout only: `C:/Users/Adam/.codex/worktrees/t03-contracts-resume/.local-ai-hub`.
- Branch: `codex/sync-t03-master-20261006`.
- Original HEAD: `ad622f8a90a81e349e94d3402f297f2995e733b2`.
- Original checkpoint ref: `codex/checkpoint-t03-original-20261006`.
- Dirty source checkpoint: `3dc82bba6dcfb7653bb61fa1086af8194ead2aaa`, ref `codex/checkpoint-t03-dirty-20261006`.
- That checkpoint commits all 18 originally modified tracked files and 15 new source/test/design files before merge. Unfinished behavior is deliberately retained.
- Original handoff Markdown documents were subsequently committed as historical evidence, not current acceptance receipts. Patch/JSON artifacts and both original overlay directories remain preserved on disk.
- Runtime state, caches and new check artifacts under `.t03-sync-checks/` are excluded from commits.
- No stash, drop, hard reset, clean, new worktree/chat, push, dependency install, root checkout edit, or master ref write.
- User supplied a prior terminal Hub failure and explicitly authorized native fallback. No Hub retry or polling. The preceding Hub receipt itself was not available in this turn; no evidence IDs invented.
- Token-economizer applied bounded discovery/source slices. Its required ensure-tools script was absent at both installed skill locations; no installation or PATH change performed.
- Native read-only sidecar delegation attempted once; agent thread limit prevented spawning. Main agent handled integration.

## Merge decisions

- `f8ac72b8`: manual merge of `fbc965f568105e1a8d3dc03ae4c9da5531a9617e`, with 24 conflicted files resolved by hunk.
- `97e8902e`: follow-up merge of advancing master `f8ba97fe9eafa38810dbbbc3c4184800da7bafcd`. Its added T02/T11/T21 handoffs and runner code merged without conflicts; those unrelated functional suites were not run.
- Master's newer inference admission, cancellation/unload ownership, cross-process operational-mode locks, bounded SSE replay, journal-before-dispatch and safe autostart behavior take precedence over older T03 variants.
- Master's shared/open MCP output envelope and scoped input contracts replace the stale closed per-action schema variant. Removed/replaced variants remain recoverable in the dirty checkpoint.
- Retained T03 finite argument validation, adoption reporting validation, receipt.passed boolean validation, trusted journal metadata reconciliation, bounded work-order numeric validation, fallback_used reliability metadata, registry-backed generator and extra safety assertions.
- Resolved merge duplicates: repeated path_hints keyword, duplicate dictionary properties/constants, duplicated mode gate and bootstrap text. In-process fixture now isolates its test APP from preceding HTTP tests. Replay assertions accept the preserved conflict error alongside conflict state.
- No duplicate root path-hint implementation: current master forwarding preserved; its regression passes.
- `preprocess.py`, `features.py`, `client.py`, `async_jobs.py`, `operational_mode.py`, and `ollama.py` exactly match merged master. This preserves master's preprocessing/agent baseline and CodeGraph removal. No additional Gemini preprocessing behavior was introduced or inferred.
- T14's `/api/context/pack` branch is AST-identical to the merged master branch; no redesign.
- Both INSTALL_PROMPT and UPDATE_PROMPT document retained argument-validation rules.

## Actual checks

- Initial changed-source AST parse: PASS. Later AST parse of 16 changed Python files: PASS.
- Initial 10-file targeted pytest run: **188 passed, 17 failed**, 70.78 seconds. Full log preserved at `.t03-sync-checks/pytest.log`.
- After merge corrections and enabling model schemas in the isolated test configuration, focused follow-up across operation contracts, MCP dispatch, in-process transport, operational-mode dispatch and mutation replay: **169 passed, 3 failed**, 31.48 seconds.
- Follow-up command: `python -B -m pytest -q --tb=short -p no:cacheprovider --basetemp=.t03-sync-checks/pytest-followup tests/test_operation_contracts.py tests/test_mcp_contract_dispatch.py tests/test_inprocess_transport.py tests/test_mcp_operational_mode_dispatch.py tests/test_mutation_replay.py`.
- Existing master path-hint regression: **1 passed, 17 deselected**, 2.11 seconds, using `tests/test_mcp_contract_dispatch.py -k test_mcp_repo_search_passes_path_hints_to_client_keyword`.
- Direct nested/non-finite operation argument assertions: PASS (NaN max_tokens; nested Infinity context).
- AST comparison of T14 context route: PASS, one matching branch.
- `git diff --check master HEAD -- src tests tools docs/INSTALL_PROMPT.md docs/UPDATE_PROMPT.md`: PASS.
- Broad staged whitespace check against old pre-merge HEAD reported inherited master CRLF/patch whitespace plus historical receipt Markdown line breaks. No unrelated formatting rewrite attempted.
- Test configuration, temp directories and telemetry state are under assigned checkout; isolated MCP test config uses port 1. Test receipts do not prove installed Hub operation, real model inference, live wire or full release acceptance.
- No full release suite run. No new acceptance asserted from historical receipts.

## Outstanding behavior

1. `tests/test_mcp_contract_dispatch.py::test_live_mcp_schemas_match_registry_for_every_public_tool`: registered local_ai_repo parameters differ from registry expectations (action alias/conditional input schema parity unresolved).
2. `tests/test_mcp_operational_mode_dispatch.py::test_gaming_mcp_dispatch_allows_only_speculative_lint`: lint dispatch returned success=false.
3. `tests/test_mcp_operational_mode_dispatch.py::test_maintenance_mcp_dispatch_still_blocks_speculative_lint`: response omitted expected mode.
4. Initial `tests/test_agent_state_transport.py::test_http_memory_get_is_scope_and_root_isolated` returned HTTP 404. Not included in the focused follow-up; remains unresolved.
5. Initial configuration deliberately disabled Ollama startup and omitted model tools; five schema/registration failures were configuration-dependent. Follow-up registered all tools using isolated configuration.
6. Historical live-wire, daemon acceptance, output-shape and architecture claims remain unverified for this synchronized checkout. Remaining behavior is committed for later owner work, not expanded into new features here.

## Changed files versus synchronized master

The final integration note itself is additional to this list. Historical handoff Markdown documents below are preserved records, not fresh receipts.

- `docs/INSTALL_PROMPT.md`
- `docs/UPDATE_PROMPT.md`
- `docs/superpowers/plans/2026-09-28-t03-mcp-contracts-autostart.md`
- `docs/superpowers/plans/2026-10-01-t03-mcp-architecture-gate.md`
- `docs/superpowers/specs/2026-09-28-t03-mcp-contracts-and-autostart.md`
- `docs/superpowers/specs/2026-09-29-t03-action-contract-validation.md`
- `handoff/T03-acceptance-current.md`
- `handoff/T03-action-output-schemas-20261002.receipt.md`
- `handoff/T03-artifact-slice-bounds-root-current-recheck.receipt.md`
- `handoff/T03-artifact-slice-bounds-root-current.receipt.md`
- `handoff/T03-live-wire-coldstart-receipt.md`
- `handoff/T03-live-wire-handshake.receipt.md`
- `handoff/T03-live-wire-root-current.receipt.md`
- `handoff/T03-live-wire-test-only.receipt.md`
- `handoff/T03-main-preflight-root-current.receipt.md`
- `handoff/T03-master-base-test-boundary-20261006.md`
- `handoff/T03-mcp-architecture-gate-20261001.md`
- `handoff/T03-mcp-http-daemon-acceptance-20261003.md`
- `handoff/T03-mcp-inprocess-continuation-20261002.receipt.md`
- `handoff/T03-mcp-inprocess-root-current.receipt.md`
- `handoff/T03-operational-mode-classifier-root-current-20261002.receipt.md`
- `handoff/T03-owner-only-mcp-contract-dispatch-20261004.md`
- `handoff/T03-path-hints-contract-manifest-20261004.md`
- `handoff/T03-path-hints-keyword-end2end-20261006.md`
- `handoff/T03-root-autostart-fake-regression-20261004.md`
- `handoff/T03-root-current-autostart-test-manifest-20261004.md`
- `handoff/T03-root-current-full-status-output-20261001.receipt.md`
- `handoff/T03-root-current-path-hints-client-keyword-20261006.md`
- `handoff/T03-root-current-path-hints-wrapper-test-20261006.md`
- `handoff/T03-root-current-path-hints-wrapper-test.receipt.md`
- `src/local_ai_hub/external_tools.py`
- `src/local_ai_hub/generator.py`
- `src/local_ai_hub/http_server.py`
- `src/local_ai_hub/inprocess_transport.py`
- `src/local_ai_hub/mcp_server.py`
- `src/local_ai_hub/operation_contracts.py`
- `src/local_ai_hub/resilience.py`
- `tests/test_agent_state_transport.py`
- `tests/test_client_transport.py`
- `tests/test_inprocess_transport.py`
- `tests/test_mcp_autostart_contract.py`
- `tests/test_mcp_compact_transport.py`
- `tests/test_mcp_contract_dispatch.py`
- `tests/test_mutation_replay.py`
- `tests/test_recovery_journal_contract.py`
- `tests/test_sse_events_stream.py`
- `tools/surface_inventory.py`

## Final structural handoff

Original and dirty checkpoint refs remain available. Final HEAD is the commit containing this note (or its subsequent master synchronization merge); obtain it with `git rev-parse HEAD`. Final structural verification must show synchronized master as ancestor, no unmerged index entries and no tracked dirty files. Preserved untracked artifacts are intentional.

