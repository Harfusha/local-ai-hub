# Local AI Hub — Druhé kolo hloubkového auditu

**Datum:** 8. listopadu 2026  
**Cílový commit:** `2176b0e`  
**Oblast:** Implementační chyby, chybové scénáře, datová konzistence, souběžnost a vnitřní výkon subsystémů.

---

## 1. Souhrnný přehled nálezů (N01–N24)

| ID | Subsystém / Soubor | Zjištění | Úroveň jistoty | Priorita |
|----|--------------------|----------|----------------|----------|
| **N01** | `token_router.py` | Nevalidní skóre od LLM může vyhodit výjimku místo fallbacku | Chyba v kódu | **P1** |
| **N02** | `agent_memory.py` | Aktuální edge dotaz vyžaduje oba konce hrany mezi vrácenými uzly; regresní test přidán v Round 81. | Zdroj/test ověřeny; nález již opraven v HEAD | **P1** |
| **N03** | `agent_memory.py` | Aktuální průchod používá bounded BFS, ne rekurzivní CTE; `max_nodes` omezuje rozšířené uzly a SELECT rozpočet kontroluje test. | Zdroj/test ověřeny; původní popis je zastaralý | **P1** |
| **N04** | `cache.py` | Malá sharded LRU může překročit deklarovanou kapacitu | Chyba v kódu | **P2** |
| **N05** | `async_jobs.py` | Samostatné vlákno pro každou přijatou úlohu bez centrálního poolu | Architektonické riziko | **P1** |
| **N06** | `async_jobs.py` | Finalizace drží SQLite write transaction přes diskové a cizí operace | Architektonické riziko | **P1** |
| **N07** | `scheduler.py` | `submit` a `enqueue` používají odlišné podklady pro VRAM admission | Chyba v kódu | **P1** |
| **N08** | `scheduler.py` | Rezidentní model může dostat přednost před podstatně prioritnějším požadavkem | Optimalizační hypotéza | **P2** |
| **N09** | `agent_memory.py` | Vektorová paměť nemá identitu embeddingového modelu ani prostoru | Architektonické riziko | **P1** |
| **N10** | `agent_memory.py` | Retrieval omezuje výběr vektorů podle stáří (`created_at DESC`), ne relevance | Architektonické riziko | **P1** |
| **N11** | `preprocess_ingest.py` | Kritická kolize preprocessing cache mezi projekty (společný klíč bez kořene) | Chyba v kódu | **P1** |
| **N12** | `token_router.py` | Lokální model může vrátit intervaly obcházející maximální rozpočet řádků | Chyba v kódu | **P1** |
| **N13** | `agent_memory.py` | Graf entit nemá repository namespace a ignoruje kombinaci filtrů | Chyba v kódu | **P1** |
| **N14** | `leases.py` | V persistentních lease závislostech mohou zůstat neplatné čekací hrany | Chyba v kódu | **P1** |
| **N15** | `repo_plan/storage.py` | Uložení více souborů plánu není atomické pro souběžné čtenáře | Architektonické riziko | **P2** |
| **N16** | `context_ledger.py` | Před reuse ověřuje digest, čerstvost i dostupnost artefaktu; chybějící artefakt se obnoví, identický živý zápis se neopakuje (Round 82). | Opraveno a ověřeno | **P2** |
| **N17** | `context_delivery.py` | Dynamicky přiděluje zbytek po metadatech; truncation metadata se započítají před výpočtem textu a výsledek nepřekročí rozpočet (Round 83). | Opraveno a ověřeno; sousední service test failures odděleny | **P2** |
| **N18** | `services.py` | `repository_revision` není vždy součástí semantic scope identity | Chyba v kódu | **P1** |
| **N19** | `semantic_cache.py` | Sémantická cache není verzovaná podle embeddingového prostoru | Architektonické riziko | **P1** |
| **N20** | `scheduler.py` | Běžná chyba modelového volání může označit celý GPU runtime za nejistý | Architektonické riziko | **P1** |
| **N21** | `preprocess_ingest.py` | `_evict_if_needed()` dovoluje ponechat jediný soubor větší než `max_bytes` | Chyba v kódu | **P3** |
| **N22** | `agent_memory.py` | Původně hlášeno jako neescapované LIKE; aktuální zdroj escapuje `\\`, `%` a `_` (ř. 1815). Regresní testy doplněny v Round 79. | Zdroj/test ověřeny; nález již opraven v HEAD | **P3** |
| **N23** | `agent_routing.py` | Python fallback se použije jen pro `.py`; nepodporované přípony se přeskočí. Testy ověřují `.cs`, `.java` a `.cpp` bez falešné Python cesty (Round 80). | Opraveno a ověřeno | **P3** |
| **N24** | `preprocess_ingest.py` | `SinglePassIngestCache.invalidate()` maže položky pouze podle relativní cesty | Chyba v kódu | **P3** |

