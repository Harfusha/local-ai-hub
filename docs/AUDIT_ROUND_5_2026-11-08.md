# Local AI Hub — Páté kolo hloubkového auditu & Nápravný plán

**Datum:** 8. listopadu 2026  
**Cílová revize:** `master` · Commit `2176b0e210cbd64fb2260f721f8546d5365b463f`  
**Hub Plan ID:** `plan_audit_round5_fixes_20261108`  
**Paměťový záznam:** `mem_72fbef3d4e52`

---

## 1. Manažerské shrnutí

Páté kolo hloubkového auditu se zaměřilo na kontrakty mezi MCP serverem, admission kontrolou, vyhledávacími moduly a podpůrnými vykonávacími službami v repozitáři [Harfusha/local-ai-hub](https://github.com/Harfusha/local-ai-hub).

Ze všech 19 nových zjištění (B01–B19) bylo všech 19 přímo ověřeno a potvrzeno ve zdrojovém kódu na commitu `2176b0e`.

### Klíčové kritické nálezy (Top priority):
1. **B02 (P1 — Model Memory Policy):** `ModelExecutionPolicy._is_small_model()` testuje přítomnost podřetězce `"3b"` v názvu modelu. Názvy jako `qwen:13b`, `model:23b`, `model:33b` jsou vyhodnoceny jako malé (3B) modely, čímž obcházejí VRAM limity (`target = min(target, 8192)` i uvolnění VRAM `keep_alive = "0s"`).
2. **B01 (P1 — Root-family Admission Ownership):** `RootFamilyBudget.reserve()` při shodě scope vrací `status: "coalesced"`. MCP server ale pro coalesced volání vytvoří stejnou rezervaci jako pro `accepted`. Na exitu pak volá `release()`, čímž uvolní tokeny i aktivní scope původního běžícího požadavku.
3. **B10 (P1 — Runtime Output Integrity):** `normalizer.py postprocess_model_output` globálně odstraňuje stop tokeny včetně literálu `[DONE]` a tagů `<plan>...</plan>`, i když jsou součástí platného generovaného kódu nebo testovacích fixtures (např. `assert resp == "[DONE]"` se změní na `assert resp == ""`).
4. **B09 (P1 — Circuit Breaker Generations):** `CircuitBreakerRegistry` neeviduje generaci nebo probe token. Opožděný úspěch starého vypršeného probe pokusu resetuje stav celého breakeru, přestože právě běží novější half-open probe.
5. **B13 (P1 — Recovery Journal Terminal CAS):** `RecoveryJournal.finish()` a dávkový zápis neobsahují podmínku `AND state = 'running'`, což umožňuje přepsat autoritativní terminální výsledek operace protichůdným stavem při opožděném callbacku.

---

## 2. Přehled nálezů (B01–B19)

| ID | Komponenta | Popis zjištění | Priorita | Umístění v kódu |
|:---|:---|:---|:---:|:---|
| **B01** | Admission / Budget | `RootFamilyBudget` coalesced scope uvolní cizí rezervaci na exitu | 🔴 P1 | `budget.py:74-139`, `mcp_server.py:3191-3207` |
| **B02** | Model Policy | `_is_small_model` substring `"3b"` klasifikuje 13B/23B/33B jako malé | 🔴 P1 | `model_policy.py:245-319` |
| **B03** | Code Index Demand | PHP demand indexing nerozpoznává Composer PSR-4 `use` importy | 🔴 P1 | `code_index_demand.py:250-311` |
| **B04** | Retrieval | `_SOURCE_SUFFIXES` postrádá `.php`, `.rb`, `.vue`, `.svelte` | 🟡 P2 | `retrieval.py:14-111` |
| **B05** | Retrieval | `_SOURCE_QUERY` má pouze anglické výrazy, český dotaz neaktivuje source-first | 🟡 P2 | `retrieval.py:14-58` |
| **B06** | Code Index Demand | TS NodeNext importy s příponou `.js` se nemapují na `.ts`/`.tsx` | 🔴 P1 | `code_index_demand.py:63-91` |
| **B07** | Code Index Demand | Rust `mod bar;` v `src/foo.rs` nenajde `src/foo/bar.rs` | 🟡 P2 | `code_index_demand.py:167-198` |
| **B08** | Code Index Demand | One-hop dependency discovery prochází celé `eligible` $O(N \times M)$ | 🟡 P2 | `code_index_demand.py:136-250` |
| **B09** | Circuit Breaker | Breaker neumí odlišit opožděný výsledek starého half-open probe pokusu | 🔴 P1 | `resilience.py:55-149`, `services.py:1415-1445` |
| **B10** | Normalizer | `postprocess_model_output` globálně maže `[DONE]` a `<plan>` i v kódu | 🔴 P1 | `normalizer.py:177-250`, `services.py:1585-1610` |
| **B11** | VRAM Balancer | Speculative inference metadata reportuje `active` jen z tlaku paměti (1.5B vs 3B) | 🟡 P2 | `vram_balancer.py:450-510` |
| **B12** | Response Protocol | `project_response()` nemá tvrdý limit po `_dense` u protected fields | 🟡 P2 | `response_protocol.py:46-149` |
| **B13** | Recovery Journal | `finish()` neobsahuje CAS `AND state = 'running'`, dovoluje přepsat výsledek | 🔴 P1 | `resilience.py:421-544` |
| **B14** | Evaluation Quality | `paired_retrieval_delta` míchá `path_only` a `symbol_ast` a padá na `KeyError` | 🔴 P1 | `evaluation_quality.py:8-70` |
| **B15** | Vision Request | `build_vision_request()` vnucuje pevnou review instrukci i při custom JSON schema | 🟡 P2 | `vision_request.py:78-162` |
| **B16** | Vision Service | `fix_requested` používá pouze anglické markery, ignoruje české zadání | 🟡 P2 | `vision_service.py:365-400` |
| **B17** | Context Warmup | `ContextWarmup.submit()` throttluje 60s i po chybě nebo timeoutu ve frontě | 🟡 P2 | `context_warmup.py:21-76` |
| **B18** | Code Index Demand | Go import kořenového modulu bez slash (`imp == module_name`) se nerozpozná | 🟡 P2 | `code_index_demand.py:136-165` |
| **B19** | Code Index Demand | C# using namespace shoduje jakýkoliv soubor se stejným stemem (`IO.cs`) | 🟡 P2 | `code_index_demand.py:224-238` |

---

## 3. Nápravný plán (14 úkolů v Hub Planu `plan_audit_round5_fixes_20261108`)

1. **`task_b02_model_policy`** (P1): `model_policy.py` — Parsování velikosti modelu z přesných metadat nebo regexem ohraničeného tagu (`r'(?:^|:|-)(\d+(?:\.\d+)?)[bB]'`). Eliminace substringu `"3b"`. Testy pro 3B, 7B, 13B, 23B, 33B.
2. **`task_b01_root_family_admission`** (P1): `budget.py` & `mcp_server.py` — Zavedení `reservation_id` a `owns_reservation: bool`. `coalesced` nesmí dovolit volajícímu odečíst cizí tokeny. Idempotentní uvolnění.
3. **`task_b10_output_integrity`** (P1): `normalizer.py` & `services.py` — Oddělení režimů normalizace: kód, unified diff, JSON a obecný text. Odstranění globálního mazání `[DONE]` a `<plan>` ze zdrojového kódu.
4. **`task_b09_circuit_breaker_generations`** (P1): `resilience.py` — Zavedení generace/tokenu probe pokusu do `allow()`, `success()` a `failure()`. Ignorování opožděných výsledků expirovaných sond.
5. **`task_b13_recovery_journal_cas`** (P1): `resilience.py` — CAS podmínka `WHERE request_id = ? AND state = 'running'`. Idempotentní návrat původního výsledku při opakování, odmítnutí konfliktního přepsání.
6. **`task_b03_php_psr4_discovery`** (P1): `code_index_demand.py` — Načtení `composer.json` (`autoload.psr-4`), mapování namespace prefixů na cesty, podpora `use Namespace\Class as Alias;`.
7. **`task_b04_b05_unified_language_registry`** (P2): `retrieval.py` — Doplnění `.php`, `.rb`, `.vue`, `.svelte` do `_SOURCE_SUFFIXES`. Explicitní parametr `intent=source_analysis` a deterministické příznakové signály.
8. **`task_b06_b07_b18_import_resolvers`** (P1/P2): `code_index_demand.py` — NodeNext extension substitution (`.js` $\to$ `.ts`/`.tsx`), Rust vnořené moduly (`foo/bar.rs`), Go přesná shoda `imp == module_name`.
9. **`task_b08_b19_indexed_dependency_lookup`** (P2): `code_index_demand.py` — Předpočítaný lookup index (`by_dir`, `by_stem`, `by_ext`) eliminující $O(N \times M)$ skeny. C# párování vyžadující namespace/assembly vazbu.
10. **`task_b14_retrieval_evaluation_contract`** (P1): `evaluation_quality.py` — Validace homogenního měřicího rámce napříč sadou, ošetření `KeyError`, oddělená agregace pro smíšené sady.
11. **`task_b12_response_size_contract`** (P2): `response_protocol.py` — Závěrečný hard-cap validátor délky serializovaného JSON. Při překročení návrat explicitního `budget_rejected` envelope.
12. **`task_b15_b16_vision_contracts`** (P2): `vision_request.py` & `vision_service.py` — Respektování uživatelského JSON schématu v promptu; explicitní `operation=fix|review|describe` parametr pro aktivaci coder kontextu.
13. **`task_b17_warmup_lifecycle`** (P2): `context_warmup.py` — Stavový automat (`enqueued`, `running`, `succeeded`, `failed`, `expired`). 60s cooldown pouze po úspěchu; zkrácený backoff po chybě.
14. **`task_b11_speculative_inference_observability`** (P2): `vram_balancer.py` — Oddělení stavů `recommended`, `configured`, `runtime_active`. Kontrola vhodnosti draft/target modelu.

---

## 4. Specifikace regresních testů (R5-01 až R5-15)

| Test ID | Cílová komponenta | Vstupní scénář | Očekávaný výsledek |
|:---|:---|:---|:---|
| **R5-01** | `budget.py`, `mcp_server.py` | 2 souběžné požadavky na stejný budget scope | Rezervace není odečtena dvakrát; 3. požadavek neprojde předčasně |
| **R5-02** | `model_policy.py` | Model `qwen:13b`, dostupná VRAM 5 GB | Neuplatní se politika 3B modelu; `num_ctx <= 8192`, `keep_alive = "0s"` |
| **R5-03** | `code_index_demand.py` | PHP controller s PSR-4 `use App\Service\UserService;` | `src/Service/UserService.php` se objeví v one-hop dependencies |
| **R5-04** | `retrieval.py` | Český dotaz „Najdi chybu ve funkci UsersController“ | Source-first režim se spolehlivě aktivuje |
| **R5-05** | `code_index_demand.py` | TS NodeNext `import { f } from "./user.js"` | Resolver úspěšně namapuje na existující `src/user.ts` |
| **R5-06** | `code_index_demand.py` | `src/foo.rs` s deklarací `mod bar;` | Resolver dohledá `src/foo/bar.rs` i `src/foo/bar/mod.rs` |
| **R5-07** | `resilience.py` | Circuit breaker: vypršený probe A, nový probe B, pozdní úspěch A | Pozdní doběh A neresetuje stav aktivní sondy B |
| **R5-08** | `normalizer.py` | Generovaný kód obsahující literál `assert x == "[DONE]"` | Obsah zůstane přesně zachován bez umazání řetězce |
| **R5-09** | `response_protocol.py` | Odpověď s mnoha chráněnými poli a rozpočtem 64 tokenů | Výstup nepřekročí limit; při nemožnosti vrátí `budget_rejected` |
| **R5-10** | `resilience.py` | Dvakrát `finish()` pro stejné request ID s odlišnými výsledky | Původní terminální stav zůstane autoritativní a nezměněný |
| **R5-11** | `evaluation_quality.py` | Smíšená sada benchmarků (`path_only` + `symbol_ast`) | Oddělené metriky bez výjimky `KeyError` nezávisle na pořadí |
| **R5-12** | `vision_request.py` | Custom JSON schema bez polí `findings`/`unknowns` | Prompt nepožaduje nekompatibilní pevnou review strukturu |
| **R5-13** | `vision_service.py` | Vision dotaz „Oprav responzivní rozložení komponenty“ | Úspěšně se aktivuje coder context workflow |
| **R5-14** | `context_warmup.py` | Warmup operace vyhodí výjimku nebo expiruje ve frontě | Systém neblokuje opakovaný pokus plným 60s cooldownem |
| **R5-15** | `code_index_demand.py` | Go import kořenového balíčku modulu (`import "module"`) | One-hop resolver úspěšně identifikuje soubory kořenového balíčku |

---

## 5. Pozitivní architektonické vlastnosti k zachování

Při realizaci úprav z 5. kola je nutné striktně zachovat:
- **`budget.py`**: Thread-safe zámky `threading.RLock()` a striktní sanitizaci family klíčů bez null-bytes.
- **`model_policy.py`**: Ochrannou sampling teplotu (headroom 0.20 pro greedy módy) a podporu `thinking` rolí.
- **`code_index_demand.py`**: Ochrannou kontrolu `_safe_inventory_file` proti traversal útokům a únikům z project rootu.
- **`resilience.py`**: Bounded in-memory struktury (max 4096 breakers), thread-safe CAS operace a write-behind dávkování žurnálu.
- **`retrieval.py`**: Bounded candidate fusion (max 4096 cest per group) a ochranu proti symlink/junction cyklům.
