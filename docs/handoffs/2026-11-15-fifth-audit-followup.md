# Local AI Hub — aktuální předávací plán pro agenta po pokračování implementace

**Datum:** 15. listopadu 2026  
**Repozitář:** https://github.com/Harfusha/local-ai-hub  
**Pull request:** https://github.com/Harfusha/local-ai-hub/pull/8 (**draft**, neslučovat před úplnou verifikací)  
**Větev:** `fix/fifth-audit-hub113-140`  
**Výchozí `master`:** `af2a64e3d23909098884a81a9363b2cfe6bbd9be`  
**Poslední implementační SHA při sestavení tohoto dokumentu:** `987fd7bd280ce63f7f1cbdd229f6c31cbd17e25b` (ověř novější HEAD před prací)

> Tento dokument aktualizuje původní `docs/handoffs/2026-11-15-fifth-audit-agent-remaining.md`. Obsahuje **především zbývající práci**, nikoli opakovaný seznam toho, co už je commitnuté. V žádném případě nevydávej v6.0.0, nepřepínej `master`, neprohlašuj CI za zelené a neměň hostitelské nastavení, dokud nejsou doložené níže uvedené akceptační podmínky.

## 1. Ověřený stav v GitHubu

- Draft PR #8 je skutečný GitHub PR. Reálné změny jsou na jeho větvi, ne v `master`.
- GitHub Actions běh **`43726349869`** (commit `bf0e88510ccf…`) má PASS **`lint`**, **`fast-contract`** a **`critical-coverage`**. Podařilo se tím na tomto commitu vyřešit dřívější neúspěšné poměrové pokrytí `commands.py` bez snížení baseline.
- Ve starším běhu na počátečním PR commitu `49779127…` (**`43716911513`**) prošlo **12/12 `platform-smoke`** kombinací Linux, macOS a Windows s Pythonem 3.11–3.14; testy lint a typing také prošly. Tento starý commit měl ale **1 fast-contract failure** a **46 full-integration failures**, kritické pokrytí proto bylo v daném běhu přeskočeno.
- Výchozí `master` měl při Linux/Python 3.14 interní chybu pytestu `WindowsPath`, která zabránila řádnému výpisu výsledků. **Nelze z ní tvrdit, že všech 46 testů v PR jsou nové regrese.** Po opravě pytestu jsou nyní viditelné.
- Následné commity opravily řadu těchto selhání (mimo jiné chybějící skill, bezpečné root policy, parser, HTTP DTO kompatibilitu, preprocessor schema fallback, telemetry route allowlist, instalační payload test), ale **kompletní plný integrační běh na posledním SHA dosud není potvrzen jako PASS**. Poslední relevantní Actions běhy byly ve frontě.

## 2. Implementované opravy — znovu neimplementovat bez důkazu nové chyby

