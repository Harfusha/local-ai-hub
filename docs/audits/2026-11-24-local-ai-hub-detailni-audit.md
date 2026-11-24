# Detailní audit Local AI Hub — aktuální stav

**Datum auditu:** 24. 11. 2026
**Repozitář:** C:/Users/Adam/.local-ai-hub
**Větev:** master
**Auditovaný HEAD:** f05c1ed403b713e288a5911c5f29d0ffc8dae5b1
**Produktová verze:** 8.0.0
**Verze uloženého stavu:** 11
**Pracovní strom:** Při úvodní inventuře obsahoval necommitnuté změny plugin instrukcí, TaskPage refaktoru, souvisejících fixture a oba auditní dokumenty; dále telemetry a čtyři nesledované lokální artefakty (state migrace, dvě config zálohy a state backup). Obsah telemetry ani záloh jsem neotevíral. Auditní poznámky se vztahují k uvedenému HEAD a statickým kontrolám v době jejich běhu; souběžný strom se může měnit.
**Typ auditu:** statický zdrojový, integrační a release audit; bez oprav aplikačního kódu

## Verdikt

Projekt nelze označit za připravený k vydání. Release check odmítá runtime payloady v kořenové state záloze; Ruff hlásí pět chyb; agent surface audit hlásí osm zastaralých MCP rozhodnutí. Statická kontrola navíc našla `shell=True` nad cestou z procházeného repozitáře v AST-Grep tréninkovém nástroji, což na Windows vytváří cestu ke spuštění příkazu pod právy uživatele.

Ve vlastním HTTP auth a command brokeru jsem staticky nepotvrdil bypass. AST parser pro trénink je samostatná shell-execution cesta mimo tento broker. Nejde o penetrační test. Migrační dokumentace nyní odpovídá state schema 11; starší zjištění o vynechaných krocích 9→10/10→11 pro aktuální stav neplatí.

Živý Hub, RAG reindex, čistou instalaci, restart, rollback ani provider handshake jsem neověřoval. Testovací běh jsem na tvůj pokyn zastavil; jeho neúplný výstup není použit jako auditní důkaz.

## Co projekt dělá

Local AI Hub propojuje lokální modely a vývojové agenty přes HTTP/MCP, project index a RAG, task/coordination služby, instalátor, aktualizátor a balíčky pro klientské hosty. Důvěryhodnost systému závisí hlavně na lokální bezpečnostní hranici, migraci uživatelského stavu, přesných API kontraktech a obnově indexů po změně modelů či schématu.

## Rozsah a metodika

Hlavní implementační commit 6625d19d mění 499 souborů, přibližně 33 286 vložených a 9 348 odstraněných řádků. Repozitář obsahuje 509 Python modulů pod `src/local_ai_hub` a 1 573 Python souborů pod `tests`. Prošel jsem změněné oblasti a cíleně kontroloval nejrizikovější implementace a kontrakty. V aktuálním necommitnutém diffu TaskStore přechází z list-kompatibilního TaskList na immutable TaskPage. Statická enumerace `list_tasks` volání v `src` a `tools` našla upravené interní přístupy přes `.tasks` a `.query_truncated`; starý `TaskList` symbol se tam nepoužívá. Bez běhu aplikace nelze potvrdit behaviorální paritu pagination/query ani externí konzumenty této veřejně exportované třídy. Neprohlašuji, že jsem ručně přečetl každý řádek všech modulů.

Hlubší zdrojová kontrola pokryla:

- HTTP autorizaci, skutečnou loopback adresu, Host/Origin validaci a odmítnutí vyřazených tokenů/tenant polí.
- Command broker, strukturované argv, shell policy, ověření task worktree a fencing transakce.
- Stavové migrace 6→11, validaci schémat, staged backup/swap a návrat runtime/stavu při chybě.
- RAG reset, fingerprint, detekci cest bez vektorů a poslední uložený stav indexu.
- HTTP/MCP registry, API coverage, provider setup, pluginy, host hooks a ownership ochranu.
- CI/release workflow, package/config pravidla, statickou typovou a lint konfiguraci, dashboard a recovery dokumentaci.

