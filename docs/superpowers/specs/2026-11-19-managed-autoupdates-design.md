# Automatické aktualizace Local AI Hubu

Stav návrhu: schváleno 19. listopadu 2026.

## Cíl

Při vydání spočítat verzi automaticky. Spravovaná instalace si ve zvoleném servisním okně stáhne ověřené stabilní vydání, provede potřebné migrace a obnoví službu. Stejný postup musí fungovat i při přeskočení několika vydání.

## Vydávání

Správce spouští release workflow a volí `patch`, `minor` nebo `major`. Workflow vypočítá další SemVer, sjednotí `pyproject.toml`, `src/local_ai_hub/__init__.py` a `RELEASE.json` a připraví commit a odpovídající tag. Při výpočtu respektuje existující zdrojovou verzi i obsazené tagy. Souběžná vydání se serializují. Po vytvoření tagu workflow výslovně spustí CI na tomto tagu, protože push provedený pomocí `GITHUB_TOKEN` další workflow nespustí. CI ověří přesný commit a balíček před vytvořením stabilního GitHub Release. Neúspěšné vydání musí jít znovu ověřit na stejném tagu.

Při každém pushi by se vydávaly i běžné vývojové změny. Spuštění release workflow odděluje okamžik vydání a míru změny verze od každodenního vývoje.

## Aktualizace instalací

- Příkaz nabídne kontrolu verze a samostatné použití aktualizace. Automatický běh správce zapne pro konkrétní spravovanou instalaci v servisním okně. Použije systémový plánovač a běží jako vlastník instalace mimo proces Hubu. Dokumentace pokryje Task Scheduler ve Windows, uživatelský timer `systemd` v Linuxu a `launchd` v macOS. Stejný příkaz lze spustit ručně.
- Zdroj aktualizací je oficiální GitHub Releases. Kandidát musí být publikované stabilní vydání s vyšším SemVer. Před spuštěním kódu ověřit vazbu vydání, tagu, čistého dočasného checkoutu a schváleného commitu. Chybějící či nekonzistentní metadata zastaví aktualizaci před odstávkou.
- Ověřit cíl instalace, uzamknout souběžné aktualizace a použít stávající instalační transakci. V konfiguraci zůstanou uživatelovy volby včetně umístění dat. Vývojové checkouty jsou mimo dosah instalátoru aktualizací.
- Před odstávkou připravit a zkontrolovat kandidáta a dostupnost jeho závislostí. Po zastavení ověřit, že Hub data nepoužívá, a provést výměnu kódu a migrace. Dnešní transakce drží zálohu kódu do dokončení migrace. Aktualizátor musí držet podklady k obnově kódu, závislostí a odpovídajícího stavu až do ověření nové verze a funkčnosti služby. Při selhání obnoví původní instalaci a její předchozí stav služby. Chybu a případný neúspěšný návrat uloží s cestou k záloze.

## Inkrementální migrace

Verze vydání a verze dat mají vlastní číslování. Změna schématu přidá ověřený převod `N` na `N+1` do `tools/state_migrations.py` a zvýší cílovou verzi stavu. Release musí obsahovat všechny kroky podporované cesty. Existující runner zkontroluje celý řetězec před odstávkou, vytvoří ověřenou zálohu a provede kroky na pracovní kopii. Každý krok ověří data před pokračováním, živý stav se vymění až po úspěchu celého řetězce. Vydání se stejným schématem data nepřepisuje.

Registr dnes nemá žádný převod, aktuální schéma má verzi `6`. Poslední publikované stabilní vydání je `v5.1.4`. Přechod z jeho staršího formátu vyžaduje doložené vstupní schéma a kontroly zachování záznamů. Při neznámém formátu nebo chybějícím kroku aktualizace skončí před odstávkou. Historický převod dat s tenanty dál vyžaduje ověřený formát a ošetření kolizí.

## Akceptace

- Test výpočtu verze a shody metadat, odmítnutí kolize tagu a publikace podmíněné úspěchem CI.
- Test aktuální verze, novějšího stabilního vydání, prerelease, downgrade a rozporu v identitě kandidáta.
- Izolovaná aktualizace se dvěma po sobě jdoucími převody se zachováním konfigurace a dat.
- Pokrytí chybějící migrace, selhání druhého kroku, neúspěšné aktivace a souběžného spuštění. Ověřit výsledek na původních datech, kódu a službě.

## Aktualizace z dashboardu

Schváleno 19. listopadu 2026. Dashboard průběžně nabídne dostupnou verzi. Průvodce zobrazí aktuální a cílovou verzi, potvrdí odstávku a předá aktualizaci stávajícímu aktualizátoru. Cílová verze a ověřený commit se při spuštění znovu ověří. Schválený požadavek spustí systémový plánovač mimo službu Hubu. Výsledek se po restartu načte z reportu. Cíl se odvodí ze skutečného běžícího spravovaného prostředí. Běžný Git checkout dostane stav nedostupné instalace. GitHub Actions ověřovat v existujícím rozsahu přístupu, bez vytváření nového repozitáře nebo publikace testovací stabilní verze.
