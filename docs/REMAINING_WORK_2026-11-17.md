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
