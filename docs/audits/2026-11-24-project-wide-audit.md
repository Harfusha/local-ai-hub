# Audit Local AI Hub — 24. 11. 2026

> Rozšířenou verzi tohoto auditu, která nahrazuje tento úvodní souhrn, najdeš v [detailním auditu projektu](2026-11-24-local-ai-hub-detailni-audit.md).

## Stav a rozsah

Audit vychází z pracovního stromu `C:\Users\Adam\.local-ai-hub`, větve `master`, dne 24. 11. 2026. Strom měl při auditu 400 položek `git status`: 345 změněných/smazaných sledovaných položek a 55 nesledovaných. Závěry proto popisují aktuální pracovní kopii, ne čistý commit ani vydané 7.0.0.

Prošel jsem strukturu celého repozitáře, hlavní uživatelskou a provozní dokumentaci, release plán, existující audit, balíčkovací a testovací konfiguraci, otevřené issue v posledním provozním záznamu a cíleně rizikové oblasti migrací, RAG, diagnostiky a poskytovatelů. Zdrojový strom obsahuje 509 Python souborů a přibližně 200 tisíc řádků. Nečetl jsem ručně každý řádek každého modulu.

Audit je statický a read-only, kromě tohoto nového reportu. Testy, build, instalace, restart Hubu, modelové benchmarky ani živý reindex jsem nespouštěl. Aktivní Local AI Hub MCP nástroje nebyly v tomto běhu dostupné; Hub plán a jeho ověřovací receipt proto nebylo možné synchronizovat. Stávající dirty soubory ani plány jsem neupravoval.

## Kontroly k zachování

- HTTP vrstva ověřuje skutečnou loopback adresu socketu, kontroluje `Host`/`Origin`, odmítá cross-origin požadavky a vede autorizační audit mutací. V této omezené statické kontrole jsem nenašel doložený bypass; nejde o penetrační test. Zdroj: `src/local_ai_hub/http_api_auth.py:67-90, 98-201`.
- CI má release check, kompilaci, `pyflakes`, Ruff, TypeScript kontrolu, `mypy`, integrační a platformní běhy. Matice pokrývá Windows/macOS/Linux a Python 3.11–3.14; celý suite se spouští podle zvolené CI podmínky, ne při každém matrix jobu. Zachovat tyto release brány. Zdroj: `.github/workflows/ci.yml:43-83, 136-180`.
- Core je lokální a loopback-only; `README.md:334-336` to uvádí konzistentně. `SECURITY.md` zůstává nesynchronizované ve verzi release, jak je uvedeno níže.

## Prioritní nálezy

### P1 — Před vydáním uzavřít aktuální pracovní strom

**Důkaz:** 400 položek ve `git status`, změny zasahují zdrojový kód, migrace, HTTP/MCP, klienty, instalátor, dokumentaci i testy. Většina změn dosud nemá jeden ověřený integrovaný výsledek tohoto auditu.

**Doporučení:** Zachovat všechny změny. Rozdělit je podle existujících aktivních plánů a vlastníků, určit přesný release kandidát, zkontrolovat diff po souvislých celcích a spustit požadované brány nad týmž finálním commitem. Neoznačovat celý pracovní strom za hotový podle starších izolovaných běhů.

### P1 — Dokončit v8 RAG reindex a živou akceptaci

**Důkaz:** Aktuální plán hlásí 31 719/31 719 RAG vektorů prázdných, 8 397 cest s vektorovým obsahem chybějícím a bez markeru prostoru a 23 projektů ve stavu čekání/chyby. Hub zůstává vypnutý; re-embedding, živý search a provozní akceptace jsou otevřené. Oprava opětovného zařazení cest má cílené testy, ale ještě neprokazuje obnovenou kvalitu vyhledávání.

**Doporučení:** Po samostatném provozním schválení dokončit reindex po dávkách, potvrdit počty a integritu vektorů, ověřit obnovu po přerušení a porovnat živé vyhledávací případy před/po. Do té doby označit sémantické vyhledávání jako neakceptované.

**Evidence:** `docs/FINAL_COMPLETION_PLAN.md:2234-2255`.

### P1 — Uzavřít release migrací s maticí podporovaných stavů

