# Local AI Hub — Realizační plán a regresní matice (Audit Round 2)

**Vychází z:** `docs/AUDIT_ROUND2.md`  
**Datum:** 8. listopadu 2026  
**Cíl:** Odstranění zjištěných chyb a architektonických rizik v logických etapách s přísnou verifikací.

---

## 1. Implementační etapy podle závislostí

### Etapa A — Zabránit nekonzistentním datům a kolizím cache (Nejvyšší priorita)
*Cíl: Zajistit, aby sémantické vyhledávání, preprocessing cache a RAG nemohly míchat data mezi projekty ani vracet neplatné výsledky po změně konfigurace.*

1. **N11 — Root-aware Preprocessing Ingest Cache:**
   - Původní cíl zůstává: klíčovat ingest podle canonical root, relative path a source content hash; ověřit všechny cache API a cesty k RAG.
   - **Částečně ověřeno 2026-11-12:** aktuální `_key()` canonicalizuje root a zahrnuje relativní cestu. `tests/test_audit_round2_preprocess_ingest.py::test_cross_project_ingest_cache_isolation` a `::test_invalidate_relative_path_is_scoped_to_root` prošly každá samostatně (1 passed; 0.36 s a 0.27 s). Source SHA `7a9a8c9849bb9339bbc26900749a946a179919b229977a2db163e157bfee7ec1`; test SHA `c0613bdc481b055aeb328ad45d7a7addd203524a5f0b9484ba7382a9b2b48684`; HEAD `409bed4a6a73fd66175ad339c399f4277ed0ed99`.
   - **Otevřeno — source-only follow-up, 2026-11-12:** klíč zůstává canonical root + relative path bez content hash. `_step_hash()` obnoví digest, ale při mismatch neinvaliduje `ingest_cache`; file-watcher invalidace je oddělená. `_step_lexical()` hash mismatch odmítne publikovat a vrátí `needs_hash=1`, takže stale text není potvrzen jako publikovaný. Bez watcher invalidace může stale cache hit opakovat hash/lexical cyklus a blokovat index update. Důkazy: `preprocess_ingest.py` SHA `7a9a8c9849bb9339bbc26900749a946a179919b229977a2db163e157bfee7ec1`; `preprocess.py` SHA `a07838931b8eb3e5931d53a3b78e8c0941e7a8dd3eaf86f572e6a68e78cd3dbc`; structural requests `req_6dd5d8c7b829`, `req_720e429a2bd9`, `req_0220dd35c494`. No targeted regression, live server/RAG action, or end-to-end cross-project proof for this branch. Runtime and functional acceptance remain NOT_VERIFIED. Finding sent to Stability; current-owner decision and integration pending.
   - **Fresh recheck 2026-11-18, dirty HEAD `cc741b54dc04830900df81b5034e7f993140b3c5`:** the 2026-11-12 cache-cycle concern is superseded for `_step_lexical`: it passes the current DB `content_hash` as `expected_hash`, and the ingest cache key includes canonical root, relative path, and content hash. A changed source cannot reuse an entry for the old hash; hash mismatch is withheld from lexical publication and requeued. `python -m pytest --no-cache -q tests/test_preprocess_single_pass_ingest.py` passed 14 tests. `preprocess.py` SHA-256 `9ab22ae3e86252306fe1049f02f9b141765c647334cc1e794da4abae373f0399`; `preprocess_ingest.py` SHA-256 `059308a590056893ab65a3fa3d49d9254f5c8351ab22b2755553ddbe608cf23c`; test SHA-256 `f4aab21fd618acff3486385986ccfbc15b96dfd525d5e7f8d5c7c5b6ab161a5f`. This closes only the reviewed lexical path; other cache APIs, RAG integration and live preprocessing acceptance remain open. `preprocess.py` is user-owned and was not edited.
   - **N24 recheck 2026-11-18:** root-scoped relative-path invalidation and rejection without a nonempty root are verified; the focused tests passed 3/3. See `docs/FINAL_COMPLETION_PLAN.md` for source/test hashes. N24 is no longer a pending code change.
   - **N21 recheck 2026-11-18:** `SinglePassIngestCache.put()` rejects entries larger than `max_bytes` for both string and `IngestedFile` inputs. Added `test_single_pass_ingest_rejects_single_item_larger_than_byte_limit`; the full focused file passed 15 tests. Source SHA-256 `059308a590056893ab65a3fa3d49d9254f5c8351ab22b2755553ddbe608cf23c`; test SHA-256 `1d87dbf539bae709fcf46c400c28c3800088f6c9755d173a12ef5d900ea6d218`. No source change was needed.
