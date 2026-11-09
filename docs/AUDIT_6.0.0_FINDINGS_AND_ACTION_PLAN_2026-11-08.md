# Detailní technický audit Local AI Hub v6.0.0 a akční plán prioritních oprav

**Datum auditu:** 8. listopadu 2026  
**Verze systému:** 6.0.0  
**Analyzovaný commit:** `2176b0e210cbd64fb2260f721f8546d5365b463f` (`master`)  
**Repozitář:** `Harfusha/local-ai-hub`  
**Aktivní Agent OS plán:** `.local-ai-hub/plans/plan_technical_audit_v6_20261108.plan.json`  

---

## 1. Souhrnné zjištění a rozsah projektu

Local AI Hub představuje komplexní platformu integrující statickou analýzu kódu, indexování, RAG, model routing, orchestraci úloh, paměť agentů (Agent OS), command broker a telemetrii.

### Rozsah kódu a testů (commit `2176b0e`)
- **Git strom:** 2 095 evidovaných položek
- **Zdrojové soubory v `src/local_ai_hub`:** ~200 souborů Python (~9,1 MB)
- **Testovací soubory v `tests/`:** 1 310 souborů (~11,7 MB)
- **Výchozí konfigurace:** ~35 KB (`defaults.toml`)

### Architektonické silné stránky (zachovat)
1. **Deterministic-first přístup:** Git, Tree-sitter, AST a symboly předcházejí jakékoli LLM inferenci.
2. **Kompaktní MCP rozhraní:** Pouze 7 veřejných MCP nástrojů omezuje režii systémových schémat.
3. **Sdílený Hub daemon:** Více agentů sdílí cache, modelové procesy a paměťové prostředky.
4. **Evidence IDs a source slices:** Přesné výřezy zdrojového kódu nahrazují nespolehlivá shrnutí.
5. **Revision-aware kontext:** Ochrana před prací se zastaralým stavem repozitáře.
6. **Graceful degradation:** Deterministické a indexové funkce pokračují i při nedostupnosti modelového backendu.

---

## 2. Kritické nálezy (P0 — Blokující)

### P0-1: Selhání CI na pyflakes kontrole
- **Popis:** Všech 12 kombinací OS/Python v GitHub Actions CI selhává na statické kontrole `pyflakes src tools`.
- **Detekováno 11 varování:** Nevyužité importy a proměnné v:
  - `src/local_ai_hub/embeddings.py`
  - `src/local_ai_hub/generator.py`
  - `src/local_ai_hub/hardware.py`
  - `src/local_ai_hub/preprocess.py`
  - `tools/benchmark_reranker.py`
- **Dopad:** Blokuje sestavení balíčku a publikaci jakékoli nové verze.
- **Akceptační kritérium:** `pyflakes src tools` projde s nulovým výstupem (exit code 0).
- **Task ID v plánu:** `task_p0_ci_pyflakes`

### P0-2: Selhávající regresní test timeoutu stderr
- **Popis:** V critical regression cohort selhal test `test_owned_model_timeout_reports_bounded_worker_stderr`.
- **Příčina:** Test očekává, že `TimeoutError` bude obsahovat zachycený výstup `stderr` z lokálního modelového worker procesu. Skutečná výjimka obsahovala pouze `model operation timed out`.
- **Dopad:** Ztráta diagnostických dat při timeoutu lokálního modelu; nestabilní CI.
- **Akceptační kritérium:** `pytest tests/ -k test_owned_model_timeout_reports_bounded_worker_stderr` prochází a `TimeoutError` obsahuje bounded stderr.
- **Task ID v plánu:** `task_p0_model_timeout`

### P0-3: Rozpor v upgrade kontraktu verze 6.0.0
- **Popis:**
  - `RELEASE.json` tvrdí, že upgrade automaticky odstraňuje starý runtime state.
  - `CHANGELOG.md` naopak uvádí, že persistentní stav se zachovává a nekompatibilní verze start odmítne.
  - `state_lifecycle.py` (L79–118) vyvolává výjimku při nekompatibilitě a vyžaduje offline konverzi.
- **Dopad:** Nejasné chování pro operátory a riziko ztráty či odmítnutí dat při upgradu.
- **Akceptační kritérium:** Sjednocení `RELEASE.json`, `CHANGELOG.md` a `state_lifecycle.py`; integrační test ověřující zachování stavu při přechodu z 5.x.
- **Task ID v plánu:** `task_p0_upgrade_contract`

---

## 3. Důležité nálezy (P1 — Výkon, relevance, lifecycle)

### P1-1: Rozpor README vs. výchozí feature flagy
- **Popis:** README uvádí, že nákladnější funkce jsou ve výchozím stavu vypnuté, ale v `defaults.toml` jsou nastaveny jako aktivní:
  - `enriched_search`: README tvrdí `false`, v `defaults.toml` je `true`
  - `batch_replacement`: README tvrdí `false`, v `defaults.toml` je `true`
  - `diagnostic_artifacts`: README tvrdí `false`, v `defaults.toml` je `true`
  - `local_diagnostic_dispatch`: README tvrdí `false`, v `defaults.toml` je `false`
- **Dopad:** Zmatení uživatelů a porušení deklarovaného rollout kontraktu.
- **Task ID v plánu:** `task_p1_feature_defaults`

### P1-2: Vynucený Git fingerprint na lexikální vyhledávací cestě
- **Místo:** `src/local_ai_hub/services.py` L3820–3842 (`LocalAIServices._repo_search_lexical`)
- **Problém:** Volání `fingerprint(root, force=True)` spouští nový `git status` při každém vyhledávacím dotazu a ignoruje `fingerprint_ttl_seconds = 30.0`.
- **Dopad:** Zvýšená latence cold vyhledávání (medián 3 365 ms, p95 6 063 ms).
- **Řešení:** Dvoustupňová kontrola čerstvosti (generační číslo / filesystem watchdog vs. plný git check při mutaci).
- **Task ID v plánu:** `task_p1_fingerprint_profile`

