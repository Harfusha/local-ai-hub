# T12 acceptance delta — 2026-10-06

## Identity and ownership

- Assigned candidate: `C:\Users\Adam\.codex\worktrees\4816\.local-ai-hub`
- Candidate HEAD/base: `933c0129079fcc0c894a71fe842cbbb5e6ad7285`
- Master comparison: `b947d76fdfb7ed592b72e55587d5c83cfa352c35`
- Candidate evidence fingerprint after the focused receipts: `a5168f8e91c71a3a6bb1fa5008720862242a90838916987d7fa89c5f500b1cf1`
- This acceptance delta is add-only. No source, shared `services.py`, root, or T14 path changed.
- Existing source/config/docs/test dirty state remains mixed/inherited. No unrelated owner changes are attributed or merged here.

## Receipted candidate contract results

1. Model routing/config/prompt/policy parity: **24 passed in 1.73s**, exit 0. Exact command, source/test blob pins, and scope are in `T12-routing-policy-blob-receipt-20261006.md` (SHA-256 `7E3F6DACD81A2A403016480DEC6CE3F1A92041405E62ED2844B330D8015BB3C6`).
2. Router, local availability, completion routing, quality/fallback contracts: **56 passed in 0.88s**, exit 0. Same receipt pins exact relevant test blobs.
3. Focused batch contract selector: **2 passed, 33 deselected in 0.19s**, exit 0. Exact command and source/test blob pins are in `T12-routing-batching-receipt-20261006.md` (SHA-256 `A9D4C7082045A27EF2CEA1AF1C6F07F2527166231061C30D53260CF5B0B8B0C1`).
4. VRAM fallback unit/scenario receipts: `tests/test_vram_balancer.py` **9 passed**; `tests/test_t12_runtime_scenarios.py -k vram` **4 passed, 18 deselected**. Prior checkpoint contains exact VRAM source/test postimages and command evidence.
5. Scoped `git diff --check b947d76f`: exit 0 on recorded model-routing/policy paths.

These receipts prove candidate contract behavior for the pinned blobs. They do not prove live inference, physical VRAM reclamation, or live overload/cancel/fallback quality.

## Release acceptance still open

- **Live latency and VRAM: NOT VERIFIED.** Latest bounded status had `active_model: null`, queue/inflight 0, VRAM pressure `nominal`. No installed-model inventory or live inference receipt was available. A prior bounded hardware benchmark failed with `AttributeError: '_InterruptibleSocketReader' object has no attribute 'peek'`; it was not repeated. No cold/warm/model-switch metric is claimed.
- **Profiles:** only balanced RTX 4060 host is available. Integrated/high/max live receipts are absent.
- **Baseline:** T02 artifact is absent; comparison and optimization claims remain skipped.
- **Integration:** root has separate dirty owners; VRAM root-current postimages were already present, and applying the dated packet against clean root index failed. Do not reapply or overlay the mixed candidate diff.
- **Final release gate:** T20 runs after root ownership reconciliation and the missing physical/baseline dependencies. T12 remains **INCOMPLETE / NO-GO** until required live receipts or an explicitly authorized scope change exists.

## No unsupported claims

No optional model is assumed installed. No model was pulled or installed. Candidate test passes are not live performance evidence. No acceptance gate is waived by this delta.
