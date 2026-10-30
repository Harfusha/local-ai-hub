# 092: mezikandidát 2026-10-29

V izolovaném sandboxu `<temp>/local-ai-eval-096-984a57350263462c99b8ac24860fe3b3/candidate-prewire` byl z commitu `6c7200a9c1b71554ebe368b8722a6757d94c0282` a čtyř upravených zdrojových souborů sestaven wheel SHA-256 `374db60769534bca56ee9fb7c249123eb6b712eeffd27302176027766e588b71`. Přesné zdrojové hashe jsou v sandboxovém `source-manifest.json`; kandidát není integrovaný ani finální.

HTTP smoke nainstalovaného wheelu ověřil verzi 5.1.0, identitu listeneru a ukončení vlastního stromu; důkaz `smoke-result-state-61994.json`. První MCP pokus byl neprůkazný, protože work orchestrator byl vypnutý; výsledky jsou uloženy zvlášť jako `mcp-preflight-results-disabled.json`.

Po úpravě izolované konfigurace prošly přes skutečné MCP stdio a HTTP čtyři negativní vstupy: explicitní null budget, neplatné oprávnění `edit`, zákaz čtení a zákaz testů v execute. Každý vrátil odpovídající odmítnutí; `work_orders` měla 0 řádků. Odpovědi: `mcp-preflight-results.json`. Local model endpoint byl záměrně nedostupný a žádná práce nebyla spuštěna.

## Další izolovaná ověření

- Kandidát `candidate-review-wire`, wheel SHA-256 `659f63eefcd30a51c9d5244f817209a7064011ea357e891c3ce726cb413d9f1b`: skutečné MCP vrátilo `review_scope_complete=false` při limitu 256 tokenů pro vyloučený nesledovaný soubor (`req_32cd4bdb0f05`) i pro směs sledované změny a nesledovaného souboru (`req_bc5af32ba5d8`). Stromy vlastních procesů byly ukončeny. Předcházející pokus správně odhalil ztrátu příznaku na MCP hranici; po opravě prošel.
- Kandidát `candidate-diff-facts`, wheel SHA-256 `56dbcaeca4e383735a92d774ed18d1ee37743f608ec828901f9f20988528d806`: skutečné MCP zkontrolovalo výslovně zadaný malý nesledovaný soubor, správně spočítalo řádek připomínající hlavičku diffu a vrátilo SHA-256 zdroje (`req_c20be81310ac`). Vlastní strom procesů byl ukončen. Přesné hashe překrytých zdrojů a odpovědi jsou v sandboxu.

Tato ověření neprokazují plnou sadu, produkční instalaci, dokončení Agent OS úloh ani review všech nesledovaných souborů. Bounded review zatím odmítá větší soubory a některé názvy cest.

Tyto kontroly nedokazují úspěšný vygenerovaný diff, autentický validační receipt, kvalitu modelu, finální integrovaný kandidát ani produkční runtime. Selektivní test/build povolení v execute jsou zatím fail-closed a nepodporovaná.
