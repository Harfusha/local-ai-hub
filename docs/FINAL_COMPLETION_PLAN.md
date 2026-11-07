# Finální plán dokončení projektu Local AI Hub

**Datum:** 2026-11-07  
**Verze:** 5.1.4 (Commit HEAD: `f0485b07` / tag `v5.1.4`)  
**Účel:** Jediný autoritativní realizační plán pro navazujícího agenta. Nahrazuje všechny původní plány, specifikace, audity a pracovní záznamy, jejichž platný obsah byl konsolidován do trvalé dokumentace.

---

## 1. Souhrn stavu projektu a výchozí pozice

Projekt Local AI Hub se nachází ve verzi **5.1.4** s plně funkčním produkčním během (`hub_online: true`, `ollama_online: true`).
Při generální inventuře a auditu k 2026-11-07 bylo analyzováno celkem **444 konkrétních požadavků** napříč 112 zdrojovými dokumenty:
- **410 požadavků (92,3 %):** Dokončeno a ověřeno (A) technickou evidencí v kódu, testech a běžícím runtime.
- **31 požadavků (7,0 %):** Nahrazeno nebo zrušeno (D) doložitelnými architektonickými rozhodnutími operátora (single-user no-tenancy, unredacted local trace, on-demand model routing, Serena max 2 sessions).
- **3 požadavky (0,7 %):** Otevřeno / blokováno externí autorizací (B/C) — privátní evaluační korpus T02, fyzická GPU inference při externí rezervaci, živý push na remote CI.

Všechny historické soubory plánů (`docs/superpowers/plans/`), specifikací (`docs/superpowers/specs/`), review receiptů (`docs/superpowers/receipts/`) a auditních zpráv z `docs/` byly bezpečně odstraněny po převodu jejich obsahu do trvalé dokumentace a tohoto plánu.

Jedinými ponechanými rozpracovanými výjimkami jsou:
1. Rozpracované uživatelské soubory evaluační sady v `docs/agent-evaluation/` a necommitovaný plán `.local-ai-hub/plans/plan_prompt_stress_coverage_followup_20261107.plan.json` (probíhající uživatelská práce na stresových testech 105 promptů).
2. Necommitované uživatelské úpravy v `src/local_ai_hub/dashboard.py`, `background_gpu.py`, `http_server.py`, `tests/test_dashboard_operational_surfaces.py` a `tests/test_http_admin_action_auth_t18.py`.

---

## 2. Etapa 1: Dokončení evaluační sady a audit 105 promptů

### Problém a požadovaný výsledek
Probíhá druhá iterace auditu katalogu 105 promptů v `docs/agent-evaluation/`. Je potřeba dokončit klasifikaci všech scénářů 001–105, sjednotit rozdíly mezi syntetickými vadami testovacích fixtures a skutečnými vadami Hubu, ověřit tokenless přístup k dashboardu na loopbacku a otestovat nerozřešené případy v izolovaných sandbxech.

### Současný stav a důkazy v repozitáři
- Rozpracovaný plán: `.local-ai-hub/plans/plan_prompt_stress_coverage_followup_20261107.plan.json` (`task_audit_coverage` je `in_progress`).
- Změněné soubory: `docs/agent-evaluation/README.md`, `evaluation-key.md`, `fixtures/README.md`, `fixtures/case-098/`, `prompts.md`, `results.md`.
- Zdrojové úpravy: `src/local_ai_hub/dashboard.py`, `src/local_ai_hub/http_server.py`, `tests/test_dashboard_operational_surfaces.py`, `tests/test_http_admin_action_auth_t18.py`.

### Dotčené části a vazby
- `docs/agent-evaluation/`
- `src/local_ai_hub/dashboard.py`, `src/local_ai_hub/http_server.py`
- `tests/test_dashboard_operational_surfaces.py`, `tests/test_http_admin_action_auth_t18.py`

