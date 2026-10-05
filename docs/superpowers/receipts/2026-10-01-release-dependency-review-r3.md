# Release dependency review r3

Owner: main orchestrator. Root production integration and serialized validation: T20.
No root production edits or tests by this review. Direct human instruction keeps the unavailable Hub ignored; native bounded fallbacks remain authorized.

## Actual integrated regression result

T20 command in `C:\Users\Adam\.local-ai-hub`:

```text
& 'C:\Users\Adam\.local-ai-hub\.venv\Scripts\python.exe' -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t08_http_memory_context_immutable.py tests/test_t08_t13_t12_consumer_overlay.py tests/test_agent_task_memory_adoption.py tests/test_agent_tasks.py tests/test_t16_cross_process_namespace_lease_recovery.py tests/test_t16_lease_wait_namespace_isolation.py tests/test_t16_project_namespace_leases.py tests/test_t16_terminal_rollback_preflight.py tests/test_t16_http_lease_routes.py tests/test_work_fencing.py tests/test_work_handoff_acceptance.py tests/test_work_orchestrator.py
```

Actual: **98 passed, 13 failed, 1 skipped in 69.92s**, exit 1. Windows WinError 1314 skip retained. No blanket green claim.

Failures: immutable memory context fixture; actual async service lifetime consumer; memory correction/delete provenance; same-status concurrent transition; HTTP namespace lease route 503; missing `closing` import; seven work-orchestrator fixtures whose `FakeLeases.claim_batch` rejects `coordination_id`. Confirm exact causes before changing assertions. T20 keeps root file write ownership; T08/T05/T16 prepare disjoint patches.

## T13 independent source review — Sartre

Reviewed exact immutable artifacts:

- `C:\Users\Adam\.codex\worktrees\t13-operational-mode\.local-ai-hub\handoff\T13-rootcurrent-app-context.patch`: `2C85860070141AFFA4906CF3A57642AF57207FAC7DF25AAC303041BD0E1472E2`.
- Same directory `T13-rootcurrent-mode-cancellation-regenerated.patch`: `036DD510B7A20FBECFBEA8B456A0249826A5A1CFE24EA95F5C24103199636D55`.

SOURCE HOLD: actual root AsyncJobManager lacks tracked admission/active API; app patch omits wrapper. Named HTTP patch adds source metadata only, not bounded async drain. Serialized project identity fields disappear at submission; batch container transformation can turn invalid string/dict input into valid list. A mode read followed by unguarded runtime start does not close post-pause start race.

T08 owns async producer; T13 owns app dispatch and HTTP bounded drain; T12 owns model/prefix resolution and generation boundary. Preserve request-ID/replay/lease root hunks. No physical VRAM proof inferred.

Inspected root hashes: app `4050325BCC0F319941A0A183C2DA7CA529A33820236062A39E86E817DCB7705E`; HTTP `6BA4B79AD0A7D06C11151E07E7261AFD9CAD515C1EF8FBA5A0DB0A34CEAA40CA`; async_jobs `A524078F716D4915F6ABFFB27347C4625FDBB9C34A1373F5F8442D7102AEF935`; services `A06AE015085E4B4DC61BF09A99570332044D65D623B7521218E569C329554235`.

## T12 R5 independent source review — Hume

Exact patch `C:\Users\Adam\.codex\worktrees\4816\.local-ai-hub\handoff\T12-O2-root-current-r5-20261001.patch`, SHA `7A6D6B5F3AD91E076723755DDD962AC3611B1357A785DF09EA2D184E68DF2410`. All seven preimages/postimages matched; T10 repo_search/git_history_search/structural_search unchanged.

HOLD one Important finding: strict `_model_info` deadline can expire immediately before HTTP request and return `{}`, falsely producing complete verified empty inventory while outer deadline remains valid. T12 owns fail-first regression and immutable R6. Other five prior review concerns addressed except this failure-inventory edge. `physical_vram_reclaimed=False` preserved. Owner reported 25 passes; reviewer performed no runtime test and did not elevate historical receipt to fresh proof.

R6 follow-up: patch `BF483E47DA2585363A79CA62D60379EB13CC2528B53D9483D4BBFA5E7AF9114B` in the same handoff directory. Main read strict deadline branch and exception propagation, verified actual-root strict apply-check exit 0, and approved narrow integration. Owner recorded 1 fail-first RED, targeted GREEN and 26 passed in 2.09s with source-origin assertions. This closes the reviewed inventory edge, not the separately assigned post-pause model-start boundary. Root services had meanwhile become T14 `6C4FFAF6AD1B90FE0979517C94D610B177F33651C99CCB9FD25FBDDB1296D12A`; preserve those distinct context hunks and pin actual integration postimage instead of pretending old whole-file metadata still matches.

