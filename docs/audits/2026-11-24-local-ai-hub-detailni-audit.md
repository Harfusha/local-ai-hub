# Local AI Hub detailní audit celého projektu

**Datum snímku:** 24. 11. 2026
**Repozitář:** `C:\Users\Adam\.local-ai-hub`
**Větev a commit:** `master`, `1b3b8819d6a36a3e938c642f8b27f4f9fe6ddf7b`
**Stav při opětovné kontrole:** 403 položek `git status`, z toho 347 změněných/smazaných sledovaných položek a 56 nesledovaných
**Stav auditu:** detailní statický audit a plán akceptace; projektový kód ani uživatelská data nezměněny

## Shrnutí pro rozhodnutí

Tento pracovní strom nelze označit za hotový ani připravený k vydání. Obsahuje stovky lokálních změn přes runtime, migrace, API, klientské balíčky, instalátor, dokumentaci i testy. Hub je podle posledního uloženého provozního záznamu vypnutý. Po v8 resetu vektory RAG zůstávají prázdné, takže oprava jejich opětovného zařazení do indexace ještě neprokazuje obnovenou sémantickou kvalitu. Dále zůstává neuzavřené živé ověření timeoutů, restartu, poskytovatelů a migrací na skutečně instalovaném stavu.

Nenašel jsem doložený kritický bezpečnostní bypass v prohlédnuté HTTP autorizační hranici. Tato kontrola ale nebyla penetračním testem ani kompletním auditem všech command, filesystem a modelových cest. Projekt má dobré automatické brány: CI kontroluje čistotu balíčku, syntaxi, Ruff, pyflakes, TypeScript, mypy, integrační a platformní běhy; release workflow vytváří inventář závislostí, OSV podklady a SBOM. Problém je stav důkazů nad nynějším pracovním stromem, ne absence těchto mechanismů.

Priorita je stabilizovat a přesně určit jeden kandidátní commit. Pak dokončit v10 migraci, bezpečný reindex a čistou instalační/rollback akceptaci. Nakonec potvrdit živé SLA a kvalitu retrieval. Teprve na tom základě uzavřít dokumentační nesoulady, balíčky poskytovatelů a dlouhodobou údržbu.

## Prioritní registr

| ID | Priorita | Oblast | Stav podle dostupných důkazů |
|---|---|---|---|
| A01 | P1 | Integrace pracovního stromu | 403 lokálních změn; finální společný výsledek neověřen |
| A02 | P1 | Startup a živý provoz | Hub vypnutý; startup a recovery otevřené |
| A03 | P1 | Reindex RAG | vektory prázdné; živé obnovení nepotvrzeno |
| A04 | P1 | Úplnost search | trace ukazují degradaci a limity; po reindexu zopakovat akceptaci |
| A05 | P1 | Review a fronta | historická chybovost a dlouhá p95; live SLA důkaz chybí |
| A06 | P1 | Context pack | p95 16,581 s; fáze nejsou plně rozlišeny |
| A07 | P1 | Response budget | známý nesoulad diagnostiky a testu |
| A08 | P1 | Persistované migrace | instalovaná migrace a rollback nejsou akceptované |
| A09 | P2 | Migrační dokumentace | recovery návod vynechává verzi 10 |
| A10 | P1 | Config migrace | všechny config vstupy potřebují update akceptaci |
| A11 | P1 | Laya capture | shadow/provenance; end-to-end přínos neprokázán |
| A12 | P1 | GPU fence | starší `outcome_unknown`; vlastnictví znovu ověřit |
| A13 | P2 | HTTP dispatch | named boundary přechod probíhá |
| A14 | P2 | API/eval docs | část coverage zachycuje historický action surface |
| A15 | P2 | Provider bundles | reproducible tracked profile chybí |
| A16 | P2 | Security version | `SECURITY.md` uvádí řadu 1.x místo 7.0.0 |
| A17 | P2 | Lokální threat model | loopback trust boundary musí zůstat explicitní |
| A18 | P2 | Model provisioning | clean-cache první běh nepotvrzen |
| A19 | P2 | Velký search | historický cold 100k-file request vracel 503 |
| A20 | P2 | Typová kontrola | strict mypy pokrývá 14 modulů z 509 |
| A21 | P2 | Údržba modulů | několik modulů má přes 2 000 řádků |
| A22 | P2 | Release checklist | dlouhá chronologie komplikuje aktuální verdikt |
| A23 | P2 | Plánovací stav | současný Hub plan list nebyl dostupný |
| A24 | P2 | Supply chain | inventory a SBOM existují; candidate výsledek chybí |
| A25 | P1 | CI akceptace | workflow definované; současný kandidát nespouštěn |
| A26 | P1 | Instalované migrace | fixture nenahrazuje staging update/rollback |
| A27 | P2 | Modelová kvalita | malé evaly nejsou provozní akceptace |
| A28 | P2 | Klientští hosté | clean install/update/uninstall matrix otevřená |
| A29 | P2 | Zálohy a exporty | privacy/restore review není kompletní |
| A30 | P2 | Evidence provenance | historické výsledky vázat na přesný snapshot |

Priorita P1 označuje blokátor vydání nebo provozní důkaz, který může ovlivnit dostupnost, integritu dat či důvěryhodnost výsledků. P2 označuje důležitý produktový, bezpečnostní nebo údržbový dluh. P3 označuje práci podmíněnou měřením. „Otevřené“ znamená, že dostupný zdrojový stav či auditní evidence neprokazuje akceptaci; neznamená to automaticky chybu v každém nasazení.

## Rozsah a síla důkazů

Při aktuálním snímku měl `src/local_ai_hub` 509 Python souborů a přibližně 200 tisíc řádků. `tests` obsahoval 1 565 souborů `test_*.py`. CI definuje čtyři workflow. Zkontroloval jsem strukturu repozitáře, hlavní release a instalační dokumentaci, existující podrobný audit, migration registry, version guard, HTTP authorization boundary, CI a release workflow, package/type-check konfiguraci a současné záznamy o provozu, výkonu a modelové kvalitě.

Současný commit `HEAD` zůstal stejný jako při předchozím auditu, avšak počet lokálních změn vzrostl ze 400 na 403 položek. Rozdíly vznikly mezi snímky; neprováděl jsem plošné porovnání všech nových změn s původním stavem. Audit je proto přesný pro uvedený časový snímek a nesmí být považován za schválení všech hunks.

Žádný test, build, instalace, restart, migrace, síťový modelový download ani živý benchmark jsem v tomto pokračování nespustil. Čísla a úspěchy převzaté z `docs/FINAL_COMPLETION_PLAN.md` nebo předchozího auditu jsou označeny jako uložené či historické. Není to nová verifikace současných 403 změn. Lokální AI Hub MCP nebyl dostupný, proto se nepodařilo načíst živý plán, lease ani receipt. Přesné současné aktivní plánové stavy zůstávají neověřené.

## Zjištění

### A01 Jediný finální kandidát zatím neexistuje