**Důkaz:** Instalátor používá přesné signatury starých stavů a při neznámém schématu zastaví. V5 cesta je záměrně omezená; některé tenantové záznamy stále vyžadují explicitní konverzi nebo bezpečné odmítnutí. Dokumentace výslovně říká, že podpora konkrétní v5 signatury neznamená podporu každé v5 instalace.

**Doporučení:** Publikovat matici `zdrojová verze × signatura databáze × migrace × záloha × rollback × očekávaný výsledek`. Pro každou podporovanou větev přidat obnovu zálohy po selhání a fixture odpovídající skutečně vydané verzi. Neznámé ani kolidující záznamy nesmí být tiše zahazovány.

**Evidence:** `docs/INSTALLER_RECOVERY.md:80-90`; širší otevřený inventář v `docs/audits/2026-11-24-local-ai-hub-canonical-cleanup.md`.

### P1 — Ověřit provozní spolehlivost, nejen izolovanou logiku

**Důkaz:** Poslední telemetrická základna měla `/api/review/diff` p95 120 s a maximum 156 s. Aktuální změny odkládání a opakování prošly izolovanými výběry, ale plán výslovně ponechává otevřené SLA, restartovou obnovu, živou kvalitu odpovědi a endpoint akceptaci. Hub je vypnutý.

**Doporučení:** Po obnovení služby změřit p50/p95/p99 a úspěšnost pro `/api/review/diff`, `/api/review`, `/api/context/pack`, `/api/solve/repo` a `/api/search`; samostatně vyhodnotit chyby modelu, frontu, timeouty, degradaci a opakování po restartu. Nastavit cílové SLA a alerty z reálných provozních dat.

**Evidence:** `docs/FINAL_COMPLETION_PLAN.md:2241-2248`, `2257-2269`.

### P1 — Vyřešit rozpor v diagnostickém kontraktu context-pack

**Důkaz:** Poslední širší kombinovaný běh měl 81/82 úspěchů; jediný selhal na `tests/test_context_pack_budget_e2e.py::test_mcp_adaptive_context_pack_crosses_http_with_bounded_provenance[detail-on]`, protože odpověď neobsahovala `response_budget.original_tokens`. Zdroj diagnostiky toto pole v režimu bez detailních diagnostik odstraňuje záměrně.

**Doporučení:** Ujasnit kontrakt pro `detail-on` a `detail-off`: které tokenové počty jsou nutné pro klienta a které mohou odhalit diagnostické metadata. Opravit zdroj nebo očekávání testu podle rozhodnutého kontraktu; zachovat kontrolu, že soukromý zdrojový detail neuniká.

**Evidence:** `docs/FINAL_COMPLETION_PLAN.md:2275-2277`; test `tests/test_context_pack_budget_e2e.py:153-157`; projekce `src/local_ai_hub/agent_diagnostics.py:257-263`.

## P2 — Smlouvy, dokumentace a údržba

### Bezpečnostní stránka uvádí chybnou major verzi

`SECURITY.md:3-5` tvrdí, že bezpečnostní opravy cílí na aktuální 1.x. `pyproject.toml:7` a `README.md:3-5` uvádějí aktuální 7.0.0. Opravte podporovanou verzi a přidejte kontrolu synchronizace bezpečnostní stránky s `RELEASE.json`.

### Provider balíčky zatím nemají plně reprodukovatelný zdroj

Existující audit označuje generování a paritu provider balíčků za otevřenou; kopie sdílených dovedností se kontrolují, ale zdrojový profil pro reprodukovatelné balení není verzovaný. Zaveďte sanitizovaný verzovaný profil, přesně definujte podporované hosty a v CI porovnávejte vygenerované MCP schéma, instrukce, hooky a instalační skripty. Do balíčků nikdy nekopírujte uživatelský `config.toml`.

**Evidence:** `docs/audits/2026-11-24-local-ai-hub-canonical-cleanup.md:70-80, 96-106, 254-257`.

### Release plán potřebuje snadno čitelný aktuální stav

`docs/FINAL_COMPLETION_PLAN.md` má přes 2 200 řádků chronologických záznamů; aktuální otevřené brány jsou až na konci. Zachovejte jediný autoritativní plán, ale jeho úvodní checklist udržujte jako stručný aktuální stav: vlastník, blocker, další krok, příkaz a výsledek. Starou chronologii neprezentujte jako dnešní stav.

### Plánovací stav sjednotit přes podporované rozhraní

