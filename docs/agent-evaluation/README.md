# Local AI Hub agent prompt evaluation

Reusable prompt suite for testing agent tool use, source grounding, changes, coordination, efficiency, safety, model routing, and end-to-end behavior.

## Files

- [prompts.md](prompts.md): 123 active copy-ready prompts. Cases 076, 080–082, 084–088, 103–104, 107, and 111 were merged into broader cases; see evaluation-key.md for the mapping. For MCP action cases 114–136, give the tested agent the selected prompt, matching action row from mcp-action-coverage.md, exact relevant input-contract rows from mcp-action-contracts.md, and complete live action enum from that session. The source-contract snapshot supplies argument fields; only the live enum proves session exposure. A source-supported read-only action explicitly named by a case may be called once to test a callable-surface mismatch; classify a rejection as UNAVAILABLE for that session, not product removal. Missing fixture values or required argument fields mean affected branch NOT_RUN, never guessed arguments or invalid-action probes.
- [evaluation-key.md](evaluation-key.md): fixture setup, expected behavior, and failure signals. Keep out of the tested agent's context.
- [results.md](results.md): append one evidence-bound record for each run. Keep results separate by agent, Hub build, instructions, and fixture revision.
- [fixtures/](fixtures/README.md): inert synthetic source trees for selected read-only repository lookup cases.
- [mcp-action-coverage.md](mcp-action-coverage.md): source-supported action map with per-run profile availability; a chat attempt is not action execution, and missing/incomplete live enums remain NOT_VERIFIED.
- [mcp-action-contracts.md](mcp-action-contracts.md): source-derived per-action fields, gates, effects, retry semantics and validator branches; schema evidence only.
- [local-model-gpu-cases.md](local-model-gpu-cases.md) and [local-model-gpu-scoring.md](local-model-gpu-scoring.md): fixed paired post-upgrade local-model cases and operator-only scoring key.

The active catalog uses stable IDs with gaps for merged cases. Cases marked as multi-turn, fault-injected, or sandbox-only need their listed preparation before use. New chats/worktrees do not isolate shared Hub memory, leases, queues, quotas, or runtime state. Projectless Codex threads can also access their launching chat through `codex_app.read_thread`; include the isolation harness rule in every run. Resolve required values such as `{{DISPOSABLE_ROOT}}`, `{{RUN_ID}}`, task/session IDs, and media paths from the harness before sending a prompt; never ask the tested model to invent them. If absent, record NOT_RUN. Read-only calls may use an explicitly authorized project/fixture root without a write fixture; state-changing, fault-injected, runtime, and concurrency cases require their own disposable root and isolated Hub state.

The included source trees support selected read-only cases. Fault-injection adapters, complete stale-index staging, disposable write-test repositories, and sandbox runtime instances are still absent. Do not point those scenarios at the shared checkout or production Hub. A profile-gated action remains in the catalog; report GATED/UNAVAILABLE for that run rather than treating it as removed.

## Recording policy

Record observed agent behavior and Hub behavior separately. Link evidence IDs, artifacts, command receipts, and exact run identities when available. Mark unavailable or unrun capabilities honestly; never manufacture PASS or receipts. Append new findings to [results.md](results.md) after the run. Edit the prompt/evaluation key only when the test contract intentionally changes, then update its revision in the run record.

These prompts are a broad practical regression set, not proof of complete correctness or a substitute for feature-specific integration and release acceptance.
