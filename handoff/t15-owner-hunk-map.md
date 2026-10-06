# T15 owner and hunk provenance map

Status: candidate is uncommitted and not apply-ready. This map records source ownership boundaries; it does not authorize combining or applying another task's patch. T06 confirms `commands.py` and caller/write-set integration ownership. Its test selectors and separate-worktree receipt are recorded below; T15/root integration remains unverified.

## Source state

| State | Git revision | `src/local_ai_hub/commands.py` SHA-256 |
|---|---|---|
| Baseline | `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11` (archive comparison HEAD `a77562e3210a175765eba914baa753f1b6a07c67`) | `5e3fd81c4ab55633a165237ae5c828ca2b73ace353da403db67c98c65128e1d3` |
| T15 candidate | same source revision, detached HEAD, dirty worktree | `12dde723016cc9d278b03cf0831898af449a766eaa2159f0471cc4fa7457f3b1` |

T21 owner worktree was separately reported at `C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub`, branch `codex/t21-project-config`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`; this is a different checkout and is not merged into the candidate. Owner-reported SHA-256: `services.py` `dec5feac889bb03efd58f84e87127e4fb32c9904060442cd7fc2b26f385ca526`; `tests/test_project_config_service_integration.py` `5894299bdccf87da4927e356ee89b18d490863e861d785dc2ffd714a28c2fc35`.

## Exact candidate path inventory

These are the current T15 worktree paths from `git status --short`. The baseline is HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`; every `M` is a dirty candidate file and every `??` is untracked in this worktree.

| Candidate path | Candidate vs inherited provenance |
|---|---|
| `src/local_ai_hub/commands.py` | Mixed. T15 cache key/policy, bypass, single-flight and capture hunks; T15 capture hunk now uses queue-stop signaling instead of 50 ms dispatcher polling. T06 process-group/recovery/cleanup ownership remains separate and unresolved. |
| `src/local_ai_hub/services.py` | Mixed. Candidate `affected_tests` dependency-graph and `command(run_affected)` fail-closed additions are T15. Candidate also has a repo-search-area hunk whose source is not byte-matched to the separate T21 worktree. |
| `tests/test_project_config_service_integration.py` | T15 adds three `run_affected` uncertainty/dependency-graph regression tests at the current +170 hunk. T21's separate worktree reports 11 repo-search tests; they are not the current candidate hunk. |
| `tests/test_command_cache_singleflight_contract.py` | T15 new regression coverage. |
| `tests/test_command_concurrency_contract.py` | Mixed provenance: T15 cache/single-flight, slow-consumer, and dispatcher-stop tests; process-group cases await T06 owner confirmation. |
| `tests/test_project_command_broker.py` | T15 new project-command broker coverage. |
| `tests/test_benchmark_command_broker.py` | T15 adds positive/invalid preflight latency fixtures and a disposable synthetic-repository fixture contract test. Tests are unrun pending T20/T02 slot. |
| `tools/benchmark_command_broker.py` | T15-owned schema v3; reports positive/invalid preflight p50/p95/p99, throughput, fixed fixture hashes; not run. |
| `tools/prepare_command_broker_fixtures.py` | T15-owned generator for clean 100/10,000/100,000-file disposable benchmark worktrees. Requires exact source pin, clean prefixed worktree, commits only `.t15-benchmark-fixture/`; not run. |
| `docs/PROJECT_CONFIGURATION.md` | Inherited/mixed T21/T04/T09 documentation changes; exact hunk owner split not yet evidenced. |
| `src/local_ai_hub/project_config.py` | Inherited/mixed T21/T04/T09 source changes; exact hunk owner split not yet evidenced. |
| `tests/test_project_config.py` | Inherited/mixed T21/T04/T09 config tests; exact hunk owner split not yet evidenced. |
| `tests/test_project_path_hints.py` | Inherited/mixed T21/T04/T09 path-hint tests; exact hunk owner split not yet evidenced. |

