# Fixture 096: offline release preparation

`prepare_wheels.py REPOSITORY BEFORE_REF AFTER_REF NEW_DISPOSABLE_ROOT` sestaví dvě různé commitované revize lokálně bez indexu a síťového stahování. Vyžaduje předinstalovaný pip, setuptools a wheel; build backend spouští kód z daných revizí, proto používej pouze důvěryhodný repozitář. Výstup obsahuje skutečné commity a SHA-256 wheelů, nikoli důkaz běžící služby. Nezachycuje necommitované změny.

Samotná příprava wheelů neřeší offline balíčky závislostí, samostatný config/state/port, spuštění Hubu, upgrade ani rollback. Tyto kroky a jejich autentické důkazy jsou nadále nezbytné. Root musí být nový, mimo jiný Git repozitář; úklid provádí operátor pouze na ověřené disposable cestě po uchování důkazů.

Po instalaci wheelu a všech závislostí do `ROOT/venv` lze spustit `ROOT/venv/Scripts/python.exe -I smoke.py ROOT --state state --expected-version VERZE` (na Windows; jinde použij cestu k interpretu venv). Smoke ověřuje instalovaný balíček, HTTP status, vlastnictví procesů a PID listeneru; používá Job Object pro ukončení stromu. Evidence je zapsána do nového souboru v sandboxu. Spouštěj jej pouze s jediným vlastníkem state. Konfigurace obsahuje dočasný token a nesmí být zveřejněna. Nejde o ověření MCP, dashboardu, zachování všech dat ani produktu na produkční instalaci.

## Neprázdný RAG při upgradu

Pro upgrade z 5.1.0 na kandidáta s jiným fingerprintem vytvoř wheelhouse a dvě vlastní venv podle `prepare_wheels.py`; do obou venv instaluj závislosti pouze z ověřeného offline wheelhouse. `before-venv` musí obsahovat starší wheel, `venv` kandidáta. Potom spusť:

```powershell
ROOT/before-venv/Scripts/python.exe -I nonempty_rag.py seed ROOT
ROOT/venv/Scripts/python.exe -I nonempty_rag.py upgrade ROOT --expected-version VERZE
ROOT/venv/Scripts/python.exe -I smoke.py ROOT --state state --expected-version VERZE
```

Seed používá deterministický syntetický embedding pouze pro neprázdný testovací index; neověřuje kvalitu modelu. Upgrade spouští kandidátní supervisor proti tomuto indexu, vyžaduje přesnou chybu fingerprintu a shodu SHA-256 DB/WAL/SHM před a po odmítnutí. Pak uchová starý state, explicitně vytvoří nový index ve vedlejším adresáři a po kontrole atomicky přepne sandbox na obnovený state. `nonempty-rag-upgrade-observation.json` je fixture pozorování, nikoli Agent OS receipt ani release acceptance. Záloha i sandbox zůstávají zachovány pro kontrolu.