Existující audit při svém vstupním snímku evidoval 12 aktivních plánů a překryvy mezi dokončovacím plánem, migracemi, endpoint spolehlivostí, modely a Laya. Jde o historický snímek, nikoli potvrzený aktuální počet. Po obnovení Hub MCP znovu načíst aktivní plán, sloučit duplicity a archivovat dokončené či dočasné plány podporovaným rozhraním.

**Evidence:** `docs/audits/2026-11-24-local-ai-hub-canonical-cleanup.md:8-20`.

### Rozšířit typovou kontrolu po dávkách

`pyproject.toml:103-122` zapíná strict mypy, ale jen pro 14 explicitních modulů z 509 Python souborů. Rozšiřujte pokrytí nejprve na hranice auth, storage, migrací, command brokeru a veřejných HTTP/MCP kontraktů. V CI sledujte počet kontrolovaných modulů; neoznačovat současný výběr za typově ověřený celý projekt.

### Rozdělit největší moduly podle odpovědnosti

Inventář našel moduly kolem 1 500–2 900 řádků, například `agent_memory.py` (2 903), `scheduler.py` (2 689), `operation_contracts.py` (2 571), `process_utils.py` (2 190) a `client.py` (2 152). To zvyšuje náklady na review a riziko překryvu; není to samo o sobě důkaz pomalosti.

**Doporučení:** Po stabilizaci rozdělovat jen při jasných hranicích odpovědnosti a s testy veřejných kontraktů. Začít `agent_memory.py`, `scheduler.py` a `process_utils.py`; měřit počet importních závislostí a složitost review, ne honit počet řádků.

### Aktualizovat dokumentaci endpoint výkonu a degradace

Historická telemetrie ukazuje dlouhé requesty, prázdné či chybějící RAG indexy a oříznutí výsledků. Klient musí umět poznat částečný výsledek od úplného. Zveřejněte tabulku limitů, timeoutů, retry podmínek a polí označujících degradaci napříč HTTP/MCP/SDK; ověřujte, že adaptery význam neztrácejí.

**Evidence:** `docs/FINAL_COMPLETION_PLAN.md:2241-2248, 2264-2277`.

## P3 — Optimalizace až po baseline

1. **Context-pack:** Historická p95 byla 16,581 s; opravné zdrojové změny cílí na opakované retrieval dotazy a blokující kandidáty, ale živý dopad nebyl změřen. Přidat subphase timing pro adaptive lookup, index, RAG, kandidáty a serializaci. Potom optimalizovat pouze fázi s největším naměřeným časem.
2. **RAG obnovování:** Po reindexu změřit dávkovou propustnost, CPU/RAM/VRAM, dobu locků a zotavení po přerušení. Nastavit limity dávky podle běžného počítače, ne pouze výkonné testovací sestavy.
3. **Velké moduly:** Refaktoring výše nepředstavovat jako výkonovou optimalizaci bez benchmarku; měřit start, importy, paměť, vyhledávání a latenci jednotlivých cest zvlášť.

## Co je zachováno jako nejisté

- Historické testy uvedené v plánu nejsou novým ověřením aktuálních 400 změn.
- Čísla telemetrie pocházejí z uloženého okna/release cutoff, nikoli z běžící služby.
- Zdroj v8 podle plánu opravuje detekci chybějících vektorů; dokončený reindex ani obnovená kvalita RAG potvrzeny nejsou.
- Statické vyhledání TODO markerů není seznam všech nedokončených funkcí; některé nálezy jsou generovaný kód nebo příklady.
- CodeGraphContext je podle projektu samostatný nástroj, ne závislost Hubu; nepřidávat ho do core jako optimalizaci.
- Tento audit neschvaluje nasazení ani neprohlašuje projekt za hotový.

## Doporučené pořadí

1. Zachovat a roztřídit dirty pracovní strom; určit jeden commit release kandidáta.
2. Uzavřít migrace, v8 reindex, startup/restart a diagnostický response-budget kontrakt.
3. Spustit release/critical brány na konečném commitu a zaznamenat přesné výsledky.
4. Ověřit živé RAG, endpoint SLA, recovery a provider instalace na čisté instalaci.
5. Opravit verzi `SECURITY.md`, uzavřít reprodukovatelnost provider balíčků, typovou kontrolu a aktuální checklist.
6. Teprve potom dělat refaktoring a optimalizace podložené baseline.