Current `handoff/` inventory (all untracked at the candidate root): `t15-acceptance-evidence.json`, `t15-acceptance.manifest.json`, `t15-acceptance.patch`, `t15-command-broker-baseline.json`, `t15-command-broker-candidate.json`, `t15-command-broker-benchmark-runbook.md`, `t15-command-receipt-opt-out-design.md`, `t15-process-group-recovery-approval.md`, `t15-execute-compat-followup.manifest.json`, `t15-execute-compat-followup.patch`, `t15-owner-hunk-map.md`, `t15-project-command-alias.manifest.json`, `t15-project-command-alias.patch`, `t15-stream-preflight.patch`, `t21-command-consumer.manifest.json`, `t21-command-consumer.patch`. T15 patch files are historical receipts, not a complete current patch; T21 consumer patch is zero bytes. No source patch was applied from either owner worktree.

The separate T21 worktree has 23 dirty paths; it is not part of the T15 candidate inventory. Its owner handoff SHA-256 is `7e88db25ced0942e4739578bfd4aeae86329253d28b9ee0c2ee21892869fa656`. T21 confirms its `services.py` changes are only `LocalAIServices.repo_search`; T21 manifest says the T06-released command-consumer seam already existed at base HEAD and its task made no consumer patch. Keep those facts separate from T15's candidate additions in `affected_tests`/`command(run_affected)`.

T21's separate dirty-path inventory, for path-level overlap review:

- Shared candidate paths with mixed provenance: `docs/PROJECT_CONFIGURATION.md`, `src/local_ai_hub/project_config.py`, `src/local_ai_hub/services.py`, `tests/test_project_config.py`, `tests/test_project_config_service_integration.py`, `tests/test_project_path_hints.py`.
- T21 paths absent from the T15 candidate status: `docs/superpowers/specs/2026-09-25-t21-adapter-handoff.md`, `src/local_ai_hub/client.py`, `src/local_ai_hub/defaults.toml`, `src/local_ai_hub/http_server.py`, `src/local_ai_hub/mcp_server.py`, `src/local_ai_hub/preprocess.py`, `src/local_ai_hub/rag.py`, `src/local_ai_hub/repo_tools.py`, `src/local_ai_hub/project_policy_adapter.py`, `src/local_ai_hub/verification_rules.py`, `tests/test_client_transport.py`, `tests/test_client_path_hints.py`, `tests/test_mcp_repo_path_hints.py`, `tests/test_t11_rag_policy_consumer_rebased.py`, `tests/test_t21_project_config_preprocess.py`, `tests/test_verification_rules.py`, `tests/test_sse_events_stream.py`.

This is a path comparison only. Shared filenames do not imply shared hunks; the T15 candidate and T21 owner worktree have different file hashes and diff locations. No T21 file was copied into the T15 worktree.

Current candidate source and handoff artifact hashes:

| Path | SHA-256 |
|---|---|
| `src/local_ai_hub/services.py` | `7394f38919b5f3b421110c6cb88e841d386cc8b6c848c410b501549ab4029add` |
| `src/local_ai_hub/project_config.py` | `eec7e2920ed905e902d3699a5259d19e23ef9d4b7f17a285e160e97f63ec4686` |
| `docs/PROJECT_CONFIGURATION.md` | `fb603d808bdf960a755055318209024df31292ffc516e23b14722c77fc85b7dd` |
| `tests/test_command_cache_singleflight_contract.py` | `9ed6fb58426b4665e6aa25b5ed8a348dddb24b080dd0d7823d8d52ba2a71209d` |
| `tests/test_command_concurrency_contract.py` | `318630b81f53650877d96063ac0181985f668ce560edce660637f13cec67d294` |
| `tests/test_benchmark_command_broker.py` | `8a3f2d0358b784a398c0bbd8257af9b0dbfb290f65a840ad13b87f75c19ce35c` |
| `handoff/t15-command-broker-benchmark-runbook.md` | `23c46071974642473e0d440cae4fba594478370705f6319bcc230daf0ba7326f` |
| `handoff/t15-process-group-recovery-approval.md` | 17321eca9a6e5481959805888228bce572fba3c8cf93a74ef9831e405faccfa0 |
| `handoff/t15-command-receipt-opt-out-design.md` | `bbed517a776ec35280f4ed8017857c683629a9b87168d615c5787681d2f6f007` |
| `tests/test_project_command_broker.py` | `c59054823d3b6b6189463c870e707b827ce4c2872c4e1758505095f5832c818c` |
| `tests/test_project_config.py` | `7d66e01b9bd24fd66b31ba063deabb6356161952d67732fba60f0a3895eebf92` |
| `tests/test_project_config_service_integration.py` | `6af5dc8ac6d575ad4600c7bc9ca6ca01e8a5e039cc52359336d6e19c7a5a1c42` |
| `tests/test_project_path_hints.py` | `2dba6145040eb2c20ff74788c88a66bf5a4bd4f6f210e292a2032b925df20dab` |
| `tools/benchmark_command_broker.py` | `8aef9b315b44b1a15bad0a52b79213f2f4a319e6bcd84dda240778f2c32930ab` |
| `handoff/t15-acceptance.patch` (historical; not current/apply-ready) | `8408ca60b348676ca2887854c2e77c04fe707f77b537cc4f7cae5054bd44afa3` |

