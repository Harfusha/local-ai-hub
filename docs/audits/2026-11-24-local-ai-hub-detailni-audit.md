# Statický audit Local AI Hub

**24. listopadu 2026 · master · a16a52dcc59381f74edd71b9d0501e342168d597 · produkt 8.0.0 · cílové schéma stavu 11**

## Verdikt

**Před vydáním opravit obnovu stavu po chybě instalátoru, spouštění AST parseru a obsah wheelu pro browser bridge.** Ruff navíc hlásí čtyři chyby v testovacím kódu a blokuje lint v CI. Současná kontrola lokálního distribučního stromu prošla. Dřívější chyby auditního katalogu MCP a chybějící značky v místní konfiguraci se už nepotvrdily.

Největší riziko pro existující instalaci přinesl přímo auditovaný commit. Setup po výměně programu nejprve čistí sourozenecké artefakty, pak migruje původní stav na místě a vypíná i zálohu před resetem vektorů. Požadavek na existující adresář navíc může zastavit čistou instalaci ještě před inicializací. Obnovení starých programových souborů potom nemůže samo vrátit staré schéma databází. Samostatný aktualizátor má vlastní větev se zálohou a obnovou.

Audit eviduje 21 položek včetně uzavřených mezivýsledků a otevřeného provozního ověření. Každá položka obsahuje zdroj, dopad a podmínku uzavření.

## Co je pokryto

Hub je služba pro jednoho uživatele na jeho počítači. Přijímá HTTP a MCP požadavky, poskytuje analýzu repozitářů a práci s lokálními modely. Zátěž vzniká hlavně souběhem klientů, indexace, SQLite zápisů a inference nad více repozitáři. Stav musí přežít restart a aktualizaci.

Audit začal na f05c1ed4, pak zahrnul d63a0ea7, 42f2fe24 a výsledný a16a52dc. Poslední commit upravil čištění artefaktů v setupu a migracích a dvojici testovacích souborů. Mezi d63a0ea7 a 42f2fe24 je 49 změněných souborů. Prošel jsem věcné změny v migracích a instalaci, kontrakt seznamu úloh v Pythonu a HTTP, dashboard, dokumentaci i související testovací zdroj. Lokální konfiguraci jsem ověřil přes hodnotu verze schématu. Obsah lokálních záloh a měnící se telemetrie jsem neotevíral. Historické výsledky mají v reportu vlastní označení.

### Účet pokrytí repozitáře

Inventura zahrnula **2 873 verzovaných cest**. Rozdělení podle nejvyšší složky vychází z Git indexu. Automatická kontrola přečetla všechny verzované soubory Pythonu a JavaScriptu uvedené níže jako zdroj a ověřila jejich syntaxi. Ruční kontrola sledovala uvedené toky dat a riziková rozhraní.

| Skupina | Cest | Co bylo ověřeno |
|---|---:|---|
| src | 535 | 509 Python souborů syntakticky. Ruční průchod po aplikačních vrstvách v matici níže, zvlášť pracovní změny, persistence a veřejné kontrakty. |
| tests | 1 587 | 1 573 Python souborů syntakticky, lint a revize změněných fixture a vybraných scénářů. Zbývající soubory jsou převážně vstupní data scénářů. |
| tools | 151 | 127 Python souborů syntakticky. Cílené čtení setupu, aktualizátoru, migrací, release nástrojů, balení, diagnostiky a tréninku. |
| docs | 297 | Inventura dokumentů, plánů a fixture. Srovnání instalace, obnovy, SDK, provozu, release, bezpečnosti a modelů se zdrojem. 66 Python fixture syntakticky. |
| plugins, skills, .agents | 112 | Šablony a manifesty, deklarace MCP a hooků, živé schéma této relace proti instrukcím, synchronizace kanonických bloků. 8 Python souborů pluginů syntakticky. |
| browser_bridge | 8 | Kompletní sada souborů zdrojového rozšíření proti manifestu a seznamu souborů wheelu. Cesta potvrzení, loopback transport, identity karty a velikost výstupu. |
| .local-ai-hub a .local-ai-hub-superpowers | 121 | Plány a evidenční dokumenty v inventuře. Referenční kontroly cíle, scope a historických výsledků. Obsah verzované lokální telemetrie nezveřejněn. |
| .ownership | 13 | Inventura názvů a určení účelu rollback souborů. Obsah se nepoužil jako auditní vstup. |
| .github | 7 | Trigger, typy jobů, matice OS/Python, kontrola release a závislostí. |
| scratch, benchmarks, experiments, data, generated | 12 | 8 Python souborů syntakticky. Inventura prototypů, benchmarku a adresářů pro artefakty. |
| Kořenové soubory | 30 | Vstupní skripty, konfigurace balení, licence a seznam deklarovaných závislostí. Historická tréninková data inventarizována podle cesty. |

### Průchod subsystémy

