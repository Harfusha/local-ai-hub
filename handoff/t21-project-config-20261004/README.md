# T21 project_config handoff to T11 — 2026-10-04

Source: existing T21 checkout `C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11` (working tree contains additional T21 changes).

Transferred into this T11 checkout as review material only:
- `project_config.py` — exact current T21 working-tree source, SHA-256 `088B8AFDF05A331E51C74925884B2B7984DF8BD5E3AD227C82DBDBEEB19289A1`.
- `T21-project-config-module-20261002.patch` — T21 single-file delta, SHA-256 `BA6B7DAB963534DC5E137CDB4CC552DB1E85F0C57B4795D27F682C3B987EC49C`.
- `T21-project-config-core-integration-20261002.md` — provenance and API contract, SHA-256 `1D53E458EE06D3D1DFE787286C65B7B94FEA462EB43F92C324218BDA9830D9D0`.

The T11 candidate at `8c945bdeb5f92270613e53b307b6f646a4f0e21b` has no `src/local_ai_hub/project_config.py`. The T21 patch is a diff for an existing file and requires its stated base SHA-256/blob; it is not an add-file patch. Therefore nothing was applied to T11 production source. The source file is supplied separately for review and a later integration decision.

No tests, builds, or benchmarks were run. T21 checkout was not modified. T11 tracked source remains unchanged.