2. **N18 — Striktní `repository_revision` v Semantic Scope:**
   - V `services.py` vždy začlenit `repository_revision` do scope identity bez ohledu na přítomnost doplňkových digestů.
   - Při neznámé revizi u úloh vázaných na kód zakázat sémantický reuse.
   - **Current-source recheck 2026-11-19:** `generation_cache_key()` includes `repository_revision` unconditionally. Focused N18 suite passed **3 tests**: different revisions produce different semantic scopes, code-bound work without a revision skips semantic lookup, and a known revision allows semantic reuse. `services.py` SHA-256 `c9acd7cdb6f53480ec5537fd48f0bdb45942a65f64bc9be37b1d889d066e8138`; test SHA-256 `5a8f7d8cf1a618f9082253819416fe914309ec985586ab7a8e5184c6b44657a0`. No source change was needed; runtime acceptance remains separate.
3. **N09 — Verzovaná identita modelu v Agent Memory:**
   - Přidat sloupce `embedding_space_id`, `model_name`, `dimension` do `agent_memory_embeddings`.
   - Zavést validaci kompatibility před kosinovým porovnáním; při neshodě fallback na lexikální vyhledávání.
   - **Current-source recheck 2026-11-19:** `agent_memory_embeddings` stores `embedding_space_id`, `model_name`, and `dimension`; vector candidates are compared only when query and stored space IDs match and dimensions agree. The targeted N09 tests passed **3** cases (2 deselected). Source SHA-256 `4bf65e23e7db7d09b2ee49dc64c7999d0b9d5cba7bd782132f666bdfc0765534`; test SHA-256 `89c07bf5408bbd0584a78e9244e68520f98f32395f505bdcf3e56de5657e9a02`. This uses stub embeddings, not an installed model. Legacy database upgrade behavior remains NOT_VERIFIED; a manually-created partial schema is rejected by durable-schema preflight and does not represent a supported migration fixture.
4. **N19 — Verzování Semantic Generation Cache:**
   - Přidat embedding prostor do namespace sémantické cache, zamezit míchání vektorů různých modelů.
   - **Fresh source/test recheck 2026-11-18:** L1 and SQLite lookup/store keys use the active embedding space; `test_n19_semantic_generation_cache_embedding_space_isolation` confirms space-a entries are not reused in space-b. The same review found eviction counted rows under the scoped key but deleted under the raw scope; corrected the DELETE bind to use the scoped key. The new regression failed first (`2` rows remained with `max_entries=1`), then passed. `tests/test_audit_round2_embedding_versioning.py` passed 5 tests; the semantic-cache focused set passed 16. `release_check.py --allow-installed`, `compileall -q src tools tests` and `git diff --check` passed. Source SHA-256 `39810fc8cd94d39f25120b25b6492bec10b173031876e02b142cce6253c060e8`; eviction test file SHA-256 `a030dd54f77c279ec824f68d468cbe6fd3db3a28ee3ce1479ae00f61cdc3032c`. Dirty-checkout checks only; runtime/release acceptance remains open.
   - **Fresh test recheck 2026-11-19:** `python -m pytest --no-cache -q tests/test_audit_round2_embedding_versioning.py::test_n19_semantic_generation_cache_embedding_space_isolation --tb=short` passed **1 test** (0.51s). Current `semantic_cache.py` SHA-256 `39810fc8cd94d39f25120b25b6492bec10b173031876e02b142cce6253c060e8`; no source change was needed. Runtime acceptance remains separate.

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
   - Ověřeno v HEAD: BFS omezuje navštívené uzly přes `max_nodes`; edge SQL vrací jen hrany s oběma konci v seznamu uzlů. Starý popis rekurzivního CTE neplatí.
   - N02 regresní test pokrývá uzavřený podgraf při limitu 2; existující N03 test kontroluje počet SELECTů proti `max_nodes + 1`. Round 81: 3 passed.