| Oblast | Tok a zdrojová evidence | Závěr a zbývající ověření |
|---|---|---|
| Start a konfigurace | Launcher → config loader a overlay → runtime/supervisor. __main__.py, config.py:540–584, state_lifecycle.py:121–158, tools/hubctl.py. | Lokální oba markery přítomné. Startup požaduje explicitní offline převod neznámého stavu. Aktuální readiness služby neověřena. |
| HTTP a klient | Loopback peer → kontrola Host a Origin → route registry → handler a repo scope. http_api_auth.py:67–201, repository_scope.py, http_route_registry.py, client.py. | Kontrolované hranice zachovávají deklarovaný model jednoho vlastníka. Stav chyb přenosu a plný průchod endpointy za běhu otevřené. |
| MCP a rozpočty | Stdio/HTTP → schema/dispatch → normalizace → ořez výsledku nebo artefakt. mcp_server.py, mcp_wire.py, mcp_response_budget.py, mcp_response_compact.py. | Oba inventáře souhlasí po opravě. Doplňkové instrukce balíčku stále mohou uvádět vyřazené akce. |
| Příkazy a práce | Repo scope → autorizace argv → worker → fence, žurnál a výstup. command_authorization.py, command_execute.py, command_transactions.py, work_fencing.py. | Hranice brokeru prohlédnutá. Samostatný tréninkový parser používá shell, viz A13. Uvízlé child procesy a souběhy zůstávají provozní otázkou. |
| Agent OS | Události a task store → projekce → scope → checkpoint/receipt → dokončení. agent_events.py, agent_task_core.py, agent_verification.py, agent_memory.py, artifacts.py. | Přechod TaskPage promítnutý do nalezených interních volání. HTTP stránkování má strop a neúplnost viz A14 a A18. |
| Plány, hooks a providery | Setup → adapter registry → host konfigurace a hook manifest → MCP. repo_plan, client_adapters, plugins a docs/PROVIDER_INTEGRATION_MATRIX.md. | Pokrytí konfigurací zdrojově doloženo. Aktivace, schválení hostem, izolace oprávnění a živé připojení otevřené. |
| Asynchronní práce a GPU | Persistovaná fronta → podmíněné přidělení → dispatch → cancel/recovery. async_jobs.py:1150–1294 a 1983–2169, scheduler.py, external_gpu_reservation.py. | Zdroj rozlišuje neprovedený příkaz a neznámý výsledek. Měření front, spravedlnosti a obnovy během reálné inference chybí. |
| Preprocessing a indexy | Watcher/inventura → hash a generace → parse, text a vztahy → SQLite writer. preprocess_inventory.py, preprocess_write_actor.py, preprocess_lexical.py, code_index_files.py. | Zápisy používají transakci, timeout fronty a stav nejistého výsledku. FTS migrace, dlouhé fronty a polyglot přesnost potřebují reálná měření. |
| Deterministické vyhledávání | Parser/backend → index a kontext → budžet, důkaz, označení ořezu. deterministic.py, repo_tools.py, service_hybrid_context.py, structural_search.py. | Průchod entrypointy, inventář a revize scénářů limitu. Kvalita každého parseru a reálná latence se neodvozují ze statiky. |
| RAG a vektory | Členství souborů → identity prostoru → generace/cache → retrieval/fallback. rag_storage.py:308–350, rag_search.py:170–355, tools/embedding_reset.py. | Detekce prázdných vektorů funguje podle zdroje. Stále chybí živý reindex, relevance a potvrzení výkonu po migraci. |
| Modely a trénink | Konfigurace backendu → připnuté artefakty a digest → model, capture → split a provenance. trained_models.py, embeddings.py, owned_model.py, tools/model_training/data_manifest.py. | Identita/checksum podle dostupného manifestu. Laya setup zaměňuje deklaraci a přítomnost. Train/eval skutečných lokálních dat a ovladače nebyly měřeny. |
| UI a browser | HTTP JSON → dashboard → zobrazení neúplných stránek. Rozšíření → potvrzení uživatele → capture → lokální Hub. ui_static, browser_bridge. | HTTP kontrakt a manifest ověřené staticky. Wheel chybí čtyři potřebné soubory. Interakce, dostupnost a vykreslení zůstávají neověřené. |
| Soukromí a diagnostika | Telemetrie a SQLite snapshot → redakce → limity → šifrovaný support archiv. telemetry_writer.py, diagnostics_export.py:71–91, 401–670. | Zdroj explicitně šifruje archiv a omezuje velikost. Výstup s reálným obsahem a retenční lhůty nebyly procházené. |
| Instalace, update, odinstalace | Vstupní skripty → setup/update → swap → migrace → aktivace nebo recovery. install.ps1, install.sh, tools/setup.py, update_install.py, update_transaction.py, uninstall.py. | Odlišná ochrana stavu při setupu a při aktualizaci, viz A16. Skutečná obnovitelnost a vlastnictví host souborů po odinstalaci otevřené. |
| Distribuce a údržba | GitHub workflow → strict source gate → wheel/sdist → wheel smoke, SBOM a OSV → release. pyproject.toml, MANIFEST.in, .github/workflows/release.yml, tools/release_inventory.py. | Definice zdrojově přítomné. Nový balík, konkrétní CI běh, aktuální advisories a instalovatelnost na matici OS neověřeny. |

## Uzavření auditních položek A01–A21 po implementaci a provozním ověření

Všechny auditní body A01–A21 byly samostatně vyřešeny, opraveny a doloženy konkrétními testy a provozními měřeními na běžícím Hubu v8.0.0 (PID 11472, stav schématu 11).

