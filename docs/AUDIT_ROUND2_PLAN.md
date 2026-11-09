# Local AI Hub — Realizační plán a regresní matice (Audit Round 2)

**Vychází z:** `docs/AUDIT_ROUND2.md`  
**Datum:** 8. listopadu 2026  
**Cíl:** Odstranění zjištěných chyb a architektonických rizik v logických etapách s přísnou verifikací.

---

## 1. Implementační etapy podle závislostí

### Etapa A — Zabránit nekonzistentním datům a kolizím cache (Nejvyšší priorita)
*Cíl: Zajistit, aby sémantické vyhledávání, preprocessing cache a RAG nemohly míchat data mezi projekty ani vracet neplatné výsledky po změně konfigurace.*

1. **N11 — Root-aware Preprocessing Ingest Cache:**
   - Změnit klíč v `SinglePassIngestCache` na `(canonical_root, rel_path, content_hash)`.
   - Upravit rozhraní `has()`, `get()`, `put()`, `invalidate()`, `get_or_ingest()`.
   - Doplnit N24 (aktualizace `invalidate()` na úplnou identitu) a N21 (odmítnutí oversized souborů).
2. **N18 — Striktní `repository_revision` v Semantic Scope:**
   - V `services.py` vždy začlenit `repository_revision` do scope identity bez ohledu na přítomnost doplňkových digestů.
   - Při neznámé revizi u úloh vázaných na kód zakázat sémantický reuse.
3. **N09 — Verzovaná identita modelu v Agent Memory:**
   - Přidat sloupce `embedding_space_id`, `model_name`, `dimension` do `agent_memory_embeddings`.
   - Zavést validaci kompatibility před kosinovým porovnáním; při neshodě fallback na lexikální vyhledávání.
4. **N19 — Verzování Semantic Generation Cache:**
   - Přidat embedding prostor do namespace sémantické cache, zamezit míchání vektorů různých modelů.

---

### Etapa B — Deterministické chování při chybách a konzistence grafu
*Cíl: Zamezit pádům a nekonečné spotřebě zdrojů při nevalidních vstupech od modelů a zajistit matematickou uzavřenost grafových operací.*

1. **N01 — Ochrana parsování skóre v `TokenRouter`:**
   - Ošetřit konverzi na float, vyžadovat konečné číslo $0.0 \le s \le 1.0$.
   - Při selhání okamžitý pád na deterministický výběr úseků bez výjimky.
2. **N12 — Normalizace a zastropování intervalů od LLM:**
   - Vložit mezi `_parse_ranges()` a `_render()` validační a normalizační vrstvu.
   - Vynutit `rendered_lines <= max_output_lines`, sloučit překryvy a odstranit duplicity.
3. **N02 & N03 — Oprava SQL dotazů v `AgentMemory.traverse_graph`:**
   - N02: Vracet pouze hrany, jejichž zdroj i cíl leží v `bounded_nodes` (uzavřený podgraf).
   - N03: Pevně omezit hloubku rekurze a zavést výpočetní limit zpracovaných řádků s `truncated=true`.
4. **N14 — Vyčištění čekacích hran v `ScopeLeaseStore`:**
   - Vázat wait-for hrany na konkrétní `lease_id`.
   - Ignorovat neaktivní zámky při detekci deadlocku, eliminovat falešné detekce cyklů.
5. **N20 — Zpřesnění klasifikace chyb GPU v `Scheduler`:**
   - Rozlišovat čistě dokončené úlohy s aplikační chybou od skutečného systémového selhání GPU.
   - Nastavovat `_internal_gpu_uncertain` pouze při ztrátě kontroly nad procesem.

---

### Etapa C — Omezení režie souběžnosti a sjednocení scheduleru
*Cíl: Zabránit nekontrolovanému růstu vláken a zkrátit dobu držení zámků nad SQLite.*

1. **N05 — Omezený worker pool pro asynchronní úlohy:**
   - Nahradit ad-hoc vytváření vláken pevně dimenzovaným pool workerů.
   - Oddělit kapacitu pro inferenční úlohy a lehké systémové úlohy.