4. **N14 — Vyčištění čekacích hran v `ScopeLeaseStore`:**
   - Hotovo v Round 84: při uvolnění ponechat wait hranu, pokud stejný vlastník stále drží aktivní lease překrývající `requested_path`; odstranit ji až po zániku posledního blockeru. Použít `_overlap` včetně pravidel pro case-insensitive Windows cesty, bez změny schématu.
   - Regrese pro duplicitní lease nejprve selhala a po opravě prošla; `tests/test_audit_round2_leases_n14.py` 2 passed a `tests/test_lease_atomic_deadlock.py` 2 passed.
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
   - **Implementation recheck 2026-11-19:** both entry points call `_queue_job_locked()` while holding the scheduler condition. The shared path refreshes external GPU reservation state, checks internal uncertainty and model cooldown, calls `_admission(background, model)`, checks queue capacity, and creates/traces the `Job`. `submit()` keeps caller deadline/cancellation and foreground preemption outside the helper; `enqueue()` remains nonblocking and only notifies after queueing. A red regression exposed the missing reservation refresh in `enqueue()`; it now uses the shared path. Source `scheduler.py` SHA-256 `e1df23deb023e442f74c79832f878382e9e8ba1b206b2c9554a4c07aee4edd87`; test SHA-256 `e4199d27e7c9e40aaece76fd16fa07d568f3f70b52459e51f971dfb81e42ecd4`.
4. **N08 — Relevance versus náklad přepnutí modelu:**
   - **Recheck 2026-11-18:** `_choose_initial_model()` prefers an already-loaded model only when its priority is within 2 points of the highest waiting job. Fresh `python -m pytest --no-cache -q tests/test_audit_round2_etapa_e.py::test_n08_scheduler_does_not_starve_high_priority_for_resident_model` passed (1 passed in 0.82s); it proves priority-9 urgent work beats a resident priority-1 job. This fixed guard is not the audit's measured `priority + wait - switch_cost` score. Bounded GPU admission ended with `503 vram_budget`; do not repeat the stress operation. Keep N08 OPEN for switch-cost calibration and performance evidence. `scheduler.py` SHA-256 `c41f45a3f2d3c9ddc46fe284bb511bbbaec65f6d9fd884a3da2f731ace989348`; test SHA-256 `466becbdbe1982438299cc1f7684029e2330160e3e5d1b4affe10ea185dd3c4c`.
   - **Implementation recheck 2026-11-19 (supersedes the OPEN-for-source status above):** `_choose_initial_model()` now uses `S=P+W-C_switch`; `W` adds one priority point per 30 seconds, capped at 9, matching existing foreground aging. `C_switch` is mean observed `_stats["switch_time_ms"] / _switch_sequence`, converted into 30-second priority units and applied only when target model is not loaded. With no observed switches, penalty is 0; no cold-start constant was invented. TDD added switch-cost and wait-aging regressions; focused scheduler selection/fairness set passed 7/7. Source algorithm is implemented and source-tested; real workload switch-cost calibration/performance remains NOT_VERIFIED.

---

### Etapa D — Lepší využití kontextu a optimalizace paměti
*Cíl: Zvýšit relevanci vrácených vzpomínek a omezit zbytečnou režii I/O a tool callů.*