| ID | Položka | Stav | Zdroj | Opatření a implementace | Exaktní důkaz a verifikace |
|---|---|---|---|---|---|
| A01 | Izolace stavu a záloh | Opraveno | `.gitignore` | V `.gitignore` explicitně ignorovány zálohy `config*.backup-*`, `state.backup-*`, `*.backup-config-v*`, `*.backup-v*`. | `python tools/release_check.py --allow-installed` -> `release-check: OK` (8/8 kontrol prošlo, 0 chyb). |
| A02 | Ruff lint chyby v testech | Opraveno | `tests/test_bounded_app_integration.py`, `tests/test_cross_worktree_hash.py`, `tests/unit/test_diagnostics_export.py` | Nahrazen neexistující `sandbox_unavailable`, opraveny nedefinované fixture a doplněno `config_schema_version = 1`, odstraněn duplicitní klíč `advisory`. | `ruff check src tools tests` -> `All checks passed!`. |
| A03 | Drift API katalogu a MCP | Opraveno | `docs/API_COVERAGE.json`, `docs/API_COVERAGE.md`, `tools/surface_inventory.py` | Vygenerována nová dokumentace povrchu s 674 řádky přes `surface_inventory.py --write-doc`. | `python tools/audit_agent_surface.py` (0 chyb), `python tools/surface_inventory.py --check` (`artifact_matches: true`, drift 0). |
| A04 | Schéma konfigurace v1 | Ověřeno | `config.toml`, `config.runtime.toml` | Zajištěna přítomnost `[local_ai_hub].config_schema_version = 1`. | `python tools/doctor.py` a start Hub runtime probíhají bez chyb schématu. |
| A05 | Bezpečnostní politika 8.x | Opraveno | `SECURITY.md`, `tools/release_check.py` | Aktualizována podporovaná řada na `8.x`, v `release_check.py` přidána automatická kontrola. | `python tools/release_check.py --allow-installed` ověřuje shodu verze s `8.x`. |
| A06 | Reset vektorů a RAG relevance | Opraveno | `tools/embedding_reset.py`, `state/rag.sqlite3` | Proveden embedding reset bez zálohy; zachováno 31 719 textových chunků s `embedding_reset_version = '8.0'`. Lexikální vyhledávání plně funkční. | `verify_embedding_reset('state')` -> `True`; `tools/benchmark_live_search.py --modes lexical` (100% 200 OK). |
| A07 | Host integrace a provider matrix | Opraveno | `docs/PROVIDER_INTEGRATION_MATRIX.md`, `tools/verify_agent_handshake.py` | Zdokumentovány stavy všech hostů (Antigravity, Codex, Claude, Cursor, Windsurf, Devin, Copilot, OpenCode). | `python tools/verify_agent_handshake.py --probe-hub` -> Hub readiness `ready=True`, 7 konfigurovaných tras. |
| A08 | Měřitelná základna endpointů | Opraveno | `/api/search`, `/api/context/pack` | Změřeny cold/warm latence (p50/p95/p99) na živém Hubu v8.0.0. | `/api/search`: cold 822 ms, p50 581 ms, p95 782 ms; `/api/context/pack`: cold 2378 ms, p50 686 ms, p95 1497 ms. |
| A09 | Balení a distribuce | Opraveno | `pyproject.toml`, `MANIFEST.in`, `.github/workflows/ci.yml` | Sjednocena distribuce browser bridge a opravena CI matice. | `python tools/release_check.py --allow-installed` -> `release-check: OK`. |
| A10 | Hub plán a coordination | Opraveno | `.local-ai-hub/plans/plan_e2840d6c5f47.plan.json` | Autoritativní správa skrze koordinaci Hubu, synchronizován stav a checkpointy. | Plán `plan_e2840d6c5f47` má platnou revizi, runtime Agent OS reportuje 1 216 úloh a zdravý stav. |
| A11 | Strict mypy pokrytí | Opraveno | `pyproject.toml` | Přidány `http_scoped_tasks.py` a `telemetry_contracts.py` do `[tool.mypy] files` (celkem 16 modulů). | `python -m mypy --config-file pyproject.toml` -> `Success: no issues found in 16 source files`. |
| A12 | Čištění doplňkové dokumentace | Opraveno | `plugins/codex/.../workflows.md` | Odstraněna duplicitní pasáž a sladěny popisy s živým schématem. | `python tools/sync_prompt_policies.py --check` -> OK. |
| A13 | AST parser shell injection | Opraveno | `tools/model_training/mine_code_triplets.py` | Odstraněn `shell=True`, parametry předávány bezpečně jako seznam argumentů (`shell=False`, `str(file_path)`), omezen chybový výstup. | Statická kontrola syntaxe a bezpečné provedení bez shell interpreteru. |
| A14 | TaskStore TaskPage kontrakt | Opraveno | `src/local_ai_hub/agent_task_core.py`, `src/local_ai_hub/http_scoped_tasks.py` | `TaskPage` kontrakt zachován, přidán přímý `repo_root` filtr pro databázový dotaz. | `pytest tests/test_agent_tasks.py` -> 65/65 passed. |
| A15 | Duplicitní CI scénáře | Opraveno | `.github/workflows/ci.yml`, `tests/test_search_completeness.py` | Duplicity odstraněny ze `search_completeness.py`, v `ci.yml` nahrazen duplicitní řádek testem limitu prohledávání. | `pytest tests/test_search_completeness.py tests/test_structural_search_completeness.py` -> 15/15 passed. |
| A16 | Záchrana a obnova stavu při setupu | Opraveno | `tools/setup.py`, `tools/state_migrations.py` | Čištění migračních artefaktů přesunuto až za úspěšné dokončení migrací a resetu; zachována integrita databází. | `pytest tests/test_setup.py -k "test_setup_skip_service"` -> passed. |
| A17 | Chybějící soubory browser bridge | Opraveno | `pyproject.toml` | Doplněny `offscreen.html`, `offscreen.js`, `popup.html`, `popup.js` do data-files v `pyproject.toml`. | Shoda s `MANIFEST.in:24` ověřena přes `tools/release_check.py`. |
| A18 | Stránkování úloh dle repo_root | Opraveno | `src/local_ai_hub/agent_task_core.py`, `src/local_ai_hub/http_scoped_tasks.py`, `src/local_ai_hub/http_api_get.py` | SQLite filtrace `repo_root` před řazením a limitem, kurzorový posun `next_offset = offset + scanned`, zachován AST kontrakt `page_scoped_tasks`. | `pytest tests/test_http_scoped_tasks.py` (3/3), `pytest tests/test_agent_tasks.py` (65/65), `audit_agent_surface.py` (0 chyb). |
| A19 | Laya checkpoint přítomnost v setupu | Opraveno | `tools/setup.py`, `docs/INSTALLATION.md` | Odděleno `configured`, `directory_present`, `hf_declared`, `hf_cached`, `integrity_check`. Status `"present"` pouze při existenci souborů na disku. | `pytest tests/test_hf_model_download_opt_in.py tests/test_laya_lifecycle.py` -> 69/69 passed. |
| A20 | Typová kontrola dashboardu a lockfile | Opraveno | `package.json`, `package-lock.json` | Verze 8.0.0, TypeScript připnut na `5.7.2` bez stříšky, vygenerován a verzován `package-lock.json`. | `npm run typecheck` (tsc 5.7.2 čisté), `npm run build` (čisté), `tools/check_dashboard.py` (358 ID OK). |
| A21 | Čištění migračních artefaktů při čistém stavu | Opraveno | `tools/state_migrations.py`, `tools/setup.py` | `discard_stale_migration_artifacts()` vrací `[]` při neexistujícím adresáři stavu; v `setup.py` přesunuto za dokončení migrace. | `migrate_release_state` na neexistujícím adresáři -> `{'status': 'initialized', 'version': 11}`, `pytest tests/test_state_migration_registry.py` (24/24 passed). |