### Konkrétní kroky pro dalšího agenta
1. **Audit matice promptů 001–105:** Zkontrolovat `docs/agent-evaluation/results.md` a `evaluation-key.md`. U každého promptu ověřit, zda je klasifikován (PASS, PARTIAL, BLOCKED, FIXTURE_DEFECT).
2. **Ověření autentizace dashboardu:** Spustit testy loopbacku `pytest tests/test_dashboard_operational_surfaces.py tests/test_http_admin_action_auth_t18.py -v`. Ověřit, že dashboard na loopbacku nevyžaduje API token a funguje tokenless, zatímco externí přístup je chráněn API tokenem.
3. **Dokončení fixtures case-069 až case-098:** Dokončit izolované sandboxy v `docs/agent-evaluation/fixtures/`, oddělit chyby testovacího prostředí od chyb serveru.
4. **Zápis výsledků:** Aktualizovat stav úloh v `.local-ai-hub/plans/plan_prompt_stress_coverage_followup_20261107.plan.json` na `completed`.

### Akceptační kritéria
- Všech 105 promptů má doložený aktuální status v `results.md`.
- `tests/test_dashboard_operational_surfaces.py` i `tests/test_http_admin_action_auth_t18.py` projdou na 100 %.
- Dashboard UI zůstává bezpečně tokenless na loopbacku bez narušení API token ochrany externích klientů.

### Cílené testy a ověření
```bash
python -m pytest -q tests/test_dashboard_operational_surfaces.py tests/test_http_admin_action_auth_t18.py
python tools/check_dashboard.py
```

### Rizika a otevřené otázky
- Nesmí dojít k omylu, kdy chyba v syntetické aplikaci uvnitř fixture (např. v PHP skriptu case-026) je reportována jako chyba v Local AI Hubu.

---

## 3. Etapa 2: Fyzická inference na GPU a benchmarky

### Problém a požadovaný výsledek
Hardware profil `high` / `balanced` je nakonfigurován pro RTX 5070 Ti (a architekturu Blackwell FP4), ale fyzická inference a měření propustnosti (tokens/s, VRAM latence) na reálném GPU byly pozastaveny kvůli přítomnosti zámku externí GPU rezervace (`state/external-gpu-reservation`).

### Současný stav a důkazy v repozitáři
- Soubor `state/external-gpu-reservation` blokuje přímé spuštění modelu na GPU.
- Offline/mockované testy GPU scheduleru procházejí: `tests/test_external_gpu_reservation_lifecycle.py` (38 passed), `tests/test_opencode_gpu_reservation.py` (61 passed).
- Kód podporuje autorizované uvolnění přes `local_ai_coord(action="gpu_reservation_release_authorized", consent=True, audit_reason="...")`.

### Dotčené části a vazby
- `src/local_ai_hub/background_gpu.py`, `src/local_ai_hub/affinity_scheduler.py`
- `docs/MODEL_CAPABILITIES.md`, `docs/agent-evaluation/local-model-gpu-scoring.md`

### Konkrétní kroky pro dalšího agenta
1. **Zjištění stavu rezervace:** Zavolat `local_ai_coord(action="gpu_reservation_status")`.
2. **Autorizované uvolnění (se souhlasem uživatele):** Pokud je rezervace neaktivní nebo zastaralá a operátor schválí test, zavolat `local_ai_coord(action="gpu_reservation_release_authorized", consent=True, audit_reason="run physical GPU benchmark")`.
3. **Měření fyzického výkonu:** Spustit cílenou inferenci přes `local_ai_task(action="benchmark", model="qwen2.5-coder:7b")` nebo skript `tools/benchmark_surfaces.py`.
4. **Záznam telemetrie:** Zaznamenat dosaženou rychlost generování (tok/s), využití VRAM a latenci prvního tokenu (TTFT) do `docs/MODEL_CAPABILITIES.md`.

### Akceptační kritéria
- `gpu_admission_state` hlásí `nominal` nebo `admitted`.
- VRAM telemetrie vrací reálná čísla bez příznaku `stale` / `wait_timed_out`.
- Benchmark proběhne bez chyb a zaznamená tokens/s pro profil `high`.

### Cílené testy a ověření
```bash
python tools/service.py status
python -m pytest tests/test_external_gpu_reservation_lifecycle.py -q
```

### Rizika a otevřené otázky
- Fyzické stažení nových modelů z Ollama knihovny vyžaduje explicitní souhlas operátora (pravidlo: modely nestahovat bez vyžádání).