Benchmark reports:

| Artifact | SHA-256 |
|---|---|
| `handoff/t15-command-broker-baseline.json` | `fc2a815971cb2b8f71c9e735eeb3bfa83441a5624f1defe4e780e0df5e0c3ca3` |
| `handoff/t15-command-broker-candidate.json` | `b03f83b769b90748bcab89879313b31befa1f837a175e4209f9f54f037d92655` |

The historical `handoff/t21-command-consumer.patch` is zero bytes and is not a usable patch.

## Ownership boundaries

| Path / current candidate hunk | Owner | Provenance / disposition |
|---|---|---|
| `commands.py`: `CommandBroker._key`, `_attempt_key`, cache policy identity, cache bypass, suppression and single-flight result publication; diff hunks around new lines 2417–2474, 2526–2764, 3269 onward | T15 | Candidate behavior and regression coverage in the three T15 command tests. Hunk ranges are current-worktree coordinates and can shift if the file changes. |
| `commands.py`: `_RecoveredDaemonProcess` (candidate line 101), `_process_group_alive` (144), `_terminate_process_group` (164), `_stop_daemon_tree` (693), `CommandBroker.daemon_status` (4478), `CommandBroker.stop_daemon` (4567); process-group registry/recovery and daemon cleanup hunks around new lines 104–209, 1714–1859, 2956–3221, plus timeout/rollback-adjacent hunks around 3877–3885 and 4381 | T06-owned; quarantine all listed candidate hunks | User-approved contract: persist `process_group_id`; on restart accept a dead leader only when its group is independently verified alive; otherwise reject recovery, including indeterminate liveness. See `handoff/t15-process-group-recovery-approval.md`. T06 owns implementation and platform-specific verification; no T15 source edit. Exclude these candidate hunks from any T15-only patch. |
| `tests/test_command_concurrency_contract.py`: cache/single-flight cases | T15 | Candidate test file SHA above; process-group-specific case ownership remains pending with T06. |
| `services.py`: `LocalAIServices.affected_tests` uncertainty/dependency-graph selection (new line ~3123); `LocalAIServices.command` `run_affected` fail-closed fallback (new line ~3263); tests `test_run_affected_expands_uncertain_selection_to_complete_test_matrix`, `test_run_affected_fails_closed_when_uncertain_and_test_matrix_missing`, `test_run_affected_compares_selected_tests_with_complete_dependency_graph` | T15 | Exact current integration-test hunk begins at new line 170; these three tests are T15 additions. Do not attribute this seam to T21. |
| `services.py`: `LocalAIServices.repo_search` / `search_paths` area (candidate diff hunk around new line 5531) | T21 owner-reported symbol boundary; candidate provenance not byte-matched | T21 owner confirms its separate worktree diff is confined to `LocalAIServices.repo_search`, with 11 repo-search/search-path test additions; `affected_tests`, `command`, and T06 `test_run_affected_*` are unchanged there. Its worktree hashes are recorded above. Candidate `services.py` also has separate T15 `affected_tests` / `command(run_affected)` changes; preserve both until exact owner-scoped export. |
| `project_config.py`, `docs/PROJECT_CONFIGURATION.md`, `tests/test_project_config.py`, `tests/test_project_path_hints.py` | Mixed inherited T21/T04/T09 provenance unresolved | T21 handoff separates its released search seams from inherited T04/T09 changes. Do not classify these whole files as T21-owned or merge their patches without per-hunk owner receipts. Current candidate SHA values are recorded above. |
| `services.py` service methods outside the `affected_tests` / `command(run_affected)` T15 hunks and T21 `repo_search` hunk | Unclassified pending exact provenance | Preserve current bytes; do not include in a T15-only patch until ownership is documented. |
| `tools/benchmark_command_broker.py`, baseline/candidate report JSON | T15 | Benchmark harness and receipts; v2 loads code from selected `--root`, records checkout identities, and emits exact paired cache fixture plus paired and concurrent-warm raw per-sample cache outcomes. Harness/test edits are unverified by pytest pending T20 slot. |