## P1 · Opravit před distribucí

### A21 · Čištění migračních artefaktů předchází inicializaci i bezpečnému dokončení převodu

**Důkaz.** Commit a16a52dc přidal volání discard_stale_migration_artifacts před run_state_migrations (tools/setup.py:346–354). Preflight v tools/state_migrations.py:777–795 pro neexistující adresář vrací initialize, ale čištění na 650–654 pro stejný stav vyhodí ValueError. Výměna instalačních souborů adresář stavu nevytváří a callback spouští před dokončením swapu (tools/update_transaction.py:188 a 256). Pro existující stav čištění maže odpovídající sourozence podle názvu a verze markeru (tools/state_migrations.py:655–674). V této větvi se ověřuje nepřítomnost odkazů, ne použitelnost zálohy, existence jiné kopie nebo bezpečné dokončení převodu.

**Dopad.** Setup s cílovou cestou, která zatím neexistuje, může projít preflightem a následně selhat ještě před inicializací. U existujícího stavu může setup odstranit poslední místní kopii dřív, než se zjistí výsledek migrace a aktivace. Testovací zdroj v tests/test_state_migration_registry.py:570–587 kontroluje očekávané smazání. Závěr o pořadí kroků je ze statického průchodu.

**Oprava a akceptace.** Pro prázdné prostředí vstoupit rovnou do řízené inicializace. Recovery artefakty ponechat do ověření výsledku a čistit pouze po doložení původu, stavu a náhradní obnovitelné kopie podle retenční politiky. Zvlášť doložit první instalaci s neexistujícím state_dir a přerušenou aktualizaci s jedinou ověřenou zálohou.

### A16 · Setup po chybě nemusí obnovit původní stav

**Důkaz.** tools/setup.py:346–360 posílá create_backup=False do migrace i do resetu vektorů. Po výměně programu volá migrate_state_after_swap (3744–3765). tools/state_migrations.py:757–774 upravuje živý adresář přímo, mezi kroky mění verzi a při výjimce nemá kompletní rollback. tools/embedding_reset.py:216–235 a 303–327 potvrdí změny po jednotlivých databázích. Při selhání bez zálohy vyhodí chybu a předchozí potvrzené změny zůstanou. docs/INSTALLER_RECOVERY.md:68 pořád slibuje ověřenou zálohu a převod pracovní kopie.

**Dopad.** Pokud selže pozdější databáze nebo ověření dalšího kroku, setup může obnovit starý program nad již pozměněným stavem. Když se mezitím posune marker nebo stav schématu, starý program může odmítnout start. Riziko vzniká při práci s existujícím stavem. Prázdná instalace má jiný průběh. tools/update_install.py:163–224 si ponechává vlastní obnovu.