| Oblast | Co již existuje ve větvi |
|---|---|
| Testovací infrastruktura | `tests/conftest.py`: automatické cachování úspěšných testů vypnuto, lokální opt-in, žádný zapisovaný pytest cache v problematickém report hooku; CI `NO_TEST_CACHE=1` a JUnit artifacts. |
| Pokrytí | `.github/workflows/ci.yml` rozšiřuje Windows critical cohort o reálné větve `commands.py`; existuje doložený PASS na uvedeném starším commitu. |
| Host CLI diagnostika | `dashboard_frontend.py`: Codex TOML, Antigravity JSON, bounded/no-symlink read, rozlišení registrace a skutečného handshake. |
| Moderní UI DTO | `ui_static/app.js`: skutečné `/api/models` a `/api/telemetry/timeline` payloady, správné read/write `/api/preprocess` akce, page state a stale responses; task root paginace používá explicitní `scoped_page=true`. |
| Task API | `http_scoped_tasks.py`, `http_server.py`: omezené root-scope filtrování před stránkováním, s přiznanými neúplnými výsledky; starý GET kontrakt zůstává výchozí, nová semantika je opt-in. |
| Repository security | `repository_scope.py`: explicitně prázdný `security.allowed_roots` = deny-all, na rozdíl od chybějícího nastavení. |
| RAG | `preprocess.py`: CAS / stale protection, fallback na starší databáze bez `file_refs_revision`, rozlišení legacy opaque hashů; `rag.py`: živé omezené bytes před indexací, nedůvěřovat starému override, velikost override i reálného souboru se ověřuje. |
| Structural search | PHP/TS/JS discovery, deterministické pořadí, `file_offset` / `next_offset` přes 400 souborů, protaženo až do MCP; `tests/test_structural_search_php_contract.py`. |
| Evidence | `evidence_merge.py`: max 10 MiB snapshot read, hash a file identity, nofollow/symlink protection, `partial`, `omitted_lines`, `requested_end_line`, `returned_end_line`, `read_at`, `revision_verified`, hash-bound recovery descriptor. |
| Analýza a telemetry | `unified_diff_parser.py`: nový diff header není deleted line; `token_router.py`: platný rozsah bez skóre dostává neutrální score; nové statické HTTP routes jsou zachované ve safe telemetry labels. |
| Release pravdivost | `tools/generate_audit_acceptance.py` a `audit_acceptance.json`: žádné syntetické `CI_GREEN`, soukromé lokální cesty nejsou součástí zdrojů; perf gate jasně říká synthetic-only. |
| Skills | Přidán chybějící `skills/token-economizer/SKILL.md`; testy vlastníka a opakované instalace chrání uživatelské úpravy. |
| Browser CI | Pokud Chromium zkolabuje při samotném startu v zygote, dva testy to nyní výslovně označí za **SKIP / browser environment unavailable** (nikoliv PASS). Browser E2E zůstává bez živého důkazu. |

## 3. P0 — bezpodmínečné další kroky

### P0.1 Zelený konečný HEAD, žádný merge podle dřívějšího commitu

1. `git fetch origin && git switch fix/fifth-audit-hub113-140 && git pull --ff-only`, zaznamenej SHA a `git diff master...HEAD --check`.
2. Zkontroluj Actions pro **aktuální** SHA, včetně `fast-contract`, lint, mypy Py3.11 a Py3.13, všech 12 `platform-smoke`, Linux/Python 3.14 full integration, Windows critical coverage a následné `package`. Testovací cache musí být vypnutá.
3. Na vhodném čistém stroji zopakuj cílené testy, např.:

```bash
python -m pip install -e '.[dev]'
python -m pytest -q --no-cache \
  tests/test_dashboard_host_inspection.py \
  tests/test_dashboard_runtime_contracts.py \
  tests/test_structural_search_php_contract.py \
  tests/test_http_scoped_tasks.py \
  tests/unit/test_evidence_merge.py \
  tests/unit/test_preprocess_rag_pending.py \
  tests/test_rag_incremental_index_io.py \
  tests/test_audit_acceptance_truth.py \
  tests/test_companion_skill_installation.py
python tools/release_check.py --allow-installed
```

4. U každé nezelené položky ulož **run URL, job ID, commit SHA, reprodukční command, prvních relevantních 100 řádků tracebacku**, teprve potom oprav příčinu. Nikdy neschovávej selhání snížením thresholdů, `xfail` bez důkazu, novou implicitní autorizací nebo vynecháním testu z CI.

**DoD:** kompletní required workflow pro přesný konečný SHA včetně wheel smoke je PASS; žádné silent skip kromě předem uznaných nevyhovujících externích prostředí.

### P0.2 Vyřešit zbylé plné integrační chyby podle odpovědnosti

Výchozí seznam z běhu `43716911513`, job `132820319834`, je **historická diagnostika, nikoli tvrzení, že na nynějším HEAD stále padá vše**. Agent má nejdříve znovu změřit, potom opravit jen zbývající reprodukovatelné chyby.