1. **N10 — Relevance-first vektorový výběr v Agent Memory:**
   - Nahradit prostý `ORDER BY created_at DESC LIMIT 500` relevančním výběrem (batch scan nebo hybridní ranking).
   - **Recheck 2026-11-18:** aktuální `MemoryStore.find()` streamuje všechny scoped vektory přes `fetchmany(512)` a udržuje bounded heap nejlepších shod; regresní test nalezne nejstarší relevantní záznam mezi 5 001 vektory. `tests/test_audit_round2_embedding_versioning.py` prošel 5/5 (včetně N09/N19). `agent_memory.py` SHA-256 `18d627ac7452d8a5a9397289ff06927c5a94ad935f18ffbe37cb0a1f43c09f95`; test SHA-256 `89c07bf5408bbd0584a78e9244e68520f98f32395f505bdcf3e56de5657e9a02`. Full-runtime performance at larger corpora remains unmeasured.
   - **Current-source recheck 2026-11-19:** `MemoryStore.find()` scans scoped embeddings in batches of 512 and retains bounded top matches; `test_n10_semantic_search_scans_past_newest_5000_embeddings` passed (**1 passed**, 3.21s) with a relevant oldest record among 5,001. Source SHA-256 `4bf65e23e7db7d09b2ee49dc64c7999d0b9d5cba7bd782132f666bdfc0765534`; test SHA-256 `89c07bf5408bbd0584a78e9244e68520f98f32395f505bdcf3e56de5657e9a02`. This proves candidate recall for the fixture, not large-corpus performance or installed-runtime behavior.
2. **N16 — Eliminace zbytečných zápisů do ArtifactStore:**
   - Hotovo: `compile()` ověřuje digest, čerstvost pointeru a existenci artefaktu přes jednoznakový `get()` před reuse; `put()` zavolá jen pro nový/změněný nebo chybějící artefakt. Regrese ověřena v Round 82 (16 passed).
3. **N17 — Dynamické přidělování rozpočtu pro text v Context Delivery:**
   - Hotovo: výpočet textového rozpočtu zahrnuje také metadata přidaná při truncation. Regresní test potvrzuje více než šestinu rozpočtu pro užitečný text a celkový limit 3,200 tokenů (Round 83, 10 passed).
4. **N22 — Escapování wildcardů v `MemoryStore.find()`:**
   - Ověřeno v current HEAD: `find()` escapuje `\\`, `%` a `_` před LIKE a používá `ESCAPE`. Doplněn parametrizovaný regresní test pro doslovné `%` a `_`; `tests/test_agent_memory.py`: 57 passed (Round 79).

---

### Etapa E — Konzistence workflow a zbývající nálezy
*Cíl: Dokončení izolace projektů a začištění drobných implementačních nedostatků.*

1. **N13 — Namespace repozitáře pro entity grafu a oprava filtrů:**
   - Aktuální `find_relations()` už skládá `source_entity` a `target_entity` jako AND; cílený test prošel 1/1.
   - **Recheck 2026-11-18:** vztahy mají repository namespace podle canonical absolute `root`, uloženého v `metadata`; `find_relations()` i `traverse_graph()` vyžadují root a vylučují legacy řádky bez rootu. Test současně ověřuje filtrování source+target přes AND, izolaci dvou rootů, odmítnutí relativního rootu a vyloučení legacy relace. Fresh `python -m pytest --no-cache -q tests/test_audit_round2_graph_n02_n03_n13.py` → 3 passed. `agent_memory.py` SHA-256 `18d627ac7452d8a5a9397289ff06927c5a94ad935f18ffbe37cb0a1f43c09f95`; test SHA-256 `ca8c922795c180ca64a00d21a1b5fe8dc1508d3aba282f47337f2a559f574558`. Přímé `record_relation()` zápisy vyžadují root, ale `repository_id` ukládají pouze auto-linky z repository-scoped memory, pokud je v provenance dostupné. Root izolace je ověřena; obecné povinné `repository_id` a live/runtime přijetí doloženy nejsou.
2. **N15 — Atomická publikace dvojice Spec & Plan:**
   - Hotovo (2026-11-11): `read_plan_file()` používá storage lock a nové `read_spec_and_plan()` načítá specifikaci i plán pod jedním lockem. Souběhová regrese ověřila nový pár po dokončení zápisu; `tests/test_repo_plan_storage.py`: 12 passed. Přímé čtení souborů mimo API není součástí kontraktu.