---

## 2. Detailní rozbor nálezů

### N01 — Nevalidní modelový výstup rozbije bezeztrátový token router
- **Soubor:** `src/local_ai_hub/token_router.py` (`_parse_ranges`)
- **Mechanismus:** Zpracování skóre úseků vrácených lokálním modelem obsahuje přímou konverzi:
  ```python
  out.append((start, end, float(item.get("score", 1.0))))
  ```
  Pokud model vrátí JSON např. `{"ranges": [{"start": 12, "end": 25, "score": "high"}]}`, vyvolá se nezachycená `ValueError`.
- **Dopad:** Místo zamýšleného deterministického fallbacku selže celá operace zkracování kontextu. Agent nedostane ani původní deterministicky vybrané úseky.
- **Oprava:** Validovat všechna tři pole (`start`, `end`, `score`) bez nekontrolovaných konverzí. Skóre musí být konečné číslo (`math.isfinite`) v intervalu $[0.0, 1.0]$. Při chybě položku přeskočit nebo přepnout na deterministický výsledek. Doplnit parametrizované testy pro `score=null`, `"high"`, `NaN`, `Infinity`, záporné hodnoty.

---

### N02 — Graph traversal vrací hrany mimo množinu vrácených uzlů
- **Soubor:** `src/local_ai_hub/agent_memory.py` (`traverse_graph`)
- **Mechanismus:** Rekurzivní SQL dotaz vybírá vztahy podmínkou:
  ```sql
  r.source_entity = b1.entity OR r.target_entity = b1.entity
  ```
  Ani jeden výraz nevyžaduje, aby *oba* uzly patřily do množiny `bounded_nodes`.
- **Dopad:** Při `start_entity="A"` a `max_nodes=1` vrátí uzel A, ale také hrany A–B a A–E. Výsledný graf není uzavřený; volající obdrží reference na entity, které ve výsledku vůbec nebyly načteny.
- **Oprava:** Buď filtrovat hrany podmínkou `r.source_entity IN (SELECT entity FROM bounded_nodes) AND r.target_entity IN (SELECT entity FROM bounded_nodes)`, nebo výslovně rozlišovat `internal_edges` a `boundary_edges`.

---

### N03 — `max_nodes` neomezuje výpočetní práci rekurzivního CTE
- **Soubor:** `src/local_ai_hub/agent_memory.py` (`traverse_graph`)
- **Mechanismus:** Rekurzivní CTE prochází graf do hloubky `max_depth` a teprve následně aplikuje `LIMIT ?` při konstrukci `bounded_nodes`.
- **Dopad:** `max_nodes=50` omezí počet řádků ve finálním výběru, ale nikoli počet mezivýsledků vytvořených SQLite při procházení cyklů a hustých větví. U grafu s mnoha propojeními dochází k nekontrolované alokaci paměti a CPU času.
- **Oprava:** Pevně omezit maximální povolenou hloubku, zavést výpočetní limit zpracovaných řádků (budget), vracet explicitní příznak `truncated=true` při vyčerpání rozpočtu, případně přejít na iterativní Python BFS s globální `visited` množinou.