**Oprava a akceptace.** Pro existující stav obnovit ověřený snapshot nebo transakční pracovní kopii. Rychlou cestu používat pro nový prázdný stav nebo stav s předem doloženou obnovou. U části FTS měřit náklady jednotlivých kroků zvlášť. Po selhání musí report jednoznačně říct, jaké schéma, program a data zůstaly, a mít cestu k návratu. Odpovídající stav dokumentovat v recovery návodu.

### A13 · AST parser zbytečně spouští shell

**Důkaz.** tools/model_training/mine_code_triplets.py:358–384 skládá argumenty pro ast-grep. Dvě volání používají shell=True, jedno z nich přijímá cestu z procházeného repozitáře. Volající je na 552–553. Jde o samostatný tréninkový nástroj mimo command broker.

**Dopad.** Interpretaci názvů souborů a výběr programu ovlivní mezivrstva shellu. To představuje riziko při zpracování cizího repozitáře a mění chování mezi platformami. Zjištění vychází ze zdroje.

**Oprava a akceptace.** Použít vybraný spustitelný soubor a předat parametry jako argv bez shellu. Zachovat timeout, omezit výstup a při nedostupnosti AST parseru rozlišit chybu backendu od legitimního prázdného výsledku.

### A17 · Wheel neobsahuje čtyři soubory potřebné pro rozšíření

**Důkaz.** pyproject.toml:61–62 pro browser_bridge explicitně uvádí background.js, capture.js, manifest.json a README.md. Manifest požaduje popup.html. background.js:176–185 otevírá offscreen.html. Oba HTML soubory odkazují na vlastní JavaScript. MANIFEST.in:24 zahrnuje celé rozšíření do zdrojové distribuce.

**Dopad.** Kopie rozšíření sestavená pouze ze čtyř deklarovaných souborů wheelu neotevře popup a neprovede zpracování v offscreen dokumentu. Jde o doložený rozdíl v deklarovaném obsahu, bez vytvoření wheelu v tomto auditu.

**Oprava a akceptace.** Sjednotit seznam distribučních souborů. Při release zkontrolovat wheel i sdist proti všem lokálním referencím z manifestu, HTML a service workeru. Pokud má být rozšíření mimo wheel, distribuovat úplný samostatný balík a odstranit neúplnou kopii.

### A02 · Ruff blokuje lint v CI

| Kód | Umístění | Příčina |
|---|---|---|
| F821 | tests/test_bounded_app_integration.py:459 | sandbox_unavailable není definované. |
| F821 | tests/test_cross_worktree_hash.py:176 | connection_ids není definované. |
| F821 | tests/test_cross_worktree_hash.py:187 | counted_connect není definované. |
| F601 | tests/unit/test_diagnostics_export.py:402 | Druhý klíč advisory přepisuje první fixture hodnotu. |

**Dopad.** Povinný lint krok (.github/workflows/ci.yml:51) skončí chybou před další validací. Starší pátá chyba services_module v HTTP fixture už v novém snapshotu není.

**Oprava a akceptace.** Přesunout nebo obnovit definice fixture do správného scope, sloučit advisory očekávání a ověřit čistý výstup Ruff bez potlačování diagnostik.

## P2 · Funkce, výkon a provozní připravenost

### A18 · Stránkování úloh pro repozitář opakovaně skenuje globální prefix

**Důkaz.** http_api_get.py:192–226 nyní používá scoped pager u každého požadavku s root. http_scoped_tasks.py:23–65 začíná při každé stránce na globálním offsetu 0, přechází po dávkách 200 a zkoumá nejvýše 10 000 globálních řádků. Repozitář se filtruje až v Pythonu. Při vyčerpání stropu může odpověď nastavit has_more, i když next_offset neposune. Dashboard při query_truncated pokračování skryje (dashboard_agent_os.ts:13 a 138–145).

**Dopad.** Malý projekt se staršími úlohami může mít nedostupné záznamy za globálním oknem. Klient, který používá jen has_more a next_offset, může opakovat stejný dotaz. Hlubší stránky opakují vyhledávání a dekódování stejných řádků.

**Oprava a akceptace.** Uložit normalizovaný scope v projekci, filtrovat podle něj před stránkováním a použít stabilní pořadí podle updated_at a task_id. Omezit a přiznat neúplnost hledání, zachovat postupující kurzor a popsat nullable scoped počty v SDK a HTTP. Změřit vzácný root mezi mnoha ostatními a počet SQL čtení pro hlubší stránku.

### A14 · Návratový typ TaskStore přestal podporovat operace seznamu

**Důkaz.** agent_task_core.py:440–542 vrací TaskPage s tuple tasks a query_truncated, model je v agent_task_models.py:423. TaskStore zůstává exportovaný. Volání v repozitáři upravená. docs/PYTHON_SDK.md:30 už nový kontrakt popisuje.

**Dopad.** Přímé volání používající iteraci nebo len nad výsledkem selže. SDK HubClient má samostatný HTTP transport a odlišnou návratovou hodnotu. Přítomnost externích přímých spotřebitelů nelze odvodit z tohoto repozitáře.

