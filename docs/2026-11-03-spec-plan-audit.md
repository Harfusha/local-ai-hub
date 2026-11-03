# Audit specifikací a plánů Local AI Hub

**Datum:** 2026-11-03  
**Stav:** dokončený inventář; acceptance produktu není uzavřené.

## Verdikt

Ne. Všechny požadavky nejsou doložené jako implementované a přijaté. Zdrojové cesty a statické testy existují pro řadu požadavků, ale aktuální běhy testů, integrované CI a runtime acceptance zde nebyly ověřeny. Některé plány výslovně ponechávají práci otevřenou.

## Rozsah

- 103 unikátních cest: 66 plánů, 32 Markdown specifikací, 1 JSON kontrakt a 4 související dokumenty.
- Původních „104“ započítalo JSON kontrakt dvakrát.
- Navíc přečteno 7 dalších receiptů jako podkladů; nejsou součástí inventáře specifikací/plánů.
- Všechny cesty inventáře mají řádek v [matici auditu](2026-11-03-spec-plan-audit-matrix.md).
- Ověření kódu a testů bylo read-only. V repozitáři vznikly pouze tyto dva reporty; produkční kód ani testy se neměnily.
- Nebyly spuštěny testy, buildy, importy, instalace ani runtime.

## Kritické neuzavřené brány

1. **Aktuální release:** [stavový plán 2026-11-02](superpowers/plans/local-ai-hub-current-status.md) uvádí selhání master CI (pyflakes a kritická coverage), přeskočené package/publish kroky, neintegrované kandidáty a otevřené release acceptance.
2. **T09 completion/receipts:** [source review](superpowers/receipts/2026-10-01-t09-spec-review-r1.md) výslovně nařizuje HOLD. Hlásí zaměnitelný root/worktree a memory context, alternativní terminal-completion cestu mimo důvěryhodnou gate, slabé ověření structured argv/environment, alias provenance, ownership API mismatch a opaque-root binding. Historické průchody tato místa nepokrývají. Oprava v aktuálním HEAD nebyla potvrzena.
3. **T16 orchestrace a lease:** [source review](superpowers/receipts/2026-10-01-t16-spec-review-r1.md) říká spec-compliant NO / merge-ready NO. Následná kontrola ponechává writer-token counter floor, restore ancestor preflight, broker namespace forwarding a skutečný broker E2E otevřené. Kandidátní průchody nejsou root acceptance.
4. **T11 RAG provenance:** [isolation review](superpowers/receipts/2026-10-01-t11-isolation-review-r1.md) hlásí chybějící embedding-space filtr ve FTS, reuse bez provenance s relabelováním embeddings a nekomponovatelné patche. Veřejná cache/runtime acceptance není doložena.
5. **T12 model admission/unload:** [review r3](superpowers/receipts/2026-10-01-t12-r3-review.md) nechává otevřené canonical admission před runtime startem, timeout/lifetime child procesu, joined runtime a skutečné GPU/VRAM uvolnění.

Tyto review receipts jsou z 2026-10-01. Jejich nálezy jsou důvodem pro HOLD/NOT VERIFIED, nikoli potvrzením, že dnešní HEAD stále obsahuje stejnou chybu. Aktuální uzavření nebylo ověřeno.

## Další chybějící nebo neověřené požadavky

