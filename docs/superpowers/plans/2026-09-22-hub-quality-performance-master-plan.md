# Local AI Hub — Quality, Performance and Reliability Implementation Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` when implementing this plan. Track individual operations and completion evidence; checklist items below are not implementation claims.

**Goal:** Dosáhnout nejvyšší doložitelné kvality a použitelnosti všech veřejných featur, MCP akcí, HTTP endpointů a Python/CLI integračních cest; opravit doložené chyby a podle potřeby celé slabé subsystémy přepracovat. Rychlost optimalizovat až při zachování nebo zlepšení kvality.

**Architecture:** Zachovat osm veřejných MCP nástrojů jako levný vstupní bod; jejich interní implementace, ergonomie akcí, služby, indexy, cache a Agent OS lze zásadně přepracovat. Sjednotit kontrakty operací, přenést validaci a bezpečnostní pravidla na společné hranice a optimalizovat podle měření. Rozdělit práci podle vlastnictví souborů; společné transporty integruje jediný vlastník.

**Tech Stack:** Python 3.11+, FastMCP, existující HTTP server a HubClient, SQLite/WAL, pytest, Git, Ollama/llama.cpp, volitelné OpenVINO/Serena, Chrome MV3. CodeGraphContext je samostatný externí CLI/MCP nástroj mimo Hub runtime.

---

## 0. Rozsah, výchozí stav a důvěryhodnost auditu

Tento dokument je plán. Jeho vytvoření neopravuje runtime. „Perfektní“ zde znamená splnění explicitních kontraktů, kvalitativních a výkonnostních bran pro podporované konfigurace; nikoli slib bezchybnosti na libovolném zařízení.

Kořen implementace: `<REPO_ROOT>`. Cesty níže jsou relativní k tomuto kořeni. Nově navržené soubory jsou označené **nový**. Naměřené artefakty patří pod nakonfigurovaný `server.state_dir`, ne do zdrojového repozitáře.

Stav při přípravě 2026-09-22: branch `master`, devět změněných a čtyři nesledované soubory. Probíhá adaptivní retrieval; dotčené jsou mimo jiné `services.py`, `mcp_server.py`, `repo_tools.py`, `scheduler.py`, `generator.py`, nové `retrieval.py` a `tests/test_adaptive_retrieval.py`. Před implementací znovu načíst stav a převzít skutečně dokončené části.

Navazující existující plány:

- `docs/superpowers/plans/2026-09-21-hub-audit-hardening.md` — reuse hardeningu, transportu, metrik a Agent OS.
- `docs/superpowers/plans/2026-09-21-v4-perfection-hardening.md` — porovnat s novým inventářem; neimplementovat stejnou opravu dvakrát.
- `docs/superpowers/plans/2026-09-22-adaptive-retrieval-orchestrator.md` a odpovídající spec — vlastník retrieval vrstvy; závislost T10.
- `docs/superpowers/plans/2026-09-21-trace-inspector-full-payloads.md` — ověřit záměr plného obsahu trace před změnou jeho výchozího chování.

Předchozí audit byl převážně statický, seskupoval endpointy a některé závěry byly hypotézy. Nebyl doložen úplný seznam každé kombinace metoda/cesta/akce ani samostatný subagent pro každou jednotlivou operaci. První etapa tento nedostatek uzavírá. Nalezený text v testu není důkaz, že test nyní prochází. Nepřítomnost testu v omezeném hledání není důkaz, že test neexistuje.

Evidence přípravy: Hub `git_status`; guarded `context` revize `9d71a5ab3de8b7d70436d81e6ca5364d8f9e143dc41f53a147c53f4f6fda1c97`; search evidence `E815ac6639cd77a45185b`, `E406073f5be585de29285`, `E9a40762a190bb876828d`, `Eccc6d2417d58c16bd580`. Jde o okamžitý snapshot, ne budoucí release revizi.

### Doplněná priorita uživatele: kvalita je číslo 1

Pořadí rozhodování: správnost a věrnost výsledku; spolehlivost a zachování dat; použitelnost; teprve poté odezva a spotřeba. Rychlejší, ale horší výsledek není přijatelná optimalizace. Delší vývoj i delší běh operace jsou povolené, pokud přinášejí prokázanou hodnotu. Deadlines, cancellation a resource limity zůstávají kvůli předvídatelnosti.

- [ ] Každá doména před implementací porovná opravu stávajícího návrhu a redesign podle golden úloh, očekávaných chyb a složitosti používání.
- [ ] Pokud základní návrh omezuje kvalitu nebo použitelnost, vytvořit konkrétní subsystémový návrh a přepsat jej s kontraktními testy; nevynucovat zachování vadné interní architektury.
- [ ] Nejprve uzavřít specifikaci chování, potom napsat konkrétní task-level plán s test inputs/expected outputs; tento master plán koordinuje domény a závislosti.
- [ ] Vybrat kvalitnější variantu na párovém srovnání. Zvýšenou latency vyjádřit číslem a přínosem; zaznamenat nový deadline/async behavior před release.
- [ ] Nepřidávat legacy aliasy nebo migration shimy do initial-release větve. Změněný kontrakt promítnout atomicky do vlastních klientů, schema, dokumentace a obou instalačních promptů; durable uživatelská data zachovat.

### Kandidáti na zásadní přepracování

| Doména | Návrh redesignu | Důkaz přínosu |
|---|---|---|
| API/MCP ergonomie | Typované action-specific payloady a výsledky místo přetížených `query/root/diff/staged`; společný registry kontraktů | Uživatel/agent zvládne reprezentativní úkol jedním správným voláním; nižší first-call error rate; menší nutnost studovat interní mapping |
| Command execution | Jednotná autorizovaná cesta pro run, daemon, repair a network; vlastněná transakce změn a rollback | Zachované cizí soubory, zákaz policy bypass, spolehlivé cancel a důkaz výsledku |
| Agent OS / swarm / work | Oddělit orchestraci, state machine, durable log a ověření; žádné modelové nebo syntetické úspěchy | Reálný receipt, atomický transition, crash recovery a úplný end-to-end task |
| Retrieval | Query planner s evidence-aware fusion, dependency reasoning a adaptivním rozpočtem; propojit probíhající retrieval práci | Vyšší recall/precision na obtížných multi-file otázkách bez vymyšlené evidence |
| RAG / ingestion | Explicitní dokumentový model, původ zdrojů, invalidace, hybrid retrieval a měřený reranking | Lepší relevance a správné citace na vícejazyčných, duplicitních a stale dokumentech |
| Model quality | Typované výstupy, task-specific evaluace, ověřovací kroky a kvalitnější model/ensemble pouze při doloženém přínosu | Vyšší task success a méně falešných tvrzení; srovnat i cenu delšího běhu |
| Multimodal | Skutečný speech/diagram/vision kontrakt; oddělit extrakci, modelové posouzení a ověřitelná findings | Žádný metadata-only výstup vydávaný za přepis/porozumění obrazu |
| Observability / UX | Čitelný stav každé operace: co se děje, co chybí, jak přejít k důkazu a jak pokračovat | Reprezentativní recovery scénáře bez čtení raw logů a bez zavádějícího success |

Redesign není automatický požadavek přepsat dobře fungující části. Zachovat řešení, které v přímém srovnání dosáhne lepší kvality a jednoduššího použití.

### Ověřené korekce předchozího auditu

| Nález | Stav při tvorbě plánu | Evidence / dopad |
|---|---|---|
| Python continuation posílá `prompt`, service čte `task` | Potvrzeno ve zdroji; MCP cesta má správný payload | `E4a8153d74735f7b3366d`, `E161e9a23806a1de3a277`, `E9bce734af5de1822851a`; opravit SDK, netvrdit poruchu všech callers |
| chat/completions validace bez odpovídajícího dispatch | Potvrzený source gap; live výsledek neměřen | `Eb2eff0be0b36f7e6e30a`, `E32108cedd4735be45590` |
| Artifact `list` v popisu, chybí v callable schema | Potvrzeno | `E9aef3c1592e9681ccf0e`, `E7b6d93856a1e90454fcb` |
| RAG POST je clientem replay-safe | Potvrzený classification gap; opakované škody neprokázány, server má recovery journal | `E388f3d12f6c2cef1fc67`, `E0a95c3f07c6753c624b8`, `Ec7de583917d5d86a6ea9` |
| Sdílené memos představují tenant security leak | Tato interpretace vyvrácena pro dokumentovaný trusted-local model | `SECURITY.md:13`, `Ede14a4df9de60ffb7933`; tenant je fairness label, sdílení/popřípadě overwrite musí mít jasný kontrakt |
| Daemon obchází běžnou command policy | Potvrzeno ve zdroji | `commands.py:2211`, `services.py:3072`, `Efd28e552edd7627b066b` |
| Rollback může zničit cizí změny | Potvrzeno ve zdroji | `commands.py:1473`, `commands.py:1689`; plošný checkout a mazání nových untracked cest |
| Swarm syntetický receipt a chybějící CAS | Potvrzeno ve zdroji | `swarm.py:220`, `swarm.py:238`, `swarm.py:267`; testovat platnost receipt, nikoli jen přítomnost ID |
| Pubsub nikdy nic neukládá | Takto silné tvrzení vyvráceno; journal je podmíněný a polling neumí restart replay | `E3c248a67acf1445e0320`, `Eee478c7342bed192651a`; zvolit jasný ephemeral/durable kontrakt |
| Schema mismatch maže jen disposable index | Vyvráceno; zasažen může být společný durable Agent State store | `E2086b7276f27291ad16d`, `E1fde81970dd6916dda1f`, `E2aa37f1c1dbefc01f8da` |

Jde o source ověření dvěma bounded audity; navržené runtime/regresní testy při tvorbě plánu nebyly spuštěny.

## 1. Co přesně znamená „všechny“

T01 vytvoří strojově čitelný inventář. Každá operace má vlastní řádek, vlastníka, test a výsledek. Rodina operací smí sdílet implementaci, nesmí zakrývat nepokrytý řádek.