| Oblast | Konkrétní původní failing tests | Co zkoumat |
|---|---|---|
| Task checkpoint / plan consistency | `tests/test_plan_reconcile_steering.py` (4 scénáře), `tests/test_t14_context_pack_agent_memory.py` | Durable pending record, CAS při rollbacku, znovupoužití bindingu, idempotentní retry, žádná dvojí revize plánu. |
| MCP a agent identity | `tests/test_t21_coordination_namespace_bridge.py` (2), `tests/test_operation_contracts.py`, `tests/unit/test_mcp_parameter_normalization.py`, `tests/unit/test_guarded_context_inference.py` | Ověřit canonical absolute root, task_id pro guarded context a kompatibilitu API; **nepovolit scope spoofing**. Některé zastaralé testovací fixture byly mezitím aktualizovány. |
| RAG/scheduler | `tests/unit/test_preprocess_rag_current_contract.py`, `tests/unit/test_preprocess_rag_adaptive_batch.py`, `tests/unit/test_preprocess_demand_priority.py`, `tests/unit/test_search_mode_fusion.py` | Lost-index recovery, schema migration, fairness, preemption, skutečný content-hash CAS; rozlišit stálé chyby od fixture. |
| Modely a hardware | `tests/test_llama_cpp_runtime.py` (4), `tests/test_embedding_gpu_lease_heartbeat.py`, `tests/unit/test_mcp_gpu_reservation_release_contract.py` | Archive integrity a symlink policy, platformní varianty, liveness lease renew, kontrakt GPU release. Neprovádět živé model pulls ani GPU změny bez souhlasu. |
| Transport a návratové kontrakty | `tests/test_http_route_operation_acceptance.py::test_http_post_complete_acceptance`, `tests/test_shared_runtime_security_lifecycle.py`, `tests/test_t10_acceptance.py` | Autentizace a root policy, deadline/fail-closed, správná serializace; zachovat původní default GET tvar. |
| Procesy, tokeny a souběh | `tests/test_command_rollback.py`, `tests/test_token_efficiency.py`, `tests/unit/test_hub_006_bounded_workers_admission.py` | Process liveness a cleanup, trace metadata isolation, starvation budget. Procesový cleanup už byl upraven. |
| Browser | `tests/test_bounded_app_integration.py`, `tests/test_endpoint_stats_integration.py` | Chromium v runneru původně SIGABRT před vykreslením; nový přesně omezený SKIP není důkaz funkčnosti webu. Použít stabilní sandboxovaný browser runner s opravdovým E2E. |

**DoD:** explicitní klasifikace `fixed / existing regression / flaky / environment blocker` opřená o nejnovější log, zelené relevantní unit+integration a žádná změna politiky bez negativního testu.

### P0.3 Audit acceptance a release manifest s důkazy

`audit_acceptance.json` je správně fail-closed, ale pořád není plně integrovaný do trusted CI pro konkrétní SHA. Vytvoř důvěryhodnou revizi receipts z GitHub Actions se SHA zdroje, příkazy, test counts, OS/Python, stavem jobs, odkazy a SHA256 artefaktů; zkontroluj wheel/sdist/provenance a zablokuj produkční tag, pokud chybí libovolná povinná evidence. Nikdy nepřeváděj starý popis `SOURCE_VERIFIED` na green runtime acceptance.

## 4. P1 — zůstávající funkční práce z HUB-113–140

- **HUB-121/138:** end-to-end fault-injection závody RAG: source změní bytes během embeddingu, SQLite busy/restart, symlink swap, missing chunks v již cached idle generaci. Dokončit requeue/ref freshness bez mazání novějších dat.
- **HUB-124/126/132:** skutečné backend + browser testy celého sedmisekčního `/dashboard/next`. K dokončení **11→7 parity** stále chybí nativní Work, Coordination, Models, Bundles, Settings operace, audit přístupnosti, stavy 403/timeout/offline. Nepřepínej výchozí `/dashboard`, dokud není parity matrix fakticky zelená; legacy alias musí zůstat.
- **HUB-127/139:** nyní existuje offset continuation, ale PHP lexical fallback stále není spolehlivý parser: namespaced classes, methods, multiline, comments, AST/Tree-sitter fyzicky otestovat; offset není snapshot token a při změně souborů může přeskočit výsledky. Dodat snapshot-safe continuation nebo jasně vynutit revision guard.
- **HUB-128/129:** prokázat, že `partial`, hash-bound `slice_recovery`, `read_at`, `revision_verified` se zachovají přes MCP `projection` a všechny kompaktní formáty, že recovery znovu autorizuje root a kontroluje content hash, a že jednoobrázkový/jednozáznamový extrémní rozsah nehlásí falešnou úplnost.
- **HUB-133:** reálné cold/warm benchmarky: PHP/Python/TS, 10k/100k souborů, FTS, semantic embeddings (pokud nainstalované), memory/RSS, WAL/I/O a 5–10 opakování. `tools/perf_gate.py` je pouze syntetický mikrobemchmark, ne důkaz celé pipeline.
- **HUB-136:** ověřit install/update/uninstall skills na třech OS, bezpečné ownership manifesty, přechody Codex/Antigravity a nezaplňovat kontext duplicitními ponytail pokyny.

