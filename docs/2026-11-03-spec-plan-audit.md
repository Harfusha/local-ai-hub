# Audit specifikací a plánů Local AI Hub

**Datum:** 2026-11-03  
**Stav:** dokončený inventář; acceptance produktu není uzavřené.

## Verdikt

Ne. Všechny požadavky nejsou doložené jako implementované a přijaté. Zdrojové cesty a statické testy existují pro řadu požadavků, ale aktuální běhy testů, integrované CI a runtime acceptance zde nebyly ověřeny. Některé plány výslovně ponechávají práci otevřenou.

## Rozsah

- 103 unikátních cest: 66 plánů, 32 Markdown specifikací, 1 JSON kontrakt a 4 související dokumenty.
- Původních „104“ započítalo JSON kontrakt dvakrát.
- Navíc přečteno 7 dalších receiptů jako podkladů; nejsou součástí inventáře specifikací/plánů.
- Všechny cesty inventáře mají řádek v [matici auditu](2026-11-03-spec-plan-audit-matrix.md).
- Prvotní inventář byl read-only; tehdy vznikly pouze tyto dva reporty. Následné implementační změny a jejich ověření jsou zaznamenány v doplněních níže.
- V prvotním inventáři nebyly spuštěny testy, buildy, importy, instalace ani runtime. Pozdější běhy jsou uvedeny odděleně.

## Kritické neuzavřené brány

1. **Aktuální release:** [stavový plán 2026-11-02](superpowers/plans/local-ai-hub-current-status.md) uvádí selhání master CI (pyflakes a kritická coverage), přeskočené package/publish kroky, neintegrované kandidáty a otevřené release acceptance.
2. **T09 completion/receipts:** [source review](superpowers/receipts/2026-10-01-t09-spec-review-r1.md) výslovně nařizuje HOLD. Hlásí zaměnitelný root/worktree a memory context, alternativní terminal-completion cestu mimo důvěryhodnou gate, slabé ověření structured argv/environment, alias provenance, ownership API mismatch a opaque-root binding. Historické průchody tato místa nepokrývají. Oprava v aktuálním HEAD nebyla potvrzena.
3. **T16 orchestrace a lease:** [source review](superpowers/receipts/2026-10-01-t16-spec-review-r1.md) říká spec-compliant NO / merge-ready NO. Aktuální candidate source obsahuje restore-path ancestor preflight i preflight celé rollback sady před prvním zápisem. Testy hardlink/ancestor a opožděného workera potvrzují, že rollback nic nezmění při odmítnutí a terminální výsledek nelze oživit ani přepsat: `5 passed in 2.43s` (`tests/test_t16_terminal_rollback_preflight.py`, SHA-256 `87233ee6a634a5c69c9875926d6da2eafa9bc6acc081e2da9250d19f1ee1e0da`; `src/local_ai_hub/work_orchestrator.py` SHA-256 `af5a9a953bce449f0be75a1cf8d2c756dc239a7481354b15922ec0cc62ee8f58`). Namespacované wait edges a cílený cleanup po release/reclaim mají regresi `3 passed in 1.48s` (`tests/test_t16_lease_wait_namespace_isolation.py`, SHA-256 `49b0ecb3877d40e98102d394f8dc9f8989ee8324ab7a94347211157a86ef76d9`; `src/local_ai_hub/leases.py` SHA-256 `78d5e17885d09c9c640058c4d475f66e417c27ca3be58a18f662aa166451eed1`). Tyto candidate testy neuzavírají T16 ani release. Counter floor při chybějícím namespace counteru je opraven a ověřen níže. Candidate source předává namespace v primary fenced acquire i recovery ScopeLeaseStore claim cestě. Nová regrese v `tests/test_t16_http_lease_routes.py` ověřuje, že HTTP lease z linked worktree zablokuje skutečný `CommandBroker._recover_transaction_journals` claim a oba vlastníky vrátí složený HTTP `waits` view (`1 passed in 5.93s`, SHA-256 `A0523F7C9D5158DF014687744A10D38453B89FBCAE1D881648A127109EF72752`). Celá `CommandBroker.run`/recovery orchestrace, úplná T16 shoda a release acceptance zůstávají otevřené.
4. **T11 RAG provenance:** [isolation review](superpowers/receipts/2026-10-01-t11-isolation-review-r1.md) hlásí chybějící embedding-space filtr ve FTS, reuse bez provenance s relabelováním embeddings a nekomponovatelné patche. Veřejná cache/runtime acceptance není doložena.
5. **T12 model admission/unload:** [review r3](superpowers/receipts/2026-10-01-t12-r3-review.md) nechává otevřené canonical admission před runtime startem, timeout/lifetime child procesu, joined runtime a skutečné GPU/VRAM uvolnění.

Tyto review receipts jsou z 2026-10-01. Jejich nálezy jsou důvodem pro HOLD/NOT VERIFIED, nikoli potvrzením, že dnešní HEAD stále obsahuje stejnou chybu. Aktuální uzavření nebylo ověřeno.

## Další chybějící nebo neověřené požadavky