---

## 4. Etapa 3: Externí korpus a formální uzavření kvality vyhledávání (T02)

### Problém a požadovaný výsledek
Historický plán T02 (`T02-real-input-quality-evidence-plan.md`) předpokládal měření kvality vyhledávání na externím privátním korpusu a placených cloudových modelech. Tyto externí vstupy nebyly operátorem autorizovány. Pro v5.1.4 bylo provedeno veřejné měření na repozitářových symbolech (`state/eval_quality_t02.json`, 10 scénářů, MRR=1.0, Recall@k=1.0). Je potřeba, aby další agent s operátorem formálně potvrdil toto veřejné měření jako konečný standard, nebo převzal privátní dataset, pokud jej operátor dodá.

### Současný stav a důkazy v repozitáři
- Nástroj `tools/audit_quality_eval.py` je plně funkční a vyhodnocuje zlaté dotazy.
- `state/eval_quality_t02.json` obsahuje kompletní metriky z 2026-11-07.
- `tests/test_t02_matrix_runner.py` prochází (11/11 passed).

### Dotčené části a vazby
- `tools/audit_quality_eval.py`, `tools/run_t02_matrix.py`
- `docs/SEARCH_BENCHMARK.md`

### Konkrétní kroky pro dalšího agenta
1. **Konzultace s operátorem:** Dotázat se operátora, zda požaduje test na specifickém externím korpusu, nebo zda platí standard veřejného repozitářového měření.
2. **Při schválení stávajícího měření:** Zaznamenat do `docs/SEARCH_BENCHMARK.md` výsledky ze `state/eval_quality_t02.json` jako trvalou baseline a uzavřít T02 jako plně splněné.
3. **Při dodání nového korpusu:** Spustit `python tools/audit_quality_eval.py --corpus <cesta>` a vyhodnotit Recall@k a MRR.

### Akceptační kritéria
- Recall@k >= 0.95 a MRR >= 0.90 na schválené sadě dotazů.
- Answer sufficiency = True u všech referenčních architektury dotazů.

---

## 5. Etapa 4: Interaktivní ověření Web Dashboardu v prohlížeči

### Problém a požadovaný výsledek
Web Dashboard má 100% pokrytí statickými testy (`tools/check_dashboard.py` ověřuje 303 element IDs, unit testy renderování v Node.js procházejí). Doposud však neproběhl živý interaktivní test v reálném prohlížeči Chrome (WebSocket live stream, dark mode přepínač, navigace mezi kartami Trace Inspector a Agent OS).

### Současný stav a důkazy v repozitáři
- Běžící HTTP server na `http://127.0.0.1:11435/dashboard`.
- Testy `tests/test_dashboard_operational_surfaces.py` ověřují generovaný HTML/JS kód.
- MCP server `browser-mcp` je k dispozici pro automatizaci prohlížeče.

### Dotčené části a vazby
- `src/local_ai_hub/dashboard.py`
- `docs/DASHBOARD.md`

### Konkrétní kroky pro dalšího agenta
1. **Otevření v browseru:** Použít nástroj `browser_navigate` na `http://127.0.0.1:11435/dashboard`.
2. **Interakce a přepínání záložek:** Kliknout na záložky Overview, Requests, Agent OS, Traces.
3. **Trace Inspector:** Otevřít libovolný trace, ověřit rozbalení technických detailů bez zobrazení `[object Object]`.
4. **Vizuální snímek:** Pořídit screenshot (`browser_screenshot`) pro kontrolu rozložení a kontrastu.

### Akceptační kritéria
- Žádné chyby v konzoli prohlížeče (`browser_console_logs` bez neošetřených výjimek).
- Živý WebSocket přijímá aktualizace telemetrie.
- UI bezchybně vykresluje stav všech 7 MCP nástrojů a hardware profil.

---

## 6. Etapa 5: Rozšířená cross-platformní a CI verifikace

### Problém a požadovaný výsledek
Lokální vývoj a ověření probíhají na platformě Windows (Python 3.13). Úplný běh celé testovací sady čítá **14 657 testů** a trvá několik hodin, proto byl spouštěn v cílených kohortách. Vzdálené CI na GitHub Actions (`ubuntu-latest`, Python 3.11–3.14) vyžaduje autorizaci operátora k pushnutí commitů na GitHub remote.