| Povrch | Jednotka pokrytí | Povinné údaje |
|---|---|---|
| MCP | tool + action/detail + podmíněná varianta | Vstupní/výstupní schéma, defaulty, feature gates, skutečný HTTP cíl, budget/projection |
| HTTP | metoda + cesta nebo path pattern + action | Query/body, povinná pole, status codes, auth/identity, limity, side effects, timeout, idempotence |
| Python klient | veřejná metoda + payload/response mapping | Cíl, parametry, timeout, retry policy, zachování error/cancel/stale metadata |
| CLI a integrace | příkaz/subcommand nebo host manifest | Parametry, návratový kód, OS/dependency, soubory které mění, způsob recovery |
| Featura/backend | flag/profile/backend kombinace | Závislosti, dostupnost, fallback, kvalita, cold/warm latency, spotřeba |

Každý řádek dále nese: `operation_id`, owner task, handler, soubor/symbol, request/response fixtures, read/write/network/process classification, cache key, tenant/trust scope, provenance, test IDs, benchmark cohort, a stav `verified`, `conditional`, `unsupported` nebo `removed`. Odvozené aliasy se musí najít ve skutečném dispatcheru; nesmějí se domýšlet podle názvu MCP akce.

Pokrytí = počet uzavřených řádků / počet zjištěných řádků. Release vyžaduje 100 %; dokumentované nepodporované varianty musí vracet testovaný strukturovaný výsledek. Žádná neznámá operace schovaná v agregovaném skóre.

## 2. Navržené měřitelné cíle

Čísla jsou výchozí cíle plánu, nikoli dosavadní měření. T02 stanoví referenční hardware a datasety; nerealistické cíle se upraví před optimalizací s uvedeným důvodem, nikoli dodatečně po neúspěšném testu. Latency cíle jsou druhotné vůči kvalitě: prokazatelně kvalitnější pomalejší varianta je přípustná, pokud má zdokumentovaný nový rozpočet a použitelný progress/async/cancel kontrakt. Quality gates, integrita dat a pravdivost výsledků se kvůli rychlosti nesnižují.

| Oblast | Cíl přijetí |
|---|---|
| Správnost | 100 % operací má pozitivní, nevalidní a feature-disabled kontrakt; žádné `success=true` za chybějící skutečný výsledek |
| Liveness | `/health` warm p95 <= 50 ms na loopback; funguje i při nedostupném modelu |
| Lehká API | cached metadata/status/artifact/lease read p95 <= 150 ms na referenčních datech |
| Indexované lookupy | warm symbol/search/code-index p95 <= 300 ms na korpusu 10 000 souborů; p99 se měří zvlášť |
| Kontext | deterministic-only pack p95 <= 750 ms; rozšířený pack dodrží explicitní deadline a uvede vynechané backendy |
| RAG | warm search bez rerankeru p95 <= 750 ms na 100 000 chunkech; reranker má vlastní změřený rozpočet |
| Queue/async | přijetí jobu p95 <= 150 ms; deadline, cancel a overload mají explicitní testovaný výsledek |
| Inference | oddělit queue wait, load time, TTFT, service time, tokens/s; žádný univerzální čas pro všechny modely a zařízení |
| Optimalizace | při shodné kvalitě u prokázaných bottlenecků cílit >= 25 % nižší p95 nebo peak paměť; kvalitnější pomalejší redesign hodnotit podle přínosu |
| Regrese | neodůvodněná warm/cold p95 nebo p99 regrese >10 % blokuje; doložené zvýšení kvality může ospravedlnit delší čas s explicitně změněným rozpočtem |
| Retrieval kvalita | golden corpus: recall@10, nDCG@10, přesnost file/line evidence; žádný pokles na známých regresních případech |
| Model kvalita | pevné úlohy, seed/parametry, výstupní schema, test-pass a evidence-grounding; kritické chybné úspěchy 0 |
| Cache | 100 % invalidace v testech změn obsahu/revize/config/modelu/identity; single-flight neduplikuje shodnou práci |
| Resource limity | fronty, payloady, response, DB, logy a subprocessy mají tvrdé limity; po soak testu nezůstávají orphan procesy |
| Restart | žádná ztráta potvrzené durable změny v crash/restart scénářích; nedokončená práce se rekonciluje |
| Observability | telemetry bez promptů/zdrojů/secrets; content stores a debug trace mají oddělenou explicitní retention/access politiku |

Měření: cold a warm odděleně; concurrency 1/4/16/32; nejméně 1000 vzorků lehkých operací pro tail latency a 30 párových drahých úloh, report nejistoty. Zaznamenat OS, CPU/RAM/GPU, model digest, config, revizi, velikost korpusu a cache state. Jedno zařízení nesmí reprezentovat všechny hardware profily.

## 3. Etapy a závislosti

| Vlna | Úkoly | Výstup / podmínka další vlny |
|---|---|---|
| A — inventář a baseline | T01–T02 | Úplná matice, ověřené nálezy, reprodukovatelné baseline; urgentní potvrzené chyby lze opravovat souběžně |
| B — hranice a správnost | T03–T09 | Sdílené kontrakty, identity, bezpečné mutace, spolehlivá evidence a stav |
| C — výkon a kvalita | T10–T16 | Měřené zrychlení retrieval/model/RAG/cache/status/command/work bez zhoršení kvality |
| D — produktové a provozní cesty | T17–T19 | Multimodal, instalace, CLI/SDK, dokumentace, feature parity a usability scénáře |
| E — ověření celku | T20 | Všechny operace uzavřeny, release gates, load/restart/backend acceptance |

T03 je závislost transportních změn T04/T05/T19. T06 předchází mutujícím acceptance testům T15/T16. T08 a T09 předcházejí verified handoff T16. T10 přebírá dokončený adaptivní retrieval. T11 a T12 mohou po T02 běžet souběžně. T20 následuje po všech úkolech.

## 4. Backlog oprav a vylepšení

### T01 — Úplný inventář a korekce předchozího auditu

**Soubory:** číst `mcp_server.py`, `http_server.py`, `client.py`, `features.py`, `generator.py`, `tools/hubctl.py` pod odpovídajícími existujícími adresáři; **nový** `tools/surface_inventory.py`, **nový** `tests/test_surface_inventory.py`, **nový** `docs/API_COVERAGE.md`.

- [ ] Extrahovat dekorované MCP tooly, Literal/conditional actions, HTTP dispatch větve, aliases/patterns, klientské metody, CLI a feature gates pomocí AST a doplnit explicitní registry pro dynamické případy.
- [ ] Pro každý auditní nález uložit `confirmed/conditional/refuted`, reprodukci, evidence a task ID; starý chat není autoritativní seznam endpointů.
- [ ] Porovnat client targets, deklarované tools, dispatch a generated manifests; sirotčí route/metoda/action je selhání inventáře.
- [ ] Přidělit samostatnou bounded kontrolu každé veřejné operaci; shodnou implementaci číst jednou, ale otestovat každý vstupní kontrakt.
- [ ] Ověřit pokrytí nové route, podmíněně skryté akce, path pattern a chybějící handler fixture; inventář musí rozdíl zachytit.

**Hotovo:** nula nezařazených veřejných operací, test inventáře prochází, každá položka má owner a acceptance.

### T02 — Výkonnostní a kvalitativní baseline

**Soubory:** `src/local_ai_hub/benchmark.py`, `telemetry.py`, `tests/test_benchmark_suite.py`; **nový** `tools/benchmark_surfaces.py`, **nový** `tests/test_surface_benchmarks.py`.

- [ ] Připravit oddělený dočasný state root a syntetické repozitáře 100/10 000/100 000 souborů, RAG 10 000/100 000 chunků; nereplikovat soukromé projekty do metrik.
- [ ] Měřit transport, validaci, index/cache, DB, queue, load a inference samostatně; zaznamenat p50/p95/p99, throughput, peak RSS/VRAM, response bytes/tokens a chybovost.
- [ ] Vytvořit golden úlohy pro symboly, graph, affected tests, retrieval relevance, code generation, vision a speech; určit objektivní očekávané výstupy.
- [ ] Spustit cold/warm a concurrency matice; baseline se ukládá pod state dir s revizí/config/hardware fingerprint.
- [ ] Automatizovat párové srovnání s tolerancemi z oddílu 2; benchmark nesmí záviset jen na aktuálním pořadí cache hitů.

**Hotovo:** baseline lze zopakovat; změna skóre/latency je přiřaditelná konkrétní operaci.

### T03 — Jednotné kontrakty, feature gates a transport

**Soubory:** `src/local_ai_hub/mcp_server.py`, `http_server.py`, `features.py`, `generator.py`, `client.py`; **nový** `src/local_ai_hub/operation_contracts.py`, **nový** `tests/test_operation_contracts.py`.

- [ ] Zavést jeden registr pro již existující operace: schéma, feature gate, side effects, retry/idempotence, timeout, projection. Reuse T01, nevytvářet druhý nezávislý katalog.
- [ ] Registrované kontrakty zapojit do runtime validace i generated schemas/docs. Zachovat osm MCP toolů.
- [ ] Validovat action/detail/phase, typy, required fields, bounds a numerické vstupy před handlerem; konkrétní chyby 400/401/403/404/409/413/415/429/503 a konzistentní error body.
- [ ] Otestovat enabled/disabled/backend unavailable přes MCP, HTTP a klienta; schema skrytí samo nestačí.
- [ ] Zachovat `success`, `terminal`, `retryable`, `degraded`, `stale`, evidence a cancel metadata i po kompakci; změny nasadit inkrementálně po rodinách.

**Hotovo:** stejná operace má shodný kontrakt na všech vstupních cestách; nevalidní vstup nespadne do generické 500.

### T04 — Přímé chyby API, klienta a objevitelných funkcí

**Soubory:** `src/local_ai_hub/client.py`, `http_server.py`, `mcp_server.py`, `services.py`; `tests/test_client_transport.py`, `tests/test_conversations.py`, `tests/test_mcp_agent_routing.py`; **nový** `tests/test_public_api_regressions.py`.

- [ ] Reprodukovat conversation continuation přes veřejný HubClient a service. Pokud posílá `prompt` místo `task`, sjednotit payload; otestovat další turn, expired ID a konkurující turn.
- [ ] Rozhodnout `/api/chat/completions` z reálného kontraktu a callerů: pokud je slíbený, implementovat řádný kompatibilní handler se schema/stream/error testy; pokud není podporovaný, odstranit zavádějící deklarace a validaci. Nepřidávat nové API jen podle domněnky starého auditu.
- [ ] Vyřešit advertised artifact `list`: implementovat pouze při doložené potřebě paginovaného metadata listing; jinak odstranit neexistující akci z popisu.
- [ ] Opravit default language rozdíl GET/POST resolve_imports, nechtěné vynucení include_code a rozdíl call_graph_diff/semantic_diff, pokud reprodukce potvrzuje problém.
- [ ] Sjednotit `delta/reuse/extra_fields/max_response_tokens`, RAG action descriptions, review/diff delivery a work response controls podle skutečných společných wrapperů.

