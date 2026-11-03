# Audit specifikací a plánů Local AI Hub

**Datum:** 2026-11-03  
**Stav:** dokončený inventář; acceptance produktu není uzavřené.

## Verdikt

Ne. Všechny požadavky nejsou doložené jako implementované a přijaté. Zdrojové cesty a statické testy existují pro řadu požadavků, ale aktuální běhy testů, integrované CI a runtime acceptance zde nebyly ověřeny. Některé plány výslovně ponechávají práci otevřenou.

## Rozsah

- 103 unikátních cest: 66 plánů, 32 Markdown specifikací, 1 JSON kontrakt a 4 související dokumenty.
- Původních „104“ započítalo JSON kontrakt dvakrát.
- Navíc přečteno 7 dalších receiptů jako podkladů; nejsou součástí inventáře specifikací/plánů.
- Všechny cesty inventáře mají řádek v [matici auditu](2026-11-03-spec-plan-audit-matrix.md).
- Ověření kódu a testů bylo read-only. V repozitáři vznikly pouze tyto dva reporty; produkční kód ani testy se neměnily.
- Nebyly spuštěny testy, buildy, importy, instalace ani runtime.

## Kritické neuzavřené brány

1. **Aktuální release:** [stavový plán 2026-11-02](superpowers/plans/local-ai-hub-current-status.md) uvádí selhání master CI (pyflakes a kritická coverage), přeskočené package/publish kroky, neintegrované kandidáty a otevřené release acceptance.
2. **T09 completion/receipts:** [source review](superpowers/receipts/2026-10-01-t09-spec-review-r1.md) výslovně nařizuje HOLD. Hlásí zaměnitelný root/worktree a memory context, alternativní terminal-completion cestu mimo důvěryhodnou gate, slabé ověření structured argv/environment, alias provenance, ownership API mismatch a opaque-root binding. Historické průchody tato místa nepokrývají. Oprava v aktuálním HEAD nebyla potvrzena.
3. **T16 orchestrace a lease:** [source review](superpowers/receipts/2026-10-01-t16-spec-review-r1.md) říká spec-compliant NO / merge-ready NO. Následná kontrola ponechává writer-token counter floor, restore ancestor preflight, broker namespace forwarding a skutečný broker E2E otevřené. Kandidátní průchody nejsou root acceptance.
4. **T11 RAG provenance:** [isolation review](superpowers/receipts/2026-10-01-t11-isolation-review-r1.md) hlásí chybějící embedding-space filtr ve FTS, reuse bez provenance s relabelováním embeddings a nekomponovatelné patche. Veřejná cache/runtime acceptance není doložena.
5. **T12 model admission/unload:** [review r3](superpowers/receipts/2026-10-01-t12-r3-review.md) nechává otevřené canonical admission před runtime startem, timeout/lifetime child procesu, joined runtime a skutečné GPU/VRAM uvolnění.

Tyto review receipts jsou z 2026-10-01. Jejich nálezy jsou důvodem pro HOLD/NOT VERIFIED, nikoli potvrzením, že dnešní HEAD stále obsahuje stejnou chybu. Aktuální uzavření nebylo ověřeno.

## Další chybějící nebo neověřené požadavky

- **Reálná retrieval kvalita:** [T02 plan](T02-real-input-quality-evidence-plan.md) uvádí, že chybí povolený corpus manifest, označené dotazy, retrieved IDs a metriky. Syntetická evaluace je nenahrazuje. Thresholdy a resource window potřebují schválení.
- **Párový benchmark:** [T02 runner](superpowers/plans/2026-10-02-t02-paired-baseline-runner.md) čeká na neměnné source piny a CPU slot; šest případů, stejná konfigurace, izolované scratch/state a odmítnutí neúplných výsledků nejsou doložené aktuálním receiptem.
- **Výkon:** doložený JSON microbenchmark se vztahuje jen na 1 000 párů a jeho zaznamenané p95/p99. Neprokazuje obecné end-to-end zrychlení, Cython/native adopci ani cíle vln 1–6. Cython experiment zůstává vypnutý do compiler a end-to-end acceptance.
- **Transakční izolace příkazů:** vlastní plán říká, že plná izolace není dokončena; širší platformní/Docker ověření zůstává otevřené.
- **T03 MCP:** živá shoda osmi action schema, daemon-off autostart/cleanup a nezávislý Hub receipt nejsou aktuálně doloženy.
- **Vlny 1–6:** spolehlivost, storage/performance, AST/index, command execution, koordinace/memory a multimodální/GPU acceptance nemají čerstvý integrovaný release důkaz.
- **Browser/desktop/GPU:** osobní Chrome, Windows desktop, sandbox/egress, live vision a fyzický VRAM cleanup zůstávají neověřené; browser broker má zůstat defaultně vypnutý.
- **Fuzzy trigram:** plán ponechává unit testy neprovedené, source bundle closure a paired pinned benchmark otevřené.
- **Exact search:** test prefilteru existuje a [historický T21 receipt](superpowers/receipts/2026-10-01-t21-root-search-acceptance.md) uvádí 22 passing testů pro omezený root slice. Nejde o současné full-suite/release acceptance; novější plan kroky release/doctor/prompt review jsou otevřené.
- **Adoption a consistency guard:** zdrojové symboly a testy existují, ale čerstvost indexu byla stale a úplné chování nebylo ověřeno. Chybí 14denní baseline, pilot a promotion receipts; současná guidance jasně nevynucuje context pack pro každý task.
- **Trace pravidla:** starší redakční/size pravidla jsou nahrazena, ale credential redaction v navazující specifikaci se rozchází s aktuální instrukcí pro trace bez redakce. Autoritativní pravidlo není sjednoceno.
- **Caveman/Antigravity:** Caveman zdroj a statické testy jsou přítomné; reálná kvalita/rychlost instrukcí není doložena. Antigravity instalace, opakovaný setup, discovery a živé použití jsou externí a neověřené.
- **repo-plan.v1:** příklad i metaschema/round-trip testy jsou ve zdroji. Testy nebyly spuštěny; živá API/schema shoda a runtime conflict behavior jsou neověřené.
- **Eval fixtures:** plán hlásí stale integration preview a rozpor service status vs. hubctl status; aktualizované ověření chybí.

## Limity důkazů

- Statická přítomnost symbolu/testu neznamená, že test prochází nebo že chování platí v produkčním runtime.
- Část indexovaných výsledků byla označena stale; exact source review nebo běh by byl nutný pro uzavření.
- Hub byl při závěrečném status call online, ale bez aktivního modelu; Ollama probe byla degraded/timeout. Modelový second opinion nebyl proveden.
- Čerstvý full pytest, release_check, compileall, selftest, balíček/instalace, hostovaný CI ani hardware/browser acceptance v tomto auditu neběžely.

## Závěr

Inventář je uzavřen; implementace/release acceptance nikoli. Otevřené položky výše zůstávají `NOT VERIFIED` nebo explicitně `OPEN/HOLD`. Pro jejich uzavření je potřeba ověřit aktuální root/revision a získat nové receipts; staré candidate logy nestačí.