### Matice pokrytí

| Oblast | Prohlédnuté zdroje | Rozsah | Výsledek / limit |
|---|---|---|---|
| Vstup projektu a balení | `README.md`, `pyproject.toml`, `RELEASE.json`, `tools/release_check.py`, release workflow | metadata, dependencies, source/data inclusion, release gate | našel jsem nesoulad security policy a aktuální release metadata; aktuální package build nebyl spuštěn |
| Konfigurace a lifecycle | `src/local_ai_hub/config.py`, `defaults.toml`, `config.toml`, `config.runtime.toml`, `tools/setup.py`, `tools/update_install.py` | schema gate, overlay, instalace a update | lokální konfigurace odmítnuta; čistá instalace a update nebyly spuštěny |
| HTTP hranice | `http_api_auth.py`, `http_api_get.py`, `http_post_tasks.py`, `http_scoped_tasks.py`, `http_route_registry.py`, `http_server.py` | loopback, Host/Origin, routování, request scope, task paging | staticky bez potvrzeného bypassu; žádná živá request akceptace |
| MCP hranice | `mcp_server.py`, `mcp_wire.py`, `mcp_tools_*.py`, MCP contract registry a surface audit | tool exposure, dispatch, normalizace a budget | 8 ručních surface rozhodnutí je zastaralých; handshake nebyl proveden |
| Příkazový broker | `command_authorization.py`, `command_execute.py`, `command_shell.py`, `command_git.py`, transakční/fencing moduly | argv, politika, repo/worktree scope, rollback | broker v kontrolovaných cestách shell nepovoluje; níže uvedená tréninková parser cesta jej obchází |
| Stav a Agent OS | `agent_events.py`, `agent_tasks.py`, `agent_memory.py`, `agent_verification.py`, leases, fencing a `tools/state_migrations.py` | event schema, projekce, receipts, migrace a recovery logika | statická kontrola; skutečná migrace/rollback nebyly provedeny |
| Task query změna | celý aktuální diff TaskList→TaskPage, všechny nalezené `list_tasks` call sites v `src`/`tools`, související test diff | typy, serializace, scoped paging, callers | interní call sites aktualizované; přímá kompatibilita veřejně exportovaného `TaskStore` není zachována |
| Preprocessing a index | `preprocess*.py`, `code_index*.py`, `deterministic_index.py`, parsovací a write-actor entrypoints | indexace, watcher, zápisy a obnovy | inventura a cílená statická kontrola; úplný behaviorální/polyglot benchmark nebyl spuštěn |
| RAG a embeddings | `rag.py`, `rag_storage.py`, `rag_index.py`, `rag_search.py`, embedding-space a recovery docs | reset, fingerprint, stale/vectoreless paths, retrieval evidence | opravená detekce prázdných vektorů; reindex/relevance nejsou potvrzené |
| Modely a akcelerace | Laya, Ollama, llama.cpp, scheduler, GPU/OpenVINO, model policy/distribution | policy, lifecycle a optional backends | konfigurace/zdroj kontrolovány; žádné modely, download, inference ani GPU běh |
| Host/plugin integrace | adapter registry, provider instrukce, browser bridge, `PROVIDER_INTEGRATION_MATRIX.md`, setup docs | capability maps a setup states | config se správně odlišuje od host trust/handshake; runtime hosty nebyly spuštěny |
| Telemetrie a dashboard | telemetrie kontrakty/agregace, `ui_static`, npm scripts a dashboard checker | redakce, UI identifiers a typová konfigurace | telemetrii z pracovního stromu jsem záměrně nečetl; aktuální build nebyl spuštěn |
| CI, docs a nástroje | `.github/workflows/ci.yml`, API registrace/coverage, lint/type konfigurace, audit/doctor/release utilities | gate definitions, generator/inventory consistency | workflow definice prošly statickou kontrolou; CI běhy pro přesný SHA nejsou doložené |

