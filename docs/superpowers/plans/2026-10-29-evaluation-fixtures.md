# Evaluation Fixtures Implementation Plan

**Goal:** Provide reproducible, isolated inputs for the blocked evaluation cases and retain authentic evidence boundaries.

**Architecture:** Store inert seed sources and per-case manifests in `docs/agent-evaluation/fixtures/`. Run agents only against disposable copies. Sandbox cases additionally require isolated services, state and genuine verification producers; fixture checks do not substitute for runtime acceptance.

**Tech stack:** Python 3.11+, standard library, pytest and the existing Local AI Hub APIs.

**Spec:** `docs/agent-evaluation/prompts.md` and `docs/agent-evaluation/evaluation-key.md`.

## Global constraints

- Preserve dirty user files and production state; no synthetic receipts or inferred live-process identity.
- Each case records its seed revision, workspace, actual commands, failure and repair evidence.
- Intentionally faulty seeds stay outside normal test discovery and are never executed in the tracked source directory.

## Tasks

- [x] 090 seed: old checkpoint contract across server, tool adapter, SDK and prompts; exact specification and loopback HTTP oracle. Agent execution remains separate.
- [x] 091 seed: independent backend/TypeScript scopes and shared integration oracle. Actual delegated execution remains separate.
- [ ] 092: original isolated seed and manual oracle `3/3` retained. Earlier work orders failed no-diff; `wo_a3e89f5357474c229c8e` generated a patch but failed `corrupt patch at line 35`, before validation. `%TEMP%` root was rejected as ephemeral; stable Documents root was accepted. Fixes: explicit `task_type=code`, code-specific diff-only prompt, and `git apply --recount` across preview/check/apply. Focused regressions pass (`3 passed`); restart/live rerun and receipt remain open.
- [ ] 093: isolated builder produced a real merge conflict between both commits. `local_ai_work` accepted `wo_e3b72d6918404f639bdf` but failed after four no-diff model calls. Manual reference resolution created merge commit `c8c0663068abaecb2f84ff7c2a0a1fa2a1011ee9`; `test_pricing` passed. Checkpoint remains simulated; real interruption/resume is unverified.
- [x] 094 seed: deterministic valid, invalid, slow and cancelled inputs; copied seed fails its oracle, and a repaired reference copy passes. Agent execution remains a separate task below.
- [x] 095 seed: existing disposable target, failpoint before replacement and byte-preservation oracle; repaired reference copy passes. Agent execution remains separate.
- [x] 096: existing 5.0 → 5.1 upgrade/rollback evidence is retained. A second isolated 5.1.0 → 5.1.2 run seeded one real file/chunk, observed the candidate supervisor reject the old fingerprint, verified byte-identical RAG DB/WAL/SHM and archived state, explicitly rebuilt the index, and passed the candidate HTTP smoke with owned process-tree cleanup. The deterministic embedding is fixture-only; this does not prove model quality or production data preservation. Evidence: `%TEMP%\local-ai-eval-096-rag-upgrade-20261030-002`.
- [ ] 098: isolated MCP/HTTP/dashboard displayed one real task identity; reusable sandbox runner also supports noninteractive execution and resumed a real task across restart. An authentic validation receipt producer and terminal completion remain outstanding.
- [ ] 100: actual disposable seed produced a dirty foreign change (`FOREIGN.md`) and its oracle exposed both intended defects (UTF-8 export error and missed cancellation). A separate repaired reference copy passed oracle `2/2`. Run a real delegated task in the isolated Hub, preserve the dirty foreign change, and verify genuine resumable Agent OS task/model/interruption evidence; no receipt is synthesized.
- [ ] Run each repaired fixture through the intended agent workflow; report fixture results separately from integrated live Hub acceptance.

## Remaining Hub findings

- [x] Wire diff citation grounding into `LocalAIServices.review` and label unstructured `review_diff` output unusable; model conclusions remain advisory. Public-boundary targeted tests pass; integrated/live evidence is still required.
- [x] Require explicit boolean `success` in each batch result and preserve explicit item IDs. Reconcile with the concurrent batch cancellation change during integration.
- [x] Hunk-aware counts use LF/CRLF framing; Unicode separator regressions are included. Full integrated pytest passed after this source change: 13,091 passed, 105 skipped, 0 failed.
- [x] Untracked review uses bounded UTF-8 pages and digest checks; full integrated pytest passed. Quoted paths, control whitespace and paths outside the bounds remain intentionally excluded. A dedicated live review call is still separate from the source/test result.
- [x] Host-native completion remains fail-closed: this host command interface provides exit status but no authenticated `command_execution_record.v2` identity. No receipt was synthesized; producer support remains an external host boundary requirement.
- [ ] Verify a successful real closed delegation and actual cancellation on the integrated candidate. Execute-mode selective test/build permissions remain deliberately unsupported until enforced safely.
- [x] Integrated the candidate into master, preserving unrelated dirty owner changes. Full pytest and release checks passed; restart verification separately covered listener/service health, seven-tool MCP surface, RAG read and local model request. Dashboard task identity and authentic completion remain separate scenario gates.