**Priorita:** P1 · **Stav:** otevřený integrační blokátor

`git status` obsahoval 403 položek, z toho 347 změněných nebo odstraněných sledovaných položek a 56 nesledovaných. Změny zasahují stovky souborů runtime, MCP/HTTP, preprocessingu, Agent OS, instalátoru, provider pluginů, generovaného obsahu, plánů a testů. Některé testy a změny dokumentů jsou nesledované, další soubory jsou smazané. Při takovém rozsahu nejde bezpečně vyvozovat, že dřívější úspěch jedné sady reprezentuje celý kandidát.

**Dopad:** Rozdíly zdroj–test–generátor–dokumentace mohou zůstat skryté. Záměna historického PASS za finální PASS může vydat napůl integrovanou migraci nebo veřejnou smlouvu.

**Doporučení:** Zachovat každý soubor. Sestavit změnový katalog podle existujících plánů a odpovědností. Přesně určit, které změny patří do jednoho release kandidáta. Reviewovat diff po logických celcích, zaznamenat vynechané či odložené soubory a poté provést všechny release gates nad jedním commit SHA.

**Akceptace:** Čistý release candidate; žádná neklasifikovaná změna; aktualizovaný jediný autoritativní plán; kompletní výsledky CI, package smoke a cílených testů svázané s kandidátním SHA. `git status` čistý po přípravě kandidáta nebo explicitní seznam povolených release artefaktů.

### A02 Vypnutý Hub nemá současný provozní verdikt

**Priorita:** P1 · **Stav:** otevřené provozní ověření

Poslední uložený plán uvádí `state/service.disabled`; uvádí také, že kompletní startup po posledních změnách neproběhl. Statické načtení konfigurace, `compileall` či izolované HTTP testy neprokazují zotavení supervisoru, migrace při startu, vznik klientských konfigurací ani funkční dashboard.

**Dopad:** Chyba může existovat pouze při startu, při otevření databáze, při locku, při připojení modelového endpointu nebo po restartu. Zdrojem rizika jsou zejména současné config/state schéma přechody a nové retrieval/runtime lanes.

**Doporučení:** Po zafixování kandidáta použít izolovanou kopii skutečného stavu a samostatnou čistou instalaci. Zachytit start, readiness, všechny writer lifecycle stavy, shutdown, tvrdé ukončení a obnovu. Poté ověřit služby klientů a jejich opětovný handshake. Neprovádět to nad nechráněným jediným kopírovacím originálem.

**Akceptace:** Úspěšné cold start i restart na čisté instalaci; žádná nevyřešená migrace; správné přežití restartu; dashboard a podporovaní klienti komunikují s aktuálním endpointem; žádný opuštěný writer lock nebo neznámý task.

**Evidence:** `docs/FINAL_COMPLETION_PLAN.md:2234-2239, 2241-2248`.

### A03 RAG vektory po resetu ještě nejsou obnovené

**Priorita:** P1 · **Stav:** kódová oprava potvrzena v uložených testech; provoz otevřen

Uložený stopped-state snapshot obsahuje 31 719 chunků RAG bez vektorů, 8 397 cest bez vektorů a markeru prostoru, 2 273 preprocess záznamů stále označených jako RAG-current, 23 projektů čekajících nebo v chybě a pět projektů s embedding chybou. Dokumentace popisuje opravu `RAGStorageMixin.indexed_paths()`, která nyní vyhodnocuje i NULL, prázdné a `'[]'` vektory, když marker prostoru chybí.

**Dopad:** Před opravou mohl vektorless dokument vypadat jako zaindexovaný. Po opravě je schopnost jeho opětovného zařazení prokázána cílenými testy; vytvoření všech vektorů, kvalita rankingů a provozní rychlost prokázány nejsou. Search může vracet pouze lexikální výsledek nebo viditelně degradovanou odpověď.

**Doporučení:** Na izolované kopii spustit reindex pod dohledem. Sledovat backlog, chyby embedding backendu, přerušení, znovuzařazení, duplicitní zápisy a restart. Před a po zhodnotit stejný označený retrieval dataset, včetně českých dotazů, změněných/smazaných souborů a případů se shodným obsahem.

**Akceptace:** Očekávaný počet způsobilých chunků a vektorů; žádný projekt tiše označený current s chybějícím vektorem; integrity check databází; dokončená fronta nebo výslovný retry stav; relevance/recall nad schváleným datasetem; živý search bez skryté degradace.

**Evidence:** `docs/FINAL_COMPLETION_PLAN.md:2250-2255`.

### A04 Search musí odlišit úplný výsledek od degradovaného

**Priorita:** P1 · **Stav:** provozní akceptace otevřená

Z uloženého okna 36 degraded `/api/search` trace mělo 26 `rag_index_missing`, 5 `source_read_uncertain`, 3 `embedding_backend` a 2 `embedding_space_mismatch`. 35 trace signalizovalo `result_limit` a 8 `candidate_file_limit`; položky se překrývají. Zdrojová nejistota má zůstat fail-closed a limity musí být viditelně označené.

**Dopad:** Agent může zaměnit omezený seznam kandidátů za kompletní pokrytí repozitáře. U code search to může vést k přehlédnutí odpovídající implementace či bezpečnostní kontroly.

**Doporučení:** Po reindexu otestovat úplnost zvlášť pro lexical, RAG i hybrid. U každého endpointu a MCP projekce zachovat `truncated`, degradaci, příčinu a případný další cursor. Ověřit, že SDK a všechny adaptéry tyto údaje nezahazují a že výsledek s chybou čtení není označen jako úplný.

**Akceptace:** Známe předpokládanou množinu výsledků; limity vyvolají explicitní značku neúplnosti; klient zobrazí retry/omezení; žádná silent-success odpověď pro nejistý obsah. Znovu změřit až na obnoveném vektorovém indexu.

**Evidence:** `docs/FINAL_COMPLETION_PLAN.md:2247-2255`; kontrakty v `src/local_ai_hub/response_budget.py` a `src/local_ai_hub/mcp_wire.py`.

### A05 Review endpointy mají vážnou historickou latenci a chybovost

**Priorita:** P1 · **Stav:** změny delivery policy mají izolované testy; live SLA otevřené

Release-cutoff telemetrie zaznamenala u `/api/review/diff` 53 volání, z toho 46 neúspěšných. P95 bylo 120,012 sekundy, maximum 156,142 sekundy. Další historické p95: `/api/review` 29,911 s a `/api/solve/repo` 11,276 s. Chybové stavy zahrnovaly queue-age 503, upstream 500 a `outcome_unknown`. Novější změny automatického odložení pomalých endpointů, omezených retry a mapování modelových chyb mají cílené testy, ne však aktuální živý SLA důkaz.

**Dopad:** Review může překročit praktické timeouty klientů, pokračovat v práci i po zrušení požadavku nebo být opakováno při nejasném výsledku. 422/502 mapování správně rozlišuje některá selhání, ale samo nesnižuje dobu ani nezlepšuje modelovou kvalitu.

