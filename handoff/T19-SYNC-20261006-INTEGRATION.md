# T19 committed synchronization — 2026-10-06

Scope: C:/Users/Adam/.codex/worktrees/t19-docs-rollout/.local-ai-hub only.
Branch: codex/sync-t19-docs-rollout-20261006.
Pinned master: fb32354f8bf632e560e052e9b12c73f64b00cba4 (read once; includes T13).
Original HEAD: 974fed0d66f19421b3ceec100565316f97213d79.
Original checkpoint: refs/checkpoints/t19-docs-rollout-original-20261006.
All ordinary untracked work checkpoint: 224bc94e808605161a75dfdd007ca03fe068786f.
Work checkpoint: refs/checkpoints/t19-docs-rollout-work-20261006.
Pinned master checkpoint: refs/checkpoints/t19-docs-rollout-master-20261006.

## Preservation and merge decisions

Original tracked dirty work was already committed in 974fed0d. At this run's entry no tracked dirty changes remained; 276 ordinary untracked files were committed before merging. All 250 original handoff files, ordinary code, tests, docs and candidate instructions remain recoverable at the work checkpoint. Existing ignored artifacts were neither removed nor committed. Runtime validation state stays ignored under state/t19-sync-validation.

Merged the pinned SHA with --no-commit --no-ff, then reviewed conflict hunks. No stash, drop, hard reset, clean, whole-file ours/theirs checkout, push, root checkout writes, new worktree or chat. Checkpoint refs were added; master was never updated by this task. The user supplied an already-terminal Hub failure and explicitly authorized native fallback; no Hub retry or polling occurred.

All runtime src/ files equal pinned master. Its transport cancellation, request identity, pre-send failure classification, operational modes, routing floors, and CodeGraph removal are preserved. No runtime feature was added. T14 retains /api/context/pack ownership; old T19/Agent 2/T21 candidate owner gates were removed from current inventory metadata.

Canonical INSTALL/UPDATE prompts now share source-grounded routing, lifecycle, client identity, transport, hint, and synchronization statements. Prior candidate prompt text remains in checkpoint/history rather than becoming current instructions. Security prose distinguishes client preflight from server authorization. Both historical adaptive-plan notices remain.

Surface inventory preserves T19 urllib/manifest extraction and master schema, conditional-action, CLI, operation-ownership, and behavior-link fixes. The original OPTIONS browser/vision metadata hunks were retained after a targeted test caught their omission. API_COVERAGE was regenerated from actual merged AST evidence: 660 rows, no drift. Coverage metadata is not runtime acceptance.

## Actual checks and bounded side effects

Validation owner: this task, assigned worktree only. Explicit LOCAL_AI_CONFIG points to handoff/T19-SYNC-20261006-validation.toml; auto-start, Ollama, llama.cpp and preprocessing disabled. Python used -B; pytest cache disabled. TEMP/TMP and pytest basetemp point under ignored worktree state. No installs, model pulls, live Hub calls, service changes or full release suite.

- Targeted transport/router/mode/T19-doc/CodeGraph/preprocessing selection: 108 passed, 4 failed, 9.25 seconds.
- Targeted inventory selection: 14 passed, 1 failed, 696 deselected, 35.78 seconds. Failure was missing OPTIONS /api/browser/ registry metadata.
- After restoring the reviewed OPTIONS hunks, that exact regression selector passed: 1 passed, 12.97 seconds.
- Inventory generation: success=true, 660 rows, drift=[].
- Earlier inventory --check: success=true, coverage_matches=true, 658 rows, drift=[] before the OPTIONS restoration. Final 660-row check recorded separately in verification receipt.
- AST syntax: all six active Python files differing from pinned master parsed successfully.
- git diff --check against pinned master for AGENTS/docs/src/tests/tools: passed.
- src/ diff against pinned master: empty. Git unmerged index: empty.
- A broad staged whitespace check inadvertently included pre-existing master .handoff overlays and reported their whitespace. No archived payloads were reformatted; the scoped check above passed.

## Outstanding behavior and documentation contradictions

1. tests/test_t19_current_prompt_adoption.py::test_current_scoped_path_controls fails for both prompts: it still requires search-only hints and no hint-specific HubClient.post keyword arguments. Current source supports hints on search and command plus tenant/cancel_event. Preserve source safety; update historical assertions in a separately scoped follow-up.
2. tests/test_t19_prompt_profile_parity.py::test_agents_profile_routes_match_hardware expects the old literal "Model routing is profile-aware" AGENTS paragraph. Master intentionally uses on-demand routing guidance and docs/MODEL_CAPABILITIES.md.
3. tests/test_t19_codegraph_removal.py::test_codegraph_is_absent_from_hub_runtime_configuration_and_telemetry rejects the protective .codegraphcontext exclude in repo_tools.py default_ignore_dirs. That exclude MUST remain: it protects external standalone data and does not restore a CodeGraph backend. Replace the stale substring prohibition with a runtime-capability/configuration check in a separately scoped follow-up. The user reports root restoration at 6d32a3c5 with RED 1 fail / GREEN 3 pass; this is user-supplied external evidence, not a check run here. No moving-master chase: repo_tools.py remains byte-identical to the original pinned master and its exclude is present.
4. Gemini preprocessing implementation was not found in the pinned source: preprocess.py still uses deterministic/background Ollama synthesis; Gemini appears in agent manifests. No provider implementation was removed or invented. The requested Gemini preservation cannot be certified beyond preserving actual pinned src/ bytes.
5. HTTP _tenant still accepts caller tenant labels outside token-bound browser routes. Client HMAC/root preflight does not establish HTTP-enforced root authorization. operational_mode.py still permits safe job actions in maintenance; complete maintenance isolation remains unaccepted.
6. Packaged response budget defaults to 6400 while generated guarded-context prose mentions 3200. Both prompts identify configuration/envelope as authoritative; generator behavior was not redesigned.
7. FEATURE_AUDIT_V4 graph claims and the older adaptive design specification contain obsolete CodeGraph prose. Historical plans, owner comparison notes, clean-host receipts and release acceptance matrices do not prove this integration.
8. tests/test_preprocess_operational_mode.py contains shadowed duplicate test definitions with conflicting False/None expectations; the later definition runs. Existing source/tests preserved.
9. The merged inventory's legacy prompt-manifest tests and the remaining installer/SDK/source suites were not fully run. Clean-host Windows/Linux, packaged SDK, live MCP, service lifecycle, model quality and release readiness remain NOT VERIFIED.

The final commit is the committed merge with these known incomplete tests/contracts. Exact changed paths, hunk choices and final verification are stored in adjacent JSON records. Resolve HEAD on the branch for the final merge SHA; no further moving-master synchronization is intended.
