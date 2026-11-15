# Local AI Hub — předávací plán pro implementačního agenta

**Datum:** 15. 11. 2026  
**Repozitář:** https://github.com/Harfusha/local-ai-hub  
**Rozpracovaný pull request:** https://github.com/Harfusha/local-ai-hub/pull/8  
**Pracovní větev:** `fix/fifth-audit-hub113-140`  
**Výchozí master pro audit:** `af2a64e3d23909098884a81a9363b2cfe6bbd9be`  
**Implementační commit před vytvořením tohoto dokumentu:** `f23c9c22f372de77496ac12d0316153407633053`  
**Původní zadání:** dokončit pátý audit `HUB-113–140` bez opakování již vyřešených auditů `HUB-001–112`.

> **Důležité:** Tento dokument je technický handoff. Záznam „implementováno“ znamená změnu zdrojového kódu na uvedené větvi, **nikoli** kompletní ověření na aktuálním HEAD. PR je záměrně **draft**; nedávej jej do `master` ani nepublikuj v6.0.0, dokud není zelený úplný požadovaný CI a nejsou vyřešeny release-gates. Není dovoleno vydávat chybějící externí důkazy za PASS. Neprováděj automatické model pulls, zásahy do GPU rezervací, nevyžádané testy živého browseru ani změny uživatelských nastavení.

## 1. Co bylo přímo implementováno na GitHubu

V PR #8 je sada skutečných commitů a kódových úprav:

| Audit ID | Stav kódu | Provedená změna / ověřitelné soubory |
|---|---|---|
| HUB-113 | Implementováno; první smoke PASS | `tests/conftest.py`: žádné `pytest.cache` I/O během `pytest_runtest_makereport`; první CI po opravě dokončilo **12/12 smoke** na Linux/macOS/Windows a Python 3.11–3.14. |
| HUB-114, 137 | Implementováno; doplnit akceptaci | Cache výsledků testů je **opt-in** `--test-result-cache`, CI má `NO_TEST_CACHE=1`; podpis zahrnuje zdrojové moduly, fixtures, config, OS/Python. V autoritativním režimu se hashe nepočítají. `AGENTS.md` aktualizován. |
| HUB-115 | Testovací rozšíření, CI dosud neověřeno | `.github/workflows/ci.yml`: critical cohort rozšířen o celý `tests/test_command_rollback.py`; výsledek nového HEAD zatím není doložen. Původní ratchet `commands.py` selhával. |
| HUB-116, 123 | Implementováno; chybí live E2E | `ui_static/app.js`: `/api/models` nyní používá skutečné `{object:'list',data:[{id,owned_by}]}`; netvrdí digest/VRAM readiness, kterou API neposkytuje. |
| HUB-117 | Implementováno; chybí live E2E | Telemetry používá `timeline`, `timestamp`, `event_type`, `action`, `net_tokens_saved`, `error_type`, `next_cursor`, `has_more`; starší stránky se zařazují před novější. |
| HUB-118, 119, 135 | Implementováno; živé propojení stále BLOCKED | `dashboard_frontend.py`: Codex TOML `[mcp_servers.local-ai]`, Antigravity JSON; odděleny registrace, skills, instalace a neověřený handshake; config read omezen na 256 KiB a odmítá symlinky. |
| HUB-120 | Implementováno jako fail-closed, nutné napojení na CI | `tools/generate_audit_acceptance.py`: bez odpovídajících SHA receipts nezapisuje `CI_GREEN`, `READY` ani falešnou `regressions_count=0`. `audit_acceptance.json` přiznává UNKNOWN/BLOCKED. Testy `test_audit_acceptance_truth.py`. |
| HUB-121 | Implementována konzervativní ochrana; ověřit závodní scénáře | `preprocess.py`: CAS invalidace podle očekávaného hashe; `rag.py`: při použití cache override čte omezené aktuální bytes a při rozdílu override nepublikuje starý obsah. `test_rag_incremental_index_io.py`. |
| HUB-122 | Implementováno; testovat skutečný browser | `ui_static/app.js`: podporuje external AbortSignal + timeout; `checkHub` ignoruje staré epochy; sekce používají latest-wins; aplikační `{success:false}` je chyba i při HTTP 200. |
| HUB-124, 132 | Částečně | `tests/test_dashboard_runtime_contracts.py` spouští skutečný JS v Node VM s API DTO; `test_dashboard_host_inspection.py` ověřuje TOML/JSON; stále chybí plný end-to-end browser se skutečným serverem. |
| HUB-125 | Implementováno; změřit velké repozitáře | `http_scoped_tasks.py` a GET handler filtrují podle rootu **před** stránkováním, bounded scanning přiznává neúplnost; frontend podporuje stránkování `Load more tasks` a root při změně sekce. Testy `test_http_scoped_tasks.py`. |
| HUB-127, 139 | Částečně | `structural_search.py` prochází také `.php`, `.jsx`, `.tsx`, stabilně řadí cesty; vrací `complete`, `has_more`, `file_limit`, `truncation_reasons`. Neimplementován cursor/continuation za limitem 400 souborů. |
| HUB-128, 129 | Částečně | `evidence_merge.py` hlásí `truncated`, `omitted_lines`, `original_end_line`, `truncation_reason`; bez content SHA nepřepisuje původní in-memory evidence živým souborem. Chybí explicitní recovery cursor a některá typovaná provenance metadata. |
| HUB-130, 131 | Částečně | CI zaručuje fresh cache mode, nově ukládá JUnit pro smoke/integration/critical a coverage artifacts. Úplná testovací evidence pro finální commit zatím chybí. |
| HUB-133 | Částečně | `tools/perf_gate.py` nově označuje výsledky **synthetic_microbench_only** a uvádí Python, OS, CPU a Git SHA; cold/warm zátěž a modelový benchmark zůstávají NOT_RUN. |
| HUB-136 | Základní testy doplněny | `tests/test_companion_skill_installation.py`: frontmatter, přítomnost skills, idempotence, zachování uživatelských změn a MCP-only režim. Existující ownership manifest v `tools/skill_ownership.py` se nesmí obejít. |
| HUB-138 | Částečně | `preprocess.py`: idle fingerprint zahrnuje `RAGStore.workspace_stats` (files/chunks/chunked_files), takže ztráta indexu může ukončit falešně čerstvou auditní cache. Chybí stress přes restart, souběh writerů, chyby SQLite a generace. |