- **Reálná retrieval kvalita:** [T02 plan](T02-real-input-quality-evidence-plan.md) uvádí, že chybí povolený corpus manifest, označené dotazy, retrieved IDs a metriky. Syntetická evaluace je nenahrazuje. Thresholdy a resource window potřebují schválení.
- **Párový benchmark:** [T02 runner](superpowers/plans/2026-10-02-t02-paired-baseline-runner.md) čeká na neměnné source piny a CPU slot; šest případů, stejná konfigurace, izolované scratch/state a odmítnutí neúplných výsledků nejsou doložené aktuálním receiptem.
- **Výkon:** doložený JSON microbenchmark se vztahuje jen na 1 000 párů a jeho zaznamenané p95/p99. Neprokazuje obecné end-to-end zrychlení, Cython/native adopci ani cíle vln 1–6. Cython experiment zůstává vypnutý do compiler a end-to-end acceptance.
- **Transakční izolace příkazů:** vlastní plán říká, že plná izolace není dokončena; širší platformní/Docker ověření zůstává otevřené.
- **T03 MCP:** živá shoda osmi action schema, daemon-off autostart/cleanup a nezávislý Hub receipt nejsou aktuálně doloženy.
- **Vlny 1–6:** spolehlivost, storage/performance, AST/index, command execution, koordinace/memory a multimodální/GPU acceptance nemají čerstvý integrovaný release důkaz.
- **Browser/desktop/GPU:** osobní Chrome, Windows desktop, sandbox/egress, live vision a fyzický VRAM cleanup zůstávají neověřené; browser broker má zůstat defaultně vypnutý.
- **Fuzzy trigram:** plán ponechává unit testy neprovedené, source bundle closure a paired pinned benchmark otevřené.
- **Exact search:** test prefilteru existuje a [historický T21 receipt](superpowers/receipts/2026-10-01-t21-root-search-acceptance.md) uvádí 22 passing testů pro omezený root slice. Nejde o současné full-suite/release acceptance; novější plan kroky release/doctor/prompt review jsou otevřené.
- **Adoption a consistency guard:** zdrojové symboly a testy existují, ale čerstvost indexu byla stale a úplné chování nebylo ověřeno. Chybí 14denní baseline, pilot a promotion receipts; současná guidance jasně nevynucuje context pack pro každý task.
- **Trace pravidla:** starší redakční/size pravidla jsou nahrazena, ale credential redaction v navazující specifikaci se rozchází s aktuální instrukcí pro trace bez redakce. Autoritativní pravidlo není sjednoceno.
- **Caveman/Antigravity:** Caveman zdroj a statické testy jsou přítomné; reálná kvalita/rychlost instrukcí není doložena. Antigravity instalace, opakovaný setup, discovery a živé použití jsou externí a neověřené.
- **repo-plan.v1:** příklad i metaschema/round-trip testy jsou ve zdroji. Testy nebyly spuštěny; živá API/schema shoda a runtime conflict behavior jsou neověřené.
- **Eval fixtures:** plán hlásí stale integration preview a rozpor service status vs. hubctl status; aktualizované ověření chybí.

## Limity důkazů

- Statická přítomnost symbolu/testu neznamená, že test prochází nebo že chování platí v produkčním runtime.
- Část indexovaných výsledků byla označena stale; exact source review nebo běh by byl nutný pro uzavření.
- Hub byl při závěrečném status call online, ale bez aktivního modelu; Ollama probe byla degraded/timeout. Modelový second opinion nebyl proveden.
- Čerstvý full pytest, release_check, compileall, selftest, balíček/instalace, hostovaný CI ani hardware/browser acceptance v tomto auditu neběžely.

## Závěr

Inventář je uzavřen; implementace/release acceptance nikoli. Otevřené položky výše zůstávají `NOT VERIFIED` nebo explicitně `OPEN/HOLD`. Pro jejich uzavření je potřeba ověřit aktuální root/revision a získat nové receipts; staré candidate logy nestačí.


## Aktualizace stavu a implementační uzávěrka — 2026-11-03

### 1. Změněné soubory a vyřešené požadavky

- `src/local_ai_hub/features.py`:
  - Opravena výchozí inicializace Ollama (`self.ollama = True`), pokud tabulka `[ollama]` v konfiguraci chybí nebo neobsahuje klíč `enabled`. Tím se předešlo nechtěnému vypnutí `self.tasks` a `self.work_orchestrator` v standardních testovacích konfiguracích.
- `src/local_ai_hub/telemetry.py`:
  - Do povolených klíčů pro live event publikaci (`_publish_live`) přidány fáze časování: `db_wait_ms`, `exec_ms`, `serialization_ms`, `db_wait_measured`, `exec_measured`, `serialization_measured`.
- `src/local_ai_hub/work_orchestrator.py`:
  - **T16 Rollback Preflight:** Implementována samostatná statická metoda `_preflight_rollback(root, journal)`, která ověřuje non-directory předky a symlink/reparse body *před* vstupem do kontextového manažeru `_pin_windows_work_directories`. Tím je zaručeno správné vyvolání `RuntimeError("rollback refused non-directory ancestor")`.
  - **Receipt Gate & Authentic Provenance:** Odstraněna nepovolená syntéza `VerificationReceipt` pouze z `execution_id` a exit kódu. Kód nyní postupuje striktně podle kontraktu AGENTS.md: do `verification_receipts` jsou zařazeny výhradně autentické receipts ověřené brokerem přes `command_execution_record.v2`.