## Acceptance evidence and open boundaries

- Focused acceptance command already completed: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_command_cache_singleflight_contract.py tests/test_command_concurrency_contract.py tests/test_project_command_broker.py tests/test_command_streaming.py tests/test_command_transport.py tests/test_command_timeout_cache_contract.py tests/test_command_suppression.py` — 39 passed, 2 skipped. The skips are POSIX process-group cases and do not prove POSIX recovery semantics.
- Benchmark: 1,000 light samples per concurrency and 30 paired expensive runs. Cache-hit p50 improved 29.1%; cache-miss p50 was nearly flat; capture p50 worsened 66.4%. This does not prove an overall performance win.
- Master-plan acceptance remains partial. Cache p95 deltas do not establish a regression or required win because pair order dominates: hit-first p50 is 16.550/17.289 ms baseline/candidate, while hit-after-miss is 161.155/169.325 ms; miss strata are 2068.978/2065.413 and 2210.081/2216.885 ms. Repeat randomized paired blocks and compare identical source/tree state. Capture remains a stronger regression (n=30, p50 65.529/109.013 ms; p95 69.158/110.824 ms). A plausible T15 cause is the 50 ms callback-dispatcher poll before reader completion; not yet fixed or remeasured. Only one Windows/AMD host is represented. Receipts do not establish every cache identity dimension, all SSE queue/drain/cursor guarantees, mock-port collision, or disposable-environment execution.
- Historical `+16.7% p95` claim is retained as unconfirmed; no matching claim appears in attached receipts. Saved v1 baseline/candidate reports both mark their worktrees dirty and use old harness v1. Their cache-hit p95 delta is +0.81%, cache-miss +1.61%, capture +60.25%; none validates `+16.7%`. Exclude claim from acceptance until a clean, revision-matched T20 benchmark.
- Rebenchmark gate (not authorized yet): wait until T20 provides both the integrated candidate revision and explicit shared-slot assignment. Pin the exact baseline commit and integrated candidate commit; require clean worktrees and record commit IDs, full source SHA-256 values, harness SHA-256, configuration and environment metadata before/after. Compare the same revisions on every required CPU/hardware profile (at least two profiles), with matching OS/hardware, Python/Git/shell, command set and harness within each paired run. Randomize paired order; separate warm/cold; collect at least 1,000 light samples per concurrency and 30 expensive paired runs. Report cache hit/miss p50/p95/p99, capture with and without callback, single-flight owner/waiter counts, peak memory, and order strata. Acceptance must meet the master-plan bottleneck target (>=25% p95 or peak-memory improvement) and show no unexcused >10% warm/cold p95/p99 regression. Do not run before both T20 gates are satisfied.
- Current gate status: T20 queue supplied for this continuation has T07 exclusive slot, then T05. T15 has no slot assignment. Integrated T15 revision is not confirmed. No T15 pytest or benchmark process is active.
- Candidate remains detached, dirty, unintegrated and uncommitted. No T06/T21 patch was applied or merged.
- T06 confirmed five core write-set and four broker caller selectors. Its separate worktree passed `46 passed, 1 skipped` at HEAD `94337de7309b66c63ff427cce8cd3a49e6414d73`; this does not validate T15/root integration. POSIX process-group liveness remains unverified. T21 boundary is owner-reported; no patch application/integration is authorized by this map.


## 2026-10-01 caller/write-set and config/path-hint audit

Candidate remains detached at `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`; current root observed at `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. No source files changed during this audit.