**Navíc nad rámec auditu:** opraveny tři chybné operace moderního dashboardu: `check` → `GET /api/preprocess/status?root=...`, `refresh` a `unregister` → `POST /api/preprocess` s příslušnou `action`; podporováno kontrakty `services.py`. Opraveno i serverové stránkování globálních tasks se scoped rootem.

**CI evidence:** GitHub Actions běh po prvním commitu s opravou hooku (`1467ed558633...`, běh `43714354065`) má `platform-smoke` **12/12 success**, lint a mypy success. `critical-coverage` na tomto *starším* commitu má failure. **Nezobecňovat jej na celý aktuální PR**; poslední běhy byly při vytváření handoff ve frontě.

## 2. Povinné první kroky agenta — P0

### P0.1 Znovu synchronizovat a ověřit PR #8

1. Přepni do `fix/fifth-audit-hub113-140`, `git fetch`, ověř přesný HEAD a rozdíl vůči `master` (`git diff master...HEAD --check`). Neprováděj force-push ani automatický merge.
2. Na čistém checkoutu proveď:

```bash
python -m pip install -e ".[dev]"
python -m compileall -q src tools tests
python -m pyflakes src tools
python -m mypy
node --check src/local_ai_hub/ui_static/app.js
python -m pytest -q --no-cache tests/test_dashboard_host_inspection.py tests/test_dashboard_runtime_contracts.py tests/test_structural_search_php_contract.py tests/test_http_scoped_tasks.py tests/test_companion_skill_installation.py tests/test_audit_acceptance_truth.py tests/unit/test_evidence_merge.py tests/unit/test_preprocess_rag_pending.py tests/test_rag_incremental_index_io.py
python tools/release_check.py --allow-installed
```

3. Pokud se některý test rozbije, oprav jen skutečnou regresi; nemaž test ani nesnižuj threshold. Zachovej fail-closed behavior, root/snapshot identity a druhy neověřených stavů.
4. Zkontroluj GitHub Actions **na konečném SHA**, ne na dřívějším commitu. Ulož job/run identifikátor, verzi Pythonu, OS, test count, pass/fail/skip a odkazy na JUnit/coverage evidence.

**DoD:** čistý lint/mypy/testy na HEAD; výsledek každého kontrolního kroku reprodukovatelný, failure nezamlčený.

### P0.2 HUB-115 — dosud nepotvrzená kritická coverage

