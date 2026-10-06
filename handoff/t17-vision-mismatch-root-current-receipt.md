# T17 vision mismatch contract — root-current handoff

Scope: only `src/local_ai_hub/vision_contracts.py` and `tests/test_vision_contracts.py`. No root files changed.

Patch: `handoff/t17-vision-mismatch-root-current.patch`

## Exact file hashes

| File | Preimage SHA-256 | Postimage SHA-256 |
|---|---|---|
| `src/local_ai_hub/vision_contracts.py` | `4b4897bd224ba813ce275d1c8acf11e4949f79fedf63159c6e9f9f373b3666cf` | `a6db25171aeeeb4164cfd90009c128bd5aab733c88df98bd1fcc23a50870b3db` |
| `tests/test_vision_contracts.py` | `66b96c9edec14bac9e1084955a2204a139429fa2cce061e29fea93772c0e30ee` | `403009c3e73cce66cb5247f4074259e20da82ae58c4892429328bb4a4407e6c0` |

Patch SHA-256: `46F71C8849B83912D3CEB43873D3D2B73AD8C19030514F1A685D96DB7E39B7A8`.

## Apply checks

- Candidate patch preimage reconstructed by reverse-applying the patch; `git apply --check`: PASS.
- Candidate current postimage; `git apply --reverse --check`: PASS.
- Root-current apply check: NOT RUN. Expected checkout `C:\Users\Adam\.codex\worktrees\8085\.local-ai-hub` is absent; only its parent worktree marker exists. Do not treat candidate verification as root verification.

The patch adds a narrow deterministic guard: reject a finding when explicit “does not match expected value/text/label X” wording contradicts a validated supplied observation fact equal to X. Tests cover both contradictory and genuine mismatch cases.
