# Local AI Hub — Třetí kolo hloubkového auditu & Nápravný plán

**Datum:** 8. listopadu 2026  
**Cílová revize:** `master` · Commit `2176b0e210cbd64fb2260f721f8546d5365b463f`  
**Hub Plan ID:** `plan_audit_round3_fixes_20261108`  
**Agent OS Task:** `task_8d00194c6553`  

---

## 1. Manažerské shrnutí

Třetí auditní cyklus se zaměřil na subsystémy mimo primární RAG/ingest flow: agentní semafory, CRDT blackboard, asynchronní databázový write actor, swarm DAG orchestraci, generování a verifikaci testů a síťové transporty.

Z celkem 21 identifikovaných nálezů (T01–T21) byla v kódu přímo potvrzena řada závažných anomálií, kde **API poskytuje silnější záruky, než jaké implementace reálně vynucuje**. Tři nejkritičtější případy:

1. **T01 (Kritická — Agent Semaphores):** `SemaphoreStore.acquire()` nepoužívá `BEGIN IMMEDIATE` ani meziprocesový zámek; vícenásobné procesy mohou při `capacity=1` současně získat platný lease.
2. **T09 (Vysoká — Swarm DAG):** `execute_swarm_dag()` vyhodnocuje výsledek callbacku pomocí `out.get("success", True)`; callback vracející slovník chyb bez explicitního klíče `success` je považován za úspěšný a odemkne navazující závislé kroky.
3. **T21 (Vysoká — Test Verification):** `affected_tests()` vyřadí nekompatibilní frameworky (např. TypeScript testy v polyglot repozitáři), ale ponechá `selection_complete=True` a vysokou spolehlivost; `patch_and_verify` tak může ohlásit kompletní verifikaci, ačkoliv relevantní testy neproběhly.

---

## 2. Přehled nálezů (T01–T21)

