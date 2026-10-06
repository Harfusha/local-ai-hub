# T19 packaged SDK smoke — 2026-10-01 r1

Result: **PASS — bounded current-candidate package capability.** Final harness ran one real packaging test in 10.022 seconds, exit 0, no skips. Approved integrated-root/production package proof: **NOT VERIFIED**. Full T19 and parent T01–T21 release goal remain open.

## Ownership and boundaries

Only new repository paths written, through `apply_patch`:

- `tests/test_t19_packaged_sdk_smoke.py`
- `handoff/T19-packaged-sdk-smoke-20261001-r1.md`

Workspace/source: `C:\Users\Adam\.codex\worktrees\t19-docs-rollout\.local-ai-hub`. Initial Git status contained 97 inherited entries, including other T19 tests/handoffs; neither owned nor edited here. Git base `2b33602adef0d030fea66cdcc04ca742c60b2e32` is context only, **not package input**. Current dirty/untracked source bytes are the input. No source freeze or production snapshot approval was supplied.

Protected T20 source root `C:\Users\Adam\.local-ai-hub` received no source edits, command validation, or Hub/SDK startup. Its existing `.venv\Scripts\python.exe` was borrowed only as the local Python/build-tool interpreter; metadata discovery and this standalone T19 test ran from the T19 worktree, build workers from temporary source trees, installed SDK probe from the fresh temporary venv. No integrated-root package was built or imported by the probe.

Hub explicitly ignored per human instruction: no health/start/autostart, Agent OS task/store, or polling. One existing-chat scoped goal was created only after `get_goal` returned no goal; no duplicate chat/worktree/persistent store. One read-only native subagent reviewed this new test without running validation or writing files; its socket-guard and stale-receipt findings were addressed. No Git writes, commit, publishing, global dependency installation, PATH/config edits, model/API process, network download, or GPU discovery. No `C:\Ostatní\Freq` access.

## Exact runnable command and final output

Working directory: `C:\Users\Adam\.codex\worktrees\t19-docs-rollout\.local-ai-hub`.

```powershell
& 'C:\Users\Adam\.local-ai-hub\.venv\Scripts\python.exe' -I -B tests/test_t19_packaged_sdk_smoke.py
```

```text
test_wheel_from_sdist_runs_sdk_in_fresh_venv (__main__.PackagedSDKSmoke.test_wheel_from_sdist_runs_sdk_in_fresh_venv) ... T19_PACKAGE_RECEIPT=C:\Users\Adam\AppData\Local\Temp\t19-packaged-sdk-rpcgo9ci\receipt.json
ok

----------------------------------------------------------------------
Ran 1 test in 10.022s

OK
```

Exit code 0. One test passed; zero skipped/failed. This does not mean the broad project suite passed: release_check, compileall, selftest, full pytest, daemon/MCP handshake, hardware and release acceptance were deliberately not run during T20's hardware slot.

Optional source selection: `T19_PACKAGE_SOURCE_ROOT` overrides the default T19 worktree. It must identify the selected source directory, including dirty files; the test never exports Git HEAD. A future approved freeze can be selected there, but the receipt conservatively keeps `production_release_approved=false`; owner approval and root integration are separate release evidence.

## Dependency diagnosis and executed package chain

Metadata-only diagnosis preceded build/backend imports. Python 3.13.2 at `C:\Python313\python.exe` had pip 24.3.1 but no setuptools, wheel, build, or pytest. Python 3.12 had pip 25.0.1 but no setuptools, wheel, build, or pytest. Existing managed interpreter had setuptools 84.0.0, wheel 0.48.0, pip 26.2.1, pytest 9.1.1; `build` was unavailable. No download was needed: actual PEP 517 setuptools backend hooks were used directly, without build isolation or dependency resolution.

Loaded requested token-economizer, caveman, TDD, good-test/anti-pattern references, and verification skill. Required `ensure-tools.ps1 -PlanOnly` attempt failed because `C:\Users\Adam\.agents\skills\token-economizer\scripts\ensure-tools.ps1` does not exist. No substitute installer or PATH change. User's explicit Hub bypass and narrow validation scope override the general routing/full-suite guidance.

