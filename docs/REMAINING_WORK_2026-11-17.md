# Předávka práce – Local AI Hub

Stav: uživatel práci pozastavil. Tento soubor zachycuje ověřený stav a otevřené kroky. Po jeho vytvoření se v práci nepokračuje.

## Dokončeno

- Commit 8567a6c938bf4a533467e7f8c2d01027c0d3c12f byl pushnut na origin/codex/preprocess-selector-sqlite-lock. Změna omezuje dávku mazání chybějících referencí v SQLite z 16 na 8 a přidává cílenou regresní kontrolu.
- Cílený příkaz python -m pytest tests/unit/test_preprocess_rag_adaptive_batch.py -q --test-result-cache skončil 6 passed za 4,00 s. Plná sada testů neběžela.
- Schéma aktivního Hubu už obsahuje gpu_scheduler_capacity_lease_release. Zdrojový kód akce kontroluje generaci, vlastníka scheduler-job, chybějící job a nepřítomnost Ollama runneru; vyžaduje consent=true a audit_reason. Implementace byla v předchozím commitu 74b9a7ca. V tomto pokračování žádný lease uvolněn nebyl.
- Čistý instalační checkout C:\Users\Adam\.codex\worktrees\hub-install-8567a6c9\.local-ai-hub odpovídá přesně commitu 8567a6c9. Nainstalovaná verze 6.1.0 je v C:\Users\Adam\.local-ai-hub-release-8567a6c9; stejný stavový adresář zůstává C:\Users\Adam\.local-ai-hub\state.
- Setup report po úspěšném běhu uvádí nainstalované core, Token Economy, Serena, local NLP, Laya runtime, AST index, performance a profiling. OpenVINO vyhodnotil jako nepotřebné; llama.cpp nebyl vybrán. Modely se nestahovaly a Hugging Face downloady zůstaly vypnuté.
- Aktualizováno 10 MCP konfigurací: globální Codex a Gemini plus Codex a Gemini pro profily Adam, Adamar, Eliska a Harfusha v Multigravity. Příkazy, cwd, LOCAL_AI_CONFIG a PYTHONPATH míří na jediný nový root. Všechny soubory prošly parsováním po změně. Zálohy: C:\Users\Adam\.local-ai-hub\state\agent-config-backups\20261117T172544Z.
- Globální local-ai-orchestrator skill v Codexu a Gemini byl srovnán se zdrojem 6.1.0; předchozí rozdíl obsahoval chybějící akci gpu_scheduler_capacity_lease_release. SHA-256 kopie byl ověřen. Zálohy: C:\Users\Adam\.local-ai-hub\state\agent-skill-backups\20261117T173200Z.
- Ve všech osmi profilech Multigravity (Codex i Gemini pro čtyři profily) odpovídalo 12 skill adresářů zdroji bez hash rozdílů.
- Po restartu Hub odpovídal jako 6.1.0, Ollama online, degraded=false. Živý listener i aktuální hub.owner.json ukazovaly proces z nového release rootu.
- Detailed telemetry zůstalo vypnuté. Žádný GPU lease ani karanténní databáze nebyly smazány.

## Zbývá

1. Po obnovení práce znovu ověřit aktivní službu. service-status jednou vrátil zastaralá PID a cestu ke starému rootu; následná kontrola aktuálního owner záznamu a TCP listeneru už potvrdila nový root. Při poslední kontrole nebyla naplánovaná úloha LocalAIHubSupervisor; service.py install použil podporovaný windows-user-startup fallback a Run klíč mířil na nový root. Ověřit, zda tento fallback spolehlivě přežije odhlášení/přihlášení, a zda se podaří zaregistrovat plánovanou úlohu bez spuštění druhého Hubu.
2. Codex a Antigravity konfigurace byly změněny během otevřené relace. Po obnovení práce restartovat příslušné agenty, aby načetly nové MCP cesty; následně ověřit každou integraci samostatně. Antigravity bylo dříve schváleno pouze staticky, dynamický test zatím neproběhl.
3. Setup report uvádí configured_with_manual_steps pro Codex a Gemini. Installer zachoval existující AGENTS.md a části MCP konfigurací, protože postrádaly ownership záznam. MCP směrování jsme následně bezpečně upravili s kopiemi, ale instrukční soubory nebyly přepsány. Porovnat jejich instrukce se zdrojem a případné změny dělat jen úzkým doplněním, se zachováním uživatelského obsahu.
4. První setup běh skončil timeoutem 60 s při codex plugin list --json v kontrole Superpowers. Úspěšný běh pak použil --skip-companion-skills. Existující Superpowers ani případné companion skills/pluginy nebyly ověřeny; neopakovat stejný CLI příkaz naslepo. Prověřit stav přes podporovaný plugin manager nebo ruční kontrolu a doinstalovat pouze chybějící součásti.
5. Po nasazení nového preprocessing buildu ověřit čerstvý stav projektu C:\Users\Adam\.codex\worktrees\klinika-integration\klinika. Před změnou měl 7 chyb a SQLite write transaction exceeded duration budget (5193 ms proti limitu 5000 ms). Nový limit dávky je 8. Post-restart preprocess_status odpověď byla zkrácena a nepřinesla stav; logy po restartu už další chybu preprocessingu neukázaly. Neprovádět force refresh ani ruční resume bez důvodu.
6. Zkontrolovat Hub logy po restartu. HTTP endpoint logs vrátil 503; byla provedena omezená lokální kontrola souborů. Před posledním restartem se opakovaly CPU preprocessing selection timeouty, chyba zápisu preprocessing failure state a timeouty POST /api/agent-state/tasks. supervisor.log měl probe_failed až do času restartu. Po restartu stav Hubu a Ollama vypadal zdravě, ale nové logy nebylo možné získat přes endpoint.
7. Prověřit pouze metadata karanténní databáze ve stavu Hubu: doctor.py hlásil jeden soubor o velikosti 2 256 306 176 bajtů. Obsah nemažte ani nepřepisujte bez samostatného rozhodnutí a ověřené zálohy.
8. Znovu ověřit, že detailed telemetry zůstává Off. Předchozí souhlas povoloval jen dočasné zapnutí; aktuální dashboard při poslední dřívější kontrole hlásil Off.
9. Před uvolněním GPU lease zjistit aktuální identitu. Dva dříve schválené scheduler-job lease ID 516be162b9d64910958dd904ec3887c0 a 4e238ea1f4cf46dc8a0e514c37656e31 nebyly v posledním čteném capacity souboru nalezeny. Pro nové ID je nutný nový výslovný souhlas pro konkrétní lease.

