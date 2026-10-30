# 092: mezikandidát 2026-10-29

V izolovaném sandboxu `<temp>/local-ai-eval-096-984a57350263462c99b8ac24860fe3b3/candidate-prewire` byl z commitu `6c7200a9c1b71554ebe368b8722a6757d94c0282` a čtyř upravených zdrojových souborů sestaven wheel SHA-256 `374db60769534bca56ee9fb7c249123eb6b712eeffd27302176027766e588b71`. Přesné zdrojové hashe jsou v sandboxovém `source-manifest.json`; kandidát není integrovaný ani finální.

HTTP smoke nainstalovaného wheelu ověřil verzi 5.1.0, identitu listeneru a ukončení vlastního stromu; důkaz `smoke-result-state-61994.json`. První MCP pokus byl neprůkazný, protože work orchestrator byl vypnutý; výsledky jsou uloženy zvlášť jako `mcp-preflight-results-disabled.json`.

Po úpravě izolované konfigurace prošly přes skutečné MCP stdio a HTTP čtyři negativní vstupy: explicitní null budget, neplatné oprávnění `edit`, zákaz čtení a zákaz testů v execute. Každý vrátil odpovídající odmítnutí; `work_orders` měla 0 řádků. Odpovědi: `mcp-preflight-results.json`. Local model endpoint byl záměrně nedostupný a žádná práce nebyla spuštěna.

## Další izolovaná ověření

- Kandidát `candidate-review-wire`, wheel SHA-256 `659f63eefcd30a51c9d5244f817209a7064011ea357e891c3ce726cb413d9f1b`: skutečné MCP vrátilo `review_scope_complete=false` při limitu 256 tokenů pro vyloučený nesledovaný soubor (`req_32cd4bdb0f05`) i pro směs sledované změny a nesledovaného souboru (`req_bc5af32ba5d8`). Stromy vlastních procesů byly ukončeny. Předcházející pokus správně odhalil ztrátu příznaku na MCP hranici; po opravě prošel.
- Kandidát `candidate-diff-facts`, wheel SHA-256 `56dbcaeca4e383735a92d774ed18d1ee37743f608ec828901f9f20988528d806`: skutečné MCP zkontrolovalo výslovně zadaný malý nesledovaný soubor, správně spočítalo řádek připomínající hlavičku diffu a vrátilo SHA-256 zdroje (`req_c20be81310ac`). Vlastní strom procesů byl ukončen. Přesné hashe překrytých zdrojů a odpovědi jsou v sandboxu.

Tato ověření neprokazují plnou sadu, produkční instalaci, dokončení Agent OS úloh ani review všech nesledovaných souborů. Bounded review zatím odmítá větší soubory a některé názvy cest.

## Closed-work delegace — 2026-10-30

- Disposable root: `%TEMP%\local-ai-eval-092-20261030-001`, seed commit `befe896402eee677bcdbf43d9d02873605946362`.
- První skutečná delegace `wo_028782a1dd24434f818f` byla přijata, ale skončila `local worker returned no unified diff`; artifact `art_a10584b497c195bff57a0f2a`, `llm_calls=4`, změněné soubory 0, validační příkazy 0. Pokus o pokračování po terminálním failu správně odmítl stav „work order is not waiting for agent input“.
- Sémantické review worker výstupu bylo nepoužitelné; delegace nedokládá dokončení ani receipt. Zjištění vedlo k opravě WorkOrchestrator: po prázdném výstupu přejde na jediný retry s `complexity=heavy`; další prázdný diff zůstává fail-closed. Zatím ověřeno cíleným testem, ne živým během po restartu.
- Referenční změna provedená pouze ručně v disposable rootu přidala `--output`; `python -m unittest oracle_092` prošel `3/3`. Diff měnil pouze `report.py`; SHA-256 pracovního souboru `26b1042b207cb0c066356915fad431d8e394ff6d409a7107542a3787a5525d5b`.
- Zbývá znovu spustit opravnou delegaci proti restartovanému kandidátovi a zachovat výsledek. Ruční oracle pass nenahrazuje agentní delegaci ani autentický Agent OS receipt.

Tyto kontroly nedokazují úspěšný vygenerovaný diff, autentický validační receipt, kvalitu modelu, finální integrovaný kandidát ani produkční runtime. Selektivní test/build povolení v execute jsou zatím fail-closed a nepodporovaná.

## Opakování po změně routování — 2026-10-30