3. **N04, N08, N21, N23:**
   - N04: Hotovo — limity shardů rozdělí celý `max_entries` včetně zbytku, takže součet kapacit odpovídá konfiguraci. Parametrizovaná regrese pro kapacitu 1/17 a `set`/`set_many`: 4 passed (Round 86).
   - N08: Výpočet kompenzovaného skóre přepnutí modelu ve scheduleru.
   - N21: Ověřeno (Round 99): `put()` odmítá položku větší než `max_bytes` před cache mutací. `test_evict_if_needed_does_not_keep_single_oversized_item` prošel v cíleném ingest běhu (**18 passed**).
   - N23: Hotovo — Python cesta se odvozuje jen pro `.py`; cizí nepodporované přípony se přeskočí. `.cs`, `.java`, `.cpp` pokryty regresním testem (Round 80).

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


## Round 2 N11 ingest cache current-source crosswalk — 2026-11-19

- `src/local_ai_hub/preprocess_ingest.py` SHA-256 `059308a590056893ab65a3fa3d49d9254f5c8351ab22b2755553ddbe608cf23c`; `tests/test_preprocess_single_pass_ingest.py` SHA-256 `1d87dbf539bae709fcf46c400c28c3800088f6c9755d173a12ef5d900ea6d218`.
- Fresh `python -m pytest --no-cache -q tests/test_preprocess_single_pass_ingest.py --tb=short`: **15 passed** in 1.16s. The current lexical-ingest contract uses root + relative path + content hash and this file tests shared ingest/cache safety; adjacent existing tests cover inventory identity and repository parse-cache paths.
- N11 is only partially evidenced: this suite does not establish all other cache APIs or end-to-end RAG/preprocessing integration. Those, installed-model behavior and live acceptance remain OPEN / NOT_VERIFIED. No model pull or live preprocess run.


### N01/N12 current-source crosswalk — 2026-11-19

- `src/local_ai_hub/token_router.py` SHA-256 `9ab51151dc60592591c919eddd19d3f9b537fba8ee5de5c7770bc4460980eb7d`; `tests/test_audit_round2_token_router_n12.py` SHA-256 `23db8e66f37c21ce8b6dbd9285ecc92698a9a09fd09cc230a8afd797812e8925`.
- Fresh `python -m pytest --no-cache -q tests/test_audit_round2_token_router_n12.py --tb=short`: **8 passed** in 1.11s. Explicit invalid/nonfinite/out-of-range scores are rejected; range normalization merges overlaps and enforces the rendered-line cap. Invalid selection falls back to deterministic routing.
- Source and focused regressions match N01/N12 criteria. This is isolated source/test evidence; installed model behavior and broader runtime acceptance remain separate.


### N08 scorer counter recheck and fix — 2026-11-19

- **Aktuální stav po integraci:** `_perform_switch()` aktualizuje `model_switches` a `successful_switch_time_ms` po úspěšné změně aktivního modelu. Scorer používá tyto dva čítače. Předchozí varianta počítající všechny pokusy způsobila tři regrese po selhání, zrušení nebo odmítnutí kapacity. Aktuální výběr přidává bonus za čekání úlohám v popředí. Prošlo 78 cílených testů včetně scénářů s řízeným časem. Kalibrace na GPU zůstává otevřená. Podrobnosti v `FINAL_COMPLETION_PLAN.md`.

Historický mezikrok se všemi pokusy:

- The earlier focused run reported **2 failed, 1 passed**. Its fixtures populated cumulative `switch_time_ms` and `_switch_sequence`, while the scorer used successful-switch counters. The reconciled fixtures populate the counters used by successful switches.
- Minimal fix: derive average switch cost from those existing counters. Scheduler source SHA-256 after fix: `67e039ef89c93b27a3ff2c88531cedc570c2152a6cf74609ca8ecfe8386172d3`. Existing test file SHA-256 `8c414deb589c5042e717f03583dd9fb6f09fa9fa0012beef9746417e50c820ea`.
- Fresh `python -m pytest --no-cache -q tests/test_audit_round2_etapa_e.py -k n08 --tb=short`: **3 passed, 1 deselected**. This verifies the selector cases; real-workload switch-cost calibration/performance remains NOT_VERIFIED.


### N20 current-source recheck — 2026-11-19

