# T19 clean-host readiness — 2026-10-04

**Status: BLOCKED / NOT RUN.** No build, install, network access, service action, or root test performed for this packet.

## Eligible source revision

**None currently identified.** Do not use a dirty checkout as a release source.

- Shared root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`; 451 dirty status entries, therefore not a clean frozen source.
- T19 candidate HEAD: `2b33602adef0d030fea66cdcc04ca742c60b2e32` (detached); 314 dirty entries, including installer, setup, prompts, docs, and tests. Not eligible as a frozen source.
- Latest T20 checkpoint: T08 v4 recorded as **partially integrated, not complete**. T20 has not named a frozen release revision, artifact pair, or T19 clean-host slot. Other owner integration completion has not been established by a final T20 matrix.
- T19 prompt/docs integration is separate evidence only. Root prompt parity selector reported `1 passed in 0.72s`; it does not qualify a release source or prove installation.

## Revision-bound sdist protocol — PREPARED, NOT RUN

1. T20 must name one full immutable source commit and version; provide a clean checkout at that commit. Verify `git rev-parse HEAD` equals the named SHA and `git status --porcelain=v1 --untracked-files=all` is empty. Preserve all existing dirty worktrees.
2. Record source tree object ID (`git rev-parse HEAD^{tree}`). Export the revision with `git archive --format=tar --output <external-source-archive> <full-sha>` and record SHA-256 of that archive. Keep build output outside the source checkout.
3. Use the T20-approved builder and command to create only the sdist, with outbound access restricted to the configured Python package index. Record stdout/stderr, exit code, artifact path, and SHA-256. Retrieve the artifact by its pinned path/digest; independently compare its SHA before extraction.
4. Required T20 revision-bound sdist receipt fields: source revision full SHA; version; Git tree object ID; source archive SHA-256; sdist SHA-256; exact artifact path; builder identity/version; exact build command; result/exit code; stdout/stderr evidence reference; build timestamp; receipt owner.

No artifact or receipt exists for an eligible integrated revision yet. Historical v7 artifacts are stale and must not be reused.

## Disposable host and ACL — REQUIRED

- Snapshot VM; new local account; no synced profile, vault, personal configuration, or durable Hub state.
- Exactly one preinstalled Python 3.11+ interpreter. Stop if bootstrap would install Python.
- Unique non-existing scratch paths for source, install, and state. Preserve scratch and receipts; no recursive cleanup.
- Network allowlist: configured Python package index only. Block external Hub, Ollama, model registries, and service registration. Skip model pulls and optional tools/runtimes.
- `--skip-service` still runs setup's local `hubctl restart` path. Capture it; stop if it reaches external providers. Persistent service lifecycle requires separate T20 slot/receipt.

## Acceptance stages — NOT RUN

| Stage | Status | Evidence required |
|---|---|---|
| sdist identity and extraction | NOT RUN | T20 receipt SHA match; source/version/tree hashes; extraction path |
| clean install | NOT RUN | exact interpreter, command, flags, exit/stdout/stderr, installed version, config/state paths |
| same-version reinstall | NOT RUN | repeat install receipt; config/state continuity |
| uninstall | NOT RUN | exit/output; Hub-managed files/config entries removed; user data preserved |
| rollback | NOT RUN | matched code/config/durable-state snapshot; restore receipt; service stopped/reconciled separately |
| cross-version update | BLOCKED | T20-approved baseline/target artifact pair and state/config preservation assertions |
| persistent service restart / MCP | BLOCKED | separate T20 slot and daemon/adapter identity receipt |

Stop on any source SHA, tree digest, sdist hash, or version mismatch; dirty source; existing scratch path; unexpected Python installation; outbound request outside package index; model pull/tool/runtime install; unexpected service action; failed command; or missing receipt field. Preserve evidence and state; do not automatically retry.

## Existing candidate-only evidence

- `handoff/T19-candidate-installer-suite-receipt-20261004.json`: candidate selector `20 passed, 1 skipped in 3.03s`; skipped only because Windows denied directory symlink creation (`WinError 1314`). This is not host install acceptance.
- `handoff/T19-prompt-profile-parity-root-receipt-20261004.json`: root prompt parity selector reported `1 passed in 0.72s`; this is not release acceptance.

**Next gate:** T20 must finish owner integrations, pin a clean frozen source revision and sdist receipt, then assign T19 one explicit serial disposable-host slot. Until then all host/build/install/update stages remain NOT RUN.