| ID | Komponenta | Popis zjištění | Závažnost | Stav v kódu |
|:---|:---|:---|:---:|:---:|
| **T01** | Agent Semaphores | Dva procesy mohou současně získat jediný slot (`DEFERRED` SQLite read-modify-write) | 🔴 Kritická | Potvrzeno (`agent_semaphores.py:78,95`) |
| **T02** | Agent Semaphores | Čekací fronta nevynucuje FIFO; staré položky v queue zůstávají po přímém zisku | 🟠 Vysoká | Potvrzeno (`agent_semaphores.py:115–195`) |
| **T03** | Blackboard CRDT | Merge může snížit lokální CAS verzi sekce pod vlivem dominujícího remote clock | 🟠 Vysoká | Potvrzeno (`agent_blackboard.py:110–155`) |
| **T04** | Blackboard Events | Opakovaný merge může vyvolat konflikt v event logu místo čistě idempotentního replay | 🟡 Střední | Upřesněno (striktní idempotence zachycena) |
| **T05** | Preprocess Write Actor | Timeout čekatele nezastaví plánovaný/běžící zápis; volající nezná stav | 🟠 Vysoká | Potvrzeno (`preprocess_write_actor.py:submit`) |
| **T06** | Preprocess Write Actor | Neodchycená fatální chyba workera zanechá čekající Futures viset v neomezené frontě | 🟠 Vysoká | Potvrzeno (`preprocess_write_actor.py:_worker`) |
| **T07** | Preprocess Write Actor | Batch fallback opakuje operace, jejichž in-memory vedlejší efekty rollback nestornoval | 🟡 Střední | Potvrzeno (`preprocess_write_actor.py:batch`) |
| **T08** | Test Command Builder | Generované příkazy neodpovídají CLI syntaxi runnerů (Rust cargo targety, Go packages, .NET FQN) | 🟠 Vysoká | Potvrzeno (`test_selection.py:affected_test_command`) |
| **T09** | Swarm DAG | Chybový slovník bez klíče `success` je považován za úspěšný krok DAGu | 🟠 Vysoká | Potvrzeno (`swarm.py:1103–1104`) |
| **T10** | Session Briefing | `isinstance(t, dict)` na objektech `TaskState` způsobí, že briefing vrátí prázdné aktivní úlohy | 🟠 Vysoká | Potvrzeno (`agent_board.py:282`) |
| **T11** | Agent Semaphores | `release()` ověřuje pouze `lease_id`, nikoliv zda volající odpovídá evidovanému `owner` | 🟠 Vysoká | Potvrzeno (`agent_semaphores.py:218`) |
| **T12** | Agent Semaphores | Čekatel se neprobudí po expiraci TTL drženého slotu bez explicitního release eventu | 🟡 Střední | Potvrzeno (`agent_semaphores.py:wait_for_event`) |
| **T13** | Blackboard CRDT | Vítězný stav při dominanci clocku neoprávněně přebírá maximální timestamp poraženého | 🟡 Střední | Potvrzeno (`agent_blackboard.py:merge_sections`) |
| **T14** | Blackboard CRDT | `merge()` nevaliduje rovnost mezi klíčem mapy a vnitřním atributem `section` | 🟡 Střední | Potvrzeno (`agent_blackboard.py:merge`) |
| **T15** | Durable PubSub | `poll()` v durable režimu ignoruje parametr `since_timestamp` a čte jen podle `after_seq` | 🟡 Střední | Potvrzeno (`agent_events.py:poll`) |
| **T16** | Tool Agent | 1s timeout `/api/show` přepne agenta do beznástrojového režimu bez označení degradace | 🟡 Střední | Potvrzeno (`tool_agent.py:230–245`) |
| **T17** | OpenCode Router | Při překročení limitu velikosti odpovědi vrátí klientovi HTTP 200 a uřízne tělo | 🟡 Střední | Potvrzeno (`opencode_local_router.py:84–162`) |
| **T18** | Source Slice | U prázdného souboru (`total_lines=0`) neproběhne validace požadovaného řádku | 🟢 Nízká | Potvrzeno (`source_slice.py:19–130`) |
| **T19** | Preprocess Write Actor | `stop()` s timeoutem nezajistí zastavení workera; následný submit přejde na souběžný přímý zápis | 🟠 Vysoká | Potvrzeno (`preprocess_write_actor.py:stop`) |
| **T20** | Test Matrix | Chybí adaptér pro PHP a PHPUnit/Pest (`composer.json`, `phpunit.xml`, `*Test.php`) | 🟠 Vysoká | Potvrzeno (`deterministic.py`, `test_selection.py`) |
| **T21** | Test Verification | Vyloučení nekompatibilních runnerů nesnižuje `selection_complete`; hrozí falešná kompletnost | 🟠 Vysoká | Potvrzeno (`deterministic.py:5554`, `commands.py`) |

---

## 3. Podrobný rozbor prioritních vad

### T01: Race condition v `SemaphoreStore.acquire()`
- **Mechanismus:** Kód volá `with self._lock:` (což chrání pouze vlákna uvnitř jednoho Python procesu). Následně otevírá SQLite transakci přes standardní `with con:`, což v Python `sqlite3` implicitně provádí `BEGIN DEFERRED`. Čtení `SELECT capacity, holders_json` proběhne ve sdíleném režimu. Dva procesy A a B současně přečtou prázdný seznam držitelů, oba vyhodnotí `len(active_holders) < effective_capacity`, oba vygenerují nový `lease_id` a zapíší. Poslední zápis přepíše předchozí, ale oba procesy obdrží `acquired=True`.
- **Dopad:** Přetížení GPU slotů, kolize zápisů na soubory, narušení exkluzivity agentních smluv.
- **Náprava:** Použít explicitní `con.execute("BEGIN IMMEDIATE")` před prvním SELECTem stavu semaforu. Ošetřit `sqlite3.OperationalError` (database locked) s bounded exponential backoff retry.

### T09: Falešný úspěch v `execute_swarm_dag()`
- **Mechanismus:** 
  ```python
  if callable(fn):
      out = fn()
      success = True
      if isinstance(out, dict):
          success = out.get("success", True) is True
  ```
