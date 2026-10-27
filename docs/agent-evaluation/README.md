# Local AI Hub agent prompt evaluation

Reusable prompt suite for testing agent tool use, source grounding, changes, coordination, efficiency, safety, model routing, and end-to-end behavior.

## Files

- [prompts.md](prompts.md): 100 copy-ready prompts. Give the tested agent only its selected prompt and ordinary environment instructions.
- [evaluation-key.md](evaluation-key.md): fixture setup, expected behavior, and failure signals. Keep out of the tested agent's context.
- [results.md](results.md): append one evidence-bound record for each run. Keep results separate by agent, Hub build, instructions, and fixture revision.
- [fixtures/](fixtures/README.md): inert synthetic source trees for selected read-only repository lookup cases.

Start with the 20-case pilot in [prompts.md](prompts.md). Cases marked as multi-turn, fault-injected, or sandbox-only need their listed preparation before use. New chats/worktrees do not isolate shared Hub memory, leases, queues, quotas, or runtime state. Projectless Codex threads can also access their launching chat through `codex_app.read_thread`; include the isolation harness rule in every run.

The included source trees support selected read-only cases. Fault-injection adapters, complete stale-index staging, disposable write-test repositories, and sandbox runtime instances are still absent. Do not point those scenarios at the shared checkout or production Hub.

## Recording policy

Record observed agent behavior and Hub behavior separately. Link evidence IDs, artifacts, command receipts, and exact run identities when available. Mark unavailable or unrun capabilities honestly; never manufacture PASS or receipts. Append new findings to [results.md](results.md) after the run. Edit the prompt/evaluation key only when the test contract intentionally changes, then update its revision in the run record.

These prompts are a broad practical regression set, not proof of complete correctness or a substitute for feature-specific integration and release acceptance.
