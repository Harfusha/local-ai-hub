# T10 fallback callgraph revalidation — 2026-10-01

Candidate `C:\Users\Adam\.codex\worktrees\t10-path-hints\.local-ai-hub` HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`. Root `C:\Users\Adam\.local-ai-hub` HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.

- Candidate `src/local_ai_hub/code_index.py`: SHA-256 `be2ea33ad26a6621df32a42e3bfd8b380d70708c78790604886936b790755101`
- Candidate `tests/test_t10_fallback_callgraph_parity.py`: SHA-256 `3b955da92b1172cba9510ecfadbda67d748ab8605b5c0c521abfd956a87318be`
- Root `src/local_ai_hub/code_index.py`: SHA-256 `ff5c2f010c9c02ac5916c99c6e6859f2e90f5457dba103dce5e9a83816bac3e9`
- Root fallback parity test: absent.
- Immutable root-current patch SHA-256 `d75bcf3fef0825f39faaf5dfe82ee657493a2816e8805884f1a8e5e74f2e4fc1`; current `git apply --check` passed. Root unchanged.

Exact command:

```powershell
python -B -m pytest -q -s -p no:cacheprovider --tb=short tests/test_t10_fallback_callgraph_parity.py tests/test_t10_ast_impact_acceptance.py tests/test_preprocessing_overhaul.py::test_code_index_find_callers_and_callees tests/test_reliability_integration.py::test_code_index_impact_batches_large_changed_file_sets tests/test_cross_repo_federation.py::test_cross_repo_symbol_find_and_impact
```

Result: **20 passed, 0 failed, 0 skipped in 6.92s** (exit 0). Previous root-source overlay receipt remains **20 passed in 5.37s**; not rerun.

T02 paired 100k benchmark remains open. No compatible final candidate pin and T20 exclusive CPU slot are recorded.
