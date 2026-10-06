# T19 prompt and clean-host acceptance handoff — 2026-10-02

## Scope and evidence

Read-only comparison of install/update prompts, installation guide, and the two T19 clean-host procedures against root `C:\Users\Adam\.local-ai-hub` at HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`. No root edits, tests, package builds, installs, runtime checks, or clean-host runs were made. Runtime and test execution remain T20-owned.

Root working-tree SHA-256:

- `docs/INSTALL_PROMPT.md`: `7e5da693aebdfe0bd2f025aa6176e75284701eb4b92fedf636e64a88d7c6573b`
- `docs/UPDATE_PROMPT.md`: `50ce34f25602653652235a8267e6ea2d85953bb6541c2ec66de7c40d22a31c97`
- `docs/INSTALLATION.md`: `3802b4f60012f8e5c0eca12673f0d8273fc93e6edeafa03fd6af838b7dbf463d`
- `docs/T19_RELEASE_VALIDATION_RUNBOOK.md`: `53ec31aa3f646308c21c0f5101123880b583513597389f5b32e8bc5541972d63`
- `docs/T19_CLEAN_HOST_INSTALLER_CYCLE.md`: `a037dae1d9942c76f15b7f0801f647e9fc5879b74b9e41d206d308432a0ad49a`

Line-ending-normalized comparison: update prompt, installation guide, release runbook, and clean-host cycle match root. Install prompt differs on one policy line: the T19 candidate says semantic delegation is optional/on-demand; integrated root says delegation is the default for useful bounded independent work. The current user-level policy includes both the general delegation default and on-demand semantic delegation. The candidate parity test explicitly expects the semantic on-demand wording. Keep the candidate unchanged pending T20 policy-owner reconciliation; do not call either side stale based on this line alone. Candidate source SHA is `7bc6af155901d203680e9df6df88565648431a2f85928aab96f686d3177fddb3`; root SHA is above.

## Install prompt checklist

- Locate `~/.local-ai-hub`; clone only if missing or without `tools/setup.py`.
- Run the platform bootstrap with profile `auto`; leave model pulls and Ollama opt-in. Standard install keeps Token Economy and companion skills enabled.
- Verify service health and version, start the service only if needed, then run doctor. Check selected local backend/hardware against configuration; don't infer one provider from another.
- Find active repository agent-instruction files; create `AGENTS.md` only if none exists; update both marked policy blocks without clobbering surrounding instructions.
- If applicable, register repository/workspace MCP, run initial repository preprocessing/handshake, and report Hub/service/backend/tool/policy results with unavailable optional components explicit.
- For rollback, first stop Hub and back up install, config, and complete configured state together, including SQLite WAL/SHM; restore only declared roots.

## Update prompt checklist

- Locate install and inspect `git status --short`. If dirty, preserve changes and stop for operator review.
- Fetch canonical `origin/master`; switch to existing local `master` and `pull --ff-only`. Create a tracking branch only if local master is absent; do not overwrite branches.
- Before update/rollback, stop service and back up install, config, and complete configured state including WAL/SHM.
- Run platform installer with `auto` profile and current provider settings; don't silently switch provider or pull vision models without explicit enablement.
- Restart service; confirm health returns `status: ok` with updated version; run doctor and hardware/backend checks.
- Refresh both marked policy blocks from generated policy files, preserve the token-economizer trigger and tool safety boundaries, then rerun repository preprocessing.
- Report revision/version, backup and update commands, service/doctor evidence, changed instruction files, preprocessing result, and any unresolved optional backend. Keep schema-gated behavior and unavailable verification explicit.

## T20 clean-host release checklist

**Current state: NOT RUN.** The v7 package and receipts are historical. Do not schedule work from a prior slot release. First obtain a T20 assignment naming the frozen integrated commit, artifact pair, allowed OS/Python combinations, and serial slot coverage.

1. **Freeze and build.** Use a clean checkout of the assigned revision with no pre-existing `build/` or `dist/`; record `HEAD` and status. Under the assigned slot, run scoped `test_t19_*.py`, the inventory check after T01 releases its source contract, then `release_check --post-test`. Build sdist and wheel to a fresh external artifact directory. Record exact commands, exit codes, output/log paths, revision, and both SHA-256 hashes. Stop on any failed step; don't reuse v7 receipts.
2. **Package install matrix.** The runbook enumerates Windows 10/11 and Linux, each with Python 3.11, 3.12, 3.13, and 3.14: eight OS/Python combinations. For every authorized combination, install the sdist with the six documented extras in a fresh isolated venv and install the wheel in a second fresh venv. Verify artifact hashes, Python/pip versions, `pip check`, CLI help, and doctor JSON from the sdist. Keep Hub service, model, and device availability outside this package acceptance claim. Each artifact/host receipt binds to the same frozen revision and pair.
3. **Installer lifecycle.** Separately run the documented disposable-VM install/reinstall/uninstall cycle. Current procedure scopes one OS/Python combination per fresh VM/slot and explicitly says one passing cycle covers only that combination. It checks selected Python availability, package-index-only network access, unique scratch paths, skipped pulls/tools/service, successful install and CLI help, unchanged config after reinstall, install-tree removal after uninstall, and survival of external state marker. Record exact commands/exit codes, artifact hash, pre/post config hashes, and receipts. Ask T20 whether the lifecycle gate needs all eight matrix cells or one designated Python per OS; its closure wording currently says Windows and Linux receipts without pinning Python coverage.
4. **Gate closure.** A package/lifecycle pass is not overall release acceptance. T07 replay/idempotency, T08 rollback/recovery, current owner receipts on the same frozen revision/artifacts, T20 integration/review, and Windows/Linux clean-host receipts are separate gates. Refresh historical owner blockers from current T20/owner receipts before calling them current.

## Handoff to T20

- No tests or runtime acceptance are claimed. T20 must schedule and own the frozen-source pack and each assigned clean-host combination.
- Root docs already contain both runbooks and match candidate bytes after newline normalization. Do not reapply the T19 patches.
- Refresh the T19 candidate install prompt from the integrated root policy line if the candidate will remain a source for future handoff; integrated root is already correct.
- Clarify whether lifecycle acceptance requires all eight OS/Python cells or one Python version for each OS, and record that choice in the frozen acceptance matrix before scheduling.