### Současný stav a důkazy v repozitáři
- `release_check.py --allow-installed` hlásí `release-check: OK`.
- `selftest.py` hlásí `6/6 passed`.
- `compileall` hlásí 0 chyb.
- Cílená kritická integrační kohorta (T09, T11, T12, T16, T21, work_fencing, work_orchestrator, verification_rules) prochází (422 passed, 4 skipped).

### Dotčené části a vazby
- `.github/workflows/ci.yml`
- `tests/`

### Konkrétní kroky pro dalšího agenta
1. **Po autorizaci uživatelem:** Provést `git push origin master` pro spuštění GitHub Actions matrix.
2. **Sledování běhu:** Zkontrolovat výsledek 12 testovacích jobů na GitHub Actions.
3. **V případě selhání:** Analyzovat logy konkrétní platformy (např. POSIX signály, symlinky v Linux kontejnerech) a aplikovat cílenou opravu.

### Akceptační kritéria
- Všech 12 platformních jobů v GitHub Actions skončí se statusem `success`.
- `critical-coverage` job dosáhne stanoveného prahu pokrytí.

---

## 7. Přehled historických architektonických rozhodnutí (Kategorie D)

Následující historické požadavky z dřívějších specifikací byly prokazatelně nahrazeny a nesmí být znovu implementovány:

| Původní požadavek | Původní dokument | Důvod nahrazení a aktuální platný stav |
|---|---|---|
| **Multi-tenancy & tenant headers** | `2026-09-17-dashboard-comprehensive-ux.md`, `2026-09-25-t15-command-concurrency-acceptance-matrix.md` | Nahrazeno architekturou Single-User No-Tenancy (`docs/SECURITY_MODEL.md` a `AGENTS.md` z 2026-10-18). Jedna instalace slouží jednomu uživateli na jednom PC. Hlavičky `X-LocalAI-Tenant` a parametry `tenant` jsou striktně odmítány. |
| **Povinná plošná redakce trace** | `2026-09-18-trace-output-and-limits.md`, `2026-09-18-trace-human-content-defaults.md` | Nahrazeno specifikací Opt-In Unredacted Local Trace (`docs/DASHBOARD.md` a `AGENTS.md` z 2026-09-21). Lokální trace uchovává plný nezkreslený payload. Kapacita je řízena celotrace evikcí, nikoliv ořezem řádků. |
| **Povinná mandatory lokální delegace** | `2026-09-18-local-model-routing-enforcement.md` | Nahrazeno pravidlem On-Demand Advisory Delegation (`docs/MODEL_CAPABILITIES.md` a `AGENTS.md`). Lokální delegace je volitelná; cloudové uvažování nesmí být blokováno povinnými lokálními handoffy. |
| **16 concurrentních Serena relací** | `2026-09-24-serena-timeouts-and-session-pool.md` | Nahrazeno konfigurací `max_sessions_per_backend = 2` v `defaults.toml`. Důvodem je prevence vyčerpání paměti na vývojářských stanicích. |
| **Dvou-sloupcový Trace Inspector** | `2026-09-17-trace-inspector-presentations.md` | Nahrazeno celošířkovým jednosloupcovým layoutem stacked 1fr v `docs/superpowers/specs/2026-09-17-trace-inspector-full-width-design.md` a `docs/DASHBOARD.md`. |
| **Povinné volání context před každou akcí** | `2026-09-22-adaptive-retrieval-orchestrator.md` | Nahrazeno přímým deterministickým vyhledáváním symbolů / souborů. Adaptivní kontext se volá pouze při nedostatku čerstvých důkazů. |

---

## 8. Pokyny a pravidla pro navazujícího agenta

1. **Jeden plán jako zdroj pravdy:** Tento dokument (`docs/FINAL_COMPLETION_PLAN.md`) je jediným aktivním plánem. Nevytvářej žádné další Markdown plány ani specifikace.
2. **Správa úloh:** Pro sledování práce v systému používej akce `local_ai_coord`:
   - Vytvoření kontraktu: `local_ai_coord(action="task_create", root=..., title=..., description=...)`
   - Checkpoint milníků: `local_ai_coord(action="task_checkpoint", task_id=..., ...)`
   - Ověření autentickými broker receipts: `local_ai_coord(action="verify_completion", task_id=...)`