**Hotovo:** každá potvrzená chyba má regresní test na veřejném vstupu; vyvrácené nálezy jsou uzavřené s důvodem.

### T05 — Identity, sdílená paměť a model důvěry

**Soubory:** `src/local_ai_hub/memory.py`, `agent_memory.py`, `leases.py`, `evidence.py`, `artifacts.py`, `http_server.py`; `tests/test_memory_http_validation.py`, `tests/test_agent_memory.py`, `tests/test_vision_artifacts.py`; **nový** `tests/test_identity_contracts.py`.

- [ ] Explicitně popsat trusted-local boundary: současné tenant označení nemusí znamenat bezpečnou izolaci. Určit, které memos/leases jsou úmyslně sdílené.
- [ ] Nezavádět automaticky nedůvěryhodný multi-tenant hosting: dokumentovaný základ je trusted-local. Pokud se skutečně zavádí privátní scope, vázat jej na ověřenou identitu, zahrnout do primárních/cache klíčů a SQL read/write/delete; klientem zaslaný label nesmí sám dokazovat oprávnění.
- [ ] Pro sdílenou koordinaci zachovat potřebnou viditelnost konfliktů a označit scope. Současné workspace/key last-writer chování testovat jako explicitní kontrakt; nabídnout expected-version conflict při potřebě ochrany před neúmyslným overwrite.
- [ ] Otestovat dvě identity, stejný klíč, cizí ID, public/shared scope, privilege spoofing, evidence/artifact lookup a cache isolation.
- [ ] Durable data převádět zálohovanou jednorázovou operací s kontrolou výsledků; nepřidávat obecné legacy shimy. Odvozené indexy se mohou rebuildnout.

**Hotovo:** zdokumentované sdílení a privátní scope odpovídají runtime; žádný náhodný overwrite nebo nedovolený read v podporovaném režimu.

### T06 — Bezpečná mutace, daemony, síť a rollback

**Soubory:** `src/local_ai_hub/commands.py`, `agent_policy.py`, `process_utils.py`, `services.py`, `defaults.toml`, `src/local_ai_hub/defaults.toml`; `tests/test_security_boundaries.py`, `tests/test_command_rollback.py`, `tests/test_auto_fix_repair_loop.py`; **nový** `tests/test_auxiliary_action_policy.py`.

- [ ] Pro run/repair/format/daemon/network/stash/stage/mock/bundle/config/model actions ověřit skutečnou cestu policy authorize; sjednotit povolení, ownership a side-effect class.
- [ ] Nastavit výchozí policy podle dokumentovaného lokálního použití; nebezpečné/unknown akce nesmějí obcházet kontrolu alternativním endpointem. Explicitně autorizované vývojové mutace musí zůstat proveditelné.
- [ ] Rollback omezit na snapshot skutečně vlastněných cest. Test musí zachovat předchozí dirty/untracked soubory i souběžnou cizí změnu; nepoužívat plošný reset/checkout/clean.
- [ ] Daemon: structured argv, environment filtering, owner, PID identity, TTL, log limits, cancel/process-tree cleanup a restart reconciliation.
- [ ] Network: cílová politika pro scheme/host/redirect/DNS, bound payload/response, header/secret redaction. Localhost a privátní dev services povolit explicitním scope, nikoli zakázat bez ohledu na účel Hubu.
- [ ] Cassette/file names pod povoleným kořenem; mock server binds loopback, CORS dle záměru; import ZIP ověřuje traversal, symlink, zip bomb, overwrite a atomicitu.

**Hotovo:** alternativní helper neobchází policy; timeout/cancel nenechá proces; rollback nepoškodí cizí práci.

### T07 — Retry, idempotence a všechny vedlejší účinky

**Soubory:** `src/local_ai_hub/client.py`, `http_server.py`, `commands.py`, `rag.py`; `tests/test_client_transport.py`, `tests/test_command_transport.py`; **nový** `tests/test_mutation_replay.py`.

- [ ] Inventář označí i index/ingest/model pull/learning/task checkpoint/cleanup jako vedlejší účinky; retrieval access metadata se popíše zvlášť.
- [ ] Automatický retry mutace povolit pouze s doloženou idempotencí/request ID; po ztrátě odpovědi vrátit známý outcome nebo explicitní nejistý stav, ne slepě opakovat.
- [ ] Klíč server journal obsahuje identitu, operaci a otisk payloadu; stejný request ID s jiným payloadem je konflikt.
- [ ] Otestovat disconnect po commit před response, process crash, retry ze dvou klientů, timeout a chybu partial publish pro RAG/work/task/command.
- [ ] GET route s maintenance side effect převést na explicitní mutující metodu; klientská read-only cesta nesmí spouštět cleanup.

**Hotovo:** žádné opakované provedení potvrzené jednorázové mutace; read cesty mají pravdivou klasifikaci.

### T08 — Agent OS atomicita, eventy a recovery

**Soubory:** `src/local_ai_hub/agent_events.py`, `agent_tasks.py`, `agent_memory.py`, `agent_blackboard.py`, `swarm.py`, `leases.py`; `tests/test_agent_state_e2e.py`, `tests/test_agent_state_reliability.py`, `tests/test_swarm_orchestrator.py`; **nový** `tests/test_agent_crash_recovery.py`.

- [ ] Event + projekci + receipt zapisovat atomicky tam, kde sdílejí DB; mezi oddělenými stores použít idempotentní reconciliation, ne tvrdit falešnou atomicitu.
- [ ] Task/swarm/blackboard update vyžaduje expected version nebo CAS; dva paralelní kroky mají jednoho vítěze a jeden konflikt bez ztraceného zápisu.
- [ ] Odstranit případné syntetické úspěšné receipt po chybě verifieru; failure musí zůstat failure.
- [ ] Pubsub napojit na app-owned durable store, pokud contract slibuje replay; zavést sequence cursor, restart replay a explicitní retention/overflow gap.
- [ ] SSE subscribe/replay race, disconnect, slow consumer a queue overflow musí mít test; ztrátu událostí nelze tiše maskovat.
- [ ] Rozlišit disposable derived SQLite od durable tasks/memory. Schema mismatch durable DB vyžaduje zachování/zálohu a explicitní recovery; nepřidávat nepovolené migration shimy.

**Hotovo:** crash během každé write fáze se rekonciluje; všechny potvrzené durable změny přežijí restart.

### T09 — Ověřovací receipts, worktree ownership a evidence

**Soubory:** `src/local_ai_hub/agent_verification.py`, `agent_tasks.py`, `work_orchestrator.py`, `worktrees.py`, `process_utils.py`, `evidence.py`, `evidence_contract.py`; `tests/test_agent_verification.py`, `tests/test_work_orchestrator.py`; **nový** `tests/test_verified_handoff.py`.

- [ ] Completion vyžaduje skutečný úspěšný receipt pro každé kritérium, odpovídající revizi/mutation generation a správného vlastníka; DB lookup failure nesmí projít.
- [ ] Zavést typ důkazu pro test/benchmark/source review; nenutit neexistující command ID do dokumentačního úkolu, ale nikdy nepřijímat modelové hodnocení jako test výsledek.
- [ ] Work orchestrator napojit na stejnou verification gate; starý receipt po změně kódu je neplatný.
- [ ] Worktree evidovat s task/owner/repo/path/branch/TTL; cleanup jen vlastněné validované worktree, bez force odstranění uživatelských změn. Při redesignu zachovat explicitní oddělení logické lease a fyzického checkoutu.
- [ ] Otestovat stale receipt, missing receipt, DB unavailable, spoofed pass, cancelled task, cizí worktree a dirty cleanup.

**Hotovo:** žádný handoff jako completed bez důkazu všech kritérií; worktree lifecycle je dohledatelný.

### T10 — Repository, AST, graph a adaptivní retrieval

**Soubory:** `src/local_ai_hub/retrieval.py` (probíhající práce), `repo_tools.py`, `deterministic.py`, `code_index.py`, `preprocess.py`, `services.py`; `tests/test_adaptive_retrieval.py`, `tests/test_repo_topology.py`, `tests/test_affected_tests.py`, `tests/test_cross_repo_federation.py`.

- [ ] Převzít a ověřit existující adaptive retrieval podle jeho plánu; vyřešit ownership před změnou stejných souborů.
- [ ] Profilovat scan/parse/SQL/graph a odstranit opakované čtení. Reuse content hash a incremental invalidation import/call závislostí; změna stejné velikosti a mtime musí být zachycena.
- [ ] Query plán vybírá relevantní backends podle confidence a zbývajícího deadline; drahé optional backends nesmí běžet bez přínosu pro kvalitu.
- [ ] Výsledky uvádějí backend, fallback, freshness, coverage/truncation a přesnou evidence; syntax failure nesmí vypadat jako úplný prázdný nález.
- [ ] Pro symbols/callers/dead code/affected tests/impact/cross-repo/API spec/invariants vytvořit language a framework fixtures podle skutečně deklarované podpory, včetně negativních případů.
- [ ] Změřit built-in/Serena on/off/crash/timeout a regressions současného retrieval; žádný marketingový „100% exact“ bez kvalifikačního rozsahu. CodeGraphContext nemá Hub benchmark ani runtime stav.

**Hotovo:** vyšší nebo shodná retrieval kvalita; splněná latency/coverage matice; nepodporované syntaxe pravdivě označené.

### T11 — RAG, embeddings, reranking a ingestion

**Soubory:** `src/local_ai_hub/rag.py`, `embeddings.py`, `reranker.py`; `tests/test_rag_hybrid.py`, `tests/test_rag_fragment_cache.py`, `tests/test_rag_dedup.py`, `tests/test_embedding_cache.py`; **nový** `tests/test_rag_quality_contract.py`.