- `%TEMP%\local-ai-eval-092-20261030-003`, seed `09143c723109193ba05f81584d67d0f2ebfe1fde`: preprocess root odmítl jako `ephemeral/system directory`; work `wo_4d48aaef074446b79d2a` přesto přijalo, ale skončilo bez unified diff po heavy retry. Změny 0, validace 0.
- Stabilní sandbox `C:\eval\Documents\local-ai-hub-eval\case-092-20261030-001`, seed `0213c60c2ebda3e90d408983a0ec3fb2b11b6dd0`: preprocess přijal, práci zařadil do fronty. Work `wo_83a087aab4ea4855a8d1` opět skončilo `local worker returned no unified diff after heavy-code retry`; změny 0, validace 0. Odpověď neobsahovala validní completion ani receipt.
- Přímý `local_ai_task` s `qwen-drafter` vybral `qwen2.5-coder:3b`, vrátil návrh `file_slice` jako text, `tool_calls=0`. Přímá žádost s kontextem a `qwen2.5-coder:7b` také vrátila obecný popis bez diffu; pozdější inference hlásila `admission_state=degraded`, `pressure_level=critical`. To je model/routing evidence, ne důkaz změny fixture.
- Nález: editované work kroky volaly `delegate_repo` s `task_type=auto`; změna nyní předává explicitní `task_type=code`, retry dál zvyšuje `complexity` z `auto` na `heavy`. Regresní test ověřuje oba parametry a fail-closed konec. Ještě nutné ověřit na Hubu po restartu.
- Manuální referenční oracle `3/3` z předchozího běhu zůstává oddělený. Žádný agentní run zatím neprošel validací.
- Pozdější restart main Hubu vrátil `restarted`, ale první MCP status skončil retryable `503`; post-restart běh zatím nepotvrzen.
- Po restartu MCP znovu přijalo work `wo_7c0488339e5f41a9b3d0`, ale edit skončil bez diffu po heavy retry, změny 0, validace 0. Tento běh zahrnoval `task_type=code` v `WorkOrchestrator`, ne nový prompt builder.
- Kořen: `LocalAIServices.delegate` při `operation=code` neměl code-specific prompt contract; `prompt_contracts.build_prompt` použil obecný `SUMMARY/EVIDENCE/ANALYSIS/LIMITATIONS/NEXT`, přestože work žádá unified diff. Doplněn `code` operation guidance a diff-only response. Test prompt contractu nejprve selhal správně, po změně prošel spolu s fail-closed retry testem (`2 passed`). První work request po novém restartu nebyl odeslán.
- Druhý restart vrátil `restarted`; následný work MCP request nebyl odeslán (`request_not_sent=true`). Bounded native `hubctl status` potvrdil Hub 5.1.2 online (PID 41944), Ollama online, 8 modelů a dedicated GPU 7 GB. MCP po nové prompt opravě zatím nepotvrzen.
- Následující live MCP work `wo_a3e89f5357474c229c8e` byl přijat. Code-specific diff prompt vygeneroval patch, ale aplikace selhala `error: corrupt patch at line 35`; změny 0, validace 0. Artifact `art_7c71e9bc61c29011a76f7e8d` potvrzuje prázdný working-tree diff a jen dříve existující `.serena/`.
- Izolovaná reprodukce ukázala, že špatný počet řádků v hunk headeru způsobí tiché vynechání přebytečného kontextu. `git apply --recount` v preview, check i apply cestě zachová celý patch; regresní test nejprve selhal s oříznutým postimage, poté prošel (`3 passed`). Nový restart a live rerun zbývá.
- Restartovaný MCP Hub přijal work `wo_982a852888fc436999d5` na seed `0213c60c2ebda3e90d408983a0ec3fb2b11b6dd0`; retry po code-only prompt skončil `patch failed: report.py:13`, validace 0. Přesný modelový diff není v handoffu, takže příčina je ohraničená na neslučivý kontext a neprokázaná hlouběji.
- Čerstvý seed `5e6bafacbaf71aae985885ec6377296d1680aca5` (`case-092-20261030-002`) dostal skutečný prompt z `zadani.md`. Work `wo_1802ddf1ba5f47fcacad` byl při jediném 45s wait stále `executing` (1/4); žádný další wait/poll neproběhl. Výsledek a změny tohoto běhu zůstávají neznámé.
- Nová regresní ochrana pro patch retry připojuje pouze přesně dotčené, UTF-8 textové soubory bezpečně uvnitř rootu, s limitem 12 kB a přeskočením citlivě pojmenovaných cest. Cílená sada: `3 passed` včetně hunk recount, retry routingu a ověření přesného CRLF preimage.