- Původní Windows Py3.13 porovnání: `commands.py` 380/2336 vs baseline 454/2752, poměr pod ratchetem.
- CI cohort byl rozšířen, ale dokud není nový **PASS**, není chyba uzavřena.
- Stáhni aktuální `critical-coverage.json`; najdi nepokryté větve `CommandBroker.run`, timeout, rollback, cancellation, cleanup. Napiš 2–5 kvalitních testů, pokud rozšíření cohortu nestačí. **Neupravuj historickou baseline pouze kvůli zelenému CI.**
- Věř testům `tests/test_command_rollback.py`, `tests/test_project_command_broker.py`, `tests/test_command_remediation.py`; prohlédni `tools/check_critical_coverage.py` a `tools/critical-coverage-win32-py3.13.json`.

**DoD:** current SHA critical-coverage PASS a artefakt s branch/function coverage.

### P0.3 HUB-113, 114, 130, 131 — autoritativní test evidence

- Znovu spusť relevantní CI matrix 3 OS × Py3.11–3.14; pohlídej, že žádná kombinace nepadá INTERNALERROR.
- Zachovej JUnit upload i při test failu, fresh execution (`NO_TEST_CACHE=1`) a aktivní `--run-all --no-cache` pro release/full suite. `0 collected` nebo pouze cached výsledky nejsou zelené testy.
- V samostatném testu simuluj změnu nepřímého modulu a `pyproject.toml`; opt-in cache musí invalidovat PASS. Pozor na monkeypatch `os.name`, jehož vliv na `pathlib` v report hooku vyvolal původní chybu.
- Ověř, že full suite na supported runneru nepadá kvůli timeoutu/memory, případně běh deterministicky sharduj a ulož pokrytí každého shardu.

**DoD:** všechna required CI zpracována, žádné chybějící či chybně „zelené“ testy.

## 3. Funkční UI a API — P1

### P1.1 HUB-124, 125, 132 — skutečné behaviorální kontrakty

Doplň živé HTTP/UI testy (offline loopback, bez cizí sítě) pro všechny sekce:

| Endpoint | Povinné vstupy / výstupy a negativní scénář |
|---|---|
| `GET /ready` | `ready:true/false`, 200/503, stale response po focus nesmí přepsat nový stav. |
| `GET /api/preprocess/status?root=...` | správný canonical root, 403 invalid scope, žádné `POST` pro read. |
| `POST /api/preprocess` | `action:refresh/unregister`, přiznat queued/partial vs success, `purge_data:false`, správná autentizace/operational mode. |
| `GET /api/agent/hosts` | Codex TOML a Antigravity JSON, stavy registered vs connected, nulový syntetický handshake. |
| `GET /api/agent-state/tasks` | globální a konkrétní root, `offset/limit/has_more/next_offset`; 100+ cizích záznamů před relevantními, přesné pořadí a neúplný scan. |
| `GET /api/coord/worktrees` | scope identity a okamžité přepnutí mezi dvěma roots. |
| `GET /api/models` | OpenAI DTO `data[{id,...}]`, empty vs error vs unknown; reálné VRAM se nevyvozuje z ID. |
| `GET /api/telemetry/timeline` | `timeline/next_cursor/has_more`, nejméně 120 historických záznamů, bez duplikátů, nula duration je nula. |
| `GET /api/config` | redacted, denied, transport error, shape mismatch nesmí vypadat jako prázdné nastavení. |

Použij již připravený Node harness a rozšiř jej o skutečný Handler fixture nebo lokální browser test. Testy musí selhat při záměně DTO klíčů nebo při vynechání rootu. Dolož keyboard/ARIA a race `AbortSignal` pro každou sekci.

**DoD:** JS a backend sdílejí spolehlivá DTO očekávání; žádné `No models/tasks/events` při error response.

### P1.2 HUB-126 — zbývá plná moderní 11→7 dashboard parita

**Toto není dokončeno.** `/dashboard` stále slouží legacy HTML; `/dashboard/next` má část operací jen jako read-only náhled nebo odkazy na `/dashboard/legacy`.