### Attributed hunks

- T15-owned project-config symbols: `_git_primary_worktree_root`, `_path_override_for_candidates`, and `test_primary_worktree_discovery_uses_git_worktree_list`. These symbols and test are already byte-identical in current root; no transfer patch needed.
- T15-owned caller selection: `LocalAIServices.affected_tests`, `LocalAIServices.command` `run_affected` branch, and the three `test_run_affected_*` regressions in `tests/test_project_config_service_integration.py`. Three tests are byte-identical in root. Service method bodies differ from root's newer dispatch implementation; do not export whole methods.
- T21 config work overlaps T15 edits in `_normalize`, `_path_override_for`, `_resolve_project_config`, and `path_is_allowed`; implementations differ. Keep those whole-function hunks quarantined pending finer ownership proof.
- T15 candidate and root `tests/test_project_path_hints.py` function bodies match. Root already contains path-hint selectors; no test patch needed.
- T06 confirmed five core write-set selectors and four broker caller selectors in `tests/test_command_transaction_snapshot.py`. Its separate T06 run passed `46 passed, 1 skipped` at HEAD `94337de7309b66c63ff427cce8cd3a49e6414d73`. This receipt is T06-worktree-only; no T15/root caller receipt. T15 candidate lacks `command_transactions.py` and `test_command_transaction_snapshot.py`. Do not change `commands.py` here.

### Receipt and patch limits

- Old T15 evidence records `152 passed, 2 skipped`, including config/path-hint modules, but has no log SHA or per-run file hashes; treat as historical, not fresh acceptance.
- The reported `86 passed in 3.51s` belongs to `t21-command-consumer.manifest.json` (SHA-256 `6ae8ace012a1b769280e32eaafb72fc96cc60234fb76fa01c7b245703a00d4e8`), not T15. It has no log SHA.
- T04 root acceptance passed `30 passed in 84.98s` on root `98a9a1a`; includes path-hint contracts, not full T15 config acceptance. Receipt: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub\artifacts\t04-current-root-acceptance-receipt.md`.
- Fresh T15 candidate selectors now pass: config/path-hint/affected tests 89 passed in 3.15s; cache/broker/streaming/transport selectors 45 passed in 10.87s. Logs and SHA values are in `t15-merge-ready-handoff.md` and `t15-acceptance-evidence.json`. Actual performance benchmark remains unrun: clean revision-matched candidate and T20 benchmark slot are not assigned.
- Existing T15 root-compatible patch `handoff/t15-root-compatible.patch` SHA-256 `fcce360431c14d5e608946d792847cb9b7700ccff11fd5edcb8b9169e8cb198c` applies cleanly to root HEAD `98a9a1a`; it covers only T15 cache-key/benchmark work, not caller/write-set or config/path-hint.
- No new patch is safe for the requested scope: path-hint and run_affected tests are already in root, config source has overlapping T21 edits, and caller/write-set integration remains T06-owned.

- Latest read-only root recheck: HEAD remains `98a9a1a`; `commands.py` SHA-256 is `9335bc98c291b8ff3738fca9955d41b8b2fae0ca9ff6b60e3148961b2dd34a46`. Existing `t15-root-compatible.patch` SHA-256 remains `fcce360431c14d5e608946d792847cb9b7700ccff11fd5edcb8b9169e8cb198c`; `git apply --check` passes and patch remains unapplied.

- Current merge-ready handoff: `handoff/t15-merge-ready-handoff.md`; exact patch remains `handoff/t15-root-compatible.patch`, SHA-256 `fcce360431c14d5e608946d792847cb9b7700ccff11fd5edcb8b9169e8cb198c`; current-root `git apply --check` passes, patch unapplied.