Audit zahrnul inventory 509 Python modulů v `src/local_ai_hub`, 127 Python nástrojů pod `tools`, 1 573 testovacích modulů a 296 dokumentačních souborů. Není to ruční čtení každého řádku: v tomto rozsahu jsem použil mapování/skeny a hluboké čtení kritických hranic, persistence, migrací, TaskPage diffu a rizikových cest. Úplné runtime, platformní a každý polyglot parser acceptance zůstává otevřený.

## Závažnost

- **P1 — před vydáním:** konkrétní chyba release brány, bezpečnosti dat nebo důkazů o kontraktech.
- **P2 — před produkční akceptací:** významná provozní či dokumentační mezera.
- **P3 — dlouhodobé zlepšení:** údržba a širší pokrytí bez potvrzeného okamžitého runtime selhání.

## P1 — před vydáním

### A01 — Stavová záloha v kořeni blokuje release kontrolu a může uniknout do balíčku

**Důkaz:** Git status uvádí dvě zálohy konfigurace a adresář stavové zálohy jako nesledovaný obsah. Aktuální python tools/release_check.py --allow-installed skončil FAILED a odmítl databáze pod state.backup-v6-1795512446287817200 jako runtime/build payload. .gitignore ignoruje state/ (řádek 15), nikoli sousední state.backup-v6-…. Pravidla pro config.toml.bak* a config.toml.local-ai-hub-backup-* (řádky 29–33) nepokrývají přítomné config.toml.backup-config-v0-* názvy.

**Dopad:** Release balení blokováno. Záloha může být omylem přidána do commitu/balíčku spolu s databázemi, konfigurací a lokálními modelovými artefakty.

**Doporučení:** Zálohu nemaž. Uchovávej stav mimo source checkout nebo doplň přesná ignore pravidla pro tyto generované názvy. Potom potvrď, že backup stále existuje a release check ignoruje jen určenou stavovou cestu.

**Akceptace:** Release check projde; status neukazuje backupy jako kandidátní obsah; existující data jsou zachována a uložená mimo distribuční strom.

**Evidence:** .gitignore:15, 29–37; aktuální git status; aktuální výstup release_check.

### A02 — Ruff blokuje CI pěti statickými chybami

**Důkaz:** Aktuální ruff check src tools tests hlásí:
1. Nedefinované sandbox_unavailable v tests/test_bounded_app_integration.py:459.
2. Nedefinované connection_ids v tests/test_cross_worktree_hash.py:176.
3. Nedefinované counted_connect v tests/test_cross_worktree_hash.py:187.
4. Nedefinované services_module v tests/test_http_route_operation_acceptance.py:520.
5. Duplicitní klíč advisory v tests/unit/test_diagnostics_export.py:402.

CI spouští ruff check src tools tests jako povinný gate (.github/workflows/ci.yml:51).

**Dopad:** Lint gate je červený. Čtyři nedefinovaná jména ukazují na chybějící fixture/helper scope; duplicitní klíč Python tiše přepíše, takže očekávaný obsah testovacího objektu nemusí být ten zamýšlený.

**Doporučení:** Opravit definici helperů/fixture v odpovídajícím scope a sloučit zamýšlený advisory obsah do jednoho klíče. Po změně znovu spustit pouze lint kontrolu.

**Akceptace:** Ruff projde bez chyb a hodnoty fixture jsou jednoznačné.

### A03 — Agent surface audit hlásí osm zastaralých MCP rozhodnutí

**Důkaz:** python tools/audit_agent_surface.py hlásí Stale pro MCP local_ai_repo.definition, diff, find_references, find_symbol, glob, read_file, references a stat. Kontrola ověřuje soulad současného povrchu s ručně zdůvodněnými záznamy v docs/agent-surface-audit.json.

**Dopad:** Ručně spravovaný audit capabilities neodpovídá canonical MCP registracím. Pokud byly operace záměrně odstraněny, artefakt obsahuje staré popisy; pokud ne, aktuální kontrakt nemá review.

**Doporučení:** Každý záznam porovnat se zdrojovou registry a rozhodnout retain, diagnostic, protocol_boundary nebo odstranění. Operace neobnovovat jen proto, aby kontrola prošla.