1. Build a fresh temporary source fixture from existing MANIFEST include/prune rules, `pyproject.toml`, and package source. Copy exact selected bytes; reject links/junction escapes, compiled/runtime trees, files over 8 MiB, snapshots over 128 MiB or 4096 files. Actual selection: 416 files. Compare identities after copying and after the complete smoke to reject source drift.
2. Run `setuptools.build_meta.build_sdist` in that fixture. Hash every selected input against actual sdist members and verify internal `docs/superpowers` exclusion.
3. Extract the actual sdist with tarfile's data filter. Run `setuptools.build_meta.build_wheel` from the extracted sdist, not the original/editable source. Match all 102 package files/resources against selected-source bytes.
4. Create an actual new venv, system-site-packages disabled; bundled ensurepip supplies pip locally. Install the actual hashed wheel using `pip --isolated install --no-index --no-deps --no-cache-dir --disable-pip-version-check`. Child home/config locations are temporary, `PIP_CONFIG_FILE` is the null device, inherited LOCAL_AI/PYTHON/PIP configuration is removed.
5. Execute actual installed SDK import/constructor, package resource read, config merge and schema generation under fresh-venv Python `-I -B`. Verify version 4.0.0 from selected pyproject, selected package module, and installed distribution; defaults bytes match selected source exactly. All imported Hub module `__file__` paths are under temporary venv site-packages; installed package file hash map exactly equals selected package source. Installed `mcp`/`watchdog` dependencies are absent, confirming the `--no-deps` fixture.

Build workers and SDK probe deny socket creation (including UDP), connection/bind/DNS/send operations, subprocess creation and shell execution with Python audit hooks. Hooks also record attempted forbidden operations and require an empty attempt list even if application code catches the error. Every build/install/probe command has a 60-second timeout; pipe draining and bounded process-tree termination handle timeouts. The standard-library venv/ensurepip and pip install steps use local bundled pip and explicit no-index installation.

Only hardware discovery is substituted with a CPU fixture because real `load_config` probes GPUs even when `auto_tune=false`. SDK, selected configuration, packaged defaults, schema generator and installation are real. Schema result is six models-disabled tools: `local_ai_artifact`, `local_ai_command`, `local_ai_coord`, `local_ai_rag`, `local_ai_repo`, `local_ai_status`; object/required-field/action/budget-field checks and JSON roundtrip pass. This is the installed generator's schema smoke, not a live `tools/list` transport or all-profile parity proof. SDK `auto_start=false`; no request methods called, no state directory or user install layout created.

## Provenance and retained artifacts

Full per-file identities, command arguments/cwd/exit codes, toolchain, installed module origins, hashes and results:

[Final receipt](C:/Users/Adam/AppData/Local/Temp/t19-packaged-sdk-rpcgo9ci/receipt.json)

SHA256 identities:

| Artifact | SHA256 |
| --- | --- |
| Final receipt | `12f74e3a9eb8aab9a9161c2b041a1f6195f402512e41ab48e6df5d6fb2fb2bc7` |
| Final test source | `fdaed8791e9021c47b9c56f92a11115f7020f03ed833bfe61dba16cfca77f58f` |
| Selected source map (sorted JSON) | `5f03a1254fc38fe2957910c43d4423de1cf1ca6b68107e696606c37eea6b501f` |
| pyproject.toml | `4e03f365d97fd475a4dff8169725bf0c999631f3f49612e06650baad172899c0` |
| MANIFEST.in | `bcbb4d098a772c2c6bfd57feddcd5ce5daf65da69ee1ac7c9d74f1bcc306e854` |
| Selected client.py / installed client.py | `3444f49e85e475ebb01ed7a8a68c24bee25c1ae8adcd5fc882e864b4f4f75073` |
| Selected generator.py / installed generator.py | `0358a5f3be0815a60592e35fe28509b280a8863b24a6a0a7d9d361e2fb694515` |
| Root defaults, package defaults, installed resource | `d688f8546f616b872b2111c1f137c06964035e75c6da8b2a2dd2f420400a039e` |
| Installed generated schemas (sorted JSON) | `6723efc297a3c5604d2eb6552b368783b694920d6f5b3298bbba2065a2168d38` |
| Actual sdist | `533792d579403bbcec294320f608ccb57f04ec1c2fdf37673eb70e5ef3855351` |
| Actual wheel, built from that sdist | `43e3809658d219c0e88c58e10f10c534524f787aae39849db70bb349a875bdf7` |