1. Projdi `docs/DASHBOARD_PARITY_PLAN.md` a `src/local_ai_hub/dashboard.py` (11 původních tabů).
2. Pro `Requests`, `Tasks/Coordination`, `Commands`, `Bundles/Transfers`, `Models/Inference`, `Settings` doplň výslovně odsouhlasené write akce s typed API, ověřeným scope a potvrzením destruktivních změn.
3. Zachovej oddělené stavy installed/loaded/routable, planned/verified, historical/live.
4. Otestuj desktop/mobile, keyboard focus, screen reader, back/forward navigation, rate-limit/timeout, offline režim a CSP.
5. **Teprve když parity matrix skutečně prokazuje funkční paritu**, přesměruj `/dashboard` na nový shell; `/dashboard/legacy` zachovej, neznič deep-links.

**DoD:** každá ze 11 původních operací má nativní funkční test nebo záměrně zdokumentovaný explicitní fallback; výchozí UI není přepnuté před ověřením.

## 4. Integrita RAG, evidence a polyglot search — P1/P2

### P1.3 HUB-121, 138 — dokončit závodní scénáře indexování

- Doplň end-to-end test pro no-watcher úpravu souboru mezi `file_refs`, `source_index`, `ingest_cache`, embeddingem a SQL publikací. Prověř `RAGStore.index_paths_step` při změně souboru v době embed call.
- CAS update musí párovat očekávaný content hash, generation, root a path; nesmí smazat novější index. Ztráta RAG SQLite/chunks při nezměněném `file_refs` musí invalidovat idle audit.
- Testuj restart, symlink swap, failed stat/read, busy DB, index rebuild a concurrent writer. Rozlišuj `unavailable/unknown` od „index current“.
- Změř overhead dalších bounded source read; nesnižuj bezpečnost kvůli synthetic benchmarku.

**DoD:** žádný starý text se nepublikuje s novým hashem; index se po rekonciliaci opraví bez manuálního force-refresh.

### P1.4 HUB-127, 139 — dokončit přesnost PHP a pokračování výsledků

- U PHP otestuj namespaced třídy, metody, funkce, multiline deklarace a komentáře; označ lexical fallback, pokud není Tree-sitter.
- Přidej deterministic cursor/offset nebo index-guided continuation po `file_limit=400`. Nynější návrat `complete:false` je pravdivý, **ale sám o sobě nedokáže prohledat zbylé soubory**.
- Zachovej `path` confinement, symlink protection, 4 MiB per-file budget a deterministický sorting.

**DoD:** dotaz na symbol za 400. souborem se při pokračování skutečně najde, bez globálního false negative.

### P1.5 HUB-128, 129 — evidence recovery/provenance

- Ke `truncated/omitted_lines/original_end_line` doplň `requested_end_line`, `returned_end_line`, explicitní `slice_recovery` (bezpečné token/cursor) pro zkrácené intervaly.
- Rozlišuj `source_kind`, originální `repository_revision`, `revision_verified`, `read_at`, `content_hash` a vlastní `snapshot_verified`; u starých hashes nikdy nepoužívej aktuální disk text.
- Ujisti se, že client/agent uvidí `partial`, nikoliv úplnou citaci. Přidej test 50 001 řádků, EOF a chybějící soubor.

**DoD:** rekonstruovatelný důkaz s přiznaným původem a limitací; bez false provenance.

## 5. Release, výkon a agentní skills — P1/P2

### P1.6 HUB-120, 134, 140 — úplný release evidence gate

- Nový `audit_acceptance.json` záměrně **nikdy sám nepotvrzuje CI_GREEN**. Dopoj jej k trusted GitHub Actions výsledkům a artifact digestům pro **přesné HEAD SHA**, OS/Python a test cohort.
- Emituj immutable release manifest pro wheel/sdist sha256 + dependency inventory + MCP wheel smoke + JUnit/coverage + `RELEASE.json` tag, verzi a source revision. Staré SHA, red/skipped/incomplete CI, checksum mismatch, nedostupné artifacts nebo chybějící live-host proof musí udržet release BLOCKED.
- `release.yml` publikuje pouze po požadovaných green jobs; potvrď všechny required checks/tag conditions a dostupnost evidence. Neoznačuj `SOURCE_VERIFIED` za runtime verified a nepovoluj v6 production-ready bez nutných gates.
- Otestuj fake green local + red CI, missing artifact, stale tag, skipped critical coverage, changed SHA a locked GPU/browser výjimky.

**DoD:** zelené celé CI pro aktuální SHA a transparentní schválení externích výjimek, nebo explicitní READY_FOR_RC/BLOCKED, nikdy tichý prod release.

### P2.1 HUB-133 — reálný výkonový test

