# T15/T29 root-current preimage packet

**Owner:** T15, packet only  
**Captured:** 2026-10-04  
**Scope:** immutable source preimage and acceptance receipts. No source edit, test, or benchmark in this capture.

## Registered T15 worktree

- Attached artifact path: `C:\Users\Adam\.codex\worktrees\fefe\.local-ai-hub`
- HEAD: `17d9f93f9d5eded85eee3a19dc7cb62dc554fd97`
- Latest repository fingerprint: `3509158d8d3068e9a7f12497acd5a7b8dcbcfe01b4dc88104e90712a4550f538`
- Last `repo_state`: `success=true`, `dirty=true`, `changed_files=5`, request `req_7a08617a99ac`.
- T15 packet lease: `lease_dd15dfeb21ee4fbc8558`, path `handoff/T15-T29-root-current-packet-2026-10-04.md` only.

## Current dirty-path inventory

Last brokered `git status --short` succeeded, exit 0, request `req_7cc1b435f502`:

```text
M src/local_ai_hub/commands.py
?? handoff/T15-T29-command-run-paired-benchmark.py
?? handoff/T15-T29-commands-run-paired-methodology-2026-10-03.md
?? handoff/T15-T29-readonly-benchmark-protocol-2026-10-04.md
?? handoff/t15-patch-snapshot-stat-20261003.patch
```

Only `commands.py` is a modified tracked source file. T15 handoff files are untracked artifacts; preserve them.

## `commands.py` preimage and inherited hunk

- HEAD blob: `a9e927362f21fd3b381c30d771dd0059a124937f`
- Worktree blob: `5fc5c1144574b74523816c4bba76ec8b751907b2`
- Previously recorded SHA-256: HEAD `58506607592a614026011df47d7a3c553552c52c6a1927c7304ff32f1f9b18d1`; worktree `ed97e7220030b4fc181bca02e5281d677e683d6038c5ce6748101a3e37ccea17`.
- Latest brokered `git diff --unified=1 -- src/local_ai_hub/commands.py` succeeded, exit 0, execution `783b8c849af744d0b28d5c27eb923948`, request `req_fe04be92f7b9`.
- Hunk location: `_snapshot_patch_targets`, around lines 358–369. Adds a Windows timestamp comment; removes `st_mtime_ns`/`st_ctime_ns` from path-vs-`fstat` identity comparison. Diff is `+3/-4`.
- This hunk changes rollback snapshot safety. T06 owns it. No current T06 checkout, exact owner handoff, or lease was available at capture. No T15 edit to `commands.py` is authorized by this packet.

## Validation receipts and outcomes

One T20-authorized root selector, run once at `C:\Users\Adam\.local-ai-hub`:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_command_rollback.py::test_rollback_oserror_marks_outcome_unknown_invalidates_caches_and_records_incident
```

Receipt: `1 passed in 2.17s`, exit 0, execution `076fea3167a441e1b1154dde56b100c6`, request `req_e1e3deed4e49`. Post-run hashes matched supplied prehashes: `commands.py` `83CB8776B086167F1198F127E05C1271ABC9E742BA1C0684772357A0BF28A279`; test `11E99867D77D2A4AD7269F56347B0AAEA50C1F0973E68AC3029EBAB9998FDEE6`. This proves existing dirty-root behavior only; it is not T06 integration or T15 acceptance.

Prior T15 context records harness contract suite `21 passed / 2.61s`, broker/benchmark selectors `26 passed / 2.97s`, CLI help passed. These are historical summaries, not fresh receipts for this capture. A previous 7-pair probe reported `+30%`, `acceptance=false`; its source pins were not comparable. Do not treat it as a baseline or rerun identical selectors.

## Current gate

- T06: no owned checkout/current preimage/lease; no disjoint `commands.py::run` hunk confirmed. Entire `run()` remains T06-owned.
- T20: T06 one-shot selector released; no T15 GO or slot ID reported.
- Paired benchmark: not run; no clean pinned baseline/candidate pair or slot authorization.
- Root: untouched by T15. This packet and all prior T15 handoffs remain under `handoff/` in the registered T15 worktree.

## Next acceptance inputs

1. T06 supplies a clean candidate, classifies inherited hunks, and provides exact HEAD/blob/SHA-256 plus ownership/lease receipt.
2. T20 pins an immutable baseline/candidate pair and issues explicit T15 GO with one serial slot ID.
3. T15 runs the existing paired harness once, writes report outside both roots, and preserves raw observations and parity/threshold results.