## T03 main integration compatibility check

Exact patch `C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub\.t03-root-overlay\handoff\T03-root-current-contract.patch`, SHA `CD7D46FF2C18C02DE41F2690D8861F1E182BA0D6727A86A2400C450B7256D64B`.
Main reviewed production hunks and targeted assertions; `git apply --check --whitespace=error` exit 0 against actual root. Approved narrow three-file transfer only. Adaptive context hint fields and guards align schema/runtime; fast/full/null/unknown modes reject context hints. Search retains path_hints only. Public output is shared typed open envelope; internal per-action validation remains. Owner overlay 54 pass/1 deselect and real-contract MCP→HTTP 2 pass; root tests and inventory test still mandatory.

## Release boundary

T06 v6 main review found a concrete regression subsequently reproduced by owner: requiring project alias/binding for every generic test receipt silently removed a valid generic pytest receipt. V7 restores generic test/benchmark evidence without granting project-bound proof, retains help/no-execution negatives and tool-aware verbose behavior. T09 independently verifies project configured-command/environment/argument/execution binding; passing generic receipt must never bypass configured-project rules. V6 `2BC2AAED…` remains HOLD; fresh V7 immutable artifact and joined root receipt required.

Current root snapshots by T20: compileall (src/tools/tests) exit 0; selftest all checks success, exit 0; dashboard Node check exit 0, 216 unique ids. Pyflakes src/tools exit 1 with 31 diagnostics. Existing owners receive their own file fixes; misc lint-only changes prepared in bounded T19 overlay by Cicero, no root writes/imports/builds/pytest. Final compileall must include the user-required `mcp` directory too. No blanket lint ignore or stale snapshot acceptance.

T08 F479 five-consumer independent review (Raman): exact SHA matches, 17/18 scoped preimage hunks match; HTTP helper conflicts with existing T16 lease helper. **HOLD broad integration**. P1: shared-repository matching trusts legacy client-supplied repository_id/tenant without server-owned origin metadata. P1: current GET `/api/agent-state/memory` record-ID branch (2085/2086) and list/find branch (2140/2141) both accept caller-selected query tenant/repository_id while patch hardens POST only. Main independently read these source slices; these are two memory branches, not a separate negative-knowledge endpoint. T05 now owns bounded agent_memory and those two HTTP GET binding fixes, public spoof regression and immutable current-root patch; T20 integrates. Do not activate shared namespace branch until trusted origin and all context/task consumers are complete. Existing exact-root reads must not disappear merely because namespace metadata is absent. T08 retains async producer; T13 mode, T16 leases and T09 task completion paths remain separately owned. No second memory system or broad transplant.

T11 independent review (Anscombe): exact v2 production/test SHA pins match and all 28 production hunks match current root in memory; **NOT READY**. P1: same-workspace `index_paths_step` accepts blank-space vectors and relabels them without recomputation; uncertainty suppression is committed after embedding waits, so mixed-file failure/preemption/timeout may leave unreadable-source content searchable. P2: runtime embedding identity may drift after cache key capture; uncertain rows consume pre-filter LIMIT slots; recovered unchanged files may never clear suppression. T11 owns minimal v3 and public fail-first regressions. New legacy test must require decoded fresh vector and exact embedding space, not merely different serialization and any non-empty space. No runtime proof from reviewer; no v2 root integration approved.

Speed priority does not permit weakening privacy, fencing, memory immutability or unknown-outcome gates. Independent owner patches and source reviews run concurrently; root gates remain serialized. 100k benchmarks, broad decomposition and physical model quality are explicit post-release unfinished acceptance, not secretly marked done. No release commit, tag or publication yet.

## Restart and current-root lint handoff follow-up

Latest restart audit found T05/T09/T20 active and 18 other existing task chats idle/notLoaded. All 18 received concrete disjoint continuation work and full-task goal instructions. Grouped wait snapshots confirmed active/inProgress for all resumed owners; T19 had no execution marker yet and its preceding two turns returned only ellipses, so actual T19 progress remains unproven. No duplicate chats/worktrees or archival actions.

Main reviewed sealed misc lint patch `C:\Users\Adam\.codex\worktrees\t19-docs-rollout\.local-ai-hub\handoff\lint-root-current-overlay\ready-current-root\misc-pyflakes-current-root.patch`, SHA `E794D48F949DDCF8996FE0FF46F8BED8E593D84C5EECCAB2D798AE7E9B9C5B09`. Exact four current-root preimages matched receipt pins; `git apply --check --whitespace=error` exit 0. Changes preserve discarded lower/as_posix RHS, complete scheduler metric_name references, and restore postponed CommandBroker annotations through TYPE_CHECKING without runtime import. Ten other original misc diagnostics were already fixed in root and omitted. T20 received approval and subsequently reported integration. This source check does not replace the final full-root lint gate. Completed worker Cicero closed; task chat T19 retained.