**Akceptace:** Kontrola projde; každý záznam má aktuální zdroj a explicitní důvod.

### A04 — Lokální diagnostika se zastaví na neversionované konfiguraci

**Důkaz:** Bezpečné načtení config.toml ukázalo chybějící config_schema_version; totéž platí pro config.runtime.toml, pokud existuje. tools/doctor.py skončil ConfigError: konfigurace vyžaduje config_schema_version = 1. hubctl status skončil stejnou výjimkou při načtení root configu.

**Dopad:** Checkout nedokáže potvrdit stav Hubu, modelů ani endpointů. Implementace odmítá starou konfiguraci fail-closed, což je záměrně bezpečné chování; konkrétní problém je neověřený místní stav.

**Doporučení:** Zachovat původní backupy a použít podporovaný config migration postup na ověřené kopii. Nepřidávat marker ručně. Poté ověřit, že diagnostika načítá config odpovídající runtime verzi.

**Akceptace:** Doctor a status načtou config bez výjimky a správně rozliší stopped/disabled/ready.

### A13 — AST-Grep parser předává cestu souboru přes shell

**Závažnost:** P1 bezpečnostní

**Důkaz:** `tools/model_training/mine_code_triplets.py:358–384` sestaví argv s `file_path` z procházeného repozitáře a spustí obě varianty `subprocess.run(..., shell=True)`. `AST_BIN` se vybírá z PATH, parser se volá při zpracování souboru (`:552–553`). Windows je podporovaná platforma.

**Konkrétní případ:** Když se při tréninkovém mining běhu zpracuje repozitář s názvem souboru obsahujícím shell metaznak, shell může cestu rozparsovat jako další příkaz pod právy uživatele, který Hub spustil. To mění parsování cizího repozitáře na lokální spuštění příkazu.

**Doporučení:** Volat ast-grep přes argv se `shell=False` (výchozí), ověřit dostupný executable a zachovat pevné timeout/output limity. Tréninkové zpracování neznámých repozitářů nepouštět s `shell=True`.

**Akceptace:** žádná cesta ani obsah souboru nevstupuje do shell command line; zvláštní názvy souborů se předají jako jeden argument.

## P2 — před produkční akceptací

### A05 — SECURITY.md uvádí špatnou release řadu

**Důkaz:** SECURITY.md:5 říká current 1.x; pyproject.toml:7 deklaruje 8.0.0.

**Dopad:** Správci nevědí, která release dostává bezpečnostní opravy. To zhoršuje triage a může udržovat nepodporovanou verzi v provozu.

**Doporučení:** Uvést, zda jsou podporovány jen 8.x nebo i starší řady, a přidat kontrolu souladu bezpečnostní politiky s project metadata.

**Akceptace:** Podporované řady v SECURITY.md odpovídají skutečnému release procesu.

### A06 — RAG po v8 resetu stále potřebuje reindex a relevance kontrolu

**Důkaz:** Poslední uložený snapshot v docs/FINAL_COMPLETION_PLAN.md:2237, 2252 uvádí 31 719/31 719 RAG vektorů prázdných, 8 397 cest s vectorless chunky bez workspace markeru, 2 273 preprocess řádků označených RAG-current a 23 projektů ve stavu čekání/chyby. Snapshot říká, že Hub je disabled. Aktuální rag_storage.py:308+ správně rozpozná NULL/prázdné/[] vektory, ale to potvrzuje opětovné zařazení cest, ne dokončené embeddingy.

**Dopad:** Search může být lexikální nebo degradovaný; obnovená detekce nedokazuje kvalitu ani úplnost indexu.

**Doporučení:** Po zprovoznění konfigurace provést kontrolovaný reindex na izolované kopii. Zaznamenat eligible paths, chunky, vektory, backend chyby, retry stav a stejnou označenou query sadu před/po.

**Akceptace:** žádná cesta označená current bez potřebných vektorů; dokončená či explicitně chybová fronta; integrity check a vyhovující retrieval kvalita.

