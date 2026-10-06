# T19 candidate package and scoped validation — 2026-10-01

## Candidate identity and scope

Candidate worktree: `C:\Users\Adam\.codex\worktrees\t19-docs-rollout\.local-ai-hub`, HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32` plus current T19 dirty working tree. No root writes, user profile/config, daemon, Hub, network, global package install, or GPU operation.

## Protected packaged SDK smoke

`tests/test_t19_packaged_sdk_smoke.py` was not modified. A first pytest invocation under the base interpreter failed because its subprocess adds `-I`, hiding user-site setuptools (`ModuleNotFoundError: No module named 'setuptools'`). Resolved without network/global install: copied only local setuptools 84.0.0 and wheel 0.48.0 package files into disposable runner venv and executed protected unittest file directly.

Exact command:

```text
C:\Users\Adam\AppData\Local\Temp\t19-packaged-runner-gni7w1_6\runner-venv\Scripts\python.exe -I -B C:\Users\Adam\.codex\worktrees\t19-docs-rollout\.local-ai-hub\tests\test_t19_packaged_sdk_smoke.py
```

Result: **2 tests passed in 7.919s**, exit 0. Harness made isolated source snapshot; built sdist and wheel from sdist; installed wheel in fresh `--no-deps` venv; compared selected dirty-source hashes to sdist and every packaged `src/local_ai_hub` file to wheel; imported SDK/client and read packaged defaults; audit guard recorded `forbidden_events: []`; CPU-only hardware discovery stubbed. Exact receipt: `C:\WINDOWS\Temp\t19-packaged-sdk-iq0fbvq7\receipt.json`, SHA-256 `3D509FE80DFFAC7CE7062D23DE886EB387FBECC63971B4C0E003030C51EEF040`.

- Source snapshot hash: `E894E334A4A3FBD4E10F5D884BB10582D01FE7C8D3D4866B2AD895BC6D500BF8`
- Sdist `local_ai_hub-4.0.0.tar.gz`: `381AEB71D8269DB9782B8EB9F2065BFC7C936223961429683AC4B376B594621D`
- Wheel `local_ai_hub-4.0.0-py3-none-any.whl`: `955554B6DE0E6FA5A217D9343F74ECE616385EE5636AFE20E8F56D20C499D86C`
- Package version: `4.0.0`; default TOML digest matches selected source.
- SDK probe reports schema names `local_ai_artifact`, `local_ai_command`, `local_ai_coord`, `local_ai_rag`, `local_ai_repo`, `local_ai_status`; schema digest `6723EFC297A3C5604D2EB6552B368783B694920D6F5B3298BBBA2065A2168D38`.

This proves candidate source packaging and isolated SDK import. Probe does not replace T20's same-revision live MCP input/output schema, auth, HTTP, outage, restart, or release checks.

## Scoped T19 regressions

Exact command (enumerated all `test_t19_*.py`, excluding delegated clean-profile test and separately run packaged smoke):

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $exclude=@('test_t19_clean_profile_roundtrip.py','test_t19_packaged_sdk_smoke.py'); $tests=Get-ChildItem -LiteralPath tests -Filter 'test_t19_*.py' -File | Where-Object { $_.Name -notin $exclude } | Sort-Object Name | ForEach-Object { $_.FullName }; python -B -m pytest -q -p no:cacheprovider --confcutdir=tests --noconftest --tb=short $tests
```

Result: **69 passed, 1 skipped in 32.97s**, exit 0. Skip: rollback snapshot directory-symlink case, Windows `WinError 1314`; no source failure. `test_t19_clean_profile_roundtrip.py` remains delegated/not rerun (user-reported isolated receipt 1 passed). The protected package smoke above ran separately.

## Open T20 / release gates

This is an unintegrated dirty T19 candidate, not a release. Do not publish these artifacts as approved package. Clean-host Windows/Linux installer/doctor/reinstall/uninstall remain NOT RUN and require one T20 frozen post-integration artifact. T20 must run same-revision MCP schema/HTTP/HubClient behavior, auth/body/feature-negative cases, outages/fallback, restart/concurrency, and full release `verify_completion`. Current candidate smoke is not acceptance for these gates.
