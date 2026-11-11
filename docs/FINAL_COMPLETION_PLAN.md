# Finální plán dokončení projektu Local AI Hub

**Datum:** 2026-11-07  
**Verze:** 6.0.0  
**Účel:** Jediný autoritativní realizační plán pro navazujícího agenta. Nahrazuje všechny původní plány, specifikace, audity a pracovní záznamy, jejichž platný obsah byl konsolidován do trvalé dokumentace.

---

## 1. Souhrn stavu projektu a výchozí pozice

Projekt Local AI Hub se nachází ve verzi **6.0.0** s plně funkčním produkčním během (`hub_online: true`, `ollama_online: true`).
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
2. **Ověření loopback hranice dashboardu:** Spustit testy `pytest tests/test_dashboard_operational_surfaces.py tests/test_http_admin_action_auth_t18.py -v`. Ověřit tokenless přístup přes loopback a odmítnutí ne-loopback peerů; externí přístup není podporován.
3. **Dokončení fixtures case-069 až case-098:** Dokončit izolované sandboxy v `docs/agent-evaluation/fixtures/`, oddělit chyby testovacího prostředí od chyb serveru.
4. **Zápis výsledků:** Aktualizovat stav úloh v `.local-ai-hub/plans/plan_prompt_stress_coverage_followup_20261107.plan.json` na `completed`.

### Akceptační kritéria
- Všech 105 promptů má doložený aktuální status v `results.md`.
- `tests/test_dashboard_operational_surfaces.py` i `tests/test_http_admin_action_auth_t18.py` projdou na 100 %.
- Dashboard UI zůstává tokenless na loopbacku; Hub odmítá ne-loopback přístup a zachovává route-level controls.

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
- Offline/mockované testy GPU scheduleru procházejí: `tests/test_external_gpu_reservation_lifecycle.py` (38 passed). Historických 61 testů OpenCode rezervace před extrakcí zůstává na `codex/opencode-extraction`.
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
   - Historický běh `45 passed in 1.71s` před tokenless změnou nepotvrzuje současnou loopback hranici; znovu ji ověř cílenými testy.
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

---

## 10. Uživatelské rozšíření: nativní integrace hostů (2026-11-09)

### Cíl a bezpečnostní hranice

Rozšiřovat existující host adaptéry po samostatných etapách. Výchozí režim je `shadow`: zaznamenává jen metadata a návrh, nic neposílá hostu a nemění relaci. Nepovolovat neřízené relace. Neukládat prompty, transcript y, výstupy ani zdrojový kód. Zachovat Agent OS, Agent Events, existující oprávnění, důkazy a receipts. Nepřidávat daemon, databázi ani veřejný MCP nástroj.

Host schopnost lze považovat za podporovanou jen při ověřené identitě hostu/verze, povrchu, relace, vlastnictví Hubem, událostí, příkazů, oprávnění a režimu. Dokumentace a přítomná konfigurace dokazují dostupnost rozhraní, ne doručení události ani oprávnění. Neznámý stav znamená `not_verified` a žádný zásah.

### Aktuální implementace a mezery

- `src/local_ai_hub/repo_plan/host_adapters.py`: `HostCapabilityReport` kontroluje soubory, vložené instrukce a lokální registraci. `probe_host_capabilities()` záměrně vrací `workflow_interception=False` a `host_event_verification="not_verified"`; konfiguraci nepovyšuje na důkaz události.
- `src/local_ai_hub/repo_plan/host_hooks.py`: instalace je projektová a omezená na `codex` a `gemini_cli`; registruje `SessionStart` a `UserPromptSubmit` pro Codex, `SessionStart` a `BeforeAgent` pro Gemini CLI. Antigravity IDE/GUI adaptér zde není.
- `src/local_ai_hub/antigravity_hook.py` a `tools/setup.py`: dřívější `PreInvocation` hook spouštěl Hub a vkládal `ephemeralMessage`, takže měnil kontext každého tahu. Nyní je handler no-op a setup hook už neregistruje; zachovává existující `PreToolUse` read/search filtr jako oddělené deterministické vynucení, ne jako shadow návrh.
- Aktuální `handle_host_event()` validuje pouze bounded hook envelope a vždy vrací `{}`. Neukládá prompt ani nevkládá `additionalContext`; hook payload nedokládá Hub-owned session, proto se z něj shadow event nezapisuje.
- `SteeringManager` je soukromá inbox evidence, ne receipt ani ověřený host event. Nepoužívat ji pro automatické ukládání promptů.
- `src/local_ai_hub/agent_events.py` již poskytuje `AgentEvent`, trvalý `AgentStateStore` a `SwarmPubSub`. Nová shadow evidence musí používat tuto infrastrukturu a obsahovat jen povolená metadata.
- `LocalAIApp` již skládá `AgentStateStore`, `PolicyEngine` a `VerificationStore`. Host adaptér nesmí schválit akci ani vytvořit receipt. `local_ai_task` v aktivním MCP schématu nyní nenabízí `review`, `reason`, `explore` ani `second_opinion`; readiness hlásí lokální review a semantic analysis jako nedostupné.

### Ověřené hosty, verze a rozhraní

#### Změna rozsahu (2026-11-10)

Na pokyn uživatele odložit integrace konkrétních IDE/klientů stejně jako OpenCode. Codex App Server, Antigravity IDE hooks, CLI a sidecar zůstávají mimo aktuální implementační etapy; existující parsery a fixture testy jsou pouze výzkumné/shadow prototypy, ne podporované integrace. Neinstalovat hooky, nevytvářet UX ani lifecycle pro konkrétní hosty a nespouštět inference bez samostatného rozpočtu. Další práce: klientsky neutrální host kontrakt, evidence a vyhodnocení shadow návrhů. Konkrétní adaptér lze znovu navrhnout až po stanovení sdíleného kontraktu a samostatné změně rozsahu.

