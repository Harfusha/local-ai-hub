# T14 render-order synchronization

Assigned checkout: `C:/Users/Adam/.codex/worktrees/t14-render-order/.local-ai-hub`.
Branch: `codex/sync-t14-render-order-20261006`.
Initial pinned master: `7aa8b00168c03de6f5fccca158ef74fa1c5dfc4d`.
Final pinned observed master: `3c23c33d76c43043d839642c7b0d3e10ea444d67`.
Master is centrally advancing; this handoff describes this immutable snapshot.

## Preservation and merge

- Original HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`, retained by
  `codex/checkpoint-t14-render-order-original-head-20261006`.
- Tracked dirty checkpoint: `3524b558cc560bbf58425f56f98f74dd6cda8675`, retained by
  `codex/checkpoint-t14-render-order-dirty-20261006`.
- Original untracked regression test: committed in
  `ed6b2dbeb80ef98e2f93cb6f54048aa64c588d6e`, retained by
  `codex/checkpoint-t14-render-order-premerge-20261006`.
- Pinned master ref: `codex/checkpoint-t14-render-order-pinned-master-20261006`.
- Final master ref: `codex/checkpoint-t14-render-order-final-master-20261006`.
- Startup had no tracked dirty or untracked files; nothing additional needed saving.
- `git merge --no-commit --no-ff 7aa8b00168c03de6f5fccca158ef74fa1c5dfc4d`
  merged automatically with no unresolved files. Both preservation commits remain
  ancestors. No blanket ours/theirs resolution or new context design was needed.
- Before this note, the entire merged index equaled the pinned master tree.
  Thus Gemini preprocessing, CodeGraph removal and newer safety changes remain
  exactly as observed in master; no runtime or model acceptance is inferred.
- Hunk review: fused evidence sorting still precedes evidence persistence;
  missing receipts still fail closed; original render-order hunk moves existing
  exact lexical blocks to evidence order before RAG append. Master already
  contained both that hunk and the original regression test.
- Initial merge committed as `19e93e2457d85a83f6dfabdc8c8392e256ed4349`.
  Final check found master advanced to `3c23c33d`; a second explicit
  `git merge --no-commit --no-ff 3c23c33d76c43043d839642c7b0d3e10ea444d67`
  also merged without conflicts. The T14 production files and five checked test
  files were unchanged between those snapshots. Merged source/tests/tools equal
  final pinned master. Only this integration note differs.

## Actual targeted checks

Native fallback explicitly authorized after prior terminal Hub failure.
No Hub retries, installs, deployment, full release suite or root/master writes.
Validation owned by this checkout; temporary fixture data remains locally in
`.t14-render-order-validation-pass2/`, excluded by its local `.gitignore`.
Python: `3.13.2`; `PYTHONDONTWRITEBYTECODE=1`; subprocess timeout: 120 seconds.

Passing command (8 passed in 7.50 seconds):

```text
python -m pytest -q --tb=short -p no:cacheprovider --basetemp=.t14-render-order-validation-pass2 tests/test_context_pack_render_order.py tests/test_context_pack_render_perf.py tests/test_context_pack_snippet_budget.py tests/test_context_snippet_budget_audit.py tests/test_context_pack_budget_e2e.py
```

First attempt used `--basetemp=.t14-render-order-validation/tmp`: 3 passed,
5 setup errors (`WinError 3`, missing parent directory). The changed basetemp
removed that setup failure; no source/test changes were made to obtain a pass.
Checks covered fused render order before RAG, intact ranked snippets, stable
repository exclusions, tokenizer budget edges and MCP/HTTP bounded provenance.
`git ls-files -u`: empty. `git diff --cached --check 7aa8b001`: passed.
Unscoped `git diff --cached --check` reported inherited whitespace in incoming
master artifacts and CRLF source; those unrelated files were preserved verbatim.

## Remaining acceptance

Synchronization and preservation are complete; product acceptance is partial.
This scoped run does not revalidate all T14 context or central integration checks.
Pinned master's `docs/WORKTREE_INTEGRATION_STATUS.md` records earlier T14 budget
failures: 128-token error truncation, rollback status fields, older scope/path
fixtures, strict CodeGraph substring assertion and long citation/identity
truncation. They were not rerun or fixed here; see
`handoff/T14-SYNC-INTEGRATION-20261006.md` for the inherited report.
The original render-order fallback leaves lexical text intact when header
matching fails; malformed/duplicate header cases were not independently tested.
Live Gemini/model behavior, daemon rollout and full release gates remain unverified.
Central integration must reconcile any master commits newer than the pinned SHA.