- `scheduler.py` SHA-256 `67e039ef89c93b27a3ff2c88531cedc570c2152a6cf74609ca8ecfe8386172d3`; `tests/test_audit_round2_scheduler_n20.py` SHA-256 `b4053016928605633aaf8949baa1d86978b895b53e80a58fced3509f526fa26e`.
- `_run_job()` marks GPU uncertainty for unknown/partial/timeout/cleanup states and fatal errors, while `completed_cleanly_with_app_error` and clean backend completion avoid poisoning scheduler certainty. Fresh focused test file: **3 passed** in 0.62s.
- Source/test evidence only; GPU runtime behavior remains subject to separately authorized live acceptance.


### N13 graph namespace current recheck — 2026-11-19

- `src/local_ai_hub/agent_memory.py` SHA-256 `9acb98c6a03fc79b7890ebe569cf003eccd81da601e7fd0520ca90bc114a6721`; `tests/test_audit_round2_graph_n02_n03_n13.py` SHA-256 `6da6aa873fd57ebdcea5ce26638a957f66b8af8416a4b0795f8ea51cdead4d0d`.
- Fresh focused graph regression file: **5 passed** in 1.94s. Existing cases cover bounded/closed traversal and canonical-root isolation with combined source/target filtering.
- Následné ověření N13 potvrdilo povinné `repository_id` pro přímý zápis a opravilo souběh dvou procesů při upgradu staré tabulky. Staré řádky zůstávají bez identity. Doklady a rozsah testů jsou v `FINAL_COMPLETION_PLAN.md`. Nasazená služba zůstává neověřená.


### N11/N21/N24 cache acceptance recheck — 2026-11-19

- `preprocess_ingest.py` remains SHA-256 `059308a590056893ab65a3fa3d49d9254f5c8351ab22b2755553ddbe608cf23c`; current `tests/test_audit_round2_preprocess_ingest.py` SHA-256 `c946327e608d9d28c02cdcc239fb90fbc0e9621d928a1a0469f0970c95daae3c`.
- Fresh focused cache contract suite: **5 passed** in 0.62s. It covers same-relative-path cross-project isolation, root-required invalidation, root-scoped invalidation, and rejection of an oversized cache entry.
- This strengthens local cache/API evidence. End-to-end RAG publication, all other cache APIs and live preprocessing remain NOT_VERIFIED; N11 stays partial.


### N09/N10/N19 embedding recheck — 2026-11-19

- Current `agent_memory.py` SHA-256 `9acb98c6a03fc79b7890ebe569cf003eccd81da601e7fd0520ca90bc114a6721`; `tests/test_audit_round2_embedding_versioning.py` SHA-256 `89c07bf5408bbd0584a78e9244e68520f98f32395f505bdcf3e56de5657e9a02`.
- Fresh complete focused suite: **5 passed** in 3.03s (N09 embedding-space compatibility, N10 scan past 5,000 records, N19 cache-space isolation, plus related cases).
- Následné ověření N09 našlo třísloupcové DDL v commitu `7adff149`. Upgrade proběhl na této historické projekci v jinak podporované databázi Agent State. Bezpečně zachoval staré vektory bez identity, textové hledání i možnost uložit a načíst nově identifikovaný vektor. Přerušení upgradu vrátilo původní schéma. Přesné otisky DDL prošly na Pythonu 3.11 až 3.13. Rozsah a doklady jsou v `FINAL_COMPLETION_PLAN.md`.


### T03 deterministic malformed-response fuzz — 2026-11-19

- Added a seeded, model-free loop over 1,000 malformed/extreme JSON responses to the focused TokenRouter regression file. Every response returned safely through deterministic fallback; no local inference was used.
- Fresh whole file `python -m pytest --no-cache -q tests/test_audit_round2_token_router_n12.py --tb=short`: **9 passed** in 26.34s.
- Test SHA-256 `d94c9ef926d86a93d8c9696dc82cf2aa522d84c46250652c126db048e7f1c391`; current implementation SHA remains `9ab51151dc60592591c919eddd19d3f9b537fba8ee5de5c7770bc4460980eb7d`. T03 acceptance is model-free; this does not establish installed-model behavior.


### N22 current-source LIKE wildcard recheck — 2026-11-19