**Omezení:** Čísla jsou uložený stavový snapshot, ne nové čtení živé služby.

### A07 — Provider integrace jsou konfiguračně pokryté, runtime handshake však ne

**Důkaz:** docs/PROVIDER_INTEGRATION_MATRIX.md odděluje configured, installed, enabled, trust, connection a runtime_verification. Dokument výslovně uvádí, že setup host trust a handshake neověřuje a ponechává not_probed_by_setup/not_run.

**Dopad:** Zapsaná MCP/hook konfigurace neznamená, že host plugin důvěřuje, spustí ho nebo naváže spojení.

**Doporučení:** Zachovat oddělené stavy a pro každý podporovaný host definovat clean install, update, uninstall, zachování cizí konfigurace a handshake scénář. Neoznačovat konfiguraci jako runtime úspěch.

**Akceptace:** Každý host má doložené samostatné stavy configured/installed/enabled/trust/connection/runtime.

### A08 — Historická latence a degradace potřebují nové měření

**Důkaz:** docs/FINAL_COMPLETION_PLAN.md obsahuje v7-cutoff telemetrii s vysokou latencí /api/review/diff a /api/context/pack a degradované výsledky search. Stejná evidence upozorňuje, že jde o historický snapshot, Hub je zastaven a aktuální live acceptance chybí.

**Dopad:** Nelze doložit, zda současný v8 kandidát dosahuje očekávané p95/p99, zvládá queue/retries a obnoví se po restartu.

**Doporučení:** Po provozním schválení měřit cold/warm /api/search, /api/context/pack, /api/review/diff, /api/review a /api/solve/repo. Oddělit backend, queue, timeout a storage latenci; svázat data s přesným SHA.

**Akceptace:** nový snapshot má timeframe, počet requestů, status/failure breakdown, SLA a source identity.

### A09 — CI definice existuje, ale výsledek pro přesný HEAD není doložen

**Důkaz:** .github/workflows/ci.yml definuje lint, typing, release a platformní joby. V této práci nebyly ověřeny skutečné GitHub Actions, wheel/sdist instalace ani čistý update/rollback na přesném HEAD f05c1ed403b713e288a5911c5f29d0ffc8dae5b1.

**Dopad:** Lokální statické kontroly neprokazují podporu OS/Python matice ani stav instalovaného balíku.

**Doporučení:** Při release review svázat CI a package smoke s přesným SHA. Pro instalační změny ověřit clean install a aktivaci/rollback na podporovaných OS.

**Akceptace:** požadované workflow zelené pro stejný SHA; wheel/sdist, dependency check a readiness instalované služby úspěšné.

### A14 — TaskStore změnil veřejný list kontrakt bez kompatibilní vrstvy

**Závažnost:** P2 kompatibilita

**Důkaz:** Pracovní diff mění `TaskStore.list_tasks()` z `TaskList(list[TaskState])` na `TaskPage` s tuple `.tasks` (`src/local_ai_hub/agent_task_core.py:440–542`, `agent_task_models.py:423`). `TaskStore` zůstává exportovaný z `agent_tasks.py` a `app.py`; aktualizoval se první party code a fixture, ale dokumentace veřejné metody/compatibility note ne.

**Konkrétní případ:** Přímý konzument `for task in store.list_tasks()` nebo `len(store.list_tasks())` po této změně dostane `TypeError`; hledání všech použití v repozitáři nenajde externí balíčky nebo uživatelský kód.

**Doporučení:** Před vydáním buď zachovat list-like kompatibilní návratový objekt, nebo explicitně označit API jako breaking, popsat nový `.tasks`/`.query_truncated` kontrakt a přenést změnu do odpovídající release verze.

**Akceptace:** dokumentovaný kontrakt, test kompatibility na veřejném importu a jasná release politika pro přímé konzumenty `TaskStore`.

### A10 — Živý Hub plán/receipt nebyl dostupný přes MCP

**Priorita:** P2 procesní omezení
**Důkaz:** V této relaci nebyla k dispozici operace plan_list/plan_board_view ani receipt. Repo pravidla zakazují ručně upravovat plan JSON; lokální plány jsem neměnil.

