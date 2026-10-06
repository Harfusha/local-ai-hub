# Local AI Hub — konsolidovaný plán dokončení

## Release-first checkpoint — 2026-10-05

- Priority correction: ship only after current release-blocking correctness/privacy failures are fixed and gates pass. Defer path-hint expansion, broad refactors, 100k performance matrix, and unrelated polish to post-release; do not treat candidate-only green runs as root acceptance.
- Execution correction after repeated stalls: every parallel owner gets one exact scope, acceptance, and handoff format; no agent waits on indefinite discovery/polling. Use one bounded status check per checkpoint, then advance independent work. For failures, reproduce the narrow failing selector once, preserve the assertion/security gate, and fix the proven cause; never rerun broad suites as a substitute for diagnosis.
- Release lane is separate from completion backlog: first integrate only verified owner deltas, fix data-integrity/privacy/correctness blockers, then run the repository-mandated release gates once on the integrated root. Do not hold release for optional benchmarks, broad audits, speculative refactors, or candidate-only evidence. Record each as post-release work with owner and proof still needed. After a failed gate, rerun only the affected selector until green, then schedule one final full gate.
- Release blocker fixed in root: `LocalAIApp.close()` called `shutdown_logging()`, which detached handlers but left `local_ai_hub.propagate=False`; later warnings escaped `caplog` to stderr. RED regression `tests/test_logging_setup.py::test_shutdown_restores_logger_propagation` failed before fix, then passed. Root `tests/test_adoption_metrics.py::test_http_adoption_endpoint_returns_aggregates_only` + T24 redacted logging selector + `tests/test_logging_setup.py`: **6 passed / 10.00s**. Full root `pytest -x`: **129 passed**, then stopped at the T08 fixture failure below. Changed only `src/local_ai_hub/logging_setup.py` (SHA `eca33a57…bb1ab7e`) and `tests/test_logging_setup.py` (SHA `a7a63000…0b6410b`); `git diff --check` exit 0.
- T03 spawn-failure slice integrated from exact owner packets after matching root preimages and `git apply --check`: `tests/test_client_startup_resilience.py` postimage `fc699f17…eba414`; `src/local_ai_hub/client.py` postimage `0e240370…7e95b`. Root `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_startup_resilience.py`: **5 passed / 2.10s**; scoped `git diff --check` passed. Owner closed this slice; broader T03 C1–C3/O5 work remains active.
- T08 crash-recovery fix integrated from owner compaction packet SHA `CBA8FCB811A64B1E08DF4F0C976170803EB0DA94BD41C75CE30896D35847CC74`. Exact root preimages matched manifest: `agent_memory.py` `1D30F09B…A0646C9`, `test_agent_crash_recovery.py` `0CF21A13…2F6709F`; postimages `5B8BB2A5…ADA68A3C` and `69B953AC…6672FBB0`. Packet also fixes the `ProjectSettings` fixture; the separate fixture packet is redundant and was not applied. Five root crash/compaction selectors **5 passed / 2.28s**, scoped `git diff --check` passed. Broader T08 memory-adoption acceptance remains open; final full suite waits for remaining blockers.
- T15 continuation produced no source delta. Windows selector `tests/test_command_concurrency_contract.py -k "recovered_daemon or leaderless"`: **3 passed, 3 POSIX integration skips, 78 deselected**. Linux recovery remains unverified. Owner confirms the benchmark exercises T06-owned `CommandBroker.run`; T20 withheld GO/slot because T06 has no clean candidate pin. Defer paired performance benchmark post-release; it is not a release gate.
- T18 invalid `days` privacy slice integrated from patch SHA `C504C301CA517F296B84BAED957375556EF3F72E8CE8BEE83C0182667F899D0B`; root source preimage `D6EDCE0BC5CEB2D49AA601DE8CBE7ED249C67341CE5D69597645361B1249E6B9`, postimage `05802B7089F6010461FA736EFB11088371025E723BEF5D7E4E3F0A0D6AD762B7`; regression test SHA `BE7799AF4EA8F24281E5211579D5175F777FCB4F2E0AF7194A47D1573949514E`. RED reproduced private prompt/token/path echo; root test **1 passed / 6.42s**, scoped diff-check passed. Privacy slice only; dashboard/status/O4/O5 remain open.
- Root dashboard source tests `tests/test_dashboard_operational_surfaces.py tests/test_dashboard_polling_quality.py`: **23 passed / 1.42s**. Source behavior only; installed/live dashboard and restart remain unverified.
- Interim `python -B tools/release_check.py` exited 1 on working-tree hygiene, not a code assertion: `.pytest_cache`, `.serena`, `.superpowers`, `.venv`, `.worktrees`, local `config.toml`, generated runtime payloads, and `__pycache__` were reported. Preserve these user-local/runtime paths; run final release check from an isolated clean release snapshot after verified integrations.
- T01/T06/T18 resumed-task audit reported no usable owned Git worktree (missing checkout, non-Git filesystem folder, or registry refusing another task's checkout). T01 and T06 managed recovery both failed `Not a git repository`; T06 returned read-only acceptance gaps, no edits/tests. T01's route artifact SHA `7562E3F4…9C278A26` reports 223 POST lines/222 dispatch branches and possible missing `/api/telemetry/timeline`, but no owner/MCP parity or current-root receipt. No changes integrated from these tasks. T02/T04 dispatch IDs were initially crossed; corrected both existing chats. Future dispatches use title-verified thread IDs.
- T02's correctly identified owner thread confirms `4b5d` is not a Git repo and cannot be attached; no source/test delta. T04 confirms `393c` is not a Git repo and its registered candidate checkout is missing. Historical candidate path-hint test exposed secret/blocked-path leakage, but its receipt and hashes are stale, not root evidence. Both owners were asked for one managed-worktree recovery from exact root HEAD `7cb4bcdf`; recovery outcome pending.
- T08 root correction complete for the five Agent Verification failures: owner fixture patch `bd51f6a31c87d5ca1cbddcab1a8d538cef6f7034258f530f03036f9f78393309` plus accessor patch `dddbc3d7fa3b686560ad399267113c12f319c9016cb9c7da5c6508f30f044b3b`; only `tests/test_agent_verification.py` changed (`0e845a4d…32c41` → `e4e1087c…d4cd8bed` → `06265890…13188635`). Root production source unchanged. Five targeted selectors **5 passed / 1.55s**; full root file `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_agent_verification.py` **72 passed / 19.90s**. Persisted `event_page()` rows are dictionaries; test now uses mapping access while retaining durability/order assertions. This closes only this T08 slice, not all T08 acceptance.
- T06 ownership check: its `57e3` cwd is not a Git repository and archived snapshot is missing. Git lists T06-named worktrees, but T06 reports app attachment refused as foreign; it relinquished its assignment, so no foreign worktree is integrated. Historical shared-root rollback selector `tests/test_command_rollback.py::test_rollback_oserror_marks_outcome_unknown_invalidates_caches_and_records_incident` passed **1/1 in 2.17s**; this does not verify the separate daemon-restart selector. Keep the final full pytest gate; daemon-restart current status remains unverified.
- Superseded T03 candidate: the old e809 overlay packet SHA `31d41abef8487610a53363bb9a5f95326057f3a859bf4cad176f6e6f9b8145a0` did not match root preimages and required two absent test files; `git apply --check` failed, so it was rejected and never applied. Its 3/3 candidate selectors were not root evidence. Replacement root-current packet and receipts are recorded below. T14 `/api/context/pack` untouched.
- T08 candidate continuation: owner acceptance batch **105 passed / 64.90s**; cache-isolation **2 passed / 0.51s**; independent context/completion/task-scope/migration-recovery **34 passed, 1 symlink skip / 14.72s**; subscriber contract **4 passed**. Final packet SHA `54a14e1b0c34249cfd4b61e1c5788691b4eb37ed7a9671798f0f8b0e6a3d29d3`; candidate-only, no production root changes. Root patches are only the already-integrated T08 test fixture/accessor patches. T08 remains open for T05 identity/migration coordination and root-current acceptance.
- T05 recovery attempt: existing `t05-identity-recovery` path is registered, but attach is refused as owned by another task. No T05 code or tests run; no foreign checkout read or integration. Prior T05 root failures remain historical pending the integrated full-suite gate; memory identity/migration acceptance stays open.
- T14 privacy/budget fix: applied only the owner packet `T14-root-current-context-budget-fit-redaction-20261005.patch` (SHA-256 `6235A47079CA0F3649266D62572CCCE0CE6486488A1DE4538F614F4CD7E2A035`) after exact root preimage `539DD01FEFD1430B6B22097755F2497FB3F21545360E69C412A9D3286C8A4256`. Root selector `python -m pytest -q -p no:cacheprovider --tb=short tests/test_context_pack_budget_e2e.py::test_mcp_adaptive_context_pack_crosses_http_with_bounded_provenance`: **1 passed in 4.16s**. Actual root postimage `A3716E64B9A0D6B860D0B94213E3FD64A0D9E86A763F908F2AE40E12C09F75D2`; owner-reported expected postimage prefix `37638CC5…` differs, so hash reconciliation remains review/open.
- Adjacent budget suite after T14's test-harness-only fix: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_response_budget.py tests/test_mcp_response_budget.py` — **20 passed in 2.21s**. Root test preimage matched T14 manifest (`AEAE2128…DBB82B12`), postimage is `D9D6F3D5…C9343801`; runtime unchanged by this fix.
- T09 root fixture now uses `app.commands.run_project_command()` to create a real broker-backed receipt and execution record. `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t09_http_task_completion_persisted_receipts.py` — **1 passed in 18.63s**; security gate and HTTP/MCP completion assertions unchanged.
- T14 owner review confirms `response_budget.py` root SHA `A3716E64…F75D2` differs from packet postimage only by one extra CRLF blank line before `budget_response`; no semantic/unowned hunk. Preserve repository formatting. E2E remains **1 passed in 4.16s** and budget suites now **20 passed in 2.21s**. Owner accepts the source hunk; hash-format discrepancy is documented, not a code blocker.
- Root `python -B tools/selftest.py` after two exact missing-symbol fixes: **success, 6/6 checks**. Added local `TaskCheckpoint` import inside `VerificationStore.record_change` and `import time` to `inprocess_transport.py`; transport acceptance selectors: **17 passed in 4.60s**.
- Superseded Agent Verification result: earlier root run had **67 passed, 5 failed / 12.37s**. T08-owned test fixture/accessor corrections now pass on root: **72 passed / 19.90s**; only `tests/test_agent_verification.py` changed, production source unchanged. Keep broader T08 acceptance open for identity/migration and integrated verification.
- Root `python -B -m pyflakes src tools` initially found two unused symbols in `services.py`. T17 could not access its owned worktree (owned by another task), so orchestrator made a two-line behavior-neutral cleanup: removed unused `vision_input_error` import and unused `observation_sources` assignments; vision call still reads `model_context.observation_sources` directly. Current file SHA-256 `C0AD7F25D98451790CAC2D889EA6B9BD2CB73A1AF1ADF4E7E6ED0023A2CE2270`. Revalidation: `python -B -m pyflakes src tools` **exit 0**; `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vision_service.py tests/test_vision_service_phases.py` — **49 passed in 7.17s**; `git diff --check -- src/local_ai_hub/services.py` **exit 0**.
- Strict root `python -B tools/release_check.py` rejects local-only workspace payloads; none removed. Supported live-checkout gate `python -B tools/release_check.py --post-test --allow-installed --json` — **success, 6/6** (`version-consistency`, `defaults-consistency`, `manifest-hygiene`, `public-docs`, `workspace-hygiene`, `release-doc-version`). Valid root syntax gate `python -B -m compileall -q src tools tests` — **exit 0**. `python -B tools/check_dashboard.py` — **dashboard ok: 216 unique ids; node=yes**.
- T03 root-current output schema packet `T03-root-output-schema-handshake-20261005.patch` (SHA `d2dd9e9277b7b6a697a169edd92b80d7af2fcb6847cb9e855d9be11b43437703`) applied after exact preimages and `git apply --check`; both postimage SHAs match manifest. New test RED before source hunk; root operation-contract file **53 passed / 7.38s**. Follow-up fixture packet `T03-root-mcp-agent-routing-isolation-20261005.patch` (SHA `bf832af1ec9b7fca01c995ec517807c5c581f45106cfc81bb05bf43646079da3`) changes only an autouse test fixture; exact reverse-check passed and route/payload assertions remain unchanged. Combined root command `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_operation_contracts.py tests/test_mcp_agent_routing.py`: **102 passed / 8.40s**. Whole T03 MCP dispatch, feature-gate and daemon-off acceptance remains open.
- T08 registered worktree exists at `C:\Users\Adam\.codex\worktrees\t08-agent-os\.local-ai-hub`, HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`, with dirty `agent_tasks.py` and `agent_verification.py`. Agent attach is denied because another task owns the worktree; use only bounded native commands against this exact path or return the access blocker. Preserve inherited hunks.
- T20 acceptance-plan candidate is not integrable: its `2026-09-22` file is 39,959 bytes/210 lines (SHA `A953B23110E47B8E1968423189FB2BF0B093493F7CF98FF61AAF52B5A0FA0062`) versus root's same-named 630,974-byte/2,152-line file (SHA `B9350F06DDC1BA36A29B101DB7F243CCCFE3F59D8E058B7FFA72E640118790BD`). It is a truncated/reconstructed plan, not a safe delta. Keep root plan; request exact status text only.
- Release remains **NO-GO**. T08 Agent Verification slice, T03 output-schema/routing contract suites, T09 persisted-receipt selector, and T14 targeted context/budget selectors pass on root. Full integrated pytest, remaining identity/lease/model-mode acceptance, and final post-integration release gates remain open. No release or deployment claimed.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dokončit existující T01–T21 bezpečně a end-to-end; vydat teprve ověřený, použitelný Hub se zachovanými Gemini změnami.

**Architecture:** Zachovat současné doménové stores a registry; opravovat jejich skutečné integrační hranice, ne přidávat paralelní systémy. Root integruje T20 po přezkoumání vlastněných patchů. Implementace probíhá v již existujících worktrees, nezávislé změny a review paralelně; měření sdíleného hardwaru se vzájemně neruší.

**Tech Stack:** Python 3.11+, SQLite, HTTP, FastMCP, Tree-Sitter, volitelné Serena/Ollama/llama.cpp.

**Spec:** `2026-09-22-hub-quality-performance-master-plan.md`, stávající adaptive-retrieval plán a uživatelská doplnění zaznamenaná v jejich acceptance.

## Účel této revize

Toto je aktuální exekuční pohled na stejné T01–T21, **ne nový backlog nebo nové chaty**.
Původní master plán zůstává zdrojem všech požadavků; jeho historické appendy nejsou aktuální status.
Úplné dokončení není tvrzení o absolutní dokonalosti: znamená splněná měřitelná kritéria a pravdivě doložený provoz.
Požadavek „krok zpět“ mění pořadí: bezpečnost a správnost před rychlým release a dalším rozšiřováním.

## Global Constraints

- Stabilní root: `C:\Users\Adam\.local-ai-hub`; žádné použití `C:\Ostatní\Freq`.
- Zachovat cizí/inherited dirty změny, branche i stashe. Počet změněných cest není dokončená práce.
- Nevytvářet duplicitní task/chat/worktree ani druhý memory, config nebo operation registry systém.
- T20 vlastní root integraci; orchestrátor vlastní tento dokument a T21 převzatý přímým souhlasem uživatele.
- `/api/context/pack` zlepšovat vůči **novému adaptivnímu chování**, nikoli obnovovat starý stav. Existující vlastník schvaluje jeho source hunks.
- Hub transport selhal před zápisem; používat autorizované bounded native fallbacky, bez opakovaných startup/health/polling smyček.
- Zachovat `success`, `terminal`, `retryable`, `outcome_unknown`, scope, provenance a evidence při kompakci.
- `done` až po acceptance na integrované revizi; candidate/unit/source kontrola nenahrazuje runtime, clean-host nebo GPU důkaz.
- Každý handoff: vlastník, absolutní worktree, base HEAD, preimage hash, vlastní soubory/symboly, patch hash, přesný test a skutečný výsledek.
- Před přijetím patche: `git apply --check` **a parse skutečného transformovaného Python source/testu**. Aplikovatelnost diffu nedokazuje syntaktickou správnost.
- Name-binding kontrola doplňuje parse. Pyflakes forward-annotation/`TypeAlias` nález se nejdřív klasifikuje; nepovažovat automaticky každý diagnostic za runtime bug.
- Neaplikovat plošný `checkout`, mazání neznámých souborů ani whole-file převzetí smíšených změn.

Aktuální doplnění review: T08 selektivní drain musí sledovat odlišné nested
inference actions; T13 batch nesmí parent rootem přepsat explicitní child cwd.
Gaming cleanup drží release reservation do skutečného konce, ale síťové volání
a accelerator release nesmí běžet pod operational-mode file/process lockem.
T12 admission patří dovnitř skutečné `_generate` closure, aby scheduler timeout
neoznačil ještě běžící runtime worker za drained. Tyto aktuální joined-source
nálezy mají vlastníky T08/T13/T12 a bounded regresní testy; historické zelené
slice receipts je neuzavírají. Detail v release-dependency-review-r3 receipt.

Izolované candidate safety testy s vlastními temp SQLite, portem 0 a bez
sdíleného Hub/GPU mohou běžet paralelně. Výhradní CPU slot je podmínka
performance benchmarku, ne důvod zastavit každý owned unit/regression test.
Root source a root gates nadále koordinuje pouze T20.

Maintenance acceptance není jen gaming bez GPU: podle explicitního zadání musí
odmítnout všechny agent MCP/API akce bez čtení/zápisů Agent OS databází při
migraci. Současný central gate dovoluje safe job actions v obou paused modes;
T13 dostal opravu omezenou na gaming výjimky. Samostatný operator mode/health/
dashboard kontrolní kanál zůstává dostupný. Canonical prompty nesmí dokumentací
proměnit tento zdrojový nedostatek v požadovaný cílový stav.

Ověřená příčina dalších idle stavů: T05 zablokoval goal kvůli sdílenému T08
test slotu, který se na vlastní temp-state privacy test nevztahuje. Přímý
pokračovací pokyn odstranil tento organizační blocker. T09 zkoušel API opravu
na checkoutu HEAD 968443 namísto současného root HEAD 98a9a1; aktuální root už
má append_in_transaction a record_in_transaction. Nested publish_committed
callback není public metoda; owner musí vyhodnotit skutečné transaction API,
nikoli přidat alias podle grep názvu. T13 dostal výslovné pokračování třemi
implementačními blokery místo statusových odpovědí na cizí handoffy.
T06 starý provenance/worktree patch zůstává HOLD pro stale preimage a EOF;
durable server provenance a T09 consumer jsou současné konkrétní úlohy.

### Ověřené obnovení existujících chatů a aktuální delty

Aktuální inventory ukázala šest aktivních Txx chatů; čtrnáct dalších vlastníků
dostalo konkrétní pokračování ve stávajících worktrees. T19 se po třech
neproduktivních odpovědích neprobouzí opakováním: dokumentační vlastnictví v
existujícím t19-docs-rollout převzal orchestrátor. T21 helper dostal skutečnou
cestu t21-project-config namísto prázdného app checkoutu 4294. Stav active
nevydáváme za hotovou práci; handoff vlastníků není root acceptance.

Aktuální source kontroly: T12 R10 přesný postimage je již v rootu a reverse-check
prošel; T08 memory-decoy test delta má reverse-check 0, takže se znovu neaplikuje.
T14 ledger/budget delta prošla strict root apply-check a source review; T20 má
schválení k integraci a vlastní čerstvé testy. T04 skutečný Hub-entrypoint/MCP
status fixture prošel nezávislým source review a strict check, runtime ověření
aktuální integrace zůstává T20. Review nevydává candidate receipt za release.

T19 R2 memory instrukce už skutečně existují a byly integrovány do root promptů;
starší poznámka o jejich absenci byla překonaná. Orchestrátor ověřil 15 candidate
testů, přidal maintenance-contract red 2 failed a green 17 passed. Jediná schválená
nová mode-only delta je 14-R6-mode-contract-only-context.patch,
SHA 95D7FADD697C0C663F3F636D3AF7322649E4CE303D6673372F24E179FF594707.
Výslovně rozlišuje požadovaný maintenance invariant od dosud nepotvrzené
integrace. Finální pending caveat odstranit až po T13 public acceptance.
Přesné příkazy, vlastní cesty a nepoužitelné meziverze zachovává T19
15-orchestrator-mode-contract-receipt.md; žádná whole-file prompt transplantace.

### Aktuální integrační kontrola, 2026-10-01 14:50 UTC

Orchestrátor ověřil osm skutečných artifact SHA před/po strict `git apply --check --whitespace=error` bez aplikace.
Pět prošlo; T16 core má EOF whitespace chybu, T06 receipts stale broker preimage, T04 SSE forward mismatch odpovídá již přítomnému source/test fixu.
T12 immutable r3 konečně odpovídá metadata SHA, jeho behavior však dosud není ověřen. T12 a T16 mají nezávislé review.
Přesné artefakty, hashe, exits, aktuální root fingerprinty a rozdíl mezi already-present/stale/unverified jsou v [integračním receiptu r1](../receipts/2026-10-01-integration-preflight-r1.md).
Žádný task tím není `done`; vlastníci opravují pouze zbývající hunks a T20 provádí root acceptance po integraci.

### Priorita uživatele: nejrychlejší ověřený release

Přímé upřesnění uživatele: „Zrychli chci to mít co nejrychleji releasnuté“.
T20 prioritizuje bezpečnostní/correctness opravy, integraci a skutečné release gates před velkou T02 šest-case 100k maticí.
`docs/TESTING.md` a `.github/workflows/release.yml` vyžadují compileall, pyflakes, úplný pytest, selftest, dashboard check, release hygiene a fresh package smoke; velká šest-case performance matice není jejich explicitním gate.
Případné přerušené měření se zachová jako incomplete/inconclusive, nikoli jako benchmark proof. Žádný broad process kill nebo `git clean` nad uživatelským dirty rootem.
Release není automatické splnění celého quality/performance goalu; nedokončené acceptance zůstávají otevřené a pravdivě zaznamenané.
Release nečeká na celý T01 operation behavior audit, 100k matrix, fyzické GPU/WER ani širokou architektonickou dekompozici. Čeká na skutečné povinné gates a opravy ověřených data-integrity/privacy chyb, bez deselectu selhání nebo oslabení assertions.
Nové root slice receipts, přerušený benchmark a paralelní hold queue: [fast-track r2](../receipts/2026-10-01-release-fast-track-r2.md). Root-source sdist/wheel/fresh-venv SDK smoke následně prošel **2 passed in 13.131s**, bez skipů; oprava testu ověřuje skutečný JSON wire tvar místo identity Python tuple/list. Finální package proof musí zopakovat T20 až po zbývajících source integracích.
T16 původní review zablokovalo terminal revival, chybějící `waits` seam, neviditelné command leases, nesprávnou wait isolation a multi-file restore preflight. Core v5 a HTTP v3 tyto source opravy již mají a T20 je integroval; celá jejich runtime acceptance dosud není zelená.
Přesné source nálezy, artifact piny, vlastníci a potřebné runtime regrese: [T16 spec review r1](../receipts/2026-10-01-t16-spec-review-r1.md). Source review není skutečný runtime RED/GREEN receipt.
T12 immutable r3 nezávislé review skončilo WITH FIXES: unknown/stale llama.cpp inventory, unmapped aliases, blank-root/cwd scope a conversation-prefix trace privacy. [Přesný T12 review receipt](../receipts/2026-10-01-t12-r3-review.md); před releasem patche opravit a společně ověřit, ne odsunout privacy nebo nepravdivý cleanup.

### Release triage — aktuální společný běh

- Root T08 memory-context guard a T16 core v5/HTTP v3 integrovány. Společný běh 12 modulů skončil **98 passed, 13 failed, 1 skipped in 69.92s**, exit 1. Windows symlink privilege skip není platformní proof; tento běh není release acceptance.
- T08 vlastní test-only aktualizaci pro povolení identického serverového memory kontextu, task-race fixture a oddělený skutečný async admission/drain producer. T05 vlastní memory correction/delete provenance seam. T16 vlastní import `closing` a aktualizaci FakeLeases fixture na namespace API; namespace gate se nesmí vypnout. T20 diagnostikuje přesné tělo HTTP lease 503.
- Skutečný root HTTP lease → CommandBroker selector prošel **1 passed**, ale souběžný HTTP lease route selector selhal 503; stejné dva testy dohromady **1 passed, 1 failed in 19.14s**. Broker bridge není důkaz celé T06/T16 acceptance.
- T03 nový root-compatible patch `CD7D46FF2C18C02DE41F2690D8861F1E182BA0D6727A86A2400C450B7256D64B` prošel main strict apply-check a source integration review. Owner overlay **54 passed, 1 deselected** a joined T14 MCP→HTTP **2 passed**; root inventory test se při finální validaci nesmí deselectovat.
- Následně T20 integroval T03 i T14; skutečná root MCP→HTTP context loopback sada **3 passed, 1 warning in 11.73s**, exit 0, explicitní root module-origin assertions. T03 root contract postimage `28DD0FF31AE5F4163BC439768F2C76B513ED3D2A1CF41AF432520D54A9AF7C83`; T14 services `6C4FFAF6AD1B90FE0979517C94D610B177F33651C99CCB9FD25FBDDB1296D12A`. Jde o nové adaptive chování, ne návrat starého context packu.
- T11 kombinovaná v2 dvojice `63F5091D…` / `3637C2EC…` nahrazuje staré konfliktní v1 patche. Owner skutečný root-copy overlay **9 passed in 24.27s**, ale nezávislé review ji drží: same-workspace stepped reuse stále přeznačuje legacy vectors a mixed-file embedding failure může obejít publikaci read-uncertainty suppression. Vlastník připravuje v3 s těmito regresními důkazy a cache/recovery opravami; v2 zatím neintegrovat.
- T12 R5 review našlo zbývající strict llama inventory deadline větev vracející `{}` jako ověřené prázdno; vlastník opravuje R6 s fail-first testem. T13 review našlo chybějící dependency-closed async lifetime admission/drain, ztrátu identity v payload whitelistu a malformed batch transformaci. T08/T13 mají oddělené vlastnictví producer vs app/HTTP consumer; žádný broad transplant.
- Detail review a piny: [release dependency review r3](../receipts/2026-10-01-release-dependency-review-r3.md). Všechny tasky zůstávají otevřené do vlastních end-to-end kritérií. Release commit/tag/publish dosud neprovedeny.
- T20 mezitím ověřil aktuální root: `python -m compileall -q src tools tests` exit 0; `python tools/selftest.py` exit 0 / všechny kontroly green (vlastní fixture HTTP, nikoli obnovení user Hubu); `python tools/check_dashboard.py` exit 0 / 216 unique ids, Node dostupný. `python -m pyflakes src tools` exit 1 / 31 diagnostik. Opravy rozděleny mezi existující vlastníky a bounded misc lint worker v T19 overlay; žádný blanket ignore nebo zrušení lint gate. Tyto snapshot gates musí finální freeze potvrdit po zbývajících integracích.

## Review Focus

1. Živá MCP hranice, ne pouze přímé Python handlery: deklarovaný argument musí skutečně projít validací a handler se nesmí zavolat dvakrát.
2. Superseded attempt: starý worker nesmí importovat, obnovovat, dokončit ani odstranit journal novějšího vlastníka.
3. Reálné Windows cesty a aliasy: junction/hardlink, CRLF, sdílení souboru, cross-process lock a částečná obnova.
4. Pause mezi admission a inference: nevytvořit nový model/subprocess; neoznačit GPU cleanup za úspěšný při partial failure.
5. Scope/identity a původ: memory i hints pouze relevantní, aktuální a bounded; pytest overlay musí prokázat skutečně importovaný root.

## Baseline a co je dobře

Revize při auditu: root master `98a9a1a7611af574caf20a88620c4aa3eb2e918a`, verze `4.0.0`.
Snapshot Git status: **158 tracked dirty + 103 untracked entries**; root se průběžně mění T20 integrací.
To není 261 dokončených změn ani čistá release revize. Worktree metadata v appce často ukazují opuštěnou cestu;
pro zápis i test musí platit skutečné `git rev-parse` a existence checkoutu.

Source ověření z této revize:

- Serena defaults: soft 4 s, query/startup 60 s, 16 sessions, idle TTL 3600 s; MCP protocol `2024-11-05`.
- U uvedených core souborů `features.py`, `preprocess.py`, `external_tools.py`, `dashboard.py` nebyly nalezeny CodeGraph/Kuzu odkazy.
  `.codegraphcontext` je v repository ignore; INSTALLATION propaguje CodeGraphContext jako externí standalone.
- RAG batch 128, vypnutá LLM card synthesis, `_seed_from_parent`, diagnostics v CPU scheduleru existují.
- AST `find_callers`/`find_callees`, embedding-space migrace, phase aliases a Windows Job Object type guard existují.
- Command rollback má postimage/hardlink ochrany a explicitní uncertain outcome při selhání; telemetrie používá allowlist důvodů místo stejné hlášky pro vše.
- Mode persistence má OS writer lock, atomický flush/fsync/replace a sharing retries; offline CLI a background mode gates existují.
- Agent OS má memory adoption testy, scoped negative knowledge, memory audit checkpoint a lineage/privacy regrese. Chybí jejich kompletní integrovaná acceptance, ne nový store.
- T21 root search již kombinuje broad + targeted výsledky a re-aplikuje policy. Nová reálná regrese je integrovaná:
  `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t21_search_recall.py` → **2 passed in 0.81s**, exit 0.
  Platný i stale persisted hint nezúží recall; projektový exclude zůstává respektovaný.

Source přítomnost těchto mechanismů není důkaz tvrzených „8–10×“, „<200 ms“ nebo „<1 ms“.
Takové výsledky musí mít měření na uvedeném korpusu/revizi, nikoli zkopírovaný popis z auditu.

## Co je špatně — prioritizované nálezy

Nezávislá source review třemi bounded subagenty; root beze změn jejich činností.
Níže jsou mechanismy ověřené source review; runtime reprodukce nových nálezů ještě není provedena.

| ID | Priorita / vlastník | Konkrétní problém | Oprava a důkaz |
|---|---|---|---|
| C1 | P1 / T03 | `operation_contracts.py` nepokrývá handler argumenty (`content/image_path`, command `execution_id/paths/patch`, coord `criterion/board_id`, task `task_id/language/cases`); live dispatch je odmítne jako unknown | Jedna úplná action-specific registry; skutečné MCP boundary testy pro každou rodinu |
| C2 | P1 / T03 | Feature-enabled `batch_replace` schema/validator slice integrovaný; původní batch fixture neregistrovala enabled feature | Fresh FastMCP registration root selector **1 passed in 3.14s**; předchozích 8 dispatch případů není společný 9/9 receipt. Kompletní enabled/disabled katalog ještě ověřit |
| C3 | P2 / T03 | Chybějící selector obchází input validaci; non-object output prochází, scalar může handler spustit podruhé | Validovat i default action; output error envelope a přesně jeden handler invocation |
| C4 | P2 / T04 | Malformed GET/POST JSON klasifikace opravena úzkým root patchem | Tři root regrese **3 passed in 1.84s**; GET invalid envelope, nebezpečný POST no replay, bezpečný POST retry |
| S1 | P1 / T06+T16 | T16 core, T06 broker a service/receipt forwarding integrovány; společná acceptance otevřená | Root původní 12-selector běh: 8 pass / 4 fail. Po narrow opravách původní čtyři neúspěšné selektory: **4 passed in 4.37s**. To není nový 12/12 receipt; **staré r4 patche neaplikovat** |
| S2 | P1 / T16 | Completion/state/receipt/journal clear není vázán na execution epoch | Pod epoch/commit guard zahrnout všechny durable transitions; starý attempt nesmí dokončit successor |
| S3 | P1 / T16 | Work rollback `write_bytes` může přepsat externí hardlink alias při shodném postimage | Preflight link-count/alias policy před jakýmkoli restore; fault test zachová všechny soubory |
| S4 | P1 / T16 | No-journal recovery může předběhnout live attempt; lease rejection zanechá `planning` bez expiry recovery | Bounded deferred recovery s authoritative lease; crash-before-first-journal regression |
| S5 | P2 / T16 | Pending patch zahazuje advisory-lease exception cleanup; fixtures nesplňují nový parent/fence kontrakt | `finally` release vlastních leases; fixture opravit bez oslabení fencing |
| S6 | P2 / T06 | Původní write-set fixture opravena; explicitní `rollback_paths` se používají jako write set i bez rollback | Patch `E61B8537…A75D33A` integrovaný; root selector **1 passed** dle T06 receipt. Fencing S1 není součást této opravy |
| S7 | P1 / T07, test orchestrátor; fix T20 | Selhání observation existující mutace nesmí tvrdit known-undispatched/retryable | Původní genuine root-import RED **3 failed in 0.57s**. T20 integroval opravu; skutečný root `python -B -m pytest -q --tb=short tests/test_mutation_replay.py tests/test_t21_journal_observation_uncertainty.py`: **69 passed in 12.43s**, exit 0. HTTP SHA po opravě `94C44910B04F8909778F926E64D3F857975BAA5738B78979427BACE29AA3EDF3`. Přijat tento slice, nikoli celý T07; starý journal patch nereaplikovat |
| O1 | P2 / T13 | Invalid UTF-8 read boundary opravena, stav fail-closed maintenance a operator recovery | Přijato jako součást **3 root selectors passed in 0.42s** po opravě integrační syntaxe |
| O2 | P1 / T12+T13 | Ollama `if/else` unload vynechá současně běžící llama.cpp | Navštívit oba enabled backendy ve společném bounded budgetu; success pouze při úplném cleanup |
| O3 | P2 / T13 | Gaming cleanup nově porovnává revision pod mode guard a drží jej během release | Stale-resume + existing mode test přijaty v **3 root selectors passed in 0.42s**; širší cross-process/GPU matrix zůstává otevřená |
| O4 | P2 / T18+T19 | CLI partial-cleanup a dashboard JS projection integrované; celý UI flow ještě není uzavřený | Root CLI partial-failure selector má **3 parametrizované pass**, T18 projection selector **1 passed in 0.30s** používá Node.js. Plný CLI/offline, fake-DOM async flow a legacy dashboard regresní sada otevřené |
| O5 | P1 contract / T03+T18 | Admin mode auth při prázdném API tokenu je podle general helperu povoleno | Sjednotit trusted-local/admin policy s existující action-token implementací; loopback badge zůstává read-only dostupný |
| O6 | Integration / T18 | Candidate event pagination a admin fixture kontrakty nejsou sladěné s aktuálním rootem | T20 root `test_http_admin_action_auth_t18.py`, `test_debug_traces.py`, `test_telemetry_timeline_paging_t18.py`, `test_agent_event_page_t18.py`: **24 passed, 17 failed in 8.06s**. Po auth portu admin+operational mode: **21 passed, 2 failed in 8.63s**, tehdy chybějící test helpery. `_redact_config_secrets` mezitím v root source přibyl; starý RED není současná absence. Ověřit actual current mode helper a events envelope/cursor/snapshot/byte budget, nikoli doplnit deprecated test-only alias. T18 vlastní read-only `event_page` + GET route; T08 write transactions untouched |
| D1 | P1 / T05+T08 | Replay tombstone i FTS/embedding deletion jsou integrované v jedné transakci | Root reopen/replay selector **1 passed in 0.29s**; purge selector prošel a opravený fault-fixture rollback selector také **1 passed**. Kompletní correction/delete/reopen/rebuild acceptance, D3/D4 stále otevřená |
| D2 | Test / T08 | 13-selector memory run: 11 passed, 2 failed; helper chyběl `closing`, delete fixture neposlala požadovanou scope identity | Helper import integrovaný, create selector **1 passed in 1.61s**; scoped fixture patch připraven. Produkční scope guard se neoslabuje |
| D3 | P2 / T08 | Chybějící `sqlite3` import v tombstone rollback handleru opraven root patchem | Double-fault selector **1 passed in 0.25s**; primary FTS error zachovaný i když selže samotný ROLLBACK. Celá memory acceptance tím není done |
| D4 | P2 / T05 | `_save_record_row` potlačuje všechny FTS write chyby přes `except Exception: pass`; correction může commitnout stale retrieval projekci | Ověřit optional-table existenci cíleně, neočekávaná write chyba rollbackne update/correction i event; fault regression |
| V1 | Verification / T09 | Starý root-source HTTP matrix výsledek 9 pass / 2 fail předcházel T20 proof-gate integraci | Aktuální root verifier předává `tenant=expected_owner` a ArtifactStore má SHA-256 tenant identity + SQL filtr; hypotéza shared artifact scope neplatí. T09 aktuální tenant singleton podle handoffu odmítá cizí proof. Nová celá matrix má 8 pass / 3 fail (56.44 s), nikoli původní security failures; nedělat storage fix na zastaralém RED |
| V2 | Fixture contract / T09 | Fixture opravena na `test = ["test", "lint"]`; bez lint receiptu singleton fail-closed | Dokumentovaný kontrakt mapuje přesné task criterion, nejde o globální switch. Missing-lint očekávání zůstalo zachované. Nové valid-flow failures ukázaly skutečný V3, ne důvod vrátit neúčinné pravidlo |
| V3 | P1 / T09+T06 | Zelený lint/typecheck/build neumí vyprodukovat automatický command receipt: classifier vrací `source_review`, broker `_record_command_verification` přijímá jen `test`/`benchmark` | Aktuální verifier umí `source_review` + neprázdný `command_id` jako typovaný `command_verification` proof; nový enum není předpoklad. Root producer už má `passed/result/owner`, opačné candidate tvrzení bylo stale. Chybí producer admission a binding skutečného `command_sha256` na configured alias/runner/current config: obecný echo příkaz nesmí splnit lint. Ověřit broker run → durable proof/receipt → HTTP complete; negatives pro substituted runner, tenant/owner, stale revision/generation a uncertain outcome. Lint nikdy nepřejmenovat na `test`. T09 vlastní gate/adapter, T06 přesný producer helper |
| V4 | P1 / T09, test orchestrátor | Caller root i mutable checkpoint mohou obejít autoritativní projektová pravidla; alternate transition nesmí obejít command provenance | Původní root RED **2 failed, 1 passed in 2.59s**. Starý adapter `0A1F…66EE2` po kritickém review zadržen; T20 přesným reverse-check/apply odstranil pouze svůj právě aplikovaný hunk, původní dirty soubor zachován. Root verification_rules SHA opět `157129234E47605307D208BB586E2D8351E619271E79720BA7D0555569FA61B3`. [Review receipt](../receipts/2026-10-01-t09-spec-review-r1.md): mutable checkpoint root/memory bypass a alternate terminal gate bez command/config binding. T09/T08/T06 vlastní nové opravy; root end-to-end acceptance stále chybí |
| P1 | Release / T01+T20 | Append-only plán a old receipts si odporují; `--check` drift se liší podle invocation | Jedno aktuální status view; root explicit invocation, readonly document hash, stejné write/check prostředí |
| P2 | Release / T02 | Combined suite run20 89/90, důvod `hub_queue_admission` není potvrzen | Instrumentovat konkrétní admission/cancel lifecycle; žádné test expectation weakening ani blind 25× retry |
| P3 | Release / T20 | Mnoho candidate receipts bez final-root/installed/GPU proof, některé patche jen apply-check | Dokončit staged acceptance na finálním integračním snapshotu; neoznačovat tasks za done předčasně |

Daemon-independent provoz: současný **bounded owned autostart** je legitimní větev původního požadavku „autostart nebo in-process“.
Nedostupný daemon ale nesmí být prezentován jako funkční transport. T03/T04 musí doložit skutečný cold start,
readiness, vlastní process-tree cleanup a structured failure. Nevytvářet bez potřeby druhý `Services` instance/store.

C1 doplnění z aktuálního T03 AST auditu: chybí také status `adoption_signal/target_tool/target_action`,
task context `phase/focus/preload_profile/repository_revision/changed_paths` a repo action-specific
`context_compile` diagnostics/identity, `pipeline.steps`, `preprocess.is_worktree/parent_root`.
T03 má implementovat registry + skutečný dispatch positive/negative test. Nepoužívaný `work.extra_fields`
se do veřejné registry nepřidává jen proto, že existuje v podpisu. T21 path hints už jsou odděleně vlastněné.

## T01–T21 acceptance a vlastníci — předchozí stavový snapshot

Řádky níže zachovávají původní acceptance kritéria a starší důkazy. Aktuální stav k 2026-10-01 je v následujícím refreshi. Stavy jsou stav celé acceptance, ne posledního selectoru.
Thread IDs z posledního `list_threads` existují; znovu použít stejné chaty. T21 vykonává orchestrátor zde.

| Task | Stav | Přesný zbývající výstup / důkaz |
|---|---|---|
| T01 | blocked | Assigned `1938` checkout missing; managed `create_worktree` failed `Not a git repository`. Route inventory evidence exists, but no root-current/API/MCP parity receipt; no edits/tests |
| T02 | blocked | Admission flake RCA pending; assigned `4b5d` checkout is not a Git repo, managed worktree recovery unavailable; no changes/tests |
| T03 | active | C1–C3/O5, skutečné MCP dispatch schemas, feature gates a daemon-off parity |
| T04 | blocked | C4 root slice přijat 3/3; assigned `393c` checkout is not a Git repo, managed `create_worktree` failed `Not a git repository`. Historical path-hint secret exclusion failure is candidate-only/stale; no current root proof |
| T05 | active | Durable/cache loss/migration/crash matrix, scope/privacy/CRUD/lineage na rootu |
| T06 | blocked | S1/S6, private mutation snapshot/import/recovery, daemon policy and no-orphan acceptance pending; assigned `57e3` is not a Git repo, managed `create_worktree` failed `Not a git repository`; no edits/tests |
| T07 | active | S7 oprava v rootu: replay + observation sada **69 passed in 12.43s**. Zbývají immutable terminal outcomes/epoch, restart a classifier na integrovaném brokeru; candidate 2931 pass / 67 fail / 19 skip / 2 errors není root acceptance. Reconcile pouze zbývající vlastní hunks nad novým HTTP preimage |
| T08 | active | Atomicity/recovery a všech sedm memory adoption integrací; 2 root E2E selektory nejsou celý task |
| T09 | active | Produkční HTTP persisted scoped-receipt selector root **1 passed in 6.74s**. Předchozí matrix 8 pass / 3 fail; typed V3 candidate verifier/orchestrator 83 pass, tasks 26 pass, MCP 2 pass není broker end-to-end. Nový root T20 batch 91 pass / 7 fail vyžaduje vlastní RCA; V4 root-binding bypass potvrzen 2 fail / 1 pass. T06 vlastní `_record_command_verification`, ne neexistující mint alias |
| T10 | active | Retrieval/AST/Tree-Sitter/diagnostics + Gemini preprocessing, paired correctness/performance a nové context consumers |
| T11 | active | Starší root ingestion sada **66 pass / 1 opt-in skip** neprokazuje exact-space izolaci. Nová embedding overlay **3 pass** také neprokazuje public cache/FTS/reuse. Nezávislé review: critical tenant cache collision, runtime-space cache identity, FTS mismatch a legacy provenance relabeling; staré dvě patch pairs se navzájem neskládají. [Review r1](../receipts/2026-10-01-t11-isolation-review-r1.md). T11 vlastní combined opravu a skutečné public RED/GREEN, T20 root integration |
| T12 | active | O2, model-profile/project prompt consumers, routing/VRAM budget a quality matrix |
| T13 | active | O1/O3, hard pause bez nového inference, async/conversation cancellation a mode persistence. Root mode čtyřmodulová sada 29 pass dle T20 receipt; AsyncJobManager admission/drain tracking chybí (T08 vlastní), proto unload fail-closed není finální gaming acceptance. Nový controlled resolver→AsyncJobManager→dispatcher→T12 service→fake generate candidate **3/3**, import origins ověřené; není real model/GPU proof. App-only patch `2C85860070141AFFA4906CF3A57642AF57207FAC7DF25AAC303041BD0E1472E2` main root apply-check 0, root integration dosud pending |
| T14 | active | Nový adaptive context/pack, config+memory identity, pinned context, bounded authoritative evidence |
| T15 | blocked | Cache-only v2 `D26D7F9075EC2E3CE94B23CEC66DAA75FB12AE036B9F51910758DE88DA246501` T20 integroval do rootu; prior targeted suites 15/15 and 115/115. Owner's current recovery selector **3 passed / 3 POSIX skips / 78 deselected**. Paired benchmark uses T06-owned `CommandBroker.run`; blocked on clean T06 pin/T20 slot, defer post-release. |
| T16 | active | Core v5 `27242C3C4F9EA7113DC9E84C4179A6E937583175BF4ECEA64D605BC34A940459` + HTTP v3 `954F126E34DC408F2AF8139E54033F88967EDC2DC072E94F627D70360CCC3AFE` po independent v4 review a main targeted follow-up schválené k integraci. Terminal revival/waits/restore preflight/legacy writer floor opravené v candidate; nové 2 RED pak **12 pass / 1 Windows privilege skip**. Zbývá skutečný root broker+namespace/epoch end-to-end, T06 bridge a root receipts; nikoli jen guarded file writes |
| T17 | active | Browser fixture repair má 5 root replay selectorů green dle T20. Skutečný izolovaný headless Edge + bundled Playwright kandidátní E2E exit 0 (finální harness 11.821 s): stage/commit, request-ID replay, fake expiry a navigation abandon. Test-copy `<all_urls>` není production `activeTab` click proof; fake API expiry není live Hub expiry. Vision/Whisper quality a root-source browser acceptance stále otevřené |
| T18 | blocked | Telemetry invalid-days privacy slice integrated and root-verified (**1 passed / 6.42s**); remaining O4/O5, admin/status/dashboard acceptance blocked by unusable `682c` checkout (`create_worktree`: `Not a git repository`) |
| T19 | active | Matching prompts, plný CLI/clean-host upgrade/uninstall stále otevřené. Nový actual-root sdist/wheel/fresh-venv installed SDK smoke **2 passed in 13.131s**, bez skipů, source map `42A4319D8CF6625E6B8F264BB494F6F239928D719192D3B1FD47FAF6CD78301C`, receipt `6E38D874EADF56ED354EAFE182C02A97A28B954A8FE657B6086FAB6F81B4097E`. Main opravil prokázaný tuple-vs-JSON-array fixture bug, zachoval všechny SDK/resource/schema/network guard assertions a přidal invalid-value controls; test SHA `CF0889E223467D5606161270FF9831005971E4F1BFFF315D1201E50BD9F46144`, Pyflakes global python exit 0. Root capability před dalšími integracemi není finální release approval. Historický clean-profile slice **1 pass in 0.96s** není úplná instalace |
| T20 | active | Root integrace schválených symbol-hunků, operation acceptance matrix, release gates, valid receipts |
| T21 | active | Config/worktree consumers pro search, preprocessing/RAG, commands, context, models a receipt rules. T10 r3 `2873B765178E686F0AF27F82ADC099A2F98B4C2FC273EC5BABD58928F4BBB842` integrovaný T20. Main explicit root-import search/config/repo-tools sada **22 passed in 7.78s**, včetně původních 3 root RED. Přijat tento search slice, ne celý T21; context/pack route nedotčen. Zbývají ostatní consumers a jejich acceptance |

### Aktuální chatový stav a release evidence — 2026-10-05

Stav níže je ověřen z existujících T01–T21 chatů; `blocked` znamená chybějící/nepřístupný přidělený worktree nebo konkrétní závislost, ne dokončenou práci. Žádný task se neoznačuje `done` bez celé root acceptance. Aktuální root `HEAD=7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`, dirty **182 tracked + 216 untracked**; zachovat vše. Počty jsou živý snapshot, ne výsledek práce tasků.

| Task | Stav | Vlastník a aktuální důkaz / blokér |
|---|---|---|
| T01 | blocked | Existující T01 chat; přidělený `1938` worktree a archive snapshot chybí. Root inventory/coverage důkazy zůstávají částečné; úplná operation matrix otevřená. |
| T02 | blocked | Existující T02 chat; `4b5d` není Git repo, artefakty chybí. Flake RCA ani plan-grade paired baseline nemají platný receipt. |
| T03 | active | Root output-schema/reporter isolation **102 passed / 8.40s**; integrated test-only packet SHA `74b6c98d…726fcfd`, base `1608dcfb…4343d0`; root CRLF post `ab81768f…272c400` equals owner LF post after newline normalization. Root `tests/test_mcp_contract_dispatch.py`: **17 passed / 7.56s**, diff-check green. Nová overlay diagnostika: daemon-on/off live FastMCP schema se liší od generatoru `additionalProperties` (RED; přesná kontraktová příčina se ověřuje); simulated `Popen` failure uniká místo bounded structured fallback (RED; ověřuje se). Owner připravuje minimální RED/GREEN receipts a zdrojový patch pouze pokud root chování neplní kontrakt. Živý daemon neověřen. |
| T04 | blocked | Existující T04 chat; `393c` attach odmítnut jako cizí worktree. Žádná nová změna/test. |
| T05 | blocked | Existující T05 chat; `a66e` attach odmítnut jako cizí worktree. Žádná nová změna/test; identity/migration acceptance otevřená. |
| T06 | blocked | Existující T06 chat; `57e3` attach odmítnut jako cizí worktree. Daemon-restart selector stále neověřený na rootu. |
| T07 | blocked | Existující T07 chat; přidělený worktree chybí (`ENOENT`). Root replay slice nepokrývá restart/classifier/terminal acceptance. |
| T08 | active | Root `tests/test_agent_verification.py`: **72 passed / 19.90s**. Integrovan test-only context packet SHA `12df7384…0e71e2`; base `ec5c1a22…c73ffdfc`, post `e9b927a5…1554c24`; root `tests/test_agent_context.py`: **23 passed / 16.62s**. Production source unchanged. Root `pytest -x`: **129 passed**, then crash-recovery test double missed required `config_digest`; owner overlay selector passes with field. Owner full recovery module hung after 17 nodes at `test_compaction_preserves_scope_identity_and_never_merges_tasks`; own pytest PID stopped, no child. Also found a stale test reading old memory stream ID; production helper uses length-encoded scoped ID. Owner preparing one test-only correction packet; selector/full-file evidence pending. Do not weaken completion/memory isolation. T05 identity/migration and Agent OS memory E2E remain open. |
| T09 | review | Root persisted-receipt selector **1 passed / 18.63s**. Přidělený `32fc` worktree chybí; celý HTTP/MCP scoped receipt acceptance není uzavřen. |
| T10 | blocked | Existující T10 chat; přidělený `d4d2` worktree chybí. Candidate AST/retrieval testy nejsou root acceptance; preprocessing a paired proof otevřené. |
| T11 | blocked | Existující T11 chat pozastavil sdílený-root práci; pokračování dovoleno jen ve vlastním worktree. Combined cache/FTS/provenance review v3 a root RED/GREEN chybí. |
| T12 | blocked | Existující T12 checkpoint je neúplný. Stale/unknown llama inventory a další R3/R5 review chyby vyžadují opravu; žádný current root receipt. |
| T13 | blocked | Existující T13 chat; očekávaný `t13-lifecycle-8429` není registrován. Správný async lifetime/mode acceptance stále chybí. |
| T14 | review | T14 zůstává vlastníkem nového `/api/context/pack`. Root E2E **1 passed / 4.16s**, rozpočet **20 passed / 2.21s**; další joined-source/privacy acceptance před release ověřit. Žádná změna T14 mimo vlastníka. |
| T15 | blocked | Existující T15 chat schválil návrh, ale implementace ani paired performance receipt nejsou ověřené. `fefe` checkout cizí/nepřístupný. |
| T16 | blocked | Existující T16 chat; přidělený worktree/artefakty chybí nebo attach odmítnut. Cross-process lease/fencing a root broker/namespace E2E neprokázány. |
| T17 | blocked | Existující T17 chat; `8085` attach odmítnut jako cizí worktree. Browser/vision/Whisper root acceptance chybí. |
| T18 | blocked | Existující T18 chat; `682c` attach odmítnut jako cizí worktree. Dashboard/status end-to-end acceptance chybí. |
| T19 | blocked | Nový owner check: checkout existuje, ale není managed; HEAD `2b33602a…`, 78 dirty entries, vlastnictví neověřeno. Root beze změn; install/update/SDK smoke tentokrát nespouštěny. Starší root sdist/wheel/fresh-venv SDK smoke **2 passed / 13.131s** zůstává platný omezený receipt, ne clean-host update/uninstall. Potřebný managed clean checkout/artefakt a serial disposable host. |
| T20 | active | Orchestrace/release chat; root compileall, selftest, dashboard a supported live-checkout release check mají historicky zelené receipts. Root full pytest a finální post-integration gates zatím neprošly. |
| T21 | blocked | Existující T21 chat; vlastní artefakt/worktree chybí. `path_hints` veřejný kontrakt existuje, ale consumer implementation a root acceptance nejsou potvrzené. `/api/context/pack` zůstává T14 scope. |

Audit TODO komentářů: `rg -n -i -m 2 '^\s*#\s*TODO\b' src/local_ai_hub` našel jediný výskyt `deterministic.py:3868`; je uvnitř dynamicky generované testovací šablony (`{sym}`), nikoli konkrétní nedokončená práce. **Žádné actionable TODO komentáře nalezeny.**

### Aktuální stavový refresh (2026-10-01)

Předchozí task acceptance a `done` kritéria zůstávají platná. Tento přehled obnovuje jen stav, vlastnictví a nejnovější důkaz. Root je dirty; zachovat všechny změny. Kandidátní běhy nenahrazují root acceptance. Žádný celý task není `done`.

| Task | Aktuální stav a nejnovější důkaz | Zbývající důkaz pro celé acceptance |
|---|---|---|
| T01 | active — root inventory refreshed to 642 rows; `surface_inventory.py --check` returns `success:true`, `coverage_matches:true`, `drift:[]`. Six focused selectors **6 passed / 6.14s**; explicit-write CLI **1 passed / 8.52s**. Gap v2 has **434 unlinked operations**; v3 root delta has 151 assigned rows, `unassigned=0`. Evidence review: **430** operations lack asserted operation tests, one disabled-mode negative, two partial source assertions; one transcript run is not bound to its source hash. | Close remaining operation behavior evidence and source-bound receipts; T01 row only `/api/context/pack`. |
| T02 | active, slot released — queue-cancel RCA exact RED/GREEN; root selector **1 passed / 0.14s**. Combined suite **82 passed/8 failed** (two `hub_rag_search` RuntimeErrors). Immutable receipt valid; metrics **2/6**, `plan_grade=false`, no paired run; queue p95 279.548/295.893ms (`n=15`, target 150ms); original 2/25 list unavailable, SQLite warning owner unknown, VRAM unavailable. Batch stopped after first of four cases started; no JSON or usable metrics; three cases never started. T02 confirmed no pytest/benchmark process and released the slot; T01 then completed without tests, so the single slot was assigned to T06 for one narrow grouped Windows daemon run. T11 used one separate 60s candidate window and failed without retry. | Resolve combined failures; 6-case paired baseline, sample targets and GPU/VRAM evidence; no release-quality claim. |
| T03 | active — candidate 58 passed/1 skipped, MCP→HTTP harness 2 passed; artifact bounds 5 root selectors green. Main preflight patch `B2F4A17A…` integrated; root handshake+cold-start selectors **2 passed / 16.56s**. Candidate live-wire **3 passed / 17.53s**; root combined history **95 passed/1 tools/list failure** remains broader unresolved receipt. Separate operation-contract status-output patch is still candidate-only: current root `operation_contracts.py` and test hashes equal its recorded preimages; no postimage/test receipt. | Resolve broad tools/list flake; complete daemon-off/dispatch contract matrix. |
| T04 | active — root/candidate client transport (pubsub excluded) **26/27 passed**; pubsub selector green both; root conversation/auth/public HTTP **15 passed**, candidate **13 passed**. No source patch needed. Exact receipt `T04-client-conversation-transport-acceptance-2026-10-01-v1.md` SHA `221B6A7C…0455E12`. | Owner supplied T04 closeout receipt claims root-current full API/client/conversation acceptance **120 passed / 63.70s** at HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`. Receipt SHA `0646A75C775ADD0E81F58E25B54935DFF2E5339D91B74065EA3B247AB0008F4E`; all eight source/test SHA pins independently match current root. Not rerun by T20; treat as corroborated owner evidence, not fresh execution. T09 broader owner/identity acceptance remains open. |
| T05 | active — v4 identity root **3 passed / 18.03s**; migration **24 passed / 17.43s**. Identity-less delete denial is intentional; scoped root+tenant candidate selector green. T09 fixture overlay selector **1 passed / 24.33s**, root not patched. Tenant predicate integrated through T08 current-root patch; five focused root selectors **5 passed / 3.94s**. Corrected 18-selector root read-only batch: **13 passed / 5 failed / 28.03s**; failures retained for unsupported migration layout/error text and stale transition/delete/provenance expectations. Follow-up test-only identity-delete patch passes root `git apply --check`; its candidate identity selector passed **1/1** with root `agent_events` injected, but edited adoption selector was not rerun and patch remains unintegrated. Earlier candidate run blocked at setup on candidate `TaskStore` lacking `set_memory_adoption`; corrected v3 patch uses direct `MemoryStore` fixture. Candidate bridge run: **2 passed / 0.57s**. Root preimages verified; T05 v3 test-only patch applied to root (patch SHA `6DDE50EAB5A824A67ED3C1CA5A3D83B9C98E57323E8210E1E0179F5521102A4B`). Root postimages: adoption test `B85E72F40C2EFE491AF08383C81D7FEDF03689096F42F630B7BA3DB71EF92847`; new identity test `8ABD2AF37787D7747F9AF58C75A4347EFD1C41537109A05313201F84FC8187E2`. Root grouped selectors now **2 passed / 1 failed / 1.04s**; both T05 selectors passed. The third, T06 restart selector could not run under root API after a test-only `task_id` edit (`TypeError: unexpected keyword argument task_id`); that edit was reverted to exact test preimage SHA `66065F38B3436CC6742BF5B771F0C675C1AA2288B3C9296028CC670CA451C7E5`. Root test remains unmodified until matching T06 API patch. No T05 source file changed. T09 owner declined cross-task fixture patch request; T20 temp probe found tenantless non-global fixtures and stale repository-ID expectations. | Resolve five root failures against supported migration and lineage contracts; run exact root selectors for the test-only identity/delete patch after current T06 slot clears; validate HTTP tenant/project identity at the root. |
| T06 | active — root cache **21 passed, 1 POSIX skip / 3.81s**; atomic exchange patch `6E74C7DD…` integrated. Full root rollback/transaction/project suite **78 passed/5 skipped / 108.75s**. Process-group patch `D7899FA4…` integrated; full daemon lifecycle file **34 passed, 1 failed / 9.99s**, sole failure live daemon stop after broker restart. | Real POSIX exchange/orphan-group behavior unverified on Windows; reconcile recovered-live stop contract and retain Windows no-orphan acceptance. |
| T07 | active — candidate mutation-replay sada **90 passed**; root replay test receipt zůstává scoped. | Root retry/restart/idempotence, immutable terminal outcomes/epoch a observer classifier na integrovaném brokeru. |
| T08 | active — root async reliability **15 passed**; cache/isolation **2 passed / 0.90s**; crash-recovery **5 passed / 2.06s**. Completion-fixture patch integrated; two root selectors **2 passed / 2.79s**. Earlier blackboard-trust selector ran before tenant fix; rerun on current root pending. Blackboard-trust hunk remains excluded pending user approval. A separate T08 migration handoff for `agent_events.py` remains unapplied; current root SHA is still the owner patch preimage, distinct from the already-integrated tenant-predicate patch. T09 reproducer confirms an ordered-event publication API is missing from `agent_events.py`; T08 owner resumed for this dependency, root acceptance blocked until fixed. | Full atomicity/recovery, seven memory-adoption integrations and T05 tenant isolation; user decision on blackboard-trust hunk. |
| T09 | active — root-current v2; broker→receipt→complete **22 passed / 15.67s**. Query module **8 passed / 17.86s**. Latest root integration after T08 fixture fix **50 passed, 1 failed / 88.76s**; focused failure reproduces: expected `task-one`, got `[]`. Diagnosis: request defaults to `http-default`; fixture records omit tenant. Temp probe with tenant-aware fixtures then exposed stale repository-ID expectations. No root test patch applied. | Align test fixture with HTTP tenant header and project repository identity; rerun focused root receipt. Latest assigned T09 worktree snapshot is 45 dirty paths, 41 tracked diffs (+4463/-596), with no owner manifest separating T09 edits from inherited Agent OS/T08 changes. New T09-only reproducer pin F3A87ED0F10965998C0874F18BFDCF6D9B28AD9A9DB1C97DC483F7D312CA4B82 fails: command succeeds (exit 0), but durable receipt is unavailable; `VerificationStoreIntegrationError: state store has no ordered event publication API`. Missing API is T08-owned `agent_events.py`; T09 left it untouched. No root test integration; broader T09 acceptance remains open. |
| T10 | active — four r2 groups integrated; fallback/AST root selectors **20 passed / 4.81s** after patch `D75BCF3F…`. | Owner candidate path-hints pair **20 passed / 1.42s**; exact test file already exists untracked in root with SHA `2155D19CE642ADA864EE102660EB02EDDA098366409F2F0D3A905B7ED10C17E4`. This is candidate execution evidence, not root receipt; T21-owned consumer files remain untouched. Remaining AST language/negative fixtures, measured scan/parse/SQL/graph profile, retrieval/context consumers and paired 100k correctness/performance benchmark. |
| T11 | active — root path-policy consumer **3 passed / 4.03s**; test-only provenance fixture patch `f6a232af…` integrated; four root regressions **4 passed / 0.65s**. Root-source offline suite **128 passed/3 skipped**. Two candidate 100k runs exceeded 750 ms: p95 **972.658 ms** at batch **4096**, then **1698.727 ms** at batch **512**; latter receipt `t11-rag-100k-red-20261001.json` SHA `B068FAB8…160D0D`. Source/harness hashes differ from current RAG; no comparable current-source result. No algorithm cause confirmed; speculative batch-limit change reverted, no retry. | Current-source 100k performance acceptance is unverified; live GPU reranker unverified because weights are absent. Exact-space/cache/FTS/reuse remain open. |
| T12 | active — runtime/gaming selectors **7 passed / 0.29s**; model-free synthetic harness added, root test **1 passed / 4.77s**. It exercises router/scheduler only; `live_inference=false`, VRAM null, quality unmeasured. | Live routing/model-profile quality matrix, repeated VRAM lifecycle and runtime proof. |
| T13 | active — root mode/cancellation suite **11 passed / 3.05s** after pause/recheck/cooperative-yield regressions; offline CLI persistence **3 passed / 2.00s**; process lock/retry selectors **4 passed / 1.47s**. Paused `_step` returns `None`. Gaming conversation release selector **1 passed / 5.15s at HEAD 01df5660** on integrated route: exact top-level cancellation payload, gaming state, and cancellation-before-unload ordering asserted. Owner root-current patch postimage SHA matched `4334271F…1073DAB4`; test fixture uses the route's emitted `conversation_release` field. No live Ollama/CUDA/VRAM proof. | T08 executor-boundary integration, HTTP receipt correlation/terminal contract where defined, and physical unload remain open. |
| T14 | active — root ledger/budget suites **16 passed / 2.77s**. Current-root context tenant selector failed in isolated overlay (**1 failed, 1 passed / 11.76s**): `KeyError: 'tenant'`; `context_identity` omits tenant. Candidate patch SHA `50070C25…` unintegrated; test stubs production `CLIENT.post`, so production tenant-header transport unverified. `/api/context/pack` untouched. | Owner-root tenant identity correction and production-client transport test; full adaptive context/pack budget, cache invalidation, pinned-context and consumer parity. |
| T15 | active — candidate suites 53 passed + 2 skips and 22 passed; paired-harness contract suite **21 passed / 2.61s**, CLI help passes. Latest owner run: benchmark contract/broker selectors **26 passed / 2.97s**; paired benchmark not run. Prior 7-pair probe +30% says `acceptance=false`; no comparable baseline, source pins differ, and no T20 CPU slot explicitly assigned. Benchmark remains blocked; `commands.py` untouched. | Align source/runtime hashes and isolate T15 delta; only then run paired benchmark. |
| T16 | active — root-current overlay junction alias, reparse containment, cross-process/fencing/write-set/broker selectors **7 passed / 12.30s**. Follow-up root fencing/recovery selectors **7 passed / 2.10s**, including the crash-after-patch-write selector (**1 passed / 1.15s**). T16 confirmed the only earlier crash-test difference was a missing child-worker suppression in its candidate fixture; root and candidate recovery sources were identical. Windows symlink fixture **skipped / 0.13s** at setup with `WinError 1314`; symlink behavior remains NOT TESTED. | Root broker+namespace/epoch E2E, T06 bridge, cancellation/recovery; supported symlink proof remains open. |
| T17 | active — root active-tab URL guard selector **1 passed**; root-current isolated browser/HTTP overlay **3 passed / 24.58s**, registered-handler E2E green. | Skutečný toolbar gesture chybí (`node_repl`/`@oai/sky` nedostupné); diagnostic `<all_urls>` test není production `activeTab` proof. Live Hub expiry, WER/vision quality zůstávají neověřené. |
| T18 | active — root diagnostics/SQLite **9 passed / 7.10s**; admin/dashboard/status **25 passed / 1.80s**; telemetry batch **23 passed / 13.24s**. DB byte-limit/store cursor root selectors **2 passed / 1.11s**; route cursor selector **1 passed / 5.23s** with `ResourceWarning` as error. Fresh candidate suite **65 passed / 22.27s**; root-pinned mode/UI/SQLite overlay **11 passed / 8.80s**; telemetry/privacy/paging overlay **28 passed, 1 failed / 15.57s** on `store.flush(1)` timeout, then that node passed alone **1/1 / 0.77s**. No T18 root edits. | Keep timing failure visible; retain admin auth, trace retention, bounded status inventory, and clean-host proof. |
| T19 | blocked (owner) — candidate packaged SDK smoke **2 passed**, T19 suite **69 passed, 1 Windows symlink skip**. Root-current 28-path hash overlay is pinned but has no test receipt; T19 now preparing the bounded 19-test root-source overlay. | Clean-host Windows/Linux upgrade/uninstall and frozen same-revision live HTTP/MCP/auth/outage/restart/concurrency matrix; final `verify_completion`. |
| T20 | active — T01 inventory clean at 642 rows; 430 operations lack asserted tests, three source assertions remain partial/negative, one transcript result lacks source binding. T02 full candidate batch stopped after its first of four cases and produced no usable metrics. A later two-selector queue/scratch reproduction passed **2/2 in 25.89s** at candidate HEAD `a7b0868a`; still no paired root baseline, only 2/6 metrics and `plan_grade=false`; T02 goal remains blocked. Process check found no running T02 pytest/benchmark; slot released, T01 used the released slot for its own two-selector run (**2 passed / 2.82s**) and then released it; T06 received the next slot. T06 candidate-worktree attempt failed at import collection; the subsequent root-current grouped run is recorded below. T03 handshake/cold-start **2 passed**. T04 partial transport green. T05 tenant predicate integrated via T08; five focused root selectors pass; corrected 18-selector read-only batch **13/18**, five failures retained. T09 broad suite **50/1**; HTTP fixtures still conflict with default tenant/project identity; no root fixture patch. T06 process-group patch integrated; daemon lifecycle **34/1**, live stop after broker restart fails. A separate candidate-only selector `test_named_daemon_job_survives_restart_and_stops_descendants` failed twice: **1/1 in 1.03s**, then after removing kill-on-close **1/1 in 1.22s** (daemon_status.success=False after broker recovery). Owner inspected exact error return; post-fix selector still failed. Exact command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_daemon_lifecycle_hardening.py::test_named_daemon_job_survives_restart_and_stops_descendants`; exit 1, **1 failed in 1.22s**, line 1109 (`status[success] is True` after second broker recovery). T06 candidate diff limited to `src/local_ai_hub/commands.py`, `tests/test_daemon_lifecycle_hardening.py` and two T06 handoff docs; root untouched. No second run or grouped rerun. Restart recovery remains unfixed/unverified. Reported candidate path `t06-safe-commands` differs from list_threads worktree `57e3`; verify canonical worktree before any integration. Candidate-worktree attempt could not collect because `local_ai_hub.project_config` was absent there. Root-current grouped equivalents then returned **22 passed, 1 failed in 25.17s**; Windows Job descendant, orphan-stop and PID-reuse selectors passed. Sole failure remains `test_live_daemon_is_reconciled_after_broker_restart` (`stop_daemon()` returned `success=False`). Slot released. T08 tenant isolation **5 passed / 3.94s**; blackboard-trust hunk excluded pending user approval. T10 fallback/AST **20 passed / 4.81s**. T11 offline **128/3**; two 100k runs above target, but source hashes mismatch current RAG; current-source performance unverified. T12 synthetic harness **1 pass**, no live proof. T13 root pause **11 passed**, offline CLI **3 passed**, lock/retry **4 passed**, exact gaming conversation release **1 passed / 4.82s at HEAD 01df5660**; root test SHA `4334271F47273A5FA99520BBF56E6E1D311A60F1CCAA79D189D86D721073DAB4` matches T13 owner overlay; live runtime proof open. T18 root DB/store **2 passed**, route cursor **1 passed**; latest root-pinned telemetry overlay **28/1** with isolated timeout node **1/1**. T14 tenant selector fails; T16 focused root fencing/recovery **7 passed / 2.10s**, symlink NOT TESTED; T06 root-current bounded group **22 passed / 1 failed**; candidate named-job restart/descendant selector **1 failed / 1.03s**, owner diagnosing; worktree identity mismatch must be resolved before integration. T10 candidate path-hints pair **20 passed / 1.42s**; root test file untracked, no root receipt; T15 contract tests **26 passed / 2.97s**, paired benchmark blocked by missing comparable baseline and reserved T20 CPU slot. No final release gate. | Resolve T06 recovered-live stop contract; resolve T09 fixture/current identity contract; obtain current-source T11 performance result; close T03/T05/T06/T08/T13/T14/T16/T18 and remaining owners; schedule T02 matrix after exact IDs/pins; align T15 pins; then run one revision gate plus clean-host/install/runtime proof. |
| T21 | active — fresh root MCP/client/`/api/search`, resolver, project/worktree configuration and path-policy batch **108 passed / 20.71s**; `git diff --check` exit 0. Existing T21 hunk overlaps shared dirty files; no attribution of whole diff. `/api/context/pack` untouched by this run; T14-owned hunks already present in shared `http_server.py`. | Remaining config consumers and receipt route; maintain T14 `/api/context/pack` owner boundary. |

## Exekuční pořadí — stejné tasky, malé ověřitelné kroky

### Vlna A: bezpečnost a veřejná použitelnost

- [x] Source review command safety, MCP contracts a operational lifecycle paralelně; vlastníci dostali konkrétní nálezy.
- [x] Quarantine nekompatibilního T16 forwarding/core patch; T06 fixture následně opravena a write-set slice přijat root testem.
- [ ] T03 opraví C1–C3 a skutečnou MCP dispatch regresi. Nepoužít jen schema-equals-registry test, který kopíruje stejnou chybu.
- [x] T04 přidal malformed GET/POST JSON test a opravil jen parsing/classification; root **3 passed in 1.84s**, request IDs a no-ambiguous-replay zachované.
- [ ] T06/T16 dokončí společnou acceptance již integrovaného privátního fence interface, durable epoch transitions a transaction commit/recovery. Úzké root receipts výše nepokrývají všechny interleavingy.
- [ ] T16 přidá hardlink a lease-recovery/cancellation regrese; po failed preflight žádná částečná obnova.
- [ ] T20 ověří preimage+patch hash, apply-check a nezávislé review; pak integruje pouze schválené hunks.

Files: `operation_contracts.py`, `mcp_server.py`, `client.py`, `commands.py`, `command_transactions.py`, `work_fencing.py`, `work_orchestrator.py`; tests vlastníků.

Po vytvoření uvedených nových regresí spusť po oddělených slotech:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mcp_contract_dispatch.py tests/test_operation_contracts.py tests/test_mcp_agent_routing.py
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_transport.py
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_command_transaction_snapshot.py tests/test_command_rollback.py
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_work_fencing.py tests/test_work_handoff_acceptance.py
```

`tests/test_work_fencing.py` i `src/local_ai_hub/work_fencing.py` již v rootu jsou (ověřeno 2026-10-01). T16 nový test se dvěma skutečnými subprocessy a successor receipt má candidate **1 passed in 0.35s**; test-only delta čeká na T20 review/root receipt.

### Vlna B: operational režimy a zachování durable dat

- [x] T13 O1: regression zapisuje `operational_mode.json` přes `write_bytes(b'\xff')`, očekává degraded maintenance; `set_operational_mode(...,'active')` obnoví čitelný snapshot. Root selector green.
- [x] T13 O3: interleaving mezi persist gaming a cleanup, mezitím resume; stale cleanup je vynechán. Root regrese a běžný mode guard selector green.
- [ ] T12 O2: zároveň fake Ollama `/api/ps` i llama.cpp loaded rows, oba unloady zaznamenané; selhání kteréhokoli nezmizí ze summary.
- [ ] T18/T19 O4: stejný partial failure model v dashboardu i CLI, včetně accelerator/job cancellation výsledků.
- [ ] T03/T18 vyřeší O5 přes stávající security boundary; offline mode recovery a loopback GET badge nesmějí být náhodně zablokované.
- [ ] T05/T08 otestují skutečné durable data po cache-clear, schema rebuild, failed migration backup a restartu; žádné mazání agent DB při opravě indexu.
- [ ] T05 D1: scoped delete atomicky odstraní retrieval projekce; neočekávaná FTS chyba rollbackne record i embeddings. T08 durable tombstone/reopen/replay slice prošel 1/1 za 0.29 s, ale společná cleanup acceptance ještě chybí. T08 D2 opraví scope fixture, ne produkční guard.

Files: `operational_mode.py`, `ollama.py`, `process_utils.py`, `preprocess.py`, `http_server.py`, `dashboard.py`, `tools/hubctl.py`, Agent OS stores.

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_operational_mode.py tests/test_hubctl_mode.py tests/test_operational_mode_http_gate.py tests/test_preprocess_operational_mode.py tests/test_ollama_gaming_mode.py
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_agent_state_migrations.py tests/test_t05_cache_clear_durable_state.py tests/test_agent_t08_cache_isolation.py tests/test_agent_crash_recovery.py
```

Windows skuteční concurrent readers/writers a GPU memory release se uvádějí jako samostatná runtime acceptance, ne jako monkeypatch proof.

### Vlna C: automatická memory adoption, config a nový context pack

- [ ] T08/T05/T09 dokončí sedm memory acceptance: create+resume injection; použité IDs nebo text reason; repo/tenant/task isolation; stale/expired/corrupt; no-noise budget/deadline/fail-open warning; privacy; dohledatelná correction/delete lineage.
- [ ] Ověřit **produkční app wiring**, ne ručně připojený test `TaskStore`; confirmed reusable findings po úkolu mají provenance, ne automatický chat dump.
- [ ] T09/T06 dořeší V1–V4 proti aktuálním produkčním imports: přesná criteria a tenant-bound artifacts, skutečný automatický lint/typecheck/build command proof, revision/generation a memory-used-or-reason. Completion config musí být vázaná na trusted task/worktree root, ne caller root jiného projektu. Před změnou gate potvrdit RED bez stale source/fixture chyby; positives nesmí selhávat a negatives nesmějí být povolené kvůli zelenému běhu.
- [ ] T21 a původní consumer owners uzavřou všechny config layers a pole: excludes/force/phase skips/extensions/size; commands/env/mappings/rules; pinned/entry/weights; languages/solution/model profile/system prefix; shared namespace.
- [ ] Hints jsou ranking/focus evidence, ne skryté zúžení recall; průchod repo policy i containment platí v search, ingest, context a command consumers.
- [ ] T10/T14 dotáhnou nové `/api/context/pack`: deterministická authoritative evidence, deadline a optional backend degradace, budget, config/memory revision invalidace; žádný návrat ke staré implementaci.

Files: stávající Agent OS stores/context/tasks, `project_config.py`, released consumer symbols v `services.py`/repo/RAG/preprocess/MCP/client; route zůstává vlastníkovi.

### T21 consumer mezery — aktuální source kontrola, ne runtime acceptance

Resolver a testy typování samy neprokazují používání konfigurace. Bounded source kontrola rootu dne 2026-10-01:

Nový actual-root-import T21 search consumer test v existing worktree `tests/test_t21_search_policy_consumers.py` prokázal **3 failed, 2 passed in 1.86s** (bez Hubu, portů a GPU; skutečné lexical tools nad tmp Git repo).
`custom_extensions.text=[".shader"]` nevrátí soubor s přesným hintem ani bez něj; `force_include_paths=["node_modules/@my-org/**"]` nevrátí Git-ignored soubor bez request hintu. Positive exact forced file hint a binary-policy refusal prošly.
Test SHA `2D95ECEB2B4F3C283AF5006633EAD8378669BF033BD0781312A50BF3E5DE7C1B`; všechny tři module `__file__` potvrzeny pod aktuálním root `src`.
Kvůli odstranění čekání mezi handoffy má T10 výslovně uvolněné pouze search backend/per-call immutable policy helpers a `RepositoryTools.search_paths`/`LocalAIServices.repo_search` pro tento malý closed fix. Orchestrátor tyto produkční seamy souběžně nemění; vlastní nový test/handoff a review. Žádná změna `/api/context/pack` route ani T12 model metod.

| Konfigurace | Aktuální důkaz / zbývající práce | Vlastník |
|---|---|---|
| inheritance, overrides, path policy | Resolver a rozsáhlé core testy přítomné; search recall regrese prošla 2/2. Všechny released consumers ještě nemají společný receipt | T21 / orchestrátor |
| `pinned_context`, `entry_points` | `task_context.py::_project_context_hint_groups` resolver používá. Chybí finální nové context/pack behavior matrix | T14 |
| `retrieval_weights` | Root source nenalezla runtime použití mimo resolver. Ověřit nepřímý tok, potom skutečné fusion/rank wiring; ne pouze schema exposure | T14 |
| preprocessing excludes, `skip_phases`, language/project/solution hints | Preprocess/index/parser nemají zřejmý project-config consumer. Ověřit call chain a doplnit policy, phase resume a invalidaci bez ztráty Gemini seed/diagnostics | T10 |
| RAG ingestion policy | Root project policy/read bounds/embedding-space/reindex matrix: 66 pass / 1 opt-in live skip. Explicit `index_paths_step` vůči `rag.ignore_dirs` je potvrzený consumer RED, T11 jej opravuje; širší worktree seed/quality/performance proof zůstává otevřený | T11 |
| `model_profile`, `system_prompt_prefix` | Root source nenalezla runtime consumer mimo resolver. Zapojit existující lokální model policy, zachovat izolaci a telemetry privacy | T12 |
| commands/env/mapping | `commands.py` resolver a `services.py::run_affected` používají; potřeba skutečný broker/worktree/env receipt | T15, T06 vlastní mutující broker seam |
| `verification_rules` | Produkční task-complete route s persisted tenant-scoped receipts prošla jeden root selector (1/1, 6.74 s); kompletní revision/criterion/fail-closed matrix ještě chybí | T09 |
| `shared_namespace` | Read-only callchain audit prokázal použití jen v path hints; memory/lease wrappers dál předávají fyzický root. Automatické sdílení napříč linked worktrees dosud chybí | T21 identity bridge; T08 memory, T16 leases/fencing seamy |

Všechny mezery předané stávajícím vlastníkům; žádný nový task, chat nebo druhý config/memory systém.

Další skutečná source kontrola root `rag.py` SHA `23BEE629DA1B9F4BA555FE64D031701553118F4CC3B55D8421FDC8D3885626DE` potvrdila T11 handoff nález: vector keyset predicates obsahují pouze tenant/workspace bez exact `embedding_space`, FTS/token fallback rovněž nemá tento filtr.
Nový read-uncertainty v1 patch tuto předchozí izolaci neobsahuje. T11 zůstává vlastníkem produkční exact-space opravy a příslušné controlled-overlay regrese; T20 ji integruje, ale není náhradním autorem. Starší narrow green receipts ani candidate testy nemohou dokazovat chybějící root consumer wiring.
Candidate read-uncertainty production patch `C5F02D68E371C38B853DDC1A4F329E82EDF916ED6E3BA916B6FF68F193615B0F` a test patch `92DF47AEC69807ACCB50689EDD99661969335E4E052E3CF4B6050CD869F8F361` se mají posuzovat odděleně od nového exact-space release fixu.

#### T21 namespace bridge — konkrétní acceptance a bezpečnostní hranice

Source audit: `mcp_server.py::_client_root` + coord dispatch, `client.py::coord`, HTTP memory scope resolver
a lease claim routes, `services` memory wrapper a `agent_context.py::ContextCompiler.compile` neprovádějí
git-common/namespace normalizaci. Resolver ji nyní používá pouze v `ProjectPathHintStore.project_id`.
Explicitní klientský `repository_id` není důkaz automatického nebo důvěryhodného propojení.

- [ ] T21/T08/T16 dokončí consumer wiring nad již integrovanou root producer identity. `ProjectContext.coordination_id` používá existující salted git-common/namespace ID, při invalid config vrací `None`, fyzický root nemění. Candidate **103 passed in 8.01s**; T20 následně integroval pouze owned hunks a oba nové producer test soubory v rootu: **6 passed in 1.80s**, exit 0. Samotná property nepřipojuje memory ani leases.
- [ ] T08-owned memory boundary ji použije pro repository scope create/get/find/context/adoption. Stejný common + namespace + tenant sdílí potvrzené repo poznatky; jiný common/namespace/tenant ne. TASK/WORKTREE/BRANCH se nesmí slít.
- [ ] T16-owned lease boundary použije stejnou repo identity pro konflikty relativních write setů, ale neoslabí monotónní attempt fencing ani physical-path containment. Cizí owner nesmí renew/release.
- [ ] Alias namespace sám nesmí sdílet data mezi nesouvisejícími repozitáři. Nevěřit client-supplied hash/root aliasu; malformed nebo nedostupná config/git identity se vrací jako jasná scoped degradace, nikoli cross-repo fallback.
- [ ] Wrapper integration test: dva linked roots A/B a nezávislý C, skutečné stores v `tmp_path`; může stubovat Git-common discovery. Memory A→B je relevantní, A→C/different namespace/tenant nikdy. Lease A claim vs B jiný owner koliduje, C namespace nezávislý.
- [ ] Durable provenance, correction/delete/replay a legacy uložené záznamy zůstanou zachované. Test explicitně oddělí znalost repository od proměnlivého source faktu ověřovaného ve skutečném worktree.

Lease `tenant` nyní představuje vlastníka v konfliktním pravidle `tenant<>?`; není to totéž jako privacy tenant memory.
Neimplementovat falešnou izolaci filtrem, který by dovolil dvěma vlastníkům současně editovat překrývající se write set.
Existující lease list metadata behavior se nemění bez samostatně schváleného kontraktu.

T16 namespace candidate patch `26C83E5B29E81EC4B8A011806D259399EB273E85CBAFC34616540D4ED7369DC8` main root apply-check 0; candidate 63 pass / 1 Windows symlink skip / 1 T06-overlap deselect, actual-root CommandBroker overlay compatibility 1 pass in 1.08s. Patch mění jen leases/fencing/orchestrator a testy. Bounded current root review potvrdila, že veřejné GET lease list/waits a POST claim routy dál předávají pouze fyzický root, takže samotný tento patch veřejnou worktree namespace adoption neuzavírá. T16 uvolněny pouze tyto candidate route callsites a `ScopeLeaseStore.waits` read seam pro server-side resolver identity; žádný klientský `coordination_id` override, žádný HTTP auth/frontdoor/journal/T18 events/memory/context-pack překryv. Route-only patch má být samostatný nad aktuálním root preimage; T20 integruje a ověří T21 wrapper collision/isolation matrix.

Producer handoff: `C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub\handoff\T21-coordination-identity-20261001.md`.
Patch `T21-coordination-identity-root-current.patch` SHA-256 `36DE4284FF1704E5B030DE0D9B76405F75C9C2FF45AAF2360A08129BC5B98D1D` obsahuje jen property a nový pět-case test, nikoli zděděný 264-line candidate diff.
Orchestrátor přezkoumal skutečné consumer test seams T08/T16 a uvolnil jejich candidate implementaci (root stále výhradně T20): T08 `MemoryStore.find_for_context`, repository matching/provenance a nezbytné `ContextCompiler`/task-adoption callsites; T16 `ScopeLeaseStore` namespace key/claim/list/renew-release a související fencing/work-orchestrator resource wiring. Žádné vzájemné editace, žádný druhý store. Public client-supplied coordination ID není autorizace a nesmí se stát přepisem server resolveru; negativní wrapper test je povinný. T06 mutující broker a context/pack route zůstávají původním vlastníkům.
Další producer proof používá skutečné tmp Git repozitáře a detached linked worktree, bez stubu discovery: candidate `tests/test_t21_real_namespace_identity.py` **1 passed in 3.12s**. Oddělený test-only patch `T21-real-worktree-identity-test.patch` SHA-256 `75A48A6511D3BBADF2252655927D603FF0041EF2FF3D497C6D1F1D59BF9E094A`, root apply-check exit 0. T20 root kombinovaný příkaz `python -B -m pytest -q -p no:cacheprovider --tb=short -c pyproject.toml tests/test_t21_coordination_identity.py tests/test_t21_real_namespace_identity.py` prokazuje **6 passed in 1.80s**, exit 0. Nejde o kombinovaný 104/104 běh ani dokončenou namespace consumer acceptance.
Přesný root producer příkaz pro T20 slot:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t21_coordination_identity.py
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t21_real_namespace_identity.py
```

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_agent_task_memory_adoption.py tests/test_agent_memory.py tests/test_project_verification_rules.py
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_config.py tests/test_project_path_hints.py tests/test_project_config_service_integration.py tests/test_t21_search_recall.py
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_api_search_path_hints.py tests/test_mcp_repo_path_hints.py tests/test_client_path_hints.py tests/test_t11_project_policy_consumers.py
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_adaptive_retrieval.py tests/test_context_delivery.py tests/test_context_request_identity.py tests/test_context_ledger.py tests/test_response_budget.py
```

### Vlna D: Gemini parity, výkon, použitelnost a modularita

- [ ] T10/T11/T12 prokáží všechny Gemini změny regresí: soft-timeout proces nezabije; empty-query skip; AST calls pro Python/C#/TS/JS/Go/Rust; seed integrity; diagnostics slot release; self-root indexing; compiler/linter no-orphans; embedding migration; pipeline/schema aliases; lease normalization/phase aliases/Job Object termination.
- [ ] T01 odstraní inventory/doc drift a doplní operation-specific evidence. Feature přítomnost a registry equality nepředstírají behavioral coverage.
- [ ] T02 potvrdí admission/cancel race trigger a ověří opravu; benchmarky cold/warm a concurrency odděleně, latency bez `tracemalloc`, memory samostatně.
- [ ] T10/T11/T12/T15 doloží recall/quality i p95/p99 na finálních implementacích; žádné snížení kvality pro zelené číslo.
- [ ] T17 reálný browser stage/commit/navigation/replay/expiry, vision bounding/evidence, Whisper cancellation a quality; nedostupný backend má pravdivý unavailable stav.
- [ ] Doménovou dekompozici `services`/`deterministic`/HTTP/dashboard provádět až po parity baseline, po malých behavior-preserving module boundaries.
- [ ] Swarm/blackboard rozšíření nerušit pouze podle počtu řádků; zjednodušit podle doložené potřeby. CodeGraph naopak z Hubu nepřidávat zpět.

#### Scope/decomposition — bounded source evidence, nikoli runtime adoption proof

| Oblast | Aktuální konkrétní evidence | Rozhodnutí / další acceptance |
|---|---|---|
| Swarm | `swarm.py` 841 řádků, SHA `8e2e0a4a7289b1308295a6b87a988921ffa56271c6079752ca361fd39c950513`; app explicit wiring, HTTP/MCP actions, coordinator závisí na stejném durable state/blackboard/verifier DB. Lifecycle test submit-patch/report-test/approve je deklarovaný scénář, ne důkaz produkčního běhu test runneru | Dočasně keep explicit capability a durable data; neclaim unused ani odstranit pouze podle velikosti. T01/T08 ověří, zda public completion nemůže mintovat syntetický test success. Potom simplify/remove pouze s parity a důkazem podporovaných scénářů |
| Blackboard | `agent_blackboard.py` 619 řádků, SHA `9222a5084bbb0a937cadb79a091134cabd4ca3a73b7a1321f0035db4dc78e2d1`; CRUD/CRDT má public API i persistence tests. Schema obsahuje board/section/content/author/clock/time/version, nikoli repo/tenant scope | Explicitní collaborative board není náhrada scoped memory. Data zachovat; prověřit implicitní context injection a potřebnost default exposure před zjednodušením |
| Implicitní blackboard context | `agent_context.py::compile` čte task/task-prefixed/swarm-prefixed i `global` board ID a obsah přidává s confidence 1.0 bez tenant/repo validity argumentu do `blackboard.get`. Source observation není ještě runtime reprodukce ani potvrzení záměrné global-sharing policy | T08 adoption acceptance musí prověřit cross-tenant/project/default-context boundary a provenance; neřešit přidáním paralelního memory store. Unscoped collaborative obsah nesmí předstírat ověřený scoped reusable fakt |
| Doménové monolity | Source AST snapshot: `services.py` 6871 řádků/SHA `1556edbe4336e1d0fecdac86d79593ab6f62be12a1f13841537cac453721dcc1`, `deterministic.py` 7216/SHA `277c43abe38a6785788747553e5d8690a9c868b3f314d0fa041ae8910be9ed04`; `task_context.py` je již samostatný 319-line modul, stores jsou také samostatné | Thin composition root cílový stav stále nesplněn. Line counts nejsou výkonová metrika. Po aktuálních correctness fixes a parity vybrat první samostatně testovatelný repo/retrieval domain seam, ne hromadný přepis `services.py` během T12/T14 integration |

Audit použil source AST, bounded explicit callsites a existující test scénáře; žádné Hub/model/import/build/test execution ani repository source edit. Při dalších změnách jsou tyto snapshot hashy historický důkaz, ne aktuální preimage licence.

Přesné benchmark příkazy/datasety a acceptance zůstávají v T02/T10/T11/T12/T15 původním kontraktu; nevymýšlet nový, jednodušší standard.

### Vlna E: integrovaná release acceptance a bezpečný úklid

- [ ] T19 synchronizuje INSTALL/UPDATE prompty, agent instrukce, model profily a skutečnou schema/feature dokumentaci.
- [ ] T20 vytvoří jeden final-root snapshot a aktuální T01–T21 tabulku s vlastníky, soubory, přesnými příkazy, exit/summary a zbývajícími blockers.
- [ ] Ve stejném invocation prostředí `python tools/surface_inventory.py --write-doc`, následně `--check`; check nesmí měnit document hash.
- [ ] Po integraci všech závislostí jediná úplná validace; failed tests diagnostikovat, nikoli přepsat očekávání nebo bez změny donekonečna opakovat.

```text
python tools/release_check.py
python -m compileall -q src mcp tools tests
python -m pytest -q
python tools/selftest.py
python tools/doctor.py
python tools/hubctl.py status
```

- [ ] Dodat clean-host install/update/restart/daemon-off runtime receipts a explicitně označit unavailable hardware/backend matrix.
- [ ] Release/tag/package až po splnění kritérií, ne před jejich doladěním. Nemaskovat neověřenou kvalitu názvem release.
- [ ] Teprve po potvrzené integraci archivovat nepotřebné completed chaty/worktrees s recoverable snapshotem; aktivní nebo unikátní dirty práci zachovat.
- [ ] Zbylé branches/stashes auditovat na unikátní změny proti finálnímu masteru; žádný blind merge/drop. `32fc` je nyní živý T09 checkout, nelze ho odstranit jen podle starého seznamu.

## Vykonané kroky této revize

- T20 root T11 příkaz `python -B -m pytest -q -p no:cacheprovider --tb=short -c pyproject.toml tests/test_t11_rag_project_policy.py tests/test_rag_read_bounds.py tests/test_t11_embedding_space_reindex.py tests/test_t11_rag_ingestion_contract.py`: **66 passed, 1 skipped in 23.22s**, exit 0; skip `T11_REAL_OLLAMA=1` nebyl zapnutý. Předchozí API/injection/Windows CRLF fixture chyby opravené podle skutečného root reader API a diskového `stat().st_size`, ne oslabením bounded-read kontraktu.
- Orchestrátor opravil zastaralé T21 verification/namespace odstavce v `docs/PROJECT_CONFIGURATION.md`; dva skutečně sesbírané TOML příklady prošly `tomllib` parsingem, scoped diff-check exit 0. Dokumentace odlišuje producer a consumer acceptance a přesný task criterion od neexistujícího globálního `required_commands` přepínače.

- T21 nový test-only patch integroval T20; orchestrátor prokázal skutečný root import a 2/2 pass.
- Přezkoumány tři nezávislé domény; subagenti dokončili a byli uzavřeni bez změn souborů.
- C1–C4/S1–S6/O1–O5 rozděleny do původních vlastníků; nevznikly duplicitní tasky.
- T01/T02/T03/T05/T06/T08/T09/T10/T11/T12/T14/T15/T16/T18/T19 obnoveni s konkrétními end-to-end acceptance, ne s pouhým status dotazem. Root T20 zůstává jediný integrátor/test-slot koordinátor.
- Po uživatelově upozornění na neaktivní chaty proběhl nový `list_threads`: původně aktivní jen orchestrátor a T20. Všech 20 neaktivních existujících Txx chatů dostalo samostatný zbývající slice, goal kontrolu a práci nezávislou na root slotu. Následný živý snapshot potvrdil **21/21 Txx chatů active**, bez nových chatů/worktrees. T21 produkční vlastnictví zůstává orchestrátorovi; starý T21 chat pomáhá jen test-only namespace acceptance. Tento activity snapshot není task completion receipt.
- Root není release-ready. Nové nálezy, původní T02 flake, final operation matrix a runtime receipts zůstávají otevřené.
- T20 aktuální step-back ledger uvádí memory run **11 passed, 2 failed**; další broad retry se nespouští. Scoped helper/store opravy jsou odděleně vlastněné.
- T08 helper opraven a cílená root create-memory regrese prošla **1 passed in 1.61s**; nepřepisuje historii 13-selector běhu ani nedokládá zbývající scoped delete.
- T13 O1/O3 patche jsou integrované; po úzké opravě integrační syntaxe prošly tři root regrese. T04 C4 patch je integrovaný a jeho tři root regrese prošly.

### Aktuální root receipt — nahrazuje starší pending stav C4

T20 integroval `t04-malformed-json-contract.patch`; T04 vlastník spustil pouze nové tři regrese:
`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t04_malformed_json_contract.py`
→ **3 passed in 1.84s**, exit 0, root HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
Root `client.py` SHA-256 `252F1781BE55DD2545DD7E3B21915F7A8AE20814DD2DB351E823124C6BFA1A19`.
Pouze C4 slice je přijat; whole T04 i MCP transport acceptance zůstávají otevřené.

T06 integroval opravný write-set hunk `E61B8537F53C861E4885EC9DF40E3B631BEBB41C5E372BEE43B820577A75D33A`.
`tests/test_command_rollback.py::test_run_uses_rollback_paths_as_write_set_without_rollback` → **1 passed**, root receipt vlastníka.
T05 potvrdil scoped-delete fixture RCA: chyběla identity; její oprava zachovává odmítnutí unscoped delete.
Původní T05 projection cleanup broad-catch patch byl zadržen; nová verze s atomickou transakcí byla root-aplikována T20.
První cleanup selector prošel, fault-injection selector původně selhal při setupu na neexistujícím `agent_memory.sqlite3` atributu.
Po test-only fixture opravě přes skutečný `sqlite3.connect` proběhl pouze rollback selector: **1 passed**, root HEAD nezměněn.
To neuzavírá celé D1: nově nalezené D3 rollback-double-fault a D4 correction/FTS atomicity ještě mají vlastní acceptance.

T19 O4 CLI patch SHA-256 `10094346520185d56945e2937c8b00b69691ac4cc36dc1636d1a306a6ed81260` integroval T20.
Vlastník spustil `python -m pytest tests/test_hubctl_mode.py::test_hubctl_reports_partial_mode_transition_failures`:
**3 parametrizované případy prošly**, root HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
Tento receipt neprokazuje plný CLI/offline ani dashboard JS behavior.

T09 nový `tests/test_t09_http_task_completion_persisted_receipts.py::test_http_task_complete_uses_persisted_tenant_scoped_receipts`
prošel **1 passed in 6.74s**, exit 0. Vlastník explicitně nastavil `PYTHONPATH=C:\Users\Adam\.local-ai-hub\src`,
`PYTHONDONTWRITEBYTECODE=1` a zavolal `pytest.main(['-q','-p','no:cacheprovider', ABS_TEST_SELECTOR])`;
vypsaný import `local_ai_hub.__file__` prokázal root. Jediný selector; nejde o celou T09 acceptance.

T13 první post-integration selector skončil **collection error**, nikoli behavior fail:
`IndentationError` v HTTP mode route. Orchestrátor po claimu odstranil pouze redundantní nested
`if mode == "gaming":` bez odsazeného těla; okolní revision guard a ostatní hunks zachované.
Parse HTTP/operational-mode/client a odpovídajících testů prošel. Následný přesný root příkaz:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_operational_mode.py::test_mode_invalid_utf8_fails_closed_and_can_recover tests/test_operational_mode.py::test_http_mode_skips_gaming_unload_after_later_resume tests/test_operational_mode.py::test_http_mode_routes_read_and_update_persisted_mode
```

→ **3 passed in 0.42s**, exit 0. Root HTTP SHA-256
`C619AE6297F9B99466304722E95455994BFFDF88258E32B1487FED247F159E15`.
O1/O3 slices jsou přijaté; celá T13 acceptance nikoli. Parse gate je od této revize povinná.

Následná syntax revize **239 dirty/untracked Python souborů** našla ještě inherited duplicate `finally`
v `tests/test_async_jobs_tasks.py:106`. Orchestrátor po scope claimu odstranil jen redundantní
dvouřádkový finalizer; původní `finally: manager.close()` i assertions zachované.
Po změně **239/239 AST parse OK**, bez importů aplikace a bytecode zápisů.
`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_async_jobs_tasks.py::test_async_batch_persists_sixteen_ordered_partial_outcomes`
→ **1 passed in 0.24s**, exit 0. Test SHA-256
`00362A891A9C912763D2BA878879E9BFCB6F0987C3FA242193AAB957F61804C8`.
Tento parse výsledek nepředstírá kompletní pytest, clean-host ani Python version matrix acceptance.

### Statická name-binding kontrola

Ruff není v PATH ani v aktivním Pythonu. Instalovaný Pyflakes použit jednou, bez zápisů/app importů:
`python -B -m pyflakes src tools tests mcp` (PowerShell filtr jen name-binding diagnostics), exit 1.
Zachyceno **16 name diagnostics** a 197 dalších lint diagnostics, nikoli 16 potvrzených produkčních bugů:

- 4 `mcp_server.StatusAction` literal-string false positives; veřejné chování ověřovat dispatch testy, ne měnit API kvůli parseru.
- 3 postponed annotation bindings: 2 `CommandBroker` v benchmarku (T15), 1 `Path` v T21 MCP route testu.
- 9 runtime branch/test names: `sqlite3` v rollback handleru (D3/T08), 7 chybějících `AgentEvent/threading/agent_tasks_module` použití ve stejné task-race regresi (T08), `pytest.skip` při nedostupném Node.js parseru (T17).

Orchestrátor doplnil pouze `from pathlib import Path` do `tests/test_mcp_repo_path_hints.py`; AST a diff-check prošly.
Jde o static/type-hint opravu, ne reprodukovaný runtime fail. Route behavior selector čeká T20 validation slot.
Ostatní nálezy mají scoped owner patch; tento lint run není zelená release acceptance ani důvod obecně vypínat lint pravidla.

### Obnovení vlastníků po zastavení chatů — 2026-10-01

Aktuální `list_threads` před obnovením potvrdil aktivní pouze T05, T09 a T20;
18 ostatních existujících task chatů bylo idle/notLoaded. Orchestrátor všem 18
poslal konkrétní nezávislý pokračovací scope a pokyn udržovat goal celého tasku.
Nevznikl nový task chat ani worktree. Následné skupinové `wait_threads`
snapshoty potvrdily všech 18 obnovených chatů active/inProgress; T19 v posledním
snapshotu ještě neměl commentary ani příkaz, takže jeho vykonanou práci zatím
nepotvrzujeme. Předchozí dvě odpovědi T19 byly pouze elipsy; dostal omezený
opravný resume se zvýšeným reasoning effort. Stav active není stav done.

Vlastnictví zachováno: T20 root integrace a serializovaná release verifikace;
T05 memory identity/HTTP memory větve; T06 broker; T08 async producer a memory
adoption; T09 receipt consumer; T12 model-start boundary; T13 mode consumer;
T14 nové adaptive context/pack; T21 helper pouze projektové adapter acceptance.
Zbylí vlastníci mají své původní domény a existující worktrees. Bez souběžných
root editací, širokých root testů, GPU a 100k benchmarků během release gates.

Main SOURCE REVIEW schválil čtyřsouborový misc lint delta
`E794D48F949DDCF8996FE0FF46F8BED8E593D84C5EECCAB2D798AE7E9B9C5B09`:
všechny čtyři aktuální root preimages se shodovaly, strict apply-check exit 0.
T20 následně ohlásil integraci; nový úplný root Pyflakes gate stále povinný.
T06 V7 zůstává historicky HOLD: fail-first prokázal falešné receipts při
`pytest -V` a `-o addopts=--collect-only`. V8
`B8925B9A3542164AA4FCF29B073DD35048E86E39BDD49E561812367C37191F60`
tyto dvě mezery opravuje; T20 ohlásil integraci a cílené root testy čekají.
T11 v3 a T08/T13 admission/consumer artifacty mají paralelní nezávislé source
review; jejich candidate výsledky nejsou důkaz úplné release acceptance.
Nový release commit, tag ani publikace tímto obnovením nebyly prokázány.

T19 následný bounded wait potvrdil třetí turn completed za 4,965 s s jedinou
odpovědí `…`, bez tool markeru. Toto není vykonaná práce. Orchestrátor další
identický resume neopakuje: dokumentační slice převzal subagent Dalton v témže
`t19-docs-rollout` worktree, výhradně INSTALL_PROMPT.md/UPDATE_PROMPT.md a nový
scoped parity test/handoff. T19 chat dostal zákaz souběžných editací těchto cest;
zůstává otevřený a jeho celá acceptance nedokončená. T20 byl o převzetí informován.

Nezávislé V3 RAG source review našlo dvě zbývající chyby již integrovaného rootu:
read-loop preemption vrací výsledek před publikací nejistých přečtení (P1);
incremental pending nevybírá suppressed soubory se stejnými metadaty (P2).
Main mechanismy potvrdil v cílených root slices. T11 připravuje minimální V4
fail-first opravy; T20 pokračuje ostatními gates, finální release zůstává HOLD
do skutečného ověření této delty. Cross-workspace legacy vector assertion musí
ověřit dekódovaný nový vektor a přesný embedding space, nikoli jen serializaci.

D3 root patch `6FB7F7D4988FA52783B447B58755167F92C671BEA3852FA58D5CB572A0704702` přijat T20:
`python -B -m pytest -q -p no:cacheprovider tests/test_agent_memory_t08_rollback_masking.py::test_delete_preserves_primary_fts_error_when_rollback_also_fails --tb=short`
**1 passed in 0.25s**, root HEAD nezměněn. Neopakovat selector bez další změny.

T16 revised root-current core/services/receipt artefakty jsou připravené (core `3C95A149…F0F3C05`,
services `716D18AA…F191E95`, receipts `9FAAECEF…447B9`). Candidate isolated regrese:
**13 passed, 1 skipped in 2.92s**; Windows symlink privilege skip není platformní proof.
Real broker valid/expired selector stále čeká společnou T06 seam integraci; staré r4 patche zůstávají quarantined.


## T20 continuation receipt — T02 slot and focused root regressions — 2026-10-01

Root HEAD remains 01df56605ccf484ebfe2808ac60d696c4e81dffc; no broad suite ran in this continuation. T02 confirmed no pytest or benchmark process remained and released its slot. T01's latest completed turn reports no tests run; the slot was assigned to T06 for one grouped, bounded Windows daemon integration run, including named-job stop-descendant and reused-PID-outside-job selectors. Hub transport failed before request dispatch; the one authorized native fallback exited 1 during collection because `local_ai_hub.project_config` is missing in `test_t06_project_validation_receipts.py` (pytest summary: 1 skipped in 0.87s, no pass count). No T06 Windows integration receipt; slot released.

- T13 gaming conversation release root selector: **1 passed in 5.15s** at HEAD 01df5660. Exact top-level conversation_release cancellation payload, success, mode=gaming, and cancel-before-unload ordering are asserted. Test SHA matches owner postimage 4334271F…1073DAB4. This is unit evidence only; no live Ollama/CUDA/VRAM proof.
- T16 root focused fencing/recovery set: **7 passed in 2.10s**; crash-after-patch-write selector **1 passed in 1.15s**. Exact run: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_work_fencing.py::test_commit_guard_revalidates_path_and_attempt_tokens_before_commit tests/test_work_fencing.py::test_commit_guard_rejects_expired_parent_attempt tests/test_work_fencing.py::test_expiry_reacquire_fences_stale_write_and_commit_without_side_effects tests/test_work_fencing.py::test_subprocess_attempt_supersession_rejects_stale_commit_with_monotonic_tokens tests/test_work_handoff_acceptance.py::test_process_crash_after_patch_write_recovers_from_persisted_journal tests/test_work_handoff_acceptance.py::test_recovery_requeues_after_crash_between_journal_clear_and_state_update`. Root pins: `work_fencing.py` C93C22210A479DA74A8ACD19134BAE2BC80979BDDD55E9E5FA08A50042ECBDD0; `test_work_fencing.py` 64115A4BC20C6F7375E39AA8C8BAD51AE24D2E1C3EAC28D96DCFEFC3DB88C9B6; `test_work_handoff_acceptance.py` 896EC91BF4F96AED5F0C11288053A8B135FB5B0DCACB533CE53163F3B4D7A5C4. Root recovery source already matched candidate (`_recover` SHA 01C0320257C53A10E4239E0DD08FAE8759524963BE959E1A69C9FD123D1D544C; `_ensure_workers` SHA A6D7C173F5B82876A68E4C7474148B2528C8B6A2919F2CEE39EF8FE8947B14A6). Diagnosis was candidate child-test fixture worker suppression, not a missing root source fix. Symlink privilege skip remains NOT TESTED.


## T20 continuation receipt — T06 root slot run — 2026-10-01

T02 found no remaining pytest/benchmark process and released the shared test slot. T01 then used it for its already-authorized operation rollback pair: **2 passed in 2.82s**, and released it. T06 received the next slot. Hub command transport failed before dispatch; its candidate worktree could not collect a receipt because local_ai_hub.project_config was unavailable there. After confirming no root pytest process, T20 ran one bounded root-current group using the equivalent selectors present in root; newer candidate-only node IDs and a candidate-only module were excluded. The run finished **22 passed, 1 failed in 25.17s**. Windows Job descendant stop, orphan-stop, PID-reuse, rollback/cache/auxiliary and existing project-validation receipt selectors passed. Sole failure: 	est_live_daemon_is_reconciled_after_broker_restart, where stop_daemon() returned success=False. This preserves the recovered-live stop blocker. The slot is released; no further pytest work is underway.


T02 follow-up status from its owner: candidate queue/scratch two-selector reproduction **2 passed in 25.89s** at candidate HEAD 7b0868ac964fd14e160001024e6e0ecaaf4e9db. This does not replace the interrupted four-case matrix or establish a paired root baseline; plan_grade remains false and T02 goal remains blocked. No T02 process is running.


T15 owner checkpoint: benchmark command-broker/contract tests **26 passed in 2.97s**. Paired benchmark remains unrun: prior 7-pair probe reported cceptance=false, source pins still differ, comparable baseline absent, and T20 has not explicitly allocated a CPU slot. Resource gate remains blocked; do not reserve hardware time until source/baseline pins align.


T09 owner/provenance checkpoint: task thread remained idle after authorized follow-up and returned no T09 acceptance receipt. Assigned worktree snapshot HEAD 968443549f2a68d17df26689cd49874d1ce400de, 45 dirty paths, 41 tracked diff files (+4463/-596), without clear separation of T09-owned changes from inherited Agent OS/T08 hunks. Root unchanged; no patch integrated. Need exact ownership manifest and SHA pins before integration.


## T20 continuation receipt — T05 selector blocker — 2026-10-02

T05 owner ran one bounded candidate invocation after slot release: **1 failed, 1 passed in 0.51s**. The unauthorized-identity regression passed. Adoption selector stopped during setup because candidate TaskStore lacks set_memory_adoption; deletion assertion was not reached. No retry/bridge. Root source/test pins unchanged. Patch 	05-root-current-memory-delete-identity-v2.patch, SHA-256 292039408CE5DA07C5C384F7C535B6B0D38996A33E0F1A0F106D58B388793147; checkpoint 	05-root-current-memory-delete-identity-v8.json, SHA-256 C11F1044925C0460FA10C6DE99004799A9D3238901DA3D6193C934FC30A6E50D. Root acceptance remains unverified.


T06 follow-up candidate evidence: 	est_named_daemon_job_survives_restart_and_stops_descendants failed **1/1 in 1.03s**; daemon_status.success=False at test line 1111. Owner is diagnosing that single selector. Candidate path cited by run differs from registered worktree path (	06-safe-commands versus 57e3); no integration until canonical worktree and owned hashes are confirmed.

T10 path-hints evidence: candidate pair 	ests/test_t10_repo_search_path_hints.py tests/test_project_path_hints.py **20 passed in 1.42s**. Root already contains first test file untracked, SHA-256 2155D19CE642ADA864EE102660EB02EDDA098366409F2F0D3A905B7ED10C17E4; this is not root execution evidence. No T21-owned source changed.


## T20 continuation receipt — T04 owner closeout — 2026-10-02

Verified owner receipt 	04-end-to-end-acceptance-closeout-2026-10-01-v2.md, SHA-256  646A75C775ADD0E81F58E25B54935DFF2E5339D91B74065EA3B247AB0008F4E. Receipt records root HEAD  1df56605ccf484ebfe2808ac60d696c4e81dffc and **120 passed in 63.70s** for T04 client/API/conversation closeout. Current root still at that HEAD. All eight listed source/test SHA pins match current root. This corroborates the owner result; T20 did not rerun the 120-test batch. T09 acceptance remains separate and open.

T02 RCA addendum: historical 25-attempt receipt `codex-t02-flake-20260930T201729-b78b0be9.json` preserves only 3 attempts. Attempt 2 proves the specific delayed-dispatch cancellation race: expected `cancelled`, observed `running`; old `async_jobs.py` RED **5.106s**, candidate `dispatch_not_before` GREEN **2.392s**. Attempts 1 and 3 observed live benchmark workers after manager close and scratch cleanup failure. Worker job identity was not correlated to probe payload; downstream linkage remains hypothesis. Do not infer failure rate from incomplete 25-attempt target.

T06 follow-up after removing `KILL_ON_JOB_CLOSE`: candidate-only selector failed **1/1 in 1.22s**. Diagnostic identified missing `task_id` in test call; policy refusal was expected. Guard remains. T06 adjusts owned test to pass `daemon-test`, then runs one focused selector. Root restart-stop batch remains **22 passed, 1 failed**; root test source has not yet been corrected. Candidate worktree identity still needs confirmation before integration.

T06 final candidate checkpoint for this slot: after removing kill-on-close and updating obsolete fake-helper references, the sole named-job restart/descendant selector still failed (**1 failed in 1.22s**, exit 1) after second broker recovery. Exact command is recorded above. T06 reports changes only in its owned commands.py, daemon test, and two handoff documents; root untouched. No further pytest run or candidate integration. T06 remains open.


## T20 continuation receipt — T03 root-current patch preimages — 2026-10-02

Verified root HEAD  1df56605ccf484ebfe2808ac60d696c4e81dffc. Patch T03-root-current-full-status-output-20261001.patch SHA-256 A5CA8543CA462B67D12C75343A794E23B1B225ADC796B2C44965125C572F04E6; apply-check passes. Current root preimages match: operation_contracts.py EA9250A37DC21286B6D194CB3AC3B96BC62356ECDE5C8094D3A4EEE7F1B4F330, 	est_operation_contracts.py B0D2CCE62F5F3FB0BABB145A8933E8254236D3D61DB31ABE57008FBFCEA28AAF. Patch only adds 50 lines per file for typed status outputs and regression coverage. Not applied: prior user-approved T03 scope named sync_jobs.py and two T13 tests; this two-file patch falls outside that explicit boundary. Root remains unchanged; root test pending approval and available slot.


T05 root test-only patch applied after exact preimage verification; only 	ests/test_agent_task_memory_adoption.py and new 	ests/test_memory_delete_identity_contract.py changed. Patch SHA-256 6DDE50EAB5A824A67ED3C1CA5A3D83B9C98E57323E8210E1E0179F5521102A4B. Root postimages adoption test B85E72F40C2EFE491AF08383C81D7FEDF03689096F42F630B7BA3DB71EF92847, identity test 8ABD2AF37787D7747F9AF58C75A4347EFD1C41537109A05313201F84FC8187E2. Candidate bridge selectors passed 2/2 in 0.57s; root run remains pending. No production files changed.


T09 producer-to-completion red receipt from assigned worktree: test 	est_command_execution_receipts_are_persisted_and_gate_task_completion failed 1/1 in 0.84s after real command exit 0; broker omitted erification_receipt with warning command succeeded but durable verification evidence was unavailable. Root cause reported VerificationStoreIntegrationError: state store has no ordered event publication API in T08-owned gent_events.py. New test SHA-256 F3A87ED0F10965998C0874F18BFDCF6D9B28AD9A9DB1C97DC483F7D312CA4B82. T09 changed only this test candidate; no root integration. Independent lease/handoff/rule selectors 56 passed, 9 skipped; four rule selectors passed, one blocked by same API.


T08/T09 dependency: T09 producer fails receipt persistence because gent_events.py lacks ordered-event publication API. T08 is active on its owned repair; root remains unchanged until owner handoff and exact preimage review.

T06 root-cause update: diagnostic returned `daemon belongs to a different or unknown task` because the restart/descendant test called `stop_daemon()` without its owning `task_id`. Keep policy guard. T06 updates only the owned test call to pass `daemon-test`, then runs one focused selector. Root fix/integration remains pending candidate receipt and exact worktree verification.

T05 cleanup variant v4 is not applied over root v3: owner reports v4 removes only one blank-line formatting hunk; nonblank test lines match, identity test SHA is unchanged. Root remains at v3 postimages (	est_agent_task_memory_adoption.py B85E72F40C2EFE491AF08383C81D7FEDF03689096F42F630B7BA3DB71EF92847; new identity test 8ABD2AF37787D7747F9AF58C75A4347EFD1C41537109A05313201F84FC8187E2). V4 receipt was not rerun; no reason to overwrite root v3.


T06 latest diagnostic: registry/duplicate fail-closed paths behaved correctly; recovery refusal came from missing task owner in test. A further process_identity() is None assertion was invalid for a terminated leader whose Popen handle remains open; T06 will assert process completion via poll(). This is an owned test correction, not policy weakening. Single selector retest pending; root untouched.


T10 root path-hints test reconciliation: root file 	ests/test_t10_repo_search_path_hints.py already exists untracked at SHA-256 2155D19CE642ADA864EE102660EB02EDDA098366409F2F0D3A905B7ED10C17E4. Required deny/exclude/outside-root function segment SHA matches candidate FF23E80AF25D33A54583B7BBB581CBF44BE9E744689F03234BA1492C2C65B4CE; root copy includes extra default-scope positive fixture. Candidate selector -k cannot_restore passed 1 passed, 3 deselected in 0.37s. No patch needed; do not copy stale candidate file SHA  6ED8143F5E6B62A3D9D945C6A451163398C3AEC48332923507885BA525C4E90. Root-current selector still awaits slot.


## T20 continuation receipt — T05 root selectors and owner deltas — 2026-10-02

After T06 candidate slot release, T20 ran the two T05 root selectors plus one existing T06 restart selector in one bounded command. Result: **2 passed, 1 failed in 1.04s**. T05 identity/delete and provenance selectors both passed against root v3 tests. T06 root selector failed at stop_daemon(..., task_id=...) because root CommandBroker.stop_daemon has no task_id keyword; I reverted those temporary test edits, restoring the exact preimage SHA 66065F38B3436CC6742BF5B771F0C675C1AA2288B3C9296028CC670CA451C7E5. T06 candidate supports the keyword; its root-current API patch is not yet available. Root has no lingering T06 test edits.

T01 owner-reported candidate run: six acceptance modules 64/64, surface inventory 687/687, coverage_matches=true across 642 rows. Receipt T01-operation-acceptance-run-20261002.md, SHA-256 D30CD1822FF0D295F7CE32289A49E36CEBDA552B3B2B79DC737EB0497323F20; source pins pending handoff, no root T01 GREEN claim.

T12 owner-reported candidate gaming/model-inventory selectors 25/25 in 1.37s; this does not prove T13 CUDA concurrency or physical VRAM lifecycle.

T08 owner-reported blackboard trust-label candidate selector 1/1 in 1.71s, patch unintegrated; preserve pending user approval. Candidate patch SHA  310DF3732A1F53BDA346B7DAB1D8BDE51AF9D58D9C019FB4536893B8B984B66.


T10 root path-hint selector remains pending while T19 owns the shared CPU slot. No T10 root test was started. Root test SHA and function-segment parity remain as recorded above.

T19 latest status: owner is running the full offline regression set, then SDK smoke against updated package snapshot. The observed active Python pytest process belongs to C:\Users\Adam\.codex\worktrees\t19-docs-rollout\.local-ai-hub; T20 did not launch another test.


T15 fallback candidate selector receipt: paired-benchmark contract plus root-parity tests **17 passed in 5.32s** at detached candidate HEAD 824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11. No benchmark ran and root was untouched. Source/root dirty parity remains to be pinned; measured paired run still blocked on baseline and exclusive CPU slot.

## T20 continuation receipt — released slots and root recheck — 2026-10-02

T02 confirmed `NO_T02_BENCHMARK_PROCESS`; its CPU benchmark slot is released to T15. T15 was told to wait for T20 to pin a clean integrated baseline/candidate revision before starting. T19 also confirmed no root pytest process; its test slot is free.

T20 reran only T19's two remaining root selectors after confirming no root pytest process:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_release_hardening.py::test_mcp_explicit_short_deadline_is_honored tests/test_release_hardening.py::test_release_gate_allows_the_live_installed_checkout
1 passed, 1 failed in 8.36s
```

The MCP deadline selector passed. The live-checkout release gate first failed because root `defaults.toml` and packaged `src/local_ai_hub/defaults.toml` differed by the single T10-owned setting `python_fallback_max_files = 8000 # independent file-count budget; ripgrep has its own timeout`. T10 confirmed the setting is intentional and supplied root-current patch SHA `4731B4DE2E68093018B136A96266FF656C569F3520386DD5D3899EB9FCD02665`. T20 applied that one-line patch. Both files now hash to `418B62992343D074C33BB6DF7D2E8139F2B0DDCD6B47CDB1A4E94971A502D57B`. T10's exact post-fix selector passed **1/1 in 7.09s**. `build/` and `dist/` were preserved.

T06 core, task-id adapters, and T07 v9 are integrated in root working tree after exact preimage checks; all six affected files match T06's combined scratch simulation. T06's initial focused root selectors failed **4/4**. Read-only diagnosis found missing task_id persistence/recovery and stale fixtures. T06 v2 patch `T06-root-daemon-task-identity.patch`, SHA-256 `42CB9B8EC380B966FBF43BD538125417F1A29C53765E4230E227B189F174B3F9`, adds task_id persistence, validated Windows named Job reopen, and preserves root POSIX live group stop while recovered POSIX remains fail-closed. Candidate selectors passed **5, skipped 1**. T20 applied v2 after exact root preimage + strict apply-check. The six root selectors initially returned **3 failed, 2 teardown errors, 1 skipped**. Failures: v2 accidentally removed `@staticmethod` from `_flush_daemon_log`, causing watcher teardown `TypeError`; HTTP adapter fixture lacked active operational-mode config. T06 follow-up `T06-root-daemon-task-identity-followup.patch`, SHA-256 `97D25CC1C2F16712D291C5ABB7B27D8AEC7571F30E008798998EE28F41DF18BD`, restores decorator and supplies active-mode fixture without weakening production gate. Candidate correction selectors passed 3/3. T20 applied exact follow-up after root preimage + strict apply-check. New root postimages: `commands.py` SHA `845348F2E362852561AE2EBB1B3F5458C8915E0134B1EC884F47356132B9FECB`; daemon test SHA `50940A53F3F232A550D1A21406ACC6677877D6AE0F889113ED117A59DAE5DB48`. The six root selectors now pass **5 passed, 1 skipped in 1.59s**; skip is POSIX process-group lifecycle on Windows. T07's root run completed **115 passed, 3 failed**; read-only compare finds `_send` same in root/candidate and three old assertions omit `request_id`. T07 root-current test-only patch `2026-10-02-t07-root-current-request-id-tests-v1.patch`, SHA-256 `f1cb0795fdd1713299ea31268bb7ecc56e443242e38f26e419d4cac6613d638f`, passed strict apply-check against test preimage `1027AF4141D6AAB1C79448BCFBFEBF82C5E0CDF4D488A9443EFD35E0F27C8F68` and is integrated. Root postimage `tests/test_mutation_replay.py` SHA-256 is `9B72B7D7B51AE288FC57A126F991CCD437EA41E50D8A2C7701241F86F8673B19`. Candidate affected selectors passed **3/3 in 0.99s** and full targeted suite **128/128 in 12.14s**. T07 root selectors after assertions passed **118/118 in 10.68s**. T08's provider patch does not apply because current root working diff already contains the ordered-publication additions; T08 made no root change, and T09 consumer acceptance remains separate. T18's telemetry patch was integrated after its strict root apply-check passed. Root `telemetry.py` postimage SHA-256 is `59A8F461CCF11C09526624EDEBD4D4FD99FB314935BE893BBFCE052CAF09281B`; new test SHA-256 is `D1FFDFB7BDB48870286B697AC374F4C9E18B9F5ACFBAB627ABD6DFF3394A8A13`. T18's sole root test file passed **1/1 in 1.21s**; no broader suite was rerun.

T02's follow-up three-selector reproduction passed **3/3 in 30.01s** in its candidate without a benchmark. It confirms the fixed sequence leaves no scratch leak for the next guard, but the original attempts 1/3 still lack DB snapshots, so their linkage remains a hypothesis and T02 stays blocked. T15's preflight confirms its benchmark remains unrun; the T02 CPU slot is available, but no clean integrated baseline/candidate commit or source pins exist, so T20 has not assigned a benchmark window.

T01 row-map delta: **0 new rows closed; 0/446 root GREEN**. Two rows have candidate-only selectors (`op-28d63e90525c` under T08; `op-65970ac00a0a` under T13/T17); their integrated root selectors remain pending. Other 444 rows still lack exact selector mapping. T09 consumer patch remains blocked pending direct user instruction; T09 did not change source.

T02 directly confirmed that it will not reserve or run another benchmark; the CPU benchmark slot is released for T15. This does not authorize a benchmark window: T15 still lacks aligned clean integrated baseline/candidate commits and source pins. T05's bounded candidate acceptance run completed **45 passed, 9 failed**; failed nodes were `test_http_global_memory_identity_ignores_transport_tenant_but_keeps_scope` (expected 200, got 400), seven migration/schema selectors rejected by the injected root bridge as unsupported `agent_incidents` table, and one new evidence-id test with missing repository scope. T05 corrected its owned fixture; patch v3 `t05-evidence-ids-shape-v3.patch` SHA-256 `F681BD90CADACC2AB9997C68F2BA5E6BB7DAD21F7DAEAFEB846FE0C50B32BCAD` passed reverse apply-check, and two shape selectors passed **2/2 in 0.48s**. Static RCA says HTTP 400 was test-owned: `monkeypatch.undo()` removed a fake `project_config`, so final delete returned 400; test-only patch v4 restores `app.agent_memory.delete`, SHA-256 `0720ED6A73E1B11486BC561F7BD686EB2B3C85B1E414F4C3E5E003BD3A448DF2`, reverse-check passed. The unique HTTP selector then passed **1/1 in 5.56s** with candidate `agent_memory.py` SHA `784116FF…AC73E` and root `agent_events.py` SHA `30AB4485…6B44822`; receipt v3 SHA `E03725B1…A1FC5E`. T05 made no root edits. The combined candidate run is not acceptance; seven root/candidate schema mismatch failures remain and have been handed to T08 for diagnosis.

After T06's compatible root follow-up, the bounded T07 root-current selector set was rerun at HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mutation_replay.py tests/test_client_transport.py tests/test_command_replay_policy.py` — **118 passed in 11.04s**, exit 0. Post-run process check found no remaining pytest process. This is targeted T07 evidence only, not a full release suite.

T01 produced a fresh candidate-only inventory evidence builder and run receipt; root stayed untouched. Builder SHA changed `DA8AFFB3…B506BF` → `E7491E6F…240305`; new evidence CSV/JSON/run note hashes are `01526A8D…20EAB`, `CA949D33…2C8D`, and `9EAFD24F…9EFB68`. The run used only unique selectors from the 642-row JSON output: **63 passed in 25.96s**, exit 0. Candidate map links 138 behavioral tests and 68 operations to six focused candidate files, with 63 unique selectors. The historical 446-row gap list still has 444 exact-link gaps; root GREEN remains **0**, no rows closed. Runtime/external and integrated-root proof remain open.

T01's follow-up node-map extension remains candidate/handoff-only. Builder patch SHA `E7491E6F…240305` → `4229AC99…9EF7FD5`; 445 historical IDs are present in the current 642-operation inventory, one ID is absent (`op-fa58799428e7`, retired `local_ai_task::cancel`), and 445 exact metadata-only parametrized selectors were emitted with 0 duplicate IDs or keys. The unique-map report JSON SHA is `2FBAFD6F…5EA19F`; gap/node map JSON SHA `4578DB6A…104D1`. **444 unique operations still lack behavior selectors**; T08 and T13/T17 candidate receipts do not close root rows. Metadata selector links are not behavior proof. Root GREEN stays **0**; T01 made no root edits or tests.

T01's root acceptance overlay contained 61 of its 63 unique behavior selectors; two T01-owned MCP coord node IDs are absent from current root and were not replaced. Present-list SHA `88B8B98E7DA23DA49F17032C3594ABF7F052F1A7241B3A23278BC3938DEAD1EC`; run at HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc` returned **60 passed, 1 failed in 31.48s**. The sole failure `test_http_get_agent_state_events_forwards_stream_cursor_and_limit` spies on `AgentStateStore.events`, while the current GET route calls `AgentStateStore.event_page`; expected params remain stream `stream-31`, after sequence 4, limit 9. T18's read-only event-page contract receipt `T18-root-current-event-page-readonly-20261001-v2.md` SHA `2B79C239F6DCF439535B58BBC5F55916FFFD4AB761467E3DC032B2A9DBC3AD0A` confirms the route-page API and 1–100 bounded limit. RCA: stale T01 test spy, not a proven route defect. T01 is preparing a test-only spy correction; root code and expectations remain unchanged, and only the failed selector may rerun after slot release. Post-run process count was 0; independent root hash check confirms `client.py` remains `5518706E…B0D056`. The 60 passes do not close inventory rows; root GREEN remains 0.

T03/T21 path-hints validation used existing root source; no patch was applied. At HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`, `mcp_server.py` SHA-256 `5FF372AF25D78EDBB09B7F6D3AB6ECF5F8C9C593247F38A7B01C2CFF8E7929CE`, `operation_contracts.py` `EA9250A37DC21286B6D194CB3AC3B96BC62356ECDE5C8094D3A4EEE7F1B4F330`, and `tests/test_mcp_repo_path_hints.py` `EF7B66D95D3E011CE28AF3D90668F19417DEECFE0D55B9D51BFFF1B665EC2AF6`. With no pytest process active, command `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mcp_repo_path_hints.py::test_repo_search_forwards_legacy_path_before_typed_path_hints tests/test_mcp_repo_path_hints.py::test_api_search_route_consumes_t03_hint_and_returns_repository_hit tests/test_mcp_live_wire_schema.py::test_stdio_handshake_publishes_all_registry_input_and_output_schemas tests/test_mcp_compact_transport.py::test_local_ai_repo_non_context_actions_ignore_guard_fields` passed **4/4 in 5.86s**. Post-run process check found no pytest process. This proves the bounded root call chain at these selectors; whole `mcp_server.py` dirty diff remains shared, with T13/T21 ownership not inferred from this run.

T05's unique HTTP identity selector also passed on current root: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_agent_memory_http_identity.py::test_http_global_memory_identity_ignores_transport_tenant_but_keeps_scope` — **1 passed in 7.00s**, exit 0, HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`; post-run process count 0. Root `agent_memory.py` SHA `C68A8C70386BA5155C23D48AE23735E3E0344C3E72F021F0D76DEF708AF2B838`; test SHA `FB721E8CAF6E2394A73DED286D6EDAA64DE1BD891DE915BBA569521B0269E321`. T05 v4 patch was not applied: its 3-file preimage check failed on already-different root source/test content, and the root HTTP fixture already restores `app.agent_memory.delete`. This root selector proves only this HTTP behavior; seven migration/schema failures remain.

T01's root events-route fixture correction was applied after exact preimage and patch-SHA checks; only `tests/test_http_route_operation_acceptance.py` changed. The correction spies on current `AgentStateStore.event_page` while preserving stream/cursor/limit assertions. At the unchanged root HEAD, the single selector `tests/test_http_route_operation_acceptance.py::test_http_get_agent_state_events_forwards_stream_cursor_and_limit` passed **1/1 in 4.88s**, exit 0. Patched test SHA is `BD01B4DBE8A0DBA1AF8B1171ED5F15B9ED1888A06AF05A7C7BC9A9CC84DCF679`; post-run pytest process count 0 and scoped `git diff --check` passed. The earlier 60/61 batch is not being repeated, and T01's two absent selectors remain unproven.

T02 confirmed its test/benchmark slot is released. Its diagnostic lifecycle selector passed **1/1 in 0.32s**; benchmark and full quality matrix remain incomplete. No benchmark was run for this slot release.

T14 defaults root check found both `defaults.toml` files already at the candidate postimage SHA `418B62992343D074C33BB6DF7D2E8139F2B0DDCD6B47CDB1A4E94971A502D57B`; the candidate patch was not applied because its preimage check failed at `defaults.toml:470`. At HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`, root selector `tests/test_rollout_controls.py::test_defaults_enable_adoption_features` passed **1/1 in 3.07s**. Test file SHA `13EA49A7EDF80A55DF4CB32EFCE0C2367C8444A3CB15805ABCF4AB2044C8F7B8`; post-run pytest count 0. This verifies only the defaults selector; wider T14 acceptance remains open.

T08/T05 migration integration is now green on current root. Applied only T08's alternate hash for the exact T05 legacy `agent_incidents` schema and its new migration test module after strict apply-checks; T08 selector passed **1/1 in 0.37s**. The seven T05 migration selectors previously blocked by that schema bridge then passed **7/7 in 3.25s**. Root postimages: `agent_events.py` SHA `09B31135FF2493F2B8E236074DBF7FB2C9CC274BC2DD5841ECDDD07F974ADA5A`, `test_agent_t08_migration_recovery.py` SHA `7218D318223FCEC6705B1514EB0820A4B88FB635CAB21C1BF35AFBE259022E73`, and `test_t05_agent_state_migrations.py` SHA `4FC21F1A7BFCC6D477104D9BABCE78F5DCAE8113B46A4B5195EC0E0F79BB2977`. This closes the seven root migration failures only; T05 durable-store matrix remains open.

T02 root queue-race selector `tests/test_surface_benchmarks.py::test_queue_admission_probe_cancels_before_delayed_dispatch_registration_race` passed **1/1 in 0.37s**. Root source already had the dispatch guard; no source patch applied. T02 diagnostic patch, benchmark, and full quality matrix remain open.

T05 root-current memory normalization patch `F7B2F7761E72755A8AB7ACF889DEAF02CB7AD413C15E0AC1CC287A87344DCB19` was applied after exact preimage checks. It validates `evidence_ids` as a sequence of strings in record and row deserialization. Six root identity/evidence selectors passed **6/6 in 1.87s**. One first attempt used the candidate-only selector name `test_scoped_memory_delete_requires_matching_tenant`; pytest collected no tests (exit 4). Root's equivalent is `test_scoped_memory_delete_still_enforces_tenant`; the corrected six-selector run passed. Root postimages: `agent_memory.py` SHA `38A9A86C3E9C6EF90BAF1CF7F2CE12DB32DA8D1DDCDB4288512942C39FEBEA73`, `test_agent_memory.py` SHA `4C15BC64C5D67735DA1C061CD392D29E9F40F63B8AC0FF683070334474649F3E`. No active pytest process remains. T05 broader durable-store acceptance stays open.

T01 GET tasks coverage patch `6FA93F13C9EE2FAD5DC36450EFC5613C1EFE27AFED01B3E8224A65B35DEE6BE9` was applied to the exact root test preimage. First root selector run failed **1/1 in 4.21s** because the new test spy omitted the current route's `query` keyword; the route passes `query=""`. Corrected only the test spy/assertion to include `query`; selector `tests/test_http_route_operation_acceptance.py::test_http_get_agent_state_tasks_forwards_filters_and_serializes` then passed **1/1 in 4.54s**. Test SHA is `B314578642480CDD0B896D863EABFE1730637BC61D5C1C2A0D05DA0BA7D9FCAF`; no pytest process remains. T01 inventory remains open.

T03 typed output patch `A5CA8543CA462B67D12C75343A794E23B1B225ADC796B2C44965125C572F04E6` integrated only `local_ai_status.full` and `agent_state` output schemas plus their test. Root selector passed **1/1 in 2.63s**; broader T03 output/transport parity and measured token/error comparison remain open.

T04 progress is candidate-only, root untouched: API/conversation/query/inventory **40 passed in 49.27s**; daemon-off MCP stdio handshake/cold-start/timeout/no-orphan **2 passed in 15.31s**; startup/timeout **3 passed, 9 deselected in 3.12s**; unchanged full candidate suite **133 passed in 27.74s**. Root wrapper selector remains unverified: broker returned `request_not_sent` without `terminal=true`/`retryable=false`, so native fallback was not run.

T16 progress is candidate-only, root untouched: junction rollback/rooted-scope **2 passed in 0.22s** and cross-process lease/recovery/write-fencing **7 passed in 7.04s**. Windows symlink creation returned `WinError 1314`; symbolic-link acceptance remains **NOT TESTED**.

T12 candidate-only: llama.cpp schema/transport **2 tests + 10 subtests passed in 0.16s**; synthetic model-free harness exited 0 over four maps, with `live_inference=false`, `quality=not_measured`, and no VRAM claim. Live backend/CUDA/VRAM and T02 baseline remain blockers.

T08 ordered-event publication: root already had the provider method; only the test-case patch `1205FFAF1CCDB242EAEB3EA88711EB8992335734B68A7C5A06D42530BE9E0348` was applied. Root selector passed **1/1 in 0.29s**; T08 candidate receipt-writer case passed **1/1 in 0.21s**. Root test postimage SHA `23472C0021DD415622882E2942F6DC99C153632D93CCA5728808AAC402F17BF9`; broader T08 acceptance remains open.

T09 producer-to-receipt root proof: its exact candidate selector name is absent from root, so that attempt collected no tests (exit 4). Root-equivalent `tests/test_t09_command_execution_completion.py::test_actual_broker_receipt_completes_agent_task` passed **1/1 in 1.71s**, exercising real broker receipt persistence, evidence/hash lookup, and task completion. Root `agent_verification.py` SHA `FB477438FF110AB80FE6F2D486FFA5D87AAB1A855735FCD94592F8080EAF0017`; test module SHA `E90EA9C7EDAEE6DC64203FE30FAE2706269C4028135B68E5D023492EDCF5F91F`.

T01's missing `local_ai_coord` task rollback persistence and feature-disabled predispatch selectors passed candidate-only **2/2 in 2.56s**. Root unchanged; patch `051F5066BC3B1589A78EE1CBE20DD6ED91069712143F67E983061918DA2D0235` remains apply-check-only and root GREEN inventory stays 0.

T20 release update (2026-10-02): T03 operational-mode classifier root-current patch passed exact preimage and apply checks; root-current equivalent `tests/test_mcp_contract_dispatch.py::test_mcp_command_run_is_gated_as_heavy_and_repo_map_read_stays_lightweight` passed **1/1 in 2.40s**. Root postimages: `mcp_server.py` SHA `2A78162B9B5157076ECF3281968369501EF38E451BB8AA01CE9E6FFE9A49C577`; test SHA `C555C2D8205EF9537EBED997D1510A31617EEFB208B4B07F28CA4B2C13187352`. Candidate selector name differs from root; only the root-equivalent selector is counted.

T21 path-hint boundary test patch added only its owned test hunk after root apply-check; `tests/test_project_path_hints.py::test_path_hint_rejects_paths_over_t03_contract_limit` passed **1/1 in 0.14s**. Root postimage SHA `07D00BBA1E0963645DDB3C5970E1C9FC9763D90F969725C0211E14A83EB8ADC4`.

T02 owns exclusive CPU slot `T02-CPU-20261002-01`. Benchmark remains unrun pending T15's exact runner/manifest and baseline source pin. Any previously sent whole-tree digest is invalidated by these plan edits; recapture before launch.


T20 architecture acceptance and owner map (2026-10-02)

| Acceptance area | Existing owner(s) | Verified state and remaining gate |
| --- | --- | --- |
| In-process MCP lifecycle, cold start, retry/timeout and no-orphan behavior | T04 | Candidate focused/full receipts: 40 pass; 2 pass for daemon-off handshake/cold-start/timeout/no-orphan; 133 pass full candidate. Root wrapper lacks a successful receipt (`request_not_sent` had no terminal/retryable evidence). |
| Durable DB separation, migration, tenant isolation and receipt consumer/provider API | T05, T08, T09 | T05 root migration selectors 7/7 and identity/evidence selectors 6/6; candidate tenant suite 15/15. T08 candidate batch 57 pass/2 deselected; root provider/consumer equivalent selectors passed. T09 latest candidate has 1 failure: expected `AgentStateStore.ordered_event_publication(con)` is missing; reconcile API between T08 provider and T09 consumer before claiming complete. |
| Typed action schemas and transport envelopes | T03 | Root status/agent-state schema selector 1/1 and operational-mode classifier selector 1/1. Broader transport parity and measured schema-token/error comparison remain open. |
| Worktree/write-set rollback and daemon ownership | T06, T16 | T16 candidate 79 pass, 1 skipped, 1 deselected; symlink/Windows acceptance remains open. T06 Windows race candidate evidence exists; root integration/selector remains pending exact patch. |
| Measured modular decomposition and scope reduction | T01, T15 | T01 inventory now covers 52/446 historical gap rows, 51 targeted, 120 unique selectors; 53 new mocked coord tests are not run and root inventory remains open. T15 runner candidate receipts exist, but candidate `commands.py` differs from root and immutable baseline/candidate/harness pins are not ready. |
| VRAM/model lifecycle and performance | T02, T12 | T02 has exclusive slot `T02-CPU-20261002-01`; no benchmark run yet pending T15 pins/command. T12 routing/prompt/token suite 66 pass + 20 subtests; live CUDA/VRAM remains unverified. |
| RAG latency acceptance | T11 | Candidate contract batch 177 pass, 3 skipped; measured p95 972.658 ms and 1698.727 ms exceed 750 ms gate. Performance remains RED. |
| Live model/runtime quality and release readiness | T17, T19 | T17 21 focused tests pass with no source edits; runtime, toolbar, WER and live quality remain unverified. T19 candidate 70 pass/1 skip and smoke 2 pass; clean-host/runtime gates remain open. |
| `/api/context/pack` scope | agent-2 | Remains owned by agent-2; no edits or reassignment. |

No new tasks or chats created; reuse listed owners for remaining gates.


Architecture audit detail: open proof required (2026-10-02)

- **Daemon-independent MCP (T03/T04):** current `HubClient.ensure_server` autostart and wire tests prove owned-daemon cold start, not an in-process Services path. Acceptance remains open until daemon-off real MCP `initialize` plus `tools/call` proves bounded owned-child lifecycle/error/shutdown or a real in-process branch.
- **Durable DB vs disposable cache (T05/T08):** source separates `agent_state.sqlite3` durable state from cache, but broad crash/rebuild proof remains open. Acceptance needs task/event/memory/receipt creation, restart, cache corruption/rebuild, proof durable rows survive, and proof DB paths differ.
- **Typed MCP outputs (T01/T03):** current output schema is a shared open envelope; handshake comparison against the same generic helper is insufficient. Acceptance needs action-discriminated output schemas for all eight public tools, invalid combinations rejected before side effects, and actual wire-schema parity.

These gates refine existing owner assignments; no new task/chat created and `/api/context/pack` remains with agent-2.


Architecture audit: transaction and hardware proof gates (2026-10-02)

- **Mutation/write-set isolation (T06/T15/T16/T20):** require a unified end-to-end acceptance across command run, daemon, repair and network mutation surfaces. Prove undeclared outputs reject, timeout/cancel and concurrent edits are handled, source remains unchanged, and crash/restart rollback restores declared paths while preserving untracked and foreign edits. Existing journal/postimage tests are not full task-write-set-to-transaction proof; Windows symlink acceptance remains **NOT TESTED**.
- **Physical VRAM lifecycle (T02/T12/T20):** source scheduler and fake-runtime tests do not prove reclaimed hardware memory. Require repeated paired active/gaming/maintenance runs on target hardware recording preprocessing admission, queue, model load/switch, inference, end-to-end p50/p95 latency, and VRAM before/after, including whether physical VRAM was reclaimed. Until those receipts exist, physical lifecycle stays **OPEN**.


T12/T21 project-model integration update (2026-10-02): the newly uncovered candidate `tests/test_t12_project_model_consumer.py` ran **2 failed, 4 passed, 5 skipped in 0.58s**. Both failures trace to missing `src/local_ai_hub/project_config.py`; `services._resolve_local_task_project` catches the import failure and returns no project settings. T21 owns the project-config module; T12 owns the consumer acceptance. No root fix is applied. Profile/CUDA/VRAM and T02 baseline gates remain open.


T08/T11/T03 follow-up receipts (2026-10-02)

- **T08 candidate only:** task-memory adoption, immutable HTTP memory, incident scope and durable command-receipt completion batch: **23 passed, 0 failed in 19.52s**. Existing root/repository/tenant memory selector passed **1/1**; prior current-hash checkpoint/receipt batch passed **57**, with two separately passed selectors deselected. No T08 source edits/root writes in these follow-ups. Root integration and T09 provider method remain open.
- **T11 candidate only:** sort-avoidance regression selectors **4 passed in 0.63s**; focused RAG quality/hybrid contracts **35 passed, 1 skipped in 4.60s** (skip: gated 100k benchmark). Candidate `rag.py` SHA `1ab43ee2324eb0cd87d462d2929a5b5c227b6806629a8e71e3a34d4fd4e29d63`; patch SHA `b120123e8962a45e7cbf4ffcf2dd7caf3e0da782cdcb3f9fa1c2662f5dcf3e24`. No profile/benchmark or root integration; prior p95 REDs 972.658 ms and 1698.727 ms versus 750 ms gate remain.
- **T03 candidate only:** local repository path-hint search regression **1 passed in 0.19s**; exact root patch/preimage handoff pending. `/api/context/pack` remains untouched.
- **T02 slot:** remains reserved exclusively for `T02-CPU-20261002-01`; no T02 measurement started. T08's 23-test batch ran after a provisional slot release and completed before T02 retracted it; no benchmark overlapped. Do not reuse slot until T02 pair finishes or T20/user explicitly reassigns it.


Root integration preflight (2026-10-02): T11 optimization patch `b120123e8962a45e7cbf4ffcf2dd7caf3e0da782cdcb3f9fa1c2662f5dcf3e24` failed `git apply --check` at `rag.py:2426` and `test_rag_quality_contract.py:108`; no root changes. Current root preimages are `rag.py` `4C0ED5C52EC4CD9D82B41F0D6D2188812D607D1CE58C4FFEA956D045FBB9048A`, test `E783C6BAC08D827B4FF5F404B5A521B4E041821992C8734A730D1441350149EF`. Require minimal root-current owner patch; keep T11 performance RED.

T03 path-hint candidate also touches `services.py`, which overlaps T21's approved ownership. Candidate test passed 1/0.19s, but no root integration until T03/T21 base diffs, exact hunk provenance, root preimage, and ownership are reconciled. `/api/context/pack` stays untouched.


T12/T21 root-scope correction (2026-10-02): the T12 consumer failures came from its candidate checkout lacking `src/local_ai_hub/project_config.py`; the main root does contain that module, SHA `4238B6A6DE1DE00F55F4679CE0DF7D431522EC1BAFABFA272258C1662F13F713`. Root `tests/test_t12_project_model_consumer.py` and `tests/test_project_config_service_integration.py` also exist, but root selectors were not run while T02 holds the exclusive CPU slot. Therefore T12 candidate failures do not prove the integrated root is broken or accepted.

T21 broad project/worktree patch `handoff/T21-project-worktree-config-20261002.patch` SHA `1D55C26847B029A6A1CE0A5C0E10FF0FFB4C043864A1F5DD20096593831AE5C4` affects 10 files (+2450/-113) including `project_config.py`, `repo_tools.py`, overlapping `services.py`, and tests. Root `git apply --check` failed across the changed paths; no broad patch was applied. Existing root path-hint selector passed 1/1, but project-config service parity and T03/T21 `services.py` ownership remain open.


Modularity and scope-reduction audit (2026-10-02): read-only structure review found `services.py` at 7,141 lines/173 methods (`LocalAIServices` facade) and `deterministic.py` at 7,216 lines/102 methods. Existing leaf modules include `repo_tools`, `commands`, `retrieval`, `diff_parsers`, and agent context/events; no direct import cycle or duplicate algorithm was established. Main observed coupling is facade forwarding/signature/cache/error boundaries. Assign extraction ownership only to existing domain owners T01/T08/T10/T17/T18 (T10 owns retrieval); T20 owns acceptance, not extraction. Keep work **OPEN** until one low-coupling slice has baseline API/output/import edges, parity tests, p50/p95/allocation measurements, and no more than 5% unexplained regression. Preserve import facades. No new tasks/chats created.


T08/T09 provider correction (2026-10-02): both `ordered_event_publication(con)` and `append_in_transaction(...)` exist in T08 candidate and current root; normalized method hashes match (`31C4BDF1339F9BDDCB9E672904F45F2246140A4F2E7546742375CD2101D2BFEA` and `443574218AEB98262A4AB6D458A5CAAB92D00F13278D793E5C85E7FE69BE61CB`). Root `agent_events.py` SHA `09B31135FF2493F2B8E236074DBF7FB2C9CC274BC2DD5841ECDDD07F974ADA5A`. T09 candidate checkout at HEAD `968443549f2a68d17df26689cd49874d1ce400de` lacks both methods, so its 1-failure result is stale-branch drift, not a missing root provider. Root broker-receipt selector passed 1/1. Same-database projection selector is still absent from root; keep only that acceptance slice open if required. No T08 provider patch needed.


T15/T02 benchmark pin checkpoint (2026-10-02): immutable baseline is HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`; isolated clean candidate commit is `b38981611868221755ff899e9f5e40aa68a6c88e`, parented by baseline, with integrated root `commands.py` SHA `845348F2E362852561AE2EBB1B3F5458C8915E0134B1EC884F47356132B9FECB` plus its two required import modules. Both checkouts were reported clean. T15 v2 four-file harness still lacks an immutable commit and its new expected-`commands.py` SHA guard lacks a green test receipt. Local AI Hub did not send the test (`request_not_sent=true`); no `terminal=true`/`retryable=false` evidence exists, so native validation fallback is not permitted. No benchmark ran. T02 assignment `T02-CPU-20261002-01` remains exclusive; do not transfer or claim performance acceptance until harness pin guard and paired receipt are verified.


Swarm/blackboard/pubsub scope audit (2026-10-02): no evidence supports removing swarm, blackboard, memory graph or public pubsub actions; they are wired through app/MCP/HTTP and durable Agent OS state. Keep public `publish/poll` until compatibility is reviewed. Internal `SwarmPubSub.subscribe/unsubscribe` has tests but no production callers; it is only a narrow deprecation candidate, still open. Production `get_default()` pubsub uses in-process TTL, not AgentStateStore; define and test restart semantics before deprecation. Documentation for blackboard/swarm/pubsub/relations remains incomplete.

Pubsub cursor acceptance (owner T04, pending path-lease confirmation before any edit): `client.py` sends `after_seq`, while `http_server.py` reads `since_timestamp`; current transport test checks request serialization only. Required E2E test must exercise client request through actual handler and prove incremental events without duplicates or skipped sequence values. Do not overlap T03/T04/T07 edits to `client.py` or `http_server.py`; no source change has started.


T11 root integration update (2026-10-02): root-current patch `ee8095d24547b4e9692b89d6a0dc2b474963544875ab198229db9d13fbe2bb07` applied after exact patch/source/test hash checks and `git apply --check`. It changes only `rag.py` and `test_rag_quality_contract.py` (+51/-6). Postimage SHA: `rag.py` `88836FE1782A3D01ED3606BC8DD2FCCC40168AC4411C7CFB73B67DA802933C27`; test `273C1EEA3645F78596009340096D2C381FD8749FE71CE8F2ECB7A8AECE723572`. Three focused root selectors remain queued behind T02's exclusive slot. No profile/benchmark ran; p95 REDs remain 972.658 ms and 1698.727 ms vs 750 ms gate.


T04 root test integration (2026-10-02): test-only patch `0FDCDA8D586ED1892A97615B53605CECCCE7E22982CB293DC73631E1A16B5FBA` added `tests/test_t04_client_request_id_http.py` (+71 lines) after exact patch hash and root apply-check; no production source changed. Candidate selector passed 1/1 in 2.38s and focused transport group passed 39/39 in 4.66s. Root test file SHA after patch `E38E06B6860F02E64E5B460DDB18AFE932B8062162F969099CEB11CED691B1CB`; root selector remains queued behind T02's exclusive slot.


T17 root test-fixture integration (2026-10-02): one-line test-only patch `431656D385BE76E22E523DA37126ED1DF23A1C8366474F4EB5713BAFE9A08966` changed the fake `transcribe` callable to accept route-provided keyword arguments such as `cancel_event`. Exact root preimage `568616AC241D6B9E1C4F797542A9FFEF63384CB3FB6C56B9A27A3DEADC71E492` and apply-check passed. Root postimage test SHA `D37CA57154D5323AD8BD55CC9DC23D2FB5C205E392FD2ED1D72F66D65CDBDAB5`. Candidate T17 targeted suite passed 21/21 in 13.57s; root selector remains queued behind T02 slot. Runtime/toolbar/WER/live vision quality remain unverified.


T05 candidate full-batch update (2026-10-02): planned selector batch returned **43 passed, 11 failed in 30.55s**. All 11 failures are candidate-only `AttributeError` from the T05 event bridge lacking T08 `AgentStateStore.ordered_event_publication`; current root/T08 provider method exists with matching normalized hash (see T08/T09 provider correction). Separate T05 receipts remain: root-bridge identity/isolation 15/15, candidate migrations 24/24, evidence 2/2, HTTP identity 1/1, tenant/global delete 4/4. T05 also reports root `agent_incidents` allowlisting failure in seven nodes, conflicting with earlier root T08 migration bridge + T05 selectors (1/1 and 7/7). Keep that migration claim **OPEN / reconcile exact hashes and current node paths**; do not overwrite prior root pass receipts without matching evidence. No new root edits.


T02 paired-matrix candidate gate (2026-10-02): `tests/test_t02_paired_matrix.py` returned **10 passed, 2 failed in 0.28s**. Failures: false-success case produced `not_established` instead of `failed`; generator/epoch receipt assertion did not establish `generator_version_match=False` for every expected row. T02 was asked to fix behavior, not weaken tests, then rerun only this suite. T15 pin/harness test and paired benchmark remain blocked until this gate is green. T02 owns current serial CPU/test slot; no other test or benchmark may overlap.


Root-wide whitespace status correction (2026-10-02): targeted `git diff --check -- tests/test_mutation_replay.py` reports `tests/test_mutation_replay.py:1567: new blank line at EOF`. This is inherited/parallel T07-owned dirty content; T20 did not edit it. Scoped checks of T20-owned changed paths remain clean, but do not report the whole root diff as whitespace-clean until T07 resolves this file.


T16 root-current test integration (2026-10-02): three owner-scoped test-only patches applied after manifest SHA/preimage/apply-check verification; no production source changed. Candidate batch **79 passed, 1 skipped, 1 deselected**; root selectors remain unrun behind T02/T15 serial gate. Patches: atomic lease lifecycle SHA `A2B836F28FEBF4043E06AB83FE2AA70D1A769727BDFDF1D2D6B8C2EDC1998574`; cross-process commit race SHA `CFCFF000F6FD1C3F1A3434B2B21BD8BB61AC5930A33D1B9AAB82C5BB027A4F66`; crash-test placement SHA `E3CC3A615D87DC4DAAF94FD4BDE1488F7E8CCC75CDAD108F8D31C8ABB6F7044A`. Root postimages: `test_t16_cross_process_namespace_lease_recovery.py` `D69F65E06443E76C8979A7F020C0DDD6F744FABFDCD84D5F79103C852D40FE44`; `test_work_fencing.py` `EEB23B457ED9C96786F4AF1763507CF8B97D5EA43B79AC187E4975D151CF3FDE`; `test_work_handoff_acceptance.py` `978B4E01CFE36116838FB22451D409F7B72DC00836913D337C2DBFCAF233BBEB`. Symlink acceptance remains unverified (`WinError 1314`); T06/T09 owner-specific and service-overlay blockers remain open.


T02 gate rerun correction (2026-10-02): after implementation-only fixes, `tests/test_t02_paired_matrix.py` passed **12/12 in 0.20s**; test expectations were unchanged. This supersedes the earlier 10/2 candidate failure for current candidate state. No benchmark ran. T15 pin-guard receipt and immutable v2 harness commit remain prerequisites; performance is still **NOT VERIFIED / RED**.


T05 acceptance correction (2026-10-02): current-hash candidate run injected root `agent_events.py` into the candidate package and passed **54/54 selectors in 40.26s** across 17 selectors, exit 0. This supersedes the earlier 43/11 stale-event-bridge candidate failure; tests were not weakened. Root provider SHA remains `09B31135FF2493F2B8E236074DBF7FB2C9CC274BC2DD5841ECDDD07F974ADA5A`; root `agent_memory.py`/memory test hashes match prior T05 patch postimages. T05 patch SHA `F7B2F7761E72755A8AB7ACF889DEAF02CB7AD413C15E0AC1CC287A87344DCB19` was already integrated; this new 54-pass run is **candidate-only**, not a root suite receipt. It excludes T08 task-create/resume selectors. Receipt SHA `34E43A87CF0D205648106E32AEA914D0E736BF4F2748EE60464E39F124F2AFB5`; manifest v3 SHA `2434983FE3250AEB3274988E33081B1183A830E7EB9A9B969DB068D1F368B077`; checkpoint v31 SHA `8D6C308CAFA386FA5E9B8DEC0E301980ECC97303DAB6B82203D1D406D50B523D`.


T06/T07/T12/T16 integration checkpoint (2026-10-02)

- **T06:** exact Windows rollback path-replacement test hunk `2BD7696FE44EDDA73308FB384D268CE6A43BB8A0B39826DBA2F930907E413DD3` applied after root test preimage `9A8F7038F73A699CB22FA8AC361A306BE4C86681D9E500D18A6CB98CB9772269` and apply-check. Root `tests/test_command_rollback.py` postimage `3A0A5F02692B9A3036558A438E2F03DC096C11BF4CA8BF37BFB56A1DBA434606`; candidate Windows race passed, root selector pending serial slot.
- **T07:** root-current whitespace patch `c1619d571dc62bfd0bbd04c50b8f3801f076b56cbfdbf2a029105cd96c3156c3` removed the exact extra EOF blank from `tests/test_mutation_replay.py`; postimage `26555eab85c074c5e5a960402438a1490f223dad12e292a1d918306e1dad7cde`. Root selector receipt 118 passed/10.68s; candidate suite 160 passed/1 skipped. Root-wide `git diff --check` now passes with only LF-to-CRLF warnings.
- **T12:** root `project_config.py` exists (SHA `4238B6A6DE1DE00F55F4679CE0DF7D431522EC1BAFABFA272258C1662F13F713`); T12 candidate lacked it. Seven candidate consumer cases passed when supplied the read-only root module (1.91s); no root test suite ran. T12 docs/policy patch `38BC78E9315668ED0D6D36001AFF3722E7448187957EB4F20DCF87C9347174D3` passed root apply-check but is not applied; owner manifest SHA `D9843D9E24547EBDDD3A6BFB9A1658C02695ABFF8335B84C2ED575DABCE42573`.
- **T16:** three test-only root patches applied; exact root postimages and candidate selector receipts are recorded above. Candidate targeted selectors passed 3/3 in 3.83s; root selectors still unrun. Symlink/Windows external acceptance stays open.


T12 root policy integration (2026-10-02): documentation-only routing-policy patch `38BC78E9315668ED0D6D36001AFF3722E7448187957EB4F20DCF87C9347174D3` applied after exact three-file preimage and root apply-check; changed only `AGENTS.md`, `docs/INSTALL_PROMPT.md`, and `docs/UPDATE_PROMPT.md`. Postimage SHA: `AGENTS.md` `FE64D54D0B96ED80FE89AD33458B7216BFC771D723B4A026D190C20614DCCC1D`; INSTALL `340711AAA1F3100F5227E3ACEE900B497D3A5D30D228EDA8418602E6C720BF6B`; UPDATE `19B20D07514F17A81173FBF142443FAE2F1AEBA04225D448727BEA08A5D9E853`. T12's seven project-model consumer selectors passed in its candidate package with read-only root `project_config.py` injected (7/7 in 1.91s); this is not a root suite receipt. Root runtime selectors, live profile/CUDA/VRAM, and T02 benchmark remain open.
T04/T09 root verification update (2026-10-02; orchestrator receipts): T04 current root command `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_transport.py tests/test_t04_client_request_id_http.py` passed **28 tests in 3.62s**, exit 0; it covers a different, smaller root scope than T04 candidate's 39/39. Files already exist in root; do not reapply T04 patch. T09 current root eight-selector batch (`test_agent_verification.py` stale/evidence/verifier/valid receipt cases plus `test_agent_tasks.py` structured-description round-trip, description-only search, cross-field keyword retrieval, and projection backfill) passed **8/8 in 1.54s**, exit 0. No benchmark ran. These are direct owner/orchestrator handoff receipts; root test artifacts were reported, not independently rerun here. T09/T04 acceptance remains limited to these selectors; whole-project release remains open.
T21 root project-config verification (2026-10-02; orchestrator receipt): after `NO_ACTIVE_TEST_OR_BENCHMARK`, `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_config.py tests/test_project_config_service_integration.py tests/test_project_path_hints.py` passed **92 tests in 2.98s**, exit 0. No root writes or benchmark. This covers current config/service/path-hint selectors; it does not prove every proposed config key or worktree-inheritance acceptance. Keep broader T21 cases open.
T04 root receipt provenance addendum (2026-10-02): owner manifest `handoff/t04-client-request-id-http.root-current.md` SHA-256 `B84CDBA1EF4062C8EED2F6E5C2CF6EB7E6EDCB182CC8AFCC315277741A23FE97`. Manifest pins exact root command/result (28 passed/3.62s), process guard, no benchmark, root HEAD, and normalized candidate/root test-content match. No rerun or root edit.
T19 partial root integration (2026-10-02): patch SHA-256 `53851641F5FA14048FF52F5B26BD5A8822CF28E239B8755E8AFCE3F7EF6F52DC`; manifest SHA-256 `B4526592DD96F2BFCB422D2204FBAD96D019DC37B9CE89A07D241F5A9D539E0B`. Strict path-filtered checks passed; integrated only disjoint `docs/INSTALLATION.md` (postimage `3802B4F60012F8E5C0ECA12673F0D8273FC93E6EDEAFA03FD6AF838B7DBF463D`), `docs/MODEL_CAPABILITIES.md` (`09FE472497C3F8F5381CCFEFB64B21CA4453C9110F55BB7C22F22BC313487617`), and `docs/UPDATE_PROMPT.md` (`A0EB389F6B366F58FFAA98ED3C1D9317896BB9255D5C2D0906142A0ADE0D0924`). Full patch check fails at `docs/INSTALL_PROMPT.md:158`, which overlaps T12 edits; left that file untouched. T19 candidate prompt/CodeGraph tests passed 7/7 and static docs check exited 0; no root T19 tests run. Clean-host/runtime acceptance remains open.
T05 root memory selectors (2026-10-02; orchestrator receipt): after guard `NO_ACTIVE_TEST_OR_BENCHMARK`, root command `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_agent_memory.py tests/test_agent_memory_http_identity.py` passed **36 tests in 40.76s**, exit 0. T05 patch `F7B2F7761E72755A8AB7ACF889DEAF02CB7AD413C15E0AC1CC287A87344DCB19` is already present; do not reapply. This covers these memory modules only; broader Agent OS memory-adoption remains open.

T13 root-current patch preflight (2026-10-02): no writes. `T13-rootcurrent-unload-receipt-validation-20261002.patch` (`19FA1329F6C7FCC369D13096D6F369C55EEE0B9E4948EE59096221E548C09EEC`) fails current root hunk checks in `operational_mode.py` and `test_operational_mode.py`; `T13-rootcurrent-ollama-unload-20261002.patch` (`98BDEE5C3BC1FDB4D31E0875CFD7D8AD9C24B06806749ABFB9F95D8D54A2BD41`) fails at `ollama.py`; `T13-rootcurrent-mode-api-get-auth-20261002.patch` (`C78FDA7D11C5913FF7FC13EE49ED51E0305973F0E0934E8E4D433C61034F1D9E`) targets missing root `tests/test_operational_mode_http.py`. Stop integration pending root-current T13 preimages/manifest reconciliation; candidate receipts do not establish root acceptance.


T20 release gate update (2026-10-02; orchestrator receipt): `tests/test_codegraph_package_policy.py tests/test_release_contract.py tests/test_setup.py` returned **41 passed, 2 failed in 5.69s**. Failures: forbidden `ALTER TABLE` marker in T13-owned `async_jobs.py` and an absolute personal path in `test_t04_root_path_hint_chain.py`. T04 path fixture now derives source from `Path(__file__).resolve().parents[1] / "src"`, not yet rerun. T13 audit confirms additive column logic is T13-owned; the destructive `DROP TABLE` fallback is inherited. Root `AGENTS.md:87` forbids migration shims; T15 flags durable-job data risk. Storage contract/owner resolution still required. T20's temporary table-rebuild source edit was reverted; source remains unchanged. Two fail-closed/data-preservation regression expectations are staged in `test_async_jobs.py` but unverified. T02 benchmark remains unrun.

T14 architecture acceptance crosswalk (2026-10-02; criteria open, not completion claims): (1) daemonless/in-process MCP without HTTP/daemon, evidence owned by T03/T06/T20; (2) physically separate disposable cache DB and durable Agent OS DB, with clear/rebuild preserving tasks, memories, and receipts, owners T08/T14/T20; (3) action-specific typed MCP input/output and runtime rejection tests for each action, T03/T20; (4) commands execute inside worktree/sandbox, not only rollback via write set, T06/T09/T20; (5) separate orchestration/HubServices measurements from deterministic boundaries, T02/T10; (6) swarm/blackboard inventory plus parity and keep/simplify/remove evidence, T01/T08. T12 VRAM/model lifecycle criteria and T02/T12 measurement remain open.

T21 follow-up (2026-10-02): current root config/service/path-hint selectors passed 92/92, but T21's new root-current test-only patch is not applied; the 122-selector candidate receipt is older and not root-green. Preserve remaining schema/override acceptance as open.


T01 surface coverage debt (2026-10-02; static mapping only; audit remains OPEN): 123 root-current selectors map to 128 operation IDs across 220 selector-operation links. Of 446 historical gaps, 58 have only targeted candidate selectors, 387 have no behavioral selector or owner receipt, and 1 has owner receipt only (op-65970ac00a0a, T13 transcribe; not root-green). Candidate selectors are not root acceptance. Known uncovered endpoints: GET /api/agent-state/events/stream owner T08, GET /api/agent-state/memory T05, GET /api/code/ast_outline T10, GET /api/db/query T18. Priority proposal pending owner confirmation: P1 for memory/events/database and mutation/auth boundaries; P2 for read-only AST and remaining ordinary operations. Remaining 387 retain owner/priority UNASSIGNED / OPEN until classified row-by-row. Integration gate: assign owner + priority per uncovered row, define exact behavioral selector, verify selector-operation mapping, run root-current selector under serial slot/process guard, attach root revision and receipt; only then close row. /api/context/pack (op-a991c9e8b941) remains explicitly excluded by user scope. T01 artifacts: selector list SHA 57610EC4E0B5BFA5BF1B5A36F44A28EB713144A0881C5CBBECB4F64B590BAE70; operation links JSON 5FF085617F2F53CA4B97B2707387CB18D68F231C0FC4B7C74426D34D4577A1D5; uncovered CSV E9A32BE7548A4E758CF5A26D4FEB05D7C2D64E69E6CE4EA1B89577A69CFE9C21; evidence manifest D1944A12EE2F66B96966C442AE8DBDB5D80C4B0CC3ACC21A380A0DDDD162CF5C. Static mapping only; no tests or root edits.

T13 async-jobs owner handoff (2026-10-02): candidate patch SHA 69DE46855A799DD5AF1DF515C57A5F074700F4112B91D6802B83CA6B4FC1AE04 adds user_version=1 transactional known-v0 upgrade and fail-closed unsupported schema handling; removes destructive DROP TABLE. Candidate targeted preservation/upgrade tests passed 2/2 in 0.31s. Root apply-check fails at current source/test preimages; no root integration. T13 receipt remains candidate-only. T02 paired benchmark attempt stopped before measurement: runner rejected unsupported --full-matrix, --comparison-repetitions, --input-seed, and --timeout-seconds arguments; no performance data. Do not repeat command/output directory. T02 is repairing only harness/manifest, then will use fresh output directory T02-CPU-20261002-02 and a newly assigned paired slot. No root suites during that slot. Afterwards revalidate T13 root preimages/ownership and run only focused async-jobs/release selectors plus gate; no threshold or test weakening.
T08/T05 delete-rollback masking (2026-10-02): T08 candidate batch **3 passed, 1 failed**; sole failure `test_delete_preserves_primary_fts_error_when_rollback_also_fails` reflects missing T05-owned FTS cleanup. T05 FTS patch SHA 1F9CA4876671700A7123DC1ACDCFF53530E4547F931D60F4EB403BFD71D0B3DB passed apply-check against T08 preimage/overlay; T08 tombstone hunk untouched. Receipt SHA 3B9BB8D2E5E15431FF9B8F5E3E624A79717C4F323C6E4E7724A87D46937737AE. No root integration/test. One selector waits for T02 slot release; root acceptance remains open.
T20 focused release-selector receipt (2026-10-02): after checkout-relative T04 fixture edit, command `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_release_contract.py::test_no_personal_paths_or_runtime_payloads_in_tracked_release_sources` failed **1 test in 0.32s** on hard-coded personal path in `tests/test_t21_root_path_hint_worktree_chain.py`. T04 path no longer flagged; T21 owns remaining fixture path and needs a current-root fix/receipt. T02 serial slot returned immediately after this one selector; benchmark still has no measurement.

T13 root-current correction (2026-10-02): superseding no-migration patch 7F4142A928E411633A76169156BD5AE22345B6E7240EE740B84F922D5BC5E2F0 applied after exact root source/test preimage hashes and strict apply-check. Changed only async_jobs.py. It removes automatic schema mutation and destructive table drop; unsupported layouts fail closed with DB preserved. Source postimage SHA CBB599D76A08BFF38F95A2AFA34DA11FFCFC96C54065D0F313E518B69D9CB950. Reverse-check, forbidden-marker check and scoped diff-check pass. The earlier versioned migration patch D886500DC4671712D3C26970FBC65A829EE02E1043905C5A57D74305AD801FDC remains superseded. Two root async-jobs selectors wait for T02 benchmark/slot completion.
T02 baseline preparation update (2026-10-02): runner CLI contract tests passed 4/4; paired-matrix suite passed 16/16. Benchmark attempt T02-CPU-20261002-01 ended before measurement; no performance data. Current clean baseline/candidate pins 01df/b389 do not contain input-seed or synthetic seed/fingerprint metadata required by six paired receipts. Keep seed=42 and provenance checks fail-closed; do not retry old command/output directory. T02 awaits T15-compatible clean pins before reserving fresh output T02-CPU-20261002-02.

T03 path-hints integration hold: patch A5F28F9C645DF211BEFE971E3B0257086A1FC07CBB9353EBC39EE3569D4130F5; receipt 30554D3BC5C70219397948405184BE7B0F817A831557EA056F0CEE7081606C6F. Root service preimage 525565A42B626A7ED2A66ADE57C6878D1802B430F2D1BD5A2818B7ADA68D3179 still matches, test target was absent, and root apply-check passes. Do not apply yet: receipt records unresolved T03/T21 services ownership/lease; root services.py is dirty. Candidate 3/2.45s and root-current scratch 3/0.60s are not root receipts. T21 personal-path fix is in its own worktree only; root failing selector still needs a T21 root-current patch.

T01 ownership-map refinement (2026-10-02): uncovered 387 operations span 20 named owners; largest groups T10=159, T04=75, T15=32, T18=20, T08=18. Zero root-green among these. Detailed row-level IDs, owner, handler, target module, priority, and acceptance criteria are in T01 plan JSON SHA 5835CC1A2AE5220E1813C3B6D3E7DE13836253606D04FE4000D8E4CA22ECE1F4 and summary MD SHA 28355F3565DDA50851E43FB831ED76517A86445A448F65EE82532426B2238568. Updated evidence manifest SHA 3CFBA8883FD2AB3573BA2BDF2E651AE1AA75019C6D9E8BC3CE93AD663576A552. Keep T01 surface OPEN; /api/context/pack remains excluded.
T02 paired-runner update (2026-10-02): parser variants **4/4** and T02 suite **16/16**. New runner SHA 938F190E546F325D0DCD97CD5DE81525EAD159A5B1D26B564E02B65944DC3A62, parser test SHA 6D3692D903DF07BE3CBF77293E7CC6E3481CF3CAC37FD2A3F0207A5A0947AE60, manifest SHA A143855AC5094D11ACC3DEE31DAF514C7D006D7BDACABA1E084F6A7CDAA48C6A, receipt SHA A307918B16638792C929E8DC4CD6DF35969D0C75A77BA630289BBB6A7F8D6A94. No benchmark is active; output -01 aborted before measurement. Current clean pins still lack required seed/fingerprint metadata; T15-compatible immutable pins remain blocker. Next output dir is T02-CPU-20261002-02.

T21 personal-path worktree correction (2026-10-02): T21 changed only its own candidate test fixture to derive ROOT_SOURCE from __file__; root remains unchanged and root release selector still fails on tests/test_t21_root_path_hint_worktree_chain.py. Await exact T21 root-current test patch/preimage, then run the single focused selector in serial slot.
T05 focused selector evidence correction (2026-10-02): first overlay run returned `DID NOT RAISE`, but receipt `F4F9A6266690EA700D6021DD62A76A674CFCDD4FDACBE47D0E03568C764F93D9` records `source_import_verified=false`; therefore this is an invalid SUT-provenance/harness run, not a confirmed regression or valid pass. T05 has one authorized retry with explicit module-path assertion and unchanged test expectation. After retry, slot moves to T21's focused selector. No root/T08 writes.
T05 retry supersedes invalid attempt (2026-10-02): explicit sys.path[0] overlay launcher verified local_ai_hub.__file__ inside T05 overlay before pytest. Exact selector test_delete_preserves_primary_fts_error_when_rollback_also_fails passed 1/1 (pytest 0.23s, wall 0.819s), exit 0. No expectation change, no T08/root edits. Verified receipt SHA 71FBA6D7BBE3669509133AF542E70137936D3CC10C376DEAC98F4B6BF417839E. Slot released to T21 next.

T03 path-hints patch integration (2026-10-02): applied T03-root-current-path-hints-20261002.patch SHA A5F28F9C645DF211BEFE971E3B0257086A1FC07CBB9353EBC39EE3569D4130F5 after exact root service preimage 525565A42B626A7ED2A66ADE57C6878D1802B430F2D1BD5A2818B7ADA68D3179, absent test target, strict apply-check, and patch review. Root postimages: services.py 11C4B336A735220CB11BCACE11021B74227BA8B303275E43F192CBDD9C52BC27; test_t03_path_hint_search_first.py FF43981461F039A12B660DA031581C5936A3499098E7A03F907D1BAB64204358. Candidate 3/2.45s and scratch root-current 3/0.60s remain distinct from root evidence. Root selector is pending serial slot; no T03 root test receipt yet.
T03 integration correction (2026-10-02): parent identified T21 ownership of LocalAIServices.repo_search. T03 services hunk was reversed with exact reverse-check; root services preimage 525565A42B626A7ED2A66ADE57C6878D1802B430F2D1BD5A2818B7ADA68D3179 restored, T03 test file removed. T03 patch remains HOLD pending owner reconciliation; no root T03 selector receipt.

T21 path fix root integration: changed only ROOT_SOURCE in tests/test_t21_root_path_hint_worktree_chain.py from personal absolute path to checkout-relative Path(__file__). Root preimage SHA 2E487752036A54D1FA750FCCDC8401A10035A5F4D7C3B20D2A47D5EB58E2C9D4; root postimage SHA AE9E9C9EDFAB0D72AD0758EA84023BEA1B99FA9FC931D422B479FDA9401917C8. T21 candidate test passed 1/5.49s; root release personal-path selector passed within the combined root batch below.

T13 + release-selector root batch (2026-10-02): two fail-closed async_jobs selectors and two previously failing release selectors returned **3 passed, 1 failed in 10.24s** per orchestrator receipt. T13 tests passed 2/2; personal-path scan passed. Remaining failure is `test_release_uses_only_current_local_ai_hub_contracts`, which finds `ALTER TABLE files ADD COLUMN analyzer_version` in T10-owned `src/local_ai_hub/code_index.py`. A separate focused rerun of the two release selectors confirmed **1 passed, 1 failed in 6.73s** on same T10 marker. Do not repeat unchanged selector; await exact T10-owned no-shim patch. Full release gate remains RED. T02 benchmark still blocked on compatible pins.
T10 acceptance update (2026-10-02): candidate AST/retrieval selection passed **48/48 in 4.19s** across AST/callgraph, adaptive retrieval, topology, affected tests, cross-repo and contract fixtures. Candidate-only; no root tests. Root release marker in code_index.py is being reviewed for a no-migration fix; exact root-current patch/preimages pending. T10 umbrella remains OPEN; T02 benchmark, CodeGraph runtime and clean-host gates remain separate.
T02/T15 paired-measurement correction (2026-10-02): no compatible clean baseline/candidate pair or prepared fixture exists. Pinned 01df/b389 harness SHA 8F8B7DA8…E976CF80 lacks --input-seed and synthetic input seed/generator/fingerprint metadata; pinned argv cannot satisfy seed=42 receipts. Newer seed-aware candidate harness is not an immutable matching pair and lacks CLI support; scratch-dir creates its own data. T02 must add seed-aware CLI/metadata, pin identical harness/generator bytes on both sides, regenerate clean pins/receipts, then obtain a fresh serial slot and output directory. No benchmark data. T02 16/16 candidate suite result is not current-hash-bound: runner/test SHA differ from hashes in preparation receipt; mark stale/unverified pending corrected receipt.
T02 slot update (2026-10-02): user authorized notifying T02 and releasing the current CPU slot. T02 was told not to benchmark until T15 returns compatible clean pins and T20 assigns a new serial slot; `T02-CPU-20261002-02` remains only the prospective output target. T10 root-current patch candidate SHA A043F980…4738AC9 passes scratch `git apply --check` against preimage 17381446…D1741, but has no test receipt and is not integrated. T10 must finish source-path-verified tests in its own checkout. T15 pin preparation is active; no benchmark runs.
T15/T02 latest handoff (2026-10-02): T15 confirmed external `PYTHONPATH`/harness routing is unsupported. Baseline clean checkout committed at `28f471f67a4b37da92499d720084ff300170c013`; candidate checkout has harness SHA `977FEC1F…314C31` copied but remains uncommitted. Thus there is still no verified clean immutable pair and T02-CPU-20261002-02 remains unscheduled. T02 final reports four focused selectors passed; its full 17-selector run was 16 passed, 1 failed on old pin incompatibility. No benchmark ran. T10 regression RED confirms legacy schema currently passes without rebuild/fail-closed; fixture connection cleanup is being fixed before implementation and root remains unchanged.
T16/T14/T06/T19 handoff inventory (2026-10-02): T16’s three root test postimages match reported hashes (D69F65E0…, EEB23B45…, 978B4E01…); candidate selectors were 3/3 and candidate suite 79 passed, 1 skipped, 1 deselected; root selectors remain pending. T14’s bounded projection selectors passed 4/4; output-schema validation remains T03-owned and open. T06 candidate rollback/race/daemon batches passed; POSIX runtime and Docker E2E remain unverified, while the root Windows race test matches its current hash. T19 candidate docs evidence does not authorize applying its stale full patch; INSTALLATION/MODEL_CAPABILITIES/UPDATE_PROMPT are already partially integrated, INSTALL_PROMPT remains shared with T12. T05/T08 agent_memory overlap remains unintegrated because root source hash 38A9A86C… differs from their candidate preimage 8FD84510…; preserve root state until a root-current patch is reconciled.
Serial-slot queue update (2026-10-02): T20 assigned the released slot to T10 candidate-only regression validation. T10 found default imports resolve to the root package; it will set process-only candidate `PYTHONPATH`, reassert import path, then run its focused tests. No T10 tests have run yet. T02 candidate pin remains uncommitted, so its benchmark slot is not assigned. T21 has resumed in its existing `t21-project-config` worktree; root integration waits on its current hash-bound handoff.
T10 root integration and serial validation (2026-10-02): root preimage `code_index.py` SHA `17381446B55B80D28C06387FD972CC907CE2F5E9D01506FBD5955080D90D1741` matched. Patch `BB9B28E7EA1EDF77FF0C43F927490BC868F39266B883D44E21567267812F0C64` passed `git apply --check` and applied only `code_index.py` plus new `tests/test_t10_code_index_schema_rebuild.py`; postimages `73BE2A44010E3EF9BA8367CAC7C99D1DBA4F2DEB7DFA3EACD4A2D4FE361BC00B` and `718FC258C6368B355F90A466113ABC3F232B4BBD01A0EB2BF068DE2AF3C1CC52`. Root T10 selectors passed 2/2; combined release-contract selector failed on existing `ALTER TABLE lease_waits_namespace_v2 RENAME TO lease_waits` in `src/local_ai_hub/leases.py` (T16 area), so release gate remains red. T16 read-only owner/preimage diagnosis requested; no write or test authorized for that diagnosis. After T10 slot release, six integrated T16/T11 selectors passed **6/6 in 4.49s** (one serial root batch).
T02 serial assignment (2026-10-02): T15 baseline `28f471f67a4b37da92499d720084ff300170c013` and candidate `a10baed2a86f721cbd724af19b4adb2a71cb88af` independently verified clean with parents `01df56605ccf484ebfe2808ac60d696c4e81dffc` / `b38981611868221755ff899e9f5e40aa68a6c88e`; both harness SHA `977FEC1F9936A0608452CFBAB720DF6D24023B79BDE2405DEDF7BEF293149C31`. T20 assigned one run only under slot ID `T20-CPU-SLOT-20261002-02`, output `T02-CPU-20261002-02`; no benchmark receipt yet.
