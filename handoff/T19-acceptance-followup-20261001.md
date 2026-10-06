# T19 Acceptance Follow-up — 2026-10-01

## Candidate and scope

Assigned candidate: `C:\Users\Adam\.codex\worktrees\t19-docs-rollout\.local-ai-hub`, `HEAD 2b33602adef0d030fea66cdcc04ca742c60b2e32`. Existing dirty work remains preserved. T19 changes stayed in this candidate. At initial pin check, root prompt hashes matched their preimages; at final check, both root prompt files were dirty in the shared checkout after concurrent integration. T19 did not edit those root prompts. Preserve them and reconcile against this candidate before another integration patch.

## T12 routing policy synchronization

T12's four-profile, six-role policy is now reflected in both canonical prompts and the `Profile routing` table in `docs/MODEL_CAPABILITIES.md`. The prompt route paragraphs match byte-for-byte. Balanced-only routing prose and the old default-delegation claim were removed from T19-owned prompt text. The policy keeps semantic delegation optional and on-demand.

Current candidate SHA-256:

- `docs/INSTALL_PROMPT.md`: `A4E3A18C701FED580489B0624116F42365D485438CAFB3E9A13DD20D75CFF3D4`
- `docs/UPDATE_PROMPT.md`: `FE2DE700D44DB2852F336A54113F964398983D20649B263D3271C4FFF3EDCC03`
- `docs/MODEL_CAPABILITIES.md`: `09FE472497C3F8F5381CCFEFB64B21CA4453C9110F55BB7C22F22BC313487617`

The earlier root-current docs patch `E003E1F7C372981742D932A1DB5A2BB4D4EB92EF45DE13CFEE8C80C4D996E5CA` is stale for these route sections. Do not integrate its old prompt hunks; refresh the integration patch against the current candidate and T12 policy.

## Candidate validation