- [ ] Změřit O(N) vector scoring a peak memory; nejdříve batch/vectorized scoring a bounded candidate retrieval, ANN zavést jen pokud benchmark prokáže potřebu i zachování recall.
- [ ] Indexování oddělit na bounded embed fázi a atomický publish; zrušení nesmí zveřejnit nekompletní index.
- [ ] Cache/embedding key zahrnuje model digest, backend, dimension, normalization a revision; fallback embedding nesmí kontaminovat jiný embedding prostor.
- [ ] `embedded`, `reranked`, `degraded` musí vyjadřovat skutečný backend výsledek; zero vector není úspěšný embedding.
- [ ] Explicitní ingest content/title/metadata/image/caption přes existující tool schema; docsets bez prázdných names; raster diagram popsat jako metadata-only nebo doplnit explicitní vision/OCR s provenance.
- [ ] Ověřit relevance golden corpus, near-duplicate edge cases, busy retry bez opakovaného embeddingu, disk full a concurrent publish.

**Hotovo:** bounded paměť, správná degradace, replay bezpečnost T07 a zlepšené změřené retrieval parametry.

### T12 — Model routing, scheduling, batch a inference

**Soubory:** `src/local_ai_hub/router.py`, `model_policy.py`, `scheduler.py`, `ollama.py`, `llama_cpp.py`, `hardware.py`, `services.py`; `tests/test_router.py`, `tests/test_local_model_availability.py`, `tests/test_completion_model_routing.py`, `tests/test_model_quality.py`.

- [ ] Vycházet z aktivního integrated/balanced/high/max profilu; nenutit jeden model do všech zařízení.
- [ ] Změřit resident model reuse, load thrashing, batch bucketing, token prefill, queue age a fairness; následně upravit admission/backpressure/concurrency s VRAM limity.
- [ ] Deadline propagovat přes transport, queue, model load a generation; cancellation uvolní kapacitu i subprocess/socket.
- [ ] Fallback viditelně označí model/backend/quality změnu; cloud zůstává explicitní opt-in. Neobcházet quality floor kvůli rychlosti.
- [ ] Fixní eval corpus pro reason/review/compress/complete/scaffold; structured outputs validovat, compression musí zachovat fakta/evidence/nejistotu.
- [ ] Batch vrací stabilní pořadí, per-item outcome a partial failures; bounded concurrency místo nekontrolovaného spuštění všech modelů.

**Hotovo:** pro každý hardware profil doložené quality/latency/VRAM výsledky a úspěšný overload/cancel/fallback scénář.

### T13 — Async jobs a conversations

**Soubory:** `src/local_ai_hub/async_jobs.py`, `services.py`, `client.py`, `http_server.py`; `tests/test_async_jobs.py`, `tests/test_async_jobs_tasks.py`, `tests/test_delivery_policy.py`, `tests/test_conversations.py`.

- [ ] Zveřejnit přesný async-supported subset; sync/async/auto cold-start pravidla sdílet mezi docs a handlerem.
- [ ] Job identity, expiry, result artifact, cancel acknowledgement a timeout jsou stejné přes MCP/HTTP/client.
- [ ] Reconcile running jobs po restartu; mutující job neopakovat bez T07 kontraktu; výsledek nesmí zmizet před svou deklarovanou retention.
- [ ] Conversations: model pinning, tenant/trust scope, jeden aktivní turn, prompt budget, expiry a restart-loss explicitně dokumentovat.
- [ ] Otestovat submit/disconnect/wait/result/cancel/restart, empty/expired conversation, duplicated continuation a 16-item batch s jednou chybou.

**Hotovo:** lifecycle má deterministický stav po chybě i restartu; klient nemusí agresivně pollovat.

### T14 — Context budget, artifacts, cache a token accounting

**Soubory:** `src/local_ai_hub/response_budget.py`, `context_ledger.py`, `agent_context.py`, `artifacts.py`, `evidence.py`, `mcp_server.py`, `services.py`; `tests/test_mcp_response_budget.py`, `tests/test_mcp_compact_transport.py`, `tests/test_evidence_contract.py`, `tests/test_projection_extra_fields.py`.

- [ ] Cache/context identity musí obsahovat všechny sémanticky relevantní vstupy: root/revision/identity/task/phase/focus/preload/config/model/memory revision podle operace.
- [ ] Invalidation testy oddělit od transport reuse pointeru; pointer má použitelné ID, freshness a způsob materializace.
- [ ] Hard budget měřit na skutečně emitovaném výsledku včetně envelope; chráněné error/evidence fields zachovat, payload dát do artifact store.
- [ ] Artifact JSON sections respektují offset; explicitní put/get/TTL/storage limit; binary metadata a MIME/hash/tenant kontrola podle kontraktu.
- [ ] Token savings počítat jen vůči doloženému baseline; protocol cost, schema exposure a local compute reuse odděleně, signed delta včetně záporných hodnot.

**Hotovo:** žádná false cache reuse, obálka drží limit, delta retrieval funguje, metriky nepřehánějí úsporu.

### T15 — Výkon command brokeru, validace a streaming

**Soubory:** `src/local_ai_hub/commands.py`, `services.py`, `agent_events.py`; `tests/test_command_streaming.py`, `tests/test_command_transport.py`, `tests/test_speculative_lint.py`; **nový** `tests/test_command_concurrency_contract.py`.

- [ ] Po T06/T07 profilovat startup shellu, command classification, repo fingerprint a capture; preferovat structured argv a levné incremental fingerprints.
- [ ] Cache pouze repeatable results se správnou environment/toolchain/revision identitou; mutation/cache/single-flight pravidla testovat zvlášť.
- [ ] Affected-test selection musí porovnat vybranou sadu s úplným známým dependency graph; nejistota rozšiřuje testy, ne tiše snižuje pokrytí.
- [ ] Preflight nesmí neočekávaně tvořit bytecode v read-only režimu; compile/build validace zůstává explicitně side-effecting.
- [ ] SSE má bounded queue, line rate, drain, dropped counter a cursor recovery; slow consumer nesmí blokovat child stdout/stderr.
- [ ] Otestovat timeout, cancel, prompt hang, stderr flood, daemon restart, mock port collision a flaky detection na disposable prostředí.

**Hotovo:** zachovaná správnost validace, rychlejší opakované běhy a žádná zablokovaná pipe/orphan process.

### T16 — Whole-task orchestration a kvalitní handoff

**Soubory:** `src/local_ai_hub/work_orchestrator.py`, `worktrees.py`, `agent_verification.py`, `generator.py`; `tests/test_work_orchestrator.py`, `tests/test_worktree_discovery.py`, **nový** `tests/test_work_handoff_acceptance.py`.

- [ ] DAG plán validovat před execution: cykly, neznámé kind, duplicity IDs, limity edits/commands/budget, explicitní acceptance.
- [ ] Izolaci volit podle mutation scope; běžný shared dirty checkout nesmí být automaticky disposable worktree.
- [ ] Paralelizovat pouze nezávislé DAG nodes s disjunktními leases; semantický planner neobchází policy.
- [ ] Napojit T09 receipts, mutation generation a artifact provenance na konečný handoff; `cancel/continue` respektují journal/recovery.
- [ ] Ověřit jeden celý edit/test/review/handoff v disposable repo plus fail/repair/cancel/crash/queue-full scénáře.

**Hotovo:** skutečný měřený E2E handoff, ne pouze modelový JSON s `verified=true`.

### T17 — Browser, vision, audio a generativní pomocné featury

**Soubory:** `browser_bridge/background.js`, `browser_bridge/capture.js`, `src/local_ai_hub/browser_bridge.py`, `services.py`, `features.py`; `tests/test_browser_bridge.py`, `tests/test_http_vision_routes.py`, `tests/test_vision_service.py`; **nový** `tests/test_transcription_contract.py`.

- [ ] Browser capability/stage/commit/abandon: test reálné Chrome/Edge instalace, změny tabu/navigation, expiry, duplicated commit a partial artifact failure.
- [ ] Vision findings uvádějí evidence z obrazu/DOM a confidence; grounding testy odhalí vymyšlené elementy. Jasné on/off/model-missing behavior.
- [ ] Transcribe respektuje požadovaný model, oddělí missing CLI/nonzero/timeout od úspěšného přepisu; metadata-only fallback nevrací úspěšnou transkripci.
- [ ] Whisper output pouze do task-owned temp/state; otestovat cleanup, cancellation, nevalidní audio, multilingual samples a word error rate.
- [ ] Scaffold/complete/speculative draft oddělují návrh od validovaného výsledku; validaci spouštět dle explicitní command permission.
- [ ] Rules/dataset/profile digest/mocks/types hodnotit proti dokumentovaným formátům, determinismu a validním parserům, ne podle neprázdného řetězce.

**Hotovo:** browser acceptance a podporované multimodal backendy doloženy; unavailable není zaměněno za quality success.

### T18 — Status, dashboard, telemetry a administrace

**Soubory:** `src/local_ai_hub/app.py`, `telemetry.py`, `debug_traces.py`, `dashboard.py`, `http_server.py`; `tests/test_debug_traces.py`, `tests/test_http_phase_telemetry.py`, `tests/test_http_admission.py`; **nový** `tests/test_operational_api_contracts.py`.

- [ ] Zrušit zbytečné status dependency calls; oddělit cached snapshot od explicitního expensive detail; každá dependency má deadline/degraded field.
- [ ] Clamp days/limits, správná recent timeline/cursor, pagination trace detail a response size cap; not-found má konzistentní status.
- [ ] Dashboard polling přizpůsobit visible tab, unchanged state, backoff a jitter; tam kde přínos prokáže měření využít existující SSE.
- [ ] Accounting vrací accepted/rejected counts a důvody; load telemetry nesmí měřit sama sebe jako uživatelský workload.
- [ ] Zachovat explicitně chtěný full-payload trace workflow; nastavit oddělené access/retention/redaction a viditelné informování. Nezaměnit trace/content stores s metadata-only telemetry.
- [ ] DB query má read-only authorizer i time/row/byte budget. Maintenance/config/control/model manage/bundle import mají action-specific oprávnění, bounded lifecycle a audit.

**Hotovo:** stabilní lehký status pod zátěží, bezpečně bounded admin operace, pravdivé privacy a accounting chování.

### T19 — Instalace, Python/CLI, dokumentace a rollout