## 5. P2 — externí akceptace, bez nich nevydávat falešné PASS

| Gate | Důkaz potřebný pro uzavření | Aktuální přístup |
|---|---|---|
| HUB-002, HUB-108 | Clean install/update/uninstall Windows, Linux, macOS, wheel/CLI smoke | CI izolované stroje, žádný uninstall osobní služby bez souhlasu |
| HUB-103 | CZ/EN embedding relevance s reálným již nainstalovaným modelem | Bez modelu `BLOCKED_MODEL_ABSENT`, nestahovat |
| HUB-104 | Živý Codex MCP handshake v aktuální relaci | TOML registration != handshake |
| HUB-105 | Živá Antigravity relace a potvrzené eventy | Env proměnná != handshake |
| HUB-106 | Browser permission/egress/security v běžícím browseru | Startup crash / CI skip != acceptance |
| HUB-107 | GPU souběh, lease, OOM recovery, výkon na skutečném hostiteli | Bez souhlasu `BLOCKED_RESERVATION` |

Po každé úspěšné sadě ulož strojově čitelný receipt a do dokumentu doplň číslo Actions běhu, přesný SHA a výsledek. Dokončení kódu není totéž jako důkaz produkční připravenosti.

## 6. Instrukce pro agenta

1. Přečti tento dokument a existující `docs/handoffs/2026-11-15-fifth-audit-agent-remaining.md`; **prioritou je tento novější stav**.
2. Neopakuj hotové implementace z tabulky v sekci 2; pouze retestuj a oprav regresi, kterou lze reprodukovat.
3. Pracuj v existujícím PR #8, nezakládej duplicitní PR ani vedlejší kompletní rewrite. Změny seskupuj do revizovatelných commitů, zachovej bezpečnostní kontrakty.
4. Než označíš bod jako dokončený, dej mu nový test či důkaz, přesný Git SHA a CI job / JUnit / coverage link.
5. Do `master` a produkčního release sáhni až po **kompletních zelených povinných kontrolách** a výslovném vyhodnocení externích gate. Dokud chybí, nech PR jako **draft**.

## 7. Pokračování auditu — nové opravy po původním handoffu (15. 11. 2026)

Změny níže jsou **skutečně commitnuté do PR #8**, nikoliv jen návrhy. Jde o následné revize původního handoffu po SHA `987fd7bd`. Stav testů ber jen podle **finálního HEAD** z GitHub Actions, nikoliv podle starších úspěšných jobs.