**Doporučení:** Změřit request end-to-end včetně fronty, inference, chunking/review synthesis a HTTP přenosu. Ověřit cancel-on-disconnect, idempotenci retry, restart uprostřed jobu a přenos statusů napříč HTTP–MCP–SDK. Nastavit konkrétní cíle pro P95/P99 a úspěšnost. Zahrnout modelové výstupy s truncation, upstream 500, invalid JSON a částečným review.

**Akceptace:** SLA pro každý endpoint; bounded timeout a queue age; retry pouze tam, kde je operace bezpečně idempotentní; žádný částečný review označený za dokončený; po restartu buď dohledatelný job, nebo explicitní terminální stav.

**Evidence:** `docs/FINAL_COMPLETION_PLAN.md:2241-2248, 2257-2262`.

### A06 Context pack zůstává pomalý a subphase telemetry chybí

**Priorita:** P1 · **Stav:** zdrojové optimalizace izolovaně ověřené; runtime dopad neznámý

V release okně mělo 73 úspěšných `/api/context/pack` requestů p50 7,305 s, p95 16,581 s a maximum 29,411 s. Trace přisuzuje pomalost převážně handleru, ne serializaci. Jeden 16,823sekundový adaptive request degradoval na deterministic fallback, který vrátil nula evidence. Jiný trace naměřil 26,446 s přípravné fáze. Záznam výslovně říká, že telemetry nerozděluje adaptive stale-evidence cestu do jednotlivých backend fází.

V pracovním stromu byly odstraněny opakované `related_paths` lookupy a kandidáti preprocessingu přesunuti do omezené single-worker lane s jedním místem pro admission. Cílené testy potvrdily reuse i deadline. Živý latency delta doložen není.

**Doporučení:** Instrumentovat samostatně code-index, deterministic resolver, RAG, stale check, preprocess candidates, backend inference a serializaci. Uchovat request ID a mode; nezapisovat source text ani soukromý modelový výstup. Potom provést stejné párové benchmarky nad studenou i teplou cache a různě velkými repozitáři.

**Akceptace:** P95/P99 rozdělené na fáze; žádná fáze blokuje nad celkovým deadline; timeout vrací explicitní degradaci; warm/cold cache srovnání; dokazatelný rozdíl před/po zdrojové optimalizaci.

**Evidence:** `docs/FINAL_COMPLETION_PLAN.md:2264-2277`.

### A07 Response-budget test a diagnostická ochrana nemají jednotný kontrakt

**Priorita:** P1 · **Stav:** známý nesoulad očekávání a projekce

Širší výběr 82 testů měl jeden neúspěch: `test_mcp_adaptive_context_pack_crosses_http_with_bounded_provenance[detail-on]` čeká `response_budget.original_tokens`, které odpověď neobsahuje. Projekce diagnostiky v `src/local_ai_hub/agent_diagnostics.py` odstraňuje toto pole, pokud nejsou povolené podrobné diagnostiky. Oddělené testy pro `detail-off` naopak ověřují jeho nepřítomnost.

**Dopad:** Nejasnost může buď blokovat CI, nebo vést k nechtěnému úniku informace o velikosti/složení předprojekčního payloadu. Pole ovlivňuje klientské pochopení truncation i diagnostickou privacy smlouvu.

**Doporučení:** Zapsat veřejný kontrakt pro detail-on/off do MCP/HTTP/SDK dokumentace. Určit, zda `original_tokens` je běžný rozpočtový údaj, citlivá diagnostika, nebo obojí v odlišných kontextech. Testovat jednu kanonickou projekci přes HTTP i MCP, včetně artifact reference a bounded outputu.

**Akceptace:** Pro každý detail režim existuje jedno očekávání napříč handlerem, wire projekcí a testem. Privátní zdrojové úryvky zůstanou nedostupné. Detailní pole jsou explicitně opt-in nebo veřejná dle schváleného kontraktu.

**Evidence:** `docs/FINAL_COMPLETION_PLAN.md:2275-2277`; `tests/test_context_pack_budget_e2e.py:153-157`; `src/local_ai_hub/agent_diagnostics.py:257-263`.

### A08 Migrace stavu jsou přesné, ale produkční vstupy a rollback potřebují celý release průchod

**Priorita:** P1 · **Stav:** offline fixture řetězec má řadu ověření; instalovaná migrace zůstává otevřená

Aktuální `src/local_ai_hub/state_lifecycle.py` uvádí `CURRENT_STATE_VERSION = 10`. Migrační historie pokrývá verze 6→7 (Agent Memory/preprocess), 7→8 (archiv retired board), 8→9 (endpoint stats) a 9→10 (přesná známá historická Laya telemetry row shape). V5 vstup je bez markeru a přijat pouze při přesné rozpoznané Agent State signatuře; neznámá DB, retired tenant provenance, poškozený sidecar nebo neznámá board/telemetry schémata mají zastavit migraci a zachovat zálohu.

**Dopad:** Přísné odmítnutí chrání data, ale zvyšuje nutnost přesně definovat podporované vstupy a operátorskou obnovu. Jediná úspěšná testovací fixture neprokazuje všechny skutečné historické soubory, symlinky, zamčené DB a přerušené update kroky.

**Doporučení:** Udržovat matici podpisů vydaných verzí a každé SQLite tabulky. Z každého podporovaného vstupu otestovat migraci, integritu, archiv, rollback po každé fázi, kolizi, orphan sidecar a současný proces s otevřenou DB. Zaznamenat SHA/count bez ukládání citlivých hodnot do logu.

**Akceptace:** Pro každý veřejně podporovaný zdroj existuje fixture z reálného tagu. Migrace je idempotentní nebo jasně jednorázová. Failure injection zachová originál a ověřenou zálohu. Runtime už nepřidává staré sloupce za běhu.

**Evidence:** `src/local_ai_hub/state_lifecycle.py:15`; `tools/state_migrations.py`; `docs/INSTALLER_RECOVERY.md:76,90`; `docs/audits/2026-11-24-local-ai-hub-canonical-cleanup.md` části o v5 signatuře a migraci 9→10.

### A09 Instalační dokumentace vynechává migraci 9→10

**Priorita:** P2 · **Stav:** potvrzený source/document mismatch

`src/local_ai_hub/state_lifecycle.py` už deklaruje verzi 10 a `tools/state_migrations.py` obsahuje migraci Laya telemetry 9→10. `docs/INSTALLER_RECOVERY.md:90` však stále popisuje v5 řetězec pouze jako 6→7→8→9. To je konkrétní rozpor, ne pouze chybějící obecné vysvětlení.

**Dopad:** Operátor nemusí vědět, že upgrade převádí uložené telemetry řádky. Historický řádek v hlavním plánu může být zaměněn za aktuální; chyba při upgradu tak komplikuje podporu a obnovu.

**Doporučení:** Aktualizovat recovery návod na aktuální v10 řetězec, popsat exact signature a chování při odmítnutí, přidat příklad `requires_manual_migration`, umístění a zacházení se zálohou a instrukci, jak validovat skutečnou obnovu. Přidat dokumentační drift check nad `CURRENT_STATE_VERSION` a registry.

