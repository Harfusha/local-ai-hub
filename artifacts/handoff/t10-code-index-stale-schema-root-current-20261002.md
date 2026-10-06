# T10 CodeIndex stale-schema gate — root-current handoff

Root T20 HEAD: `01df56605ccf484ebfe2808ac60d696c4e81dffc`. Root `code_index.py` preimage SHA-256: `17381446B55B80D28C06387FD972CC907CE2F5E9D01506FBD5955080D90D1741`. Root was not edited.

## Finding and safety boundary

`CodeIndex.db_path` is `state_dir/code-index.sqlite3`; its tables hold only derived repository hashes, symbols, references, edges and parser blobs. `app.py` wires durable `AgentStateStore` and Blackboard to separate `state_dir/agent_state.sqlite3`. Proposed guard raises on stale `files.analyzer_version`, using existing CodeIndex-only archive/rebuild path. Rename/rebuild failure raises again and fails closed. No state directory or AgentState file is deleted.

## Patch and evidence

- [Root-current patch](t10-code-index-stale-schema-root-current-20261002.patch) — SHA-256 `BB9B28E7EA1EDF77FF0C43F927490BC868F39266B883D44E21567267812F0C64`.
- [JSON manifest](t10-code-index-stale-schema-root-current-20261002.json) — exact root/candidate preimages and postimages, test hashes, slot status.
- `git apply --check --whitespace=error` against temporary overlay with exact root preimage passed; patch applied in overlay. Root postimage SHA-256: `73BE2A44010E3EF9BA8367CAC7C99D1DBA4F2DEB7DFA3EACD4A2D4FE361BC00B`.
- RED before code: both new tests failed for expected stale-schema behavior.
- GREEN candidate-only: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_code_index_schema_rebuild.py tests/test_t10_ast_impact_acceptance.py::test_batch_rename_and_delete_remove_stale_call_edges` — **2 passed in 0.37s**; candidate import explicitly verified. Earlier combined selector including existing rename/delete regression passed **3 in 0.55s**.

New tests verify cache-only rebuild/current indexes, byte-identical `agent_state.sqlite3`, fail-closed archive failure, and that import resolves to the candidate worktree module. Root release-contract test remains unrun for T20's coordinated slot. No benchmark run.