T19 regression command, 18 files (all `test_t19_*.py` except separately run package smoke):

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$exclude=@('test_t19_packaged_sdk_smoke.py')
$tests=Get-ChildItem -LiteralPath tests -Filter 'test_t19_*.py' -File | Where-Object { $_.Name -notin $exclude } | Sort-Object Name | ForEach-Object { $_.FullName }
python -B -m pytest -q -p no:cacheprovider --confcutdir=tests --noconftest --tb=short $tests
```

Result: **70 passed, 1 skipped in 28.02s**. The skip is the Windows directory-symlink case (`WinError 1314`). This run includes the isolated clean-profile install/update configuration and prompt roundtrip.

Prompt/model-profile regression after synchronization: `python -B -m pytest -q -p no:cacheprovider --confcutdir=tests --noconftest --tb=short tests/test_t19_prompt_profile_parity.py` — **2 passed in 0.07s**.

Release prompt selector: `python -B -m pytest -q -p no:cacheprovider --confcutdir=tests --noconftest --tb=short tests/test_release_contract.py::test_canonical_prompts_share_profile_and_installation_docs_own_standalone_setup` — **1 passed in 0.13s**.

Static docs command: `powershell -NoProfile -File handoff/T19-docs-static-check-20261001.ps1` — **exit 0**. It checked prompt parity, all four role-matrix rows, optional standalone CodeGraphContext documentation, Python version tags, trailing whitespace, and docs diff cleanliness. Final scoped `git diff --check` — **PASS**.

Offline package smoke command:

```powershell
& 'C:\Users\Adam\AppData\Local\Temp\t19-packaged-runner-c10a83e1659c469eb14f9eeb756a73b5\Scripts\python.exe' -I -B tests/test_t19_packaged_sdk_smoke.py
```

Result: **2 passed in 9.729s**. Runner used locally cached setuptools/wheel plus `_distutils_hack`; no network or global install. Receipt: `C:\Users\Adam\AppData\Local\Temp\t19-packaged-sdk-uxrl5mqe\receipt.json`, SHA-256 `65A78DCCDD9516BDCEC04B9522A6435630E58BD38522BFDC13AD37B2579D72DE`. Source snapshot SHA-256 `f21b6b9e76544fd7c60f0e76fcb52de122f4008d0f87c1dd8b1b9c9a2f2afe93`. Sdist SHA-256 `04b4879ac899e77401b4091dc40d90a099d24b52d064ed549899d10bc247b5fd`; wheel SHA-256 `fb1ad4963c792cb9c7a0f8731e8226bffee8d73883f553038be2f6eb4d798cd7`. Receipt explicitly sets `production_release_approved=false`.

## Release status

**NOT RELEASE-READY.** No frozen same-revision artifact pair or clean Windows/Linux hosts are available for installer, doctor, reinstall/config-preservation, and uninstall/external-state checks. T20's integrated live MCP/HTTP/auth/outage/restart/concurrency and final `verify_completion` gates remain open. Candidate packaging and isolated roundtrip do not replace those checks.

`docs/API_COVERAGE.md`, `tools/surface_inventory.py`, and `tests/test_surface_inventory.py` remain T01-owned and untouched in this T19 continuation.

## Final resumed ownership and goal check

- Final candidate audit: `HEAD 2b33602adef0d030fea66cdcc04ca742c60b2e32`, 73 dirty paths. The older ownership snapshot's 83-path count is stale; existing worktree changes remain intact.
- T01-owned `docs/API_COVERAGE.md`, `tools/surface_inventory.py`, and `tests/test_surface_inventory.py` remain dirty from their owner. T19 continuation made no edits to these paths.
- Root is at `01df56605ccf484ebfe2808ac60d696c4e81dffc` after the separate T10 test-only integration. Root INSTALL/UPDATE prompts are dirty in the shared checkout; T19 did not edit them. Preserve current root work.
- Existing T19 goal already reports `blocked`. It stays incomplete while clean-host and integrated release gates remain unavailable.

## 2026-10-02 resumed offline follow-up

- Local AI Hub was unavailable and intentionally ignored per user instruction. All work stayed in the assigned T19 candidate; shared root was read-only.
- Fixed two candidate release-hygiene findings: exclude the non-shipped `handoff/` archive from the historical-name source scan, and remove the personal local path from the T19 prompt-adoption test docstring.
- Targeted hygiene checks: **2 passed in 17.84s**.
- T19 regression set (all `test_t19_*.py` except the separately-run package smoke): **70 passed, 1 skipped in 24.27s**. Skip is Windows directory-symlink privilege (`WinError 1314`).
- Packaged SDK smoke, using the isolated cached-toolchain runner: **2 passed in 8.694s**. Receipt: `C:\Users\Adam\AppData\Local\Temp\t19-packaged-sdk-r5wz6pjz\receipt.json`; status `passed`, version `4.0.0`, `production_release_approved=false`. Source snapshot SHA-256 `b2ae4f52bd3fc1457d2af85780f549351c1ebba6ca29dad76899e0bd1fd56fcd`; sdist SHA-256 `add9ed5025039afacbb19cd3f243fe7fee1d26d12f931363640040c1ff1625c2`; wheel SHA-256 `c2326e37d191c104e375e92396b15aea960b3dfb15483303f43a5c7fb49f55e6`.
- The same package smoke was also included once under system Python and failed because that interpreter has no `setuptools`; this is an invocation/toolchain limitation. The dedicated isolated runner above is the valid package-smoke result.
- Initial offline release group (`test_codegraph_package_policy.py`, `test_setup.py`, `test_release_contract.py`, `test_release_hardening.py`): **58 passed, 1 skipped, 2 failed in 55.37s**. Follow-up diagnosis and targeted results below; broad group was not rerun.
- `handoff/T19-docs-static-check-20261001.ps1`: **exit 0**, including prompt parity, profile rows, standalone optional CodeGraph docs, whitespace, and docs diff checks.
- Original root-current docs/prompt patch: `handoff/T19-root-current-docs-prompt-20261002.patch`, SHA-256 `53851641F5FA14048FF52F5B26BD5A8822CF28E239B8755E8AFCE3F7EF6F52DC`. Its first manifest SHA was `B0FB5F7F2E7281DA20FD0595C4D4FF034D6B51B6F0E8280B6D13E61CBF951FC0`; later marked superseded in the revalidation manifest below. The patch was valid against the earlier root snapshot before T20's partial integration; it is not valid against the current root. It carries only four docs paths; `/api/context/pack` remains untouched. T19 made no root writes.
- Candidate remains at `2b33602adef0d030fea66cdcc04ca742c60b2e32` with 73 dirty paths; no dirty work was discarded. T01 ownership files remain untouched. CodeGraphContext remains optional and standalone.
- **NOT RELEASE-READY.** Clean Windows/Linux host gates and integrated T20 gates remain outstanding. The existing T19 goal remains blocked/incomplete.

### Release-failure ownership follow-up

- `test_mcp_explicit_short_deadline_is_honored` failed because its `_LiveProc` double lacked `pid` (then `stdout`/`stderr`) required by the unchanged `Popen` cleanup path. This was a test-fixture defect, not a production-code regression: the failing call and `_stop_process` implementation are unchanged versus candidate `HEAD`; the preexisting edit in this test file only changes a different session-close assertion. Updated this fixture with the expected process fields and a no-op `terminate_tree` monkeypatch, preventing any real process termination.
- Exact command after fixture fix:

  ```powershell
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -B -m pytest -q -p no:cacheprovider --confcutdir=tests --noconftest --tb=short tests/test_release_hardening.py::test_mcp_explicit_short_deadline_is_honored
  ```

  Result: **1 passed in 0.22s**.
- Since the fixture is included in the source distribution, refreshed the isolated packaged smoke after that edit: **2 passed in 10.663s**. Current receipt: `C:\Users\Adam\AppData\Local\Temp\t19-packaged-sdk-psaa3ouk\receipt.json`, status `passed`, `production_release_approved=false`. Snapshot SHA-256 `6077a36c921a6b50f425c23a5674bacc97a1e3774cb5de484f9d18afd69ca16d`; sdist SHA-256 `115836f93c35c9472da2cc5f3eb4b52a9a7d7e5880f9b3acdc61a5c304268af9`; wheel SHA-256 `24a2fe972b584f93f83da4a8acf8854c1d172b14229005823443263a36f275fa`.
- `test_release_gate_allows_the_live_installed_checkout` fails on candidate checkout state: `build/` created 2026-09-28 16:10:28 and `dist/` created 2026-09-28 16:10:26, last changed 2026-09-30 19:12:41. Both are ignored by `.gitignore` (lines 27-28) and neither is tracked. T19 package smoke used `%TEMP%` staging, so these predate its run. They were preserved.
- Exact targeted command for that unchanged environment-dependent gate:

  ```powershell
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -B -m pytest -q -p no:cacheprovider --confcutdir=tests --noconftest --tb=short tests/test_release_hardening.py::test_release_gate_allows_the_live_installed_checkout
  ```

  Result: **1 failed in 10.21s**, with `forbidden directory: build/` and `forbidden directory: dist/`. No cleanup or root/merge test was performed.
- Gate ownership decision: this is correct fail-closed behavior for a dirty local checkout. `tools/release_check.py` deliberately lists top-level `build` and `dist` as forbidden, and `allow_installed` only exempts managed runtime environments. `.github/workflows/release.yml` runs the post-test gate, removes expected ignored artifacts with `git clean -fdX`, then reruns release check before building artifacts. Therefore an ignored old output tree blocks local acceptance until its owner cleans it; ignoring it in the gate could hide stale package outputs.
- Replaced the environment-dependent assertion on the actual dirty repository with deterministic hygiene tests over `tmp_path`: managed installed directories pass, while `build/`, `dist/`, and a standalone stale `.whl` remain violations. No release-check implementation changed; existing directories were not read recursively or modified.
- Exact targeted command:

  ```powershell
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -B -m pytest -q -p no:cacheprovider --confcutdir=tests --noconftest --tb=short tests/test_release_hardening.py::test_release_hygiene_allows_managed_installed_directories tests/test_release_hardening.py::test_release_hygiene_still_rejects_build_outputs
  ```

  Result: **2 passed in 0.20s**. Broad release suite was not repeated.
- After this test-only edit, current isolated packaged smoke: **2 passed in 8.296s**. Receipt: `C:\Users\Adam\AppData\Local\Temp\t19-packaged-sdk-2ua6t0k5\receipt.json`; `production_release_approved=false`. Snapshot SHA-256 `401fae763c90f493b4760dcb02e729db0dcaeca54c81f365755c6976ece8745c`; sdist SHA-256 `59672188dd9f61f786875c655185b07c8be7d8af2b250c8f5f8b4cfb5e57e935`; wheel SHA-256 `a5de1c638d33f9f943f157bee23de5c7818dfc456439093b68c65ba80fb2b802`.

## Initial root patch recheck before T20 partial integration

- Root remains at `01df56605ccf484ebfe2808ac60d696c4e81dffc`; only INSTALLATION and the two prompt files are dirty among the four patch paths. Existing patch/manifest still match those preimages and candidate documents.
- Recheck command: `git -C C:\Users\Adam\.local-ai-hub apply --check --whitespace=error C:\Users\Adam\.codex\worktrees\t19-docs-rollout\.local-ai-hub\handoff\T19-root-current-docs-prompt-20261002.patch` — **PASS**. No root writes.
- Current targeted prompt and CodeGraph contract command: `python -B -m pytest -q -p no:cacheprovider --confcutdir=tests --noconftest --tb=short tests/test_t19_prompt_profile_parity.py tests/test_t19_codegraph_removal.py` — **7 passed in 0.26s**.
- Current `powershell -NoProfile -File handoff/T19-docs-static-check-20261001.ps1` — **exit 0**, including prompt parity and standalone CodeGraphContext contract.
- Standalone recommendation accuracy rechecked against upstream on 2026-10-02: CodeGraphContext 0.6.13 advertises the optional `gcf` extra and both `cgc` and `codegraphcontext` entry points in its [`pyproject.toml`](https://github.com/CodeGraphContext/CodeGraphContext/blob/main/pyproject.toml); upstream [MCP setup](https://github.com/CodeGraphContext/CodeGraphContext/blob/main/docs/docs/getting-started/mcp-setup.md) documents direct local MCP startup; [PyPI](https://pypi.org/project/codegraphcontext/) lists 0.6.13 and the `gcf` extra. Candidate INSTALLATION's `pip install "codegraphcontext[gcf]==0.6.13"` and `codegraphcontext mcp start` alias are accurate. Bounded `rg` over Hub `pyproject.toml`, both defaults files, and `tools/setup.py` returned `NO_CODEGRAPH_DEPENDENCY_HIT`; existing package-policy and removal tests passed as recorded above. Runtime operation of the separate CGC server is not claimed.

## Current root state after T20 partial integration

- Current root remains at HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`; root files are dirty under shared T20 integration. Current root SHA-256: INSTALLATION `3802b4f60012f8e5c0eca12673f0d8273fc93e6edeafa03fd6af838b7dbf463d`; INSTALL_PROMPT `340711aaa1f3100f5227e3acee900b497d3a5d30d228eda8418602e6c720bf6b`; UPDATE_PROMPT `a0eb389f6b366f58ffaa98ed3c1d9317896bb9255d5c2d0906142a0ade0d0924`; MODEL_CAPABILITIES `09fe472497c3f8f5381ccfefb64b21ca4453c9110f55bb7c22f22bc313487617`.
- Rechecked old full patch with `git -C C:\Users\Adam\.local-ai-hub apply --check --whitespace=error C:\Users\Adam\.codex\worktrees\t19-docs-rollout\.local-ai-hub\handoff\T19-root-current-docs-prompt-20261002.patch`: **FAIL**, stale preimages at all four paths. No write was made.
- T20's task log records filtered T19 integration for INSTALLATION, MODEL_CAPABILITIES, and disjoint UPDATE_PROMPT hunks. T12 reports its overlapping routing/policy hunks are already in root (T12 forward-check fails and reverse-check passes). T19 INSTALL_PROMPT still mixes T12-owned routing/delegation hunks with T19 documentation hunks; T20 owns the remaining root-current merge. T19 does not overwrite or refresh that shared prompt patch.
- Revalidation manifest `handoff/T19-root-current-docs-prompt-20261002.json` now marks the full patch superseded and records current root hashes, T20 integrated paths, pending overlap, and `root_writes=false`. Current manifest SHA-256 `BF1E17CD3475A7861B47F950E3F28B0C97E183934352289BCAA8E3524525A800`.

## T19 continuation checkpoint — 2026-10-02