- `tools/perf_gate.py` je nyní výslovně **synthetic microbench**. Připrav oddělený workload: 10k a 100k souborů, CZ/EN a PHP/Python/TS, cold/warm SQLite, FTS/RAG/preprocess/fusion + peak RSS/I/O.
- Embedding, semantic rerank a inference měř **jen při již nainstalovaném modelu a s oprávněním na hardware**; jinak explicitně NOT_RUN.
- Měř p50/p95, environment, source SHA, pracovní profil, počet dokumentů, bytes, sample count; neporovnávej nekompatibilní prostředí ani netvrď 0 regresí pro neprovedenou část.

### P2.2 HUB-136 — agentní skills a update

- Potvrď nově přidaný test `tests/test_companion_skill_installation.py` na Windows/Linux/macOS.
- Prověř `COMPANION_SKILLS`, ověřené soubory frontmatter, uživatelské úpravy, ownership manifest, uninstall/upgrade, změnu aktivace v Codex vs Antigravity, MCP-only setup bez nevyžádaných skills.
- Audituj duplicitní automatické policy triggers v `skills/ponytail*` a `skills/plan-led-work` tak, aby nezahltily agentní instrukce. Nedoplňuj zbytečný další instalační framework.

## 6. Externí akceptace z předchozích auditů — nejsou to automaticky hotové úkoly

| ID | Potřeba | Co agent smí udělat bez dalšího zásahu |
|---|---|---|
| HUB-002, 108 | Čistý install/update/uninstall Windows, Linux a macOS | GitHub Actions runner a owned fixture; neodinstalovávat aktivní lokální službu bez souhlasu. |
| HUB-103 | CZ/EN embedding relevance na reálném modelu | Použít **jen již dostupný** embedding model, jinak `BLOCKED_MODEL_ABSENT`, neprovádět pull. |
| HUB-104 | Skutečný Codex MCP host-session handshake | Bez CLI/session logu neuzavírat; static TOML parser není handshake. |
| HUB-105 | Živá Antigravity host session | Bez IDE trace neuzavírat; env proměnná není důkaz. |
| HUB-106 | Chrome/Playwright permission, egress a browser real flow | Jen se skutečným browser session permission; nepředstírat izolaci. |
| HUB-107 | RTX 5070 Ti 16 GB VRAM souběh a OOM recovery | Jen po schválení lokální GPU rezervace; nic nestahovat, nerušit gaming/inference. |

Pro každý gate vytvoř auditní receipt `{item_id, source_sha, env, test_command, exit_code, observed_at, artifact_sha256, verification_level}`, nebo pravdivé `BLOCKED_*`. Důkazy nemusí obsahovat osobní cesty, prompty ani tajné tokeny.

## 7. Přesné pořadí a podmínky ukončení

1. **P0:** GitHub PR #8 testy a typy; oprava případných regresí, ověření 12 platform-smoke, critical-coverage PASS (HUB-113–115, 130–131).
2. **P1:** E2E HTTP/UI contract suite, sekční root identita a latest-wins; dokončení dashboard parity nebo explicitní legacy stav (HUB-122, 124–126, 132).
3. **P1:** RAG race tests a evidence recovery; PHP lexical/AST a continuation (HUB-121, 127–129, 138–139).
4. **P2:** realistic perf a skills platform roundtrip (HUB-133, 136).
5. **Release:** pouze pro přesný SHA post-build manifest, zelené required checks a externí gates/explicitní exceptions (HUB-120, 134, 140 + HUB-002, 103–108).
6. Po každé etapě změň úkol na `verified` **až po důkazu**, ne podle existujícího slova `done` v JSON plánu. Posílej malé reviewovatelné commity, nové testy a aktuální CI linky. Neotevírej duplicitně již řešené úkoly z prvních čtyř auditů.

### Done znamená

- `HEAD` PR má PASS lint, strict mypy, relevantní testy a required package/release checks, bez interních pytest crashů.
- Nový frontend API DTO end-to-end i pod error/stale/race scénáři; všechny běžné workflow dostupné v moderním UI nebo explicitně přiznaný legacy fallback.
- Žádné falešné `ready`, `no models`, `complete evidence`, `zero regressions` nebo `CI_GREEN` bez příslušného měření.
- Trvalý origin/scope/provenance pro RAG, evidence, tasks a audit.
- Externí model/GPU/browser/host/OS gates jsou ověřené, nebo pravdivě BLOCKED; **dokud jsou required release gates BLOCKED, PR zůstává draft a v6 se nevydává jako production-ready**.