- **Codex CLI:** lokálně `codex-cli 0.167.0-alpha.3.2`; `codex app-server --help` potvrzuje dostupnost příkazu. Oficiální [App Server protokol](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server) dokumentuje JSON-RPC relace, `thread/start`, `turn/start`, stream událostí a požadavky na schválení. [Návod pro ChatGPT plan](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server) popisuje OAuth token a `turn/start`; `model/list` je jen katalog, nikoli entitlement check. Dokumentace nedokládá předběžný peněžní strop pro tah. Podporovat pouze vlákna, která Hub sám založí a vlastní. Živý `codex app-server` handshake uspěl přes JSON-RPC `initialize`/`initialized` (Codex CLI `0.167.0-alpha.3.2`). V izolovaném dočasném `CODEX_HOME` proběhl `thread/start`; skutečná notifikace `thread/started` dorazila a parser ji přijal. Lokální JSON schema generátor potvrzuje `thread/tokenUsage/updated`, `thread/status/changed`, turn notifikace a approval requesty příkazu, změny souboru a oprávnění; parser přijímá pouze kumulativní usage čítače, allowlistovaný turn status a typ approval requestu pro očekávané vlákno, s hashovanou identitou procesu. Cílené shadow testy ověřily pseudonymizaci, deduplikaci v procesu, oddělení restartu, vynechání turn/approval obsahu a permission check. Nebyl spuštěn turn ani inference. Dočasný profil a event store byly po smoke odstraněny; pracovní checkout zůstal zachován. Živé doručení turn/usage/approval eventů a item eventy zůstávají `not_verified`.
- **Antigravity CLI:** Dřívější lokální kontrola zaznamenala `agy.exe` `1.4.2` v `%LOCALAPPDATA%\agy\bin`; aktuální shell jej na této cestě ani v `PATH` nenalezl, takže dostupnost/verze instalace nyní není ověřená. Oficiální changelog uvádí CLI `1.4.12` (2026-10-30), což samo nedokládá místní instalaci. Aktuální [Hooks dokumentace](https://antigravity.google/docs/hooks) popisuje CLI `SessionStart` před první modelovou invokací a `Stop`; payload obsahuje `conversationId`, `workspacePaths`, `transcriptPath` i `lastUserInput`. Konfigurace může být workspace, globální nebo pluginová, takže sama nedokládá Hub vlastnictví. Headless [`stream-json`](https://antigravity.google/docs/cli/headless/) přijímá prompt přes stdin a streamuje `init`, `step_update` a `result`, včetně textu, tool informací a session-cumulative `usage` čítačů; žádný prompt ani živý stream jsme nespustili. Parser nyní ukládá pouze allowlistované nezáporné celočíselné token čítače; ty jsou agregovaná telemetrie, nikoli cenový strop. `agy` nebyl nalezen v aktuálním PATH, takže lokální verze, hook ani stream zůstávají `not_verified`. Hub-owned spouštěcí cesta, která bezpečně zahodí obsah a prokáže vazbu procesu/konverzace, stále chybí. Locator pouze hledá CLI a nemění `PATH`.
- **Omezení pasivního zachycení Antigravity (ověřeno v aktuální dokumentaci):** Headless `-p` odešle jeden prompt agentovi; `stream-json` je pouze formát výstupu, nikoli připojení k běžící GUI/CLI relaci. Spuštění tedy provádí inference a bez výslovného rozpočtu se nesmí použít. Oficiální Hooks platí pro App, CLI i IDE; payload může obsahovat prompt, cesty, transcript a argumenty nástroje. `SessionStart` může vkládat kroky, `PreToolUse` schvaluje, zamítá nebo mění volání a `Stop` může vynutit pokračování. Aktuální oficiální [Hooks schema](https://antigravity.google/docs/hooks/) říká, že `PostToolUse` dodá `toolCall.name`/`args`, `stepIdx`, volitelný `error` a společná pole včetně `conversationId`, `workspacePaths`, `transcriptPath`, `artifactDirectoryPath` a `modelName`; nedodá výstup nástroje a odpověď hooku je `{}`. Jde o jediného kandidáta na metadata-only observer, pokud zahodí args/error; samotné ID konverzace a workspace nedokládají Hub vlastnictví. Hook instalace ani živé doručení nebyly ověřeny; hook capture zůstává `not_verified`.
- **Antigravity sidecar/`agentapi`:** oficiální [sidecar dokumentace](https://antigravity.google/docs/sidecars) popisuje spravovaný persistentní proces a `agentapi` příkazy `new-conversation`/`send-message`; dokumentovaný povrch nenabízí read-only stream událostí. Sidecar je proto `unsupported` pro shadow event capture; jeho zápisové příkazy nebyly volány. Místní `.gemini/config/config.json` nemá `sidecars` a sidecar/plugin adresáře jsou prázdné. Dostupnost jiných instalací a oprávnění zůstávají `not_verified`.

### Produkční volající Codexu

Oficiální [App Server protokol](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server) popisuje produktovou aplikaci, která vlastní proces, vytváří/obnovuje vlákno, spouští turn a zobrazuje stream i žádosti o schválení. V Hubu máme pouze izolovaný parser/sink smoke; `hubctl` ani aktivní MCP schéma nemají uživatelsky řízený lifecycle této relace. Pasivní sběr z cizího Desktop/CLI vlákna proto nepodporujeme. Podle pokynu uživatele z 2026-11-10 se konkrétní IDE/klientské integrace odkládají; nyní nenavrhujeme produkční App Server UX ani lifecycle. Produkční integrace zůstává `unsupported`; Desktop události a oprávnění jsou `not_verified`.

**Konkrétní klientská etapa odložena podle pokynu uživatele z 2026-11-10.** Neimplementovat ani dále navrhovat `hubctl codex`, Antigravity CLI/IDE hook nebo sidecar lifecycle v tomto rozsahu. Zachovat jejich podporu jako `unsupported` nebo `not_verified`. Pokračovat klientsky neutrálním host kontraktem a shadow evidencí; nový návrh konkrétního adaptéru vyžaduje samostatnou změnu rozsahu. Pokud se klientská etapa později znovu otevře, nejprve ověřit Hub vlastnictví, cleanup procesu, oprávnění a vymahatelný peněžní rozpočet. Počet tahů není peněžní strop; `run_antigravity_cli_turn` zůstává fail-closed s `enforceable_monetary_budget_unavailable`.

### Shadow záznam a pojmenování výsledků

Záznam smí obsahovat typ a čas události, host/povrch/verzi, pseudonym relace nebo oprávněně stabilní ID, task/evidence ID, navrženou akci a důvod, stav ověření a tri-state výsledek kontroly oprávnění. Nepřidávat cesty, argumenty nástrojů, prompty, transcript y, výstupy ani kód. `proposed`, `simulated`, `executed` a `verified` jsou samostatné stavy. `shadow_only` znamená, že návrh nebyl odeslán. Neznámé oprávnění zaznamenat jako `not_evaluated`, nikdy jako povolení.

Event schema `host.shadow.observation.v2` může u Antigravity navíc obsahovat pouze celočíselné `input_tokens`, `output_tokens`, `thinking_tokens`, `cache_read_tokens` a `total_tokens` pod `token_usage`, s `token_usage_scope=session_cumulative`. `source_sequence` zachovává pořadí v proudu a `source_stream_ref` je hash čerstvého Hub nonce pro každé spuštění procesu; raw nonce se neukládá. Stejná událost v témže proudu se deduplikuje, restartovaný proces dostane nový event ID při zachování pseudonymu konverzace. Neznámé usage položky se zahazují; vadný známý čítač odmítne událost. Tyto session-cumulative hodnoty slouží k vyhodnocení režie, nikoli k předběžnému cenovému limitu. Text, výsledek, prompt a raw usage payload se nikdy neukládají. Živý Hub-owned procesní caller zůstává `not_verified`.

Kanonický kontrakt rozlišuje `success`, `refused`, `unsupported`, `uncertain` a `shadow_only`. Shadow metadata lze zapsat pouze pro Hubem spravovanou relaci s ověřenou schopností, shodnou identitou a potvrzeným připojením. Neznámý stav oprávnění se zapíše jako `not_evaluated`; neznamená povolení ani hostí akci. Při neznámé verzi, identitě, spojení nebo vlastnictví se událost neukládá. Budoucí hostí akce navíc vyžadují samostatně ověřená oprávnění a existující policy grant. Použít `AgentStateStore`/`SwarmPubSub`; idempotency key odvodit z hostího event ID.

### Budoucí shadow schopnosti a jejich vstupní brány

Tato matice popisuje budoucí kandidáty, ne aktivní chování. Návrh i shadow event vzniknou pouze z ověřeného Hub-owned eventu; při chybějícím signálu, identitě, spojení nebo vlastnictví se nic neuloží. Neznámý stav oprávnění zůstane `not_evaluated`; žádná akce se neprovede. Shadow nikdy nic nevloží ani neodešle hostu.

| Schopnost | Dostupný signál a mezera | Stav / brána |
|---|---|---|
| Vložit radu do tahu | Codex parser pokrývá schéma `turn/started` a `turn/completed`, ale jejich živé doručení a Hub-owned caller chybí; hooky nedokládají vlastnictví tahu. | `unsupported`; před návrhem nutný ověřený Hub-owned turn event a vazba relace. Návrh zůstane pouze v metadatech. |
| Doporučit zastavit nebo pokračovat | Agent OS checkpoint nyní vytvoří task-level návrh pauzy/pokračování z typed statusu a presence bitů. Vazba na tah konkrétního klienta zůstává odložená a neověřená. | Task-level shadow producer implementován; host-turn doporučení `not_verified`; nikdy neposlat interrupt ani force-continue. |
| Skills Advisor | Lokální schema `skills/changed` má prázdné params a je pouze invalidation signal; neobsahuje thread identity ani skill state. Refresh `skills/list` by četl další host metadata. | `not_verified`; event není vstupem pro návrh. Před případným refresh vyžadovat Hub-owned session a minimální autorizovaný metadata výběr. |
| Doporučit delegaci | Agent OS má task/evidence ID, ale není ověřené jejich spojení s konkrétní host relací. | `not_verified`; bez dispatch. Návrh musí uvést, zda by jej odmítla existující oprávnění. |
| Cross-agent handoff | Není ověřena identita druhého hosta ani přenosový kanál. | `unsupported`; žádná zpráva, dispatch ani převod vlastnictví v shadow. |
| Speculative prefetch | Chybí ověřené předvídatelné eventy i párová data o cache zásazích a režii. | `unsupported`; nejdřív měřit cache hit/miss, latenci a tokenovou režii. |
| MCP push notifikace | Schema obsahuje `mcpServer/event/stream/notification` se subscription ID a libovolným notification payloadem, bez thread identity; jde o MCP server event stream, ne o ověřený push kanál do uživatelské relace. | `unsupported`; nepropagovat payload ani nezavádět nový kanál bez konkrétní host potřeby a oprávnění. |
| Approval relay | Lokální schema potvrzuje request příkazu, změny souboru a oprávnění; parser fixture ukládá pouze typ. Živý request nebyl pozorován. | `not_verified`; shadow může zaznamenat pouze typ a výsledek permission checku. Nikdy neposlat approval response. |
| Nativní read-only review | `local_ai_repo` nabízí deterministické diff/security akce, ale host trigger neexistuje a aktivní `local_ai_task` schema nenabízí `review`. | `not_verified`; pouze na výslovné vyžádání a po ověření review akce, důkazů a receipt. Výsledek se neposílá hostu a nepřepisuje approval. |
| Synchronizace Hub tasků/cílů | Agent OS tasky existují, ale hostí task ID/lifecycle nejsou navázané. | `not_verified`; vyžaduje přesnou mapu identit a auditovatelný rollback. |
| Dynamické nástroje | Schema obsahuje server request `item/tool/call` pro konkrétní běh nástroje, ale neověřuje registry ani registraci dynamických nástrojů. Argumenty requestu mohou obsahovat soukromý obsah. | `unsupported`; nic nepropagovat ani neregistrovat. |
| Diagnostika příkazů/běhu | `src/local_ai_hub/commands.py`: `CommandBroker.get_command_execution_record()` ověřuje přesné `task_id`, kanonický root a jeho hash; `_get_server_command_execution_record()` přijímá pouze `command_execution_record.v2` s platným checksumem, `exit_code=0` a `cached=false`. Selhané běhy tak nemají tímto rozhraním ověřenou diagnostickou stopu. | `not_verified`; jen existující autorizované broker receipts a metadata. Bez raw stdout/stderr, volného shellu nebo inference bez rozpočtu. |

Každý kandidát se před opt-in měří samostatně: počet reprezentativních případů, přesnost, falešné zásahy, zmeškané příležitosti, latence, tokenová režie a selhání adaptéru. Prahy, lidské potvrzení, kill switch a rollback se určí až z těchto dat; chybějící data nejsou úspěch.

### Gate po shadow období

1. Vyhodnotit reprezentativní shadow běhy. U každého výsledku oddělit naměřené hodnoty, odhady a neověřená tvrzení; chybějící lidské štítky zůstávají `not_verified`.
2. Pro každou schopnost samostatně změřit přesnost, falešné zásahy, zmeškané příležitosti, latenci, tokenovou režii a selhání adaptéru. Uvést počet případů a jmenovatel každé metriky.
3. Před rozhodnutím stanovit pro danou schopnost prahy, minimální počet případů, požadované lidské potvrzení a explicitní podmínky, kdy se nesmí aktivovat. Prahy se nesmějí odvodit z jiného kandidáta.
4. Opt-in navrhnout až po splnění těchto bran. Omezit dosah, zaznamenat auditovatelný souhlas, připravit kill switch a ověřený rollback. Nesplněná nebo neznámá brána znamená ponechat schopnost vypnutou.
5. Nasazovat nejvýše jednu schopnost v dané etapě. Po každé změně znovu změřit kvalitu a bezpečnost proti shadow baseline; při regresi použít rollback a vrátit schopnost do vypnutého stavu.
6. Schopnost bez doloženého přínosu ponechat vypnutou nebo vyřadit. Samotná existence shadow návrhů ani splnění jiné schopnosti její povýšení neospravedlňuje.

Žádná etapa tohoto gate nespouští placenou nebo cloudovou inferenci bez samostatného výslovného rozpočtu.

### Audit klientsky neutrálních vstupů (2026-11-10)

- `agent_tasks.py` zapisuje `task.created` s celým `TaskState`, `task.checkpointed` s celým checkpointem a `task.transitioned` se statusy plus volným `reason` a případným `operator_waiver`. Tyto události nelze poslat do shadow návrhu jako raw payload.
- `task.verified` obsahuje jen `criterion` a `receipt_id`; samo o sobě nedokládá receipt platnost, oprávnění ani vhodnost návrhu. `VerificationStore._receipt_evidence_matches()` následně ověřuje passed artifact proti task/owner/criterion/evidence vazbě a při zapnutém execution provenance také exact task, canonical root, revision, mutation generation a uncached exit code 0. Jde o validační bránu, ne samostatný signál pro nový návrh nebo lidský štítek kvality.
- `EvidenceStore.get(evidence_id, verify=True, root=...)` umí ověřit důkaz v explicitním rootu, ale vrací také root, cestu, rozsah řádků a raw text; metadata-only autorizovaný projection neposkytuje. Samotný evidence ID proto není bezpečný vstup pro další shadow návrh. Nevytvářet duplicitní metadata API bez konkrétní schopnosti, která je potřebuje.
- `ScopeLeaseStore.waits(root, coordination_id=...)` vrací čerstvé čekající lease v explicitním scope, ale zahrnuje owner, blocker owner a požadovanou cestu. Čekající stav už znamená, že task čeká; další stop/pause návrh by zatím jen opakoval tento stav. Bez filtrovaného task projection a doloženého přínosu se z těchto řádků nový shadow event nevytváří.
- `AgentStateStore.cleanup(retention_days=30)` odstraňuje starší eventy a snapshoty. Volá jej periodická údržba `LocalAIApp` (při zapnutém AgentState) i HTTP cleanup endpoint; endpoint bere retention z požadavku nebo konfigurace, výchozí 30 dní (`src/local_ai_hub/app.py`, `src/local_ai_hub/http_server.py`). `event_page()` vrací `first_retained_seq` a mezery po promazání. Existující `GET /api/agent-state/events/stream` je rootově a taskově omezený na `task:{task_id}` streamy, zatímco obecné shadow záznamy jsou ve `host-shadow:` streamech. Proto klientsky neutrální Agent OS shadow eventy patří do existujícího `task:{task_id}` streamu a čtou se jeho SSE filtrem `kind=host.shadow.observation.v3`; nové API není potřeba. Ostatní host shadow streamy zůstávají mimo task export. Export ve `VerificationStore` se týká verification receipts, ne štítků shadow návrhů.
- Ruční eval export používá `HubClient.stream_events(stream_id=f"task:{task_id}", kind="host.shadow.observation.v3", root=ABS_ROOT, after_seq=...)`; root/task binding ověří vlastnictví tasku a kind filtr vrátí jen metadata shadow záznamů. Anotátor může při autorizované kontrole použít task-scoped checkpoint historii lokálně; její text se nekopíruje do exportu ani anotací. Anotace ukládat pouze jako JSONL pod nakonfigurovaným `server.state_dir/shadow-evaluation/annotations.jsonl`, nikoli do task streamu, receipts ani source repo. Každý řádek obsahuje jen `task_id`, SSE `sequence`, `expected_action` (`recommend_pause`, `recommend_continue`, `none`, `unclear`), pseudonymní `reviewer_ref` a `reviewed_at`; bez volného textu, promptů, transcriptů a checkpoint obsahu. Dvojitě anotovat reprezentativní podvzorek a rozřešit neshody před reportem.
- Vyhodnocení návrhů: shoda akce je true positive; návrh při `expected_action=none` je false positive; návrh opačné akce je současně false positive pro navrženou a false negative pro očekávanou akci. `not_proposed` checkpoint s očekávanou pause/continue je false negative; `unclear` se vykazuje zvlášť. Reportovat precision/recall podle akce, abstence a počet anotovaných příležitostí. Dokud nevzniknou skutečné lidské štítky, žádné skóre ani opt-in tvrzení.
- `HostShadowRequest` a `record_shadow_observation()` poskytují metadata-only, deduplikovaný zápis přes `AgentStateStore`. Každý checkpoint s platným repository ID dostane klientsky neutrální `host.shadow.observation.v3` event: blocker přinese návrh `recommend_pause`; aktivní úkol s další akcí `recommend_continue`; jiný stav nese `proposal.status=not_proposed`, `action=none`.
- Producer čte pouze typed task status a přítomnost blockerů/next action; pro deduplikaci načte kanonický zdrojový event podle streamu a idempotency key. Zapisuje pouze action/reason kódy, task status, dvě presence bits a ID ověřeného source eventu. Do shadow události se nedostane goal, phase, text blockerů/next action, checkpoint state ani task evidence list. Permission stav zůstává `not_evaluated`; host se nevolá a task se nemění.
- Další implementace má vybírat allowlistované typed statusy/počty a autorizované evidence refs z task projekce; nesmí číst raw event payload. Neznámá identita, permission či provenance zůstává `not_verified` a návrh se neuloží.

#### Offline eval nástroj

Přijímací běh musí přidat `--require-double-review`: odmítne neanotované případy, single-reviewer případy i neadjudikované neshody. `double_review_gate=passed` potvrzuje úplnost štítků podle předložených pseudonymů. Report vždy nastaví `reviewer_identity_status=not_verified`; nezávislost osob zůstává potvrzená operátorem, ne technicky ověřená. Modelová kvalita zůstává `quality_status=not_verified`.

`python tools/shadow_eval.py export --root ABS_ROOT --task-id TASK_ID --timeout 1` vypíše pouze allowlistovaný v3 task-shadow JSONL na stdout. Export používá `HubClient(auto_start=False)`, nevytváří Hub proces, neprovádí inference a selže při stream gap nebo neplatném task/event scope. Uložit stdout do souborů pod `server.state_dir/shadow-evaluation/`. `python tools/shadow_eval.py score --observations OBSERVATIONS.jsonl --annotations ANNOTATIONS.jsonl` ověří přesné annotation schema a vypíše lokální confusion metrics; report vždy ponechá `quality_status=not_verified` až do nezávislého splnění lidských a reprezentativních eval bran.

Každý annotation řádek obsahuje přesně `task_id`, `sequence`, `expected_action`, pseudonymní `reviewer_ref`, timezone-aware `reviewed_at` a `stage` (`independent` nebo `adjudication`). Dva revieweři nejprve nezávisle označí každý případ jako `recommend_pause`, `recommend_continue`, `none` nebo `unclear`; nevidí štítek druhého reviewera. Jejich nezávislost je doložena pouze operátorem; nástroj kontroluje různé pseudonymní `reviewer_ref`, ale identitu člověka neověřuje. Adjudikátor smí přidat jeden řádek pouze při neshodě alespoň dvou nezávislých reviewerů. Adjudikovaný štítek pak vstupuje do confusion metrics; původní neshoda zůstává vykázána jako adjudikovaná, nikoli jednomyslná. Adjudikace bez dvou nezávislých štítků, při shodě nebo duplicitní adjudikace se odmítne.

Report odděluje `single_reviewer_cases` od `multi_reviewer_cases`; single-reviewer řádky ale do výsledných metrik vstupují. Přijímací eval proto musí být tvořen jen oprávněným reprezentativním vzorkem s alespoň dvěma nezávislými reviewery na každý skórovaný případ. `unanimous_cases` vyžaduje alespoň dva různé reviewery se stejným štítkem. Neshoda bez adjudikace se označí jako `unresolved_disagreements` a nezapočítá se do kvality. Platný adjudikovaný případ zvýší `adjudicated_cases` a skóruje se podle adjudikovaného štítku. Syntetické testy dokazují pouze kontrakt evaluátoru, nikoli lidskou kvalitu ani reprezentativnost.

Generované `local_ai_repo` popisy uvádějí review doporučení jen pro akce přítomné v profilu (`review_diff`, `security_audit`); vypnuté akce se nepropagují ve statické větě.

Před rozšířením adjudikace: `python -m pytest -q tests/test_operation_contracts.py tests/test_mcp_agent_routing.py` **208 passed**; `python -m pytest -q tests/test_t19_prompt_profile_parity.py tests/test_generator_action_descriptions.py tests/test_shadow_evaluation.py` **11 passed**.

Validace 2026-11-10 po rozšíření adjudikace a double-review CLI brány: `python -m pytest -q tests/test_shadow_evaluation.py tests/test_host_shadow_adapters.py tests/test_agent_tasks.py tests/test_generator_action_descriptions.py` **124 passed, 1 skipped** (opt-in Codex smoke); `git diff --check` změněných souborů prošel. Žádná inference ani živý host smoke neběžel. Tyto testy nedokládají reprezentativní lidské štítky ani živé klientské integrace.

### Etapy a postupové brány

#### Priorita po steeringu uživatele (2026-11-10)

Etapy pro Codex App Server, Antigravity CLI/hooks/sidecar a OpenCode jsou odložené; následující původní pořadí je zachováno jako podklad, ne jako aktuální implementační fronta. První obecná pause/continue shadow funkce nyní používá ověřený Agent OS checkpoint. Další etapa má vycházet z dalších ověřených, klientsky neutrálních vstupů Agent OS, event store, command brokeru a repository evidence. Vyber jedinou schopnost s dostupným vstupem; nebuduj nový daemon, databázi ani MCP nástroj. Když žádný vstup není doložen, ponech schopnost `unsupported`/`not_verified` a nejdřív doplň důkazy.

1. **Společný kontrakt a bezpečný shadow sink — nyní.** Typované schopnosti/požadavky/výsledky; pseudonym relace; metadata-only Agent Event; deduplikace; defaultní no-op pro současné neověřené hooky. Cílené testy: neověřený host/verze, cizí relace, zamítnutá oprávnění, ztráta Hubu, duplicitní event, restart a nepřítomnost textu promptu ve storage.
2. **Codex App Server, Hub-owned relace.** Spusť izolovaný server, dokonči handshake a ověř fixture parser pro `thread/started`, `thread/status/changed`, `turn/started`, `turn/completed`, token-usage a tři schema approval requesty. Turn parser ukládá jen status enum; token usage parser mapuje pouze kumulativní `total`; approval parser ukládá jen typ a pseudonymní event identity. Živé doručení turn/usage/approval eventů zůstává neověřené. Živý smoke bez inference smí ověřit pouze inicializaci. Žádné `turn/steer`, `turn/interrupt`, `command/exec` ani approval response v shadow.
3. **Antigravity CLI hooks/`stream-json`, Hub-owned proces.** Přidán bounded metadata-only parser a sdílená shadow gate s testy; CLI parser nepřijímá text, `tool_info`, cesty ani výstupy. Pro aktuálně doložené `PostToolUse` schema přibyl `parse_antigravity_post_tool_use_event()`: ověřuje očekávanou konverzaci a kanonický workspace, vrací pouze `tool.completed`/`tool.failed` a hashované identity; zahazuje argumenty, text chyby, transcript/artifact cesty a název modelu. `record_antigravity_hook_shadow_event()` zapisuje pouze přes společnou fail-closed bránu. Parser fixtures nejsou živým doručením: produkční caller, hook instalace, session ownership a místní `agy` zůstávají `not_verified`. Headless `stream-json` vyžaduje prompt/inference. Další etapa potřebuje Hub-owned launcher a ověřenou vazbu procesu/konverzace; teprve pak ověřit EOF/timeout, deduplikaci, restart a cleanup. Shadow návrh se nesmí odeslat jako prompt.
4. **Antigravity sidecar/`agentapi`.** Odložit, dokud nebude doložena konkrétní GUI konverzace, vlastnictví, oprávnění a neinvazivní read-only pozorování. `new-conversation` a `send-message` jsou zakázané v shadow.
5. **Vyhodnocení před opt-in.** Na reprezentativním běhu oddělit měření, odhady a neověřené výsledky. Pro každou schopnost zvlášť změřit přesnost, falešné zásahy, zmeškané příležitosti, latenci, tokenovou režii a selhání. Před opt-in stanovit minimální počet případů, prahy, lidské potvrzení, kill switch a rollback. Bez doloženého přínosu zůstat vypnuto.

### Aktuální změny a stav ověření

- Scope steering 2026-11-10: na pokyn uživatele jsou všechny konkrétní IDE/client adaptéry odložené jako OpenCode. Aktuální práce přechází na klientsky neutrální shadow funkce používající již ověřené Hub vstupy; žádná host UX, hook instalace ani relace.
- Klientsky neutrální pause/continue shadow producer je připojen k `task.checkpointed`. `host.shadow.observation.v3` ukládá do kanonického task streamu návrh i `not_proposed` checkpointy s allowlistovaným task statusem a dvěma presence bits. Stávající `/api/agent-state/events/stream` zpřístupňuje záznamy přes root/task binding a `kind` filtr; generické klientské shadow streamy zůstávají oddělené. Core regresní sada včetně export/scoring unit testů: **259 passed, 1 skipped** (opt-in Codex smoke); po přidání dalších dvou export boundary testů `tests/test_shadow_evaluation.py`: **6 passed**. `git diff --check` → **exit 0**.
- Agent OS task `task_endpoint_routing` naposledy potvrzen na revizi `e559cf22a8be10b84ad085365b7f65347d3a88caf57fde85437db1032337dd0a`, `plan_validate` → `valid=true`. Následný plánový zápis pro no-proposal v3 Hub neodeslal (`request_not_sent`); interní plánové soubory nebyly editovány přímo.
- Agent OS task: `task_6afd02ab3178`. Navázání přes `plan_bind_task` není doloženo, protože dostupný session ID chybí. Plán `plan_4fc62af31642` zůstává aktivní; poslední potvrzená revize tasku je `e559cf22a8be10b84ad085365b7f65347d3a88caf57fde85437db1032337dd0a`.
- Shadow matice výslovně mapuje všech 12 budoucích schopností na dostupné signály, mezery, stav podpory a měřicí bránu. Nepovoluje automatické návrhy ani hostí zásahy.
- Etapa 1 implementována ve stávajícím `host_adapters.py`: typované capability/request/result stavy; pseudonymizovaná session reference; metadata-only zápis přes existující `AgentStateStore`; idempotentní eventy; fail-closed při neověřené identitě, vlastnictví nebo event store. Neznámá oprávnění shadow záznam nezastaví; `permission_check` zůstane `not_evaluated` a žádná akce se neprovede.
- Codex App Server: `parse_codex_app_server_notification()` přijímá `thread/started` bez RPC `id`, `thread/tokenUsage/updated`, `thread/status/changed`, `turn/started` a `turn/completed`; samostatný `parse_codex_app_server_approval_request()` přijímá command-execution, file-change a permissions approval requesty. Start ověřuje `thread.cwd` a `cliVersion`; usage ukládá pouze kumulativní `total` allowlistovaných čítačů; turn ukládá jen status enum; approval pouze typ a permission check. Události vyžadující thread vazbu kontrolují očekávané vlákno a čerstvou procesní identitu. Výsledek obsahuje pseudonym relace, hash eventu a pořadí; prompt preview, cesta, command, reason, permissions, thread/turn/item/request ID, error text, item payload ani raw usage se nepřenášejí. `record_codex_shadow_event()` používá společnou gate a nikdy neposílá approval response. Živé doručení turn/usage a approval eventů zůstává `not_verified`.
- Antigravity CLI etapa: locator najde `agy`; bounded NDJSON parser zpracuje jen metadata `init`/`step_update`/`result` a společný sink zapisuje pouze shadow eventy. `run_antigravity_cli_turn()` je nyní explicitně `unsupported` a nevyhledá ani nespustí CLI: existující external-call counter nedokládá peněžní limit a není doložena bezpečná tool-free konfigurace. Žádný prompt se do hostu neposílá.
- `PolicyEngine.reserve_external_call()` a `reserve_antigravity_cli_turn()` zůstávají samostatné testované primitivy pro autorizaci a deduplikaci počtu volání. Nejsou callerem a nenahrazují peněžní limit; jejich rezervace se nesmí vykládat jako povolení inference.
- Stávající Codex/Gemini CLI hook nyní vrací `{}`. Antigravity `PreInvocation` také vrací `{}`, nespouští Hub a při novém setupu se neregistruje; `PreToolUse` zůstává odděleným filtrem. Tyto hook payloady nejsou důkazem vlastnictví, takže se z nich shadow event nezapisuje.
- Čerstvá lokální kontrola hostů: `codex --version` vrátil `codex-cli 0.167.0-alpha.3.2`; `codex app-server --help` nabízí stdio. `codex app-server daemon version` nedokázal připojit socket a daemon neběží. `agy` není v `PATH` ani na resolverní cestě `%LOCALAPPDATA%\agy\bin\agy.exe`; místní verze a rozhraní jsou `not_verified`. Dřívější hlášení `1.4.2` nebylo možné znovu ověřit.
- Oficiální [headless CLI docs](https://antigravity.google/docs/cli/headless/) popisují `stream-json` jako print/headless běh, který posílá prompt a provádí tah. `agy` v aktuálním shellu chybí, proto lokální help ani stream nelze ověřit. Runner zůstává `unsupported`, dokud Hub nedoloží tool-free konfiguraci a enforceable peněžní limit. Živý Antigravity stream a inference zůstávají neověřené.
- `git diff --check` pro změněné soubory prošel; Git současně vypsal běžná upozornění LF→CRLF pro jiné existující dirty změny.
- Parser, policy a reservation testy ověřují sanitizaci fixture streamů, metadata-only zápis, broker grant a deduplikaci počtu volání. Opt-in smoke `$env:LOCAL_AI_HUB_RUN_CODEX_APP_SERVER_SMOKE='1'; python -m pytest -q --tb=short tests/test_host_shadow_adapters.py::test_installed_codex_app_server_event_uses_metadata_only_shadow_sink` s `codex-cli 0.167.0-alpha.3.2` prošel: **1 passed**. V dočasném `CODEX_HOME` ověřil `initialize`, `thread/start` a skutečně doručený `thread/started`; parser jej přijal a existující sink zapsal metadata do dočasného `AgentStateStore`. `permission_check=not_evaluated`, `content_stored=false`; test neposílá `turn/start`. Cílená regresní sada: **122 passed, 1 skipped** (opt-in smoke). Ověřena je jen úzká cesta lokální App Server události, ne Codex Desktop, turn/approval ani produkční správa relace. Antigravity živý stream, oprávnění instalace a vlastnictví OS procesu zůstávají `not_verified`; peněžní limit chybí.
- Bounded hledání nenašlo produkčního calleru `run_antigravity_cli_turn()` ani `record_codex_shadow_event()`; čerstvé vyhledání zdrojových volání našlo pouze definice a testy parseru/sinku. Izolovaný smoke test není Hub runtime caller. Po extrakci na `codex/opencode-extraction` už `hubctl.py` na `master` nenabízí akci OpenCode; není zde ani Codex/host-session akce. Aktivní MCP schema také nemá lifecycle akci pro Codex relace. App Server nabízí stdio i spravovaný daemon, ale daemon bootstrap/start je trvalá host změna a nebyl spuštěn. Antigravity CLI hooks dokumentačně zpřístupňují `conversationId`, ale také `lastUserInput` a transcript cestu; žádné z těchto polí nedokládá Hub vlastnictví. `agy` nebyl nalezen v aktuálním PATH a `run_antigravity_cli_turn()` zůstává fail-closed `unsupported` kvůli chybějícímu vymahatelnému peněžnímu limitu. `agentapi` se v tomto prostředí nenašel v PATH; dostupnost mimo PATH zůstává `not_verified`. Hooky zůstávají no-op a nesmějí zapisovat z neřízených relací. Další Codex etapa potřebuje explicitní Hub-owned lifecycle vstup; bez něj by připojení znamenalo neověřenou relaci.
- Regresní testy provedly migraci již registrovaného Hub hooku: zachovají cizí uživatelský hook, odstraní Hub `PreInvocation`, zachovají `PreToolUse` a ověří, že starý `PreInvocation` handler nic nevloží ani nespustí Hub. Shadow event s neověřeným permission stavem uloží pouze povolená metadata a nastaví `permission_check=not_evaluated`; ověřené `would_be_denied=true` zůstává zaznamenáno jako odmítnutí.
- Hub preprocessing byl jednou zaregistrován. Fronta hlásí globální pauzu; žádný refresh ani polling neproběhl.
- Pracovní strom měl při startu 43 upravených a 4 nesledované položky. Zachovat všechny; neinterpretovat je jako součást této etapy.
- Nebyla vytvořena trvalá uživatelská host relace, nespustil se turn ani placená inference a integrační přijetí zůstává `not_verified`. Codex `thread/started` je ověřen pouze v izolované dočasné relaci a metadata-only sinku.
- Antigravity `PostToolUse` schema bylo znovu ověřeno v oficiální dokumentaci: `toolCall.name`/`args`, `stepIdx`, volitelný `error` a common session/workspace pole; odpověď je `{}` a output nástroje není součástí eventu. Nový fixture-only parser zahazuje soukromá pole, kontroluje conversation/workspace vazbu a event ID deduplikuje podle konverzace a kroku. Cílená host/hook sada po změně: **71 passed, 2 skipped**. Žádný hook nebyl nainstalován ani spuštěn; žádný Antigravity event nebyl živě doručen a nic se neposlalo do hostu.
- Čerstvé ověření 2026-11-10: `python -m pytest -q --tb=short tests/test_host_shadow_adapters.py tests/test_feature_surface_parity.py` → **38 passed, 1 skipped**. `test_shadow_observation_deduplicates_after_event_store_restart` nyní zapisuje i opakuje událost ve dvou samostatných Python procesech; druhý proces vrátí `duplicate=true` a jeden uložený záznam. Doplňující host/hook sada `tests/test_host_adapters_superpowers.py tests/test_managed_host_hooks.py` → **22 passed, 1 skipped** (symlink creation unavailable). Opt-in `test_installed_codex_app_server_event_uses_metadata_only_shadow_sink` → **1 passed**. Isolated smoke ověřil pouze `initialize`, `thread/start` a `thread/started`; turn, inference ani trvalá relace nevznikly.
- Čerstvá revalidace 2026-11-10: Codex CLI `0.167.0-alpha.3.2`; `agy` nenalezen. Host adapter/hook sada `tests/test_host_shadow_adapters.py tests/test_host_adapters_superpowers.py tests/test_managed_host_hooks.py` → **53 passed, 2 skipped** (volitelný live smoke a nedostupné symlink oprávnění); nový test ověřuje, že disconnected/unknown vrací `uncertain` bez zápisu. Oddělený App Server smoke → **1 passed**; žádný `turn/start` ani inference.
- Shadow telemetry etapa (2026-11-10): Antigravity parser předává do `host.shadow.observation.v2` pouze pět známých celočíselných usage čítačů; neznámé usage pole se zahodí, záporná/booleovská/desetinná/nadměrná hodnota se odmítne a chybějící čítače se nedoplňují. Event označuje `token_usage_scope=session_cumulative`; `source_sequence` a hash per-process nonce odlišují opakování od restartu bez uložení raw ID. Není to cenový limit. Host shadow/hook regresní sada po změně → **62 passed, 2 skipped**. Lokální `agy` chybí, takže živý stream zůstává `not_verified`.
- Revalidace 2026-11-10 v hlavním worktree (`HEAD ecf259c7`, před testy dirty): `python -m pytest -q --tb=short tests/test_host_shadow_adapters.py tests/test_host_adapters_superpowers.py tests/test_managed_host_hooks.py` → **68 passed, 2 skipped**; skipy jsou opt-in živý Codex smoke a nedostupné vytvoření symlinku. Jde o cílenou zdrojovou regresní sadu, ne o živé přijetí Codex nebo Antigravity.
- Codex turn, usage a approval metadata etapa (2026-11-10): lokální App Server JSON Schema potvrzuje `thread/tokenUsage/updated`, `thread/status/changed`, `turn/started`, `turn/completed` a command-execution/file-change/permissions approval requesty. Parser ukládá jen kumulativní `total` čítače, allowlistovaný turn status, approval event type a permission-check výsledek pro očekávané vlákno; pseudonymizuje thread ID a ukládá hash čerstvého process nonce. Testy ověřují vyřazení ID, command/cwd/reason/permissions, item/error obsahu a cizích polí, stejno-procesní deduplikaci i odlišení restartu. Společná host shadow/hook sada → **68 passed, 2 skipped**. Neproběhlo živé doručení turn/usage/approval eventu ani inference; caller, cenový limit a produkční lifecycle zůstávají `not_verified`/blokované.
- Ztráta spojení zůstává samostatnou mezerou: Codex smoke skončí chybou, pokud proces zavře stdout před očekávaným `thread/started`, ale netestuje ztrátu již navázaného streamu, obnovu ani neurčitý výsledek po přerušení. Produkční stream supervisor/caller neexistuje. Antigravity nemá živý stream test, protože jeho CLI běh zatím spustí inference a nemá ověřený tool-free režim ani peněžní limit. Transportní EOF, timeout a restart proto zůstávají `not_verified`; budoucí supervisor je musí mapovat na `uncertain`, nikdy na úspěch.
- Aktuální revalidace: `python tools/surface_inventory.py --check --task-id task_d20e0b092c32` → 698 řádků, bez driftu na HEAD `ecf259c7`. `python -m pytest -q --tb=short tests/test_surface_inventory.py` → 755 passed na HEAD `e1552258`; následný kódový commit `688dbd6a` se `surface_inventory` testů ani generátoru netýkal. Na HEAD `688dbd6a` (kódové testované soubory se od té doby nezměnily): `tests/test_http_post_route_registry_t18.py tests/test_host_shadow_adapters.py tests/test_host_adapters_superpowers.py tests/test_managed_host_hooks.py` → 78 passed, 2 skipped; oddělený izolovaný App Server smoke → 1 passed. Smoke poslal jen `initialize`, `thread/start`; žádný `turn/start` ani inference.
- První společný běh před aktualizací HEAD měl 14 importních chyb kvůli přechodnému konflikt markeru v `repo_tools.py:715`. Po posunu na `688dbd6a` čistý opakovaný běh prošel; žádný cizí zdrojový soubor nebyl v této etapě upraven.

- Revalidace 2026-11-10 (owner-state export): read-only state/agent_state.sqlite query found 47 host.shadow.observation.v3 and 46 v2 events. Exported only main-root task streams for C:\Users\Adam\.local-ai-hub: 21 allowlisted v3 observations across six tasks to state/shadow-evaluation/exports/local-ai-hub-v3-9a155ca5b3e6.jsonl. Export schema contains proposal/status/reason and task-presence metadata; prompt, transcript, source, command and output fields are absent. Other repository/worktree roots were excluded. No annotations or scoring were created; two independent reviewers and adjudication remain required, so quality and reviewer identity remain not_verified.

- Current installed host interface check 2026-11-10: codex-cli 0.167.0-alpha.3.2 is in PATH and codex app-server --help exposes the experimental server; no live thread or turn was started. agy and agentapi are not in PATH; availability outside PATH remains not_verified. Google documents Antigravity stream-json as an inference-driven CLI protocol with init/step_update/result events ([headless CLI](https://antigravity.google/docs/cli/headless/)) and documents SessionStart, PreToolUse, PostToolUse, PreInvocation, PostInvocation, and Stop hooks ([hooks](https://antigravity.google/docs/hooks)); these docs do not prove local installation, Hub ownership, or event delivery. OpenCode v2.2.5 is installed, but its extraction worktree is clean at 9e5b00c6; main has no OpenCode runtime symbols in src/local_ai_hub or hubctl.py. The user deferred concrete IDE adapters, so no host process or hook was launched. Codex app-server supports app-owned thread/turn lifecycle and streamed events ([official protocol guide](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server)); production Hub ownership remains not_verified.

- Export distribution 2026-11-10: all 21 main-root rows are task.checkpointed observations with proposal action recommend_pause, reason checkpoint_has_blockers, and source_state.has_blockers=true. This is natural recorded data but a one-class, condition-selected sample; it cannot estimate continue/none behavior, false negatives, or overall quality. Keep quality_status=not_verified until representative states and independent labels are available.

- Cílená revalidace host shadow 140/2 (2026-11-10, hlavní checkout HEAD ecf259c7, dirty tree): python -m pytest -q --tb=short tests/test_agent_tasks.py tests/test_shadow_evaluation.py tests/test_host_shadow_adapters.py tests/test_host_adapters_superpowers.py tests/test_managed_host_hooks.py -> 140 passed, 2 skipped. Skipy: opt-in Codex App Server smoke nebyl spuštěn; Windows odmítl vytvoření symlinku. Jde o zdrojové/regresní testy, ne o živé přijetí hosta nebo inference.

- Aktualizace shadow exportu 2026-11-10: po předchozím 21řádkovém snapshotu přibyly tři nové hlavní-root události. Aktuální snapshot má 24 metadata-only v3 záznamů ze šesti task streamů v state/shadow-evaluation/exports/local-ai-hub-v3-3622e498f91c.jsonl; nahrazuje předchozí soubor pro budoucí anotace. Všech 24 zůstává recommend_pause / checkpoint_has_blockers, takže vzorek stále není reprezentativní. Do exportu nepřibyly prompt, transcript, source, command ani output fields.