**Soubory:** `tools/setup.py`, `tools/doctor.py`, `tools/hubctl.py`, `src/local_ai_hub/client.py`, `generator.py`, `features.py`, `pyproject.toml`, `install.ps1`, `install.sh`, `docs/HTTP_API.md`, `docs/MCP_AND_AGENTS.md`, `docs/INSTALL_PROMPT.md`, `docs/UPDATE_PROMPT.md`; `tests/test_surface_and_packaging.py`, `tests/test_feature_surface_parity.py`, `tests/test_release_contract.py`.

- [ ] Vygenerovat API/MCP/client coverage docs z T01/T03; documentovat payload/status/timeout/side effects/backend availability pro každý řádek.
- [ ] Klientské convenience metody přidat jen pro skutečně chybějící veřejné případy; payload mapping test porovnává s reálným handlerem. Provést usability scénáře: najít caller, získat kvalitní kontext, ověřit změnu, pokračovat v konverzaci, zrušit job, obnovit task a najít důkaz; měřit first-call success, počet potřebných volání a srozumitelnost chyb.
- [ ] Clean-host Windows/Linux install, core-only i podporované optional extras; chybějící Tree-sitter/Whisper/OpenVINO/Serena musí mít přesný doctor výsledek. CodeGraphContext/KuzuDB není Hub runtime ani doctor backend; v dokumentaci může být jen jako samostatný externí nástroj.
- [x] Config merge dvakrát je idempotentní a zachovává cizí entries; per-host manifest parse + skutečný MCP handshake, kde host dostupný.
- [x] Změny flags/models/policy/schema promítnout současně do INSTALL_PROMPT a UPDATE_PROMPT, generatoru a generated manifest testů.
- [ ] Rollout po doménách s quality/latency comparison a rollback na předchozí kód/config. Durable state před změnou zálohovat; nevracet starý kód proti nekompatibilní DB bez recovery postupu.

**Hotovo:** vydaný balík obsahuje správné závislosti/soubory, docs odpovídají runtime a upgrade je reprodukovatelný.

### T20 — Release acceptance všech operací

**Soubory:** `tools/release_check.py`, `tools/selftest.py`, `docs/TESTING.md`, `docs/FEATURE_AUDIT_V4.md`, **nový** `docs/API_COVERAGE.md`; využít testy a benchmarky T01–T19.

- [ ] Před release porovnat inventář s aktuální revizí: všechny rows mají test result, owner, measurement a disposition; každá výjimka konkrétní důvod a uživatelsky pravdivý unavailable výsledek.
- [ ] V izolovaném prostředí provést povinné projektové kontroly přes `local_ai_command`; uložit exit code, revizi a log artifact.
- [ ] Provést live HTTP/MCP/HubClient shodu, auth/body/feature negatives, backend outage/fallback, restart recovery a concurrency matice.
- [ ] Zátěž alespoň 60 minut mixed workload; restart/crash fault injection odděleně. Změřit memory/queue/process growth a reconciliation.
- [ ] Porovnat výkon i kvalitu s T02, provést nezávislé correctness/security review a uzavřít potvrzené P0/P1.
- [ ] Agent OS `verify_completion` musí projít s receipts odpovídajícími skutečné závěrečné revizi; potom task_complete a release report.

Povinné commands z kořene, každý samostatně přes broker:

```text
python tools/release_check.py
python -m compileall -q src mcp tools tests
python -m pytest -q
python tools/selftest.py
```

Instalovaná instance: `python tools/doctor.py` a `python tools/hubctl.py status`. Předem ověřit cestu `mcp` v konkrétním checkoutu; chybějící cestu nesmí wrapper vydávat za splněnou kontrolu. Compileall/build/pytest mohou zapisovat; patří do explicitně vlastněného validačního prostředí.

#### Kandidátní T19 evidence — 2026-09-27 (není T20 release acceptance)