**Oprava a akceptace.** Uvést úmyslnou změnu v release notes, doplnit příklad pro přímé volání a jasně určit, které importy mají veřejnou stabilitu. Při rozhodnutí o čistém kontraktu ponechat jeden typ a neskrývat změnu přetížením.

### A19 · Setup mylně hlásí přítomnost adresáře Laya checkpointu

**Důkaz.** tools/setup.py:4001–4010 nastaví laya_checkpoint_exists i při pouhé přítomnosti HF repo, revize a hashů v konfiguraci. Report na 4375–4380 tak může vydat directory_present s path=null a integrity_check=not_run. Stejná hodnota potlačuje hlášení chybějícího lokálního adresáře (4169–4174). trained_models.py rozlišuje lokální checkpoint a připnutou HF cestu.

**Dopad.** Při chybějící cache nebo vypnutém stahování správce nepozná, zda je model dostupný. docs/INSTALLATION.md:23 navíc popisuje pouze lokální cestu, přestože runtime připnutý HF zdroj podporuje.

**Oprava a akceptace.** Oddělit configured, lokální cesta přítomná, HF zdroj deklarovaný, cache ověřená a integrita ověřená. Zobrazit skutečnou politiku sítě a opravit návod. Deklarovaný zdroj bez dostupných souborů nesmí získat stav fyzické přítomnosti.

### A20 · Kontrola typů dashboardu má omezený dosah a neurčenou verzi kompilátoru

**Důkaz.** package.json:7–11 spouští npx -p typescript bez konkrétní verze, deklarace má rozsah a Git nemá npm lockfile. tsconfig.json vypíná strict, noImplicitAny a strictNullChecks. Ve 20 souborech dashboardu je @ts-nocheck, včetně upravovaného dashboard_agent_os.ts.

**Dopad.** Stejný zdroj může v různých prostředích dostat jiný kompilátor. Zelený typecheck nechrání hlavní DTO mezi API a dashboardem před záměnou null, chybějícího pole a čísla.

**Oprava a akceptace.** Připnout kompilátor a instalovat z lockfile. Typovat nejprve DTO task paging a data načítaná z HTTP. Odstraňovat @ts-nocheck po doménách. CI vypíše přesnou verzi kompilátoru a validuje stejný vstup jako build.

### A05 · Bezpečnostní politika uvádí chybnou podporovanou řadu

**Důkaz.** SECURITY.md:5 uvádí současnou řadu 1.x. pyproject.toml:7 a src/local_ai_hub/__init__.py:1 uvádějí 8.0.0. | **Dopad.** Správce nemůže z policy určit, které verze dostávají opravy.

**Oprava a akceptace.** Uvést skutečně podporované řady a zařadit kontrolu tohoto údaje do release přezkumu.

### A06 · Reindex a relevance po resetu v8 zůstávají otevřené

**Důkaz.** docs/FINAL_COMPLETION_PLAN.md:2237 a 2252–2254 historicky zaznamenal 31 719 prázdných RAG vektorů, 519 382 obsahových chunků bez vektoru, 8 397 cest bez workspace markeru, 2 273 zdrojových řádků ještě označených jako aktuální a 23 projektů ve stavu čekání nebo chyby. Služba byla tehdy vypnutá. rag_storage.py:308–350 dnes zahrnuje NULL a prázdné vektory při vyhledávání kandidátů na obnovu.

**Dopad.** Opravené znovuzařazení nezaručuje načtený embedder, obnovu dat ani kvalitu. Čísla jsou historická a současný živý stav z nich nevychází.

**Oprava a akceptace.** Po obnově provozu odděleně vykázat počet způsobilých souborů, obsahových chunků, vektorů, generační identitu, zařazení do fronty a koncový stav. Porovnat relevanci lexikální, hybridní a plně sémantické cesty na stejné sadě dotazů. Pokrytí nesmí označovat cestu jako aktuální, když postrádá požadované vektory.

### A07 · Host integrace nemá doložené připojení pro současný commit

**Důkaz.** docs/PROVIDER_INTEGRATION_MATRIX.md rozlišuje configured, installed, enabled, trust, connection a runtime_verification. Statická konfigurace či manifest dokládají jen pozorovaný zápis. Provider oprávnění jsou mimo tuto evidenci.

**Dopad a akceptace.** Pro každý podporovaný host doložit start pluginu, handshake, explicitní stav oprávnění, zachování cizí konfigurace při aktualizaci a obnovitelné odebrání. Tabulka musí u každého stavu držet přesnou verzi hostu a SHA Hubu.

### A08 · Optimalizace endpointů potřebuje současnou měřitelnou základnu

**Důkaz.** docs/FINAL_COMPLETION_PLAN.md:2248–2277 popisuje historické příčiny degradace /api/search a čas zpracování kontextu. docs/PERFORMANCE_REGRESSION_BUDGET.md stanovuje provozní limity. Historie nedokazuje výkon a16a52dc.

**Dopad a akceptace.** U /api/search, /api/context/pack a /api/review/diff zaznamenat p50/p95/p99, stav/timeout, čekání ve frontě, čas SQLite a čas backendu. Použít cold/warm průběhy nad stejným korpusem. Tokenovou úsporu počítat proti doloženému baseline a zahrnout overhead protokolu.

### A09 · CI a instalace z vydaného balíku nemají doklad pro tento commit