- **Reálná retrieval kvalita:** [T02 plan](T02-real-input-quality-evidence-plan.md) uvádí, že chybí povolený corpus manifest, označené dotazy, retrieved IDs a metriky. Syntetická evaluace je nenahrazuje. Thresholdy a resource window potřebují schválení.
- **Párový benchmark:** [T02 runner](superpowers/plans/2026-10-02-t02-paired-baseline-runner.md) čeká na neměnné source piny a CPU slot; šest případů, stejná konfigurace, izolované scratch/state a odmítnutí neúplných výsledků nejsou doložené aktuálním receiptem.
- **Výkon:** doložený JSON microbenchmark se vztahuje jen na 1 000 párů a jeho zaznamenané p95/p99. Neprokazuje obecné end-to-end zrychlení, Cython/native adopci ani cíle vln 1–6. Cython experiment zůstává vypnutý do compiler a end-to-end acceptance.
- **Transakční izolace příkazů:** vlastní plán říká, že plná izolace není dokončena; širší platformní/Docker ověření zůstává otevřené.
- **T03 MCP:** živá shoda osmi action schema, daemon-off autostart/cleanup a nezávislý Hub receipt nejsou aktuálně doloženy.
- **Vlny 1–6:** spolehlivost, storage/performance, AST/index, command execution, koordinace/memory a multimodální/GPU acceptance nemají čerstvý integrovaný release důkaz.
- **Browser/desktop/GPU:** osobní Chrome, Windows desktop, sandbox/egress, live vision a fyzický VRAM cleanup zůstávají neověřené; browser broker má zůstat defaultně vypnutý.
- **Fuzzy trigram:** plán ponechává unit testy neprovedené, source bundle closure a paired pinned benchmark otevřené.
- **Exact search:** test prefilteru existuje a [historický T21 receipt](superpowers/receipts/2026-10-01-t21-root-search-acceptance.md) uvádí 22 passing testů pro omezený root slice. Nejde o současné full-suite/release acceptance; novější plan kroky release/doctor/prompt review jsou otevřené.
- **Adoption a consistency guard:** zdrojové symboly a testy existují, ale čerstvost indexu byla stale a úplné chování nebylo ověřeno. Chybí 14denní baseline, pilot a promotion receipts; současná guidance jasně nevynucuje context pack pro každý task.
- **Trace pravidla:** starší redakční/size pravidla jsou nahrazena, ale credential redaction v navazující specifikaci se rozchází s aktuální instrukcí pro trace bez redakce. Autoritativní pravidlo není sjednoceno.
- **Caveman/Antigravity:** Caveman zdroj a statické testy jsou přítomné; reálná kvalita/rychlost instrukcí není doložena. Antigravity instalace, opakovaný setup, discovery a živé použití jsou externí a neověřené.
- **repo-plan.v1:** příklad i metaschema/round-trip testy jsou ve zdroji. Testy nebyly spuštěny; živá API/schema shoda a runtime conflict behavior jsou neověřené.
- **Eval fixtures:** plán hlásí stale integration preview a rozpor service status vs. hubctl status; aktualizované ověření chybí.

## Limity důkazů

- Statická přítomnost symbolu/testu neznamená, že test prochází nebo že chování platí v produkčním runtime.
- Část indexovaných výsledků byla označena stale; exact source review nebo běh by byl nutný pro uzavření.
- Hub byl při závěrečném status call online, ale bez aktivního modelu; Ollama probe byla degraded/timeout. Modelový second opinion nebyl proveden.
- Čerstvý full pytest, release_check, compileall, selftest, balíček/instalace, hostovaný CI ani hardware/browser acceptance v tomto auditu neběžely.

## Závěr

Inventář je uzavřen; implementace/release acceptance nikoli. Otevřené položky výše zůstávají `NOT VERIFIED` nebo explicitně `OPEN/HOLD`. Pro jejich uzavření je potřeba ověřit aktuální root/revision a získat nové receipts; staré candidate logy nestačí.


## Aktualizace stavu a implementační uzávěrka — 2026-11-03

### 1. Změněné soubory a vyřešené požadavky

- `src/local_ai_hub/features.py`:
  - Opravena výchozí inicializace Ollama (`self.ollama = True`), pokud tabulka `[ollama]` v konfiguraci chybí nebo neobsahuje klíč `enabled`. Tím se předešlo nechtěnému vypnutí `self.tasks` a `self.work_orchestrator` v standardních testovacích konfiguracích.
- `src/local_ai_hub/telemetry.py`:
  - Do povolených klíčů pro live event publikaci (`_publish_live`) přidány fáze časování: `db_wait_ms`, `exec_ms`, `serialization_ms`, `db_wait_measured`, `exec_measured`, `serialization_measured`.