- Current `agent_memory.py` SHA-256 `0da7dacbd7b4a8abfd6368620e71341b737af929cf59b0d0ded41c2a40e4d8c3`; `tests/test_agent_memory.py` SHA-256 `4dc7e25fa4d4c878fb6c02a45fe77f5fb03b2d9878ad80e90a245625fef0ccfb`.
- Fresh `python -m pytest --no-cache -q tests/test_agent_memory.py -k wildcard --tb=short`: **2 passed** (59 deselected, 0.53s). Literal `%` and `_` queries remain exact-match regressions.
- No code change required; broader memory suite/runtime acceptance is separate.

### N04 current sharded LRU capacity recheck — 2026-11-19

- Current `cache.py` SHA-256 `e9db1cc0c375ecc8fd3b7bdde311247537b04806cccd353763fa9be7155afb65`; regression file SHA-256 `e4199d27e7c9e40aaece76fd16fa07d568f3f70b52459e51f971dfb81e42ecd4`.
- Existing `test_t2_04_sharded_lru_uses_full_non_divisible_capacity` parameterizes `max_entries` 1/17 and `set`/`set_many`; fresh `python -m pytest --no-cache -q tests/test_audit_round2_regressions.py -k t2_04 --tb=short`: **5 passed, 16 deselected** in 0.57s.
- Current shard capacities sum to configured `max_entries`; this rechecks local behavior only, not workload/performance acceptance.

### Current-source recheck: Round 2 N13 and N08 — 2026-11-19

- N13: `record_relation` requires a canonical `repository_id` and absolute root; `find_relations` and `traverse_graph` filter on both. Legacy relation rows migrate with an empty repository ID rather than deriving identity from metadata. Fresh `python -m pytest --no-cache -q tests/test_audit_round2_graph_n02_n03_n13.py --tb=short`: **6 passed** in 2.05s. `agent_memory.py` SHA-256 `9da56f7c43c1e5a76fd8dc7980add2d29aaec6779caa00a567236b58b6d154bf`; test SHA-256 `e5c2a9eb3662673d02e3ea4fbf896aa10245c1541cf15e70788765ffbb5741d0`.
- N08: scheduler scores jobs using successful measured average switch time plus wait bonus; switch timing is recorded from `time.perf_counter()`. Fresh `python -m pytest --no-cache -q tests/test_audit_round2_etapa_e.py -k n08 --tb=short`: **3 passed, 1 deselected** in 0.38s. `scheduler.py` SHA-256 `9878785c05ff65d355d9c5bfa3ba5a2d4e6be066504204db907facc17fad97ac`; test SHA-256 `ca3838236b61f49fba8bf1ea435db0ee0b0f9aa0b6f2332ccba14bc6f08c24b9`.
- This verifies current source behavior and focused regressions. Real workload switch-cost calibration and live GPU admission remain NOT VERIFIED; no live GPU test or lease mutation was run.

### N10 malformed embedding rows and long-range recall recheck — 2026-11-19

- Current `MemoryStore.find()` skips invalid stored dimensions, malformed JSON, wrong-length vectors, and non-finite/bad scalar values without letting them mask valid matches. The regression runs scalar, NumPy batch, and NumPy mixed-type fallback modes; the separate recall case finds the oldest relevant record among 5,001 embeddings.
- Fresh `python -m pytest --no-cache -q tests/test_audit_round2_embedding_versioning.py --tb=short`: **9 passed** in 4.06s. `agent_memory.py` SHA-256 `b698b70f4624c40003beef6a00f7ebb24a07c8d923bedE02367dec3ca727503e`; test SHA-256 `543ed48a8f8d3ce1cecc33958d54333613ee565426ac03ba37d39b69d01c7208`.
- This verifies bounded fixtures and current local source. Large-corpus throughput and installed-runtime behavior remain NOT VERIFIED.

### N07 unified scheduler admission focused recheck — 2026-11-19

