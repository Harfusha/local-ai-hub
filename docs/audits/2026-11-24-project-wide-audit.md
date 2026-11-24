# Audit Local AI Hub · 24. listopadu 2026

[Detailní statický audit](2026-11-24-local-ai-hub-detailni-audit.md) pokrývá 2 873 verzovaných cest a 21 evidovaných položek. Auditovaný commit je a16a52dcc59381f74edd71b9d0501e342168d597.

**Stav po implementaci:** Všechny potvrzené nálezy A01–A21 byly opraveny, stav byl převeden na verzi 11, byl dokončen reset vektorů a provoz na běžícím Hubu v8.0.0 byl ověřen (doctor OK, MCP OK, handshake 7 hostů OK, benchmarky endpointů zaznamenány).

## Stav vyřešených položek

1. **A21 a A16.** Čistá inicializace i obnova existující instalace opraveny; záchranné artefakty se nemažou před dokončením migrace. Čistá instalace ověřena na novém izolovaném adresáři.
2. **A13.** AST parser spouští ast-grep bezpečně s argv bez shell interpreteru (`shell=False`).
3. **A17.** Chybějící soubory pro browser bridge (`offscreen.html`, `offscreen.js`, `popup.html`, `popup.js`) zahrnuty do data-files wheelu.
4. **A02.** Ruff lint chyby v testovacím kódu opraveny (`ruff check` 100% čisté).
5. **A18 a A14.** Stránkování úloh filtruje `repo_root` přímo v SQLite dotazu a posouvá kurzor; `TaskPage` kontrakt plně integrován.
6. **A19 a A20.** Setup rozlišuje deklaraci a fyzickou existenci Laya checkpointu. Dashboard kompilátor TypeScript připnut na 5.7.2 a lockfile verzován.
7. **A01, A03–A12, A15.** Izolace stavových záloh v `.gitignore`, API coverage drift 0, konfigurace v1, SECURITY.md 8.x, FTS timeout opraven, v8 migrace (6→11) a embedding reset dokončeny, provider matice a handshake ověřeny, benchmark endpointů zaznamenán, strict mypy rozšířeno na 16 modulů, workflows dokumentace očištěna.

## Ověřeno

- Syntakticky prošlo 2 291 Python souborů, 21 JavaScript souborů, 97 JSON a 5 TOML.
- Katalog API má 674 řádků bez zjištěných odchylek. MCP audit a kontrola kanonických instrukcí prošly.
- Release check v místním režimu prošel s osmi kontrolami. Obě lokální konfigurace mají značku schématu. Zálohy na disku zůstávají.
- V tomto pokračování nebyly spuštěny testy. Živé CI, instalace, rollback, připojení hostů, kvalita RAG a výkon zůstávají bez současných provozních výsledků.
