# T19 current prompt correction: orchestrator-owned continuation

Owner: orchestrator. Existing workspace: `C:\Users\Adam\.codex\worktrees\t19-docs-rollout\.local-ai-hub`. Root production/integration remains T20-owned. No new task chat or worktree. Runtime Hub ignored under the user's explicit fallback instruction.

## Verified predecessor

Dalton's R2 artifact `09-R2-root-current-docs.patch`, SHA-256 `8269FCA4B7E1DB051635395489883CDD59DA515C7414A4DC36DB56387046572C`, already supplied memory audit instructions, privacy constraints and three checkpoint JSON examples. Main independently ran its candidate tests: **15 passed in 0.12s**. Strict root apply-check initially returned 0; later reverse-check returned 0 and actual root contained the memory section. R2 had been integrated in parallel; no repeated application was attempted. The preceding summary that memory instructions were still missing was outdated, not an assertion of current source.

## Own correction

Only candidate `docs/INSTALL_PROMPT.md`, `docs/UPDATE_PROMPT.md` and `tests/test_t19_current_prompt_adoption.py` changed. The new regression requires maintenance to block every agent MCP/API action before Agent OS database access and preserves operator control channels. The former paragraph described safe-job exceptions in both paused modes without distinguishing the requested maintenance invariant. The replacement states the invariant and explicitly marks the current implementation fix as pending integration/verification, rather than claiming accepted isolation.

TDD red command, candidate cwd:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -B -m pytest -q -p no:cacheprovider --confcutdir=tests --noconftest tests/test_t19_current_prompt_adoption.py -k maintenance_contract --tb=short
```

Actual result: **2 failed, 15 deselected in 0.15s**, both prompts missing the required maintenance sentence.

Fresh green command, same cwd:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; & 'C:\Users\Adam\.local-ai-hub\.venv\Scripts\python.exe' -B -m pytest -q -p no:cacheprovider --confcutdir=tests --noconftest tests/test_t19_current_prompt_adoption.py --tb=short
```

Actual result: **17 passed in 0.09s**, exit 0. A preceding global-python combined command emitted no test output despite exit 0; that command was not used as green evidence. No runtime/application imports, GPU work or root test executed by main.

Candidate postimage SHA-256:

- INSTALL_PROMPT.md: `D77344A3B685141413F90FA4BCDB5E716D976BB6E2029D7B8CB62AB94B027FBC`.
- UPDATE_PROMPT.md: `BDDE8E04ADA45DA2B92EB84A8AFAD372A3DF02DD7472DBFEB83652CA08697A31`.
- test_t19_current_prompt_adoption.py: `91D629C9B1D189B93A21E940D87BEF7D680EC06DB3B514002623E9FF773A00E3`.

## Authorized integration artifact

Use only the two-paragraph current-root delta `14-R6-mode-contract-only-context.patch`, SHA-256 `95D7FADD697C0C663F3F636D3AF7322649E4CE303D6673372F24E179FF594707`.

Main root preimages at check:

- INSTALL_PROMPT.md: `2EAC7D77F67F8C76C05D6D365ED7BA78CACED0AA786CBF9516BAFB55296CD31C`.
- UPDATE_PROMPT.md: `9ECB7B9E13EC57B482989E8AA55568B11501E933D6D66980DCC164DA04ADDB95`.

`git apply --check --whitespace=error` against `C:\Users\Adam\.local-ai-hub`: exit 0, no output. Candidate `git diff --check -- docs/INSTALL_PROMPT.md docs/UPDATE_PROMPT.md`: exit 0, line-ending notices only. Patch changes no runtime source, inherited prompt sections or context route. Final root adoption/packaging proof remains T20-owned; this is not whole T19 completion.

Unapproved intermediate artifacts are preserved for audit and must not be applied: `11-R3` targets the already-applied R2 preimage; `12-R4` is a zero-context variant checked only with `--unidiff-zero`; `13-R5` is corrupt because its final context marker was trimmed. None was applied. Do not overwrite original published R1/R2 artifacts.

Release prerequisite: T13 must integrate and verify gaming-only safe-job exceptions, maintenance all-agent rejection, out-of-lock cleanup and release reservations. Then remove the pending-implementation caveat and adapt the narrowly scoped documentation test before publication; retain the maintenance safety assertions. Current fixtures do not prove physical VRAM release, model quality or installed clean-host acceptance.