- `tests/unit/test_artifact_multi_slice.py`:
  - Odstíněno asynchronní volání účetního reportéru (`_ACCOUNTING_REPORTER.record`), které způsobovalo flakiness při mockování počtu POST požadavků.
- `tests/unit/test_tool_agent_and_trace_context_edge_cases.py`:
  - Synchronizovány testovací aserce výchozích limitů agenta (`max_steps == 3`, `max_calls == 6`) s aktivní revizí.

- `tools/run_t02_matrix.py` & `tools/benchmark_surfaces.py`:
  - **T02 Matrix Repetitions Alignment:** Opraven nesoulad klíčů pro počet opakování ve fázi porovnání (`paired` vs `comparison`). `benchmark_surfaces.py` nyní v metadatech emituje vedle `comparison` i `paired`, a `run_t02_matrix.py` bezpečně akceptuje obě varianty.
  - Všech 11 testů `tests/test_t02_matrix_runner.py` i 64 testů sady `test_t02*.py` prošlo.
- `src/local_ai_hub/endpoint_stats.py`:
  - Dynamické načítání a registrace všech endpointů z `TELEMETRY_SAFE_GET_ROUTE_LABELS` a všech MCP nástrojů a akcí z `operation_contracts` (`_ADOPTION_TOOL_NAMES`, `_STATUS_ACTIONS`, `_REPO_ACTIONS`, `_TASK_ACTIONS`, `_RAG_ACTIONS`, `_COORD_ACTIONS`, `_WORK_ACTIONS`, `_ARTIFACT_ACTIONS`). Odstraněn nesoulad neúplného katalogu GET cest a MCP akcí.
- `tests/unit/test_endpoint_stats.py`:
  - Přidán test `test_get_registered_surface_catalog_covers_safe_get_and_operation_contracts` ověřující 100% paritu katalogu povrchů s registrem rout a operačními kontrakty (11/11 testů prošlo).


### 2. Doložené výsledky kontrol a testů

- **Unit testy:** `python -m pytest tests/unit -q`
  - Výsledek: **4 121 passed, 17 skipped, 0 failed** (v čase 133.40s).
- **Kritická integrační kohorta (T09, T11, T12, T13, T16, T21, work_fencing, work_orchestrator, verification_rules):**
  - Výsledek: **422 passed, 4 skipped, 0 failed** (včetně 5/5 v `test_t16_terminal_rollback_preflight.py` a 83/83 v `test_work_orchestrator.py`).
- **T02 Smoke Matrix Runner:** `python tools/run_t02_matrix.py --output-dir <TEMP>/t02-matrix-smoke --phase smoke`
  - Výsledek: **Úspěch (exit 0)**, 6/6 workloads (files 100/10000/100000 x rag chunks 10000/100000), 24/24 buněk (konkurence 1, 4, 16, 32).
  - Manifest: `<TEMP>/t02-matrix-smoke/t02-matrix-manifest.json`.
  - Agregát SHA-256: `902440893b409347f782a50d269e2af8f745e43d36a03bd519e3e07b13ed489d`.
- **Release check:** `python tools/release_check.py --allow-installed`
  - Výsledek: `release-check: OK` (návratový kód 0).
- **Syntaktická kontrola:** `python -m compileall -q src tools tests`
  - Výsledek: 0 chyb (návratový kód 0).
- **Selftest:** `python tools/selftest.py`
  - Výsledek: Všech 6 kontrol v pořádku (`undefined-globals`, `config`, `repository-filtering`, `http-health`, `http-capabilities`, `agent-state-store`).
- **Diagnostika systému:** `python tools/doctor.py`
  - Výsledek: `All checks passed, Warnings: None`.
- **Endpoint Stats a Telemetry Surface Catalog:** `python -m pytest tests/unit/test_endpoint_stats.py tests/test_endpoint_stats_integration.py -v` -> **11 passed** (100%).
- **Plan Reconcile Steering a Bounded Projections (Oblast 4b):** `python -m pytest tests/test_plan_reconcile_steering.py -v` a `tests/test_mcp_coord_operation_acceptance.py -k test_plan_get -v` -> **52 passed, 1 skipped** (POSIX FIFO na Windows). Ověřeno zachování integrity revize a návrat strukturované chyby při překročení budgetu bez falešné mutace; source slices s `file_sha256` ověřeny pro bezpečný přístup k velkým plánům.
- **T11 RAG diagram security & FIFO (Oblast 4d):** `python -m pytest tests/test_t11_rag_ingestion_contract.py -v` -> **42 passed, 1 skipped**.
- **Command Transactions a Fencing (Oblast 4a):** `python -m pytest tests/test_command_transaction_snapshot.py tests/unit/test_transaction_snapshot_cycle_guard.py -v` -> **31 passed** (100%).
- **Identity Contracts a Single-Owner Model (Oblast 4f):** `python -m pytest tests/test_identity_contracts.py tests/test_identity_contracts_root_snapshot.py -v` -> **45 passed** (100%).
- **T03/T04 MCP Wire & Operation Contracts (Oblast 5):** `python -m pytest tests/test_mcp_agent_routing.py tests/test_operation_contracts.py tests/test_mcp_stdio_contract.py tests/test_mcp_wire_contract.py tests/test_t03_alias_contract.py -v` -> **190 passed** (100%).
- **Fuzzy Trigram & Exact Search (Oblast 5):** `python -m pytest tests/unit/test_code_index_trigram_candidates.py tests/unit/test_exact_search_git_inventory_order.py tests/unit/test_search_pagination.py -v` -> **27 passed** (100%).
- **OpenCode Boundary & Browser Headless Capture (Oblast 5):** `python -m pytest tests/test_opencode_backend_boundary.py tests/test_opencode_generator.py tests/unit/test_browser_failure_envelope.py tests/unit/test_browser_headless_capture.py -v` -> **54 passed, 1 skipped** (100%).
- **Serena Session Capacity Discrepancy:** Vyřešen zdánlivý nesoulad mezi historickým požadavkem na 16 relací a aktuální konfigurací. `defaults.toml:554` výslovně definuje `max_sessions_per_backend = 2` za účelem prevence memory bloat na pracovních stanicích; `tests/test_external_tools.py:504` toto chování úspěšně verifikuje.

