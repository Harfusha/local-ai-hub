# T14 snippet checkout synchronization

Assigned checkout: `C:/Users/Adam/.codex/worktrees/t14-snippet-isolated/.local-ai-hub`.
Branch reused: `codex/sync-t14-snippet-isolated-20261006`.
Master observed exactly once and pinned: `3c867cc72e04e26ab609d34f8a579e909a8086d9`.
This includes T12 `8ab07a6c` and T14 render-order `53198c04`.
No subsequent master lookup or moving-master chase was performed.

## Preservation

Startup had no tracked dirty or untracked files; prior preservation was reused.
Original source HEAD: `8c945bdeb5f92270613e53b307b6f646a4f0e21b`.
Tracked dirty checkpoint: `9a40aeca4c84d28cdbe56243f45bfa410d6f216e`.
Premerge HEAD with original untracked test: `ee8ba503dc192d46f2a1e0fcca9ca7366b1cf4aa`.
Existing `codex/checkpoint-t14-snippet-isolated-dirty-20261006` remains untouched.
Additional recovery refs, created through this assigned checkout only:

- `refs/checkpoints/t14-snippet-isolated-original-head-20261006`: original source HEAD.
- `refs/checkpoints/t14-snippet-isolated-dirty-20261006`: tracked dirty checkpoint.
- `refs/checkpoints/t14-snippet-isolated-original-20261006`: premerge HEAD with test.
- `refs/checkpoints/t14-snippet-isolated-master-20261006`: pinned master.

## Manual merge decision

`git merge --no-commit --no-ff 3c867cc72e04e26ab609d34f8a579e909a8086d9`
produced one content conflict in `src/local_ai_hub/repo_tools.py`.
Both hunks were inspected. The old isolated implementation checked the growing
serialized envelope per candidate and skipped oversized ranked candidates.
Current master instead budgets context text, stops at the first non-fitting
ranked candidate, renders in linear time, and accepts current directory/exclusion/
force-include controls. HTTP/MCP applies the separate serialized response budget.
The reviewed master hunk was retained, rather than restoring the old design.
No whole-file ours/theirs resolution was used.

All production source, MCP, tools, existing docs and ignore rules equal pinned
master byte-for-byte after reconciliation. Thus incoming Gemini preprocessing,
CodeGraph removal, current `/api/context/pack` and safety fixes are retained.
No live provider availability or model-quality claim follows from that equality.
The original isolated test's assertions remain unchanged. Added harmony test
checks intact ranked-prefix provenance, no skipping a larger middle candidate,
and transport-envelope bounding with context identity and evidence IDs retained.

## Actual checks

Native fallback authorized by user after prior terminal Hub failure; no Hub retry.
Validation side effects owned by this checkout. Python 3.13, bytecode disabled;
pytest cache disabled; subprocess timeout 120 seconds for each invocation.
Fixture state and XML receipts stay under ignored `.t14-sync-runtime-20261006/`.

1. First targeted attempt: 3 passed, 7 setup errors, missing fixture parent
   (`WinError 3`). Created only the local ignored parent directory.
2. Fresh `snippet-reconcile-pass2` run: **11 passed in 8.99 seconds**.
   Modules: `test_context_snippet_budget_isolated.py`, `test_context_pack_render_order.py`,
   `test_context_pack_render_perf.py`, `test_context_pack_snippet_budget.py`,
   `test_context_snippet_budget_audit.py`, `test_context_pack_budget_e2e.py`.
3. Fresh `snippet-http-memory` run: **4 passed in 25.00 seconds**.
   Modules: `test_t14_context_pack_agent_memory.py`, `test_t14_mcp_context_http.py`.
4. Commands used `python -m pytest -q --tb=short -p no:cacheprovider`, distinct
   `--basetemp` paths and corresponding `--junitxml` paths for successful runs.
5. `git ls-files -u`: empty. Scoped `git diff --check <pinned-master>`: passed.
   Production tree equality verified with `git diff --cached --quiet <pinned-master>`.
   Final handoff requires pinned-master and preservation ancestry plus clean status.

## Remaining acceptance and exact delta

Only this note and `tests/test_context_snippet_budget_isolated.py` differ from pinned
master. Original dirty implementation remains recoverable in its checkpoint.
Direct repository packing is not a general serialized-envelope guarantee; the
public transport provides that guarantee. This behavior difference is intentional.
Historical T14 issues recorded in `handoff/T14-SYNC-INTEGRATION-20261006.md` remain
unverified here: 128-token diagnostic shortening, rollback error fields, old
scope/path fixtures, CodeGraph substring assertion and long identity/citation
truncation. No expectations were weakened and no unrelated fixes attempted.
Full release suite, live Gemini, daemon rollout and broader product acceptance
were not run. Agent sidecar audit could not start because agent limit was reached.
Token-economizer setup script was absent; no tooling installation was performed.
No stash, reset, clean, new worktree/chat, push, root checkout edits or master-ref writes.