- **Dopad:** Pokud krok vrátí `{"error": "Dependency resolution failed", "status": "failed"}`, kód vyhodnotí `success = True`, zařadí krok do `completed_steps` a spustí na něm závislé implementační či testovací kroky.
- **Náprava:** U slovníkových návratových hodnot striktně vyžadovat přítomnost klíče `"success"`:
  ```python
  if isinstance(out, dict):
      if "success" not in out:
          success = False
      else:
          success = out["success"] is True
  ```

### T10: Výpadek úloh v `BoardStore.session_briefing()`
- **Mechanismus:** Metoda volá `active = self.services.task_store.list_tasks(status=None, limit=5)`. Následně filtruje:
  ```python
  [... for t in active if isinstance(t, dict) and t.get("status") in {...}]
  ```
  Objekty vrácené z `TaskStore.list_tasks()` jsou dataclassy `TaskState`, nikoliv primitivní slovníky. Podmínka `isinstance(t, dict)` je pro každou položku vyhodnocena jako `False`.
- **Dopad:** Session briefing pro startující agenty je permanentně bez aktivních úloh. Navíc chybí vazba na konkrétní `repository_id` / `root`.
- **Náprava:** Převod na `t.to_dict()` nebo přímé čtení atributů (`t.task_id`, `t.status`, `t.contract.goal`) a filtrování podle aktuálního kořene projektu.

### T11: Absentující kontrola vlastníka v `SemaphoreStore.release()`
- **Mechanismus:** V `release(name, lease_id, owner="")` se prochází seznam držitelů a hledá se pouze shoda na `lease_id`. Předaný parametr `owner` je použit pouze pro pročištění čekací fronty `wait_queue`.
- **Dopad:** Libovolný proces či agent, který zná nebo odhadne `lease_id`, může uvolnit zámek jiného vlastníka.
- **Náprava:** Uvolnit držitele pouze tehdy, když `h.get("lease_id") == lease_id and (not owner or h.get("owner") == owner)`. Pokud je `owner` známou identitou volajícího, vynucovat striktní shodu.

### T21: Falešně kompletní verifikace v polyglot projektech
- **Mechanismus:** `affected_tests()` vyvolá `compatible_tests()`, která vybere testy pro primární framework (např. Python) a ostatní odloží do `incompatible_tests`. Do výsledku vrátí pouze kompatibilní testy, ale ponechá:
  ```python
  "selection_complete": graph_complete,
  "confidence": 0.95 if matched_tests else 0.5,
  ```
  V `patch_and_verify` se při `selection_complete=True` a `confidence >= 0.95` spustí pouze Python runner a po jeho úspěchu se vytvoří verification receipt, ačkoliv frontendové TypeScript testy neproběhly.
- **Dopad:** Agent se spolehne na to, že změna prošla kompletní sadou testů, ačkoliv polovina relevantních testů nebyla vůbec spuštěna.
- **Náprava:** Zavést vícerunnerový kontrakt. Pokud existují `incompatible_tests` nebo chybí runner, `selection_complete` MUSÍ být `False` a výsledek musí obsahovat `requires_multiple_runners: True`.

---

## 4. Balíčky implementačních prací (Work Packages)

Práce jsou seřazeny podle kritičnosti pro správnost a bezpečnost systému:

```
┌────────────────────────────────────────────────────────┐
│ WP1: Atomické semafory & kontrola vlastníků (T01, T11) │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│ WP2: Swarm DAG exaktní kontrakt výsledků (T09)         │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│ WP3: Session Briefing oprava typů a filtru (T10)       │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│ WP4: Blackboard CAS revize a ochrana timestampů (T03,13│
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│ WP5: Polyglot Test Selection & Verification (T21, T08) │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│ WP6: Preprocess Write Actor životní cyklus (T05,6,7,19)│
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│ WP7: Semaphore TTL Expirace a PubSub probouzení (T12)  │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│ WP8: PHP / PHPUnit / Pest test adaptér (T20)           │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│ WP9: Tool Capability Cache & Degradation (T16)         │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│ WP10: Transport & Boundary Hardening (T14, 15, 17, 18) │
└────────────────────────────────────────────────────────┘
```