**Akceptace:** Návod, setup/update prompt, registry, příklad reportu a testovací matice souhlasí s v10; kontrola najde chybějící migrační hranu.

### A10 Config schema version je správně tvrdá hranice, ale všechny vstupní soubory musí projít aktualizátorem

**Priorita:** P1 při upgradu · **Stav:** runtime odmítnutí a offline converter existují; clean install/update akceptace otevřená

`src/local_ai_hub/config.py` odmítá existující config bez `local_ai_hub.config_schema_version = 1`. `tools/config_migrations.py` převádí verzi 0 se zálohou; runtime override má být stejnou smlouvou řízen. Uložený audit popsal selhání `hubctl plans`, protože nainstalovaný `config.toml` byl bez markeru, a vyžadoval update migraci místo tichého runtime přijetí. Tuto konkrétní uživatelskou konfiguraci jsem v tomto běhu znovu nečetl.

**Dopad:** Tvrdá validace brání chybnému sloučení, ale může zablokovat dashboard nebo CLI dřív, než operátor dokáže spustit podporovanou konverzi. Riziko je vysoké pro různé zdroje configu, runtime override a neúplný atomický zápis.

**Doporučení:** Zmapovat všechny config cesty: základní TOML, runtime overlay, profile, dashboard edit, setup, update a testovací fixtures. Každá má mít stejné pořadí: ověření původu, vedlejší ověřená záloha, atomický zápis, read-back, verifikační report. Invalidní config nesmí být částečně sloučen s defaulty.

**Akceptace:** Všechny supported install/update profily přejdou; neznámá verze zůstane beze změny; rollback obnoví původní bajty; dashboard změna odmítne starý override s jasnou cestou obnovy.

**Evidence:** `src/local_ai_hub/config.py:519-582`; `tools/config_migrations.py`; `docs/audits/2026-11-24-local-ai-hub-canonical-cleanup.md` část o strict config schema.

### A11 Laya capture má ochranné provenance brány, chybí provozní důkaz datové smyčky

**Priorita:** P1 pro deklarované Laya rozhodování · **Stav:** shadow/advisory fungování částečně testováno; end-to-end otevřené

Laya rozhodnutí mají být advisory/shadow, navázaná na repo identity, evidence a následné task verification. Starší provozní snapshot uvádí mnoho `/api/search`, `/api/repo/code-index` a `/api/context/pack` bez task/evidence ID, takže nevznikaly použitelné kandidáty. Evidence z 17. 11. uváděla sedm pending kandidátů; nejde o aktuální počítadlo. Uživatelská produktová politika zakazuje, aby doporučení modelu samo změnilo runtime bez deterministic server baseline.

**Dopad:** Bez kompletního provenance nelze spolehlivě měřit, zda Laya zlepšuje práci; malé vzorky mohou dát falešný pocit kvality. Bez ověření opt-in/shadow boundary by chybný model mohl ovlivnit task nebo model route.

**Doporučení:** Pro každé decision type definovat vstupní důkazy, baseline, `decision_id`, task ID, receipt, outcome, label a retenční pravidla. Oddělit capture acceptance od model quality evaluation. Pokrýt chybějící a duplicitní identifikátory, zamítnutí, task cancel, opravu labelu a import historical telemetry v10.

**Akceptace:** V kontrolované end-to-end sérii každý candidate dohledatelný ke zdroji a receipt; bez evidence žádný training candidate; Laya se nemůže změnit na autoritativní akci; eval dataset oddělen od trénovacích záznamů.

**Evidence:** `docs/FINAL_COMPLETION_PLAN.md:2210-2217`; `src/local_ai_hub/app_laya_runtime.py`; `src/local_ai_hub/laya_rl.py`; `tools/state_migrations.py`.

### A12 Ownerless GPU fence je provozní blokátor; neuvolňovat bez nové identity stavu

**Priorita:** P1 pro GPU operace · **Stav:** starý `outcome_unknown`; současný vlastník neověřen

Completion plan historicky zaznamenává `legacy_digest_only_fence` jako čekající ruční zásah po `outcome_unknown`. Současná instrukce požaduje ověřit vlastníka a stav rezervace před změnou či uvolněním. Při tomto auditu nebyl dostupný live reservation status, takže nelze tvrdit, že fence stále drží nebo že už neexistuje.

**Dopad:** Slepé uvolnění může narušit cizí živý GPU job; slepé ponechání může blokovat povolený inference/benchmark. Tento stav také brání úplnému modelovému výkonovému auditu.

**Doporučení:** Obnovit dostupný koordinátor. Načíst přesnou identitu rezervace, generaci, lease, expiraci, vlastníka a scheduler capacity. Pokud schema vyžaduje consent, nezaměňovat auditní doporučení s consent. Každé ruční rozhodnutí zaznamenat podle autorizovaného Hub rozhraní.

**Akceptace:** Čerstvý status, známý vlastník nebo důkaz jeho smrti, odpovídající generation/lease a explicitní disposition. Do té doby žádný GPU stres test ani ruční release.

**Evidence:** `docs/FINAL_COMPLETION_PLAN.md:49,2217,2232`.

### A13 HTTP POST dispatch se stále převádí z podmínek na pojmenované hranice

**Priorita:** P2 · **Stav:** bezpečná refaktorizace probíhá; konvergence nedokončena

Auditní snapshot z 24. 11. eviduje 182 aktivních POST route IDs, z nich 40 přes pojmenované boundary a 142 stále ve větvích `do_POST`. Toto je stav refaktorování, nikoli důkaz, že 142 tras jsou staré aliases nebo mrtvý kód. Hlavní společné gate pro auth, mode, recovery, trace a payload mají zůstat před dispatch.

**Dopad:** Dlouhý conditional řetězec zvyšuje riziko, že budoucí route vynechá společný gate, změní pořadí nebo předá jiný argument. Na druhé straně hromadný extraction může vytvořit různé error boundary nebo změnit HTTP status.

**Doporučení:** Migrovat po skupinách podle stejného service boundary. Registry musí být jediný action source, ale named handler má přesně zachovat coercion, status, cancellation, permission a audit. Každý nový route testovat pro úspěch, invalid payload, authorization failure, mode rejection, cancellation a backend failure.

**Akceptace:** `surface_inventory` a `audit_agent_surface` bez driftu; dispatch inventory shodná s registry; žádná ztracená route; stejné testované odpovědi přes HTTP i SDK; žádné orphan branch.

**Evidence:** `src/local_ai_hub/http_route_registry.py:18,204-321`; `docs/audits/2026-11-24-local-ai-hub-canonical-cleanup.md` část `current HTTP dispatch inventory` a následné agent-state slices.

### A14 API action coverage a eval scénáře musí odlišit současný povrch od historických oracle

**Priorita:** P2 · **Stav:** dokumentace/eval scope vyžaduje další reconciliaci

