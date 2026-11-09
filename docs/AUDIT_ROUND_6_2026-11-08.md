# Local AI Hub — Šesté kolo hloubkového auditu & Nápravný plán

**Datum:** 8. listopadu 2026  
**Cílová revize:** `master` · Commit `2176b0e210cbd64fb2260f721f8546d5365b463f`  
**Hub Plan ID:** `plan_audit_round6_fixes_20261108`  
**Paměťový záznam:** `mem_520a37051b2e`

---

## 1. Manažerské shrnutí

Šesté kolo hloubkového auditu se zaměřilo zejména na víceagentní pipeline, převzetí rozpracovaných úloh, verifikační artefakty, provozní izolaci GPU a scheduleru a řízení automatizovaných operací.

Všech 14 nových zjištění (C01–C14) bylo přímo ověřeno a potvrzeno ve zdrojovém kódu na commitu `2176b0e`.

### Klíčové kritické nálezy (Top priority):
1. **C04 (P0-A — GPU lease lifecycle & OpenCode heartbeat):** Nesoulad mezi `ExternalGpuReservationStore` (TTL 60s) a `ExternalInferenceSession` (heartbeat delay `min(idle_timeout/3, 300)` = 300s). Během inference i idle stavu lease po 60s vyprší a `scheduler.reap_expired()` uvolní GPU jinému procesu, což ničí exkluzivitu GPU a vede ke kolizím.
2. **C01 & C05 (P0-B — Proof immutability & Execution Record Integrity při adopci úloh):** `TaskStore.claim()` volá `_rebind_verification_receipts_owner()`, které přímo přepisuje JSON proof v databázi artefaktů (`UPDATE artifacts SET text = ?`) pod stejným `artifact_id`, čímž rozbíjí content-addressed identitu `art_HASH(text)`. Navíc přepočet `record_sha256` v execution recordu neodstraní starý hash před výpočtem, což selhává při kontrole v `commands.py`.
3. **C02 & C03 (P1-A — Pipeline stage contracts & confidence gate):** V `pipeline.py` selhání povinného criticu v režimu `quality` nevede k chybě ani degradaci, ale pipeline vrátí `success: True` a `degraded: False`. V adaptivním režimu navíc explorer může přeskočit worker i critic pouze na základě vlastního self-reported `confidence >= 0.85` a `missing_evidence: []` bez deterministických důkazů.
4. **C06 & C07 (P1-B — Preprocessing fallback error persistence & schema validation):** Dočasná chyba generování souborové nebo modulové karty zapíše náhradní kartu (`fallback-error`) a nastaví `card_key` nebo `revision_hash`. Další běh tyto soubory/moduly přeskočí a chyba zůstane trvalá. `BackgroundGPUWorker._generate_one()` navíc vrací `success: True` i při výjimce `json.loads` nebo nevalidním schématu.
5. **C12 (P1-C — Background GPU CPU offload admission):** Pokud `loaded_model_details()` neobsahuje požadovaný model, kontrola CPU offloadu se přeskočí a session se bez ověření schválí.

---

## 2. Přehled nálezů (C01–C14)

