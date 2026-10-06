# T10 fallback callgraph parity — root-current r1

## Status

Fallback callgraph correction passed candidate and root-source overlay acceptance. The patch is immutable and root-current at the recorded preimage; root was not modified. The paired 100k T02 run remains unstarted: the T02 runbook requires a T20 exclusive CPU slot, and the T02 manifest and T10 runbook candidate package pins conflict. T11/T14 were idle at the status snapshot.

## Patch

- Patch: `t10-fallback-callgraph-root-current-r1.patch`
- SHA-256: `d75bcf3fef0825f39faaf5dfe82ee657493a2816e8805884f1a8e5e74f2e4fc1`
- Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`
- Candidate HEAD: `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`

Preimage SHA-256:

- `src/local_ai_hub/code_index.py`: `ff5c2f010c9c02ac5916c99c6e6859f2e90f5457dba103dce5e9a83816bac3e9`
- `tests/test_t10_fallback_callgraph_parity.py`: `ABSENT`

Postimage SHA-256 in tested overlay:

- `src/local_ai_hub/code_index.py`: `17381446b55b80d28c06387fd972cc907ce2f5e9d01506fbd5955080d90d1741`
- `tests/test_t10_fallback_callgraph_parity.py`: `e82e8213e28c371d969da9beff0b7a76ab9b03acf3a333765dbf54d8c3255875`

The CodeIndex change scopes fallback call edges to the narrowest enclosing function, filters declaration lines, and advances analyzer version to invalidate stale parse blobs. Tests compare fallback caller/callee pairs against Tree-sitter where available across C#, TypeScript, JavaScript, Go, Rust, and Python.

## Exact validation

Fail-first command: `python -B -m pytest -q -s -p no:cacheprovider --tb=short tests/test_t10_fallback_callgraph_parity.py` — **5 failed, 1 passed**; non-Python fallbacks reported `<module>` callers.

Candidate command: `python -B -m pytest -q -s -p no:cacheprovider --tb=short tests/test_t10_fallback_callgraph_parity.py tests/test_t10_ast_impact_acceptance.py tests/test_preprocessing_overhaul.py::test_code_index_find_callers_and_callees tests/test_reliability_integration.py::test_code_index_impact_batches_large_changed_file_sets tests/test_cross_repo_federation.py::test_cross_repo_symbol_find_and_impact` — **20 passed in 5.66s**.

Root overlay: copied root `src/local_ai_hub` and `tests` to `C:\Users\Adam\AppData\Local\Temp\t10-fallback-root-current-r1-final-107_iosq`, applied the patch, then ran:

```powershell
C:\Python313\python.exe -B -m pytest -q -s -p no:cacheprovider --tb=short tests/test_t10_fallback_callgraph_parity.py tests/test_t10_ast_impact_acceptance.py tests/test_preprocessing_overhaul.py::test_code_index_find_callers_and_callees tests/test_reliability_integration.py::test_code_index_impact_batches_large_changed_file_sets tests/test_cross_repo_federation.py::test_cross_repo_symbol_find_and_impact
```

Result: **20 passed in 5.37s**, exit 0. Root apply-check passed before the overlay run.

## 100k paired run

Not run. The T02 dataset manifest lists T10 candidate and baseline outputs as unavailable and says the owner runbook requires a T20 exclusive CPU slot. The T10 runbook pins candidate revision `7a36be3b8b69531dccd9215515ac793369da0a44` and `HEAD:src` baseline from that revision; T02 manifest and runbook report different candidate package hashes. No output is substituted or claimed. T11/T14 were idle when checked; no CodeGraph or Hub action was used.