- Existing goal: `T19: install SDK docs release rollout — satisfy the existing master-plan acceptance criteria`; status remains `blocked` because clean-host and integrated release acceptance is not complete. This checkpoint does not claim end-to-end completion.
- Candidate prompt pair remains unchanged: INSTALL_PROMPT SHA-256 `7bc6af155901d203680e9df6df88565648431a2f85928aab96f686d3177fddb3`; UPDATE_PROMPT SHA-256 `fe2de700d44db2852f336a54113f964398983d20649b263d3271c4fff3edcc03`. Existing parity/CodeGraph result remains **7 passed in 0.26s**; docs static check **exit 0**. No source test changed after these receipts.
- T02 currently owns the only test/benchmark slot per the latest orchestration instruction. No tests or benchmark ran in this continuation. Previously recorded candidate receipts remain: T19 set **70 passed, 1 skipped**; package smoke **2 passed**; release hygiene selectors **2 passed**; MCP timeout selector **1 passed**.
- T14 confirmed its current work leaves prompt files to their owners. T20 owns root-current integration. T19 sent both owners current candidate/root hashes and retained the superseded full patch state; no root or prompt edit was made.
- Next steps: T20 resolves the remaining INSTALL_PROMPT merge while preserving T12/T14 hunks; after the slot is released, only run a T19 candidate selector if files change or T20 requests an integration-specific check. End-to-end release still needs clean Windows/Linux install/doctor/uninstall evidence and integrated T20 gates. The existing ignored `build/` and `dist/` remain untouched and intentionally block a dirty-checkout release hygiene gate.

## T19 continuation checkpoint — 2026-10-02, after T20 root integration

- T20's root-current prompt integration receipt is `C:\Users\Adam\.local-ai-hub\artifacts\handoff\T20-t19-prompts-root-current-receipt-20261002.json`, SHA-256 `D529F138C0D33AE82180738571A7CD276CF09B09668C9AA20C3616C9D70EDFBE`. It records patch check/apply and `git diff --check` as passed, tests not run because T02 owns the exclusive slot, and the earlier 7-pass prompt/CodeGraph result as historical candidate evidence.
- Fresh root hashes after T20 integration: `docs/INSTALLATION.md` `3802B4F60012F8E5C0ECA12673F0D8273FC93E6EDEAFA03FD6AF838B7DBF463D`; `docs/INSTALL_PROMPT.md` `7E5DA693AEBDFE0BD2F025AA6176E75284701EB4B92FEDF636E64A88D7C6573B`; `docs/UPDATE_PROMPT.md` `50CE34F25602653652235A8267E6EA2D85953BB6541C2EC66DE7C40D22A31C97`; `docs/MODEL_CAPABILITIES.md` `09FE472497C3F8F5381CCFEFB64B21CA4453C9110F55BB7C22F22BC313487617`; `tests/test_release_hardening.py` `2FC77A30E13D928FB9EE527DB43D6260AAE7175E1A85BFA964180F2D0BE6A23F`. Root HEAD: `01df56605ccf484ebfe2808ac60d696c4e81dffc`.
- Read-only `git -C C:\Users\Adam\.local-ai-hub diff --check -- docs/INSTALLATION.md docs/INSTALL_PROMPT.md docs/UPDATE_PROMPT.md docs/MODEL_CAPABILITIES.md tests/test_release_hardening.py` returned exit 0 after integration. Normalized root-vs-candidate diff shows one textual delta: `docs/INSTALL_PROMPT.md` line 136 keeps T20's shared policy, `Delegation is the default for any task with useful bounded independent work.` `docs/INSTALLATION.md` and `docs/UPDATE_PROMPT.md` have no normalized textual delta despite byte-hash differences; Git reports candidate LF-to-CRLF normalization warnings. `MODEL_CAPABILITIES.md` matches byte-for-byte. T19 did not modify root.
- T02 remains active; no tests or benchmarks ran in this continuation. Prior candidate receipts remain historical, not fresh root verification. The Agent OS goal remains blocked/incomplete pending the slot, integrated acceptance, and clean-host Windows/Linux install/doctor/uninstall evidence; the standalone CGC runtime gate also remains open. `build/` and `dist/` remain untouched.
- T02 state rechecked from its live thread: active, so exclusive test/benchmark slot remains held. Token-economizer setup was attempted as required by the local instructions, but `C:\Users\Adam\.agents\skills\token-economizer\scripts\ensure-tools.ps1` is absent (also absent from the `.codex\skills` alternative); no installation or PATH mutation occurred.
- Test-file comparison for root integration: T19 candidate has two release-hygiene regression tests absent from root (`test_release_hygiene_allows_managed_installed_directories`, `test_release_hygiene_still_rejects_build_outputs`); root has T20's `test_release_gate_allows_the_live_installed_checkout`. The same file also has different MCP fixture/deadline setup, so integrate owned T19 test hunks only and preserve root-specific edits; do not replace the file. Prepared post-release selectors: `python -B -m pytest -q -p no:cacheprovider --confcutdir=tests --noconftest --tb=short tests/test_release_hardening.py::test_release_hygiene_allows_managed_installed_directories tests/test_release_hardening.py::test_release_hygiene_still_rejects_build_outputs`. Not run while T02 slot is held.

## T19 source-owned follow-up — 2026-10-02

- User delegated continuation of T19 docs/SDK/installer prompt alignment. Hub remains explicitly excluded. T11 currently owns the assigned serial validation slot after T02 released it; T11 thread is active and requesting its next assignment from T20. T19 ran no test, benchmark, install, or runtime check.
- Additional bounded source check: `pyproject.toml` declares `requires-python = ">=3.11"` and classifiers through 3.14; `install.ps1` selection/fallback and `install.sh` candidate list include Python 3.11–3.14; `tools/setup.py` requires 3.11+. Candidate `docs/INSTALLATION.md` range Python 3.11–3.14 matches these declarations. This is source inspection only, not host compatibility proof.
- Source-owned acceptance inventory remains: candidate static checker historical receipt exit 0; historical T19 unit/regression receipts remain in prior sections. Root T20 prompt integration diff-check receipt passes. Root still needs the two T19 release-hygiene selector hunks integrated; preserve T20's live-checkout test and MCP fixture edits. Prepared selector command from prior checkpoint remains unrun.
- Runtime/host gates are for T20's explicit slot: clean Windows/Linux install, doctor, reinstall/config preservation, uninstall/external-state review, frozen artifact pair, and integrated T20 live MCP/HTTP/auth/outage/restart/concurrency checks. Standalone CodeGraphContext operation also remains unverified. No release-ready claim.

## T19 release-hygiene gate prepared — 2026-10-02

- T20 queue order now: T04 slot 07, T15 correctness slot 08, T13 one-selector slot 09, T19 two release-hygiene selectors slot 10, T11 privacy/offline slot 11. T19 performs source/hash preflight only until T20 confirms slot 10 readiness. No tests, install, or runtime work ran.
- Patch artifact: `handoff/T19-release-hygiene-tests-root-current-20261002.patch`, SHA-256 `268360E97FBEC7EDEA7EBA23C13345AA9DD1BE74ED0BA33D15FEED079E2A77E4`. It adds only the two T19 release-hygiene test functions to root HEAD `tests/test_release_hardening.py`; preimage blob SHA-256 `a7672c49d5542fab28f2bc9c2dd122dba4e1a19d92fb8b4c6573ecbe3fb5723d`, synthetic postimage SHA-256 `b4a0d210d56e42dd351875ed200af773dfe00b210c4d3afe171e4daddc9c5f48`.
- Isolated `git apply --check` against a temporary copy of the exact HEAD preimage passed. Root-current `git apply --reverse --check --whitespace=nowarn` passed, proving the test-only patch is already integrated. No root write occurred. Both function bodies match T19 candidate exactly: SHA-256 `4f1a2245fb5b62b5e725de2ab4e1e59708d0202921be2c6b3bb9fbe313980c0e` and `8b7115092b316a763bf8af3b53d7370ab9f06cbc750334211d340645cb7724b1`.
- Slot-10 root inputs pinned in `handoff/T19-release-hygiene-test-patch-receipt-20261002.json`, SHA-256 `bb4ccff858a52e833bedbbe9c941e9b13258a0c3dd1c553bbf16f7def9c005d4`: `tests/test_release_hardening.py` `0b21e4eea8636d700dfef1389dc4c75da53c883da32d59e2f7aabfd9d8f0e70a`; `tools/release_check.py` `90a70686c30c8050ceffeef585a6ad07923c8865ce14ee97cbe2c8d9ca99c8ed`. Recheck these immediately before slot execution; preserve T20's separate test fixture edit in the same test file.
- Prepared slot-10 command (not run): `python -B -m pytest -q -p no:cacheprovider --confcutdir=tests --noconftest --tb=short tests/test_release_hardening.py::test_release_hygiene_allows_managed_installed_directories tests/test_release_hardening.py::test_release_hygiene_still_rejects_build_outputs`.