Existující audit označuje `docs/agent-evaluation/mcp-action-coverage.md` a párové prompt scénáře za zachycený povrch před odchodem některých operací. Současná API coverage se průběžně regeneruje z operation contracts; staré fixtures přitom mohou zůstávat validní historický test oracle, pokud jsou takto označené.

**Dopad:** Stale action katalog může podhodnotit aktuální možnosti nebo učit klienta používat odstraněné vstupy. Naopak automatické mazání historických scénářů by odstranilo důkaz, že odstraněný alias je odmítnut.

**Doporučení:** Přiřadit každému akčnímu řádku status `current`, `retired-rejection`, `migration-only` nebo `historical-only`, zdroj kontraktu, provider coverage a test. V CI generovat aktuální action matrix z `operation_contracts.py`; historické fixtures označit a validovat jako odmítnuté inputy.

**Akceptace:** Dokumenty, MCP schema, HTTP route, Python SDK a provider adaptation mají stejnou current action set; každá výjimka má účel a test. Žádný test nesmí považovat odstraněný alias za podporovaný behavior.

**Evidence:** `docs/audits/2026-11-24-local-ai-hub-canonical-cleanup.md:106-116`; `src/local_ai_hub/operation_contracts.py`; `docs/API_COVERAGE.md`.

### A15 Provider balíčky se nekontrolují proti reprodukovatelnému sledovanému profilu

**Priorita:** P2 · **Stav:** potvrzená mezera reprodukovatelnosti

Sedm provider bundle kopií se podle současného auditu shodovalo s ignorovaným vygenerovaným výstupem. Test porovnává lokální mirror, nikoli výsledek generování pouze ze sledovaného source tree s přesně verzovaným profilem. Samostatný prototyp neutrálního balíčku byl odmítnut, protože přišel o potřebnou Laya/capability guidance. OpenCode má záměrně jiný setup a nemá sdílené skills v balíčku.

**Dopad:** Čistý klon nemusí vygenerovat stejný provider balíček jako lokální instalace. Změna uživatelského configu může omylem ovlivnit veřejný output. Neúplná guidance může ztratit capability gates nebo současný action schema.

**Doporučení:** Schválit verzovaný, sanitizovaný statický profil, který zachová aktivní Laya, MCP-authoritative a high/max capability text. Vygenerovat všechny bundles z tracked inputs v temporary clean root; porovnat manifesty a provider-specific exceptions. Nikdy nepoužít soukromý `config.toml` jako generovací zdroj.

**Akceptace:** Nový klon znovu vytvoří identické balíčky. Diff je deterministický; všechny hosty mají popsanou instalaci, update, odstranění a capability matrix. OpenCode zůstává ověřen jako vědomá výjimka.

**Evidence:** `docs/audits/2026-11-24-local-ai-hub-canonical-cleanup.md:206-211,254-257`; `tests/test_provider_plugin_bundles.py`.

### A16 Security dokumentace má nesprávné číslo podporované řady

**Priorita:** P2 · **Stav:** potvrzená dokumentační chyba

`SECURITY.md:3-5` uvádí, že bezpečnostní opravy cílí na současné vydání 1.x. Balíček a README uvádějí verzi 7.0.0. Ostatní část bezpečnostní stránky správně popisuje loopback-only službu, důvěryhodný OS účet a absenci Hub API tokenu.

**Dopad:** Uživatel zranitelné nebo staré instalace nepozná, zda je stále podporovaná. Bezpečnostní report může být veden podle neexistujícího release kanálu.

**Doporučení:** Opravit podporovaný tag/major/minor a definovat dobu podpory. Přidat check proti `pyproject.toml`/`RELEASE.json` a při každé major změně provést security page review. Nepřevzít verzi z textu release history.

**Akceptace:** Dokumentace ukazuje přesnou supported policy; automatická kontrola selže při stale major verzi.

### A17 Threat model je bezpečný jen při důvěryhodném lokálním účtu

**Priorita:** P2 · **Stav:** deklarovaný deployment boundary; nutné zachovat

HTTP authorization kontroluje loopback adresu socketu, Host a Origin, odmítá retired identity fields a audituje mutace. `SECURITY.md` současně uvádí, že loopback API nemá token a chrání jej OS účet a stroj. Tato architektura odpovídá jednomu lidskému vlastníkovi na jednom počítači, ale neposkytuje oddělení mezi nedůvěryhodnými lokálními procesy nebo více OS uživateli.

**Dopad:** Lokální škodlivý proces má síťový přístup k místním API a soubory state/backup/index obsahují citlivé derived code data. Label v lease/memory není identita ani autentizace. Otevření do LAN by mimořádně změnilo threat model.

**Doporučení:** Zachovat loopback bind bez remote override; ověřovat host/origin i pro všechny nové mutační trasy. Chráníme state, logs, indexy, exporty a zálohy OS oprávněními. Výslovně odmítat tvrzení o tenant isolation/API tokenu. Multi-user deployment vyžaduje nové authenticated principaly a návrh všech klíčů/cache/tabulek.

**Akceptace:** Security regresní testy na non-loopback, DNS rebinding, cross-origin, retired headers, identity injection, write authorization a backup permissions. Žádný nástroj nesmí prezentovat request label jako ověřenou identitu.

**Evidence:** `src/local_ai_hub/http_api_auth.py:67-201`; `src/local_ai_hub/http_server.py:365-374,1363-1364`; `SECURITY.md:13-30`.

### A18 Čisté stažení a první provisioning modelu ještě nemají kompletní důkaz

**Priorita:** P2 · **Stav:** artefakt metadata a pin ověřeny, clean-cache běh neproveden

Aktuální preprocessing model má být pinovaný na přesný revision a SHA-256 před registrací. Uložený záznam potvrdil veřejnou HF repository, LFS velikost a digest proti lokálnímu artefaktu. Čistý cache first-use běh ale nebyl proveden. To je důležitá mezera, protože nainstalovaná Ollama/model path, lokální cache a setup report mohou mít jiný stav než metadata request.

**Dopad:** Instalace bez existujícího modelu může selhat při přesměrování, partial download, kvótě, nekompatibilní runtime nebo přerušení bez bezpečného resume/cleanup.

**Doporučení:** Na čistém izolovaném state dir provést opt-in provisioning bez existujícího cache. Ověřit TLS/redirect, digest mismatch refusal, disk full, interrupt, resume, already-present same digest, invalid manifest, offline rerun a install report. Žádný model pull v běžném CI bez explicitní opt-in.

**Akceptace:** První instalace buď vytvoří přesný pinned artefakt, nebo vrátí srozumitelný terminální stav; partial soubory nejsou zaregistrované; chybný hash se odmítne; offline druhý start funguje.

**Evidence:** `docs/FINAL_COMPLETION_PLAN.md:2278`; `docs/MODEL_DISTRIBUTION.md`; `tools/setup.py`.

### A19 Velký cold search má nevyřešenou historickou 503

