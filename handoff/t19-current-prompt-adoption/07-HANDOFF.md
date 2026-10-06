# T19 current-prompt adoption: bounded handoff

Status: own docs slice VERIFIED. Whole T19, runtime, GPU and release acceptance NOT VERIFIED. Ownership of both prompts returns to orchestrator at this handoff.

Workspace: `C:\Users\Adam\.codex\worktrees\t19-docs-rollout\.local-ai-hub`.
Root `C:\Users\Adam\.local-ai-hub` read only: explicit source/doc slices and patch applycheck from T19 cwd. No commands used root as working directory; no root writes. User prohibition superseded Hub/install/build routes. No Hub/GPU activity, install, build, chat/worktree creation, Git writes or commits.

## Exact worker changes

- `docs/INSTALL_PROMPT.md`
- `docs/UPDATE_PROMPT.md`
- NEW `tests/test_t19_current_prompt_adoption.py`
- NEW immutable handoff files listed in `08-verification-manifest.json`; all beneath `handoff/t19-current-prompt-adoption/`.

Pre-existing dirty work was not rolled back. The worker-only patch identifies this slice separately from earlier edits.

| Path | Pre SHA256 | Post SHA256 |
| --- | --- | --- |
| docs/INSTALL_PROMPT.md | 6EC6B55A08EEE0E552346DB6526BBCBA08D887CDC44145A1432ABB2652854AF8 | 1D6021FDE9EB66411F274607B517C6F498B51C1D9565B5AAC2187BDC16FB6A3D |
| docs/UPDATE_PROMPT.md | 4B40839C25891B00A704A1178D20C2343D41FB0F0F08422D39DE186807AB3D3C | 3B0513C3BFF44EF95AD4EB3908D3C95F7152E3A45FFCDDFC74EE81532BC5995D |
| tests/test_t19_current_prompt_adoption.py | ABSENT | 4DC9A34231395D45884FDE62B932F6304EEACBC675893A79010976F12324B78E |

Protected main-owned `tests/test_t19_packaged_sdk_smoke.py` unchanged:
`CF0889E223467D5606161270FF9831005971E4F1BFFF315D1201E50BD9F46144`.

## Verification

Exact cwd: existing T19 workspace above. Command:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -B -m pytest -q -p no:cacheprovider --confcutdir=tests --noconftest tests/test_t19_current_prompt_adoption.py --tb=short
```

Actual sequence: initial RED `4 failed in 0.20s`; expanded RED `6 failed, 5 passed in 0.15s`; final GREEN `11 passed in 0.07s`, exit 0. No source imports, server, dependency install, bytecode or pytest cache. These tests assert docs contracts and parity, not runtime behavior.

`git diff --check -- docs/INSTALL_PROMPT.md docs/UPDATE_PROMPT.md`: exit 0. Git's existing LF/CRLF notices remain informational.

Source origins, exact assertions and current-source hashes: `05-source-review.json`. Current root contains project/mode modules absent in T19. Current path controls differ from inherited T19 docs: command hints and adaptive pack controls are supported by current root HTTP/client adapters. Installed public MCP schema remains authoritative; no claim inferred from internal adapters.

Memory use IDs are selected context elements; non-use IDs are limited diagnostics, not an exhaustive adoption receipt. Root selection filters normal sensitivity, expiry, scope and status before its limit. Cross-worktree Agent OS memory sharing remains HOLD; only scoped path hints share the namespace. No model-obedience or physical GPU claim.

## Root-current narrow patch

`04-root-current-narrow.patch` modifies exactly the two docs and adds the new candidate test. It appends only the source-reviewed common contract and corrects the install prompt's context-first guidance. It does not copy the entire dirty T19 doc diff or unrelated rollout content.

SHA256:
`C4F762C533C63FA0D29A563836BF2F7C0BB4F276FA3D4CC471F6050B668D0A8D`.

Read-only applycheck, run from T19 cwd:

```powershell
git apply --check --unsafe-paths --directory=C:/Users/Adam/.local-ai-hub handoff/t19-current-prompt-adoption/04-root-current-narrow.patch
```

Actual result: no apply errors; exec exit 0. `git apply --numstat`: install +42/-1, update +41/-0, candidate test +110/-0. Patch not applied. Root target test absent.

Root doc hashes before and after applycheck unchanged:

- INSTALL: `1B5E57631929A3CA1FDDEF87DB3A3DCE0E9CCE1A61E485B96FABE0AB8CFC71C5`
- UPDATE: `692301661A67C0FEF78A0CEAAD90F87665ADC1EFC88BCE934F1D2366355D2BCF`

Root docs already differed from T19 preimages. Patch targets the recorded root-current preimages; do not overwrite on later drift. Recheck exact root hashes before applying. Root mutation belongs to orchestrator.

`06-worker-only.patch` preserves the exact worker delta against dirty T19 preimages. Its context-free single-line hunk requires `--unidiff-zero`: initial reverse-check without that flag failed at install line 157, no mutation; `git apply --reverse --check --unidiff-zero handoff/t19-current-prompt-adoption/06-worker-only.patch` then passed, explicit exit 0. No artifact rewritten.

## Remaining main-owned gates

Legacy `test_t19_project_config_prompts.py` expects unintegrated configuration. `test_t19_parity_contract.py` expects command hint stripping/no pack hints and generator text parity. These inspected assertions are stale against current root source. Neither edited nor run. Generator, existing tests, full release gates, public MCP/schema integration and runtime owner/tenant/revision/memory checks remain main-owned.

Native read-only subagent was closed without a result; no subagent edits integrated. Main completed reclaimed source review. Goal completion concerns only this slice.