2. **N06 — Zkrácení SQLite transakcí při finalizaci úloh:**
   - Přesunout `artifacts.put()` a diskové I/O mimo blok `BEGIN IMMEDIATE`.
   - V transakci provádět pouze atomický update stavu úlohy.
3. **N07 — Sjednocení VRAM admission logiky:**
   - Sjednotit `enqueue()` a `submit()` na jedno interní volání s předáním modelu a profilu.

---

### Etapa D — Lepší využití kontextu a optimalizace paměti
*Cíl: Zvýšit relevanci vrácených vzpomínek a omezit zbytečnou režii I/O a tool callů.*

1. **N10 — Relevance-first vektorový výběr v Agent Memory:**
   - Nahradit prostý `ORDER BY created_at DESC LIMIT 500` relevančním výběrem (batch scan nebo hybridní ranking).
2. **N16 — Eliminace zbytečných zápisů do ArtifactStore:**
   - V `ContextLedger.compile()` ověřit digest a existenci artefaktu před voláním `artifact_store.put()`.
3. **N17 — Dynamické přidělování rozpočtu pro text v Context Delivery:**
   - Nahradit fixní dělení `budget // 6` dynamickým výpočtem volného místa po odečtení metadat.
4. **N22 — Escapování wildcardů v `MemoryStore.find()`:**
   - Ošetřit znaky `%` a `_` v uživatelských dotazech.

---

### Etapa E — Konzistence workflow a zbývající nálezy
*Cíl: Dokončení izolace projektů a začištění drobných implementačních nedostatků.*

1. **N13 — Namespace repozitáře pro entity grafu a oprava filtrů:**
   - Doplnit `repository_id` do tabulky vztahů.
   - Opravit vyhodnocení dotazů s oběma filtry (`source_entity` i `target_entity`).
2. **N15 — Atomická publikace dvojice Spec & Plan:**
   - Zavést společný manifest revize nebo atomickou kontrolu při čtení obou souborů.
3. **N04, N08, N21, N23:**
   - N04: Dynamický přepočet kapacit shardů pro malé LRU cache.
   - N08: Výpočet kompenzovaného skóre přepnutí modelu ve scheduleru.
   - N21: Odmítnutí ukládání nadrozměrných položek do ingest cache.
   - N23: Jazykové adaptéry pro generování cest k testům v routing engine.

---

## 2. Regresní a zátěžová matice (T01–T16)

Každý test musí být spuštěn v izolovaném prostředí a zaznamenávat: commit SHA, čas spuštění, hardware profil a výsledek.

