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

