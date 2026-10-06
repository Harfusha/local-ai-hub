# T04 lock-recovery committed checkout synchronization

Scope: existing `t04-lock-recovery/.local-ai-hub` only; native fallback explicitly
authorized after terminal Hub failure. No Hub retries, installs, push or root edits.

- Branch: `codex/sync-t04-lock-recovery-20261006`.
- Original HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`.
- Pinned original ref: `checkpoint/t04-lock-recovery-original-20261006`.
- Pinned dirty source ref: `checkpoint/t04-lock-recovery-dirty-20261006` =
  `b81b75a784f7bed45745bb709ba15d4bc018911b`.
- Checkpoint commits all original tracked dirt and untracked startup test.
- Startup/client conflicting hunks reviewed against newer master behavior.
  Master already contains the intended recovery changes plus newer PID creation
  identity, OS-held lock, cancellation and bounded retry-cooldown safety fixes.
- Removed duplicate import and obsolete automatic-merge `ready` assignment.
  Final executable source/tests match master; original variants remain committed
  in checkpoint ancestry, not discarded.
- Handoff Markdown retained and committed as historical documentation.
  Other original handoff overlay source, patches and pytest configuration are
  committed in the final preservation commit. No runtime state/caches staged.
- Preprocessing/Gemini integration, CodeGraph removal and T14 context-pack route
  inherited unchanged from master.
- No duplicate test execution: T04 source/tests match master; companion
  integration checkout exercised shared startup/transport implementation.
  This checkout has no independent runtime acceptance receipt.
  No full release, live-daemon, deployment or model-quality acceptance claimed.

Companion targeted runs: initial 113 passed / 5 failed / 1 skipped; follow-up
98 passed / 6 failed. Four old assertions corrected there; remaining MCP schema,
fixture, T14 expectation and removed-sidecar tests remain explicitly unfinished.
CodeGraph lexical absence assertion also disagrees with master ignore-directory
string. Committed synchronization does not claim full acceptance.

Latest master merged at handoff; original and dirty checkpoint refs pinned.
Final HEAD: `git rev-parse HEAD`. Changes versus master include original handoff
patches/overlay source/tests, historical documentation and raw preservation data.

Master start pinned at `fbc965f568105e1a8d3dc03ae4c9da5531a9617e`;
already synchronized through `f8ba97fe9eafa38810dbbbc3c4184800da7bafcd`.
Later moving-head integration belongs to the orchestrator.

`handoff/t04-preservation-lock-recovery-20261006-v2/manifest.json` lists 11 raw
snapshot entries with SHA-256 and all 339 excluded paths. Matching
`original-bytes.zip` verified entry-by-entry before Git staging; exact remaining
original handoff bytes remain recoverable despite Git EOL normalization.
Earlier raw archive/manifest also retained. Pre-merge source checkpoint is a
Git tree; original mixed EOL bytes for already-normalized source are unverified.
Excluded, preserved on disk: `.serena/` generated backend state/local config,
source/tests/tools `__pycache__/`, overlay generated cache files.
Exact excluded paths are enumerated in the manifest.
Final raw ref: `checkpoint/t04-lock-recovery-preservation-20261006`.