**Priorita:** P2 · **Stav:** starý failure-path benchmark; aktuální stav neověřen

Historický 100 000-file Windows cold search při defaultním osmivteřinovém ripgrep limitu vracel HTTP 503. Následně byla optimalizována failure path: počet source reads v bounded případě klesl na nulu a paired failure-path čas se zlepšil. Záznam zároveň výslovně uvádí, že successful exact search v default budget na této velikosti zůstával otevřený. Tyto benchmarky odpovídají starším checkoutům a nejsou čerstvým potvrzením současného zdroje.

**Dopad:** Výkonový limit může pro velký repozitář vypadat jako výpadek. Uživatel nemusí rozlišit „překročený rozsah“ od chyby backendu. Zvýšení timeoutu bez profilu by mohlo pouze blokovat request déle.

**Doporučení:** Na aktuálním kandidátu měřit cold/warm exact search 10k/100k souborů na Windows a Linuxu, default i explicitní širší budget, s výsledky úplnými i při scan bound. Zaznamenat p95, memory, files scanned, coverage, fallback a 503 status. Horkou cache a synthetic fixture oddělit od reálného endpointu.

**Akceptace:** Defaultní limit splní schválené SLA nebo vrátí chybu s jasným reason, retryability a informací o coverage; nad limitem se nespouští neomezené source scan.

**Evidence:** `docs/FINAL_COMPLETION_PLAN.md:2056-2066,2224`.

### A20 Typová kontrola je striktní, ale pokrývá malý výřez

**Priorita:** P2 · **Stav:** coverage rozsah potvrzen z konfigurace

`pyproject.toml` nastavuje `mypy` `strict = true`, ale seznam `files` obsahuje 14 modulů, zatímco package má 509 Python souborů. Ruff a pyflakes běží napříč `src tools tests`, což zachytí řadu chyb, nikoli však rozhraní typů, nullable hranice a změny návratových dat.

**Dopad:** Typová regresní chyba v migrační, HTTP, scheduler nebo persistence cestě nemusí být chycená, pokud tyto soubory nejsou do explicitního mypy scope.

**Doporučení:** Přidávat úseky po balících s nejvyšším rizikem: persistence contracts, config, migrations, command broker, HTTP route signatures, MCP operation contracts a SDK adapters. Každý krok má oddělený baseline a scope. U složitých dynamických modulů nejdříve definovat Protocol/TypedDict boundary.

**Akceptace:** CI reportuje růst kontrolovaných modulů a nezvyšuje počty ignore; kritické public contracts jsou strict. Výjimky mají datum, vlastníka a snižovací plán.

**Evidence:** `pyproject.toml:103-122`; `.github/workflows/ci.yml:58-70`.

### A21 Několik modulů spojuje příliš mnoho odpovědnosti

**Priorita:** P2 · **Stav:** maintainability risk, ne prokázaný runtime bug

Největší soubory podle současné inventory: `agent_memory.py` 2 903 řádků, `scheduler.py` 2 689, `operation_contracts.py` 2 571, `process_utils.py` 2 190, `client.py` 2 152, `async_jobs.py` 2 140, `laya_candidates.py` 2 081 a `agent_verification.py` 1 902. Projekt část modulů už dělí do mixinů a helperů, takže samotný počet řádků není dostatečná příčina dalšího dělení.

**Dopad:** Vysoká review plocha a provázané testy zvyšují cenu bezpečných změn. Jemné detaily transakcí, policy a transportu mohou být editované v širokých souborech s velkým diffem.

**Doporučení:** Neprovádět plošné „rozsekat podle velikosti“. Vytvořit import/call graph, najít stabilní veřejné typy a skutečně samostatné stores/services. Priorita: `agent_memory.py`, `scheduler.py`, `operation_contracts.py`. Zachovat transakční a security hranice v jednom vlastníkovi; nepřidávat re-export kompatibilitu jen pro staré test monkeypatch.

**Akceptace:** Menší samostatné odpovědnosti, žádné nové cykly/import proxy, všechny public contracts stejné, nižší import fan-in a cílené regression coverage. Výkon tvrdit pouze po benchmarku.

### A22 Jediný aktuální release checklist je překryt historickou chronologií

**Priorita:** P2 · **Stav:** autoritativní princip existuje; čitelnost je slabá

`docs/FINAL_COMPLETION_PLAN.md` má přes 2 200 řádků. Úvodní checklist nese datum 19. 11., zatímco nové důkazy sahají do 24. 11. Historické plány a CI obsahují stavy `PASS`, které samotný checklist upozorňuje nepoužívat jako aktuální akceptaci. Některé starší části si navíc protiřečí s pozdějšími slices; například počáteční popis state v8/v9 přepsaly následné migrace až do v10.

**Dopad:** Čtenář musí ručně rozlišovat aktuální stav, historickou investigaci, aktuální zdroj a nevztahující se fixture. Riziko chybného předání je vysoké při tak dlouhé chronologii.

**Doporučení:** Zachovat jediný kanonický plán. Jeho první část převést na aktuální brief s timestampem, commit, P1/P2, owner, next action, acceptance command/result a odkazem na evidenční blok. Každý detail označit `CURRENT`, `HISTORICAL`, `SUPERSEDED` nebo `UNVERIFIED`. Nevymazávat hodnotné historické důkazy bez archivace.

**Akceptace:** V úvodu jedna stránka odráží současné blockers; každý historický PASS uvádí revision/platformu a scope; žádný stav bez data a zdroje se nevydává za současný.

### A23 Aktivní plány a široké překryvy vyžadují čerstvé sjednocení

**Priorita:** P2 · **Stav:** live plan list nebyl dostupný

Předchozí audit při vstupním snapshotu zaznamenal 12 aktivních plánů a překryv: unified completion, endpoint routing, Laya, migration/autoupdates, endpoint reliability, FP4/model provisioning a další. Počet pochází z předchozího snapshotu a v tomto pokračování nebyl potvrzen. Git status nyní stále obsahuje změněné i nové JSON plány.

**Dopad:** Souběžné plány mohou vlastnit stejný zdroj, vést k duplicitní práci nebo k recyklaci neaktuálního výsledku. Přímá editace plan storage by navíc obešla revision/lease gate.

**Doporučení:** Až bude Hub MCP funkční, načíst `plan_list`, ověřit revision i `work_status`, zachovat jediný master release plan, připojit Superpowers spec/plan refs a přes podporované rozhraní aktualizovat nebo archivovat duplicity. Do té doby neprovádět ruční JSON úpravy.

**Akceptace:** Jeden autoritativní aktivní plán, každá práce má stabilní task ID, kritéria a owner; žádný task označen hotový bez skutečné evidence/receipt; přesné blockers a next action.

### A24 Release bezpečnostní kontrola závislostí existuje, ale musí být nad finálním artefaktem

**Priorita:** P2 · **Stav:** mechanismus přítomen; aktuální artefakt neověřen