### P1-3: Heuristika rozpoznávání symbolů v `search_modes.py`
- **Místo:** `src/local_ai_hub/search_modes.py` L20–67 (`prefers_lexical_precision`)
- **Problém:** Znaky jako `.`, `/`, `+`, `#`, `_` automaticky přepnou dotaz na čistě lexikální větev. Dotazy jako `config.php` nebo `Python 3.13` tak zbytečně vyřadí sémantické kandidáty.
- **Řešení:** Explicitní klasifikace dotazu (`exact_symbol`, `file_path`, `natural_language`, `mixed`).
- **Task ID v plánu:** `task_p1_query_classification`

### P1-4: RAG lifecycle, embedding space mismatch a GPU rezervace
- **Problém:**
  - Při `embedding_space_mismatch` live dotazy selhávají nebo degradují bez plánovaného reindexu.
  - GPU rezervace zanechávají stav `gpu_reserved` při neúspěšném nebo přerušeném běhu.
- **Řešení:** Explicitní stav `reindex_required`, bezpečné plánování reindexu na pozadí, fallback na lexikální hledání bez blokování foreground dotazů, sjednocený lease lifecycle s automatickým uvolněním po timeoutu.
- **Task ID v plánu:** `task_p1_rag_lifecycle`

### P1-5: A/B měření skutečného přínosu Hubu (Token Economy)
- **Problém:** Tvrzení v `docs/TOKEN_ECONOMY.md` o 80–95% úspoře cloudových tokenů není doloženo systematickým A/B měřením vůči modernímu agentovi s nativními úspornými nástroji.
- **Řešení:** Exaktní měření stejných úkolů:
  - Cloud input/output tokeny
  - Počet tool volání
  - Čas dokončení
  - Úspěšnost validace a počet následných oprav
- **Task ID v plánu:** `task_p1_ab_evaluation`

### P1-6: GPU admission a model routing na RTX 5070 Ti (16 GB VRAM)
- **Problém:** Jediný 40-tokenový test 9B modelu s 2,1 GB volné VRAM neprokazuje stabilitu při delším kontextu (8k, 16k, 32k) ani při souběhu s desktopovým využitím GPU.
- **Řešení:** Profilace skutečného TTFT (streamované tokeny), throughputu a paměťové náročnosti pro rezidentní 4B model vs. na vyžádání načítaný 9B model.
- **Task ID v plánu:** `task_p1_gpu_admission`

---

## 4. Architektonické úpravy a údržba (P2)

### P2-1: Dokončení OpenCode E2E integrace
- **Stav:** `docs/OPENCODE.md` uvádí integraci jako „in progress“.
- **Cíl:** Plně ověřený end-to-end sandbox runtime: model → MCP → transakční editace → úklid → recovery.
- **Task ID v plánu:** `task_p2_opencode_e2e`

### P2-2: Sjednocení SQLite přístupu
- **Cíl:** Konsolidace přímých `sqlite3.connect` volání přes `sqlite_support.py` při zachování specifických timeoutů, WAL a read-only režimů. Audit smyček `while True` a doplnění bounded retry.
- **Task ID v plánu:** `task_p2_sqlite_factory`

### P2-3: Postupná dekompozice monolitických modulů
- **Kritické moduly:**
  - `commands.py` (~10 844 řádků)
  - `services.py` (~9 870 řádků)
  - `mcp_server.py` (~7 474 řádků)
  - `code_index.py` (~5 169 řádků)
  - `preprocess.py` (~5 119 řádků)
- **Postup:** Rozdělovat podle stabilních funkčních celků bez zásahu do veřejných MCP schémat nebo HTTP rozhraní.
- **Task ID v plánu:** `task_p2_modularize`

---

## 5. Akceptační kritéria pro pilotní release v6.0.0

| Metrika / Oblast | Cílová hodnota pro release |
|---|---|
| **GitHub Actions CI** | 100 % jobů zelených napříč OS/Python maticí |
| **Pyflakes varování** | 0 v `src` i `tools` |
| **Search Recall@10** | $\ge 0{,}85$ na rozšířeném reálném korpusu |
| **Search MRR** | $\ge 0{,}70$ |
| **Warm search medián** | $\le 150\text{ ms}$ |
| **Cold search medián** | $\le 2\,000\text{ ms}$ |
| **Falešně čerstvé výsledky** | 0 po změně souboru |
| **RAG mismatch chování** | Explicitní `reindex_required`, neblokující fallback |
| **GPU admission** | 0 VRAM OOM pádů na 16 GB hardware při 32k kontextu |
| **A/B evaluace úspory** | Změřena reálná delta tokenů a času proti baseline bez Hubu |

---

## 6. Ověřovací příkazy

```bash
# 1. Základní statická kontrola a testy
python -m compileall -q src tools tests
pyflakes src tools
python -m pytest -q
python tools/selftest.py
python tools/release_check.py

# 2. Bounded spuštění selhávajícího testu
python -m pytest tests/test_owned_model_timeout_reports_bounded_worker_stderr.py -v

# 3. Vyhledávací a kvalitativní benchmarky
python tools/benchmark_live_search.py --modes lexical --repeats 3
python tools/benchmark_real_search.py
python tools/audit_quality_eval.py

# 4. Profilace a telemetrické reporty
python tools/performance_probe.py --help
python tools/benchmark_surfaces.py --help
python tools/telemetry_report.py --days 14
```