### Specifikace balíčků:

1. **WP1 — Atomic Semaphores (`src/local_ai_hub/agent_semaphores.py`)**
   - Transakce `BEGIN IMMEDIATE` pro všechny read-modify-write operace (`acquire`, `release`, `prune`).
   - Validace identity vlastníka (`owner`) při uvolnění lease.
   - Odstranění držitele z wait fronty při úspěšném přímém zisku.
   - *Kritérium přijetí:* Stresový test se 4 nezávislými procesy soutěžícími o semafor s kapacitou 1 nikdy nevrátí 2 souběžné aktivní držitele.

2. **WP2 — Swarm DAG Result Contracts (`src/local_ai_hub/swarm.py`)**
   - Striktní validace výsledku callbacku.
   - Zákaz implicitního `True` pro slovníkové odpovědi; chybějící `success` nebo přítomnost `error` musí vést k `success=False`.
   - *Kritérium přijetí:* Krok vracející `{"error": "fatal"}` skončí ve stavu failed a jeho závislé kroky se nespustí.

3. **WP3 — Session Briefing Correctness (`src/local_ai_hub/agent_board.py`)**
   - Podpora objektů `TaskState` i případných slovníků.
   - Restrikce seznamu úloh na aktuální projektový kontext (`repository_id` / `root`).
   - *Kritérium přijetí:* Volání `session_briefing()` vrátí v `active_tasks` existující rozpracované úlohy daného projektu.

4. **WP4 — Blackboard CAS Monotonicity & Timestamps (`src/local_ai_hub/agent_blackboard.py`)**
   - Oddělení lokální CAS revize (`version`) od logického vector clocku.
   - Výsledná lokální verze musí být vždy `max(local_ver, remote_ver) + 1`.
   - LWW timestamp se přebírá výhradně od dominující varianty obsahu.
   - Validace shody názvu sekce na vstupu s vnitřním payloadem.
   - *Kritérium přijetí:* Merge s vyšším vector clockem, ale nižší verzí nikdy nesníží lokální `version`.

5. **WP5 — Polyglot Test Selection & Verification Completeness (`src/local_ai_hub/deterministic.py`, `src/local_ai_hub/commands.py`)**
   - Rozdělení dotčených testů podle frameworků (`pytest`, `vitest`, `cargo`, apod.).
   - `selection_complete=True` povoleno pouze při plném pokrytí všech detekovaných dotčených testů.
   - Zajištění správné syntaxe testovacích příkazů pro Rust, Go a .NET.
   - *Kritérium přijetí:* Změna zasahující Python i TypeScript kód neoznačí verifikaci za kompletní, pokud proběhl pouze pytest.

6. **WP6 — Preprocess Write Actor Resilience (`src/local_ai_hub/preprocess_write_actor.py`)**
   - Explicitní stavový automat (`STARTING`, `RUNNING`, `DRAINING`, `STOPPED`, `FAILED`).
   - Při pádu workera označit všechny čekající `Future` výjimkou `WorkerDiedError`.
   - Timeout čekatele nesmí ponechat volajícího v nejistotě — zrušení neprovedené úlohy z fronty nebo návrat `outcome_unknown`.
   - *Kritérium přijetí:* Simulovaný crash writera deterministicky probudí všechny čekající požadavky s chybovým stavem.

7. **WP7 — Semaphore TTL Expirations & Wakeup (`src/local_ai_hub/agent_semaphores.py`, `src/local_ai_hub/agent_events.py`)**
   - Čekací smyčka nesmí spoléhat výhradně na pubsub event `released`.
   - Pravidelný periodický re-check odvozený od nejbližšího `expires_at` aktivních držitelů.
   - *Kritérium přijetí:* Po uplynutí TTL slotu se čekající agent probudí a získá slot i bez volání `release()`.

