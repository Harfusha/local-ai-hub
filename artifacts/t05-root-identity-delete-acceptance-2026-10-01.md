# T05 root identity and delete receipt — 2026-10-01

Status: PARTIAL. This receipt closes the root identity/delete selectors only; it does not close all T05 store scope/privacy/CRUD acceptance.

## Root evidence

Integrator reports the exact four selectors below passed on root: **4 passed in 1.49s**. This is integrator-reported root evidence; no raw test log was supplied in this task.

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_agent_memory.py::test_find_filters_global_and_repository_rows_by_tenant_and_root tests/test_agent_memory.py::test_global_memory_delete_ignores_transport_tenant_but_keeps_scope tests/test_agent_memory.py::test_scoped_memory_delete_still_enforces_tenant tests/test_agent_memory.py::test_memory_find_enforces_root_repository_and_tenant_identity
```

Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`

Root `src/local_ai_hub/agent_memory.py` SHA-256: `436E90BFF060005F91F93803719D0F33DCDE9A3089731F7743273456FC619FFF`

Root `tests/test_agent_memory.py` SHA-256: `FB7115C9401A66A2A5200A6424F4A31C261F233765E40DB64AE8FC94A3DF12CA`

Integrated correction patch SHA-256: `A4960FD29F2397B7E4414423B0855F0DD335FCE2087360335712AA8958DD04F1`

## Remaining T05 store acceptance

Root does not contain these candidate selectors or sanitizer helpers at the hashes above:

- `test_find_skips_corrupt_rows_without_aborting_scoped_read`
- `test_memory_write_redacts_private_fields_and_blocks_sensitive_records`
- `test_memory_correction_lineage_and_delete_survive_reopen`

Candidate previously reported these four selectors passing, but that is not root proof. Keep T05 store scope/privacy/CRUD acceptance open until the remaining root implementation and selectors have fresh root receipts.
