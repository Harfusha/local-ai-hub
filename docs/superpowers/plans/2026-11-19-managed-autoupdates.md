# Implementace automatických aktualizací Hubu

Požadavky a akceptace jsou v [návrhu](../specs/2026-11-19-managed-autoupdates-design.md).

1. **Vydání.** Testy pro SemVer a synchronizaci metadat. `tools/prepare_release.py` spočítá verzi. Workflow vytvoří tag a spustí CI na jeho přesném commitu. Při chybě publikace zůstane možné znovu spustit CI pro stejný tag.
2. **Výběr kandidáta.** Testy pro stabilní GitHub Releases, vazbu tagu a ověřeného commitu, downgrade a spravovaný cíl. `tools/auto_update.py` poskytne kontrolu a aplikaci z odděleného checkoutu a se zámkem pro aktualizace.
3. **Transakce instalace.** Připravit závislosti před zastavením, reuse kontroly cíle, stávající výměnu payloadu a migrační runner. Ponechat původní prostředí a ověřenou zálohu dat do potvrzení funkčnosti. Testovat cesty úspěchu, návratu a selhání návratu v izolované instalaci.
4. **Provoz.** Popsat ruční příkaz, systémové plánovače a postup obnovy v `docs/INSTALLER_RECOVERY.md`. Ověřit testy aktualizace, nastavení, transakce a release kontraktu. Reálný release ani automatický restart živého Hubu není součástí vývojového ověření.
5. **Dashboard.** Testovat ověření cíle a potvrzení verze i commitu. Přidat stav aktualizace a předání pevného příkazu systémovému plánovači mimo proces Hubu. Průvodce po restartu zobrazí report.
6. **Ověření řetězce.** Ověřit lokální izolovanou instalaci s reálným sestavením wheelu a dvěma stupni migrace. Ověřit dostupné spuštění GitHub Actions v existujícím repozitáři a zaznamenat překážky publikace. Nový GitHub repozitář nevytvářet.
