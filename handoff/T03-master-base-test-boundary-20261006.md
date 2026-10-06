# T03 master-base packet addendum — 2026-10-06

- Current master/root HEAD: `744727887bb1027b1bc464534a1ab0280ddbc9fe`.
- Target `tests/test_mcp_contract_dispatch.py` committed base blob: `64c8c11a93fec6bf487b7613342e17696f4a5ca4`.
- Target current worktree blob: `e53cf0f9c1a8810338b21fbe58b720849b7d2dea`; it retains pre-existing dirty test changes. Expected postimage after only the T03 test addition: `06662c9340d7d1c19582369b37b1bf27b328401d` (SHA-256 `ff84e19726dc633db0aeebaf696d155884139cd2d9bb15833487b433dcaddbbf`).
- Root `git apply --check` for `T03-root-current-path-hints-client-keyword-postfix-20261006.patch` passed against that current dirty preimage; patch was not applied. This is an applicability check, not a clean-master test.
- T03 worktree remains on `ad622f8a90a81e349e94d3402f297f2995e733b2`, with three commits unique to it and dirty changes preserved. No rebase, merge, reset, or cleanup performed.
- No safe task-owned clean master-based test checkout is available in this workflow. Creating another checkout would cross the exact assigned-worktree boundary. Therefore the only test receipt is **candidate-only**: selector `test_mcp_repo_search_passes_path_hints_to_client_keyword`, 1 passed in 5.75s, execution `bdd4446579bd4a54bafabc8441a4ffd9`.
- Root source/test integration remains unperformed. T04 has no exact path_hints keyword-to-HTTP receipt; that hop remains unverified.

References: `T03-path-hints-keyword-end2end-20261006.md` and `T03-root-current-path-hints-client-keyword-postfix-20261006.patch`.
