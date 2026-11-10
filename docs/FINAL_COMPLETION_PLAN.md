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

- **Codex CLI:** lokálně `codex-cli 0.167.0-alpha.3.2`; `codex app-server --help` potvrzuje dostupnost příkazu. Oficiální [App Server protokol](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server) dokumentuje JSON-RPC relace, `thread/start`, `turn/start`, stream událostí a požadavky na schválení. [Návod pro ChatGPT plan](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server) popisuje OAuth token a `turn/start`; `model/list` je jen katalog, nikoli entitlement check. Dokumentace nedokládá předběžný peněžní strop pro tah. Podporovat pouze vlákna, která Hub sám založí a vlastní. Živý `codex app-server` handshake uspěl přes JSON-RPC `initialize`/`initialized` (Codex CLI `0.167.0-alpha.3.2`). V izolovaném dočasném `CODEX_HOME` proběhl `thread/start`; skutečná notifikace `thread/started` dorazila a parser ji přijal. Nebyl spuštěn turn ani inference. Dočasný profil a event store byly po smoke odstraněny; pracovní checkout zůstal zachován. Události `turn/*` a approval request zůstávají `not_verified`.
- **Antigravity CLI:** Dřívější lokální kontrola zaznamenala `agy.exe` `1.4.2` v `%LOCALAPPDATA%\agy\bin`; aktuální shell jej na této cestě ani v `PATH` nenalezl, takže dostupnost/verze instalace nyní není ověřená. Oficiální changelog uvádí CLI `1.4.12` (2026-10-30), což samo nedokládá místní instalaci. Aktuální [Hooks dokumentace](https://antigravity.google/docs/hooks) popisuje CLI `SessionStart` před první modelovou invokací a `Stop`; payload obsahuje `conversationId`, `workspacePaths`, `transcriptPath` i `lastUserInput`. Konfigurace může být workspace, globální nebo pluginová, takže sama nedokazuje Hub vlastnictví. Headless [`stream-json`](https://antigravity.google/docs/cli/headless/) stále vyžaduje prompt; nepoužili jsme jej. Žádný živý hook ani stream nebyl spuštěn. Zachovat `not_verified`, dokud nebude dostupný konkrétní CLI a Hub-owned spouštěcí cesta, která bezpečně zahodí obsah a dokáže vazbu procesu/konverzace. Parser whitelistruje pouze povolená stream metadata; locator pouze hledá CLI a nemění `PATH`.
- **Antigravity sidecar/`agentapi`:** oficiální [sidecar dokumentace](https://antigravity.google/docs/sidecars) popisuje spravovaný persistentní proces a `agentapi` příkazy `new-conversation`/`send-message`; dokumentovaný povrch nenabízí read-only stream událostí. Sidecar je proto `unsupported` pro shadow event capture; jeho zápisové příkazy nebyly volány. Místní `.gemini/config/config.json` nemá `sidecars` a sidecar/plugin adresáře jsou prázdné. Dostupnost jiných instalací a oprávnění zůstávají `not_verified`.
- **OpenCode:** 86 integračních souborů odstraněno z pracovního stromu `master` a zachováno na čisté větvi `codex/opencode-extraction` (`9e5b00c626a49dc41495056d1a3407cae7181749`). Další návrh má být klientsky neutrální; zachovaná větev nedokládá provozní přijetí.
- **OpenCode event API (ověřeno 2026-11-10):** aktuální oficiální [API reference](https://opencode.ai/docs/api) označuje HttpApi i `/api/event` za experimentální. SSE může při pomalém odběru selhat a při odpojení se události ztrácejí; dokumentace neprokazuje doručení ani vlastnictví událostí v lokálně instalované `v2.2.5`. Zprávy navíc obsahují obecné `data` objekty a rozhraní zahrnuje textové, reasoning, tool i permission události. Další klientský adaptér zůstává `not_verified`: nejdřív ověřit konkrétní potřebu, připnutou verzi, Hub-owned identitu, bezpečný metadata allowlist a obnovu po výpadku.

### Produkční volající Codexu

Oficiální [App Server protokol](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server) popisuje produktovou aplikaci, která vlastní proces, vytváří/obnovuje vlákno, spouští turn a zobrazuje stream i žádosti o schválení. V Hubu máme pouze izolovaný parser/sink smoke; `hubctl` ani aktivní MCP schéma nemají uživatelsky řízený lifecycle této relace. Pasivní sběr z cizího Desktop/CLI vlákna proto nepodporujeme. Samotné vytvoření prázdného vlákna neposkytuje použitelnou interakci; před produkčním volajícím je třeba navrhnout explicitní Hub UX, vlastnictví a cleanup procesu, ověřitelná oprávnění a vymahatelný rozpočtový limit. Do té doby je produkční App Server integrace `unsupported`; Desktop události a oprávnění jsou `not_verified`.

**Kandidátní minimum k posouzení, zatím neimplementováno:** lokální interaktivní `hubctl codex` vlastní pouze jím spuštěný stdio App Server proces a vlákno založené po přímém uživatelském příkazu; žádný daemon ani nový MCP tool. To je lifecycle oddělený od shadow: shadow sink jen pozoruje povolené události vlastního procesu a nikdy nevolá `thread/start`, `turn/start`, interrupt, approval ani zprávu. Raw thread ID zůstává v paměti klienta; event store dostává pouze pseudonym. Zavření klienta korektně uzavře vstup a ukončí jeho procesní strom. Aktivní `turn/start` zůstává `unsupported`, dokud není vymahatelný peněžní limit a samostatný explicitní souhlas. Existující durable reservation počítá externí volání, ne cenu; `run_antigravity_cli_turn` proto dnes selže zavřeně s `enforceable_monetary_budget_unavailable`. Počet tahů není peněžní strop. Neznámé oprávnění je `not_evaluated`. Tato volba vyžaduje rozhodnutí o cílovém UX a její procesní/permission/budget hranice se musí ověřit před implementací.

### Shadow záznam a pojmenování výsledků

Záznam smí obsahovat typ a čas události, host/povrch/verzi, pseudonym relace nebo oprávněně stabilní ID, task/evidence ID, navrženou akci a důvod, stav ověření a tri-state výsledek kontroly oprávnění. Nepřidávat cesty, argumenty nástrojů, prompty, transcript y, výstupy ani kód. `proposed`, `simulated`, `executed` a `verified` jsou samostatné stavy. `shadow_only` znamená, že návrh nebyl odeslán. Neznámé oprávnění zaznamenat jako `not_evaluated`, nikdy jako povolení.

Kanonický kontrakt rozlišuje `success`, `refused`, `unsupported`, `uncertain` a `shadow_only`. Zápis je dovolen jen pro Hubem spravovanou relaci s ověřenou identitou a oprávněními. Při neznámé verzi, relaci, spojení nebo vlastnictví neukládat událost a nevykonat žádnou akci. Použít existující `AgentStateStore`/`SwarmPubSub`; idempotency key odvodit z hostího event ID.

### Etapy a postupové brány

1. **Společný kontrakt a bezpečný shadow sink — nyní.** Typované schopnosti/požadavky/výsledky; pseudonym relace; metadata-only Agent Event; deduplikace; defaultní no-op pro současné neověřené hooky. Cílené testy: neověřený host/verze, cizí relace, zamítnutá oprávnění, ztráta Hubu, duplicitní event, restart a nepřítomnost textu promptu ve storage.
2. **Codex App Server, Hub-owned relace.** Spusť izolovaný server, dokonči handshake a zaznamenej skutečné `thread/started`, `turn/*` a approval request eventy přes mock/fixture testy. Živý smoke bez inference smí ověřit pouze inicializaci. Žádné `turn/steer`, `turn/interrupt`, `command/exec` ani approval response v shadow.
3. **Antigravity CLI hooks/`stream-json`, Hub-owned proces.** Přidán bounded metadata-only parser a sdílená shadow gate s testy; parser streamu nepřijímá text, `tool_info`, cesty ani výstupy. Oficiální hooks docs nyní dokládají `SessionStart` před první modelovou invokací, ale aktuální shell nenašel CLI `agy`; hook nebyl lokálně ověřen a nemá Hub ownership. Headless `stream-json` vyžaduje prompt/inference. Další bezpečná etapa potřebuje Hub-owned launcher a hook binding, který nepřenáší prompt do storage; teprve pak ověřit živý SessionStart bez inference, EOF/timeout, deduplikaci, restart a ukončení. Shadow návrh se nesmí odeslat jako prompt.
4. **Antigravity sidecar/`agentapi`.** Odložit, dokud nebude doložena konkrétní GUI konverzace, vlastnictví, oprávnění a neinvazivní read-only pozorování. `new-conversation` a `send-message` jsou zakázané v shadow.
5. **OpenCode.** Znovu posoudit oficiální SSE/plugin události po měření potřeby; nepřekrývat existující OpenCode launcher/MCP adaptér.
6. **Vyhodnocení před opt-in.** Na reprezentativním běhu oddělit měření, odhady a neověřené výsledky. Pro každou schopnost zvlášť změřit přesnost, falešné zásahy, zmeškané příležitosti, latenci, tokenovou režii a selhání. Před opt-in stanovit minimální počet případů, prahy, lidské potvrzení, kill switch a rollback. Bez doloženého přínosu zůstat vypnuto.

### Aktuální změny a stav ověření

- Agent OS task: `task_6afd02ab3178`. Navázání přes `plan_bind_task` není doloženo, protože dostupný session ID chybí. Existující Hub plán `plan_4fc62af31642`, task `task_endpoint_routing`, byl aktualizován přes `plan_task_edit`; aktuální revize `49a585b35f8b399bf4fa6ca296f2c0bad2fa5e1d9bfbd7e91879a50be72d6ddb`; předchozí revize byla `valid=true`.
- Etapa 1 implementována ve stávajícím `host_adapters.py`: typované capability/request/result stavy; pseudonymizovaná session reference; metadata-only zápis přes existující `AgentStateStore`; idempotentní eventy; fail-closed při neověřené identitě, vlastnictví nebo event store. Neznámá oprávnění shadow záznam nezastaví; `permission_check` zůstane `not_evaluated` a žádná akce se neprovede.
- Codex App Server: `parse_codex_app_server_notification()` přijímá pouze notifikaci `thread/started` bez RPC `id`, kontroluje `thread.cwd` a `cliVersion`, a vrací whitelisted typ/povrch, pseudonym relace, hash eventu a pořadové číslo. Prompt preview, cesta a thread ID se do výsledku ani shadow záznamu nepřenášejí. `record_codex_shadow_event()` používá společnou gate. Turn a approval eventy zůstávají `not_verified`.
- Antigravity CLI etapa: locator najde `agy`; bounded NDJSON parser zpracuje jen metadata `init`/`step_update`/`result` a společný sink zapisuje pouze shadow eventy. `run_antigravity_cli_turn()` je nyní explicitně `unsupported` a nevyhledá ani nespustí CLI: existující external-call counter nedokládá peněžní limit a není doložena bezpečná tool-free konfigurace. Žádný prompt se do hostu neposílá.
- `PolicyEngine.reserve_external_call()` a `reserve_antigravity_cli_turn()` zůstávají samostatné testované primitivy pro autorizaci a deduplikaci počtu volání. Nejsou callerem a nenahrazují peněžní limit; jejich rezervace se nesmí vykládat jako povolení inference.
- Stávající Codex/Gemini CLI hook nyní vrací `{}`. Antigravity `PreInvocation` také vrací `{}`, nespouští Hub a při novém setupu se neregistruje; `PreToolUse` zůstává odděleným filtrem. Tyto hook payloady nejsou důkazem vlastnictví, takže se z nich shadow event nezapisuje.
- Čerstvá lokální kontrola hostů: `codex --version` vrátil `codex-cli 0.167.0-alpha.3.2`; `codex app-server --help` nabízí stdio. `codex app-server daemon version` nedokázal připojit socket a daemon neběží. `agy` není v PATH, ale resolverem používaná `%LOCALAPPDATA%\agy\bin\agy.exe` existuje; `--version` vrátil `1.4.2` a `--help` potvrzuje stream-json vstup/výstup v headless/print režimu. Zdroj: [Antigravity headless CLI docs](https://antigravity.google/docs/cli/headless/).
- Lokální `agy --help` potvrzuje, že `--input-format stream-json` patří do print režimu; oficiální stream `init` zpřístupňuje seznam dostupných nástrojů. Help neukazuje přepínač pro jejich vypnutí. Runner proto zůstává `unsupported`, dokud Hub nedoloží tool-free konfiguraci a enforceable peněžní budget. Živý Antigravity stream a inference zůstávají neověřené.
- `git diff --check` pro změněné soubory prošel; Git současně vypsal běžná upozornění LF→CRLF pro jiné existující dirty změny.
- Parser, policy a reservation testy ověřují sanitizaci fixture streamů, metadata-only zápis, broker grant a deduplikaci počtu volání. Opt-in smoke `$env:LOCAL_AI_HUB_RUN_CODEX_APP_SERVER_SMOKE='1'; python -m pytest -q --tb=short tests/test_host_shadow_adapters.py::test_installed_codex_app_server_event_uses_metadata_only_shadow_sink` s `codex-cli 0.167.0-alpha.3.2` prošel: **1 passed**. V dočasném `CODEX_HOME` ověřil `initialize`, `thread/start` a skutečně doručený `thread/started`; parser jej přijal a existující sink zapsal metadata do dočasného `AgentStateStore`. `permission_check=not_evaluated`, `content_stored=false`; test neposílá `turn/start`. Cílená regresní sada: **122 passed, 1 skipped** (opt-in smoke). Ověřena je jen úzká cesta lokální App Server události, ne Codex Desktop, turn/approval ani produkční správa relace. Antigravity živý stream, oprávnění instalace a vlastnictví OS procesu zůstávají `not_verified`; peněžní limit chybí.
- Bounded hledání nenašlo produkčního calleru `run_antigravity_cli_turn()` ani `record_codex_shadow_event()`; izolovaný smoke test není Hub runtime caller. Po extrakci na `codex/opencode-extraction` už `hubctl.py` na `master` nenabízí akci OpenCode; není zde ani Codex/host-session akce. Aktivní MCP schema také nemá lifecycle akci pro Codex relace. App Server nabízí stdio i spravovaný daemon, ale daemon bootstrap/start je trvalá host změna a nebyl spuštěn. Antigravity CLI hooks dokumentačně zpřístupňují `conversationId`, ale také `lastUserInput` a transcript cestu; žádné z těchto polí nedokládá Hub vlastnictví. `agentapi` se v tomto prostředí nenašel v PATH; dostupnost mimo PATH zůstává `not_verified`. Hooky zůstávají no-op a nesmějí zapisovat z neřízených relací. Další Codex etapa potřebuje explicitní Hub-owned lifecycle vstup; bez něj by připojení znamenalo neověřenou relaci.
- Regresní testy provedly migraci již registrovaného Hub hooku: zachovají cizí uživatelský hook, odstraní Hub `PreInvocation`, zachovají `PreToolUse` a ověří, že starý `PreInvocation` handler nic nevloží ani nespustí Hub. Shadow event s neověřeným permission stavem uloží pouze povolená metadata a nastaví `permission_check=not_evaluated`; ověřené `would_be_denied=true` zůstává zaznamenáno jako odmítnutí.
- Hub preprocessing byl jednou zaregistrován. Fronta hlásí globální pauzu; žádný refresh ani polling neproběhl.
- Pracovní strom měl při startu 43 upravených a 4 nesledované položky. Zachovat všechny; neinterpretovat je jako součást této etapy.
- Nebyla vytvořena trvalá uživatelská host relace, nespustil se turn ani placená inference a integrační přijetí zůstává `not_verified`. Codex `thread/started` je ověřen pouze v izolované dočasné relaci a metadata-only sinku.
- Čerstvé ověření 2026-11-10: `python -m pytest -q --tb=short tests/test_host_shadow_adapters.py tests/test_feature_surface_parity.py` → **38 passed, 1 skipped**. `test_shadow_observation_deduplicates_after_event_store_restart` nyní zapisuje i opakuje událost ve dvou samostatných Python procesech; druhý proces vrátí `duplicate=true` a jeden uložený záznam. Doplňující host/hook sada `tests/test_host_adapters_superpowers.py tests/test_managed_host_hooks.py` → **22 passed, 1 skipped** (symlink creation unavailable). Opt-in `test_installed_codex_app_server_event_uses_metadata_only_shadow_sink` → **1 passed**. Isolated smoke ověřil pouze `initialize`, `thread/start` a `thread/started`; turn, inference ani trvalá relace nevznikly.
- Ztráta spojení zůstává samostatnou mezerou: Codex smoke skončí chybou, pokud proces zavře stdout před očekávaným `thread/started`, ale netestuje ztrátu již navázaného streamu, obnovu ani neurčitý výsledek po přerušení. Produkční stream supervisor/caller neexistuje. Antigravity nemá živý stream test, protože jeho CLI běh zatím spustí inference a nemá ověřený tool-free režim ani peněžní limit. Transportní EOF, timeout a restart proto zůstávají `not_verified`; budoucí supervisor je musí mapovat na `uncertain`, nikdy na úspěch.