---

### N04 — Sharded LRU nedodržuje deklarovanou kapacitu u malých cache
- **Soubor:** `src/local_ai_hub/cache.py` (`MemoryLRUCache`)
- **Mechanismus:** Kapacita jednotlivých shardů se počítá jako:
  ```python
  self._shard_max = max(1, self.max_entries // self.num_shards)
  ```
  Při konfiguraci `max_entries=1` a `num_shards=16` je kapacita každého shardu 1, takže celá cache pojme až 16 položek.
- **Dopad:** Cache může překročit deklarovaný limit až šestnáctinásobně. U větších cache navíc statické dělení způsobuje nerovnoměrné vytížení shardů (jedna shard rotuje, ostatní jsou prázdné).
- **Oprava:** Dynamicky omezit počet shardů pro malé kapacity (`min(num_shards, max_entries)`), případně centrálně sledovat souhrnnou velikost.

---

### N05 — Samostatné vlákno pro každou přijatou asynchronní úlohu
- **Soubor:** `src/local_ai_hub/async_jobs.py` (`dispatch`, `_dispatch`)
- **Mechanismus:** `AsyncJobManager` při zařazení úlohy spustí pomocné vlákno `async-dispatch-*` a následný `_dispatch()` vytvoří pracovní vlákno `async-job-*`. Limit `max_pending=256` omezuje počet čekajících úloh v DB, ale v kódu chybí fixní thread pool workerů.
- **Dopad:** Při nárazové zátěži může vzniknout stovky aktivních OS vláken blokujících na modelových zámcích či I/O, což vede k exhaustionu systémových prostředků, vysoké režii context-switchingu a lock contention na SQLite.
- **Oprava:** Zavést pevně dimenzovaný worker pool (např. `ThreadPoolExecutor` s omezenou kapacitou) odděleně pro modelové operace a rychlé deterministické úlohy. Úlohy nad limit ponechat v durable SQLite frontě.

---

### N06 — SQLite write transaction drží během externích diskových operací
- **Soubor:** `src/local_ai_hub/async_jobs.py` (`_execute`)
- **Mechanismus:** V kódu se otevírá transakce:
  ```python
  con.execute("BEGIN IMMEDIATE")
  ```
  V jejím rámci se následně volá `artifacts.put()`, kontrola diskových souborů artefaktu a zápisy do task/verification subsystémů.
- **Dopad:** Diskový zápis velkého artefaktu drží exkluzivní zámek na databázi asynchronních úloh. Ostatní vlákna čekající na zápis stavu nebo čtení výsledků jsou blokována, což způsobuje vysoké tail latence a riziko `sqlite3.OperationalError: database is locked`.
- **Oprava:** Rozdělit operaci na 3 fáze: (1) příprava a uložení artefaktu mimo DB transakci s unikátním klíčem, (2) krátká atomická transakce zapisující metadata a ID artefaktu do DB, (3) notifikace posluchačů.

---

### N07 — Rozdílná kontrola modelu při přijetí úlohy do scheduleru
- **Soubor:** `src/local_ai_hub/scheduler.py` (`submit` vs. `enqueue`)
- **Mechanismus:**
  ```python
  # Synchronní submit:
  self._admission(background=background, model=model)
  # Asynchronní enqueue:
  self._admission(background=background)
  ```
  V metodě `enqueue()` se nepředává cílový model.
- **Dopad:** `_admission()` používá `model` k výpočtu specifických paměťových nároků VRAM. Při volání přes `enqueue` se použije pouze obecný odhad, což vytváří nekonzistenci: identická úloha může být jednou cestou odmítnuta a druhou přijata.
- **Oprava:** Sjednotit obě vstupní brány na jednotné interní volání `_admission()`, které vždy vyžaduje `model`, prioritu a paměťový profil.

