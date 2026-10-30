# Fixture 100: seed

`python prepare.py <nová-složka>` vytvoří samostatný Git repozitář se dvěma chybami, plánem a reálnou cizí necommitovanou změnou. `oracle_100.py` ověřuje jen lokální funkci exportu. Pro úplný scénář musí provozovatel vytvořit skutečnou Agent OS úlohu a sandbox, ověřit dostupný lokální model, přerušit reálného agenta a uchovat autentické důkazy API/UI; připravený plán ani seed tyto kroky nenahrazují. Nikdy neměň produkční Hub.

Pro společný izolovaný Hub nejprve vytvoř nový prázdný sandbox root mimo existující Git repozitáře a spusť tento builder s cílem `ROOT/workspace`. Připrav samostatný `ROOT/venv` a `ROOT/state` podle fixture 098. Spouštěč 098 lze následně použít se stejným rootem pro MCP/HTTP/dashboard; jeho obecný kontrolní task je oddělený od skutečné úlohy testovaného agenta a nesmí se za ni vydávat. Před a po běhu porovnej cizí diff a ověř skutečné přerušení a obnovení. Lokální model ani autorizovaný producent validačního receipt nejsou součástí seedu.
