# T03 root autostart fake regression receipt

Date: 2026-10-04 (Europe/Prague)
T03 candidate: `C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub`
Candidate HEAD: `ad622f8a90a81e349e94d3402f297f2995e733b2`

## Finding

Root-current report: one command across four files, after removing one missing test path, returned **72 passed, 4 failed in 27.83s**. Root test `test_mcp_transport_selection_injects_lazy_transport_with_same_config_and_tenant` used a `FakeHubClient` constructor that rejected `auto_start`. Root command text and root file hashes were not included in the report; this receipt does not infer them.

## T03-owned candidate disposition

No candidate source change was needed. The candidate already has the owner-scoped test `test_mcp_transport_selection_uses_http_autostart_with_same_config_and_tenant` in `tests/test_mcp_contract_dispatch.py`. Its fake accepts keyword-only `tenant`, `config_path`, and `auto_start`; assertions require the original tenant/config and `auto_start=True`. Candidate `src/local_ai_hub/mcp_server.py` calls `HubClient(tenant=tenant, config_path=config_path, auto_start=True)`.

Candidate test postimage SHA-256: `31ADBEF93145A1C57F049836795ADFAD3FF1424DD3049802F411259931DAF1EC`.
Candidate implementation postimage SHA-256: `3B36A3313DC04388F49A29741FACAF29BE2D4CFCF8964E9A905FC006F3F9B24D`.

## Candidate receipt

Exact command:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_operation_contracts.py tests/test_mcp_contract_dispatch.py tests/test_mcp_autostart_contract.py tests/test_recovery_journal_contract.py tests/test_mcp_live_wire_schema.py
```

Recorded same-HEAD result: **110 passed in 22.02s**, exit 0. This receipt is recorded in `handoff/T03-acceptance-current.md`; it includes the candidate autostart fake test. No tests were rerun for this addendum. Root tests were not repeated.

## Owner boundaries

The reported `process_identity` `NameError` in `_write_start_lock_owner` belongs to client lifecycle owners T16/T04. T03 made no `client.py` or autostart lifecycle changes for that failure. Do not weaken the root assertions or overlay candidate files onto root; candidate/root postimages differ.