---

### N08 — Rezidentní model má nepřiměřenou prioritu před důležitějším požadavkem
- **Soubor:** `src/local_ai_hub/scheduler.py` (`_choose_initial_model`)
- **Mechanismus:** Metoda seřadí čekající úlohy podle priority, ale následně projde seznam a vybere *první model, který je již načten v paměti GPU*.
- **Dopad:** Úloha s prioritou 1 (např. nepodstatné generování tagů) může předběhnout urgentní analytickou úlohu s prioritou 9 jen proto, že její model je náhodou v paměti.
- **Oprava:** Zavést dynamické rozhodovací skóre $S = P + W - C_{\text{switch}}$, kde $P$ je priorita úlohy, $W$ bonus za dobu čekání ve frontě a $C_{\text{switch}}$ odhad časové penalizace za přepnutí modelu.

---

### N09 — Uložené embeddingy nemají verzovanou identitu modelu
- **Soubor:** `src/local_ai_hub/agent_memory.py`
- **Mechanismus:** Tabulka `agent_memory_embeddings` ukládá pouze `record_id`, `embedding` a `created_at`. Chybí sloupce pro identifikaci embedding modelu, jeho verze a dimenze.
- **Dopad:** Pokud dojde ke změně konfigurace modelu (např. z `nomic-embed-text` na `bge-m3`), dotaz novým modelem bude porovnáván s nekompatibilními vektory. Pokud mají modely náhodou stejnou dimenzi (např. 768), dojde k tichému znehodnocení sémantického vyhledávání.
- **Oprava:** Doplnit metadata `embedding_space_id`, `model_name`, `dimension`. Před kosinovým porovnáním ověřit shodu prostoru. Při neshodě vynutit reindexaci nebo přepnout na čistě lexikální vyhledávání.

---

### N10 — Retrieval omezuje výběr vektorů podle stáří, nikoli relevance
- **Soubor:** `src/local_ai_hub/agent_memory.py` (`MemoryStore.find`)
- **Mechanismus:** Kandidáti pro vektorové porovnání se načítají dotazem:
  ```sql
  SELECT record_id, embedding FROM agent_memory_embeddings
  WHERE ... ORDER BY created_at DESC LIMIT 500
  ```
- **Dopad:** Pokud má agent 2 000 záznamů a klíčové architektonické rozhodnutí bylo uloženo na začátku projektu, nedostane se do výběru 500 nejnovějších řádků a nebude vůbec vektorově vyhodnoceno.
- **Oprava:** Pro malé paměti načítat všechny vektory v bounded streamu. Pro větší paměti použít hybridní předvýběr (lexikální match + embeddings) nebo lehký vektorový index (např. SQLite-vec / k-d tree / HNSW).

---

### N11 — Kritická kolize preprocessing cache mezi projekty
- **Soubory:** `src/local_ai_hub/preprocess_ingest.py`, `src/local_ai_hub/preprocess.py`, `src/local_ai_hub/rag.py`
- **Původní mechanismus (před opravou cache):** `SinglePassIngestCache` klíčovala data pouze relativní cestou:
  ```python
  normalized = rel_path.replace("\\", "/")
  ```
  `ProjectPreprocessor` drží jednu sdílenou instanci cache pro více kořenů. Před root-scoped opravou mohl projekt B se stejnou relativní cestou dostat text uložený projektem A. Původní audit také zjistil, že preprocessing předával text přes `content_override` do `rag.py` bez dalšího čtení souboru.