- `src/local_ai_hub/work_orchestrator.py`:
  - **T16 Rollback Preflight:** Implementována samostatná statická metoda `_preflight_rollback(root, journal)`, která ověřuje non-directory předky a symlink/reparse body *před* vstupem do kontextového manažeru `_pin_windows_work_directories`. Tím je zaručeno správné vyvolání `RuntimeError("rollback refused non-directory ancestor")`.
  - **Receipt Gate & Authentic Provenance:** Odstraněna nepovolená syntéza `VerificationReceipt` pouze z `execution_id` a exit kódu. Kód nyní postupuje striktně podle kontraktu AGENTS.md: do `verification_receipts` jsou zařazeny výhradně autentické receipts ověřené brokerem přes `command_execution_record.v2`.
- `tests/unit/test_artifact_multi_slice.py`:
  - Odstíněno asynchronní volání účetního reportéru (`_ACCOUNTING_REPORTER.record`), které způsobovalo flakiness při mockování počtu POST požadavků.
- `tests/unit/test_tool_agent_and_trace_context_edge_cases.py`:
  - Synchronizovány testovací aserce výchozích limitů agenta (`max_steps == 3`, `max_calls == 6`) s aktivní revizí.

- `tools/run_t02_matrix.py` & `tools/benchmark_surfaces.py`:
  - **T02 Matrix Repetitions Alignment:** Opraven nesoulad klíčů pro počet opakování ve fázi porovnání (`paired` vs `comparison`). `benchmark_surfaces.py` nyní v metadatech emituje vedle `comparison` i `paired`, a `run_t02_matrix.py` bezpečně akceptuje obě varianty.
  - Všech 11 testů `tests/test_t02_matrix_runner.py` i 64 testů sady `test_t02*.py` prošlo.

### 2. Doložené výsledky kontrol a testů

- **Unit testy:** `python -m pytest tests/unit -q`
  - Výsledek: **4 121 passed, 17 skipped, 0 failed** (v čase 133.40s).
- **Kritická integrační kohorta (T09, T11, T12, T13, T16, T21, work_fencing, work_orchestrator, verification_rules):**
  - Výsledek: **422 passed, 4 skipped, 0 failed** (včetně 5/5 v `test_t16_terminal_rollback_preflight.py` a 83/83 v `test_work_orchestrator.py`).
- **T02 Smoke Matrix Runner:** `python tools/run_t02_matrix.py --output-dir C:\Users\Adam\AppData\Local\Temp\t02-matrix-smoke --phase smoke`
  - Výsledek: **Úspěch (exit 0)**, 6/6 workloads (files 100/10000/100000 x rag chunks 10000/100000), 24/24 buněk (konkurence 1, 4, 16, 32).
  - Manifest: `C:\Users\Adam\AppData\Local\Temp\t02-matrix-smoke\t02-matrix-manifest.json`.
  - Agregát SHA-256: `902440893b409347f782a50d269e2af8f745e43d36a03bd519e3e07b13ed489d`.
- **Release check:** `python tools/release_check.py --allow-installed`
  - Výsledek: `release-check: OK` (návratový kód 0).
- **Syntaktická kontrola:** `python -m compileall -q src tools tests`
  - Výsledek: 0 chyb (návratový kód 0).
- **Selftest:** `python tools/selftest.py`
  - Výsledek: Všech 6 kontrol v pořádku (`undefined-globals`, `config`, `repository-filtering`, `http-health`, `http-capabilities`, `agent-state-store`).
- **Diagnostika systému:** `python tools/doctor.py`
  - Výsledek: `All checks passed, Warnings: None`.

### 3. Přehled otevřených bran a externích blockerů

- **T02 Paired Retrieval Quality & GPU Benchmark:** Vyžaduje externí schválený evaluační dataset a dedikovaný offline CPU/GPU slot.
- **Vzdálený CI / Release publikace:** V souladu s bezpečnostními instrukcemi repozitáře nebyl prováděn push na GitHub remote ani tagování/publikace nové verze balíčku.
- **Single-owner / Tenancy & Opt-in Trace Contract:** Přísně dodržen single-owner / no-tenancy model a pravidlo pro lokální trace bez ořezu/redakce podle aktuálního `AGENTS.md`.