- Fresh `python -m pytest --no-cache -q tests/test_audit_round2_regressions.py::test_t2_10_scheduler_enqueue_passes_model_admission --tb=short`: **1 passed** in 0.47s. Current `scheduler.py` SHA-256 `9878785c05ff65d355d9c5bfa3ba5a2d4e6be066504204db907facc17fad97ac`; test file SHA-256 `e4199d27e7c9e40aaece76fd16fa07d568f3f70b52459e51f971dfb81e42ecd4`.
- This covers the enqueue model-admission argument in a local fixture; live GPU admission and workload acceptance remain NOT VERIFIED.

### Current-source recheck: Round 2 N03/N13 graph memory — 2026-11-19

- Fresh `python -m pytest --no-cache -q tests/test_audit_round2_graph_n02_n03_n13.py --tb=short`: **6 passed** in 4.09s against the current shared `agent_memory.py`. The suite covers graph traversal bounds and repository-scoped relation writes/queries.
- Current `agent_memory.py` SHA-256 `b698b70f4624c40003beef6a00f7ebb24a07c8d923bede02367dec3ca727503e`; test SHA-256 `e5c2a9eb3662673d02e3ea4fbf896aa10245c1541cf15e70788765ffbb5741d`.
- This is focused local-source evidence; installed-state migration and runtime acceptance remain NOT VERIFIED.

### Current-source recheck: Round 2 N20 scheduler certainty — 2026-11-19

- Fresh `python -m pytest --no-cache -q tests/test_audit_round2_scheduler_n20.py --tb=short`: **3 passed** in 0.49s. Current `scheduler.py` SHA-256 `9878785c05ff65d355d9c5bfa3ba5a2d4e6be066504204db907facc17fad97ac`; test SHA-256 `b4053016928605633aaf8949baa1d86978b895b53e80a58fced3509f526fa26e`.
- This covers deterministic uncertainty classification only; live GPU/runtime acceptance remains NOT VERIFIED.

### Current-source recheck: Round 2 N05/N06 async jobs — 2026-11-19

- Fresh five-file regression run: `python -m pytest --no-cache -q tests/test_audit_round2_async_n05_n06.py tests/test_async_jobs.py tests/test_async_job_reliability_contract.py tests/test_async_job_http_status_mapping.py tests/test_async_jobs_tasks.py --tb=short` → **128 passed** in 58.87s.
- `async_jobs.py` SHA-256 `74254b6d84443c9fe13d56440373e32e0fb3ae4b8884ab9a4dcfbc6434524f36`; tests: N05/N06 `7fab37e7c13ff5bcce07410eaaeb5da489339c25ab4cf791fceba48a03997140`, async jobs `9bb68b63c26d58610ccd3b14c0a963b767e39b63b8ba2116b354bf2d16e68c97`, reliability `33541659fceb4bd9e6a7d3b0c6d2f2cfc1262a42de5ea138f46fccd15ab11fbd`, HTTP mapping `99b49edf94852350ad5384b2436641bbd8b32c53b5ee5c59856a09ae692775b6`, task lifecycle `602cd2f5465fccb07ba6e983bda92236cde456bda231c26cff6677e36dcd802c`.
- Local regression evidence only; installed service and active-traffic behavior remain NOT VERIFIED.

### Current-source Agent Memory suite — 2026-11-19

- Fresh `python -m pytest --no-cache -q tests/test_agent_memory.py --tb=short`: **61 passed** in 12.15s against current `agent_memory.py`; includes literal LIKE wildcard coverage.
- Source SHA-256 `b698b70f4624c40003beef6a00f7ebb24a07c8d923bede02367dec3ca727503e`; test SHA-256 `4dc7e25fa4d4c878fb6c02a45fe77f5fb03b2d9878ad80e90a245625fef0ccfb`.
- This is local fixture/test evidence only; installed memory DB migration and runtime acceptance remain NOT VERIFIED.

### Existing-card export fixture recheck — 2026-11-19

- `python -m pytest --no-cache -q tests/unit/test_model_training_scaffold.py -k existing_card_export --tb=short`: **4 passed, 23 deselected** in 1.17s. Test file SHA-256 `84e689d46152e0c23d3802547220efe76044c4382883c71c29f1ecf2509c54cd`.
- This is fixture-only export coverage; no user dataset, model pull, training or evaluation run occurred. Live dataset quality remains NOT VERIFIED.
