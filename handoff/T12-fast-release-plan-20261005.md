# T12 fast release plan — 2026-10-05

Scope: existing T12 assignment in the registered candidate `C:\Users\Adam\.codex\worktrees\4816\.local-ai-hub`, HEAD `933c0129079fcc0c894a71fe842cbbb5e6ad7285`. This plan preserves all inherited dirty state. It does not authorize root edits or tests, change T14 `/api/context/pack` ownership, or resolve other owners' code.

## Release-critical acceptance — keep in scope

The T12 master-plan acceptance remains the gate. Fast release order:

1. **Correctness and safety:** profile-aware routing; stable model reuse and bounded load switching; VRAM admission after unload; request deadlines through queue/load/generation; cancellation releasing capacity and child/socket resources; fail-closed inventory and truthful errors.
2. **Runtime behavior:** bounded overload/backpressure; batch stable order, per-item results, partial failure, bounded concurrency; fallback reports selected model/backend and quality change, honors cloud opt-in and quality floor.
3. **Quality and performance evidence:** fixed evaluation corpus for reason/review/compress/complete/scaffold; validate structured output; compression preserves facts, evidence and uncertainty; measure latency and VRAM for every required profile.
4. **Required profiles and scenarios:** integrated, balanced, high, max; successful overload, cancellation and fallback scenarios. Synthetic/model-free tests remain supporting evidence only, not live acceptance.
5. **Release integration:** T20 must reconcile shared-root dirty fingerprint/count and owner-packet preimages before root integration or root validation. Keep T14's context-pack scope untouched.

No acceptance item above is deferred. Existing candidate receipts (56-pass routing/availability/quality suite; 24-pass routing/policy suite; targeted admission selector 1-pass; prior CPU-mocked VRAM selectors 2-pass) are useful offline evidence only.

## Explicitly deferred polish

- **Optimization claims and baseline comparisons:** deferred because T02 baseline artifact is absent. No savings, speedup, or improvement claim until a valid paired baseline exists.
- **Extra model families, extra hardware, or broader sweeps beyond the four named profiles:** deferred as expansion beyond the current acceptance matrix. Do not substitute these for any required profile.
- **Cosmetic documentation or UI polish outside the generated-policy parity and install/update requirements:** deferred; docs ownership remains with T19 where applicable.

## External blockers and next actions

- Registered candidate is present. Current `repo_state`: 42 changed paths, fingerprint `065e0ef6953b220617755d8de88f1ba328a422801cd93eed70be7a91a6958f1d`; HEAD unchanged at `933c0129079fcc0c894a71fe842cbbb5e6ad7285`.
- Shared-root validation stays paused: T20 must resolve the disputed 379-vs-452 dirty count/fingerprint. I sent T20 the candidate identity, current receipts and coordination request; do not integrate any packet before T20 replies with reconciled preimages/ownership.
- T20's current recovery turn reports its registered checkout unavailable; T02 reports its candidate unavailable. T02 baseline and benchmark/validation slot remain unavailable.
- Only one physical machine/profile is available: RTX 4060, balanced. Integrated/high/max live evidence cannot be fabricated from synthetic harnesses or inferred from configuration.
- Next safe step: continue candidate-only source acceptance that does not touch `services.py` shared ownership or `/api/context/pack`; once T20 provides a valid slot and reconciled root identity, prepare or refresh immutable owner packets against those exact preimages, then run only the unique approved selectors.

Status: **T12 incomplete**. This note defers only non-release polish and optimization claims; it does not waive T12's live acceptance gates.