8. **WP8 — PHP / PHPUnit / Pest adaptér (`src/local_ai_hub/deterministic.py`, `src/local_ai_hub/test_selection.py`)**
   - Detekce PHP projektů podle `composer.json`, `phpunit.xml`, `phpunit.xml.dist`.
   - Vyhledávání testů v `tests/` a podpora konvencí `*Test.php`.
   - *Kritérium přijetí:* Deterministický engine v CakePHP/Laravel fixture repozitáři správně identifikuje testy a runner.

9. **WP9 — Tool Capability Caching & Safe Degradation (`src/local_ai_hub/tool_agent.py`)**
   - Perzistentní/verzovaná cache schopností modelů.
   - Přechodné selhání metadat (timeout 1.0s) nesmí trvale vypnout nástroje; explicitní stav `capability_probe_timeout`.
   - *Kritérium přijetí:* Pomalá odpověď `/api/show` nesníží agenta do beznástrojového režimu, pokud je model ověřen jako tool-capable.

10. **WP10 — Transport & Boundary Hardening (`src/local_ai_hub/opencode_local_router.py`, `src/local_ai_hub/source_slice.py`, `src/local_ai_hub/agent_events.py`)**
    - Router: Vrátit HTTP 502 / error payload před streamováním, pokud `Content-Length > 64MB`.
    - Source slice: Korektní odmítnutí dotazu na neexistující řádky i u prázdného souboru (`total_lines=0`).
    - Durable pubsub: Konzistentní chování parametru `since_timestamp`.
    - *Kritérium přijetí:* Požadavek na řádek 10 prázdného souboru vrátí explicitní chybu mimo rozsah.

---

## 5. Povinné regresní scénáře

Pro akceptaci oprav je navržena tato sada 7 cílených testovacích scénářů:

1. `test_concurrent_multiprocess_semaphore_acquire`: Dva nezávislé procesy spuštěné přes `multiprocessing` volají `acquire()` na semafor s kapacitou 1 ve stejný okamžik. Přesně jeden proces smí získat `acquired=True`.
2. `test_swarm_dag_unspecified_dict_error_fails`: Callback vracející `{"error": "something broke"}` musí označit krok jako neúspěšný a zabránit spuštění navazujících závislostí.
3. `test_session_briefing_returns_task_state_objects`: Uložení reálného `TaskState` do úložiště a ověření, že `session_briefing(root=...)` vrátí odpovídající záznam v `active_tasks`.
4. `test_blackboard_crdt_monotonic_cas_version`: Vzdálená sekce s vyšším vector clockem a nižší verzí (např. remote clock 10, version 2 vs local clock 2, version 8) musí po merge vyústit v lokální verzi >= 9.
5. `test_polyglot_verification_refuses_partial_complete`: Testovací repozitář obsahující Python i TypeScript soubory nesmí po spuštění samotného pytestu vrátit `selection_complete=True`.
6. `test_preprocess_writer_worker_crash_drains_futures`: Vynucená výjimka ve vlákně workera musí okamžitě dokončit všechny čekající požadavky s chybou `WorkerDiedError`.
7. `test_semaphore_auto_wakeup_on_ttl_expiry`: Čekatel na semaforu s TTL 0.2s se musí úspěšně probudit a získat uvolněný slot, i když držitel nepublikoval žádný release event.

---

## 6. Doporučení k architektuře: Sjednocený operační kontrakt

Pro eliminaci rozptýlených ad-hoc kontraktů úspěchu napříč Hubem se doporučuje sjednotit stavový model do standardizované datové struktury:

```python
@dataclass(frozen=True)
class OperationContract:
    outcome: Literal["succeeded", "failed", "cancelled", "outcome_unknown"]
    execution_state: Literal["not_started", "running", "settled"]
    idempotency_key: str
    attempt_id: str
    owner_id: str
    retryable: bool
    side_effects_confirmed: bool
    # Pole pro verifikaci a testy:
    verification_complete: bool = False
    tests_executed: int = 0
    coverage_incomplete: bool = False
```

Zavedení tohoto jednotného kontraktu zajistí, že žádná komponenta nebude zaměňovat dílčí úspěch za kompletní hotovou práci.