Release workflow používá hashované build nástroje a volá `tools/release_inventory.py`, které vytváří runtime lock, dependency inventory, OSV query evidence a CycloneDX SBOM. `pyproject.toml` obsahuje verziované minimální/maximum rozsahy pro několik runtime a optional dependencies. Mechanismus je dobrý; tento audit nespustil release workflow nad znečištěným pracovním stromem.

**Dopad:** OSV výsledek a SBOM odpovídají pouze konkrétnímu resolveru, locku a build artefaktu. Změna markerů, extras, `MANIFEST.in` či package-data může opomenout závislost nebo soubor.

**Doporučení:** Uchovat lock, resolver report, SBOM a OSV výsledky přesně proti wheel/sdist každého release kandidáta. Ověřit optional extras, platform tags a licenční inventář. Zřetelně odlišit „OSV bez nalezeného záznamu“ od neúplného paginovaného dotazu.

**Akceptace:** Clean build; wheel a sdist smoke v novém prostředí; `pip check`; instalace všech podporovaných extras podle matice; žádná nevyřešená nebo neúplná OSV evidence; SBOM identifikuje přesný artifact digest.

**Evidence:** `.github/workflows/release.yml:39-79`; `tools/release_inventory.py`.

### A25 CI má silné brány, ale jejich současné výsledky nejsou tento audit

**Priorita:** P1 před vydáním · **Stav:** definice workflow zkontrolována; žádná CI sada spuštěna

CI zahrnuje release check, Python syntax, pyflakes, Ruff, TypeScript typecheck, mypy na Python 3.11/3.13, fast contract, platform smoke, integrační běhy a coverage baseline. Platformní matrix pokrývá Windows, macOS, Linux a Python 3.11–3.14. Celá sada běží podle workflow podmínek v určených platformních jobs; ne každý matrix job běží vždy jako full suite. Autoritativní release workflow používá `--strict-tree`.

**Dopad:** CI design nabízí adekvátní mechanismus, ale žádná definice sama nepotvrzuje současný dirty HEAD. Targeted historical PASS může patřit jinému souborovému snapshotu nebo předcházet poslední změně sdíleného modulu.

**Doporučení:** Po zafixování kandidáta vyžádat CI pro přesné SHA a uchovat JUnit/coverage/package artifacts. Pro důležité změny spouštět explicitní domain selection. Full `--run-all` pouze při plánovaném release či explicitní potřebě, protože repo blokuje neomezený pytest.

**Akceptace:** Všechny required jobs zelené pro jedno SHA; jeden přeskočený job má zdůvodnění; release smoke instaluje vytvořený wheel, nikoli pouze editable checkout; release check používá správný clean-tree režim.

**Evidence:** `.github/workflows/ci.yml`; `.github/workflows/release.yml`; `AGENTS.md` test execution policy.

### A26 Skutečnou migraci instalovaných dat a rollback nelze nahradit fixture

**Priorita:** P1 před release · **Stav:** ověření tohoto běhu nebylo provedeno

Cílené testy v auditní historii ověřují real SQLite fixtures, kopii staged state, row digests, fail-closed unknown layouts a obnovu části updater transaction. Tyto výsledky jsou užitečné, ale release checklist stále žádá skutečné izolované instalace a update/rollback. Současný Hub je vypnutý; není zde nový runtime proof.

**Doporučení:** Vytvořit disposable instalace ze supported release artifactu pro každou verzi-state signaturu. Migrovat kopie existujících dat, přerušit update v každém kroku, obnovit zálohu a spustit nový binary. Zahrnout config, Agent State, board archive, endpoint stats, telemetry, RAG, runtime overrides, plugin manifests a klientské soubory.

**Akceptace:** Všechny supported source versions mají přesný expected result a row counts. Unknown/corrupt layouts odmítnuty bez změny originálu. Rollback vrací provozuschopný předchozí release i původní data.

### A27 Benchmarky kvality jsou malé a oddělené od provozní akceptace

**Priorita:** P2 · **Stav:** důkazy jsou cílené, ne reprezentační

Plán obsahuje malé manuálně označené reranker případy a úzké anglické embedding smoke. Výsledky ukazují, že vybrané modely fungují na daných příkladech; neprokazují multilingual retrieval, výběr modelu v běžném runtime, live cache invalidation ani kvalitu napříč repository size. Laya training/eval data se musí kontrolovat podle provenance a splitu.

**Dopad:** Uživatel může vidět změnu relevance nebo české dotazy zhoršené optimalizací, přestože syntetické testy projdou. Model update může změnit embedding space a vyžadovat nákladné nové vektory.

**Doporučení:** Držet oddělený stabilní evaluation set s train/validation/test split, českými i anglickými dotazy, code identifiers, misspellingy, update/deletion scénáři a known-negative queries. U embedding změny hlídat prostor, dimenzi, normalize, cache key, batch order a reindex rollback.

**Akceptace:** Relevance metrics a confidence interval; porovnání starý/nový model se stejným corpus snapshotem; žádný train–eval leakage; rollback a reindex dokončení pro supported profile.

### A28 Osmi providerů a instalace klientů potřebují čistou host matrix

**Priorita:** P2 · **Stav:** implementace existuje; úplná clean-host akceptace otevřená

Repozitář obsahuje provider adaptéry a pluginy pro více agent hostů. Historické testy ověřují část bundle parity a action schemas, avšak současný plán požaduje clean install/update/uninstall, reálný handshake, správné host paths, restart klienta, permissions a cleanup owned files. OpenCode má odlišnou strategii instalace skills než sdílené bundle.

**Dopad:** Host může načíst starou MCP URL, ztratit instrukci, přesunout soubor vlastněný uživatelem nebo zobrazit zastaralé tool schema po upgradu.

**Doporučení:** Definovat tabulku host × OS × instalace × update × uninstall × MCP handshake × skill snapshot. Testovat původní uživatelské soubory, symlinky, nečekané user edits a opětovnou instalaci. Kontrolovat, že cleanup odstraní pouze soubory s platným ownership record.

**Akceptace:** Každý podporovaný host projde uvedeným lifecycle a handshake; nepodporovaný host odmítne install s konkrétním důvodem; user-owned content zachováno.

### A29 Uložené zálohy a exporty mají stejnou citlivost jako zdrojový stav

**Priorita:** P2 · **Stav:** ochranná logika existuje; kompletní privacy review otevřené

Security policy správně připomíná, že index a RAG obsahují odvozený lokální kód. Migrace pořizují verified backup; browser/artifact exports mohou nést payloady. Uložená evidence u ZIP64 exportu prokazuje syntetické AES/ZIP64 dešifrování, nikoli live download/restore, privacy review ani task-session binding.

**Dopad:** Zálohy a exporty mohou uchovat staré tenant labely, source fragmenty, model metadata či prompt artifacts i po odstranění z aktivního stavu.

**Doporučení:** Popsat lifecycle, šifrování, umístění, oprávnění, retenční limit a bezpečnou likvidaci pro state backups, artifacts, logs a exporty. Ověřit, že cleanup report vypíše file inventory bez leaknutí obsahu. Testovat obnovu a vazbu exportu na root/task/session.