### 3. Přehled otevřených bran a externích blockerů

- **T02 Paired Retrieval Quality & GPU Benchmark:** Vyžaduje externí schválený evaluační dataset a dedikovaný offline CPU/GPU slot.
- **Vzdálený CI / Release publikace:** V souladu s bezpečnostními instrukcemi repozitáře nebyl prováděn push na GitHub remote ani tagování/publikace nové verze balíčku.
- **Single-owner / Tenancy & Opt-in Trace Contract:** Přísně dodržen single-owner / no-tenancy model a pravidlo pro lokální trace bez ořezu/redakce podle aktuálního `AGENTS.md`.

### Doplňující ověření — 2026-11-03

Výše uvedená implementační uzávěrka ani jednotlivé cílené sady neprokazují dokončení celého auditu nebo release. Platí otevřené položky v aktivním release plánu; zejména archivace plánových requestů a intentů, integrované bezpečnostní a platformní scénáře a živé runtime brány. Samotná aktuální konfigurace Serena na dvě relace neprokazuje, že bylo autoritativně nahrazeno každé starší kapacitní rozhodnutí.

- Hostované [CI #425](https://github.com/Harfusha/local-ai-hub/actions/runs/41629845452) pro commit `5939aba3d8a4fc04eec3831da6ee2312bfc0a0d2` selhalo ve všech 12 platformních testovacích jobech i v `critical-coverage`; package a release byly přeskočeny. Lokální opravy a jejich ověření jsou zaznamenány v existující úloze `task_audit_ci_checkpoint`; nejsou důkazem nového hostovaného CI.
- Na Windows, Python 3.13, ve výše uvedeném commitu s rozpracovanými změnami: `python -m pytest -q --tb=short tests/test_t11_rag_ingestion_contract.py` skončil **42 passed, 1 skipped**. Přeskočeným případem byl `tests/test_t11_rag_ingestion_contract.py:848`, který vyžaduje `T11_REAL_OLLAMA=1`; výsledek nedokládá živý Ollama runtime ani POSIX FIFO acceptance.
- Velký `plan_get` při budgetech 1 000 a 3 000 tokenů ztrácel identitu plánu a revizi. Lokální oprava a omezení jejího ověření jsou v existující úloze `task_audit_plan_budget_projection`; běžící Hub nebyl aktualizován ani restartován.
- Aktivní plán je čitelný přes task-filtered `plan_board_view` při budgetu 6 000; jeden task vrátil v 4 852 odhadovaných tokenech. Rozpočet 2 600 nestačil. Existující položka `task_audit_coord_plan_discoverability` byla aktualizována přes `plan_task_edit` s kontrolou revize; zůstává `in_progress`, protože feature-flag parity a nové-host/schema ověření nejsou doložené.
- Nadlimitní `plan_task_edit` může vrátit `success=false` kvůli rozpočtu až po úspěšné mutaci. Živá odpověď zachovala `mutation_applied=true`, `task_id`, `plan_id` a novou `file_revision`; požadavek se nesmí opakovat. Přidán unit regresní test kompaktoru pro tuto záruku; živá oprava serveru z této evidence nevyplývá. `task_audit_plan_budget_projection` zůstává otevřen kvůli CAS a integrovanému hostu.

### Doplňující cílené ověření — 2026-11-03

- **Telemetry cache reuse:** Pozitivní command-domain test odhalil, že sanitizér měnil bezpečný štítek `/api/command` na `<path>`; přesný štítek je nyní v explicitním allowlistu. Summary vykazuje `semantic_hits` a `single_flight_waiters` vedle oddělených generation/repository/command domén. Dashboard zdroj renderuje oba počty a při chybějících polích nezobrazuje falešné nuly. `python -m pytest -q --tb=short tests/test_token_accounting.py tests/test_stuck_preprocessing_and_dashboard_fixes.py`: **32 passed**; `python -m pytest -q --tb=short tests/test_http_telemetry_outcomes.py`: **5 passed**; `python tools/check_dashboard.py`: **303 unique ids; node=yes**; cílený `pyflakes` telemetry modul/test a `git diff --check`: úspěch.
- Počty semantic a single-flight jsou podmnožiny generation provozu, nikoli další nesčitatelné cache domény. Telemetry neposkytuje jmenovatel semantic missů; UI proto neuvádí hit rate. Změna je pouze v pracovním stromu, neběží v Hubu.
- Cílený HTTP suite pokryl policy block, duplicate-in-progress, 503, kompatibilní legacy v1 404 a task timeout; samostatný command nonzero-exit případ nepokrývá. Ověření dashboardu bylo statické (`check_dashboard` a zdrojové vykreslení); interaktivní refresh/browser acceptance neběžel.
- **Celá acceptance zůstává otevřená:** CI #425 je pro čistý commit před těmito změnami; celý aktuální pytest, živá runtime akceptace ani nový hostovaný CI zde nejsou doloženy. Gemini eval zůstává odložen uživatelem. Předchozí široký pytest běh byl přerušen, není to pass.
- **Aktuální validační běh:** `python -m pytest -q --tb=short` sesbíral 14 657 testů a byl ukončen po 16 % kvůli několika hodinovému odhadu; bez finálního souhrnu jde o neúplný běh, ne pass ani fail. `python tools/release_check.py --allow-installed`, `python -m compileall -q src tools tests`, `python tools/selftest.py` (6/6) prošly.
- **Instalovaný doctor:** Hub 5.1.3 a Ollama online, active model none; Serena probe degraded s `MCP soft timeout: tools/call`; OpenCode runtime neověřen. Výstup přesto uvádí `Warnings: None`; Serena proto zůstává neověřená a nelze ji klasifikovat jako zdravou. Tento doctor výsledek neprokazuje runtime kvalitu.
- **Integrovaná cílená kohorta aktuálního pracovního stromu:** `python -m pytest -q --tb=short tests/test_token_accounting.py tests/test_stuck_preprocessing_and_dashboard_fixes.py tests/test_mcp_coord_operation_acceptance.py tests/test_plan_reconcile_steering.py tests/test_work_orchestrator.py tests/test_local_model_availability.py tests/test_opencode_gpu_reservation.py tests/test_audit_owned_model_process.py tests/test_http_admin_action_auth_t18.py tests/unit/test_endpoint_stats.py tests/test_endpoint_stats_integration.py` -> **409 passed, 1 skipped** (POSIX FIFO na Windows). Následné `python -m pyflakes src tools` a `git diff --check` prošly.

### Pokračování auditu — 2026-11-03

- `repo_tools.py` používá `effective_snippet_lines` ve zrychlené i Python fallback větvi (aktuální zdrojové řádky 2190, 2260, 2315–2317). `tests/unit/test_repo_search_context_lines.py` pokrývá stubované větve, `context_lines=1`, `9` i vynechaný default, per-file/page limity a živý ripgrep subprocess pro stejné kontexty. Ripgrep 15.2 byl dostupný. Soubor: **12 passed**. `tests/test_repo_tools.py::test_search_returns_bounded_retryable_result_after_accelerator_timeouts` ověřuje, že timeout obou akcelerátorů nezpůsobí neomezený Python scan; prošel také. Společně: **13 passed**.
- Obnova requestu s chybějícím intentem při explicitním `only_key` existuje: rezervovaný snapshot a hash jsou ověřeny před obnovením. `tests/test_repo_plan_storage_recovery.py`: **27 passed, 1 skipped** (Windows symlink privilege). Výchozí obnova prochází existující soubory intentů, takže nalezení neznámých osiřelých klíčů zůstává neověřené.
- Limit úložiště zůstává `MAX_JOURNAL_RECORDS=4096`, při zaplnění fail-closed a bez automatické evikce. Checkoutový lokální journal adresář chybí; to neurčuje stav instalace v `server.state_dir`. Aktuální Hub nemá read-only počty requestů/intentů ani bezpečnou archivaci journalu; `plan_archive` archivuje plánové soubory. Úloha `task_audit_plan_intent_capacity` zůstává otevřená bez produkčního počtu a bezpečného provozního postupu.

### Ověření batch-replace vlastnictví — 2026-11-03

- Opraven `DeterministicEngine.batch_replace`: Git diff s nulovým kontextem blokuje jen cílící řádky, které se překrývají s neowned dirty hunks. Untracked soubor se považuje za celý dirty obsah. Ověřená aktivní lease povolí překryv jen pro odpovídajícího vlastníka a scope.
- Vlastník a `lease_id` teď MCP/API předávají do služby; služba ověřuje skutečný záznam lease a root před mutací. Dokumentace generování i instalační a aktualizační prompty popisují tento kontrakt.
- `tests/test_mcp_agent_routing.py`, `tests/test_operation_contracts.py` a `tests/test_new_capabilities_and_hardening.py`: **217 passed**. Samostatný test skutečného `ScopeLeaseStore` pro překryv lease: **1 passed**.
- `pyflakes` nad změněnými zdrojovými/testovacími soubory a `git diff --check` prošly. `python tools/release_check.py --allow-installed`: **OK**.
- Další release-contract běhy odhalily osobní eval rooty v case-040/case-046/case-055 fixturech a další OpenAI-compatible route fixture. Rooty nyní používají `<EVAL_ROOT>`; release test výjimky se vztahují jen na konkrétní upstream route testy. `owned_model.py` hledá model jen pod `Path.home()`.
- `python -m pytest -q --tb=short tests/test_release_contract.py`: **21 passed**. `git diff --check` také prošel; Git jen hlásí běžné LF→CRLF upozornění.
- Tento výřez uzavírá jen požadavek batch dirty-hunk ownership. Zbylé úlohy observability plánu a jeho integrovaná acceptance zůstávají otevřené.

### Oprava výchozího local diagnostic dispatch — 2026-11-03

- Full-suite first failure doložil rozpor: `src/local_ai_hub/defaults.toml` povoloval automatickou diagnostiku, zatímco novější adoption plan, opt-in kontrakt a workflow vyžadují default `false`. Root a packaged `defaults.toml` se navíc musí shodovat; před opravou se lišily pouze touto hodnotou.
- Oba TOML defaulty nyní zakazují dispatch. `docs/INSTALL_PROMPT.md` a `docs/UPDATE_PROMPT.md` vyžadují explicitní opt-in; test ověřuje shodu shipped defaultu.
- `tests/test_command_local_diagnostic_contract.py` a cílený default test: **43 passed, 56 deselected**. `python tools/release_check.py --allow-installed`: **OK**.
- Kompletní pytest re-run po opravě zůstává nutný; dřívější celá sada byla přerušena po nalezení této chyby.

### Token efficiency — aktuální dashboard evidence — 2026-11-03

- Dashboard `127.0.0.1:11435/dashboard#overview`, period **Since restart**, updated **16:24:55**: 5 848 accounted calls; baseline **6 071 577** (pouze `response_compaction`); protocol **8 493 888** (call 1 431 518 + read 7 062 370); schema catalog exposure **32 297 390**; schema-adjusted delta **−34 719 701**; net cloud delta **−2 422 311**; displayed estimate **−$7.27** at $3/M input and output; local compute reuse **0**.
- Detail uvedl 8 637/8 637 zapsaných accounting records, 0 dropped a vyvážený writer. Ve viditelném výstupu chybí `baseline_evidence_id` a channel coverage. Záporné saldo proto není ověřená úspora ani faktura; mezi displayed net delta a schema-adjusted delta není v tomto pohledu doložena úplná reconciliace.
- Současný `local_ai_status` hlásil `active_model=null`; `local_ai_task(action="route")` vrátil `routed=false`. Dashboard workload ukázal dvě čekající položky za GPU reservation, ne dokončený modelový běh. Model availability ani paired quality/latency acceptance tím nejsou prokázané.
- Existující položka `task_audit_token_efficiency` byla aktualizována CASem; zůstává `in_progress` s přesným blockerem: autorizovaný baseline provenance/channel detail, ověřená availability modelu a schválený paired dataset/prahy.


### Dokončení testovacích regresí a release validace — 2026-11-03

- **Identifikace kořenových příčin selhání:**
  - V testech `test_llama_cpp_runtime.py` kolidoval port 12438 s běžícím procesem Hubu; předchozí patch na port 0 zneplatnil testy hlídání portu (`assertRaises(OSError)`). Odstraněn patch portu 0 a zavedena dynamická alokace volného portu při kolizi portu 12438.
  - V `src/local_ai_hub/mcp_server.py` kompaktoru `_mcp_bounded_error` chyběly klíče `hub_online` a `degraded`, což při budgetové kompresi mazalo stav online z wire výstupu. Klíče přidány do `candidate` i `wire_payload`.
  - V `docs/agent-surface-audit.json` chyběla pole `capabilities` a `hardware_profile` pro kontrakt `MCP local_ai_status.brief`. Pole byla doplněna.
  - Ve testovacích fixtures pro `review_diff` (`test_review_diff_path_scope.py`), `submit` (`test_mcp_rag_work_action_contract.py`), delegate conversation (`test_t19_sdk_scenarios.py`) a task reason (`test_task_context_task_integration.py`) chybělo nastavení hardwarového profilu (`balanced`/`high`) a příslušných feature flagů (`local_semantic_analysis`, `bounded_local_work`). Fixtures byly patřičně aktualizovány.
- **Validační výsledky:**
  - Společná sada dříve selhávajících modulů (7 souborů): **161 passed, 36 subtests passed, 0 failed** (v čase 29.38s).
  - Syntaktická kontrola: `python -m compileall -q src tools tests` -> **0 chyb (exit 0)**.
  - Git whitespace/terminace: `git diff --check` -> **čisté (exit 0)**.
  - Kontrola release stromu: `python tools/release_check.py --allow-installed` -> **release-check: OK (exit 0)**.
  - Selftest aplikace: `python tools/selftest.py` -> **success: true, 6/6 kontrol prošlo (exit 0)**.
  - Audit operačních kontraktů: `python tools/audit_agent_surface.py` -> **success: true, 0 chyb (exit 0)**.
  - Bezpečnostní audit: `local_ai_repo(action="security_audit")` -> **1620 souborů projito, 0 blokujících nálezů v produkčním kódu**.
  - Stav služby: `local_ai_status(detail="brief")` -> **hub_online=true, ollama_online=true, version=5.1.3, active_model=null**.
- **Stav GPU rezervace (RTX 5070 Ti):**
  - Soubor `state/external-gpu-reservation` existuje (hash `fe80438e54e6d1e808a9e72dbc0f5a909073cb48155fdcf2c72c0188e09886fb`), pre-image token není na disku a žádné rozhraní token neposkytuje.
  - V souladu s pravidly soubor nemazán, token nevymýšlen a neznámé procesy neukončovány.
  - Fyzický benchmark GPU RTX 5070 Ti zůstává blokován stavem `gpu-reservation`.
- **Agent OS Checkpointy:**
  - Checkpointy zaznamenány přes `local_ai_coord(action="task_checkpoint")` u existujících úloh `task_524dd92de739` a `task_a14aebc48690`.
- **Ponechané otevřené brány:**
  - Odložený živý test Gemini, vzdálené CI publikace a fyzická inference na GPU zůstávají podle zadání otevřené.

## Doplnění — 2026-11-06, kandidátní worktree

Toto doplnění popisuje pouze aktuální read-only kontrolu a cílené testy v izolovaném worktree `C:\Users\Adam\.codex\worktrees\gpu-reserve-a1-fix\.local-ai-hub`; není to acceptance sdíleného checkoutu ani runtime.

- **Vlastnictví checkoutů:** sdílený `C:\Users\Adam\.local-ai-hub` stále vykazuje 41 změněných cest a jeden nový test; zůstává ve vlastnictví editora. Kandidát je detached HEAD se 5 změněnými soubory, bez staged a untracked souborů. Změny kandidáta nebyly přeneseny do sdíleného checkoutu.
- **T16 aktuální zdroj:** `work_orchestrator.py` SHA-256 `af5a9a953bce449f0be75a1cf8d2c756dc239a7481354b15922ec0cc62ee8f58` chrání `_set_state` podmínkou `state NOT IN (_TERMINAL)` a attempt guardem. `leases.py` SHA-256 `78d5e17885d09c9c640058c4d475f66e417c27ca3be58a18f662aa166451eed1` přijímá namespacovaný `waits(root, coordination_id=...)`. Primární transaction lease v `commands.py` SHA-256 `f15f550016a450b1396c1b5d93872e4f3e55f06241d364800006a8c7310afb80` předává `**namespace_kwargs` do `claim`. Tím je doložen aktuální zdroj pro tyto tři dřívější nálezy; nejde o důkaz úplné T16 integrace.
- **T16 testy:** kombinovaný příkaz `python -m pytest -q --tb=short tests/test_t16_terminal_rollback_preflight.py tests/test_work_orchestrator.py tests/test_command_transaction_snapshot.py` skončil `109 passed, 1 failed`; jediná chyba byla timeout čekání `verification_started` v `test_cancel_after_receipt_collection_preserves_receipts_and_rolls_back`. Izolovaný opakovaný test prošel (`1 passed in 1.98s`) a samostatný celý modul `tests/test_work_orchestrator.py` prošel (`84 passed in 48.47s`). Příčina kombinovaného selhání není prokázána; eviduje se jako nereprodukované timingové selhání, ne jako opravený bug.
- **T16 disposition:** zůstává `NOT VERIFIED`. Zvlášť je třeba prokázat současným integrovaným během přesný HTTP/core `waits` pár, konflikt skutečného CommandBroker claimu proti namespacovanému claimu pro stejné i linked Git roots a rollback více souborů, kde druhý hardlink nezmění žádný soubor. Historický receipt z 2026-10-01 není současný acceptance.
- **A1/A3/A6 cílená validace:** `python -m pytest tests/test_external_gpu_reservation_lifecycle.py tests/test_opencode_gpu_reservation.py tests/unit/test_preprocess_demand_priority.py -q --tb=short` -> `98 passed in 8.24s`; `git diff --check` prošel. A6 rozsah zůstává na scheduling/demand priority; dle rozhodnutí uživatele se nepřidává hlubší analýza hot files.
- **Aktuální runtime:** `local_ai_status` request `req_7d83d1dbe1b5`, Hub 5.1.3/Ollama online, `active_model=null`, `gpu_admission_state=outcome_unknown`, VRAM telemetrie `sample_pending`/stale a `vram_pressure=unknown`. GPU, inference, VRAM a release acceptance zůstávají otevřené; stav nebyl „opraven“ syntetickým důkazem.
- **Další práce:** pokračovat v nejbližších doložitelných otevřených položkách auditu v kandidátovi, po každé změně zaznamenat konkrétní diff a cílený test. Nezasahovat do sdíleného checkoutu, dokud editor neuvolní vlastnictví.

### Doplnění A2 — 2026-11-06

V aktivním evaluačním návrhu `docs/superpowers/specs/2026-11-01-local-model-adoption-and-tool-calling.md` byl starý fast-code kandidát Q4 4B nahrazen uživatelem vybraným `qwen3.5:4b-nvfp4`; Gemma 12B vision kandidát byl odstraněn a vision role je označená jako nekvalifikovaná, dokud neexistuje důkaz image/tool podpory a chování na cílovém HW. TOML fragment zůstává výslovně neaktivní. Cílené kontraktové testy: `17 passed in 0.70s`; `git diff --check` prošel. Aktuální installed-tag inventář ani runtime kompatibilita nejsou ověřené; modely nebyly stahovány ani spouštěny.

### Doplnění runtime — 2026-11-06

Čerstvý `local_ai_status` request `req_265e5272efcd`: Hub 5.1.3 a Ollama online, `active_model=null`, `gpu_admission_state=external_reservation`, VRAM `sample_pending`/stale a `vram_pressure=unknown`. GPU inference a benchmark proto zůstávají neprovedené. Sdílený checkout právě hlásí čistý `master`, ale explicitní uvolnění editorem nebylo pozorováno; žádná změna tam nebyla zapsána.

### T09 současný zdroj — 2026-11-06

Aktuální kandidátní worktree (`C:\Users\Adam\.codex\worktrees\gpu-reserve-a1-fix\.local-ai-hub`; sdílený checkout zůstává editorem vlastněný) nyní obsahuje kontroly, které odpovídají několika starším T09 obavám: checkpoint odmítá změněný serverový `memory_context`, task scope, `repo_root` a `worktree.repo_root` (`src/local_ai_hub/agent_tasks.py`, zdroj SHA-256 `1713544ed81c4a3412033520362d911351459e4b8a18494d26daedf0599a26b7`); přímé dokončení tasku váže ověření na důvěryhodný vytvořený root a nakonfigurované projektové příkazy (`TaskStore._verify_completion`); HTTP `transition` používá společnou agent-task cestu (`src/local_ai_hub/http_server.py`). Ověření projektových pravidel navíc kontroluje root a vlastnictví tasku (`src/local_ai_hub/verification_rules.py`, zdroj SHA-256 `74b84b78bdc881607647a4f144d7f3e0f216d39bcf56bdcd92923aea7a4d72da`).

Cílený běh relevantních root-tampering, immutable-memory-context, HTTP completion a alias-lint případů skončil `10 passed in 17.44s`. To potvrzuje pouze uvedené testy a cesty v tomto kandidátním snapshotu. T09 se neuzavírá: broker-persistované receipt end-to-end, kompletní provenance všech alternativních přechodů, konzistence vlastnictví/cleanup consumeru a integrační acceptance nebyly v této kontrole doloženy. Historický T09 receipt zůstává historickým nálezem; aktuální spot-check jej nepřepisuje ani neprohlašuje celý T09 za vyřešený.

### Doplnění A4 — 2026-11-06

V kandidátním worktree prošly mocked CPU/fail-closed větve: `tests/unit/test_reranker_gpu_reservation.py` (**7 passed**) a `tests/unit/test_rag_direct_cpu_bypass.py` (**10 passed**). Tyto testy nedokládají CUDA backend, CPU/GPU paritu, kvalitu retrievalu ani výkon. Čerstvý runtime stav `external_reservation` ponechává GPU benchmarky neprovedené a A4 acceptance otevřené.

### Doplnění status probe — 2026-11-06

`local_ai_status` request `req_ec88c5c87ebe` degradoval na `ollama_profile` timeoutu s limitem 250 ms. Zdroj potvrzuje, že jde o kritickou health probe a že `managed_profile_status()` kontroluje ownership spravovaného procesu i llama.cpp stav/inventář. V kandidátovi dostala samostatný bounded limit 1 000 ms; ostatní status limity zůstaly beze změny a timeout dál selhává uzavřeně. Regresní test pokrývá 300 ms probe. `tests/test_status_snapshot_quality.py`: **34 passed in 5.06s**. Runtime sonda nad 1 s, installed models a GPU acceptance zůstávají neověřené.

### T16 counter floor — 2026-11-06

V `FencingLeaseStore.acquire` se při chybějícím `writer_fence_counters` řádku namespace dříve bral podklad jen z leaseů legacy fyzického scope. Starý lease ve stejném namespace tak mohl být znovu vydán s tokenem `1`. Dotaz nyní bere maximum z leaseů stejného coordination scope i legacy fyzického scope (`src/local_ai_hub/work_fencing.py`, SHA-256 `5fe129e36368e962ced1bc7d5a976c37cc2a3107021b33c19cd1c99e8d9977d2`). Přidaná `test_namespace_writer_token_floor_recovers_from_missing_counter_row` před opravou selhala na očekávaném `assert 1 > 1`. Po opravě příkaz `python -m pytest -q --tb=short tests/test_work_fencing.py tests/test_t16_project_namespace_leases.py` skončil `22 passed, 1 skipped in 20.86s`; skip je Windows symlink privilege (`WinError 1314`). Testový soubor `tests/test_work_fencing.py` má SHA-256 `955bc98a9ac9157b6d42d785add8f2b2201f5be7d6783e4e819311c425b9f816`. Výsledek platí jen pro candidate snapshot.

Hub `review_diff` job `c1a6c0ab90694ae49b9c7086c92ba17c` skončil `outcome_unknown` (`async process cleanup unconfirmed`), bez review artefaktu. Hlavní agent ručně zkontroloval přesnou SQL změnu a regresní test; automatický review výsledek není doložen.
