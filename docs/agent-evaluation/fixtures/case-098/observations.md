# 098: částečný sandboxový průchod 2026-10-29

Oddělený sandbox `<temp>/local-ai-eval-096-984a57350263462c99b8ac24860fe3b3/fixture098`, Hub 5.1.0 z commitu `6c7200a9c1b71554ebe368b8722a6757d94c0282`, vlastní venv, workspace a state.

MCP stdio vytvořilo úlohu `task_afe30b9a8ffd`; checkpoint pro stejnou úlohu prošel. HTTP vrátilo stejné ID, stav `planned`, fázi `sandbox-ready`; v dashboardu Tasks byly viditelné stejné ID, stav PLANNED a fáze. MCP a HTTP odpovědi jsou v sandboxovém `identity.json`. Supervisor byl ukončen s potvrzeným úklidem Job Object.

Po chybné kontrole horního `task_id` se další úloha nevytvořila: ID bylo v `task.task_id` a znovu použito. První zadání s nepovoleným `owner` bylo odmítnuto v preflight. Receipt ani terminal completion nebyly vytvořeny nebo prokázány. Aktuální necommitovaný kandidát nebyl součástí této instalace.

Na pozdějším izolovaném kandidátu `candidate-review-wire` vytvořilo MCP úlohu `task_82b3bd266e47` a po restartu sandboxu ji stejný runner s `--task-id` znovu načetl přes MCP a HTTP. Původní neinteraktivní běh skončil `EOFError` při čekání na Enter, přesto bezpečně ukončil vlastní procesy; následně přidaný `--no-wait` prošel s návratovým kódem 0 a potvrzeným úklidem. Odpovědi jsou v souborech `identity-task_82b3bd266e47-64153.json` a `identity-task_82b3bd266e47-61366.json` v sandboxu. Nejde o důkaz receipt, dokončení ani dashboardového zobrazení této druhé úlohy.