| Commit | Změna | Ověření |
|---|---|---|
| [`a32c1b84`](https://github.com/Harfusha/local-ai-hub/commit/a32c1b84b6ee0d21f06b9001ee8a89f263421417) | Oprava deterministického CI dirty-tree: generovaný `token-economizer/SKILL.md` odpovídá verzované verzi; parity test ve fast-contract. | Zdrojová oprava + regresní test; nové CI zatím bez potvrzeného výsledku. |
| [`4742671a`](https://github.com/Harfusha/local-ai-hub/commit/4742671a93eaf53e25914bc865c1eb0434a2a02f) | `SinglePassIngestCache` omezuje nadbytečné reready stabilních souborů; při změně/nejistotě znovu čte hash; regresní test změny stejné velikosti. | Zdrojová oprava + test; čeká na integrační běh. Metadata jsou optimalizační indikátor, **nikoliv bezpečnostní důkaz SHA256**. |
| [`d7daf50c`](https://github.com/Harfusha/local-ai-hub/commit/d7daf50c47e388d5bc5b98f0575556109799fcd7) | GPU scheduler nevrací z `finally` (Python 3.14 SyntaxWarning a maskování výjimek); regresní test bezpečné nepřipravenosti i získání/uvolnění lease. | Zdrojová oprava + test; čeká na relevantní CI. |
| [`9af1600f`](https://github.com/Harfusha/local-ai-hub/commit/9af1600fa3c12648dc31199dfd6ba43ec55e5825) | CI už neduplikuje feature-branch push a PR, staré PR matrix běhy budou při dalších změnách přerušované; master/tag/schedule/manual zůstávají plně zachovány. | Nový test event policy ve fast-contract; ověření nového workflow nutné. |

### Nový konkrétní důkaz z již dokončeného staršího CI

- GitHub Actions [`43726782408`](https://github.com/Harfusha/local-ai-hub/actions/runs/43726782408) na `e04a4460` (starší SHA, **ne aktuální**): lint, mypy 3.11/3.13, fast-contract, critical-coverage = PASS. Dvanáct `platform-smoke` jobs mělo FAIL v `Reject tracked test mutations` kvůli přepisování `skills/token-economizer/SKILL.md` generátorem, což motivovalo commit `a32c1b84`. Linux/Python 3.14 full integration stále FAIL.
- V historickém full integration logu se vyskytl `test_t2_13_ingest_contention_isolated_across_roots` s opakovanými čteními snapshotu (`4 != 1`), na což míří commit `4742671a`. Zůstaly také další nesouvisející chyby, např. `test_command_rollback.py`; je potřeba získat **nový** aktuální failure list. Chromium zygote SIGABRT je environment blocker, nikoli úspěšný E2E.
- Starší výsledky nijak nedokazují PASS na novějším SHA. `package` byl u staršího běhu přeskočen, protože `needs` nebyly zelené.

### Nejbližší P0 kroky pro dalšího agenta

1. Na nejnovějším HEAD ověř Actions fast-contract, lint, typing, Windows critical-coverage, 12 platform-smoke, Linux/Python 3.14 full integration a až potom package/wheel smoke. Specificky očekávej kontrolu dirty-tree a `tests/test_ci_event_policy.py`.
2. Pokud integrační testy stále selhávají, klasifikuj pouze aktuální reprodukovatelná selhání. Nevyvozuj počet zbývajících chyb z historického logu `43726782408`.
3. U ingest-cache ověř chování na NTFS/reparse point, same-size/timestamp rollback a race s invalidate; správnost musí být důležitější než metadata fast-path. Nesmí být obejita root autorizace ani cryptographic provenance pro RAG.
4. Dokonči důvěryhodné exact-SHA CI/coverage/package receipts, RAG fault injection, dashboard parity a externí host/browser/GPU acceptance podle sekcí 3–5.

**Release stav:** PR zůstává draft; bez kompletního zeleného CI a externích důkazů není v6.0.0 připravena na merge/tag.


## 8. Navazující změny strukturálního vyhledávání

- [`19de2cc6`](https://github.com/Harfusha/local-ai-hub/commit/19de2cc62940bcece449c26edf0f32c45a4cd5ca): dovnitřsouborové pokračování `match_offset` + page boundary bez ztráty shod, přenos přes HTTP/MCP, strict bounds a PHP regresní testy. Číselný offset stále **není snapshot-stable**.
- [`f5b8609c`](https://github.com/Harfusha/local-ai-hub/commit/f5b8609c7d118983c89520c808520e04dd94edb1): `match_offset` doplněn do veřejného action-aware MCP JSON schema; ostatní akce tento parametr nesmějí přijímat.
- [`5173ec1f`](https://github.com/Harfusha/local-ai-hub/commit/5173ec1fb1806a7d2b51b865fe609bf73965f0d5): samostatný `file_offset` 0–100000 pro MCP velké repozitáře bez zvětšení limitu běžného `offset` u ostatních akcí.
- Předčasné `CI GREEN` nebo `release-ready` tvrzení je nepřípustné. Závěrečná akceptace vyžaduje exact-SHA CI a nové JUnit + packaging receipts.

## 9. Pokračování 2026-11-15: release privacy a managed llama.cpp

- [`9f65a234`](https://github.com/Harfusha/local-ai-hub/commit/9f65a234779c3d7347b00f6530f1646c6a7f9492): odstranění konkrétní osobní Windows cesty v `docs/FINAL_COMPLETION_PLAN.md`. Původní cesta byla doložena ve starším release privacy selhání.
- [`0f5bd52d`](https://github.com/Harfusha/local-ai-hub/commit/0f5bd52d8311cf566225c623dd40abd848009a92): `_find_server` vybírá `llama-server(.exe)` podle `_host_platform()` (cílový pinovaný balíček), ne podle `os.name` CI runneru. Odmítá symlinkovaný executable; aktualizované runtime fixture pro host OS.
- [`eb7d8b19`](https://github.com/Harfusha/local-ai-hub/commit/eb7d8b193f868b2d1fe176ad4f01bad2eb0f0356): oprava pořadí `from __future__` v runtime testu.
- [`a8ca62f5`](https://github.com/Harfusha/local-ai-hub/commit/a8ca62f5d57bd1d544a75e209a5b04af40fa2bf1): izolované mockování symlinku výhradně u modelu; nedotýká se validního executable.
- Starý CI run `43726782408` selhal v Python 3.14 na 35 testech a 12 platform-smoke jobech s dirty-tree detekcí; jeho výsledky se **nesmějí** zaměňovat za výsledky nové větve. Poslední aktuální run je ve frontě. Nové regression smoke testy a tracked-source privacy test jsou přidány do `fast-contract`. Je nutné získat zelené exact-SHA JUnit a distribuční packaging evidence, než PR opustí draft.

## 10. Další kontrola – přesné regresní testy a pokračování strukturálního vyhledávání (2026-11-15)

- Na starším HEAD `3ed1448e` měl GitHub Actions run [43749429162](https://github.com/Harfusha/local-ai-hub/actions/runs/43749429162) sedm selhání ve full Ubuntu/Python 3.14 (17 426 passed, 219 skipped). Ostatních 28 dostupných jobs mělo success s výjimkou následně skipped packaging.
- [`e51b85bd`](https://github.com/Harfusha/local-ai-hub/commit/e51b85bdc92330683796d432a6d72d2ba12afed5) opravuje cíleně scoped Laya shadow task ID, MCP test oddělující telemetrii, HTTP test při podporovaném hardware profilu, hostem izolovanou Windows Chrome detekci, preferenci validovaných pinned context cest a chybějící audit endpoint.
- [`28fafb9a`](https://github.com/Harfusha/local-ai-hub/commit/28fafb9a869d514728206e968bec0ea9ac8b7e0d) doplňuje soupis odpovědních polí do auditního záznamu `GET /api/repair-priorities`.
- Následný commit přidává regresní případy pro PHP namespaced/multiline deklarace a zakazuje falešné výsledky typu `fn:...` nebo `class:...` pocházející pouze z textového řetězce či komentáře.
- **Pozor:** žádný zde vyjmenovaný commit sám neznamená PASS finálního SHA; před merge a release ověř nejnovější GitHub Actions run včetně `integration (ubuntu-latest, 3.14)`, `critical-coverage` a `package`. Potvrzení modelů, GPU, browseru a host CLI vyžaduje externí akceptaci.
- **Nedokončeno:** cursor/revision guard pro strukturální vyhledávání mezi změnami stromu souborů a kompletní AST parser PHP; číselný file/match offset je nadále nestabilní při změnách repozitáře.

## 11. Continuation — RAG source races, no-follow reads and transactional fault injection

Repo state is read from the live PR #8 branch; the commit hash in the original document heading is historical and must not be taken as current HEAD.

- Post-embedding publication now compares bounded live source content and file identity for full and incremental RAG indexing. A mismatch rejects publication with retryable `source_changed_before_publish` and preserves the existing committed chunks.
- Pre-embedding file reads use `os.open` with `O_NOFOLLOW` where supported, verify path components against symlinks/reparse points, compare pre/open/post file identity, and reject escaped paths. Incremental code intentionally preserves the source path before validation instead of hiding a symlink through `resolve()`.
- Regression tests cover in-embedding edits, symlink swaps, aliased paths, wrong opened file descriptors, and publication failures. `tests/test_rag_incremental_index_io.py` is part of fast-contract CI.
- Fault injection now checks that a simulated SQLite timeout after deleting rows **rolls the transaction back** to the previous snapshot, and that one transient `database is locked` event retries the publish without rerunning embeddings.
- **Remaining concurrency boundary:** these are best-effort identity checks around the embedding/publish boundary, *not* a filesystem snapshot pinned across arbitrary concurrent edits. SQLite atomicity covers persisted rows; external filesystem mutation after the final check can still race. Do not claim stronger consistency.
- **Remaining:** verify *exact-HEAD* CI including full Ubuntu/Python 3.14 integration, all platform-smoke combinations, Windows critical-coverage and the installed wheel/package job. Browser, local GPU, live Codex/Antigravity handshake and model retrieval remain external acceptance blockers.

- Po SQLite busy/backoff se provádí opětovná kontrola aktuálních bytes před každým pokusem o publikování (full i incremental). Nový fault-injection test mění zdroj během prvního nezdařeného pokusu a vyžaduje fail-closed místo zapsání starého embeddingu.

## 12. Master drift and cancelled dashboard preview (2026-11-15)

- Master advanced to [`f14666a`](https://github.com/Harfusha/local-ai-hub/commit/f14666a77a816c09fd77676ab0d467ca17951dc3), intentionally removing the cancelled `/dashboard/next` preview, `ui_static` assets, and its preview-specific host diagnostics. Preserve the existing `/dashboard` interface. **Do not restore or reimplement the cancelled preview.**
- PR #8's CI had begun checking out a synthetic merge with this newer master and therefore attempted to run removed `tests/test_dashboard_host_inspection.py`. `tests/test_dashboard_runtime_contracts.py` also depended on a deleted preview-only JavaScript bundle. Drop these invalid preview-only tests and their explicit fast-contract entries; retain dashboard tests for the supported existing `/dashboard` interface and `tools/check_dashboard.py`.
- Windows critical-coverage on [run 43759417630](https://github.com/Harfusha/local-ai-hub/actions/runs/43759417630) failed because 100k-row `mark_stale_for_revision` exceeded a bounded write transaction (5346ms > 5000ms). Commit [`be07e14`](https://github.com/Harfusha/local-ai-hub/commit/be07e14f8947ae521c6e24a4e03e1a72324bd5a2) avoids repeated root normalization on the query hot path without raising the transaction budget. Validate on Windows critical-coverage in exact-HEAD CI.
- Do not infer PASS from old PR runs. Check all CI for the exact merged branch SHA before changing Draft status or release gates.

## 13. Structural-search inventory revision guard

- Structural search now exposes an `inventory_revision` token (SHA-256 over bounded source paths, relevant directory names, query/target, and filesystem stat metadata). Pass it as optional `expected_revision` when advancing `file_offset`/`match_offset` for the same root, query, and path. On detected changes return HTTP 409 `stale_search_revision` and restart from offset zero.
- The revision parameter is wired through deterministic search, services, the direct HTTP route and the MCP `local_ai_repo(action="structural_search")` schema. Structural searches bypass the repository TTL result cache so a stale cache cannot bypass revision validation.
- Original numeric-only offsets remain backwards-compatible but unprotected. This metadata revision is **not** a fully immutable content snapshot: metadata-preserving rewrites or changes after verification still require a pinned immutable Git worktree for a strict no-duplicate/no-omission guarantee.
- Inventory hashing is bounded and avoids file-content reads. A requested revision that cannot be verified fails retryably rather than silently accepting an unverified page.
- Regression tests cover successful continuation, insertion before page, same-file rewrite, changed query, invalid token, exact-file paging and old numeric behavior. Exact-HEAD CI and external integration gates remain outstanding.