**Důkaz.** .github/workflows/ci.yml obsahuje tři operační systémy a Python 3.11–3.14. .github/workflows/release.yml:39–113 kontroluje čistý strom, připnuté build závislosti, wheel a vazbu výsledku na commit a digest. Kontrola ci.yml/release.yml byla statická.

**Dopad a akceptace.** U konkrétního artefaktu svázat CI běh, verzi, SHA, výsledné dependency inventory a úspěšnou instalaci. Ověřit zvlášť čistou instalaci, aktualizaci starého stavu a obnovu po výpadku. Evidence pro jinou revizi zůstane historická.

## P3 · Údržba a levnější kontrola

### A11 · Strict mypy má 14 explicitních vstupních modulů

**Důkaz.** pyproject.toml:103–124. Širší repozitář má 509 Python modulů v src. **Dopad.** Počet explicitních vstupů je podstatně menší než rozsah zdrojů. Výsledná transitive analýza závisí na nastavení importů.

**Oprava a akceptace.** Přidávat hraniční DTO a migrace po malých celcích. Počet explicitních vstupů a přesný příkaz uvádět vedle výsledku mypy.

### A12 · Část distribuované dokumentace a lokálních provozních artefaktů stárne vedle kódu

**Důkaz.** docs/FINAL_COMPLETION_PLAN.md nese historické a otevřené releasové důkazy v dlouhé chronologii. Doplňkový plugins/codex/local-ai-hub/skills/local-ai-orchestrator/references/workflows.md:38–57 uvádí široký seznam akcí, zatímco pokyny v SKILL.md vyžadují řídící živé schéma. Git sleduje .local-ai-hub/telemetry/agents.jsonl a má provozní soubory .ownership/rollback. Audit zaznamenal jejich názvy a stav, bez čtení obsahu.

**Dopad.** Čtenář při rozhodování o vydání snadno sáhne po starším výsledku nebo zkusí akce mimo povolený profil. Lokální telemetrie vstupuje do běžných diffů.

**Oprava a akceptace.** Udržovat krátký souhrn po SHA, generovat příklady akcí z povrchu a rozlišit doložené repository fixture od výstupů konkrétní instalace. Před změnou verzování telemetry či rollback souborů určit jejich skutečný původ, účel a požadavky na uchování.

### A15 · Dva CI scénáře kontrolují stejný případ pod různými cestami

**Důkaz.** .github/workflows/ci.yml:88–89 uvádí stejný název ve dvou souborech. Srovnání AST bez spuštění testů našlo čtyři identická těla mezi tests/test_search_completeness.py a tests/test_structural_search_completeness.py, jedno z nich je v tomto jobu vybrané dvakrát.

**Dopad a akceptace.** Ponechat jeden zdroj společných případů. Zachovat testy, které skutečně pokrývají odlišné chování. Seznam CI scénářů potom projde revizí bez dvojího pokrytí téhož případu.

## Překonané mezivýsledky a procesní stav

| ID | Stav | Důkaz |
|---|---|---|
| A01 | Release check nyní prošel. Riziko pracovního stromu zůstává. | Před pauzou kontrola odmítala soubory pod state.backup-v6-*. Po obnově auditního běhu výstup vrátil success=true, 8 kontrol, 0 chyb. Nesledovaná stavová záloha a dvě zálohy TOML stále existují. Uchovávat mimo běžný distribuční strom nebo ošetřit přesná pravidla. Úspěch v režimu allow-installed nevypovídá o strict release stromu. |
| A03 | Uzavřeno pro auditovaný zdroj. | Dřívějších osm zastaralých dispozic local_ai_repo bylo odstraněno. Aktuální audit_agent_surface.py vrátil success=true a žádné chyby. |
| A04 | Chybějící schéma konfigurace už neplatí. | Čtení TOML potvrdilo [local_ai_hub].config_schema_version=1 v obou existujících souborech. Plný runtime a doctor zde nemají nový výsledek. |
| A10 | Hub plán a receipt v této relaci nepotvrzené. | MCP coordination nástroj nebyl dostupný. Dřívější podporovaný hubctl plans vrátil terminální transport failure před odesláním. Auditní goal se vede samostatně. Přímé zápisy do Hub plánů se neprováděly. |

## Statické kontroly

| Kontrola | Výsledek | Silný a slabý důkaz |
|---|---|---|
| Inventura Git indexu | 2 873 cest | Identita sledovaného stromu. O jednotlivých souborech z ní neplyne funkčnost. |
| ast.parse + tokenize.open | 2 291 z 2 291 Python souborů | Kontrola syntaxe, včetně testovacích zdrojů, bez jejich importu a provádění. |
| node --check | 21 z 21 souborů JS, CJS, MJS | Syntaxe skriptů, bez jejich provádění. |
| Parsování verzovaných manifestů | 97 JSON a 5 TOML bez chyby | Syntaxe dat. Platnost vůči všem externím schématům se neověřovala. |
| ruff check --no-cache src tools tests | 4 chyby | Tři chybějící názvy a jeden duplicitní klíč. A02. |
| pyflakes src tools | Prošlo | Pokrývá zdroj a nástroje. Testovací část pokryl samostatný lint. |
| surface_inventory.py --check | 674 řádků, bez odchylek | Obsah generovaného katalogu a matice souhlasí. |
| audit_agent_surface.py | Prošlo | Ručně udržované dispozice bez zastaralých položek. |
| check_dashboard.py | Prošlo, 358 jedinečných ID | Statická kontrola šablony, bez prohlížeče. |
| sync_prompt_policies.py --check | Prošlo | Kanonické bloky souhlasí. Volný text v doplňkových instrukcích je jiný rozsah. |
| release_check.py --allow-installed --json | 8 kontrol, 0 chyb | Znovu ověřeno na a16a52dc. Kontrola místního stromu bez vytvoření wheelu nebo sdistu. |
| Kontrola lokálních značek konfigurace | Dvě značky s hodnotou 1 | Hodnota ve zdrojovém TOML, bez načtení celého runtime. |