T06 V7 remained HOLD after owner reproduced two false-proof paths: `pytest -V` and `-o addopts=--collect-only`. V8 patch `B8925B9A3542164AA4FCF29B073DD35048E86E39BDD49E561812367C37191F60` preserves raw case-sensitive argv and expands addopts before no-execution checks; main read those guards. T20 had already integrated V8 when main checked its patch against root, so apply-check failed against the changed preimage; no duplicate application authorized. T20's fresh root tests and T09 consumer proof remain required. Generic actual tests stay eligible absent matching configured-project rules; generic proof cannot satisfy project-bound rules.

T20 reported narrower actual root results: T16 71 passed / 1 Windows symlink privilege skip; T11 v3 31 passed; T14 lint/schema 1 passed. Exact commands/source pins remain with T20 receipts; these reports do not erase outstanding T08/T09 joined failures. Independent source reviews of sealed RAG v3 and canonical async/mode consumers run concurrently with release integration.

T19 follow-up bounded wait returned completed in 4965 ms, literal `…`, no tool marker. Third identical non-progress outcome; no further resume loop. Existing T19 chat/worktree retained. Orchestrator transferred only candidate INSTALL_PROMPT.md/UPDATE_PROMPT.md plus a new scoped parity regression/handoff to native worker Dalton (`01a0f842-cbb9-7c82-8a17-d641dc5dd738`) and notified T19/T20 of exclusive path ownership. No duplicate task chat/worktree, root build or root production edit authorized to worker.

## Joined-source review verification

Review was evaluated against actual current-root slices before assigning implementation; old sealed patch postimages were already integrated and were not applied twice.

## T09 V4 current-root review — Heisenberg, HOLD

Sealed V4 bundle SHA `77EECCF88D6DBA6052F814641ACDBEF6E8ACAD9FB3D4F5A8C22646ACF3BAFFE1`: nine files, 1731 additions/86 removals. Reviewer found all 25 source hunks already in root, 43/44 total exact postimages; last benchmark test body exists with spacing difference. Do not double-apply. Root T09 reported 59 passed/18 failed, not acceptance. Source review executed no imports/tests/builds/Hub or writes.

Current-source findings: alternate terminal transition accepts checkpoint revision instead of fresh repository revision; initial state repo_root can override authoritative TaskContext and opaque IDs resolve against cwd; custom configured validator can accept generic work_source_review without command proof; same-tenant fabricated self-consistent proof lacks server-owned broker issuance validation; direct transition checkpoint bypasses memory immutability; nonempty default config digest wrongly rejects generic project test proof without matching configured command; new rejection fixture expects PLANNED/no events while complete commits ACTIVE/VERIFYING first; new Git-worktree subprocess.run bypasses tracked descendant-tree cleanup. Main independently inspected the affected trusted-root, proof-binding and transition/checkpoint branches before dispatching corrections. External exploit and all regressions remain unverified, not assumed absent.

Ownership: T09 consumer/trusted root/fresh-revision completion; T08 transition checkpoint preservation only; T06 broker issuance provenance and added worktree subprocess helpers. Existing private proof/receipt stores must be reused; no parallel verification database or caller-supplied issuer treated as trust. Separate actual test failures include six missing hashlib imports, an obsolete set_verification_store fixture (fix supported injection, do not add deprecated alias), and projection failure that still leaves an outcome event. T09 assigned targeted current-root delta instead of reapplying V4 or stopping on legitimate T20 integration drift.

## T04 / T17 bounded public fixture handoffs

T17 browser test-only patch `E3C68C130731DD22657772035F681A4FEE68485B27E65600E505880D2E1B9323` passed main strict current-root apply-check exit 0 and source review: disconnect-after-stage/permission denial produce no committed artifacts; actual handler/store fixture adds unchanged-artifact replay and TTL terminal expiry. Approved to T20; actual toolbar click/WER/live vision remain NOT VERIFIED.

