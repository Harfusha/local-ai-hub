# T16 root recovery failure diagnostic v1

## Candidate result

Candidate: `C:\Users\Adam\.codex\worktrees\t16-orchestration-recovery\.local-ai-hub`
HEAD: `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.

The requested focused crash-recovery test passed in the T16 candidate after T20 reported its root failure:

`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_work_handoff_acceptance.py::test_process_crash_after_patch_write_recovers_from_persisted_journal`

Result: `1 passed in 0.99s`.

## Diagnosis

Candidate `_apply_patch` computes expected postimages in an isolated preview and persists the preimage, postimage digest, lease identity, and monotonic tokens before touching the workspace. Candidate startup `_recover` claims fresh recovery fencing, verifies and restores the postimage, records a recovery checkpoint, clears the journal, then requeues the transient row.

In candidate `_recover`, successful recovery writes `queued`; unsafe recovery writes `needs_agent`. It does not write literal state `failed`. The reported root value `failed` therefore does not match this candidate recovery implementation. Root integration must verify that it has the same `_recover` implementation and that the test disables worker startup before asserting the recovered queued row. Candidate test does disable `_ensure_workers` before constructing the recovery orchestrator. Do not rerun root selector until source/test preimages are compared.

This continuation made no source edits: candidate already contains the required regression and passes it. No root files inspected or changed in this continuation.

## Root-current T16 patch reference

Existing T16 core patch: `handoff/T16-r2-root-current-core.patch`
SHA-256: `75AD70EC3D5DFAF7B0239AF4837F00EFC5A0D3395682CE2E45BA3BD8DED90020`.

Existing T16 core handoff manifest: `handoff/T16-r2-root-current-handoff.md`
SHA-256: `1039D6FDF9077FD8E32B16A9A2F190AE7D56020E9311F549A34FE4F529E926EC`.

These are prior root-current integration artifacts; they are references, not a claim that they alone fix the newly observed root mismatch. T20 should compare its active recovery source/test against candidate before applying any replacement hunk.

## Candidate integrity pins (SHA-256)

- `src/local_ai_hub/work_orchestrator.py`: `70C5084F02D4D1202C5375194324A6E6754C5623C4389DED19846CF4CE9B3AD5`
- `src/local_ai_hub/work_fencing.py`: `287DA1CDC5A8CA31EA96CE08D9D3D2EDC641F7BF7DC0F815BC3B2AECCED2F214`
- `tests/test_work_handoff_acceptance.py`: `391503C600E03CDFD807D1F90A31734EC19CD5F94180E3F8CAD009AC833B4FCE`
- `tests/test_work_fencing.py`: `E7C82981577F48144E849B80EC473FBBA258B269EEEC05E84584228E04CA5A0D`

Whole-file pins include inherited content; they do not imply exclusive authorship. T21 `project_config.py`, T06 `commands.py`, and T20 root remain outside T16 ownership.