- T20 confirmed central queue ownership and corrected serial order: T13 slot 09 → T19 slot 10 → T11 privacy/offline slot 11 → T05 tenant slot 12 → T03 focused integration slot 13 after exact hash preflight. T21 has no separate slot; T20 reports T21→T11 source/test hashes match and 93 T11 project-config tests passed, but direct candidate attachment is blocked by ownership boundary and root integration remains unresolved. No duplicate tests started.

- T13 released slot 09 after one `outcome_unknown=true` Hub command (`req_31241f6fa3a3`); T13 receipt `handoff/T13-slot09-unknown-20261002.md`. No retry/native fallback. T19 is next in T20 queue for slot 10 but still awaits explicit T20 assignment; no selectors run.

- T20 placed slots 10+ on hold: Hub health `success=false, version=null`; no tests/native fallback until Hub recovery and a fresh explicit assignment. T19 rechecked pinned root hashes source-only: test file `0b21e4eea8636d700dfef1389dc4c75da53c883da32d59e2f7aabfd9d8f0e70a`, release checker `90a70686c30c8050ceffeef585a6ad07923c8865ce14ee97cbe2c8d9ca99c8ed`; root `git diff --check` exit 0.


## T19 reconciliation checkpoint — 2026-10-02, latest root state

- Rechecked root vs attached T19 candidate by normalized text. `docs/INSTALLATION.md`, `docs/UPDATE_PROMPT.md`, and `docs/MODEL_CAPABILITIES.md` are identical. `docs/INSTALL_PROMPT.md` has one intentional shared T20 policy delta at line 136: root says `Delegation is the default for any task with useful bounded independent work.` No other T19-owned docs/prompt delta remains.
- Root `tests/test_release_hardening.py` currently SHA-256 `0b21e4eea8636d700dfef1389dc4c75da53c883da32d59e2f7aabfd9d8f0e70a`; `tools/release_check.py` `90a70686c30c8050ceffeef585a6ad07923c8865ce14ee97cbe2c8d9ca99c8ed`. The two T19 release-hygiene test bodies match candidate; prepared patch is already integrated. Root scoped `git diff --check` passes. Tests were not run.
- T20 owns central queue. Latest status: Hub `success=false, version=null`; slots 10+ held, no native fallback. T19 selector gate awaits Hub recovery and new explicit slot 10 assignment. Exact command and pins remain in `handoff/T19-release-hygiene-test-patch-receipt-20261002.json`.
- Still open: clean Windows/Linux install, doctor, reinstall/config-preservation, uninstall/external-state checks; frozen same-revision artifact pair; T20 integrated live MCP/HTTP/auth/outage/restart/concurrency gates; standalone CodeGraphContext runtime. No publish/tag or release-ready claim.

- T20 queue update: slot10 was never assigned; T19 source/static work is complete, no tests ran. Slot11 now belongs exclusively to T11 for privacy selector then offline suite, no benchmark. T19 has no active slot; wait for next T20 allocation after T11 releases.


## Additional independent T19 documentation work — 2026-10-02

- `docs/T19_RELEASE_VALIDATION_RUNBOOK.md` contained three stale references tying frozen-source, Windows/Linux package smoke, and pytest to T02 slot release. Replaced them with T20-owned explicit serial assignment: a released prior slot alone does not authorize T19; assignment covers package build/install smoke and any pytest. This is T19-owned runbook text; no root edits.
- Patch `handoff/T19-runbook-serial-slot-policy-20261002.patch`, SHA-256 `0520fe902186f7e1d74deea92f45d5d61c42b1a433725301d5cf1958cb52feb9`; reconstructed pre-edit SHA-256 `948a6e826f0944478ca586298d47861140d4291e93f858b03984df9bd7874700`; current doc SHA-256 `fc8a799f1a79f09dc34c89f0f04ca833d077a475eb4a3e1056728214d53caa01`. Isolated apply-check passed; source doc has no trailing whitespace and ends with newline. Receipt: `handoff/T19-runbook-serial-slot-policy-20261002.receipt.json`, SHA-256 `e13e0c8175805a51c457c275a6409bba6ea0d70dfca89f61eb8af3dba13ddf93`. No tests, package builds, installs, runtime checks, publish, or tag ran.
- T01-owned inventory files remain under owner boundary; preserved the existing user-approved coverage artifacts without further edit. T19 runbook correction is independent.


## T19 operational runbook gates — 2026-10-02

- Extended the slot-policy correction to `docs/T19_CLEAN_HOST_INSTALLER_CYCLE.md`: clean-host install/reinstall/uninstall now requires a T20 explicit serial assignment for the exact frozen revision and each OS/Python combination; a prior slot release is insufficient. Patch SHA-256 `0366cd5ab446419dc884cec6710f162effe611bc3ec656ca06082fcc9239c344`, reconstructed preimage `80f7dde7a9f75a6e56e97ba9d53ca75674a7d78e0b5e7fbcf88fe23fe6f1ef24`, current doc SHA-256 `9e6bd37411ec8fbbe33f249047e7c812eaff618445bcfb9693c674e2b3600b64`; isolated apply-check passed. Receipt `handoff/T19-clean-host-slot-policy-20261002.receipt.json`, SHA-256 `175527b7b45fecce2fb4b2f084ac7ad91ce03a7f33f05e7284c632d1ceda97a7`.
- Latest T20 queue: T11 slot11; then T05 slot12, T03 slot13, T01 slot14, T08 no earlier than15 after root integration. T19 has no current slot; no validation ran.
- T04 reported unresolved gaming policy for `/api/repo/topology`: deterministic MCP read path passes its semantic gate, root HTTP path-mode gate denies in gaming. T04 patch remains unapplied pending T03/T13 owner decision and review. This is cross-track; no T19 edit made.


## T20 queue and root-current documentation handoff — 2026-10-02

- T20 queue corrected: T21 config_loader slot14, T01 slot15, T08 no earlier than16 after root integration. T19 has no current slot.
- Root HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc` does not contain either new runbook. Root preimage for each path is therefore absent. Prepared root-current additive patches, without applying: `handoff/T19-release-validation-runbook-root-current-20261002.patch` SHA-256 `e9cb89a3006f3b701bebe867f1758859840bd20054b6417e4f3a18225852d243`, postimage `docs/T19_RELEASE_VALIDATION_RUNBOOK.md` SHA-256 `fc8a799f1a79f09dc34c89f0f04ca833d077a475eb4a3e1056728214d53caa01`; `handoff/T19-clean-host-installer-cycle-root-current-20261002.patch` SHA-256 `52e4edb28489cb5dfd89124bef14a0d9b5112bfe2a6058aae2323c095e759440`, postimage `docs/T19_CLEAN_HOST_INSTALLER_CYCLE.md` SHA-256 `9e6bd37411ec8fbbe33f249047e7c812eaff618445bcfb9693c674e2b3600b64`. `git -C C:\Users\Adam\.local-ai-hub apply --check --whitespace=nowarn <each patch>` returned exit 0 for both. No root apply occurred.
- Receipts updated: `handoff/T19-runbook-serial-slot-policy-20261002.receipt.json` and `handoff/T19-clean-host-slot-policy-20261002.receipt.json`; both record absent root preimage, exact postimage, root check, and not-applied state.


## T20 serial queue update — 2026-10-02

- T05 explicitly released slot12 after hash drift; no pytest ran. T20 assigned exclusive `T20-CPU-SLOT-20261002-13` to T03. T03 must recheck all ten pinned selector hashes, stop on out-of-scope drift, run its pinned batch once, capture exact evidence, and release the slot. T19 forwarded those instructions; T19 did not run tests. Next queued owners: T21 slot14, T01 slot15, T08 no earlier than16 after root integration. T19 has no current slot.


## Slot13 drift and root-current runbook patches — 2026-10-02

- T03 slot13 stopped before pytest: `src/local_ai_hub/inprocess_transport.py` expected SHA-256 `4820102BE7AB5BF2E4F2C2F47CC45A500DA65F679FFCB67B7EB122D25C703982`, actual `AED6A4B8B3F04A3AC0977CFA6D1618FF316441D9ED0E8ED976E234BBF3250C38`. Prior contract-dispatch pin matched. No T03 tests started; slot13 released. T21 remains slot14, T01 slot15, T08 >=16 after integration; T19 has no slot.
- T20-requested root-current patch evidence at HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`: `handoff/T19-release-validation-runbook-root-current-20261002.patch` SHA-256 `e9cb89a3006f3b701bebe867f1758859840bd20054b6417e4f3a18225852d243`, root preimage absent/no blob SHA, postimage `fc8a799f1a79f09dc34c89f0f04ca833d077a475eb4a3e1056728214d53caa01`; `git apply --check --whitespace=nowarn` exit 0, not applied. `handoff/T19-clean-host-installer-cycle-root-current-20261002.patch` SHA-256 `52e4edb28489cb5dfd89124bef14a0d9b5112bfe2a6058aae2323c095e759440`, root preimage absent/no blob SHA, postimage `9e6bd37411ec8fbbe33f249047e7c812eaff618445bcfb9693c674e2b3600b64`; same apply-check exit 0, not applied. Older delta patches `T19-runbook-serial-slot-policy-20261002.patch` (`0520fe902186f7e1d74deea92f45d5d61c42b1a433725301d5cf1958cb52feb9`) and `T19-clean-host-slot-policy-20261002.patch` (`0366cd5ab446419dc884cec6710f162effe611bc3ec656ca06082fcc9239c344`) remain unchanged; they are not the root-current additions.