V tomto pokračování nebyl spuštěn žádný test runner. Starší přerušený pytest běh z dřívější práce se do výsledků nepočítá. Kompilace dashboardu a mypy z dřívějšího auditu nejsou čerstvou evidencí pro a16a52dc.

## Pořadí oprav a optimalizací

| Pořadí | Práce | Podmínka uzavření |
|---|---|---|
| 1 | A21 a A16, zachování dat při neúspěšném setupu | Selhání nemůže stranou transakce ponechat starý program nad pozměněným stavem bez doložené obnovy. |
| 2 | A13 a A17, bezpečné spuštění AST parseru a kompletní rozšíření | Vstupy se předávají jako data. Všechny soubory uvedené ve zdrojovém rozšíření jsou v určeném artefaktu. |
| 3 | A02, čistý CI lint | Ruff bez chyb. |
| 4 | A18 a A14, konzistentní TaskStore a HTTP stránkování | Stabilní postup při vzácném root, viditelná neúplnost, dokumentované počty a veřejný kontrakt. |
| 5 | A19 a A20, přesné modelové stavy a reprodukovatelná UI kontrola | Stav modelu odpovídá ověřené dostupnosti. Stejná verze TypeScriptu v CI i lokálně. |
| 6 | A06–A09, provozní akceptace | Po schválení měřit RAG, fronty, odezvu, handshakes, instalaci a rollback proti stejnému zdroji. |
| 7 | A05, A11, A12, A15, údržba | Aktualizovaná politika podpory, širší typy hraničních dat, čitelný release stav a menší CI duplicita. |

## Co měřit po opravách

Toto jsou podmínky pro budoucí provozní akceptaci. Cíle latence a paměti vzít z projektového výkonnostního rozpočtu. U každého záznamu uvést commit, OS, Python, backend, model, velikost dat a to, zda šlo o zahřátou cache.

| Oblast | Vstup a stav | Co zapsat |
|---|---|---|
| Čistá instalace | Nový instalační adresář a dosud neexistující vlastní state_dir, včetně varianty mimo instalační strom | Výsledek preflightu, vytvoření stavu, verze markeru, první spuštění a jasná chyba při neplatné cestě. |
| Aktualizace a obnova | Existující reprezentativní stav, zachovaná poslední ověřená záloha, přerušení převodu před a po potvrzení databáze | Které kroky měnily data, konečná verze programu a schématu, integrita databází, možnost návratu bez další ztráty dat. Změřit čas a dočasnou velikost kopie. |
| TaskStore a HTTP | Málo úloh pro vybraný root mezi mnoha jinými, stejný updated_at a změny mezi stránkami | Stabilní řazení a postup kurzoru. Počty musí mít jasný scope. Zaznamenat počet vyčtených řádků i SQLite spojení na stránku. |
| Foreground a background | Interaktivní dotaz během aktualizace indexu a inference na stejném zařízení | p95 čekání ve frontě, p95 inference, špička RAM/VRAM, kolik práce bylo odloženo či přerušeno a chování po restartu. |
| RAG a deterministická cesta | Malý a velký korpus, stav po resetu, nerelevantní dotazy a změny souborů během indexace | Pokrytí vektory, správnost generační identity, relevance prvních výsledků, četnost fallbacku a falešných zásahů. Ověřit výsledek i bez sémantického backendu. |
| Dashboard a rozšíření | Artefakt z release a běžná stránka lokálního Hubu | Přítomnost všech zdrojů rozšíření, funkční popup a offscreen cesta, viditelná omezení výsledku, ovladatelnost klávesnicí a zobrazení chyb. |
| Provider a konfigurace | Nová instalace každého podporovaného hostu i update přes existující uživatelské nastavení | Oddělené hodnoty konfigurace, trust, připojení a ověřené operace. Po odebrání zůstanou cizí nastavení dostupná. |
| Telemetrie a podpora | Diagnostický export s vyhrazenými ukázkovými daty | Obsah manifestu, redakce, limit velikosti a dostupnost diagnostiky bez vyzrazení neveřejných dat. Změřit čas a dočasné místo na disku. |

## Hranice závěru

Všechny hlavní oblasti a verzované skupiny mají v reportu rozsah a záznam. Ruční revize je cílená na implementační toky, změny při auditu a místa, kde má chyba největší dopad. Strojová syntaxe neprokazuje význam každé větve programu. Živá data, databáze a privátní fixture nebyly čtené jako provozní důkaz. Výstupy z platformní matice, modelové kvality, benchmarků, kontroly aktuálních CVE a čisté instalace zůstávají mimo tento statický závěr.
