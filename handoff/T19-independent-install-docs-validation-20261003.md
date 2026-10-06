# T19 independent install/docs validation — 2026-10-03

- Candidate: `C:\Users\Adam\.codex\worktrees\t19-docs-rollout\.local-ai-hub`, HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`.
- Scope: portable TOML install copy, standalone optional CodeGraphContext docs/uninstall preservation, verified install flow, install/update prompt parity contracts.
- Validation: focused pytest selector covering eight T19 test modules — **48 passed in 2.21s**.
- Portable config evidence: dry-copy fixture checks config byte parity, supported portable keys, defaults consistency, package version/manifest data, feature prompts, and profile/model docs.
- CodeGraph evidence: tests assert no Hub runtime/config/telemetry integration, standalone `codegraphcontext[gcf]==0.6.13` docs, uninstall preservation, and no Ollama prompt claim.
- Limits: tests use fixtures/mocks; no real install/update or clean-host cycle ran. This is source/test evidence only.
- Dependencies: T03/T04 schema/transport parity and T13 lifecycle/auth-root work remain candidate gaps. Prompts label those gaps. No release PASS claimed.
- Side effects: only this receipt was written in the T19 candidate; test bytecode/cache disabled. Root and host install/config were not written.