| ID | Komponenta | Popis zjištění | Priorita | Umístění v kódu |
|:---|:---|:---|:---:|:---|
| **C01** | Agent Tasks / Artifacts | Převzetí úlohy mění text v content-addressed artefaktu pod původním ID | 🔴 P0 | `agent_tasks.py:2779-2820`, `artifacts.py:149-167` |
| **C02** | Pipeline | Selhání povinného criticu v režimu quality vrátí `success: True`, `degraded: False` | 🔴 P1 | `pipeline.py:514-550` |
| **C03** | Pipeline | Explorer přeskočí worker i critic pouze na základě self-reported confidence | 🔴 P1 | `pipeline.py:367-380` |
| **C04** | GPU / OpenCode Session | GPU lease (TTL 60s) vyprší dříve než heartbeat (300s); absence idle keepalive | 🔴 P0 | `external_gpu_reservation.py:37`, `opencode_inference_session.py:59`, `scheduler.py:1050` |
| **C05** | Agent Tasks / Commands | Přepočet `record_sha256` při adopci neodstraní starý hash, selhává validace | 🔴 P0 | `agent_tasks.py:2824-2838`, `commands.py:3895-3898` |
| **C06** | Preprocessing | Dočasná chyba vytvoří fallback kartu a nastaví `card_key`, brání budoucímu retry | 🔴 P1 | `preprocess.py:4116, 4430-4434, 4537-4541` |
| **C07** | Background GPU | `_generate_one` označí neparsovatelný nebo nevalidní JSON jako `success: True` | 🔴 P1 | `background_gpu.py:398-405` |
| **C08** | Autotune / Services | Tuner observe počítá neúspěšné pokusy a timeouty do latence a tps | 🟡 P2 | `autotune.py:141-177`, `services.py:1880-1886` |
| **C09** | Automation | Pomalý start/cleanup backendu drží globální `self.lock` a blokuje ostatní sessions | 🟡 P2 | `automation.py:162-168, 242-252` |
| **C10** | Negative Knowledge | `find_negative_knowledge` načítá všechny incidenty repozitáře bez SQL limitu | 🟡 P2 | `agent_incidents.py:1358-1384` |
| **C11** | Static Exports | PHP/C# export validator neověřuje přítomnost symbolu `name` v souboru | 🟡 P2 | `static_exports.py:102-114` |
| **C12** | Background GPU | Chybějící model v `loaded_model_details()` obejde kontrolu CPU offloadu | 🔴 P1 | `background_gpu.py:213-225` |
| **C13** | Task Search Index | `_backfill_task_search_index` při startu rekurzivně reindexuje všechny nezměněné tasky | 🟡 P2 | `agent_tasks.py:1911-1930` |
| **C14** | Benchmarks | `_persist_record` provádí neatomický read-modify-write bez zámku souboru | 🟡 P2 | `benchmark.py:1104-1118` |

---

## 3. Implementační a testovací plán

1. **P0-A (C04, T6-01, T6-02):**
   - V `opencode_inference_session.py` navázat heartbeat timer na skutečný TTL rezervace: interval = `min(ttl / 3, 20.0)`.
   - Zajistit keepalive nejen během aktivního požadavku, ale i ve stavu `IDLE_RESERVED` až do uplynutí `idle_timeout_seconds` nebo zavření session.
   - Otestovat konkurenční schedulery a zabránit uvolnění aktivní i idle rezervace.

2. **P0-B (C01, C05, T6-03, T6-04):**
   - Odstranit destruktivní mutaci `_rebind_verification_receipts_owner()` v `agent_tasks.py`. Původní artefakty a execution records zůstávají neměnné.
   - Zaznamenat adopci v task eventech a umožnit ověřovacímu kontroleru (`_receipt_evidence_matches`) akceptovat původní důkazy vytvořené předchozím autorizovaným vlastníkem daného tasku.
   - Opravit integritu execution record hashování.

3. **P1-A (C02, C03, T6-05, T6-06):**
   - V `pipeline.py` při selhání criticu v režimu `quality` nevracet `degraded: False` a `success: True`. Vrátit `degraded: True` / `verification_incomplete: True` nebo chybový stav podle přísnosti.
   - Při rozhodování o přeskočení workeru v adaptivním režimu vyžadovat doložená fakta (evidence IDs / context tokens) a neukončovat práci pouze ze self-reported confidence.

4. **P1-B (C06, C07, T6-07, T6-08):**
   - V `preprocess.py` nezapisovat fallback karty jako definitivní hotové karty (`card_key IS NULL` zachovat pro retry, případně zavést retry plánování).
   - V `background_gpu.py` validovat JSON a schema. Při chybě vrátit `success: False` s popisem chyby.

5. **P1-C (C12, T6-09):**
   - V `background_gpu.py` vyžadovat nalezení modelu v `loaded_model_details()`; pokud chybí, nepovažovat residency za schválenou.

6. **P2 (C08, C09, C10, C11, C13, C14, T6-10 až T6-14):**
   - C08: Tuner observe provádět pouze při `success == True`, případně trackovat chyby odděleně.
   - C09: V `automation.py` vytvoření backendu a `close()` provádět mimo globální zámek `self.lock`.
   - C10: V `agent_incidents.py` přidat SQL candidate limit a FTS/lexikální ořez.
   - C11: V `static_exports.py` pro PHP/C# doplnit kontrolu deklarace `name`.
   - C13: V `agent_tasks.py` startup backfill optimalizovat pomocí kontroly digestu / generace dokumentu.
   - C14: V `benchmark.py` použít atomický zápis přes dočasný soubor se zámkem.
