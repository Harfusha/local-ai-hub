# T21 root-current core project config follow-up

Status: immutable follow-up packet; root and T21 source checkout unchanged.

## Bases and artifacts

- T21 worktree: `C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub`
- T21 HEAD: `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`
- Root checkout: `C:\Users\Adam\.local-ai-hub`
- Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`
- Follow-up patch: `T21-root-current-core-project-config-followup-20261005.patch`
- Patch SHA-256: `9307CB6025A881DC860A45C8560E9C7A1CF29FE89B98B483ACE936A4F08EDD33`
- Patch is byte-identical to the earlier core patch. Earlier packet remains unchanged.

## Root-current preimage -> patch postimage SHA-256

| Path | Preimage | Postimage |
|---|---|---|
| `src/local_ai_hub/project_config.py` | `00E80B1342E5E70A66FA8955D95553127E913F56EC693CF527B6AC96053BDBDE` | `1C004FA51B9D18737EFAF2EB63F3648814DB68B7FBF7FE348012917EDC07B641` |
| `tests/test_project_config.py` | `90A66B610B84FADDF178147321362DB91139FFCE0FDC680E01AAD9FBD1866270` | `07E063C2EC00A94BE82A6D7F2C4ADAAD39BB117BAFB5873DEC904347F8AABDC9` |
| `tests/test_project_path_hints.py` | `92EC33C9BB69D75F50ACB9EFBC501C541574D877128112444458CD11576AA5C7` | `237E00CF3E723A5EC010458277DF7810205196CD21DA0C448F5E59D915AC31C0` |

## Snapshot validation

Disposable snapshot copied four root-current files: the three patch inputs plus `src/local_ai_hub/__init__.py` (SHA-256 `945D7DE874D7CEB14D8F723083C6C4353E0CA8241D325B8F61FD36DB738DBA4E`). The initializer pins Python import resolution to the snapshot. Patch apply exit `0`; all three postimage hashes above matched. Import receipt pointed to the temporary snapshot's `src/local_ai_hub/project_config.py`.

- T21 candidate command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_config.py tests/test_project_path_hints.py`
- T21 candidate result: **100 passed in 2.68s**.
- Snapshot command, with `PYTHONPATH=<snapshot>\src`: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_config.py tests/test_project_path_hints.py`
- Root-equivalent snapshot result: **102 passed in 2.52s**, exit `0`.

The earlier 101-pass/1-fail run omitted `__init__.py`; Python resolved `local_ai_hub` from the root checkout instead of the snapshot. This was a fixture error, independently confirmed by import-path output. Corrected snapshot passed; test expectations unchanged.

Root `git apply --check --whitespace=error` passes. Patch not applied. Root preimage hashes remain unchanged. No Hub call; no adapter or `/api/context/pack` changes.
