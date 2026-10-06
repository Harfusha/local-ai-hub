# T17 auxiliary test import handoff

- Root HEAD preimage: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
- Target: `tests/test_t17_auxiliary_formats.py`; preimage SHA-256 `A8D4A66102C18FA1E8F40687008BFB34F9A6B475F57120D238B3BF091A373A01`.
- Patch: `t17-auxiliary-pytest-import-root-current.patch`; SHA-256 `B73E23D6473CDF36BE29D84715FA3C1B97DBE60D77DF0B29952E2E69067392CE`. One-file import-only change: add `import pytest` for existing `pytest.skip` at line 177. Root not modified; T20 owns integration. Other vision/browser hunks untouched.
- Static AST check: PASS; proposed module parses and binds `pytest.skip` through import.
- `git -C C:\Users\Adam\.local-ai-hub apply --check -- <patch>`: PASS.
- Exact selector: `tests/test_t17_auxiliary_formats.py::test_generated_typescript_mocks_parse_as_esm`. Not run.