## Zachování stavu a přesné hranice

- Hlavní checkout C:\Users\Adam\.local-ai-hub zůstal nedotčený; obsahoval 13 uživatelských změn a untracked .ownership. Necommitovat je ani nepřepisovat.
- Zdrojový pracovní checkout: C:\Users\Adam\.codex\worktrees\hub-timeout-install\.local-ai-hub, větev codex/preprocess-selector-sqlite-lock. Před vytvořením této poznámky ukazoval 0 modified, 0 staged a untracked .ownership. Tato poznámka je nový soubor; není commitnutá ani pushnutá.
- Poslední evidovaný Agent OS plán: plan_3a1fdfc49ddf, task_endpoint_reliability_audit, revize fa0e085af5e3767f4aeb06558445274ea9ceb1071a406d3ac6cb9a5b004d1c6c.
- Nepouštět plnou sadu testů. Při pokračování používat jen cílené testy s cache, pokud bude potřeba změnu ověřit.
- Uživatel výslovně pozastavil práci; pokračovat až po jeho pokynu.

## Pokračování po obnovení uživatelem — 2026-11-18

Následující ověření doplňují a tam, kde se týkají stejné položky, nahrazují starý stav výše. Původní předávka a uživatelský obsah zůstávají zachované.

- **Služba a autostart:** `python tools/service.py status` hlásí Hub 6.1.0 ready, PID 62740, supervisor PID 57908, Ollama online, 0 restartů a bez chyby. Opakovaný `python tools/service.py install` skončil `windows-user-startup`; plánovaná úloha `LocalAIHubSupervisor` zůstává absent a hodnota HKCU Run míří na `.venv\Scripts\pythonw.exe tools\service_entry.py`. Ověřeno: stávající PID i počet restartů se nezměnily. Supervisor získává OS lock před spuštěním Hubu; neúspěšný duplicitní start skončí před spawnem. Skutečný logon/logoff cyklus ověřen nebyl.
- **Klienti:** aktuální Codex MCP volání do Hubu fungují. Antigravity po změně konfigurace dynamicky ověřen nebyl. Superpowers 7.0.2 a skills `using-superpowers`, `writing-plans`, `test-driven-development` a `verification-before-completion` jsou přítomné. Ve zpřístupněném plugin manageru není inventář lokálních companion pluginů; stejný timeoutující příkaz CLI nebyl opakován. Z `AGENTS.md` (SHA-256 `3962f3ecfa6f4df5e808fec6ea5ea52091658fd95e4ba6a9bac888f943fb2605`) byly zkontrolovány cílené části; konkrétní úzká oprava nebyla doložena, soubor zůstal beze změny.
- **Klinika:** `preprocess_status` hlásí RAG čekající na slot (max 9), 31,4 % celkem, 549 čekajících obohacení a 0 RAG souborů zaindexováno. Nebyl proveden force refresh ani resume.
- **Logy a diagnostika:** `/health` odpověděl úspěšně; supervisor dříve zaznamenal občasný `probe_timeout`, ale Hub zůstal ready. Doctor 2026-11-18 hlásí Serenu healthy (0 oprav) a jeden karanténní DB soubor ve `state`, celkem 2 256 306 176 B. Doctor neuvádí jméno ani schéma souboru; jeho obsah nebyl čten ani měněn.
- **Telemetrie a lease:** `debug_traces.enabled` bylo nalezeno zapnuté, přes podporované `/api/config/update` vypnuto a následné `/api/status` (včetně kontroly 2026-11-18) potvrzuje `false`. `gpu_reservation_status` hlásí stav free, bez rezervace; žádný lease nebyl uvolněn.
- Agent OS plán `plan_e2840d6c5f47` byl aktualizován a `plan_validate` uspěl (revize `0072190faa460c68bbb64af11546657830a75059980101478638dd330c6129b7`). Plná kontrola po skutečném přihlášení, dynamický handshake Antigravity, úplný inventář lokálních pluginů, detailnější metadata karantény a finální clean-SHA/CI důkazy zůstávají otevřené.