- **Původní dopad:** Obsah projektu A mohl proniknout do sémantického indexu projektu B.
- **Oprava:** Změnit klíč cache na trojici `(canonical_repository_root, relative_path, source_content_hash)`. Aktualizovat metody `has`, `get`, `put`, `invalidate`, `get_or_ingest`. Odstranit všechny cesty obcházející identitu repozitáře.
- **Následné ověření 2026-11-12 — částečné:** `SinglePassIngestCache._key()` používá kanonický kořen + relativní cestu; zdrojový hash v klíči chybí. `ProjectPreprocessor._step_lexical()` čte `ingested.content_hash` a porovnává jej s aktuálním `file_refs.content_hash`; při nesouladu přeskočí publikování a nastaví `needs_hash=1` (`preprocess.py` SHA `a07838931b8eb3e5931d53a3b78e8c0941e7a8dd3eaf86f572e6a68e78cd3dbc`). `_step_rag()` načte `content_overrides` jen z `source_index` stejného kořene, pokud hash odpovídá čekajícímu hashi, a předá je do `RAGStore.index_paths_step` (zdrojový důkaz `req_b2e3da93e86c`). Dřívější cílené testy hlásí **1 + 1 passed** pro oddělení projektů a invalidaci omezenou na kořen; aktuální SHA zdrojů/testů zůstávají `preprocess_ingest.py` `7a9a8c9849bb9339bbc26900749a946a179919b229977a2db163e157bfee7ec1` a `tests/test_audit_round2_preprocess_ingest.py` `c0613bdc481b055aeb328ad45d7a7addd203524a5f0b9484ba7382a9b2b48684`. Tyto testy nedokazují hash v klíči ani průchod bez kontaminace mezi projekty až do RAG. `rag.py` je stále dirty a patří Stability; neupravoval jsem jej. N11 zůstává částečný.

---

- **N11 doplňující source follow-up — 2026-11-12:** `get_or_ingest()` vrací cache hit podle kořene + relativní cesty před čtením aktuálního snapshotu. `_step_hash()` obnoví souborový digest, ale na hash mismatch neinvaliduje `ingest_cache`; invalidace je v aktuálním zdroji navázaná na file-watcher. `_step_lexical()` správně odmítne publikovat text s jiným hashem a nastaví `needs_hash=1`, takže stale text do `source_index` nepublikuje. Pokud hash fáze zachytí změnu bez watcher eventu, další lexical krok může znovu dostat starý cache item a znovu vrátit soubor do hash fáze. Zdroj tedy ukazuje riziko neuzavřeného hash/lexical cyklu a zablokované aktualizace, ne potvrzený stale-content zápis. Důkazy: `preprocess_ingest.py` SHA `7a9a8c9849bb9339bbc26900749a946a179919b229977a2db163e157bfee7ec1`; `preprocess.py` SHA `a07838931b8eb3e5931d53a3b78e8c0941e7a8dd3eaf86f572e6a68e78cd3dbc`; structural search `req_6dd5d8c7b829`, `req_720e429a2bd9`, `req_0220dd35c494`. Neprovedl jsem změny zdrojů ani testů. Předáno Stability threadu `01a1c762-d599-75c2-ae34-344aae056aa0`; čeká na bounded regresi a vlastníkovo rozhodnutí, oprava zůstává mimo tento audit.

### N12 — Lokální model může obejít maximální délku výstupu token routeru
- **Soubor:** `src/local_ai_hub/token_router.py`
- **Mechanismus:** Deterministický výběr řádků striktně vynucuje `max_output_lines` (výchozí 140). Pokud však úseky vybírá LLM, výstup z `_parse_ranges()` se předává do `_render()` bez celkového limitu řádků. Omezení `max_ranges=8` omezuje pouze počet intervalů.
- **Dopad:** Model může vrátit `{"start": 1, "end": 100000, "score": 1.0}`, což způsobí vložení celého obrovského souboru do kontextu, vyčerpání paměti a popření účelu token routeru.
- **Oprava:** Vložit mezi parsování a renderování striktní normalizaci intervalů: ořezání délek, limit celkového součtu řádků na `max_output_lines`, sloučení překrývajících se rozsahů.

