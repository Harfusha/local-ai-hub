# T09 pinned artifact review r1

Owner: independent read-only Dirac review; orchestrátor records and coordinates. No tests/imports/patch application by reviewer. Root HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a` unchanged during review.

## Exact immutable artifacts reviewed

Candidate `C:\Users\Adam\.codex\worktrees\t09-t08-receipt-fixture\.local-ai-hub\handoff`:

| Patch | SHA-256, stable before/after |
|---|---|
| t09-command-provenance-root-current.patch | `80BD075DE73C82CD3AE1072F724C27B45E9EF461FEF83B171AD5D782602011F9` |
| t09-command-provenance-tests-root-current.patch | `2C2D75FB2FEB023B1B4CC40B90BDDF3160E365BF797C1B36F8E2D8C6F1DDC0B1` |
| t09-project-binding-adapter-root-current.patch | `0A1F7F9ED2A3EBD026D6AF54B6E4F5992EDD6D987CDBA07E9794785702A66EE2` |
| t09-route-acceptance-root-current.patch | `BEBA95E4F71D74AF556B4827F173CEDDA8CDE16979736976AECC9C02DB892471` |
| t09-worktree-ownership-root-current.patch | `CFE2EE69189A3556A77BF9742AC70DE91BAB16156549730A152608690D0B6834` |

Result: **NOT SPEC-COMPLIANT, HOLD integration of this bundle**. Tenant/artifact freshness checks, string-command hash binding and non-forced dirty worktree preservation are positive, not sufficient.

## Critical

1. Adapter patch line 39 trusts checkpoint `worktree_path`/`repo_root`. Root `agent_tasks.py:1489` checkpoint accepts replacements, HTTP `http_server.py:3256` accepts caller state_data. A caller can select a weaker project's completion rules. Memory context can likewise be replaced with empty items/warnings, bypassing audit at `agent_tasks.py:573`. T09 owns authoritative project/worktree binding; T08 owns immutable server-injected memory context. Protect before any checkpoint/event mutation.
2. Alternate HTTP transition path (`http_server.py:3189`) invokes `TaskStore._verify_completion` (`agent_tasks.py:1196`) without configured commands/config digest, bypassing the new provenance checks. Root selection at `agent_tasks.py:1124` differs from adapter worktree-path selection. T09 must route all terminal completion through one trusted gate, including worktree configuration.

## Important

3. Provenance patch line 103 checks expected execution hash only for string command definitions. Structured argv can receive appended `--help` and exit 0 without tests. Alias/digest plus syntactically valid hash are not execution proof. T06 owns trusted resolved argv, permitted arguments and private environment identity producer; T09 validates the same contract.
4. Provenance patch line 89 allows a configured source alias such as `check` to accept a non-command source-review receipt. Existing root special case at `agent_verification.py:505` only singles out literal `lint`. Require command-backed proof for every configured command alias.
5. Ownership patch line 165 does not provide `get_git_worktree_ownership` or `expected_metadata`, required by current root `agent_tasks.py:1744/1793`. Reconcile actual API narrowly, preserve dirty files and ownership checks.
6. HTTP `http_server.py:3207` resolves opaque context repository ID as filesystem root/revision before adapter binding. Resolve trusted physical task root first for omitted-root completion.

Minor: classifier inspects every operand stem, so `echo pytest` becomes test and `py.test` is missed. Parse executable/module positions.

## Verification required

New immutable versions with genuine RED/GREEN regressions: forged project root and memory context, direct task_complete and alternate transition, structured argv/environment substitution, configured non-lint alias, opaque repository context, actual owned cleanup consumer. Joined real broker, persisted receipts, HTTP and terminal gate; no dropped verifier kwargs or forged passing receipts.

Prior 68 verifier passes and adapter-only 3 passes do not cover these bypasses. Actual T06+T09 overlay still rejects lint for missing trusted alias/digest; preserve that rejection. T20 is root integrator, old bundle remains held. All owners notified; full T09 goal stays active.