[Wheel](C:/Users/Adam/AppData/Local/Temp/t19-packaged-sdk-rpcgo9ci/dist/local_ai_hub-4.0.0-py3-none-any.whl), [sdist](C:/Users/Adam/AppData/Local/Temp/t19-packaged-sdk-rpcgo9ci/dist/local_ai_hub-4.0.0.tar.gz).

Actual SDK origin: `C:\Users\Adam\AppData\Local\Temp\t19-packaged-sdk-rpcgo9ci\venv\Lib\site-packages\local_ai_hub\client.py`. Package/config/generator/hardware and seven other imported Hub module origins are captured in the receipt; none are editable source paths.

All five final command exits were 0: sdist 2.096 s, wheel 1.112 s, venv 2.979 s, install 1.903 s, installed smoke 0.295 s. Full log files remain alongside the receipt: [sdist.log](C:/Users/Adam/AppData/Local/Temp/t19-packaged-sdk-rpcgo9ci/sdist.log), [wheel.log](C:/Users/Adam/AppData/Local/Temp/t19-packaged-sdk-rpcgo9ci/wheel.log), [venv.log](C:/Users/Adam/AppData/Local/Temp/t19-packaged-sdk-rpcgo9ci/venv.log), [install.log](C:/Users/Adam/AppData/Local/Temp/t19-packaged-sdk-rpcgo9ci/install.log), [installed-smoke.log](C:/Users/Adam/AppData/Local/Temp/t19-packaged-sdk-rpcgo9ci/installed-smoke.log). Receipt includes their SHA256 hashes. Wheel build warnings were `warning: build_py: byte-compiling is disabled, skipping.` and `warning: install_lib: byte-compiling is disabled, skipping.` No build failure; bytecode intentionally disabled.

Temporary fixtures, source/export snapshots, dist files, venv and logs were retained, not deleted. They are local temporary artifacts and can be reclaimed externally; key identities/results above remain in this handoff. This is an in-test clean fixture, not a new persistent export system.

## Negative controls and review closure

Before first GREEN, a temporary copy with `local_ai_hub = []` package-data declaration produced a real sdist missing `src/local_ai_hub/defaults.toml`; assertion failed, process exit 1. Production/worktree packaging files were never mutated. The same packaging omission was rechecked with the final harness after review fixes, again exit 1 with `AssertionError: sdist missing selected input: src/local_ai_hub/defaults.toml`.

[Final missing-resource negative-control receipt](C:/Users/Adam/AppData/Local/Temp/t19-package-red-final-flanawix/attempt/receipt.json). Its sdist build genuinely succeeded, then archive validation failed; this is expected failure evidence, not a candidate packaging failure or skipped build. Initial negative-control and earlier GREEN receipts remain in `t19-package-red-xsyxbbbv` and `t19-packaged-sdk-c7bqi_4k` temporary directories; earlier GREEN proves the previous harness, not this final test revision.

Final offline guard negative command, cwd T19:

```powershell
& 'C:\Users\Adam\.local-ai-hub\.venv\Scripts\python.exe' -I -B -c 'import runpy; m=runpy.run_path("tests/test_t19_packaged_sdk_smoke.py"); exec(m["OFFLINE_GUARD"]+"\nimport socket; socket.socket(socket.AF_INET,socket.SOCK_DGRAM)")'
```

Actual exit 1: `AssertionError: packaging smoke forbids socket.__new__`. UDP socket creation was denied before any packet could be sent. Final normal smoke subsequently passed. Independent review found no further material package-byte identity or fresh-venv gap; its two findings were the guard gap and receipt identity changing during an explicit test refinement, both resolved above.

## T20 handoff

Test-only patch ready: integrate only the two new paths listed above through the T20 owner. No wholesale candidate copying into protected root. Run this smoke against the explicitly selected approved release snapshot when available; preserve its receipt/hash identities separately from this candidate proof. Missing local toolchain yields an explicit unittest skip plus `status=skipped` receipt and reason, never an accepted package proof. Build/install/import/assertion failures yield failure plus retained logs/receipt. Root/package approval, full T19 rollout, all-profile/public MCP parity, clean-host acceptance and parent release completion are still the respective owners' work.
