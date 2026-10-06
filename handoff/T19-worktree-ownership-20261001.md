# T19 Worktree Ownership Snapshot — 2026-10-01

Status is read-only. Candidate `HEAD` is `2b33602adef0d030fea66cdcc04ca742c60b2e32`; observed root `HEAD` is `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. After adding this note, candidate has **83 dirty paths**: 48 tracked modifications and 35 untracked files. All are preserved. No root writes, tests, or builds occurred for this inventory.

## Ownership classes

### T19-owned work and artifacts — 40 paths

- Scope files: `MANIFEST.in`, `docs/INSTALLATION.md`, `docs/INSTALL_PROMPT.md`, `docs/UPDATE_PROMPT.md`, `docs/MODEL_CAPABILITIES.md`, `docs/PYTHON_SDK.md`, `docs/T19_RELEASE_VALIDATION_RUNBOOK.md`, `docs/superpowers/plans/2026-09-25-t19-install-sdk-rollout.md`, and `tools/rollback_snapshot.py`.
- Regression files: all `tests/test_t19_*.py` files present in this snapshot.
- Handoff files: all `handoff/T19-*` files present in this snapshot. These are T19-authored receipts or proposed patches, not authority to overwrite another owner's source. Existing superseded patches remain preserved; follow each receipt before applying any patch.

### Shared T19 hunks — 2 paths

- `AGENTS.md`: T19's exact model-profile routing update is one hunk in a shared policy file.
- `tests/test_release_contract.py`: T19's release-content exclusion and routing expectation are narrow hunks in a shared test file.

Apply only the reviewed hunk from `handoff/T19-prompts-release-contract-current-root.patch`; keep all other file content.

### Explicit T01 ownership — 3 paths

- `docs/API_COVERAGE.md`
- `tests/test_surface_inventory.py`
- `tools/surface_inventory.py`

The T19 coverage-owner test and patch are handoff artifacts. T01 owns inventory implementation and coverage document integration; keep candidate changes intact and do not edit or integrate these three paths without T01 release.

### Inherited or ownership unconfirmed — 38 paths

Preserve without edits until a baseline or owner receipt assigns them:

- `config.toml.example`
- `docs/ARCHITECTURE.md`, `docs/DASHBOARD.md`, `docs/FEATURE_AUDIT_V4.md`, `docs/MCP_AND_AGENTS.md`, `docs/OPERATIONS.md`, `docs/SECURITY_MODEL.md`, `docs/TROUBLESHOOTING.md`
- `docs/superpowers/plans/2026-09-22-adaptive-retrieval-orchestrator.md`
- `src/local_ai_hub/client.py`, `external_tools.py`, `generator.py`, `http_server.py`, `mcp_server.py`, `ollama_subagents.py`, `preprocess.py`, `resilience.py`, `retrieval.py`
- `tests/test_adaptive_retrieval.py`, `test_agent_os_enhancements.py`, `test_client_transport.py`, `test_codegraph_package_policy.py`, `test_doctor_support.py`, `test_external_tools.py`, `test_features.py`, `test_mcp_agent_routing.py`, `test_preprocessing_overhaul.py`, `test_preprocessor_and_deterministic.py`, `test_projection_extra_fields.py`, `test_release_hardening.py`, `test_setup.py`, `test_stuck_preprocessing_and_dashboard_fixes.py`
- `tools/doctor.py`, `hubctl.py`, `selftest.py`, `telemetry_report.py`, `uninstall.py`

The T19 plan also requires preserving inherited T10, T21, and Agent 2 work. This snapshot does not prove exact ownership for each path above; it assigns no new owner.

## Integration boundary

The earlier `handoff/T19-root-delta-classification.md` compares candidate/root hunks; it is not a per-file ownership record. T20 owns root integration. Never copy whole candidate files to root. The prompt/AGENTS patch is currently `git apply --check`-clean at the observed root state; recheck before integration if either checkout changes.