## Další pokračování — 2026-11-18

- Čerstvý `git_status`: větev `master`, HEAD `b439f75690e581ff75ea32894d5fed450374712d`, bez konfliktů; 26 upravených souborů a jeden necommitovaný plán. Žádná z těchto změn nebyla vrácena ani přepsána.
- Cílená preprocess regresní sada (7 souborů: active priority, status scaling, activity mode, enrichment, GPU loop, opmode resume a RAG pending) prošla `85 passed` za 7,65 s s `--no-cache`.
- Další offline brány z plánu prošly fresh: dashboard/HTTP admin `53 passed`, external GPU reservation lifecycle `48 passed`, T02 runner `11 passed`; vše s `--no-cache`. Nejde o živou browser, GPU ani soukromý korpus akceptaci.
- Další specifikační regresní soubory (Trace Inspector, training scaffold, diagnostics export a C10 negative knowledge) prošly `51 passed` s `--no-cache`.
- Další lokální gates na stejném pracovním stromu: `check_dashboard.py` OK (322 ID), `release_check.py --allow-installed` OK, `compileall` exit 0, `selftest.py` 6/6 OK, kritická kohorta `1956 passed, 14 skipped, 15748 deselected` za 675,28 s. Skipy: POSIX-only, symlink oprávnění Windows a nepřipnutý T18 root. Výsledky nejsou clean-SHA/CI receipts.
- Plugin manager search potvrdil Superpowers jako nainstalovaný a enabled; výsledky nejsou úplným inventářem lokálních companion pluginů.
- Poslední evidence `docs/agent-evaluation/results.md` je datována 2026-11-14: aktivní katalog uvádí 123 promptů; CASE131/133/135 obsah NOT VERIFIED, CASE132 partial, CASE134 partial a CASE136 protokol FAIL s 16 větvemi NOT RUN/BLOCKED. Nynější offline testy tento praktický audit neuzavírají; soubory evaluační sady zůstaly nedotčené.
- Index potvrdil všech 15 design specifikací a 8 markdown plánů. Plný sémantický křížový přehled ještě není hotový: adaptive context skončil terminální chybou vyžadující `task_id`; RAG degradoval kvůli `source_read_uncertain`.
- Agent OS task `task_ae875900711f` zůstává `planned` bez autentického `session_id`; nebyl svázán s vymyšlenou relací ani checkpointem.
- Otevřené brány podle autoritativního plánu: login cycle a Antigravity handshake, živý browser test, GPU benchmark/release, rozhodnutí o T02 korpusu, úplné audit/spec crosswalk a finální CI/package receipts pro přesný čistý SHA.
- Instalační politika: opraveny generované nadpisy a duplicity pravidel, které rozcházely oba kanonické prompty a překračovaly 23 900 B pro instalační profil. `tests/test_setup.py`, `tests/test_t19_setup_manifests.py`, `tests/unit/test_setup_style_policy.py`, `tests/unit/test_sync_prompt_policies_and_setup_wave12.py`: **63 passed**; `test_t19_prompt_profile_parity.py` a `test_generator_action_descriptions.py`: **8 passed**. Zastaralé očekávání `native_fallback_allowed` v testu parity bylo nahrazeno přesným současným kontraktem. Prompt parity, release check, compileall i diff check prošly. Výstup má 23 660 B; host instalace a živý klientský handshake zůstávají neověřené.
- Fresh Laya source sada všech 15 odpovídajících testových souborů: **391 passed**. Opravena dvojitá capture telemetrie v queued decision; prázdný výsledek má jeden `outcome_not_captured` event a přímé volání ponechává svůj vlastní zápis. Jde o fixture/temp-state důkaz, ne o skutečná Laya data, lidské labels, live unload nebo modelovou kvalitu.
- Fresh tokenless/security regresní sada čtyř souborů: **49 passed** (loopback bez tokenu, bind/origin, veřejné API a admin action auth). Specifikace hub tokenu zůstává OPEN kvůli OpenCode provider bridge a úplné inventory retired fields.
- Další targeted specifikace: diagnostics export **10 passed**; C10 `test_auto_negative_knowledge.py` **4 passed**; existing-card export **4 passed** (`tests/unit/test_model_training_scaffold.py -k existing_card_export`). Všechny testy používají fixtures/temp DB; žádný user dataset, >4GB archive, model nebo hardware se netestoval.