---

### N13 — Graf paměti není oddělený podle repozitáře a ignoruje cílový filtr
- **Soubor:** `src/local_ai_hub/agent_memory.py` (`agent_entity_relations`, `find_relations`)
- **Mechanismus:**
  1. Tabulka vztahů neobsahuje `repository_id` ani `coordination_id`. Symboly jako `Service` či `Config` z různých projektů se slijí do jednoho grafu.
  2. Implementace `find_relations()` začíná:
     ```python
     if source_entity:
         ent = source_entity.strip(); direction = "out"
     elif target_entity:
         ent = target_entity.strip(); direction = "in"
     ```
     Při zadání obou parametrů se `target_entity` zcela ignoruje.
- **Dopad:** Cross-project kontaminace vztahů v grafu. Nemožnost filtrovat specifickou hranu $A \to B$.
- **Oprava:** Přidat `repository_id` do tabulky vztahů. Sestavovat klauzuli `WHERE` nezávisle pro `source_entity` i `target_entity`.

---

### N14 — V persistentních lease závislostech mohou zůstat neplatné čekací hrany
- **Soubor:** `src/local_ai_hub/leases.py` (`ScopeLeaseStore`)
- **Mechanismus:** Při uvolnění lease se čekací hrany v grafu závislostí mažou podle kombinace `(blocked_by, requested_path)`. Pokud agent A držel `src/` a agent B čekal na `src/service.py`, uvolnění `src/` neodstraní hranu, protože se neshoduje `requested_path`.
- **Dopad:** Vznikají osiřelé čekací hrany. Pokud agent B později získá jiný zámek a agent A na něj začne čekat, vznikne falešná detekce deadlocku ($A \to B \to A$) a operace bude neoprávněně zamítnuta.
- **Oprava:** Vázat čekací vztahy na konkrétní `lease_id`. Před spuštěním detekce cyklů ověřit, zda blokující lease stále reálně existuje a je aktivní.

---

### N15 — Uložení více souborů plánu není atomické pro souběžné čtenáře
- **Soubor:** `src/local_ai_hub/repo_plan/storage.py` (`save_spec_and_plan`)
- **Mechanismus:** Zápis specifikace a plánu probíhá v cyklu soubor po souboru:
  ```python
  for target, (_, data, _) in zip(targets, candidates):
      self._atomic_write_bytes(self.repo_root / target.rel_path, data)
  ```
  Každý soubor je atomicky přepsán, ale operace jako celek není atomická pro čtenáře, protože `read_plan_file()` nepoužívá zámek úložiště.
- **Dopad:** Souběžný čtenář může načíst novou specifikaci, ale starý plán, což vede k nekonzistentnímu stavu orchestrace.
- **Oprava:** Zpřístupnit manifest nebo generační čítač pro dvojici souborů, případně v `read_plan_file()` kontrolovat shodu revizí obou dokumentů.

---

### N16 — Reuse kontextu zbytečně přepisuje existující artefakt
- **Soubory:** `src/local_ai_hub/context_ledger.py`, `src/local_ai_hub/artifacts.py`
- **Mechanismus:** V `ContextLedger.compile()` se bezpodmínečně volá:
  ```python
  artifact_store.put(raw_context, kind="agent-context")
  ```
  Teprve poté se porovnává digest a vrací `status="unchanged"`.
- **Dopad:** I pro zcela nezměněný kontext probíhá zbytečný diskový zápis a SQL `INSERT OR REPLACE` do artifact databáze.
- **Oprava:** Nejprve zkontrolovat digest a ověřit existenci odpovídajícího artefaktu. Zápis provádět pouze při změně obsahu nebo neexistenci artefaktu.

---

### N17 — Context delivery rezervuje pro užitečný text pouze šestinu rozpočtu
- **Soubor:** `src/local_ai_hub/context_delivery.py`
- **Mechanismus:** Textový rozpočet je pevně nastaven na:
  ```python
  text_budget = max(32, int(budget) // 6)
  ```
