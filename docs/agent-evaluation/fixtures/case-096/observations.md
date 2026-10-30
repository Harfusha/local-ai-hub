# 096: sandboxový průchod 2026-10-29

- Root: `<temp>/local-ai-eval-096-984a57350263462c99b8ac24860fe3b3`; samostatný config, state, venv a náhodné loopback porty.
- Zdroj 5.0.0: commit `65a6fbe4f4caf862f00ba4d9b8dd77145a4a35df`, wheel SHA-256 `ec9f11393e47f72aa054572b0ba8b5b08dcadbc29b6750f22868b17ca35870d2`.
- Zdroj 5.1.0: commit `6c7200a9c1b71554ebe368b8722a6757d94c0282`, wheel SHA-256 `5344e0712861b089aab5e499d82b3e4616ee23f228be1d4e983927b4bf6d2b78`. Není to dosud necommitovaný kandidát oprav.
- Závislosti připraveny do wheelhouse před offline během; `wheelhouse-manifest.json` v sandboxu obsahuje SHA-256 všech 32 wheelů. Instalace obou verzí proběhly s `--no-index`. 5.0.0 na izolovaném portu vrátil `hub_online=true`. Pokus o zápis workspace memo vrátil 403 a nebyl opakován.
- Po instalaci 5.1.0 první start selhal: `RAG database has fingerprint mismatch; explicit offline rebuild required`. Záloha původního stavu existuje. Před offline přesunem staré RAG databáze byly ověřeny nulové počty files/chunks/project_file_owners. Po přesunu a vytvoření nového indexu 5.1.0 vrátil `hub_online=true`. Všech pět původních řádků sandboxové telemetry zůstalo identických.
- Rollback: 5.0.0 z původního wheelu a samostatné kopie zálohy. První start selhal na zkopírovaných starých identitách procesů; po ověření stale byly tyto soubory archivovány mimo aktivní state. Následně 5.0.0 vrátil `hub_online=true`; všech pět původních řádků telemetry zůstalo identických.
- První ruční spuštění odhalilo Windows launcher: zánik původního Popen handle nedokazuje úklid potomků. Vlastní listener byl ukončen po kontrole identity a rodičovské vazby. Další běhy použily `popen_managed` a Windows Job Object; ukončení stromu potvrdilo `true`.
- Opakovatelný `smoke.py` následně svázal port se skutečným PID listeneru a ověřil rodičovskou vazbu i cestu instalovaného balíčku pro 5.0.0 a 5.1.0. Podklady: `smoke-result-state-rollback-57348.json` a `smoke-result-state-61421.json` ve výše uvedeném sandboxu. Přímý parser netstatu selhal; použit existující `find_listening_pid`.
- Omezení: zachování pěti telemetry řádků neprokazuje zachování všech druhů dat. Netestován neprázdný RAG, konverze starých tenant dat, API/MCP/UI task, lokální model ani kandidát aktuálních oprav. Nejde o produkční upgrade ani potvrzení plné funkčnosti Hubu.

## Neprázdný RAG upgrade — 2026-10-30

- Nový izolovaný sandbox: `%TEMP%\local-ai-eval-096-rag-upgrade-20261030-002`. Build Python 3.13.2; wheel 5.1.0 z `6c7200a9c1b71554ebe368b8722a6757d94c0282` (`7d2b0f190dfbd2016d4207b1df47f5491d96d2df4446197b213d1dfc267246de`) a 5.1.2 z `af5bb9e7443ce5196bfd24d78e2f2abb53774d5` (`33c87c18d0ab36c655dae614178e896851136381ce327063322b102d62972979`). Všechny závislosti byly instalovány offline z wheelhouse s ověřenými SHA-256.
- Před upgrade obsahoval index jeden fixture soubor, jeden chunk a jeden owner; fingerprint 5.1.0 `8332062635fe7da6f2faa8e2f494e53520db9948210253f1980af4b04d27400f`.
- Supervisor kandidáta zaznamenal `RAG database has fingerprint mismatch; explicit offline rebuild required`. SHA-256 `rag.sqlite3`, WAL i SHM se před a po odmítnutí shodovaly. Původní celý state byl zachován v `state-before-offline-rebuild`.
- Explicitní rebuild vytvořil index s fingerprintem 5.1.2 `33cc3d67b3bd44f4ce60a67687367a538b71990d9b8e6567ad75899394247580`; obsahový SHA-1 souboru souhlasí, `files=1`, `chunks=1`, `owners=1`, SQLite `integrity_check=ok`.
- Kandidátní HTTP smoke: verze 5.1.2, port 64500, listener/proces vlastněn sandboxem; `process_tree_terminated=true`. Evidence `smoke-result-state-64500.json`; pozorování upgradu `nonempty-rag-upgrade-observation.json`. Oba artefakty označují `runtime_acceptance=false` a nevytvářejí receipt.
- Ověření odhalilo a opravilo chyby samotného fixture runneru: v5.1.0 předává `background=True` embedderu, supervisor směruje chybu do `state/logs/hub_stderr.log` a SQLite connection context manager vyžadoval explicitní close před Windows přejmenováním adresáře. Nešlo o regresi produkčního Hubu.
- Omezení: deterministický embedding je syntetický a testuje pouze formát/databázovou cestu; ne kvalitu modelu, všechna produkční RAG data, MCP/UI task scénář ani tenant konverzi.
