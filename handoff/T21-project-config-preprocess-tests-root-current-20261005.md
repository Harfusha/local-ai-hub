# T21 project-config preprocess tests root-current handoff — 2026-10-05

Status: add-only T21 test packet prepared and apply-checked. Not applied. Root tests not run. Candidate suite passes; root acceptance still requires matching T21 production hunks.

## Checkout pins

- T21 candidate: `C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub`, branch `codex/t21-project-config`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.
- Root current: `C:\Users\Adam\.local-ai-hub`, branch `master`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.

## Single-path test packet

- Patch: `handoff/T21-project-config-preprocess-tests-root-current-20261005.patch`
- Patch SHA-256: `FA80B1FD9EFF2AB0A7F844053B5819D40F66C30515C9FFBEF490FE9E43825473`
- Exact path: `tests/test_t21_project_config_preprocess.py` (new file; absent from root current and candidate HEAD).
- Candidate file SHA-256: `0391722543F054ACCDFB6C73D2FDA0803ACC193A5F50D872EAE1C484374FDF7E`.
- Base SHA-256: absent at candidate HEAD and root current.
- `git apply --stat`: one new file, 247 insertions. Root-current `git apply --check`: exit 0. Patch not applied.

The file covers project inventory/exclusions/force-includes, preprocessing phase skips and cache recheck, candidate policy, bounded Python fallback metric, and exact-cap versus omitted-candidate truncation sentinel. The fallback truncation cases depend on the T21 `repo_tools.py` production change; this add-only packet does not claim root test pass by itself.

## Candidate test receipt

Exact command run in the T21 candidate:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_config.py tests/test_project_config_worktrees.py tests/test_project_config_service_integration.py tests/test_t21_project_config_preprocess.py tests/test_project_path_hints.py tests/test_mcp_repo_path_hints.py tests/test_client_path_hints.py
```

Observed: **138 passed in 11.79s**, exit 0. Candidate-only. No root tests were run.

## Ownership boundary

Only the T21-owned test file is in the packet. No root/T11/T14 files were changed; `/api/context/pack` is untouched. Integrate only alongside its matching owned production patch and then validate at the authorized root acceptance gate.