# T16 independent specification review r1

Owner: orchestrator receipt; reviewer Euclid `01a0f7f3-ad7d-7311-84cb-386d5d2f71ad`.
Review is SOURCE ONLY: no runtime tests, imports, workspace or Git writes by reviewer.
Scoped review goal complete; full T16 and release remain open. Verdict: spec compliant NO, merge ready NO.

## Immutable scope

- Root `C:\Users\Adam\.local-ai-hub`, HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
- Namespace artifact `C:\Users\Adam\.codex\worktrees\t16-orchestration-recovery\.local-ai-hub\handoff\T16-namespace-root-current.patch`, SHA-256 `26C83E5B29E81EC4B8A011806D259399EB273E85CBAFC34616540D4ED7369DC8`.
- HTTP artifact beside it: `T16-http-lease-routes-root-current.patch`, SHA-256 `F22B5290486857EAC823F408B4558C89A308180B26C193EA0F8D6B7B5D9A6D0B`.
- Both artifact pins and supplied leases/orchestrator/HTTP root preimages matched before/after review.
- Namespace strict apply check: 128, new blank EOF line 1188; whitespace-neutral hunk check: 0. HTTP strict check: 0.

## Specification findings and ownership

| Severity | Finding | Exact observed seam | Required acceptance / owner |
|---|---|---|---|
| Critical | Terminal outcome can revive with a fresh valid token | Root `work_orchestrator.py:968`, execution entry `1555`: delay after `_next()` and before attempt claim; successor completes; delayed worker claims newer token and unconditional planning transition overwrites terminal result | State-conditioned claim and transitions; reproduce with delayed worker and completed successor, terminal result immutable. T16; T09 receipt hunks kept separate |
| Important | Exact HTTP/core artifact pair lacks required `waits` signature | HTTP patch line 37 calls `waits(root, coordination_id=...)`; root `leases.py:315` accepts only root and core artifact does not change it | Joined HTTP GET/list/waits fixture using the actual composed artifact pair, not a different candidate. T16 |
| Important | Real command lease callers bypass namespaced HTTP leases | Root `commands.py:4315`, recovery `4065`; omitted coordination identity takes physical-root legacy query, invisible to namespaced rows | Actual CommandBroker acquisition versus namespaced HTTP/store claim must conflict, same and linked physical roots. T06 caller / T16 store |
| Important | Wait metadata and cleanup cross namespaces | Root `leases.py:106` wait key, `222` owner-global cleanup, `259` matching-path release cleanup | Distinct namespaces with same owner/blocker/path retain independent waits after acquisition/release; keys and targeted cleanup scoped. T16 |
| Important | Multi-file rollback can mutate before hardlink rejection | Root `work_orchestrator.py:1362` checks link eligibility inside restore loop | Preflight entire restore set; refusal of second hardlinked file leaves every file unchanged. T16 |
| Minor | Published namespace artifact violates whitespace gate | Namespace patch line 1188 | New immutable version; re-pin and re-review, never overwrite reviewed artifact. T16 |

Positive source evidence: coordination identity server-derived from Git common directory plus namespace; client override ignored; physical root separate; transactionally advancing attempts and write guards; owner predicates retained.
These positives do not resolve terminal-state, joined artifact, actual broker or multi-file restore gaps.
Existing candidate tests include SQLite, linked/unrelated Git roots and guarded writes, but the reviewed artifacts lack the scenarios above. Candidate 62 passes is not integrated-root proof.

## Release disposition

T16, T06, T09 and root integrator T20 received the findings. Do not integrate this exact pair as accepted.
T16 owns scoped state/fencing/store/read-route/restore fixes; T06 owns real broker claim/recovery callers; T09 owns completion receipts.
Only reviewed owner hunks are integrated by T20. No whole-file replacement or suppression of negative assertions.
After owner replacement: verify new hashes and applicability, execute RED/GREEN regressions and joined consumer acceptance, then independent re-review.
## Revised v4/v3 independent follow-up

Bernoulli reviewed exact immutable core v4 `5CFB42C73B1095F63C3FFFFB3482B01D46B016095E6AF21450ABEA3DA785DD81` and HTTP v3 `954F126E34DC408F2AF8139E54033F88967EDC2DC072E94F627D70360CCC3AFE`; hashes/preimages stable, 58 hunks/10 files composed in memory. No imports/tests/writes. Prior critical terminal revival, waits signature/namespace isolation and hardlink ordering are fixed in source; T09 receipt seam preserved.

Remaining P2: writer-token counter must inherit legacy physical counter floor (legacy 8 currently can become namespaced 1); full restore preflight must reject an existing regular-file ancestor before any restore (otherwise later `mkdir` may fail after an earlier file changed). No stale-write bypass established by source review. T16 owns these two bounded corrections/new immutable v5; T06 owns actual advisory claim namespace forwarding, still absent in root commands callers 4238/4488. Reported candidate 68 pass/1 skip/1 deselect excludes real broker. Root end-to-end acceptance remains pending.