## Resumed T19 acceptance run — 2026-10-02

- Worktree: `C:\Users\Adam\.codex\worktrees\t19-docs-rollout\.local-ai-hub`; detached HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`. Dirty status was 277 rows before and after validation. Existing T01-owned dirty paths remain `M`: `docs/API_COVERAGE.md`, `tests/test_surface_inventory.py`, `tools/surface_inventory.py`; none were edited by this run.
- Exact command:

```powershell
$repo=(Get-Location).Path
$python='C:\Users\Adam\.local-ai-hub\.venv\Scripts\python.exe'
$env:PYTHONPATH=Join-Path $repo 'src'
$files=Get-ChildItem tests -Filter 'test_t19_*.py' -File | Where-Object { $_.Name -ne 'test_t19_packaged_sdk_smoke.py' } | Sort-Object Name | ForEach-Object { $_.FullName }
$extra=@(
  'tests/test_release_contract.py::test_release_metadata_and_documentation_are_current',
  'tests/test_release_contract.py::test_release_uses_only_current_local_ai_hub_contracts',
  'tests/test_release_contract.py::test_canonical_prompts_share_profile_and_installation_docs_own_standalone_setup',
  'tests/test_release_contract.py::test_release_docs_match_stable_defaults_and_ci_gate',
  'tests/test_release_contract.py::test_update_prompt_uses_branch_safe_pull_and_generated_artifact_wording',
  'tests/test_release_hardening.py::test_release_hygiene_allows_managed_installed_directories',
  'tests/test_release_hardening.py::test_release_hygiene_still_rejects_build_outputs')
