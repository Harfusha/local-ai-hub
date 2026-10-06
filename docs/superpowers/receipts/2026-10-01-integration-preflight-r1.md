# Orchestrator integration preflight r1

Observed: 2026-10-01 14:50:58 UTC. Root: `C:\Users\Adam\.local-ai-hub`.
HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`; existing dirty changes preserved.
Owner: orchestrator, this receipt only. T20 owns root source integration and serialized validation.
Hub ignored under the user's explicit unavailable instruction; no startup or polling.

## Exact bounded check

For each existing artifact below, SHA-256 was measured before and after:

```text
git apply --check --whitespace=error -- <absolute artifact path>
```

All eight artifact hashes stayed unchanged during this observation. No patch was applied.
This checks applicability/whitespace only, not transformed-source parsing, behavior, root acceptance or release.

| Owner / artifact | SHA-256 | Exit | Decision |
|---|---|---|---|
| T08 `t08-root-current-identity-inference-blackboard.patch` | `F47991E39CB7D5C69ED7B2F3096360ADF3F602E3EA22B85FDDFED89B9D6D4178` | 0 | Applicable; candidate memory/identity/drain receipts are not integrated root acceptance |
| T16 `T16-namespace-root-current.patch` | `26C83E5B29E81EC4B8A011806D259399EB273E85CBAFC34616540D4ED7369DC8` | 128 | Strict check rejects new blank line at EOF, patch line 1188; owner must issue a new immutable version |
| T16 `T16-http-lease-routes-root-current.patch` | `F22B5290486857EAC823F408B4558C89A308180B26C193EA0F8D6B7B5D9A6D0B` | 0 | Depends on namespace core `waits` seam; independent spec review dispatched |
| T13 `T13-rootcurrent-app-context.patch` | `2C85860070141AFFA4906CF3A57642AF57207FAC7DF25AAC303041BD0E1472E2` | 0 | Applicable; actual T08 tracking and T12 service compatibility still require joined root proof |
| T13 `T13-rootcurrent-mode-cancellation-regenerated.patch` | `036DD510B7A20FBECFBEA8B456A0249826A5A1CFE24EA95F5C24103199636D55` | 0 | Applicable HTTP receipt delta; not full gaming cleanup proof |
| T04 `t04-sse-disconnect-root-current.patch` | `D17394EB216F92A783555CCF420435231DA268A75D1E0DFC0D88A33ED8A32271` | 1 | Forward hunk mismatch at HTTP line 1484 and SSE test line 40; current source already contains the correction/assertions, so do not reapply or report lost work |
| T06 `T06-T09-validation-receipts.patch` | `58EC1AE45611BA89DE79D38B95DF37BF7B1A3AF41FD826AE919D551765895F42` | 1 | Broker preimage mismatch at commands line 2210; owner must reconcile only remaining owned hunks |
| T12 `T12-O2-root-current-r3-20261001.patch` | `D108A873AC95E15E0D2F3111F078607DCEBE741C0BD9CD47ED41B375F5059B5A` | 0 | Immutable r3 metadata agrees; r3 behavior unverified, independent review resumed. Earlier 12 pass / 6 fail used a different artifact |

## Artifact locations

- T08: `C:\Users\Adam\.codex\worktrees\t08-agent-os\.local-ai-hub\artifacts`.
- T16: `C:\Users\Adam\.codex\worktrees\t16-orchestration-recovery\.local-ai-hub\handoff`.
- T13: `C:\Users\Adam\.codex\worktrees\t13-operational-mode\.local-ai-hub\handoff`.
- T04: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub\handoff`.
- T06: `C:\Users\Adam\.codex\worktrees\t06-safe-commands\.local-ai-hub\handoff`.
- T12: `C:\Users\Adam\.codex\worktrees\4816\.local-ai-hub\handoff`.

## Root-source identity at observation

| Path under `src/local_ai_hub` | SHA-256 |
|---|---|
| `services.py` | `1556EDBE4336E1D0FECDAC86D79593AB6F62BE12A1F13841537CAC453721DCC1` |
| `app.py` | `4050325BCC0F319941A0A183C2DA7CA529A33820236062A39E86E817DCB7705E` |
| `commands.py` | `1B27F83872D439B9167C9B2323BF4BE71279E688DF6094C002CA20934F761B67` |
| `http_server.py` | `15BD92CE83A7FB472AAC4581F1A5FAD42ECF6E303C73C7DBC463E05A4528F57F` |
| `leases.py` | `BF56E69ABC46DCF1B9CC4B4778251618FD1EA243329D58E48BEFE833DB1AF1CB` |
| `agent_events.py` | `02A25102B888B23FE99B8C508F59AEDD846BA24FD38A268BCC6893B0877E0A38` |
| `work_orchestrator.py` | `BA24529B8F330248A7F1A8A14847244778B74CE2A201B5DA0D7A928367130093` |

These are observations, not a lock on the live integration checkout. Recheck affected preimages immediately before integration.
T04 root contains `stream_success`/`stream_error` and `finished_stream_request` assertions. A supplementary reverse check emitted no T04 diagnostic; its individual exit was not separately captured, so it is not claimed as a verified reverse-check result or test receipt.
Owners T04/T06/T16 and integrator T20 received exact failures. Do not overwrite already-published versions during review.
No runtime suite, shared port, model, GPU or 100k benchmark was started by this preflight. Full T01–T21 acceptance remains open.
