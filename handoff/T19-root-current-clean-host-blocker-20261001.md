# T19 root-current scope and clean-host status — 2026-10-01

## Checkouts

- Root `C:\Users\Adam\.local-ai-hub`: HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`; 447 dirty paths observed. This work wrote no root files. All 28 selected root paths still match their baseline SHA-256 values.
- T19 candidate `C:\Users\Adam\.codex\worktrees\t19-docs-rollout\.local-ai-hub`: HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32` plus dirty work preserved. T19 patch scope contains 28 paths: 7 root-existing files updated, 19 candidate files added, 2 identical. It includes docs and 19 T19 tests.
- Ownership boundary: excluded T01-owned `docs/API_COVERAGE.md`, `tools/surface_inventory.py`, `tests/test_surface_inventory.py`; excluded shared `AGENTS.md` and `tests/test_release_contract.py` hunks. Ownership snapshot lists 36 inherited/unconfirmed dirty paths; scope overlap is 0. Candidate and inherited changes remain untouched.

## Root-current patch

- Patch: `handoff/T19-root-current-owned-overlay-20261001.patch`, SHA-256 `348309F6FF0237A9A590730DC65FF4BCAF29515BDF9B67D09E266B4A0CB5D0D8`, 330125 bytes.
- Manifest with per-path root/candidate SHA-256: `handoff/T19-root-current-owned-overlay-20261001.json`, SHA-256 `59164F6BC5032D41EA659575D757C25C8DE2926862AA976A9BBE3029EAB0643F`.
- Validation: `git apply --check` passed against an isolated selected-path snapshot of current root. Patch applied there. All 28 resulting scoped files matched candidate hashes. Root HEAD and all selected root bytes remained unchanged.
- Full-tree test overlay did not complete. A whole-checkout copy reached about 37.9 GB because it included heavy local runtime/install trees. The attempted test produced no receipt. Its temporary tree has now been removed. Do not infer a test pass from the selected-path overlay.
- Existing candidate evidence remains separate: T19 regression suite 69 passed / 1 Windows symlink-permission skip; packaged SDK smoke 2 passed. Receipts: `handoff/T19-candidate-validation-20261001.md` SHA-256 `ADEF14DEEE893446A9061DB0AB13D70C7F95862FE66A43BC1591973E3EC007AF`; package receipt `C:\WINDOWS\Temp\t19-packaged-sdk-iq0fbvq7\receipt.json` SHA-256 `3D509FE80DFFAC7CE7062D23DE886EB387FBECC63971B4C0E003030C51EEF040`. These are candidate-only results.

## Clean-host blocker

- Clean-host installer runbook is **procedure only**. No clean Windows or Linux result recorded. Frozen T20 post-integration artifact is required; existing wheel/sdist/install receipts use candidate/development-host artifacts, some predating latest prompts. No disposable clean Windows/Linux VM receipt is available here.
- The actionable blocker is unavailable same-revision frozen artifacts and clean Windows/Linux hosts. T20 must freeze and identify one artifact pair, then run install, doctor, reinstall/config preservation, uninstall/external-state preservation on both clean hosts and bind receipts to artifact hashes.
- T20 same-revision live MCP/HTTP/HubClient, auth/negative, outage/restart/concurrency, and final completion gates remain open. CodeGraph stays optional standalone tooling; not part of Hub runtime/setup.

No release or clean-host acceptance claim follows from this handoff.

## Bounded root-source test overlay

- Receipt `handoff/T19-root-source-tests-20261001.json`, SHA-256 `EF737EE653DB5BECF4091A4D5D2CD5977B5973E45CBB7F1898BB7C38AFAC8A68`. Overlay copied root `src/`, `tools/`, `docs/`, selected top-level config/install files, T19 candidate test paths, and applied the owned patch. It excluded full checkout, virtual environments, runtime trees, build and dist; temporary overlay removed after run.
- Exact all-19 command ended at collection: `ImportError: cannot import name T19_RUNTIME_PARITY_CONTRACT from local_ai_hub.generator` in `tests/test_t19_parity_contract.py`. Current root generator lacks candidate's dirty inherited symbol.
- Remaining 18 paths: **19 failed, 49 passed, 1 skipped, 3 subtests passed in 45.92s**. Failures cover unintegrated CodeGraph/doctor/hubctl, recovery journal and rollback docs, package smoke, and SDK route behavior. Candidate suite results remain separate (69 passed/1 skipped, package smoke 2 passed).
- These failures show root integration gaps. They do not falsify candidate-only receipts or prove release readiness.

## Root-compatible install/prompt slice — 2026-10-01, revision 2

- Patch `handoff/T19-root-current-install-sdk-docs-disjoint-20261001.patch`, SHA-256 `E003E1F7C372981742D932A1DB5A2BB4D4EB92EF45DE13CFEE8C80C4D996E5CA`, 26,247 bytes. Six paths: `docs/INSTALLATION.md`, both prompts, and three T19 tests. Patch contains no `/api/context/pack` reference or source/API change.
- Install guide explains `--skip-service` behavior, preserves existing-config text, and pins optional standalone CodeGraphContext to `0.6.13`; [PyPI](https://pypi.org/project/codegraphcontext/0.6.13/) confirms release and `gcf` extra. CodeGraph remains outside Hub runtime/setup.
- INSTALL/UPDATE prompts place health/schema/model-routing guidance at matching policy locations and append current document/diagram plus LLM-card guidance. Root target Adaptive sections match both T19 candidate prompts. Candidate prompt hashes remain INSTALL `D77344A3B685141413F90FA4BCDB5E716D976BB6E2029D7B8CB62AB94B027FBC`, UPDATE `BDDE8E04ADA45DA2B92EB84A8AFAD372A3DF02DD7472DBFEB83652CA08697A31`.
- `git apply --check` passed against current root. Bounded root-source overlay command: `python -B -m pytest -q -p no:cacheprovider --confcutdir=tests --noconftest --tb=short tests/test_t19_packaging_contract.py tests/test_t19_prompt_profile_parity.py tests/test_t19_codegraph_removal.py::test_optional_codegraph_docs_use_current_gcf_extra_without_hub_integration`; result **4 passed in 0.03s**. Prompt section parity and per-path hashes passed. Root and selected root paths remain unchanged.
- Manifest `handoff/T19-root-current-install-sdk-docs-disjoint-20261001.json`, SHA-256 `EE134DB49126022CBB4DA1C37713A05A94C02B01B2FFD442998876CC99CC3486`, records exact root/patched hashes and command.
- SDK route guide/test remain candidate-only because their complete route inventory includes the explicitly excluded endpoint. Clean-host Windows/Linux and full T20 gates remain open.