- **Dopad:** Z celkového rozpočtu 8 192 tokenů dostane samotný text maximálně cca 1 365 tokenů. Větší texty jsou zbytečně označeny jako nekompletní a nutí agenta volat extra tool call pro načtení artefaktu.
- **Oprava:** Spočítat reálnou velikost hlaviček a metadat a zbytek rozpočtu dynamicky alokovat pro text.

---

### N18 — `repository_revision` není vždy součástí identity semantic cache
- **Soubor:** `src/local_ai_hub/services.py`
- **Mechanismus:** Do sémantického scope se `repository_revision` přidává pouze tehdy, pokud je vyplněn `project_config_digest` nebo `project_namespace`.
- **Dopad:** Pokud volající poskytne revizi repozitáře bez těchto doplňkových polí, dotazy nad různými commity budou mít identický scope a mohou vrátit zastaralý sémantický cache hit.
- **Oprava:** Vždy bezpodmínečně zahrnout známou `repository_revision` do klíče semantic scope.

---

### N19 — Sémantická cache není verzovaná podle embeddingového prostoru
- **Soubor:** `src/local_ai_hub/semantic_cache.py`
- **Mechanismus:** Uložené vektory v sémantické cache nemají vazbu na model, kterým byly vytvořeny.
- **Dopad:** Při změně embeddingového modelu v konfiguraci může cache porovnávat nekompatibilní vektory a vracet falešné cache hity.
- **Oprava:** Zahrnout identifikátor embedding prostoru do namespace sémantické cache a při změně provést invalidaci.

---

### N20 — Běžná chyba modelového volání může označit celý GPU runtime za nejistý
- **Soubor:** `src/local_ai_hub/scheduler.py` (`_run_job`)
- **Mechanismus:** Při vyhodnocení výsledku:
  ```python
  failed = (result.get("success") is False or bool(result.get("error"))) and not clean_cancel
  ```
  se může nastavit `self._internal_gpu_uncertain = True`.
- **Dopad:** Pokud model vrátí validní aplikační chybu (např. odmítnutí dotazu nebo nevalidní formát), celý scheduler může zablokovat další GPU operace.
- **Oprava:** Rozlišovat systémové selhání backendu (pád procesu, timeout spojení) od aplikační chyby modelu (`completed_cleanly_with_app_error`). Pouze fatální stavy smí nastavit `gpu_uncertain`.

---

### N21 — `SinglePassIngestCache._evict_if_needed()` dovoluje ponechat soubor větší než limit
- **Soubor:** `src/local_ai_hub/preprocess_ingest.py`
- **Mechanismus:** Pokud je vkládaná položka sama o sobě větší než `max_bytes`, eviction vyprázdní celou cache, ale položku přesto vloží.
- **Dopad:** Cache okamžitě překračuje svůj nakonfigurovaný paměťový limit.
- **Oprava:** Nadrozměrné položky vůbec neukládat do cache a vracet je jako uncached stream.

---

### N22 — `MemoryStore.find()` neescapuje SQL wildcards v dotazu LIKE
- **Soubor:** `src/local_ai_hub/agent_memory.py`
- **Mechanismus:** Vyhledávání používá přímé vložení do LIKE vzoru: `f"%{query}%"`.
- **Dopad:** Pokud uživatel hledá řetězec obsahující `%` nebo `_`, SQLite je interpretuje jako zástupné znaky pro libovolný řetězec či znak.
- **Oprava:** Escapovat znaky `%`, `_` a `\` a použít klauzuli `ESCAPE '\'`.

---