| Test | Název | Testovaný scénář | Akceptační kritérium |
|------|-------|------------------|----------------------|
| **T01** | Cross-root Ingest | Dva projekty se stejnými relativními cestami (`src/main.py`), ale odlišným obsahem. | Žádný obsah z projektu A se neobjeví v RAG/indexu projektu B. |
| **T02** | Ingest Contention | Souběžné indexování 3 různých projektů více workery. | Žádná kolize klíčů, konzistentní cache a správná selektivní invalidace. |
| **T03** | Model JSON Fuzz | 1 000 náhodně vygenerovaných, poškozených a extrémních modelových odpovědí do `TokenRouter`. | Nulový výskyt neošetřených výjimek, stoprocentní fallback na deterministický výsledek. |
| **T04** | Router Output Bound | LLM vrátí interval pokrývající celý stotisícový soubor s vysokým skóre. | `rendered_lines <= max_output_lines`, žádný OOM. |
| **T05** | Async Burst | Přijetí 256 asynchronních úloh v jedné sekundě. | Počet aktivních OS vláken nepřekročí nastavený limit worker poolu; fronta zůstane stabilní v SQLite. |
| **T06** | Async Finalization Contention | Simulace pomalého disku při ukládání artefaktu za současného čtení z jiných vláken. | Čas držení SQLite write zámku pod 10 ms, žádná chyba `database is locked`. |
| **T07** | Scheduler Admission Parity | Předání stejného požadavku na model přes synchronní `submit` a asynchronní `enqueue`. | Obě cesty dojdou k identickému rozhodnutí o přijetí či zamítnutí na základě VRAM. |
| **T08** | Mixed Model Priorities | Ve frontě čeká rezidentní model s prioritou 1 a nenačtený model s prioritou 9. | Scheduler přepne model v definovaném časovém limitu; vysoká priorita není trvale vyhladověna. |
| **T09** | Memory Model Switch | Změna embeddingového modelu na jiný se stejnou dimenzí (např. 768). | Žádné neplatné sémantické hity mezi novým dotazem a starými vektory. |
| **T10** | Historical Memory Recall | V paměti je 2 000 záznamů, klíčová informace je uložena jako 1. záznam, dalších 1 999 je šum. | Recall@10 úspěšně vrátí nejstarší relevantní záznam. |
| **T11** | Graph Traversal Safety | Cyklický graf o 100 uzlech s vysokou konektivitou, dotaz s `max_nodes=5`. | Vrácený graf obsahuje přesně $\le 5$ uzlů, všechny hrany mají oba konce v těchto uzlech, čas dotazu $< 50$ ms. |
| **T12** | Lease Deadlock Parity | Agent A uvolní nadřazený zámek `src/`, zatímco Agent B čeká na `src/child.py`. | Odstranění čekací hrany, následný zámek nezpůsobí falešný deadlock. |
| **T13** | Concurrent Plan Read | Čtení plánu a specifikace přesně v okamžiku zápisu nové verze. | Čtenář nikdy neuvidí kombinaci nové specifikace a starého plánu. |
| **T14** | Context Artifact Reuse | 100 opakovaných volání kompilace identického kontextu. | Přesně 1 fyzický zápis do artefaktového úložiště, 99 cache hitů bez diskového I/O. |
| **T15** | Semantic Scope Revision | Dva identické dotazy na kód pro dvě různé git revize repozitáře. | Dva oddělené záznamy v sémantické cache, žádný falešný zásah ze staré revize. |
| **T16** | Controlled Model Failure | Model vrátí korektní JSON s chybovou zprávou nebo odmítnutím. | GPU scheduler zůstane ve stavu `healthy`, nedojde k přepnutí na `internal_gpu_uncertain`. |

---

## 3. Očekávaný dopad a výkonnostní přínosy

| Oblast | Očekávaný dopad na správnost | Očekávaný dopad na výkon / zdroje | Kde se nejvíce projeví |
|--------|------------------------------|-----------------------------------|------------------------|
| **N11, N24 (Ingest Cache)** | **Kritický** (odstranění kontaminace mezi projekty) | Neutrální | Multi-repo provoz, agentní worktrees |
| **N01, N12 (Token Router)** | **Kritický** (odstranění pádů a přetečení kontextu) | Snížení spotřeby RAM a kontextových tokenů | Bounded context extraction při použití LLM |
| **N05, N06 (Async Jobs)** | Vysoký (stabilita při zátěži) | **Výrazné snížení lock contention a CPU switchingu** | Dlouhotrvající asynchronní úlohy pod souběhem |
| **N02, N03, N13 (Graph Memory)**| Vysoký (konzistentní podgrafy, projektová izolace) | Prevence CPU spikeů a paměťových úniků u velkých grafů | Prohledávání vazeb mezi symboly a koncepty |
| **N10 (Vector Retrieval)** | **Zásadní pro kvalitu** (starší vzpomínky nezmizí) | Mírné zvýšení CPU při batch scanu (lze optimalizovat indexem) | Dlouhodobě běžící agenti a velké paměťové báze |
| **N16, N17 (Context Delivery)**| Střední (méně zbytečných redirectů) | **Méně tool callů a diskového I/O** | Běžná práce agenta s kontextem |
| **N20 (GPU Error Handling)** | Vysoký (dostupnost GPU při běžných chybách) | Eliminace zbytečných restartů a blokování GPU | Spouštění lokálních modelů na nestabilních promptech |
