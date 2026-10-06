# T19 current canonical prompt contract audit — 2026-10-01

## Scope and ownership

Compared existing T19 candidate `C:\Users\Adam\.codex\worktrees\t19-docs-rollout\.local-ai-hub` with current root `C:\Users\Adam\.local-ai-hub`. Local AI Hub ignored; root read only. No runtime/source edits. Canonical prompt sections already contain current root contract; this turn made no INSTALL/UPDATE prompt edit. These prompt working copies were inherited from the prior T19 current-prompt-adoption work and match its recorded postimage hashes (`D77344...` / `BDDE8...`). Current prompt adoption receipt remains `handoff/t19-current-prompt-adoption/07-HANDOFF.md`, which records 17 prompt-specific assertions.

Current root and candidate normalized section contents match in both prompts:
- Adaptive context and supported capabilities: `9A574E8439883386F36D3B2DEDAE4CF8EE6DF5E0E5956EC99A21407F9549BA62`
- Project configuration, verification, and PathHints: `63D077E90A86091DBA9710493C16A39D5A20D23EAD3E8D5138642E87DB3FC4E2`
- Runtime schemas, offline mode, and Agent OS memory: `83E8A69BE0FC9FD685261279A38BE2DC262B8B37EC75D4D0914799B673BD33FB`
- Memory adoption checkpoints: `C12460ED4DDEAC3A4D76902CF601B8525846755A53EFEAD6387CC6B5C30CE09E`

CodeGraph is described in prompts only as optional external standalone tooling outside Hub setup/runtime; installation/MCP setup details stay in `docs/INSTALLATION.md`. No install command appears in either prompt or SDK guide.

## Test fixes

Two old candidate-only regressions still expected the earlier unshipped T21 contract, `/api/context/pack` hint denial, and historical profile wording. Updated only tests:
- `tests/test_t19_parity_contract.py`: validate parity between canonical prompt contract sections; retain generated-skill checks separately from current canonical prompt content.
- `tests/test_t19_project_config_prompts.py`: check current project config, typed adapter/schema boundary, modes, and memory policy; remove obsolete project draft assertions.

`tests/test_t19_current_prompt_adoption.py` was inherited and not modified. `tests/test_release_contract.py` was not modified; its standalone documentation ownership test passes.

Exact command:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -B -m pytest -q -p no:cacheprovider --confcutdir=tests --noconftest tests/test_t19_current_prompt_adoption.py tests/test_t19_parity_contract.py tests/test_t19_project_config_prompts.py tests/test_release_contract.py::test_canonical_prompts_share_profile_and_installation_docs_own_standalone_setup --tb=short
```

Result: **23 passed in 0.28s**, exit 0. `git diff --check` passed. No broader suite, runtime server, daemon, GPU, install, or profile mutation used.

## Patch and hashes

Review patch: `handoff/T19-current-prompt-contract-tests-20261001-v1.patch`, SHA-256 `8A81CE9D543F67120678CBB1E05DA8252DC90E9B0445A920E325842F75748D8E`. Reverse apply-check passed. It changes only the two scoped T19 test files.

Verified parity-test preimage SHA-256: `12673F889CAE3A015AA9D2558ACBFC0CBE0C86A3AF221A69DD4E435BEE3521C0`.

`tests/test_t19_project_config_prompts.py` was pre-existing untracked work and had no recorded pre-edit hash. Its old source was reconstructed from the observed pre-edit contents for patch generation; reconstructed hash `013B580CAD8F4DB4C914F565EFC00C7B0A29575956B146E55725B83438596C6A` is not represented as a verified original preimage. Reverse check verifies patch against current postimage only.

Postimage SHA-256:
- `tests/test_t19_parity_contract.py`: `4AE596BA4BB7E534C817338843F33EF87B7D17999CAE99997DCCDDD6A9CE6B20`
- `tests/test_t19_project_config_prompts.py`: `EE476BFF3741DF06FF666FDBC4CF2BB3E32D9B5B47841602BE2A7CC418176218`
- `docs/INSTALL_PROMPT.md` unchanged this turn: `D77344A3B685141413F90FA4BCDB5E716D976BB6E2029D7B8CB62AB94B027FBC`
- `docs/UPDATE_PROMPT.md` unchanged this turn: `BDDE8E04ADA45DA2B92EB84A8AFAD372A3DF02DD7472DBFEB83652CA08697A31`

Root test and source changes remain T20-owned. Whole T19 acceptance remains open; this audit is not release completion.