T04 V2 public stream fixture patch `9BB4416E...` failed default strict whitespace check for CRLF carriage bytes; scoped `core.whitespace=cr-at-eol` strict check passed, confirming line-ending issue rather than real trailing spaces. Source review also identified setup cleanup before try boundary. Owner immutable V3 `6E22966E5F34DB964531B43A8309E5B62FBB1E6226F8B20B7609FCA520C63D59` normalizes LF and uses ExitStack/bounded server join while retaining auth/conversation/cancel/deadline assertions. Main strict current-root apply-check exit 0; approved test-only addition to T20. No production transport overwrite. Verify actual daemon-off cold-start uses real Hub entrypoint, not merely an HTTP fixture child.

T19 replacement worker's C4F762... prompt patch has two added blank EOF lines under strict apply-check; R2 requested without rewriting published artifacts. Both canonical prompts must add grounded memory_audit used_ids/not_used_reason/source_checks instructions and confirmed reusable-only privacy requirements. Normal compiled memory element IDs equal record IDs in current source; preload prefixes must not be invented as task checkpoint IDs. Final root prompt parity/package proof remains T20-owned.

## Canonical async/mode source review — Fermat

T08 admission patch `17E5CEABBEA17711749104894A7E5E24708E2D260A4298CDDD7895BAEC69A41E` and T13 consumer V2 `2DFD20E54161C20F57C447A2433BAAA2570DD3F31DCBEDB1EFDD1FA403237948` were already integrated: reviewer found 16/16 and 3/3 postimages respectively. No duplicate apply. Review remains HOLD on joined-source defects, not a claim these patches introduced every defect.

P2 T08: outer delegate admission suppresses distinct nested vision registration through `if depth == 0`, so selective waits/callbacks and excluding delegate can falsely report vision drained. P2 T13: async batch parent root inheritance through setdefault overrides explicit child cwd by creating root=A/cwd=B, while services resolves root first. P1 T13 inherited: HTTP gaming unload/accelerator cleanup executes inside the operational mode guard, holding file/process lock during network calls. Main read the three bounded current-root slices and confirmed mechanisms before assigning owned fixes. T08 must track distinct nested actions; T13 must preserve explicit child identity and reserve release ownership under lock while running cleanup outside it. Release ownership must remain until actual cleanup exit.

Separately T12 actual _generate closure still lacks canonical admission before runtime start; scheduler timeout may return while child execution continues. T12 owns actual executor lifetime boundary and barrier proof, not an outer mode check alone. No GPU proof. Reviewer performed no runtime mutations/tests/imports and was closed after handoff. Source-approved existing aspects: cancellation retains running worker admission, async worker start is serialized against pause, drain is bounded and defers unload when active, malformed batch containers are rejected. Actual joined regressions remain required before accepting the full slice.

## T11 V3 source review — Harvey, remaining HOLD

V4 follow-up: owner sealed delta `9442D24111600F8219716AA2A9F13EE1B4A96AACF02C78BC79EEBA5FB11CB4B2` and reported candidate 168 passed/3 live/benchmark skips. Main read the two production fixes and strengthened decoded-vector test proposal: mechanisms are appropriate, but actual-root strict apply-check failed at rag index_step and both test files. Delta targets preserved candidate V3, not the integrated root generation. Root `494594BA...81DA25` has old_chunk_rows SQL but no following candidate stored_space/space_counts/stale_embedding_paths/explicit_dirty_paths branch. T11 must reseal minimal V5 against fresh root-copy, inserting uncertainty selection under the existing SQL connection and in the actual metadata condition, without whole-file transplant. Root T20 informed; no integration approval or runtime acceptance from those candidate passes.

V3 sealed production SHA `AFAC10C2903FF46613BCDCD9E7CC6FB831315E4FA145AA48B7356CF226E2EAA42`, tests SHA `CD2922E6C746EB08D21A99BC96F8CD7E17D044C0951928CE7118F405A025B224`. Reviewer found all 31 production postimages already in root, rag SHA `494594BA69CE6C18FE2A141B7D43DEBBC08F32D7151764FD730C3FD11781DA25`; old patch must not be reapplied. Source review only, no runtime side effects. Main independently inspected the two affected root slices and confirmed the mechanisms.

P1: read-loop preemption at root rag.py around 1290 returns before accumulated `read_uncertain_paths` suppression publication; unreadable-first then-yield can expose old indexed content. P2: incremental `index_step` around 1619 selects metadata changes/deletions but not uncertain paths with unchanged metadata; full-index recovery fix does not cover incremental recovery. Existing cross-workspace legacy assertion still checks serialized inequality/nonempty space rather than decoded fresh vector and exact expected embedding space across all entrypoints. T11 assigned minimal fresh-root V4 plus fail-first public regressions; T20 notified final release must await the source fix and genuine tests, while other gates continue. Completed Harvey reviewer closed. This supersedes any interpretation of the 31 narrow V3 passes as sufficient release acceptance.