**Akceptace:** Každý export má přesný scope a recipient; záloha je čitelná jen OS ownerem; verified restore úspěšný; expiry/deletion proof zahrnuje sidecary a temp copies.

**Evidence:** `SECURITY.md:17,28`; `docs/FINAL_COMPLETION_PLAN.md:2230`.

### A30 Stale planning evidence a source identity musí být v každém auditu čitelné

**Priorita:** P2 · **Stav:** procesní kvalita

Auditní archiv obsahuje porovnání různých commitů a pracovních stromů, starší plánové počty, deprecated action names, různé modelové profile a výsledky z odlišných OS. Sám upozorňuje, že některé snapshots jsou historické a že pozdější sekce je nahrazují. V tomto opakování se také změnil git status z 400 na 403, přestože HEAD zůstal stejný.

**Dopad:** Bez revisions/fingerprints u každého výsledku lze omylem spojit nový diff se starým PASS. Chybně se pak mění bezpečnostní decision nebo se znovu spouští drahá či nebezpečná práce.

**Doporučení:** Každý důkaz v master plánu obsahuje source commit, dirty/clean state, platformu, přesný command/action, scope, timestamp, result a artifact ID. Historické závěry neodvozovat do současného statusu bez diff-based revalidation.

**Akceptace:** Reviewer dokáže jednoznačně určit, které source snapshot daný výsledek kryje a co zůstalo neověřené.

## Co funguje a má zůstat zachováno

1. **Fail-closed migrační princip.** Runtime odmítá neznámé state layouty; updater používá přesné signatury, staged kopie, verified backup a rollback. Neodstraňovat odmítnutí ve prospěch obecného `ALTER TABLE` za běhu.
2. **Single-owner bezpečnostní boundary.** Loopback peer se ověřuje ze socketu, Host/Origin chrání browser surface, action contract váže capability, a administrativní mutace mají audit. Nezavádět tenant label jako autentizaci.
3. **Deterministické action contracts.** `operation_contracts.py` je veřejný zdroj schémat a feature/profile gates. Generator, HTTP, MCP a klienti mají zůstat odvozené či testované proti němu.
4. **Viditelná degradace a bounded output.** Truncation, candidate caps, source-read uncertainty a model failure mají zůstat explicitní. Nikdy neoznačovat omezený výsledek jako úplný.
5. **Release supply-chain artefakty.** Hashovaný build tooling, dependency inventory, OSV evidence a CycloneDX SBOM jsou silnou vlastností release procesu. Navázat je na finální wheel/sdist.
6. **Opt-in model provisioning.** Model download zůstává volitelný a pinovaný; zachovat kontrolu digestu a oddělení modelového/runtime configu.

## Doporučené pořadí uzavření

### Fáze 1 — Zafixovat rozsah

1. Po obnovení Hub MCP načíst aktuální master plán a aktivní leases. Nepoužívat přímou editaci `.local-ai-hub/plans` JSON.
2. Klasifikovat 403 lokálních změn podle vlastníka, plánu, souborové skupiny a release zahrnutí. Zachovat všechny změny.
3. Vybrat jeden kandidátní commit a připsat k němu nový status snapshot. Dřívější results považovat za historické, dokud se nepotvrdí shoda vstupu.

### Fáze 2 — Stabilita a migrace

1. Srovnat `INSTALLER_RECOVERY.md` s aktuální verzí state 10 a řetězcem 6→7→8→9→10.
2. Ověřit čistý install, update ze všech podporovaných signatur, selhání v každém kroku, rollback a restart.
3. Ověřit config schema v base a runtime override, včetně verified backup a atomického návratu.
4. Znovu určit GPU reservation status před jakýmkoli release/benchmark krokem.

### Fáze 3 — Search a provozní kvalita

1. Spustit kontrolovaný RAG reindex nad izolovaným state snapshotem.
2. Potvrdit vektory, marker, queue, integrity a search relevance.
3. Změřit `/api/search`, `/api/context/pack`, `/api/review/diff`, `/api/review` a `/api/solve/repo` ve cold/warm režimu.
4. Ověřit cancellation, retries, error statuses, restart recovery a field parity přes MCP/HTTP/SDK.

### Fáze 4 — Integrace a public contract

1. Uzavřít provider profile a clean client-host lifecycle matrix.
2. Přegenerovat API/action/evaluation matrix; označit historical-only fixtures.
3. Opravit rozpočet `original_tokens` a synchronizovat `SECURITY.md`.
4. Zkrátit current plan, ponechat chronologii a jasně oddělit current/superseded evidence.

### Fáze 5 — Release gates

Následující příkazy jsou doporučené pro pozdější akceptaci, nikoli provedené tímto auditem:

```powershell
python tools/release_check.py --strict-tree
python -m compileall -q src tools tests
python -m pytest -m critical --no-cache
python tools/selftest.py
```

Pro release ověřit současně CI výsledky, wheel/sdist smoke, `pip check`, dependency inventory, OSV evidence, SBOM a clean-install klientskou matici na témže commit SHA. Celý pytest suite nespouštět bez plánovaného explicitního výběru; repozitář jej záměrně chrání před neomezeným spuštěním.

## Celkový verdikt

Projekt má široké automatické testy, přísné route/config contracts, bezpečnostní loopback boundary a rozpracované recoverable migrace. Auditní historie obsahuje mnoho cílených úspěchů. Hlavní problém je, že dnes nelze tyto oddělené výsledky spojit do jednoho současného release důkazu: pracovní strom má 403 lokálních změn, runtime je vypnutý, RAG data po resetu nejsou re-embedována a živá akceptace zůstává otevřená.

Projekt proto zatím neoznačuji za perfektní ani připravený k vydání. Nejprve uzavřít P1 položky a vydat čistý kandidát. P2/P3 práci pak provádět podle změřeného rizika a výkonu, ne podle samotné velikosti kódu.

## Hlavní zdroje

- `docs/FINAL_COMPLETION_PLAN.md` — autoritativní completion checklist a chronologická evidence; aktuální nejnovější položky 24. 11. 2026.
- `docs/audits/2026-11-24-local-ai-hub-canonical-cleanup.md` — detailní inventář current-source cleanup, provider bundles, migrací, route dispatch a otevřených auditních rozsahů.
- `src/local_ai_hub/state_lifecycle.py`, `tools/state_migrations.py`, `tools/update_install.py`, `tools/config_migrations.py` — state/config migration source.
- `src/local_ai_hub/operation_contracts.py`, `src/local_ai_hub/http_route_registry.py`, `src/local_ai_hub/http_api_auth.py`, `src/local_ai_hub/mcp_wire.py` — public API, dispatch, auth a response boundary.
- `pyproject.toml`, `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `tools/release_inventory.py` — package, type/lint/test a supply-chain gates.
- `SECURITY.md`, `docs/INSTALLER_RECOVERY.md`, `docs/MODEL_DISTRIBUTION.md` — operator contracts.
