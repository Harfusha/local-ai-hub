# T04 → current root read-only integration audit

Date: 2026-10-01 (Europe/Prague)

## Scope and baseline

- Candidate: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`, branch `codex/t04-integration-2b33602`, HEAD `3658d5056354849ddf17883ed04f807f16cc44c1`.
- Current integration target: `C:\Users\Adam\.local-ai-hub`, branch `master`, HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`; common base `2b33602adef0d030fea66cdcc04ca742c60b2e32`.
- Root worktree is heavily dirty (140 tracked paths in diff stat, plus untracked items). This audit changed no root files, did not merge/cherry-pick, clean up, or run tests.
- Reviewed every T04 commit after the common base: `e2dcd2c899ac87b204ac66d84e2c687140bddad2`, `f305ec6a8f4200b1fd9a2bde5048f43bd508db19`, `3658d5056354849ddf17883ed04f807f16cc44c1`.

## Commit dispositions against the current root worktree

| T04 commit | Disposition | Evidence and boundary |
|---|---|---|
| `e2dcd2c` — public API contracts | **Already present**, with one docs-only sub-area deferred. Root `client.py::HubClient.list_tasks` serializes `query`; HTTP validation no longer rejects unsupported chat-completions payloads before route handling; POST `/api/resolve_imports` defaults to `auto`. Root `docs/HTTP_API.md` documents task-query filters. Current root tests include `test_t04_current_root_acceptance.py` and `test_agent_task_query.py`. The expanded `_desc_rag`/`_desc_work` text from the commit does not match current root descriptions; defer those prose hunks pending current capability/owner review. Do not cherry-pick the commit. |
| `f305ec6` — task-list query filtering | **Already present**, implemented differently in current root. Root forwards query through HubClient, MCP task-list, GET and POST routes, and TaskStore. The root TaskStore uses the existing indexed search and shared normalized fields; this is not a safe place to replace with T04's linear scan. Root HTTP API docs and `tests/test_agent_task_query.py` cover the behavior. |
| `3658d50` — bounded query and tenant listing | **Already present** in current root. Task query scan has the 10,000-candidate cap and `query_truncated` result propagation. `ArtifactStore.list()` hashes tenant identity and filters both v2 and legacy tables while retaining newest-first order, limit 100, and metadata-only projection. `tests/test_artifact_tenant_isolation.py` exists; it was not run in this current-root audit. |

No safely missing unique production change was found, so no patch was generated and there is no patch SHA or apply-check. The stale/different MCP description strings are deliberately deferred; no T04 whole-file transfer is safe.

## Existing validation receipts and limits

- T04 candidate receipts: assigned nine-file suite **132 passed in 26.57s**, log SHA-256 `7CC3BE41A4D4E4CD8471DDEE0287A3BD8FF5F3318D80E56D2A10277B70E03403`; public API/conversation/query/inventory selectors **39 passed in 43.83s**, log SHA-256 `9FC7FD1F9D623B9503C798DFDA70F15AF5F0E8A945830D12CE59E3C6335178A5`. These are candidate results, not current-root runs.
- Earlier T20 root receipt recorded **30 passed in 84.98s**, but it predates the current dirty root source snapshot: current `http_server.py` SHA-256 is `2D5AF917C8F25404BC6D6421E1C277DABAD8419FC4E62EE61B97E02C71819CC8`, while that receipt recorded `6B6E79EF059941592B532FF0F7C617A97770D3C31F923C00EB254D28169553A2`. Do not present 30/30 as validation of the current worktree.
- Current root was checked statically only. Shared test slot belongs to T20; no tests were started.

## Preservation

No T06, T07, or T12 hunks were adopted or altered. `/api/context/pack` ownership was preserved. T04 candidate remains untouched; root remains untouched by this audit.

## Current root file hashes inspected

- `src/local_ai_hub/client.py`: `DDB55EDA5F1949B19A876106E056A0C92992AA4D00BF711D85EFB67D3809A562`
- `src/local_ai_hub/agent_tasks.py`: `8CD475518266D1318D8F6DC0BA76896028C82A212786DB2423639ED46C23A8FF`
- `src/local_ai_hub/artifacts.py`: `BBDB461575A015A7C64624ABA6E90AD8A62B646C1E273714B2C3780D6FE8C7A7`
- `src/local_ai_hub/http_server.py`: `2D5AF917C8F25404BC6D6421E1C277DABAD8419FC4E62EE61B97E02C71819CC8`
- `src/local_ai_hub/mcp_server.py`: `CA57DCD703F6C7E85897A7E805556EAFD46A351C51CF4BE8833962FEEE64D45B`
- `docs/HTTP_API.md`: `2D14B07658C527624913636B7891D22F994DBACE6C9E537B0CEB07649A94FF25`
- `tests/test_agent_task_query.py`: `0F5CE4A1805C18919DFF1360729E510786C8E99B725FB690A69C278E2D53A86B`
- `tests/test_artifact_tenant_isolation.py`: `15F7B981EFCE1D0939FE7A3C34A5F2822B1AB5CB8E185857206A3EB68F17D992`
- `tests/test_t04_current_root_acceptance.py`: `F2356F8E15D915966BF76CDD9CDFE04CC9A78E6FA59D62D37AF63AF74A137A17`