& $python -B -m pytest -q -p no:cacheprovider --confcutdir=tests --noconftest --tb=short @files @extra
```

- Runtime: `.venv\Scripts\python.exe` Python 3.13.2, pytest 9.1.1; `PYTHONPATH` pointed to this worktree's `src`.
- Exact T19 modules (18; packaged SDK smoke excluded):
- `tests/test_t19_clean_profile_roundtrip.py`
- `tests/test_t19_codegraph_removal.py`
- `tests/test_t19_coverage_owner.py`
- `tests/test_t19_current_prompt_adoption.py`
- `tests/test_t19_doctor_optional_status.py`
- `tests/test_t19_hubctl_config_isolation.py`
- `tests/test_t19_install_contracts.py`
- `tests/test_t19_mcp_handshake.py`
- `tests/test_t19_packaging_contract.py`
- `tests/test_t19_parity_contract.py`
- `tests/test_t19_project_config_prompts.py`
- `tests/test_t19_prompt_profile_parity.py`
- `tests/test_t19_recovery_journal_schema.py`
- `tests/test_t19_rollback_contract.py`
- `tests/test_t19_rollback_snapshot.py`
- `tests/test_t19_sdk_docs.py`
- `tests/test_t19_sdk_scenarios.py`
- `tests/test_t19_sdk_wrapper_payloads.py`
- Additional exact selectors:
- `tests/test_release_contract.py::test_release_metadata_and_documentation_are_current`
- `tests/test_release_contract.py::test_release_uses_only_current_local_ai_hub_contracts`
- `tests/test_release_contract.py::test_canonical_prompts_share_profile_and_installation_docs_own_standalone_setup`
- `tests/test_release_contract.py::test_release_docs_match_stable_defaults_and_ci_gate`
- `tests/test_release_contract.py::test_update_prompt_uses_branch_safe_pull_and_generated_artifact_wording`
- `tests/test_release_hardening.py::test_release_hygiene_allows_managed_installed_directories`
- `tests/test_release_hardening.py::test_release_hygiene_still_rejects_build_outputs`
- Result: **77 passed, 1 skipped in 52.55s; exit 0**. Skip: `tests/test_t19_rollback_snapshot.py:175`, Windows directory-symlink privilege unavailable (`WinError 1314`).
- No source file changed during validation. `tests/test_t19_packaged_sdk_smoke.py`, build/install, clean-host Windows/Linux, service/runtime, and model checks did not run; the candidate is dirty and not T20's frozen revision.
- Prompt parity correction: candidate `docs/INSTALL_PROMPT.md` has the semantic on-demand line; root has the general delegation-default line. `tests/test_t19_prompt_profile_parity.py` asserts the candidate wording. No source edit made; T20/policy owner must reconcile if identical text is required. The earlier checklist statement that reversed these sides is corrected in `T19-prompt-clean-host-checklist-20261002.md`.

### Remaining acceptance blockers

- T01 still owns API coverage inventory/parser/tests; use its released source contract and same-revision inventory receipt before closing item 1.
- T21 typed project-config consumer receipt and validation remain absent; do not edit T21-owned code.
- T08 incompatible-database/crash-recovery receipt remains open.
- Package build/current artifact hashes and clean-host Windows/Linux receipts must bind to one T20-frozen clean revision and explicit serial assignment. Prior receipts are from older source snapshots.
- Overall T20 integration, independent review, and revision-bound release receipts remain open. Local T19 tests passing do not close these gates.

### 2026-10-02 CodeGraph doctor removal

- Removed CodeGraph from `tools/doctor.py` optional-component data and rendered status lines. Standalone CodeGraphContext/KuzuDB remain documented only as optional external tools in `docs/INSTALLATION.md`; install/update prompts and feature audit state that Hub does not install, configure, preprocess, invoke, or report them.
- Bounded source check: `rg -n -m 5 'codegraph|CodeGraph' tools/doctor.py` returned no matches. Docs stale-marker check for `not_managed` / doctor claims returned no matches. `git diff --check -- tools/doctor.py docs/FEATURE_AUDIT_V4.md docs/INSTALLATION.md docs/INSTALL_PROMPT.md docs/UPDATE_PROMPT.md`: exit 0.
- Read-only runtime/config/install preflight: `rg -n -i -m 3 'codegraph|kuzudb' src/local_ai_hub tools config.toml.example defaults.toml install.ps1 install.sh pyproject.toml` returned no references (exit 1 normalized to `NO_RUNTIME_CONFIG_INSTALLER_REFERENCES`).
- Extended T19-owned `tests/test_t19_codegraph_removal.py` source contract to include every `tools/*.py`, including `tools/doctor.py`; test not executed pending T20 GO. SHA-256 `2C37BFBB22ED4F44336EF749044E822EF0995E61D803998D54A710A4289B11AC`.
- No tests run: G remains UNKNOWN and no T20 serial-test slot is assigned.
- SHA-256: `tools/doctor.py` `94BB1EE3B303C5F9E6D1747DB82093C97A02E985398FC10AE394961BE2CF9691`; `docs/INSTALLATION.md` `541920D634A139F3E303758ED6AE8ED107CAD549206329241BFE045467A9214E`; `docs/INSTALL_PROMPT.md` `15C96DE6AFDA833238EAAB519F94547192A1E1543912A770EA6C20285C72D742`; `docs/UPDATE_PROMPT.md` `9E06FC795EEED02399D42EC4BC77B8836204B3E8CEE7EB92A3B61C9C69D75260`; `docs/FEATURE_AUDIT_V4.md` `4EE159E7E48E8834CED166CC94C07D9BACA74B5EF518ADA4D41022B80D55BD33`.
- Remaining release blockers unchanged: T01 coverage owner receipt, T21 config consumer receipt, T08 database recovery receipt, T20 frozen revision and clean-host Windows/Linux checks, integrated T20 acceptance.

### 2026-10-02 shared-runtime install/docs preparation

- T19-owned doc/config hunks updated: `config.toml.example`, `docs/INSTALLATION.md`, `docs/MCP_AND_AGENTS.md`, `docs/OPERATIONS.md`, `docs/SECURITY_MODEL.md`, `docs/TROUBLESHOOTING.md`, `docs/INSTALL_PROMPT.md`, and `docs/UPDATE_PROMPT.md`. Content covers one per-user daemon, lightweight stdio proxies, managed-entry migration, loopback/auth defaults, per-user service restart after login/reboot, dashboard access, and matching code/config/state/agent-MCP rollback sets.
- Source-backed current setup facts: `tools/setup.py::build_mcp_entries` and `src/local_ai_hub/generator.py` currently emit one `local-ai` stdio entry using the installed Python/module, install cwd, `LOCAL_AI_CONFIG`, and `PYTHONPATH`; setup's managed merge backs up and preserves unrelated MCP entries. The generated command/args/cwd/env remain authoritative. T03 must supply final proxy entry and stdio lifecycle; T04 must supply exact daemon transport/auth/readiness/offline/retry contract; T06 must supply final user-service identity/control/startup contract. Prompts avoid hardcoding those pending fields/commands.
- Other confirmed defaults: `server.bind=127.0.0.1`, port `11435`; remote non-loopback requires `allow_remote=true` and an API token of at least 16 characters. `hubctl dashboard` prints dashboard URL. Windows service startup is per-user logon task, macOS uses a LaunchAgent, Linux uses a systemd user service; availability begins with user session. Rollback snapshot coverage remains exactly code/config/state; agent MCP configs are extra labeled roots, not `--covers` values.
- No source/runtime edits and no tests. T03/T04/T06 are still active; exact interface acceptance and T20 serial GO remain pending. `git diff --check` exited 0. Current SHA-256: `config.toml.example` `35589127F4D4E605210B4D2D64967922DC46E081340E8A3A042DF4D35E39B587`; `docs/INSTALLATION.md` `94F854BE6251724973113C77759B20BE94F1B1202968B2636A0899E8B66959DD`; `docs/MCP_AND_AGENTS.md` `41B915E88EF76297116F9F7A2E9917F13989D05CF728F35D08377FA5F6963CF5`; `docs/OPERATIONS.md` `3CD9325DA9FEDBD392AFCF052A2F0F2CD97A209092B472624B0220442A3D8FC7`; `docs/SECURITY_MODEL.md` `568F5EE69EB87B5764D3CFFAD3225DB21611DA31F9BF05D10E7D244A10D6CDF5`; `docs/TROUBLESHOOTING.md` `264DA93ECA5F8E98115F43A10496E7A88A4722B5EF4DD0AA4BAF8BCA712B5B05`; `docs/INSTALL_PROMPT.md` `83470840D15109FC70E2CA30463EC0D0CCCE218E2D08C22BAA58905FDB82879D`; `docs/UPDATE_PROMPT.md` `877E191CA03C8841E88C9C3B0FAD8B8CA551BA611F883F37684E3E32B9F3000B`.

### 2026-10-02 caller-root/shared-runtime docs revision

- Baseline: `HEAD 2b33602adef0d030fea66cdcc04ca742c60b2e32`, 73 dirty paths. All eight product doc/config files below were already dirty before this revision; no other product paths changed here. The existing untracked handoff was appended as checkpoint only. Before/after SHA-256 pairs are recorded below.
- Source pins: `tools/setup.py:715-719` generates both project-local (`SOURCE_ROOT`) and global (`install_dir`) artifacts; `src/local_ai_hub/generator.py:822-834` currently emits one `local-ai` stdio command using installed Python/module, `cwd=install_dir`, `LOCAL_AI_CONFIG`, and `PYTHONPATH`. `mcp_server.py:154-163` on current root still attaches `InProcessTransport`/`LocalAIApp`; T03 proxy implementation is separate and not integrated here. Caller worktree root/task/tenant must therefore be explicit per request; process cwd must not determine repository context.
- Docs change: distinguish project-local `cwd=target_root` from global `cwd=install_dir`; global proxy requires caller root/task/tenant; document one user daemon with lightweight stdio proxy, loopback/auth defaults, user-session restart, dashboard and backup/restore of managed agent MCP configs. Added Codex MCP recipe to use installer-generated `local-ai` entry and not hand-author command/args/env. Prompts use generated command/args/cwd/env as authority and add no guessed args or environment variables.
- T03 implementation handoff is available; T04 and T13 remain active. T04/T13 exact auth, readiness, offline/retry and lifecycle behavior remain unfinalized. T20 serial test GO remains absent. No tests or source/runtime edits.
- Before -> after SHA-256: `config.toml.example` `35589127F4D4E605210B4D2D64967922DC46E081340E8A3A042DF4D35E39B587` -> `E7130AA3B5630D28E32BE7D2F303B3BB979361A22AE10A8BBEDD46A26C719EA2`; `docs/INSTALLATION.md` `94F854BE6251724973113C77759B20BE94F1B1202968B2636A0899E8B66959DD` -> `167E18AF04B60CD2B240122A23FDB942F5CCD4F440294D3AC5E3501A262EA085`; `docs/MCP_AND_AGENTS.md` `41B915E88EF76297116F9F7A2E9917F13989D05CF728F35D08377FA5F6963CF5` -> `447B4CD9DAD254EB977AD2A22E5EFB5F45E7AEE9EB953B891CE7399611A99973`; `docs/OPERATIONS.md` `3CD9325DA9FEDBD392AFCF052A2F0F2CD97A209092B472624B0220442A3D8FC7` -> `135D1F9B6F1C382563408F3890D73FD400DA4A3C96AA8404A488FF3AB00B3A30`; `docs/SECURITY_MODEL.md` `568F5EE69EB87B5764D3CFFAD3225DB21611DA31F9BF05D10E7D244A10D6CDF5` -> unchanged; `docs/TROUBLESHOOTING.md` `264DA93ECA5F8E98115F43A10496E7A88A4722B5EF4DD0AA4BAF8BCA712B5B05` -> `728DAD8B30FB7BAE056ED2DD741CEA1811BF20C80233BF8D6D044A34D855E321`; `docs/INSTALL_PROMPT.md` `83470840D15109FC70E2CA30463EC0D0CCCE218E2D08C22BAA58905FDB82879D` -> `A0581A7ED887A691C4F3D0D5CBF0295F565C150E69139264639C5EC6272FF281`; `docs/UPDATE_PROMPT.md` `877E191CA03C8841E88C9C3B0FAD8B8CA551BA611F883F37684E3E32B9F3000B` -> `ABE604AF3C433E80960B9A6F525ADB187885F6F296146C596AEA51BF484E385F`.
- `git diff --check -- config.toml.example docs/INSTALLATION.md docs/MCP_AND_AGENTS.md docs/OPERATIONS.md docs/SECURITY_MODEL.md docs/TROUBLESHOOTING.md docs/INSTALL_PROMPT.md docs/UPDATE_PROMPT.md`: exit 0. After MCP recipe addition, `docs/MCP_AND_AGENTS.md` SHA-256 is `447B4CD9DAD254EB977AD2A22E5EFB5F45E7AEE9EB953B891CE7399611A99973`. Final handoff diff-check/hash recorded after this revision.

### 2026-10-02 T03/T04/T13 shared-runtime contract sync

- Correction to earlier checkpoint: T03, T04, and T13 final handoffs are now available. Their implementation changes remain separate and are not integrated into this T19 candidate. This revision changes owned docs/config/prompts only.
- Corrected security contract from T13: bind is exactly `127.0.0.1`; non-loopback binds, `allow_remote = true`, and anonymous HTTP API access are unsupported. Protected HTTP routes require one configured API token sent in `X-LocalAI-Token` or `Authorization: Bearer`. Supported permissions are `monitor`, `read`, `write`, and `admin`; optional `api_token_tenant` binds that token to one tenant. `/health` is public liveness, `/dashboard` is a public static shell, and `/ready` requires monitor authorization. Tenant labels alone do not authenticate callers.
- Both install/update prompts now include the T13 async job and conversation contract: sorted supported `job_action` list and mapped routes; sync/async/auto delivery rules; `cold_start_review_diff`; durable HTTP/MCP lifecycle actions; stable replay/idempotency conditions; TTL/expiry, wait, cancellation, and terminal `outcome_unknown`; tenant-scoped in-memory conversations and defaults.
- Static marker inspection found all 48 required prompt contract strings in both prompts. This was a read-only text check, not test execution. `git diff --check` exit 0. T20 serial GO remains absent; no tests, builds, service checks, or runtime validation ran.
- Before -> after SHA-256 for this revision: `config.toml.example` `E7130AA3B5630D28E32BE7D2F303B3BB979361A22AE10A8BBEDD46A26C719EA2` -> `8E5BD45E28E467FE67482C0996DE8E2C06ED11CEABCD140B18D1857AB13D8A40`; `docs/INSTALLATION.md` `167E18AF04B60CD2B240122A23FDB942F5CCD4F440294D3AC5E3501A262EA085` -> `068630A872763530E24FC6413B9D29E16F884DFC47BA6B572AEC9C645FF46580`; `docs/OPERATIONS.md` `135D1F9B6F1C382563408F3890D73FD400DA4A3C96AA8404A488FF3AB00B3A30` -> `4CCCA2B8F0C83ADB4E868D9B691D08BD3F00840F9C1B0673489C3772C1A9190B`; `docs/SECURITY_MODEL.md` `568F5EE69EB87B5764D3CFFAD3225DB21611DA31F9BF05D10E7D244A10D6CDF5` -> `1288A90775F7884757C51149924AD0D27B482913744F7D7FB285112CAC0E850F`; `docs/TROUBLESHOOTING.md` `728DAD8B30FB7BAE056ED2DD741CEA1811BF20C80233BF8D6D044A34D855E321` -> `CCCEDD3E6D670AD302DAB2E29307AF90F87B3D24D497F6FDC4BEF80C1370767E`; `docs/INSTALL_PROMPT.md` `A0581A7ED887A691C4F3D0D5CBF0295F565C150E69139264639C5EC6272FF281` -> `E7BE63AC390A596FF0CA2201E8432992AD2A2B2A0B6DADBFCBD028270AB9C8E7`; `docs/UPDATE_PROMPT.md` `ABE604AF3C433E80960B9A6F525ADB187885F6F296146C596AEA51BF484E385F` -> `A640C6EB6EB08E3C9C53D37524A113271F4C82AEE5B036194936BDA69F194DEE`. `docs/MCP_AND_AGENTS.md` was not changed in this revision.
- Candidate remains at HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`, with 73 dirty paths. Preserve all existing dirty ownership. T20 integrated acceptance and revision-bound receipts remain open.
### 2026-10-02 shared-runtime proxy, root, and offline contract follow-up

- Updated T19-owned shared-runtime docs plus `docs/MCP_AND_AGENTS.md` to remove the claim that callers explicitly pass tenant on every request. Global entries run with `cwd=install_dir`; project-local entries use `cwd=target_root`. Every global repository, task, or memory request must carry the explicit caller project root and preserve task context. Tenant propagation is explicitly pending T03/T04/T13 integration.
- Documented target architecture: one user-scoped supervisor/daemon; lightweight per-agent stdio proxies forward to it and do not instantiate `InProcessTransport`, `HubServices`, another `LocalAIApp`, or another full daemon. T03/T04/T13 integration is not in this candidate, so docs label this as release contract rather than current runtime proof.
- Static source pins for current checkout: `src/local_ai_hub/generator.py:824-834` emits global stdio registration with `cwd=install_dir`, configured Python/module, `LOCAL_AI_CONFIG`, and `PYTHONPATH`; project generation uses `target_root`. `src/local_ai_hub/client.py:209-317` bounds startup by `startup_wait`, uses a cross-process lock, and blocks direct launch when managed service/supervisor/listener owns the installation. `src/local_ai_hub/client.py:154-162` returns structured `outcome_unknown` after uncertain transport failure. Distinguishing `request_not_sent` from `outcome_unknown` remains T04 integration work. Current `src/local_ai_hub/mcp_server.py` still builds the older in-process MCP runtime; lightweight proxy integration is not verified here.
- Added operations guidance for supervisor restart/recovery, structured offline errors, and no automatic replay of `outcome_unknown`. Existing rollback contract still backs up matching daemon code, config, complete `server.state_dir`, SQLite WAL/SHM, and managed agent MCP registrations together.
- No tests or runtime checks ran, per instruction. `git diff --check` on all changed docs exited 0. HEAD remains `2b33602adef0d030fea66cdcc04ca742c60b2e32`; dirty path count remains 73.
- Before -> after SHA-256: `docs/INSTALLATION.md` `068630A872763530E24FC6413B9D29E16F884DFC47BA6B572AEC9C645FF46580` -> `1166D5DCBD3B7E2DCE5C022854481B4D931C8D3A3B035B6D33A19BFD255D0244`; `docs/MCP_AND_AGENTS.md` `447B4CD9DAD254EB977AD2A22E5EFB5F45E7AEE9EB953B891CE7399611A99973` -> `527414DFCCA57DCEE6DC6CAAFEBC0A8E9818B6AC51826FDA3F736F9DF0845592`; `docs/OPERATIONS.md` `4CCCA2B8F0C83ADB4E868D9B691D08BD3F00840F9C1B0673489C3772C1A9190B` -> `DCB7C525A168974BB80DFB4790B1ECE45DBA3DF6500D0AED1B1F083EFB6FE491`; `docs/TROUBLESHOOTING.md` `CCCEDD3E6D670AD302DAB2E29307AF90F87B3D24D497F6FDC4BEF80C1370767E` -> `7AE0DDDA4BC55D0227FF4ECB2E46B8EA6B317A51E7064DF5AA376257801DC94D`; `docs/INSTALL_PROMPT.md` `E7BE63AC390A596FF0CA2201E8432992AD2A2B2A0B6DADBFCBD028270AB9C8E7` -> `460780148AA484A50D9C949C6295CFDD0F9526AA37D782DCAB7BA5BDCB2086E3`; `docs/UPDATE_PROMPT.md` `A640C6EB6EB08E3C9C53D37524A113271F4C82AEE5B036194936BDA69F194DEE` -> `AC3C5C5B0D57F11E63579D21C7921BD474A8BDA28683B8417DBC436DE17D8858`.
- Changed paths this follow-up: `docs/INSTALLATION.md`, `docs/MCP_AND_AGENTS.md`, `docs/OPERATIONS.md`, `docs/TROUBLESHOOTING.md`, `docs/INSTALL_PROMPT.md`, `docs/UPDATE_PROMPT.md`, and this handoff. No source, tests, or config changed.
- Final root-field wording/hash correction after the preceding checkpoint: explicit global `root` is now named in every affected document; tenant remains pending. Final SHA-256: `docs/INSTALLATION.md` `530E4D29E9C223FF17C8F2FDDFD8B533F7E28134874785AD80D7D96B14537141`; `docs/MCP_AND_AGENTS.md` `E8CA6898701ADF337525828B9AA9BE049FF219E51FDBC222F7DE828768FA0200`; `docs/OPERATIONS.md` `60D023558F315AA44DFC8BB5E06DA577F3E5CE6D9F5E577FACC1D6453BD6AC6B`; `docs/TROUBLESHOOTING.md` `AD424D0B2E6952EACC400068A1A199C2FCE2B1E740444F603F39EE0641F4F5A5`; `docs/INSTALL_PROMPT.md` `74B7191DAE02808D6D2084A1973184F3776EABCDAFC4D5F71A042477CC915867`; `docs/UPDATE_PROMPT.md` `5EABDF8931C712F1776F3B4AD1A9C97717E23A44103E061A07D4AAE35042DEFE`. `git diff --check` exit 0; dirty count 73. No tests ran.
### 2026-10-02 T13 root-scoped principal/effective-tenant docs sync

- Synced T13 stable contract into the T19-owned sample config and docs/prompts. Principal precedence is `security.api_token_tenant`, then `security.api_token_principal`, then `api-token-default`. Root-scoped memory/task requires explicit absolute, existing, symlink-free `root` inside `security.allowed_roots`; max 32 entries, empty default denies. Both MCP API and `HubClient` must send caller root; neither may infer it from installation cwd.
- Server derives root effective tenant as `root-` plus HMAC-SHA256 keyed by `security.tenant_derivation_key`, falling back to `security.api_token`, over `local-ai-root-tenant\0{principal}\0{canonical_root}`. Rootless session binds to principal. Browser routes keep special browser tenant. `X-LocalAI-Tenant`, `X-Tenant-ID`, and body/query tenant values are consistency assertions only; mismatch is terminal 403.
- Fixed malformed root-field wording in MCP guide. Updated security, install, operations, troubleshooting, MCP, and both prompts; added sample config comments/keys for `api_token_principal`, `tenant_derivation_key`, and `allowed_roots`. T13 lifecycle/auth code remains candidate-only and untested; docs do not claim this T19 checkout implements it.
- Changed product paths: `config.toml.example`, `docs/SECURITY_MODEL.md`, `docs/MCP_AND_AGENTS.md`, `docs/INSTALLATION.md`, `docs/OPERATIONS.md`, `docs/TROUBLESHOOTING.md`, `docs/INSTALL_PROMPT.md`, `docs/UPDATE_PROMPT.md`; this handoff also changed. No runtime or test paths touched. No tests/install run.
- Baseline retained: HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`, 73 inherited dirty paths. `git diff --check` on all changed product files exited 0.
- Before -> after SHA-256: `config.toml.example` `8E5BD45E28E467FE67482C0996DE8E2C06ED11CEABCD140B18D1857AB13D8A40` -> `2DA721268BC147DFA9966B312BF3A1A74CC5AFF36DF718CF65A96583F4487EB6`; `docs/SECURITY_MODEL.md` `1288A90775F7884757C51149924AD0D27B482913744F7D7FB285112CAC0E850F` -> `690FF7A1264D4515E54974686050483120D2434A1042DEF3DD483A156AEFC229`; `docs/MCP_AND_AGENTS.md` `E8CA6898701ADF337525828B9AA9BE049FF219E51FDBC222F7DE828768FA0200` -> `64EED3B3D05C66E92F517A5178642BFB47E685A2F01D1EE354C201409D5A7335`; `docs/INSTALLATION.md` `530E4D29E9C223FF17C8F2FDDFD8B533F7E28134874785AD80D7D96B14537141` -> `64612375BD2FEF0EA3A77D0521F58C4ECCCD015A4566816350BF64D78DEFAB71`; `docs/OPERATIONS.md` `60D023558F315AA44DFC8BB5E06DA577F3E5CE6D9F5E577FACC1D6453BD6AC6B` -> `8AEF560CB5B4F87B0ECE641EF3672DEF867BC817B804014F2D7F0A8DFCA05F7E`; `docs/TROUBLESHOOTING.md` `AD424D0B2E6952EACC400068A1A199C2FCE2B1E740444F603F39EE0641F4F5A5` -> `11D0CC3CFEB3CCA0175132F32AC27FDA41F2A0876F21E249BAC5A7BF3A786ADF`; `docs/INSTALL_PROMPT.md` `74B7191DAE02808D6D2084A1973184F3776EABCDAFC4D5F71A042477CC915867` -> `9CA8A98BAC75E13B6AADE8BD3644293CB4AA059C981E42CE2BECB5D28026F8D9`; `docs/UPDATE_PROMPT.md` `5EABDF8931C712F1776F3B4AD1A9C97717E23A44103E061A07D4AAE35042DEFE` -> `A147BC38D81577A15340D96D9DF52CB99F73A118CAF21C0B0895B0E3F88CC018`.
### 2026-10-02 one-per-user install/update/rollback contract

- Clarified clean install and update acceptance: one user install, one `server.state_dir`, and one user service/supervisor shared by all Codex chats and worktrees for the OS account. Each enabled agent uses a lightweight stdio proxy. Clean install registers exactly one service; update reuses/reconciles it. No per-agent, chat, repository, or worktree daemon/service.
- Config sample now states shared per-user state/service scope. Installation and both canonical prompts state the singleton lifecycle. Operations/rollback records service-manager identity and enabled state separately because service registration is external to rollback file roots/`--covers`; restore matching code/config/state/proxy registrations, then reconcile the same service once. Troubleshooting directs all chats/worktrees to the same service.
- Runtime/source integration remains pending T03/T04/T13 in this candidate. No installer, service, or process was executed. No tests/install ran. Parent GO remains required before platform acceptance. `git diff --check` over edited config/docs/prompts exited 0.
- Inherited baseline preserved: HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`, 73 dirty paths. Current delta changed only `config.toml.example`, `docs/INSTALLATION.md`, `docs/OPERATIONS.md`, `docs/SECURITY_MODEL.md`, `docs/TROUBLESHOOTING.md`, `docs/INSTALL_PROMPT.md`, and `docs/UPDATE_PROMPT.md`; no runtime/test files. Prior T19-owned `docs/MCP_AND_AGENTS.md` changes remain intact and unchanged in this delta.
- Before -> after SHA-256: `config.toml.example` `2DA721268BC147DFA9966B312BF3A1A74CC5AFF36DF718CF65A96583F4487EB6` -> `1130A9A6B0CD3F535919F8B7C13F7824316D3F2382D4B340E0448212BEBD2B5F`; `docs/INSTALLATION.md` `64612375BD2FEF0EA3A77D0521F58C4ECCCD015A4566816350BF64D78DEFAB71` -> `31AD32D43C4AD39DDFB4854F6A211AAB0F97A794B83A04011296B8FC30F4B177`; `docs/OPERATIONS.md` `8AEF560CB5B4F87B0ECE641EF3672DEF867BC817B804014F2D7F0A8DFCA05F7E` -> `EF678F97D8213909AF1B6427427117D5578F63726338D61DD3AD7CFF19424F81`; `docs/SECURITY_MODEL.md` `690FF7A1264D4515E54974686050483120D2434A1042DEF3DD483A156AEFC229` -> `154468ABA29A0A4B959301A7993215AEE136A74BE2887380CC748DCC2EC276DB`; `docs/TROUBLESHOOTING.md` `77403E8D566586771E28A3B79F14BE7535B66C0E5150885F052D8ECEE8BCFE9F` -> `EBFF8E8FFC1493D98C2FA751C2C61B6A6744A2903ED1F5232B1B55F53AD1A285`; `docs/INSTALL_PROMPT.md` `9CA8A98BAC75E13B6AADE8BD3644293CB4AA059C981E42CE2BECB5D28026F8D9` -> `C617B3199843E559779A6D6574A48F51B5687DEA5FC476805C055A62C95C6486`; `docs/UPDATE_PROMPT.md` `A147BC38D81577A15340D96D9DF52CB99F73A118CAF21C0B0895B0E3F88CC018` -> `E152A283631820707DF8AD93545C74661043FDC7B84682E6DF3B122666CBCF5C`.
### 2026-10-02 install/update/rollback command and clean-host matrix

- Added `docs/OPERATIONS.md` shared-daemon command/acceptance matrix and linked detached-fallback diagnosis from troubleshooting; both canonical prompts now require checking one per-user platform service registration after install/update. Platform identities are source-pinned from current `tools/service.py`: Windows Task Scheduler `LocalAIHubSupervisor` (registry startup fallback only if task registration is unavailable), macOS LaunchAgent label `com.localai.hub`, Linux systemd user unit `local-ai-hub.service`.
- Documented exact clean-checkout install commands (`powershell -ExecutionPolicy Bypass -File ".\install.ps1" -Profile auto`; `./install.sh --profile auto`), existing-install update commands, user-venv `hubctl.py restart/status/service-status`, loopback health check, and restored-tree `tools/service.py install` reconciliation. Existing rollback snapshot `create`/`restore` commands keep same roots/labels and `--service-stopped`; manager registration is recorded separately because file snapshots do not contain it.
- Matrix covers clean install, multiple chats/worktrees, loopback/auth/root isolation, update preservation, restart/login persistence, and rollback. It explicitly rejects per-agent/worktree service, rejects `detached-fallback` as reboot-persistent acceptance, and marks every platform gate NOT RUN. T03/T04/T13 integration remains absent from T19 runtime; source docs candidate is not platform proof.
- This delta changed `docs/OPERATIONS.md`, `docs/TROUBLESHOOTING.md`, `docs/INSTALL_PROMPT.md`, `docs/UPDATE_PROMPT.md`, plus this handoff. No source/config/test file changed in this delta; prior T19 config/security/MCP/install documentation hunks remain intact. No installer, service, process, or test ran.
- Inherited baseline retained: HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`, 73 dirty paths. `git diff --check` over this delta exited 0.
- Before -> after SHA-256: `docs/OPERATIONS.md` `EF678F97D8213909AF1B6427427117D5578F63726338D61DD3AD7CFF19424F81` -> `38ACCBAC67E8E7B67DF926CF46D53C230D4B58FDE2F90498D0E3DFD4EBC99569`; `docs/TROUBLESHOOTING.md` `EBFF8E8FFC1493D98C2FA751C2C61B6A6744A2903ED1F5232B1B55F53AD1A285` -> `2A8B2A19373E559F1CD0F22608502FE36802DA705E1E1B833E4CDF25EF37CFC5`; `docs/INSTALL_PROMPT.md` `C617B3199843E559779A6D6574A48F51B5687DEA5FC476805C055A62C95C6486` -> `9FE7C49F9642F7BC8CCF06F41AE8042E4E9EB57E00DFB3E82196926D71A8997F`; `docs/UPDATE_PROMPT.md` `E152A283631820707DF8AD93545C74661043FDC7B84682E6DF3B122666CBCF5C` -> `6C08B16E8BE573FC36CCAE36F5585D956BF712AD7020F0AA0703C5875DED2CE6`.