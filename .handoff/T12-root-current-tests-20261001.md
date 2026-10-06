# T12 root-current test handoff — 2026-10-01

Owner: T12 test-only patch; T20 owns root integration. Primary root was read-only.

- Patch: `T12-root-current-tests-20261001.patch`; SHA-256 `03FBD569B30BB8DBB70BEC777DB2EE63CF0253FC9D20AE2A97E0CF04A5C16D28`.
- Root strict `git apply --check --whitespace=error`: exit 0. Patch scope is only `tests/test_t12_runtime_scenarios.py` and `tests/test_ollama_gaming_mode.py`.
- Root-source overlay command: `$env:PYTHONPATH='src'; python -B -m pytest -q -p no:cacheprovider --tb=short -c pyproject.toml tests/test_t12_runtime_scenarios.py::test_t12_json_format_and_think_are_promoted_to_ollama_request_fields tests/test_ollama_gaming_mode.py`.
- Result: **7 passed in 0.11s**.
- `test_t12_runtime_scenarios.py`: root preimage `885EE75E4389CED0A30B184672F2A26D77434C78EF3E3657BAE5E8CBF4A36DBA`; postimage `CAD7B0DE7FDC18848C72BCACE7E300E257EC06BB716B7750594177B1E995F1D1`.
- `test_ollama_gaming_mode.py`: root preimage `786A376B8F5D55182687AB82E1032A2F05183A14EAE4CD0694544ACA47664FC9`; postimage `8A8FAA094CA75E746D9C6BF4214CF46D1AE40E608D1B1AA4FB4266B3358E5D2A`.
- Runtime JSON test fixture now initializes production `ModelExecutionPolicy`. Gaming tests model inventory removal only after confirmed `done_reason=unload`, then assert request, unload, remaining inventory, verification/completion state, backend inventory status, failure paths, and `physical_vram_reclaimed=false`.
- No production source, T13 file, or root file was edited. Broad T12 suite was not rerun; only the seven changed selectors were run against copied current-root source and patched tests.