- Historický wheel `local_ai_hub-4.0.0-py3-none-any.whl`, SHA-256 `2abb3aa960df532c3cdee19a925e8f2ff911d221212bd9a9be4766d8568c89aa`, měl při dřívějším inventory hlášenou shodu 103/103 souborů. Nový doctor smoke z aktuálního checkoutu ale v čistém venv skončil `ImportError: cannot import name 'managed_serena_executable'`; wheel je stale vůči současnému `doctor_support.py`. Následující core/extras instalace z tohoto wheelu jsou historické, ne důkaz aktuálního kandidáta.
- Windows core-only venv (`$venv = Join-Path $env:TEMP 't19-win-core-20260927'`, `$py = Join-Path $venv 'Scripts\python.exe'`, `$wheel = Join-Path $env:TEMP 't19-current-wheel-9_mybaeo\wheel\local_ai_hub-4.0.0-py3-none-any.whl'`): `python -m venv $venv`; `& $py -m pip install --disable-pip-version-check --no-warn-script-location $wheel`; `& $py -m pip check`; `& $py -c "import local_ai_hub; print('import=ok')"`. Výsledek: instalace exit 0, `No broken requirements found.`, `import=ok`.
- Ve stejném venv běželo `& $py -m pip install --quiet --disable-pip-version-check "${wheel}[local-nlp,intel-accelerators,token-economy,performance,profiling,dev]"`; exit 0. `& $py -m pip check` hlásí `No broken requirements found.`; metadata kontrola vrací `extras_present=13/13`. Předchozí core-only výsledek zůstává zaznamenán, finální venv už obsahuje extras.
- Windows source bootstrap přes izolovaný `tools/setup.py`: `python tools/setup.py --config %TEMP%\t19-setup-core-72266c2880\config.toml --profile cpu --skip-model-pull --skip-local-nlp-preload --skip-tools --skip-agent-config --skip-service --skip-ollama-install --skip-token-economy --skip-companion-skills` — exit 0; fresh venv `pip check` clean, `import=ok`, 11 kontrolovaných optional/dev distribucí absent. Config cílil jen na temp install/state/port; MCP host config a model pulls vypnuté. `setup.log` a config zůstávají v `%TEMP%\t19-setup-core-72266c2880`; wrapper `install.ps1` ani managed-service instalace tímto smoke neprošly.
- Zjištěná bezpečnostní odchylka `--skip-service`: setup přesto spouštěl globální `hubctl.py restart`. Regresní test `tests/test_setup.py::test_setup_skip_service_does_not_restart_hub` před opravou selhal a po guardu prošel; skip nyní neinstaluje ani nerestartuje službu. Isolated setup proto neběžel proti sdílené službě.
- Z instalovaného core venv, s `PATH` omezeným na venv a Windows systémové adresáře, `doctor.py --json` skončil exit 0: `hub_online=false`, `tree_sitter=false`, `whisper_cli=false`, OpenVINO `requested=false/installed=false`, `code_intelligence=null`. JSON je v `%TEMP%\t19-setup-core-72266c2880\doctor-isolated.json`; offline běh nedokazuje dostupnost ani absenci Serena.
- Generovaný generic `mcp-servers.json` z izolovaného setupu prošel skutečným stdio MCP `initialize` + `tools/list`: protocol `2025-11-25`, `Local AI Hub (compact)`, 8/8 nástrojů. Klient v `%TEMP%\t19-setup-core-72266c2880\mcp_handshake.py`, surový výstup `mcp-handshake-manifest.log`. Trvalý fixture `tests/test_mcp_stdio_handshake.py` generuje manifest entry a opakuje handshake; neověřuje host UI/config instalaci ani tool call proti běžícímu Hubu.
- Aktuální MCP transport běh: `python -m pytest -q --tb=short tests/test_mcp_stdio_handshake.py` — **15 passed in 31.09s**. Test provádí initialize + úplný paginovaný tools/list pro osm agent profilů a pro sloučené JSON, VS Code/Copilot a Codex TOML host manifesty; Antigravity používá skutečný Gemini profil z setup helperu. Každý výsledek uvádí stejných 8/8 nástrojů; command/args/cwd/config/env zůstávají host merge výstupem. Ověřen protokol a parsované host entry, ne spuštění host aplikace/UI.
- Owner-reported probe (temporary command/log artifact not retained): `tools/doctor.py --json` z dočasného probe rootu, s temp konfigurací/state directory, portem 65534 a omezeným `PATH`, skončil exit 0: `hub_online=false`, Tree-sitter installed, Whisper CLI not installed, OpenVINO installed/not requested. JSON neobsahuje `code_intelligence`; offline doctor hlásí `Status unavailable (Hub did not report backend diagnostics)` pro Serena. Chování chybějícího Serena backendu za běhu tedy neprokázáno. CodeGraphContext je standalone externí CLI/MCP nástroj a není součástí doctor výstupu.
- Owner-reported Windows `robocopy` snapshot/restore smoke (temporary fixture/log artifact not retained) použil syntetický `agent_state.sqlite3`, install/config soubor a `work_journals/`: `PRAGMA integrity_check=ok`, obnoven sentinel `before`, code/config/journal sentinely odpovídají pre-upgrade, failed snapshots zachovány. Toto dokládá kopírovací mechaniku, ne aplikací používané schema ani downgrade.
- Následný owner-run PowerShell smoke ověřil změnu `server.state_dir` mezi releasy přes `robocopy`, `Move-Item` a `Copy-Item`; výstup: `path-change-rollback=ok; old-config-and-state-restored; new-state-and-failed-install-preserved`. Temporary fixture/log nebyl zachován; smoke neověřuje aplikační schema.
- Aktuální dirty source wheel: `%TEMP%\t19-current-source-build-20260927\wheel\local_ai_hub-4.0.0-py3-none-any.whl`, SHA-256 `b35eb9f5e93d52cf255aea972e778ef40c586db3c93d8b4efea9cb7cad94ccef`; čistý temp staging dal 103/103 package souborů byte-identických se zdrojovým stromem. Core venv `%TEMP%\t19-win-core-current-20260927`: instalace exit 0, `pip check` clean, `import=ok version=4.0.0`. Oddělený extras venv `%TEMP%\t19-win-extras-current-20260927`: všech šest extras (`local-nlp`, `intel-accelerators`, `token-economy`, `performance`, `profiling`, `dev`), `pip check` clean, `extras_present=13/13`.
- Installed doctor z aktuálního wheelu, izolovaný config/state a port 65534, exit 0; redigovaný JSON v `%TEMP%\t19-doctor-windows-core-20260927\evidence-summary.json`: Tree-sitter chybí, Whisper CLI je dostupný, OpenVINO chybí a nebyl požadován, Serena executable chybí. Backend runtime status má `available=false, reason=hub_offline`; živou absenci Serena tento offline běh neprokazuje.
- Read-only recheck retained Windows venvs: `pip show local-ai-hub` reports version `4.0.0` in both `%TEMP%\t19-win-core-current-20260927` and `%TEMP%\t19-win-extras-current-20260927`; `pip list` finds 0/13 declared extra distributions in core and 13/13 in extras. This confirms retained install metadata only, not a new install, `pip check`, or runtime test.
- Installer docs audit (2026-09-27): `docs/INSTALLATION.md` lists `auto` with the other profiles and documents effects of all eight setup skip flags, matching `tools/setup.py`, `install.ps1` parameters, and `install.sh` parser/help. The descriptions distinguish Ollama pulls, local NLP prefetch, generated manifests, service setup and managed llama.cpp provisioning. The installed-instance verification block now uses `doctor.py` and `hubctl.py status`, plus a cross-platform `/health` version assertion against installed package metadata; `hubctl.py clean` is identified as cache/build cleanup, not verification. Static source comparison only; wrapper install was not rerun.
- Package extras documentation audit (2026-09-27): `docs/INSTALLATION.md` now lists all six extras and exact declared packages from `pyproject.toml`, with generic and combined install syntax. Static metadata comparison only; no package install was run for this change.
- Retained PowerShell rollback smoke `%TEMP%\t19-rollback-smoke-20260927.ps1`, receipt `%TEMP%\t19-rollback-smoke-20260927\receipt.json`: path-change rollback restored old code/config/host MCP config, SQLite row `before` and journal; `PRAGMA integrity_check=ok`; failed install, old/new state, changed host config and backup preserved (10/10 checks). Isolated synthetic schema, service stop skipped; no live Hub database or previous-version runtime.
- `docs/OPERATIONS.md#upgrade-backup-and-rollback` now documents stopped-service snapshots of prior code/environment, config, host MCP configs and the entire state directory, plus unit restore while preserving failed post-upgrade copies. This supplies the recovery procedure, not proof of a real rollback: the smoke used synthetic SQLite state and did not exercise an application schema migration or previous-version runtime.
- Current-source synthetic benchmark offline smoke: 100 files, 1,000 RAG chunks, 3 repetitions, concurrency 1; `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, isolated empty `HF_HOME`; exit 0, `success=true`, quality 100, stderr 0. Record is `%TEMP%\t19-bench-offline-current-20260927\state\surface-benchmark-1790533857593211900.json`; readiness remains `per_case` with sample/matrix reasons, so this is not T02 acceptance. Same no-`--inference` benchmark without offline flags emitted an unauthenticated HF Hub request and was canceled without a record. Runner config omits model/feature overrides; app inherits `embedding_backend=sentence-transformers`, `features.rag=true`, and `features.reranker=true`, which can trigger remote model lookup during its context-pack stage.
- Pre-T19 HEAD offline benchmark result `%TEMP%\t19-bench-head-100-10000-offline-state-20260927\runner-output.json` and record `%TEMP%\t19-bench-head-100-10000-offline-state-20260927\surface-benchmark-1790539351626845800.json`: `success=false`, failed stage `hub_queue_admission`; measurement `async_jobs_submit_cancel_admission_only`, 53,000 admissions, 183 `RuntimeError` failures (0.345%). Per concurrency: 1=20/1,000, 4=16/4,000, 16=63/16,000, 32=84/32,000. `stderr.log` is empty. Runner catches exceptions and records only the exception class; unsuccessful submit/cancel results also become generic `RuntimeError`, so this receipt cannot distinguish those failure causes. This is a failed per-case result, not a T02 comparison or T19 rollout acceptance; no candidate comparison was run.
- Linux: `wsl.exe --status` hlásí Ubuntu 2, ale `wsl.exe -d Ubuntu --exec python3 -c ...` opakovaně končí `Wsl/Service/E_UNEXPECTED`; Docker Desktop API nedostupné/time-out. Pokus o skryté spuštění Docker Desktop a bounded `docker --context desktop-linux info` skončil timeoutem po 15 s; Linux instalace neprovedena. Host recheck: `podman`, `nerdctl`, `qemu-system-x86_64`, `VBoxManage`, `vmrun` a `multipass` nejsou instalované; jiný místní Linux runtime nenalezen.
- Předchozí targeted raw běhy nad stejným kódovým stavem (od té doby jen doc edits): `python tools/surface_inventory.py --check --task-id 01a0d30b-fffc-7810-a1ca-9cdde7be9264` — 675 řádků, drift prázdný; `python -m pytest -q --tb=short tests/test_surface_inventory.py` — 704 passed; `python -m pytest -q --tb=short tests/test_client_sdk_routes.py tests/test_conversation_continue_route_contract.py` — 6 passed; `python -m pytest -q --tb=short tests/test_setup.py tests/test_t19_setup_manifests.py` — 43 passed; `python -m pytest -q --tb=short tests/test_release_contract.py` — 16 passed; `python -m pytest -q --tb=short tests/test_surface_and_packaging.py tests/test_feature_surface_parity.py` — 19 passed. Jde o raw lokální běhy, bez Hub receipts.
- Aktuální sloučený T19-targeted běh po host handshakes, prompt/schema assertions a SDK recovery testu: `python -m pytest -q --tb=short tests/test_surface_inventory.py tests/test_surface_and_packaging.py tests/test_feature_surface_parity.py tests/test_release_contract.py tests/test_setup.py tests/test_t19_setup_manifests.py tests/test_client_sdk_routes.py tests/test_conversation_continue_route_contract.py tests/test_doctor_support.py tests/test_mcp_stdio_handshake.py tests/test_python_sdk_docs.py` — **811 passed in 56.33s**. Vybraný slice nenahrazuje celý suite ani T20 release acceptance.
- Aktuální rerun po coverage drift opravě a odebrání CodeGraph runtime: stejný T19-targeted pytest příkaz skončil **817 passed in 57.21s**; `surface_inventory.py --check` potvrdil 675 řádků, `coverage_matches=true`, `drift=[]`.
- CodeGraph removal slice: focused runtime/config/preprocessing tests skončily **133 passed, 13 skipped in 60.72s**. Skips jsou staré CodeGraph integration scénáře; aktivní testy ověřují ignorování stale flagu a odmítnutí backendu. Serena zůstává jediným Hub-managed code-intelligence backendem. CodeGraphContext zůstává standalone externí CLI/MCP nástroj.
- Prompt/generator contract test rozšiřuje `test_public_contract_notes_match_install_update_and_generated_skill`: plný synthesis caveat musí sedět v obou promtech, v generated skill i MCP docs; `write_all_generated` výstup musí parsovat generic a VS Code/Copilot manifesty a RAG schema musí deklarovat obě ingestion actions i jejich vstupní properties. Model routing v tomto candidate diffu změněn nebyl.
- Aktuální audit coverage kontraktu: `python tools/surface_inventory.py --check --task-id 01a0d30b-fffc-7810-a1ca-9cdde7be9264` — `coverage_matches=true`, 675 řádků, `drift=[]`. `test_operation_contract_metadata` vyžaduje pro každý řádek payload, response, status, timeout, side effects, backend availability a explicitní evidence/gaps. Hodnoty označené jako `unverified` zůstávají otevřenými runtime mezerami; dokumentace je nevydává za ověřené chování.
- Po schválené coverage drift opravě: `python tools/surface_inventory.py --write-doc --task-id 01a0d30b-fffc-7810-a1ca-9cdde7be9264` zapsal 675 řádků, `drift=[]`; následný `--check` potvrdil `coverage_matches=true`. Regresní test `test_root_inventory_resolves_imported_actions_and_redacted_pack_route` — 1 passed in 4.73s. Jde o parser/drift důkaz, ne o uzavření kontraktu `/api/context/pack`.
- Coverage contract review našel všechny povinné oblasti v 675 renderovaných řádcích. Dva `/api/context/pack` HTTP řádky mají `status_codes=[]` a explicitní contract gap, protože extractor záměrně nečte handler body; metadata proto přesně označují neověřený status. V žádném řádku se nevyvozuje runtime dostupnost backendu z registrace.
- Coverage řádky `/api/context/pack` zůstávají otevřené a Agent 2-owned; jejich handler body nebylo inspektováno. Proto první T19 coverage kritérium zůstává nezaškrtnuté, i když aktuální `--check` vrací 675 řádků bez generovaného driftu.
- SDK recovery update: `docs/PYTHON_SDK.md` nyní říká, že `task_resume` nastaví `ACTIVE`, zachová checkpoint metadata a neobnoví pracovní soubory. Nový route assertion porovnává vrácený checkpoint; dokumentační test pokrývá terminální invalid mode, expired conversation a duplicitní continuation guidance. `HubClient` zachová text HTTP chyby a normalizuje status/retry pole; recovery text uvádí doporučenou akci před protokolovými poli. Jde o úpravu dokumentace, ne o měření lidské srozumitelnosti, které zůstává otevřené.
- `test_sdk_convenience_methods_map_to_production_http_handlers` uses an in-process loopback HTTP server and actual `Handler.do_POST`, verifies route/payload mapping for callers, context_pack, cancel_job, and get_evidence; service boundaries are stubbed, so this test alone does not prove retrieval. Earlier combined SDK/conversation/docs run: 8 passed, 1 failed. `test_sdk_docs_explain_resume_state_and_failure_recovery` expects `Wait for the original continuation to finish; do not send a duplicate prompt.` Current `docs/PYTHON_SDK.md` wording is `A continuation is already running. Wait for it to finish; do not send a duplicate request.`; mismatch is wording-level, not missing recovery guidance. File remains T21-owned; do not edit until ownership is released.
- Additional SDK context E2E 2026-09-28: `test_context_pack_returns_indexed_evidence_from_real_fast_context` and `test_adaptive_context_pack_returns_grounded_indexed_evidence_offline` each passed; complete `tests/test_client_sdk_routes.py` passed 5/5. Both use production loopback HTTP routing + real indexed TOML evidence. Adaptive case asserts `quality_first=true`, deterministic + lexical backends, one endpoint request; RAG and external Serena are disabled for bounded offline execution. This proves grounded deterministic/adaptive fallback, not live RAG/Serena/model quality.
- SDK config contract check: `HubClient.__init__` forwards explicit `config_path` to `load_config`; omitted path consults `LOCAL_AI_CONFIG`, then existing installed home config, then source-checkout `config.toml`, then the home path default. T19-owned `docs/INSTALLATION.md` now documents this exact selection; `tests/test_release_contract.py` passes 16/16. `docs/PYTHON_SDK.md` still omits the source-checkout fallback and remains T21-owned. No path-hint persistence is claimed.
- T20 povinné `python tools/release_check.py`, `python -m compileall -q src mcp tools tests`, `python -m pytest -q`, `python tools/selftest.py` v této revizi neběžely; T19 kandidátní evidence není jejich náhradou.
- Skutečný `install.ps1` Windows core-only smoke proběhl v `%TEMP%` s dočasným `config.toml`; wrapper exit 0, instalované `.venv` `pip check` exit 0 (`No broken requirements found.`), import `local_ai_hub` OK. Důkazy zůstávají v `%TEMP%\t19-installps-smoke-809d108a441440f387e6fc6d71677281`; repo `config.toml` po běhu odstraněn. Managed service, host config a modely byly vypnuté; doctor správně hlásil Hub offline.
- Windows recheck 2026-09-28: current-source wheel SHA-256 `b35eb9f5e93d52cf255aea972e778ef40c586db3c93d8b4efea9cb7cad94ccef` zůstává byte-identický se zdrojem 103/103 souborů; METADATA uvádí verzi 4.0.0 a všech šest extras. Retained core/extras venv: oba `pip check` clean a `import=ok version=4.0.0`.
- Isolated Windows core-only doctor probe `%TEMP%\t19-doctor-missing-20260928`: current installed wheel + temporary config, doctor JSON exit 0; `tree_sitter=false`, `whisper_cli=false`, OpenVINO `requested=false/installed=false`, code intelligence unavailable (`hub_offline`). `tests/test_doctor_support.py`: 10 passed, covering missing/installed optional status formatting, synthetic missing Serena, and Hub-offline output. Hub service was offline; copied doctor lacked repo MCP surface, so this is optional-component diagnostic evidence, not installed-service acceptance. Live Serena availability remains unverified.
- Isolated Windows extras doctor probe using retained `%TEMP%\t19-win-extras-current-20260927` venv and same temporary config: JSON exit 0, `tree_sitter=true`, `whisper_cli=false`, OpenVINO `requested=false/installed=true`; code intelligence unavailable (`hub_offline`). Confirms installed extras change parser/OpenVINO presence while Serena and live backend state remain unverified.
- Configured-but-missing OpenVINO doctor probe `%TEMP%\t19-doctor-openvino-requested-20260928`: core-only venv, `models.embedding_backend="openvino"`; doctor JSON exit 0, OpenVINO `requested=true/installed=false`, exact CPU-fallback warning returned. Hub remained offline; copied doctor lacked repo MCP surface, so this verifies diagnostic output only.
- CodeGraphContext/KuzuDB audit 2026-09-28: installation, operations, troubleshooting, dashboard, and MCP docs describe standalone external tooling; setup/config/generator/doctor do not register or manage it. `tests/test_codegraph_package_policy.py`: 3 passed, including stale config flag ignored and unknown backend unavailable.
- Linux recheck 2026-09-28: WSL `--status`/`--list --quiet` succeed, but `wsl.exe -d Ubuntu --exec python3 -V` still fails `Wsl/Service/E_UNEXPECTED`. Docker Desktop was installed and started hidden; Linux engine pipe appeared, but `docker info --format '{{.ServerVersion}}'` remained blocked for 58s and was interrupted (exit 1). Docker Desktop remains running; Linux install is still unverified. Podman, nerdctl, QEMU, VirtualBox, VMware, and Multipass were absent in the earlier host check.
- Offline same-host rollout smoke, 100 files/1,000 RAG chunks, 30 light + 30 paired samples, concurrency 1: HEAD record `%TEMP%\t19-head-bench-smoke-20260928-state\surface-benchmark-1790556200307848400.json` má quality 100 %, `hub_queue_admission` 1/30 `RuntimeError` a `success=false`; current record `%TEMP%\t19-candidate-bench-smoke-20260928-state\surface-benchmark-1790556341850888700.json` má quality 100 %, 0 queue errors a `success=true`. Shodné benchmark/config/hardware fingerprints. Exploratory p95: context 2045.532 → 2167.966 ms (+6.0 %), queue 149.632 → 159.700 ms (+6.7 %). `compare_records` správně vrátil `incomparable`, protože HEAD neprošel stage gate; toto není přijatelná release comparison.
- HEAD diagnostic run s 1,000 light + 30 paired samples, concurrency 1/4, skončil `success=false`, `hub_queue_admission` 30 `RuntimeError`; record `%TEMP%\t19-head-bench-paired-20260928-state\surface-benchmark-1790556007459972800.json`. Vyšší počet vzorků potvrdil baseline queue failure, nepřinesl validní comparator baseline.
- App-state rollback smoke `%TEMP%\t19-app-db-rollback-20260928\receipt.json`: HEAD `LocalAIApp` vytvořil task ve skutečném agent-state schema; current source jej otevřel a zapsal candidate-only task; snapshot/config restore vrátil HEAD app. 8/8 kontrol prošlo, původní task obnoven, candidate task odstraněn, failed state i backup zachovány, všech 17 SQLite DB prošlo `PRAGMA integrity_check`. Izolovaný app-generated stav; bez live managed service a produkčního DB.
- Coverage drift repair 2026-09-28: inventory parser now resolves imported `local_ai_status` action aliases and registered dynamic `POST /api/context/pack`; regression coverage added, `docs/API_COVERAGE.md` regenerated. `surface_inventory.py --check --task-id 01a0d30b-fffc-7810-a1ca-9cdde7be9264` reported 675 rows, `drift=[]`; focused test file reported 704 passed. Two `/api/context/pack` status-code values remain unknown and handler remains Agent 2-owned; T19 full coverage criterion stays open.
- SDK usability scenarios 2026-09-28: produkční handler + deterministic fallback našel caller; konverzace použila skutečný store/handler s generátorem stubnutým v testu; cancellation zrušila queued job ve skutečném manageru; `get_evidence` načetl skutečný store záznam. Caller, context, conversation, cancel, evidence, resume a receipt testy ověřují očekávanou route; `tests/test_client_sdk_routes.py`: 9 passed. Human clarity remains unmeasured.
- SDK docs recovery assertion 2026-09-28: `docs/PYTHON_SDK.md` in the current shared checkout documents HTTP error normalization, resume behavior, retry-safe recovery text, and seven first-call workflows. `tests/test_python_sdk_docs.py`: 3 passed; current SDK route + conversation rerun: 12 passed. Human clarity remains unmeasured.
- SDK first-call/call-count evidence 2026-09-28: the current SDK scenario table maps seven workflows to seven successful first direct calls and seven HTTP POST requests total; route assertions cover one request per workflow. Current rerun of `tests/test_client_sdk_routes.py` plus `tests/test_conversation_continue_route_contract.py`: 12 passed. Context retrieval uses a stubbed fast service and conversation generation is stubbed, so this proves mapping/handler flow rather than live retrieval/model quality; human error clarity remains unmeasured.
- Queue diagnostic provenance correction 2026-09-28: the earlier 100-file/1,000-chunk run (21/5,300 `cancel_not_cancelled`) and the 12-file/20-chunk follow-up (0/1,590) imported `external user-level Local AI Hub source tree`, so neither is candidate evidence. The runner now puts its own checkout's `src` first and removes duplicate entries; a regression test with a foreign `PYTHONPATH` passes. Candidate and baseline import probes resolve respectively to `candidate checkout src/local_ai_hub/__init__.py` and `baseline checkout src/local_ai_hub/__init__.py`. Both checkouts were at `a1a82adffc069c85c2583bbcf1072944a6fdedf7`; runner SHA-256 matched (`9BE29586832A30C0575B6199B51D42AB8A4BA717317375F537362735860F2BC0`). New offline 12-file/20-chunk, 30-light/1-paired, concurrency 1/4/16/32 diagnostics both exited 0 with 0/1,590 queue errors: candidate receipt `%TEMP%\t19-queue-candidate-sourcefixed-20260928\state\surface-benchmark-1790581414483122500.json` (90,483.523 ms), baseline receipt `%TEMP%\t19-queue-baseline-sourcefixed-20260928\state\surface-benchmark-1790581512036410600.json` (78,314.529 ms). Later audit found the old fingerprint omitted imported `src/local_ai_hub/retrieval.py`; candidate removes its `codegraph: 0.0` override, so equal old hashes/revisions did not establish identical implementation. The source-wide fingerprint regression passes (`tests/test_surface_benchmarks.py`: 19 passed). A corrected offline pair now has baseline receipt `%TEMP%\t19-queue-baseline-fingerprintfix-20260928\state\surface-benchmark-1790583724936796700.json` and candidate receipt `%TEMP%\t19-queue-candidate-fingerprintfix-20260928\state\surface-benchmark-1790583812837423600.json`; config/hardware fingerprints match, source implementation fingerprints differ (`60564c57...` baseline, `6de1f038...` candidate) despite shared HEAD `a1a82adffc069c85c2583bbcf1072944a6fdedf7`. Both had 0/1,590 queue errors and 100% on the two supported quality checks. The 12-file/20-chunk/30-light/1-paired candidate comparison exited 2 with `inconclusive`; it is per-case only. A larger 100-file/1,000-chunk single-concurrency pair used 1,000 light/30 paired samples: baseline receipt `%TEMP%\t19-large-percase-baseline-20260928\state\surface-benchmark-1790584179442791600.json`, candidate receipt `%TEMP%\t19-large-percase-candidate-20260928\state\surface-benchmark-1790584291410548500.json`. Both had 0/1,000 queue errors and 100% on the two supported quality checks. Queue p50/p95 ms: baseline 30.060/51.584, candidate 30.902/41.339; context-pack p50/p95 ms: baseline 159.357/415.995, candidate 168.048/344.998. Config/hardware fingerprints matched and source implementation fingerprints differed. The comparator still exits 2 with `inconclusive` because concurrency 4/16/32, the full matrix, golden operations, and some per-regime sample minima are missing; per-case deltas are descriptive only, not rollout evidence. `tests/test_surface_benchmarks.py`: 19 passed.
- Linux runtime recheck 2026-09-28: WSL Ubuntu start skončil `Wsl/Service/E_UNEXPECTED`; host hlásí `SecondLevelAddressTranslationExtensions=False`. Microsoft uvádí SLAT jako požadavek WSL2, takže jde pravděpodobně o příčinu start failure ([Microsoft Learn](https://learn.microsoft.com/uk-ua/Windows/wsl/troubleshooting)). Docker service běžel, ale `docker version --format '{{.Server.Version}}'` nedal výstup za 15 s a proces byl přerušen. Linux instalace zůstává neověřená.
- T19 targeted rerun 2026-09-28: `tests/test_setup.py` 37 passed, `tests/test_doctor_support.py` 10 passed, `tests/test_codegraph_package_policy.py` 3 passed. Tyto testy kryjí setup/merge, synthetic doctor availability a externí CodeGraph policy; nenahrazují Linux install ani živý Hub/Serena probe.
- Windows core-only isolated install 2026-09-28: candidate package inputs copied to `%TEMP%\t19-clean-install-win-core-20260928-run2`; fresh Python 3.13.2 venv installed `local-ai-hub` 4.0.0, `pip check` clean, import resolved from venv `site-packages`, and installed CLI `--version` passed. Installed CLI `--generate` emitted 16 artifacts; all 8 JSON manifests parsed. This is an isolated venv on the existing Windows host, not a clean OS image; runtime extras were not installed. `install-report.json` and generated files remain under that temp root.
- Windows optional-extras isolated install 2026-09-28: a separate fresh venv in the same temp root installed all declared extras (`local-nlp`, `intel-accelerators`, `token-economy`, `performance`, `profiling`, `dev`); `pip check` and imports for Sentence Transformers, OpenVINO, token-economy, performance, and Scalene passed. `py-spy --version` returned 0.4.2 and `repo-map --help` passed. Not a separate clean OS image; Linux install remains unverified. `extras-install-report.json` records resolved distributions.
- Coverage contract completeness audit 2026-09-28: 675 generated rows, no malformed contract JSON; every row contains payload, a status/schema response field, timeout, side-effect and backend-availability fields. Field values still carry explicit unknown/unverified markers in 304 payload, 667 timeout, 673 side-effect and 591 backend-availability contracts; 5 rows have an empty `status_codes` value (`GET/POST /api/context/pack` and browser capture stage/commit/abandon). The browser routes dispatch through `http_server.py:2142`, using helper `status` or fallback `200 if success else 400`; capture helpers emit dynamic error statuses, so route-specific status sets still need operation-level fixtures. The two context routes remain Agent 2-owned. T19 documentation fidelity remains open pending precise contract evidence.
- Current Windows setup/packaging slice 2026-09-28: `tests/test_setup.py`, `tests/test_t19_setup_manifests.py`, and `tests/test_surface_and_packaging.py`: 56 passed. This is source/test evidence, not Linux or clean-OS evidence.
- Benchmark gate source audit 2026-09-28: `run_benchmark` records `matrix_aggregation=not_performed_single_case_record`; plan-grade comparison requires all six file/RAG size pairs, concurrency 1/4/16/32, at least 1,000 light and 30 paired samples. Only `symbols` and `context_pack` golden checks run; graph, affected tests, retrieval relevance, code generation, vision, and speech are explicitly skipped. Current per-case receipts cannot satisfy rollout comparison.
- Neuzavřeno: Linux core/extras; live missing-backend výsledky (Hub/Serena offline); human evaluation of SDK error clarity; exact status contract for `/api/context/pack` remains Agent 2-owned; valid rollout quality/latency comparison (latest distinct-source pair remains per-case; comparator is inconclusive on concurrency, matrix, and golden-operation gates). Rollback app-state smoke verifies real Hub SQLite schemas in isolation; live managed-service upgrade or production-state migration was not tested. No T20 item is satisfied or checked off by this evidence.

- Windows clean-OS runner audit 2026-09-28: `WindowsSandbox.exe` is absent; reading optional-feature state requires elevation. No clean Windows OS image is available through this host session; fresh venv installs remain host-level evidence only.
**Hotovo:** release report obsahuje skutečné výsledky, známá omezení podporovaných konfigurací a nulové neuzavřené inventární položky.

## 5. Paralelní práce a ownership

Jeden samostatný read-only auditor na inventární operaci dle požadavku uživatele; dávky maximálně do aktuálního limitu Codex subagentů. Počet současných workerů závisí i na RAM/VRAM a Hub admission. Endpoint auditor ověřuje kontrakt své operace; neduplikuje procházení celé codebase.

Implementační workery dělit podle write setu, nikoli jeden souběžný editor na každý endpoint ve stejném `http_server.py`.

| Worker | Vlastní scope | Etapy |
|---|---|---|
| A — integrátor kontraktů | mcp_server/http_server/client/features/generator + generated docs | T01/T03/T04/T19; postupné payload integrace ostatních |
| B — bezpečnost exekuce | commands/agent_policy/process_utils | T06/T07/T15 |
| C — durable Agent OS | agent_events/tasks/memory/verification/leases/blackboard/swarm | T05/T08/T09 |
| D — retrieval | code_index/deterministic/preprocess/retrieval/repo_tools | T10, koordinace s již probíhající prací |
| E — RAG | rag/embeddings/reranker | T11 |
| F — inference | router/model_policy/scheduler/ollama/llama_cpp/hardware/async_jobs | T12/T13 |
| G — evidence a provoz | artifacts/evidence/context_ledger/response_budget/telemetry/debug_traces/dashboard | T14/T18 |
| H — acceptance/integrace | benchmark fixtures, clean-host setup, browser integration, full acceptance | T02/T17/T19/T20 |

`services.py`, `app.py`, společné test fixtures, defaults a INSTALL/UPDATE prompty mají vždy jednoho aktivního editora. Ostatní dodají přesný integrační patch a test očekávaného kontraktu. Leases chrání překryvy; neumožňují přepsat cizí rozpracovanou změnu. Nezávislý review následuje po integraci, ne nad odlišnými verzemi téhož souboru.

## 6. Prováděcí cyklus každé opravy

1. Evidence: aktuální source/revision + veřejná reprodukce, dotčené rows inventáře.
2. Regresní test: konkrétní nesprávné chování musí před opravou selhat; performance změna vyžaduje baseline, nikoli křehký časový unit test.
3. Oprava nebo redesign: nejmenší řešení dosahující požadované kvality; pokud ji současná architektura omezuje, přepsat odpovědný subsystém. Explicitní owner/write set a mutation classification.
4. Ověření: focused suite přes command broker; impact/review před širší validací; žádné duplicitní commands při `in_progress`.
5. Benchmark/quality: podle dotčené domény, stejné workload/hardware/config, zahrnout studené i teplé cesty.
6. Integrace: příslušné schemas/docs/INSTALL_PROMPT/UPDATE_PROMPT, nezávislý review, receipt a checkpoint. Commitovat pouze vlastní ověřené změny v dohodnutém integračním workflow.

Jednotné očekávání testů: pozitivní případ vrací skutečný výsledek; invalid inputs 4xx bez side effects; feature off vrací explicitní unsupported; timeout/cancel/fallback mají strojově čitelné metadata; opakování requestu respektuje idempotence; revision změna invaliduje cache/receipts.

## 7. Zpětné přiřazení všech oprav z auditu

| Nález nebo návrh minulého auditu | Úkol / rozhodnutí |
|---|---|
| Conversation prompt/task, chat/completions bez handleru | T04: reprodukce a oprava skutečného kontraktu |
| Artifact list, JSON offset, numerické payloady | T03/T04/T14 |
| Lean actions, review/diff docs, work delta/controls, feature gating | T03/T04/T19; nejprve zkontrolovat společné decorators |
| RAG replay-safe mutace, embedding flag, raster diagram metadata | T07/T11 |
| Memory tenant overwrite/read, lease/evidence visibility | T05: respektovat trusted-local/shared koordinaci |
| Daemon bypass, permissive defaults, rollback, network/SSRF, cassette paths | T06/T15 |
| Swarm CAS/synthetic receipts, pubsub, worktree ownership | T08/T09/T16 |
| Event/projection atomicita, durable schema reset | T08; disposable cache a durable data nejsou totéž |
| Missing receipt/evidence validation, DB exception fail-open | T09 |
| Context identity/phase, include_code, Git/retrieval freshness | T03/T04/T10/T14 |
| RAG O(N), silent reranker fallback | T11 |
| Status redundant calls/full fan-out, metrics days, oldest timeline | T18 |
| Trace content/privacy a checkpoint snapshots | T08/T18: oddělit content store od telemetry a respektovat dřívější záměr |
| Transcribe false success/model/cleanup | T17 |
| Work isolation/receipt gate/cancel/races | T09/T16 |
| HTTP contract tests, exact aliases, SDK payload parity | T01/T03/T04/T19/T20 |
| Runtime latency, hardware/backends, browser, restart/load, install | T02/T10–T20 |

## 8. Podmínky celkového dokončení

- [ ] 100 % skutečně nalezených operací má uzavřený řádek inventáře; žádné odvozené neexistující endpointy.
- [ ] Potvrzené P0/P1 vyřešené; sporné nálezy reprodukované nebo vyvrácené s evidencí.
- [ ] Kontrakty, flags, SDK, MCP, HTTP a oba instalační/aktualizační prompty souhlasí.
- [ ] Výkon a kvalita změřené proti baseline; nesplněný SLO není nahrazen subjektivním skóre 5/5.
- [ ] Mutace zachovávají ownership, idempotenci a rollback; durable state přežije deklarované restart scénáře.
- [ ] Povinné projektové kontroly a podporované live acceptance scénáře procházejí na závěrečné revizi.
- [ ] Předáno: coverage tabulka, changelog oprav, benchmark comparison, validační receipts, podporované konfigurace a známá omezení.

Dokončení tohoto plánu jako dokumentu neznamená splnění implementačních checkboxů. Pořadí zahájení: T01/T02 a potvrzené opravy T04, následně společné hranice T03/T05–T09 a teprve změřené optimalizace.