**Dopad:** Report není připojený k autoritativnímu živému task checkpointu.

**Doporučení:** Až bude Hub MCP dostupný a konfigurace validní, připojit report podporovaným coordination postupem. Needitovat .local-ai-hub/plans/*.json ručně.

**Akceptace:** aktivní auditní task odkazuje na tento dokument, přesný SHA, statické výsledky a otevřené runtime položky.

## P3 — dlouhodobá zlepšení

### A11 — Strict mypy pokrývá jen malý výřez

**Důkaz:** python -m mypy prošel bez chyb, ale pyproject.toml:108–123 obsahuje jen 14 modulů z 509.

**Dopad:** PASS se vztahuje pouze na tento seznam; změny v auth, migracích, RAG a API mimo něj nejsou typově kontrolovány.

**Doporučení:** Postupně rozšiřovat coverage od command authorization, migration helpers, API contracts a response models.

**Akceptace:** nové rizikové moduly se přidávají do strict mypy a CI publikuje aktuální počet.

### A12 — Release checklist potřebuje zřetelné aktuální shrnutí

**Důkaz:** docs/FINAL_COMPLETION_PLAN.md kombinuje chronologii s aktuálními blokátory; řada starších běhů sama varuje, že neověřují současný SHA. Nový docs/PROVIDER_INTEGRATION_MATRIX.md už dobře odděluje config od runtime stavu.

**Dopad:** Reviewer může zaměnit historický PASS za současný stav.

**Doporučení:** Nahoře udržovat krátký current-state seznam s SHA, datem a P1 blokátory; historii ponechat datovanou a označit superseded důkazy.

**Akceptace:** aktuální release stav je čitelný bez procházení celé chronologie; každý PASS má datum, příkaz a SHA.

### A15 — Fast-contract CI spouští jeden acceptance případ dvakrát

**Závažnost:** P3 efektivita CI

**Důkaz:** `.github/workflows/ci.yml:85–90` obsahuje dvakrát tentýž parametrizovaný uzel `tests/test_structural_search_completeness.py::test_structural_search_reports_incomplete_400_file_scan`.

**Dopad:** Fast-contract job opakuje přesně stejný případ, prodlužuje běh a nepřidává další pokrytí.

**Doporučení:** Odstranit jednu kopii nebo ji nahradit zamýšleným jiným scenářem.

**Akceptace:** seznam test node IDs ve workflow je bez duplicit; žádný vynechaný scénář.

## Statická kontrola bezpečnostních hranic

V prohlédnuté části `src/local_ai_hub/http_api_auth.py:67–201` se ověřuje skutečná loopback adresa, Host/Origin a odmítají se vyřazená token/identity pole. Samotný command broker odmítá `shell=True` a mutující Git váže k registrovanému worktree. Samostatný AST-Grep tréninkový nástroj však používá `shell=True` (A13). Stavová migrace používá přesné signatury, zálohu, staged kopii, integritní kontroly a odmítá neznámé schéma.

V těchto kontrolovaných cestách jsem staticky nepotvrdil bypass. Nezahrnuje to úplný threat model každého handleru, knihovny, hooku ani konkurenční runtime průběh.

## Samostatné statické kontroly

| Kontrola | Výsledek | Rozsah |
|---|---|---|
| pyflakes src tools | PASS při této kontrole | Zdrojové a tool moduly. |
| ruff check src tools tests | FAIL: 5 | Čtyři nedefinovaná jména, jeden duplicitní dict klíč v testovacích souborech. |
| python tools/release_check.py --allow-installed | FAIL | State backup obsahuje řadu zakázaných SQLite runtime/build payloadů; pathnames ukazují také uložené build/model artefakty. Obsah jsem nečetl. |
| python tools/surface_inventory.py --check | PASS: 674 řádků | Zdrojový API inventář a oba generované coverage artefakty souhlasí. |
| python tools/audit_agent_surface.py | FAIL: 8 stale | Ruční MCP decisions artefakt není synchronní. |
| git diff --check | PASS při této kontrole | Žádné whitespace chyby. |
| `load_config` contract + metadata probe root configů | FAIL pro aktuální workspace | Existující `config.toml` i `config.runtime.toml` nemají povinné `[local_ai_hub].config_schema_version = 1`; loader odmítá existující config/runtime file bez markeru (`config.py:570–584`). Migraci jsem nespustil. |
| `python tools/hubctl.py plans --root <repo> --json` | BLOCKED | Vrátilo `request was not sent because transport failed before write`, `terminal=true`, `retryable=false`; bez opakování. Aktivní task checkpoint nebyl potvrzen. |

Předchozí audit zaznamenal compileall, mypy nad 14 explicitními moduly, dashboard typecheck/build, dashboard check a prompt-policy check jako PASS před finálními změnami pracovního stromu. V této iteraci jsem je neopakoval; nejde o současný CI ani runtime důkaz.

### Testy

V této auditní iteraci jsem žádný test runner nespustil. Starší předchozí report uvádí přerušený full pytest běh bez finálního souhrnu; ten není důkazem PASS/FAIL a nepatří k této kontrole.

## Stav systému a otevřené důkazy

- Aktuální HEAD je f05c1ed403b713e288a5911c5f29d0ffc8dae5b1; produkt 8.0.0; state schema 11.
- docs/INSTALLER_RECOVERY.md nyní popisuje migrační řetězec 6→7→8→9→10→11.
- surface_inventory.py --check nyní prochází s 674 řádky; starší neúspěšný meziběh vznikl při souběžné změně stromu.
- Aktuální release check selže kvůli nově přítomnému lokálnímu state backupu. Dřívější PASS před vznikem této cesty se na současný filesystem nevztahuje.
- Neznámé host aplikace, jejich plugin trust dialogy, permission sharing a MCP handshakes nebyly automaticky ověřeny. Setup report odlišuje `not_observed_by_setup`/`not_probed_by_setup`; potvrzení konfigurace není runtime důkaz.
- TaskPage diff aktualizoval viditelné first-party call sites, ale symbol search nemůže dokázat, že neexistují externí importy nebo uživatelské skripty.
- Untracked state backup a migration artefakty jsem neotevíral ani nepřesouval; release check je rekurzivně detekoval. Zálohy zachovat, dokud nejsou bezpečně archivovány mimo distribuční strom.
- GitHub Actions výsledky pro aktuální SHA nebyly ověřeny.
- Hub/MCP runtime, clean install, provider handshakes, live RAG a endpoint SLA nebyly ověřeny.
- Historické telemetrické/modelové výsledky nejsou novým měřením tohoto auditu.

## Doporučené pořadí

1. Odstranit `shell=True` z AST-Grep volání a předávat cestu jako argv data.
2. Zachovat zálohy a přesunout runtime state mimo checkout; doplnit přesné ignore patterny pro skutečné názvy.
3. Opravit pět Ruff chyb a rozhodnout osm agent-surface stale položek podle canonical registry.
4. Rozhodnout TaskStore API kompatibilitu a verzování před vydáním.
5. Migrovat konfiguraci podporovaným updaterem, potom ověřit doctor/status.
6. Opravit SECURITY.md a duplicitní CI node.
7. Po provozním povolení spustit Hub nad izolovaným stavem, reindexovat RAG a změřit search/review/context.
8. Svázat CI, wheel/sdist a clean update/rollback akceptaci se stejným SHA; rozšířit strict mypy nad 14 modulů.
9. Oddělit aktuální release stav od historické chronologie.

## Omezení

Audit je statický a cílený na rizikové zdrojové cesty. Neprovedl jsem penetrační test, clean install, živý restart, model download/inference, deployment ani přesné benchmarky. Aktivní Hub plan/receipt nebyl dostupný přes MCP. Uložené provozní údaje jsou historická evidence, ne stav právě běžící služby.

Při souběžné práci se repozitář a commit měnily. Tato verze reportu se vztahuje k uvedenému SHA; před další změnou nebo vydáním znovu ověř HEAD a statické release gates.