## Boundaries for remaining work

- The current host command tool supplies an exit status but no trusted `command_execution_record.v2` identity. `record_authentic_native_receipt` checks an existing broker record against task, owner, root and criterion; a caller-provided status cannot replace that record. A supported host attestation must originate at the trusted host boundary and bind the actual command execution and candidate revision before completion may rely on it.
- `classify_verification_command` classifies evidence, not process capabilities. Do not use its lexical labels as enforcement of selective test/build permissions. Until an enforceable execution boundary exists, reject selective execute-mode permissions before enqueue.
- RAG startup rejects mismatched index fingerprints, including application-version changes. Case 096 now proves one-file nonempty recovery in a disposable sandbox, including DB/WAL/SHM preservation and explicit rebuild. It does not prove preservation of every production RAG record or tenant conversion.
- The user later authorized testing, with the constraint that the full suite runs only after fixes and fixtures are ready. The final full suite passed on the integrated candidate before the additional fixture-only case-096 runner; run the full suite once more after remaining fixture work is complete. Scenario agent workflows and dashboard/receipt boundaries remain separately tracked above.
- Latest live work on 092/093/100 exposed two more model patch failures: wrong source context and malformed unified-diff syntax. WorkOrchestrator now retries patch failures with exact bounded UTF-8 preimages for safe in-root paths; private-key paths are excluded. Five focused regressions pass. The 092 fresh-seed work was still executing at its one allowed wait; 093/100 failed before validation. Restart the candidate only after isolated activity is quiescent, rerun fresh 092/093/100, then run the full suite once at the end.
- Current service evidence: `tools/service.py status` says supervisor 15224 and Hub 50284 are ready/running, and MCP status is online. `tools/hubctl.py status` contradicts this with Offline (stopped); investigate/update the operator-facing status path before claiming the whole running Hub is verified.

## Integration preview 2026-10-30

- **Preview stale:** the worktree `services.py` changed after the recorded preview to add paged untracked review and interior-space path handling. Recompute against current bytes before any integration.
- Main later advanced to `935d3e61ac69b2759be9cf8b2ec09420fa27fda2`; commits since `704f75ff` change only `docs/agent-surface-audit.json` and `docs/release-evidence-5.1.0.md`. Fresh byte hashes of all four overlapping main/worktree paths match the `704f75ff` preview inputs. This does not validate the combined code; recheck before integration.
- Main subsequently advanced to `704f75ffab4f94c7a0309f3e8084c552d3430d02`. A new disposable three-way preview against that HEAD found the same single `services.py` conflict; `mcp_server.py` and the two prompt files merge without textual conflict. These are the only tracked paths changed on both sides; no untracked worktree files collided with paths in main at the time of inspection. The existing user-owned results document and `config.runtime.toml.lock` remain uncommitted and must be preserved.
- Current preview: `%TEMP%/local-ai-merge-704-i2xk4yg1/services.integrated-preview.py`, SHA-256 `0347c356c31483df0db957e0d6604860936ce02bf74bb523024e66e8dc505bf2`. It preserves batch cancellation, strict success and skipped IDs, and adds review cancellation checks. This preview is not integrated or validated; recheck exact inputs and ownership before use.
- Main HEAD `a6593e4a1c9fa973b8292a4517f81874a656d485` differs from worktree baseline `6c7200a9c1b71554ebe368b8722a6757d94c0282` by a documentation commit; both checkouts also contain distinct uncommitted changes. All must be re-read before integration.
- A disposable three-way preview normalized CRLF to LF solely for comparison. The MCP adapter and both prompt files merge without textual conflict. `services.py` has one conflict: preserve the main checkout's cancellation result and the worktree's strict boolean-success check together.
- Semantic interaction: cancellation creates results for unsent batch items; those results must retain the original explicit item IDs. Prepared regression `test_cancelled_batch_preserves_ids_for_unsent_items` has not been run and relies on the main checkout's cancellation implementation. A candidate resolution exists only in `%TEMP%/local-ai-merge-preview-acp5e0ef/services.resolution-with-cancel-ids-preview.py`, SHA-256 `8d09386f8325054abfdbff3befc497d9f1d5d2bc71974951772e79fbd09400b9`; it is not integrated or validated.
- The integrated preview also shows that cancellation during diff collection can otherwise produce a successful AST result. Prepared unrun regression `test_ast_review_cancelled_during_diff_collection_does_not_succeed` and a preview with cancellation checks plus batch-ID preservation are in `%TEMP%/local-ai-merge-preview-acp5e0ef/services.integrated-preview.py`, SHA-256 `0347c356c31483df0db957e0d6604860936ce02bf74bb523024e66e8dc505bf2`. Neither is validated; other cancellation boundaries still require review.
- Preview inputs: main `services.py` SHA-256 `f7b07a1e1c4c22b60f26b471a1ae0429a7c214e2fb8d7d0044383664ef5f324e`, worktree `services.py` SHA-256 `2946dc99e98bda318a83ac22c1b92fefdf906b7ab07170b6b6ac5a931eff8820`. Never apply a stale preview to changed files; recompute it under exclusive ownership.
