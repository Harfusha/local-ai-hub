# Fixture 100: seed

`python prepare.py <nová-složka>` vytvoří samostatný Git repozitář se dvěma chybami, plánem a reálnou cizí necommitovanou změnou. `oracle_100.py` ověřuje jen lokální funkci exportu, včetně zrušení před nahrazením cíle. Pro úplný scénář musí provozovatel vytvořit skutečnou Agent OS úlohu a sandbox, ověřit dostupný lokální model, přerušit reálného agenta a uchovat autentické důkazy API/UI; připravený plán ani seed tyto kroky nenahrazují. Nikdy neměň produkční Hub.

Pro společný izolovaný Hub nejprve použij builder fixture 098 s novým absolutním `ROOT` mimo existující Git repozitáře. Ten založí `ROOT/workspace`, `ROOT/state` a samostatnou konfiguraci; pak spusť tento builder s dosud neexistujícím cílem `ROOT/workspace/repo`. Případné `ROOT/venv` se připravuje zvlášť. Izolovaný Hub používej pro MCP/HTTP/dashboard; jeho obecný kontrolní task je oddělený od skutečné úlohy testovaného agenta a nesmí se za ni vydávat. Před a po běhu porovnej cizí diff a ověř skutečné přerušení a obnovení. Lokální model ani autorizovaný producent validačního receipt nejsou součástí seedu.

`python -B smoke_100.py` v repozitáři fixture provede lokální smoke exportu a pozdního zrušení ve vlastním dočasném adresáři. Jeho exit code ani výstup nejsou Agent OS receipt a neprokazují stav produkční služby.