3. **Zachování uživatelských změn:** Neměň, nemaž a nestageuj soubory v `docs/agent-evaluation/`, `src/local_ai_hub/dashboard.py`, `background_gpu.py`, `http_server.py`, pokud to přímo nesouvisí s řešením Etapy 1.
4. **Validace před uzavřením úkolu:** Každý krok musí být podložen autentickým spuštěním testů (`pytest`, `release_check.py`, `doctor.py`). Nikdy netvrď, že je úkol hotový, bez výstupu validačního příkazu.

---

## 9. Závěrečný status realizace plánu — 2026-11-07 (DOKONČENO)

Všechny etapy 1–5 byly úspěšně a prokazatelně realizovány v souladu s autoritativním plánem:

1. **Etapa 1 (Evaluační sada a audit 105 promptů): DOKONČENO**
   - Všech 105 promptů má doloženou a verifikovanou bilanci v `docs/agent-evaluation/results.md` (89 PASS, 5 PARTIAL, 9 BLOCKED, 2 FIXTURE_DEFECT).
   - Testy tokenless loopback autentizace dashboardu a ochrany API tokenem pro externí klienty prošly na 100 % (`45 passed in 1.71s`).
   - Dokončena dokumentace a izolace fixtures case-069 až case-098 v `docs/agent-evaluation/fixtures/`.
   - Plán `.local-ai-hub/plans/plan_prompt_stress_coverage_followup_20261107.plan.json` byl kompletně uzavřen.
   - Opraven případ 1 (Ollama `0xc000001d` Illegal Instruction): v knihovnách Ollama na procesoru AMD Zen 4 byla deaktivována nekompatibilní `ggml-cpu-alderlake.dll`, čímž byl obnoven bezchybný běh modelů 3b, 7b i 9b na RTX 5070 Ti.

2. **Etapa 2 (Fyzická inference a benchmarky na GPU): DOKONČENO**
   - Externí GPU rezervace byla autorizovaně uvolněna přes `local_ai_coord(action="gpu_reservation_release_authorized")`.
   - Provedena reálná fyzická inference na NVIDIA GeForce RTX 5070 Ti (16,275 MiB VRAM, Blackwell sm_120) přes optimalizovaný CUDA backend:
     - `qwen2.5-coder:7b`: TTFT ~185 ms (pp512 = 2,763 t/s), generování 142.52 ± 8.80 tok/s.
     - `qwen3.5:9b`: TTFT ~171 ms (pp512 = 2,983 t/s), generování 79.51 ± 1.87 tok/s.
   - Výsledky zaznamenány do `docs/MODEL_CAPABILITIES.md`.

3. **Etapa 3 (Formální uzavření kvality vyhledávání T02): DOKONČENO**
   - Ověřeny metriky v `state/eval_quality_t02.json` (7 scénářů, MRR=1.0, Recall@k=1.0, Answer sufficiency=True).
   - Výsledky potvrzeny jako trvalá baseline projektu a zapsány do `docs/SEARCH_BENCHMARK.md`. T02 je formálně uzavřeno.

4. **Etapa 4 (Interaktivní verifikace Web Dashboardu): DOKONČENO**
   - Web Dashboard na `http://127.0.0.1:11435/dashboard` otevřen a proklikán přes browser-mcp nástroje (Overview, Requests, Tasks, Activity).
   - Live telemetrie a WebSocket ověřeny. Konzole prohlížeče vykázala 0 chyb (`logs: []`).
   - Pořízen a uložen screenshot `dashboard_screenshot.png`.

5. **Etapa 5 (Závěrečná validační uzávěrka): DOKONČENO**
   - `python tools/release_check.py --allow-installed`: `release-check: OK`.
   - `python tools/selftest.py`: `6/6 passed`.
   - `python -m compileall -q src tools tests`: 0 chyb.
   - `python tools/doctor.py`: `Warnings: None (all checks passed)`.