### N23 — `RoutingEngine.select_tests()` generuje Python cestu i pro cizí jazyky
- **Soubor:** `src/local_ai_hub/agent_routing.py`
- **Mechanismus:** Metoda natvrdo generuje název `tests/test_<name>.py` bez ohledu na příponu zdrojového souboru (např. TypeScript, Rust, Go).
- **Dopad:** Doporučení testů pro jiné jazyky vrací neexistující cesty.
- **Oprava:** Zohlednit jazyk zdrojového souboru a mapovat testy podle konvencí daného ekosystému.

---

### N24 — `SinglePassIngestCache.invalidate()` maže položky pouze podle relativní cesty
- **Soubor:** `src/local_ai_hub/preprocess_ingest.py`
- **Mechanismus:** Metoda `invalidate(rel_path)` odstraňuje záznam bez znalosti kořene repozitáře.
- **Dopad:** Po implementaci opravy N11 by neúplná invalidace smazala záznamy napříč všemi projekty se stejnou relativní cestou.
- **Oprava:** Vyžadovat v `invalidate()` plnou identitu včetně kořene repozitáře.

### N14 — Ověření aktuálního chování (Round 84, 2026-11-11)

Uvolnění jednoho lease zachová čekací hranu, pokud stejný vlastník stále drží jiný aktivní lease překrývající `requested_path`. Hrana se odstraní po uvolnění posledního překrývajícího lease. Porovnání používá `_overlap()` a pravidla citlivosti na velikost písmen podle kořene; změna schématu nebyla potřeba. Regresní test nejprve selhal a po opravě N14 testy prošly **2/2**, navazující deadlock test **2/2**. Podrobnosti a SHA jsou v Round 84 v `docs/agent-evaluation/results.md`.

### N13/N15 — aktuální stav (Round 85, 2026-11-11)

N13: filtry source+target už fungují společně; projektová izolace zůstává nevyřešená, protože tabulka i API zápisu postrádají repository provenance a staré vztahy nelze bezpečně přiřadit. N15: writer drží lock při zápisu obou souborů, ale `read_plan_file()` jej nezískává; atomické čtení dvojice není doloženo. Viz Round 85 v `docs/agent-evaluation/results.md`.

### N15 — aktuální stav (2026-11-11)

`read_plan_file()` nyní sdílí storage lock. Nové `read_spec_and_plan()` načte obsah i revizi specifikace a plán i jeho revizi pod jedním lockem. Regresní souběhový test ověřil, že čtenář počká na zápis dvojice a vrátí novou specifikaci s novým plánem. `tests/test_repo_plan_storage.py`: **12 passed**. Čtenáři dvojice mají používat toto API; přímé čtení souborů mimo něj kontrakt nepokrývá.

### N04 — LRU cache kapacita (Round 86, 2026-11-11)

`MemoryLRUCache` rozděluje zbytek `max_entries` mezi shardy; `set()` i `set_many()` zachovávají plnou nakonfigurovanou kapacitu. Test pokryl kapacitu 1 a nedělitelnou kapacitu 17: **4 passed**. N05–N11, N13 a N18–N20 zůstávají podle vlastnictví a chybějících důkazů otevřené. N21 je ověřen v Round 99; N24 je opraven a cíleně ověřen níže.

### N24 — aktuální stav (Round 99, 2026-11-11)

`SinglePassIngestCache.invalidate(rel_path)` nyní vyžaduje neprázdný `root`; jinak vyvolá `ValueError` před zámkem a mutací. Root-qualified invalidace smaže jen odpovídající repository key. Produkční watcher call-site již předává root. Test-first důkaz: chybějící/empty-root testy nejprve selhaly (**2 failed, 1 passed, 2 deselected**); po opravě oba cílené testovací soubory prošly (**18 passed in 1.57s**). Stejný cílený běh zahrnul existující N21 regresi pro oversized vstupy; `put()` odmítá cacheovat příliš velké řetězce i `IngestedFile` objekty. SHA zdroje a testů jsou v `docs/agent-evaluation/results.md`. Plná sada zůstává mimo tento důkaz.
