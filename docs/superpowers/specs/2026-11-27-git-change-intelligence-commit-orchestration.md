# GOAL: Complete Git Change Intelligence & Commit Orchestration end-to-end

Execution map: [`../plans/2026-11-27-git-change-intelligence-completion.md`](../plans/2026-11-27-git-change-intelligence-completion.md). The Hub plan `.local-ai-hub/plans/plan_7022c137eeae.plan.json` remains the sole source of task state and completion evidence.

## 1. Zadání a pracovní prostředí

Pracuj přímo v repozitáři:

- Repository: https://github.com/Harfusha/local-ai-hub
- Pracovní větev: `feat/git-change-intelligence`
- Pull request: https://github.com/Harfusha/local-ai-hub/pull/11
- Cílová integrační větev: `master`
- Poslední známá revize: `ff373cde5ee1a682c03b2a9964e299c713d5710b`

Tvým úkolem je **kompletně dokončit Git Change Intelligence & Commit Orchestration, jeho integraci do Local AI Hubu a následně integrovat dokončenou větev do masteru**.

Nejde pouze o opravu aktuálně známých chyb. Musíš dokončit celý původní implementační plán, zkontrolovat existující implementaci, odstranit architektonické nedostatky, optimalizovat výkon, doplnit testy a dokumentaci a zajistit konzistentní fungování celého systému.

Pracuj autonomně a nepřerušuj práci po dokončení jednotlivých kroků. Pokračuj opravou dalších nedostatků, dokud nejsou splněny všechny akceptační podmínky.

Nevytvářej další samostatný PR pro nedokončenou část tohoto úkolu. Nevytvářej pouze plán budoucí implementace. Plán musí být skutečně implementován.

## 2. Povinné vstupní seznámení s projektem

Před implementací důkladně prostuduj:

- `docs/GIT_CHANGE_INTELLIGENCE.md` – celý dokument včetně původní cílové architektury, akceptačních podmínek a všech následných implementačních dodatků.
- Celý popis PR #11, jeho historii, změny, komentáře, výsledky CI a otevřené problémy.
- Relevantní `AGENTS.md` a ostatní projektové instrukce.
- Aktuální architekturu Local AI Hubu.
- Agent OS, Task Store, Verification Store, Context Ledger, Command Broker, Work Fencing, Code Index, Artifact Store a Git-first Project Intelligence.
- Existující desktopovou aplikaci v Rustu, Python bridge, CLI, HTTP a MCP rozhraní.
- Instalační, aktualizační a migrační mechanismy.
- Související změny v PR #10 a PR #12 a aktuální stav masteru.

Nespoléhej na to, že předchozí agent označil určitou funkci jako dokončenou. Každý takový stav ověř proti skutečnému produkčnímu kódu, jeho volajícím a testům.

Vytvoř v rámci implementační dokumentace úplnou trasovací matici požadavků. Každý požadavek musí mít identifikátor, stav, odpovídající implementaci, testy a konkrétní důkaz splnění.

Průběžně ji aktualizuj. Nesmí sloužit jako náhrada implementace.

## 3. Zásadní architektonické požadavky

Výsledkem musí být jedna integrovaná součást Local AI Hubu, nikoli další izolovaný subsystém.

Používej existující infrastrukturu Hubu všude, kde je to možné a architektonicky správné.

Především:

- Nevytvářej paralelní Task Store, Verification Store, Artifact Store, systém projektové konfigurace, systém oprávnění nebo koordinace agentů.
- Konsoliduj překrývající se implementace.
- Udržuj jednu kanonickou implementaci každé odpovědnosti a datového kontraktu.
- MCP, HTTP, CLI a desktop musí využívat stejnou aplikační logiku.
- Nevytvářej zvláštní implementaci Git inteligence pro jednotlivé klienty.
- Nepřidávej další MCP nástroje, pokud lze funkci začlenit do existujícího sedminástrojového katalogu.
- Nevynucuj cloudové modely pro úlohy, které lze deterministicky nebo lokálně vyřešit.
- Zachovej vysokou typovou bezpečnost, modularitu, testovatelnost a nízkou spotřebu systémových prostředků.
- Zajisti plnohodnotné fungování na Windows, Linuxu a macOS.
- Nepřidávej zbytečné závislosti, procesy na pozadí, databáze nebo pravidelné full-repository scany.

Pokud je existující architektura nevhodná, uprav ji. Neudržuj špatný návrh jen proto, že již existuje.

## 4. Absolutní zákaz legacy chování a zpětné kompatibility

Tento požadavek má přednost před všemi staršími pokyny v implementačním plánu, které požadovaly zachování zpětné kompatibility.

Nechci žádné trvalé legacy chování.

Odstraň zejména:

- Legacy API kontrakty a alternativní zastaralé formáty odpovědí.
- Deprecated metody, parametry, aliasy a příkazy.
- Kompatibilní wrappery a adaptéry sloužící pouze starým implementacím.
- Staré datové modely a paralelní databázová schémata.
- Dual-read a dual-write mechanismy.
- Automatické přepínání mezi starou a novou architekturou.
- Legacy feature flags.
- Staré implementace seskupování změn.
- Neověřené explicit-path klasifikace mimo Git, pokud jsou zachovány pouze kvůli kompatibilitě.
- Legacy full-mode chování HTTP endpointu.
- Duplicitní lineární plánování závislostí, pokud je nahrazeno kvalitnějším grafovým plánováním.
- Legacy dashboard a všechny související HTML, CSS, TypeScript, JavaScript, assety, build nástroje, routy, instalační kroky, konfigurace, příkazy a dokumentaci.
- Příkaz `dashboard`, pokud je pouze kompatibilním aliasem desktopové aplikace.
- Všechny staré instrukce a příklady, které agenty navádějí na odstraněné funkce.
- Nepoužívaný kód, testy zastaralých kontraktů a mrtvé větve programu.

Jedinou povolenou výjimkou je **jednorázová migrace při aktualizaci existující instalace**.

Migrace musí:

1. Rozpoznat původní verzi schématu nebo instalace.
2. Bezpečně převést podporovaná trvalá data do nové kanonické struktury.
3. Zachovat uživatelská nastavení, důležitá data, oprávnění a relevantní historii.
4. Odstranit nebo invalidovat obnovitelné cache, jejichž migrace nedává smysl.
5. Bezpečně zpracovat přerušení aktualizace, nedostatek místa, poškozená data a opakované spuštění.
6. Být transakční všude, kde je to technicky možné.
7. Ověřit konzistenci výsledných dat před potvrzením dokončení.
8. Zaznamenat dokončení migrace prostřednictvím existujícího migračního mechanismu.
9. Po úspěšném dokončení nepoužívat původní schéma, staré soubory ani starou logiku.

Migrační kód může zůstat v aktualizačním mechanismu pro uživatele přecházející ze starších verzí. Nesmí však být součástí běžného runtime rozhodování.

Čistá instalace musí rovnou používat výhradně nový datový model a novou architekturu.

Rozlišuj legacy fallback od legitimního moderního bezpečnostního fallbacku. Například přechod z dávkového čtení Git patchů na jednotlivé přesné čtení při chybě je v pořádku. Přechod na starou, méně bezpečnou implementaci nebo zastaralý kontrakt v pořádku není.

## 5. Hlavní produktový cíl

Git Change Intelligence má významně snížit množství opakované práce cloudových agentů při:

- Analýze dirty worktree.
- Kontrole velkého množství změn.
- Opakované kontrole již analyzovaných souborů.
- Přípravě commitů.
- Rozdělování změn do logických commitů.
- Generování commit messages.
- Kontrole závislostí mezi změnami.
- Ověřování změn.
- Vytváření pull requestů.
- Generování release notes.
- Předávání rozpracované práce jinému agentovi.

Cloudový agent nemá opakovaně číst celý diff, pokud Hub již disponuje aktuálními, dostatečnými a ověřitelnými informacemi.

Zároveň nesmí optimalizace spotřeby tokenů způsobovat vynechání změn, ignorování problémů, falešné potvrzení správnosti nebo ztrátu kontextu.

Cílem je snížit náklady při zachování nebo zvýšení kvality výsledků.

# Povinné implementační oblasti

## 6. Snapshot engine a Change Ledger

Dokonči kanonický systém pozorování Git změn.

Musí přesně rozlišovat:

- Repository a worktree identitu.
- HEAD, branch a index.
- Staged a unstaged změny.
- Untracked soubory.
- Přidané, odstraněné, přejmenované a kopírované soubory.
- Binární změny.
- Změny oprávnění a typu souboru.
- Symlinky.
- Submoduly.
- Konflikty.
- Překrývající se hunks.
- Externí změny provedené uživatelem nebo jiným agentem.

Doplň nebo oprav:

- Stabilní content-addressed identifikátory.
- Identitu jednotlivých patchů, hunků, souborů, skupin a snapshotů.
- Přesné rozlišení původního a výsledného obsahu.
- Spolehlivé odhalování změn obsahu při zachování velikosti a timestampu.
- Ověření konzistence před a po pozorování.
- Inkrementální zpracování.
- Bounded streaming a dávkové operace.
- Content-addressed L1/L2 cache.
- Watcher-driven invalidaci a reverzní závislosti.
- Bezpečné slučování souběžných pozorování.
- Automatický úklid a omezení velikosti lokální evidence.
- Izolaci mezi různými repozitáři, worktrees, projekty a agenty.

Současná implementace dávkově zpracovává až osm patchů na jednu Git operaci a maximálně 256 patch scopes na pozorování.

Ověř její správnost, optimalizuj ji a odstraň stav, kdy velký dirty worktree nelze smysluplně zpracovat jen kvůli fixnímu limitu.

Preferuj bezpečné stránkování, inkrementální snapshoty, pokračovací kurzory a transparentní evidenci nepokrytých oblastí před neomezenými operacemi.

Žádný soubor ani změna nesmí zmizet z inventáře bez explicitního označení.

Pokud nelze garantovat kompletní pozorování, nesmí být nekompletní snapshot prezentován jako kompletní ani autorizovat mutaci.

## 7. Provenance, autorství a evidence práce agentů

Propoj Git Change Ledger s existujícími Agent OS úlohami, pracovními pokusy, leasingem, Command Brokerem a systémem ověřovacích důkazů.

Rozlišuj minimálně:

- Pozorovanou změnu.
- Změnu asociovanou s úlohou.
- Změnu deklarovanou agentem.
- Změnu zaznamenanou přes důvěryhodnou instrumentaci.
- Změnu provedenou prostřednictvím fenced Command Brokeru.
- Uživatelskou nebo externí změnu.
- Změnu s neznámým autorstvím.
- Nejednoznačné nebo konfliktní autorství.

Doplň autentizovanou instrumentaci spravovaných agentů tam, kde je to možné.

Využívej serverem ověřenou identitu tasku, attemptu, session a autorizovaného pracovního rozsahu. Pokud lze zachytit preimage a postimage, přesně je propoj s pozorovanými atomy změn.

Nezaměňuj:

- Časovou korelaci za důkaz autorství.
- Existenci lease za důkaz provedení změny.
- Shodu postimage za důkaz autorství celého patche.
- Deklaraci agenta za důvěryhodný ověřovací důkaz.

U nativních externích editorů bez důvěryhodné instrumentace musí autorství zůstat neznámé.

Nepokoušej se tento principiální problém řešit falešným přisuzováním změn.

Umožni více agentům bezpečně pracovat v jednom projektu, aniž by si navzájem přivlastňovali změny nebo commitovali cizí práci.

## 8. Sémantická analýza změn

Dokonči víceúrovňový systém sémantického popisu změn.

Podporuj úrovně:

- Hunk a change atom.
- Symbol, funkce, metoda a třída.
- Soubor.
- Modul.
- Logický celek.
- Task.
- Commit.
- Branch.
- Pull request.
- Release.

Maximálně využívej existující AST, symbol index, source facts, call graph, import graph, business graph, test mappings a projektové znalosti.

Doplň analýzu:

- Přidaných, odstraněných a změněných symbolů.
- Změn signatur a veřejných kontraktů.
- Změn datových modelů.
- Změn databázových schémat a migrací.
- Změn konfigurace.
- Změn závislostí a lockfiles.
- Dopadů na veřejná API.
- Breaking changes.
- Změn testovacího pokrytí.
- Bezpečnostně významných změn.
- Změn relevantních pro build, packaging a deployment.
- Přesunů a přejmenování symbolů nebo souborů.

Rozšiř současnou sémantickou analýzu, která je stále omezená počtem analyzovaných scopes a některými jazykovými heuristikami.

Podporované jazyky musí konzistentně využívat existující polyglot infrastrukturu Hubu. Nevytvářej zbytečně nové parsovací systémy.

Pokud je dostupný lokální model, využij ho pro:

- Přirozené shrnutí změn.
- Návrh logického seskupení.
- Vysvětlení záměru.
- Commit messages.
- PR popisy.
- Release notes.
- Identifikaci oblastí vyžadujících další kontrolu.

Model musí pracovat nad strukturovanými deterministickými fakty. Jeho výstup musí být validovaný proti schématu a skutečným identifikátorům změn.

Lokální model nesmí vymýšlet provedené testy, autorství, úplnost kontroly, neexistující změny ani závislosti prezentované jako ověřená fakta.

Sémantické shrnutí nesmí být považováno za důkaz správnosti implementace.

## 9. Inteligentní seskupování změn a dependency graph

Nahraď zbývající primitivní seskupování založené pouze na názvech souborů kvalitním kombinovaným grafovým modelem.

Graf musí kombinovat:

- Deterministicky prokázané závislosti.
- Importy a reference.
- Symbolové a call-graph závislosti.
- Task associations.
- Testovací vazby.
- Databázové migrace.
- Konfigurační závislosti.
- Build a package dependencies.
- Vazby mezi implementací, dokumentací a testy.
- Sémantickou podobnost.
- Projektové konvence.

Rozlišuj hard dependencies, soft dependencies a nejisté kandidátní vztahy.

Používej strongly connected components pro cyklické závislosti a následné topologické řazení commit jednotek.

Ověř aktuálnost všech použitých indexovaných dat. Zastaralý index nesmí být důkazem aktuální závislosti ani důvodem k přeskočení kontroly.

Zahrň nezměněné konzumenty změněných symbolů, nikoliv pouze vztahy mezi změněnými soubory.

U dynamických jazyků a nerozřešených závislostí explicitně eviduj nejistotu. Netvrď, že je graf úplný, pokud to nelze prokázat.

Umožni uživateli nebo autorizovanému agentovi:

- Upravit navrhované skupiny.
- Sloučit skupiny.
- Rozdělit skupiny.
- Přesunout změnu mezi skupinami.
- Upravit pořadí commitů.
- Explicitně vyloučit změnu.
- Změnit commit message.
- Rozdělit změny uvnitř jednoho souboru na základě přesných hunk identit.

Každá úprava plánu musí být znovu validována.

Každý change atom musí být zahrnut právě jednou, nebo musí být explicitně označen jako vyloučený, nepozorovaný či blokovaný.

Žádná změna nesmí být potichu ignorována.

## 10. Inkrementální kontext a optimalizace tokenů

Dokonči systém, který umožní agentovi získat pouze nový nebo invalidovaný kontext.

Musí podporovat:

- Plný přehled.
- Kompaktní summary.
- Detail konkrétní skupiny.
- Detail konkrétního atomu nebo hunku.
- Delta od dříve pozorované revize.
- Odstraněné skupiny.
- Nově vzniklé skupiny.
- Změněný dependency context.
- Změněnou evidenci review a verification.
- Přesné artifact-backed detaily.
- Bezpečné pokračování přes více stránek.
- Invalidaci zastaralých tvrzení.

Nezměněné skupiny nesmí být znovu analyzovány jen kvůli nesouvisející změně v repozitáři.

Pokud se změní závislost, invaliduj relevantní tranzitivní konzumenty.

Pokud se změní pouze review stav, nezahazuj zbytečně sémantickou cache.

Pokud je výsledek příliš velký, musí Hub vrátit použitelnou kompaktní reprezentaci s identitou a instrukcí pro načtení detailů.

Zkontroluj skutečný MCP wire formát včetně:

- Textového obsahu.
- Structured content.
- Duplicitní serializace.
- Obalových metadat.
- JSON escaping.
- Response budget metadata.
- Artifact pointers.
- Recovery instructions.
- Error envelopes.
- Pagination.

Aktuálně známá kritická regrese souvisí s překročením limitu 128 tokenů kvůli následnému přidání structuredContent. Existuje implementovaný fix, ale musíš jej ověřit skutečným end-to-end testem.

Nevydávej pouhý odhad velikosti vnitřního JSON objektu za velikost skutečně emitované MCP odpovědi.

## 11. Review, verification a evidence reuse

Dokonči jednotný životní cyklus kontroly změn.

Jednoznačně rozlišuj stavy:

- Observed.
- Summarized.
- Reviewed.
- Needs review.
- Verified.
- Failed.
- Stale.
- Skipped.
- Unknown.
- Approved.
- Committed.

Každý stav musí mít přesně definovaný význam, podmínky přechodu a zdroj autority.

Zajisti integraci s existujícím Verification Store a Agent OS acceptance criteria. Odstraň zbytečné překrývání samostatných evidencí, aniž by došlo ke ztrátě odlišných významů jednotlivých důkazů.

Evidence musí být svázána s:

- Přesným repository/worktree scope.
- Obsahem.
- Git tree identitou.
- Dependency contextem.
- Testovacím příkazem a jeho argumenty.
- Konfigurací.
- Prostředím.
- Relevantními acceptance criteria.
- Identitou důvěryhodného pracovního pokusu.
- Časem platnosti.

Při změně jedné části projektu invaliduj pouze skutečně dotčené důkazy, pokud to lze bezpečně prokázat.

Při nejasné invalidaci postupuj konzervativně a požaduj nové ověření.

Ověření celého dirty worktree nesmí automaticky autorizovat commit obsahující pouze jeho podmnožinu.

Každý intermediate tree v commit sequence musí mít vlastní platné ověření.

Doplň robustní:

- Reuse platných receipts.
- Detekci zastaralých receipts.
- Fencing konkurenčních pokusů.
- Evidenci selhání a přerušení.
- Expiraci.
- Explicitní re-verification.
- Ochranu proti zneplatnění důkazu během commit publication.
- Propojení relevantních artifact IDs.
- Recovery po pádu procesu.

Dokonči projektovou politiku `git_commit` a bezpečné generování verification manifestů.

Zjednoduš jejich používání. Agent ani uživatel by neměl ručně sestavovat technické hodnoty, které Hub dokáže spolehlivě odvodit sám.

Především nikdy automaticky nevytvářej smyšlený environment digest. Pokud skutečnou identitu prostředí nelze získat, transparentně vyžaduj explicitní doplnění.

Odstraň produkční bypassy, které umožňují označit neověřenou sekvenci za bezpečnou nebo obejít požadovanou projektovou politiku. Prověř zejména `--allow-unverified` a samostatnou cestu `commit-staged`. Konsoliduj je do jednotné publikační logiky bez obcházení povinného ověření.

## 12. Bezpečné plánování, staging a vytváření commitů

Dokonči celý transakční životní cyklus:

1. Pozorování změn.
2. Sestavení logického plánu.
3. Kontrola autorství a pracovního rozsahu.
4. Review nevyřešených změn.
5. Výběr atomů.
6. Vytvoření přesného prospective tree.
7. Preview.
8. Explicitní schválení.
9. Staging.
10. Re-observation.
11. Sestavení commit sequence.
12. Nezávislé ověření jednotlivých stromů.
13. Finální revalidace.
14. Publikace.
15. Zápis commit SHA a evidence.
16. Recovery a závěrečný reporting.

Implementuj nebo dokonči:

- Whole-file staging.
- Partial staging.
- Více nezávislých hunků.
- Rozdělení jednoho souboru mezi více commitů v rámci jedné sekvence.
- Více logických commitů.
- Kontrolu již staged změn.
- Zachování nesouvisejících unstaged změn.
- Zachování uživatelských a cizích agentových změn.
- Přesný index a tree verification.
- Compare-and-swap nad Git refs.
- Sdílené repository leases.
- Ochranu před souběžnou mutací.
- Durable transaction journal.
- Bezpečné a idempotentní recovery.

Prověř a podle možností odstraň současná omezení pro linked worktrees, sparse/split index, submoduly, filtry, Git hooks a signing.

Podpora těchto případů musí respektovat skutečnou Git sémantiku a bezpečnostní požadavky. Pokud určitý případ nelze bezpečně zpracovat interním transakčním mechanismem, použij korektní kanonický Git workflow nebo operaci explicitně zablokuj s konkrétním vysvětlením.

Nikdy nepřeskakuj hooks, signing nebo bezpečnostní pravidla jen proto, aby operace prošla.

Nikdy:

- Automaticky nepoužívej blanket `git add .` nebo `git add -A` bez přesného schváleného rozsahu.
- Nenič existující změny.
- Neprováděj automatický destruktivní reset nebo stash.
- Nepřepisuj publikovanou historii.
- Nepřivlastňuj si cizí změny.
- Neopakuj naslepo operaci s neznámým výsledkem.
- Nepublikuj commit mimo schválený rozsah.
- Neprováděj automatický push jako vedlejší efekt Git Change Intelligence operace.

Git transakce musí zůstat bezpečné i při externích Git operacích, pádu procesu, timeoutu, chybějících oprávněních a změně HEAD.

## 13. Plná integrace do Agent OS a pracovních procesů

Git Change Intelligence nesmí být pouze volitelným pomocným nástrojem, o jehož existenci agent neví.

Integruj ji do existujících agentových lifecycle procesů:

- Zahájení úlohy.
- Načtení relevantního kontextu.
- Plánování.
- Přiřazení pracovního rozsahu.
- Souběžná práce agentů.
- Průběžná kontrola.
- Checkpointing.
- Handoff.
- Obnovení práce po přerušení.
- Kontrola implementace.
- Ověření acceptance criteria.
- Příprava commitů.
- Ukončení úlohy.

Agent musí být schopen zjistit:

- Co se změnilo.
- Které změny již analyzoval.
- Které změny mají aktuální review.
- Které důkazy lze znovu použít.
- Které změny byly invalidovány.
- Co zbývá zkontrolovat.
- Jaké soubory nebo hunks patří do jeho úlohy.
- Jaké změny nesmí zahrnout do svého commitu.
- Jaké další ověření je potřeba.

Maximálně využij existující Agent OS a generické mechanismy task coverage z PR #12, pokud jsou dostupné.

Nevytvářej druhý paralelní systém task coverage nebo review progress jen pro Git.

Aktualizuj všechny spravované instrukce, skills a integrace pro podporované klienty včetně Codex, Antigravity, Gemini, Claude, OpenCode, Cursor, Copilot a dalších skutečně podporovaných klientů.

Instrukce musí být praktické, stručné a využívat kompaktní Hub kontext před opakovaným čtením kompletního diffu.

## 14. MCP, HTTP a CLI

Dokonči sjednocený kanonický kontrakt existujících Git operací.

Prověř zejména:

- `local_ai_repo(action="split_changes")`
- `synthesize_commit`
- Existující HTTP Git endpoints.
- `hubctl changes`.
- Artifact retrieval.
- Task a verification integrace.

Zajisti jednotné:

- Názvosloví.
- Parametry.
- Validaci vstupu.
- Identifikátory.
- Strukturu výstupů.
- Chybové kódy.
- Oprávnění.
- Stránkování.
- Response budgets.
- Omission metadata.
- Stavové informace.
- Recovery mechanismy.

Summary, details, semantic, delta, preflight, artifact, PR, release, commit plan, staging, verification a publication musí tvořit konzistentní workflow.

Zachovej oddělení veřejného read-only rozhraní a lokálně autorizovaných mutací tam, kde je to bezpečnostně potřeba.

Odstraň implicitní nebo nebezpečné chování. Nepoužívej starý kontrakt jako fallback při selhání nového.

CLI musí obsahovat všechny relevantní funkce a poskytovat kvalitní machine-readable JSON i srozumitelné informace o chybách.

Zkontroluj, že používané argumenty nejsou potichu ignorovány.

## 15. Nativní desktopová aplikace v Rustu

Dokonči plnohodnotnou integraci Git Change Intelligence do existující Rust desktopové aplikace.

Desktop musí být použitelný pro běžného uživatele bez nutnosti ručního sestavování JSON objektů, kopírování hashů a opakovaného používání CLI.

Sekce Changes & Commits musí podporovat:

- Přehled repozitářů a worktrees.
- Aktuální Git stav.
- Staged, unstaged a untracked změny.
- Logické skupiny změn.
- Detail souboru, atomu a hunku.
- Čitelný diff.
- Sémantická shrnutí.
- Dependency graph.
- Rizika a nevyřešené závislosti.
- Informace o původu změn.
- Review a verification status.
- Filtrování a vyhledávání.
- Stránkování rozsáhlých výsledků.
- Inkrementální aktualizaci.
- Výběr změn prostřednictvím UI.
- Návrh commit messages.
- Editaci logických commit skupin.
- Přesun a rozdělení změn mezi commity.
- Preview staged tree.
- Partial staging.
- Ověřování commit sequence.
- Přehled aktuálních receipts.
- Opětovné spuštění kontrol.
- Recovery nedokončených transakcí.
- PR a release summaries.
- Bezpečné potvrzení publikace commitů.

Odstraň situace, kdy běžný uživatel musí ručně editovat komplexní JSON v textovém poli, pokud lze použít typované ovládací prvky.

Zajisti jasné rozlišení mezi preview, ověřením a skutečnou mutací.

Při změně vstupních údajů musí být staré schválení, preview digest nebo potvrzovací stav invalidován.

Dlouhé operace nesmí blokovat UI. Implementuj přehled průběhu, cancellation tam, kde je bezpečná, a robustní zpracování chyb.

Optimalizuj komunikaci desktopového bridge a jeho procesní režii. Nepoužívej těžký webový runtime ani zbytečné permanentní procesy.

Aplikace musí fungovat na Windows, Linuxu a macOS.

## 16. Kompletní odstranění webového dashboardu

Zkontroluj celý repozitář a odstraň veškeré pozůstatky původního dashboardu.

Nestačí odstranit HTML soubory.

Zkontroluj:

- Python routy.
- Statické soubory.
- JavaScript a TypeScript.
- Frontend build závislosti.
- Package manifests.
- CLI příkazy.
- URL odkazy.
- Automatické otevírání prohlížeče.
- Porty používané pouze dashboardem.
- Konfigurační položky.
- Instalační skripty.
- Update mechanismus.
- Uninstall mechanismus.
- Packaging.
- CI workflows.
- Dokumentaci.
- Testy.
- Chybové hlášky.
- Agent instructions.
- README a release dokumentaci.

Zachovej HTTP API potřebné pro Hub, desktop a podporované klienty. HTTP API není legacy dashboard a jeho odstranění by poškodilo architekturu.

Při aktualizaci starší instalace bezpečně odstraň již nepotřebné dashboard soubory a závislosti prostřednictvím jednorázové migrace.

## 17. Git-first ukládání a integrace projektových znalostí

Všechna data, která dávají smysl sdílet mezi vývojáři a agenty prostřednictvím Git, ukládej pomocí existující Git-first Project Intelligence architektury.

Typicky:

- Projektové konvence.
- Commit policy.
- Verification policy.
- Test mappings.
- Trvalá architektonická rozhodnutí.
- Sdílené instrukce.
- Pravidla seskupování změn.
- Relevantní akceptační kritéria.
- Důležité projektové znalosti.

Lokálně ponechávej:

- Dočasné cache.
- Runtime leases.
- Transakční journal.
- Machine-specific environment evidence.
- Secrets.
- Osobní nebo citlivá metadata.
- Dočasné snapshoty.
- Odvoditelné indexy.
- Velké nebo rychle se měnící provozní záznamy.

Nevytvářej další projektový adresář nebo formát jen kvůli této funkci, pokud existující Git-first struktura poskytuje vhodné místo.

# Kontroly kvality a dokončení

## 18. Kritický audit existující implementace

Proveď vlastní kritický audit celé funkcionality, včetně již hotových částí.

Hledej zejména:

- Race conditions a TOCTOU chyby.
- Nesprávné cache keys.
- Neúplnou invalidaci.
- Záměny scope a identity.
- Nevalidované vstupy.
- Překročení transportních rozpočtů.
- Neúplné nebo zavádějící výsledky.
- Falešně platné verification receipts.
- Duplicitní logiku.
- Nekonzistentní kontrakty.
- Deadlocks.
- Úniky procesů, souborů nebo databázových spojení.
- Nekontrolovaný růst cache a databází.
- Neefektivní SQL dotazy.
- N+1 dotazy.
- Zbytečné Git subprocessy.
- Zbytečné full-repository scany.
- Zbytečné AI inference.
- Opakovanou analýzu stejných dat.
- Slabou izolaci repozitářů.
- Path traversal.
- Symlink a reparse-point problémy.
- Únik citlivých dat.
- Prompt injection přes názvy souborů, zdrojový kód nebo konfiguraci.
- Neověřené předpoklady o platformě.
- Nekonzistenci mezi desktopem, CLI, HTTP a MCP.
- Chybějící nebo nedokončenou funkcionalitu.
- Všechny zbývající legacy prvky.

Každý skutečný nález oprav. Neponechávej jej pouze v reportu.

Zvláštní pozornost věnuj nedávno přidanému dávkovému čtení patchů, přesnosti partitioningu, canonical diff flags, Windows command-line limitům a konzistenci s partial staging.

## 19. Výkon a spotřeba prostředků

Optimalizuj celou end-to-end cestu, nikoliv pouze izolované funkce.

Měř:

- Cold-cache a warm-cache latency.
- Dobu pozorování Git změn.
- Dobu sémantické analýzy.
- Dobu sestavení dependency graphu.
- Dobu vytvoření commit plánu.
- Dobu inkrementální aktualizace.
- Počet Git subprocessů.
- Počet databázových operací.
- CPU usage.
- Peak RAM.
- Velikost cache.
- Velikost transportovaných odpovědí.
- Počet požadavků.
- Počet lokálních inference.
- Desktop responsiveness.

Používej existující benchmark infrastrukturu Hubu.

Aktuální izolovaný benchmark dávkového čtení 80 patchů vykázal přibližně 145 ms oproti 20 ms. Ověř jeho reprodukovatelnost, ale nevydávej jej za měření rychlosti celého Hubu.

Připrav testovací scénáře pro malé, střední i rozsáhlé repozitáře a dirty worktrees s desítkami, stovkami i tisíci změn.

Veškeré nákladné operace musí mít rozumné limity. Pokud je potřeba pokračovat přes více požadavků, použij spolehlivý inkrementální mechanismus.

## 20. Reálná evaluace token savings a kvality agentů

Dokonči benchmark nástroje:

- `tools/benchmark_git_change_context.py`
- `tools/benchmark_git_change_evaluation.py`

Vytvoř reprodukovatelný evaluation corpus využívající syntetické fixtures, skutečné historické Git změny a nezávisle adjudikované nálezy.

Porovnej minimálně:

### Baseline

Cloudový agent pracující standardním způsobem nad raw diffy a běžnými repository nástroji.

### Git Change Intelligence

Stejný cloudový agent a model využívající kompaktní summary, delta kontext, sémantická metadata, dependency graph, review evidence a cílené detailní inspekce.

Obě varianty musí pracovat na stejných úlohách, revizích a za srovnatelných podmínek.

Měř:

- Skutečné provider-reported input tokens.
- Output tokens.
- Cached a uncached input tokens.
- Počet požadavků.
- Tool schema overhead.
- Retry overhead.
- Detail follow-ups.
- Precision a recall nálezů.
- False positives.
- False negatives.
- Dokončenost úlohy.
- Správnost commit skupin.
- Kvalitu commit messages.
- Správnost výsledných změn.
- Celkový čas.
- Lokální výpočetní režii.

Zahrň i situace, kdy Git Change Intelligence žádné tokeny neušetří nebo je dražší než baseline.

Nevymýšlej výsledky a nezaměňuj odhad tokenů za skutečné provider usage.

Nevyužívej nové placené externí služby ani neposílej citlivý repository obsah neschváleným poskytovatelům.

Pokud skutečné provider měření nelze provést kvůli chybějícímu přístupu, dokonči všechny automatizovatelné části, spusť dostupné lokální a deterministické benchmarky a přesně odděl neověřenou externí akceptační podmínku. Neprezentuj ji jako splněnou.

## 21. Kompletní testování

Doplň rozsáhlé testování produkčního chování.

Povinně pokryj:

- Unit testy.
- Integration testy.
- End-to-end testy.
- Contract testy.
- Regression testy.
- Property-based testy tam, kde mají přidanou hodnotu.
- Concurrency testy.
- Security testy.
- Performance testy.
- Migrační testy.
- Packaging a installation testy.
- Desktop bridge testy.
- Rust testy.
- Reálné Git fixtures.

Git testovací matice musí zahrnovat:

- Čistý a dirty worktree.
- Unborn HEAD.
- Detached HEAD.
- Merge a rebase.
- Konflikty.
- Rename, copy a delete.
- Binární soubory.
- Symlinky.
- Submoduly.
- Speciální názvy souborů.
- Unicode a case-sensitive kolize.
- Změny oprávnění.
- SHA-1 a SHA-256 Git repozitáře.
- Partial staging.
- Mixed staged/unstaged.
- Překrývající se hunks.
- Více commitů nad jedním souborem.
- Velké množství změn.
- Externí editaci během operace.
- Souběžnou práci více agentů.
- Linked worktrees.
- Hooks a signing.
- Cache invalidaci.
- Expiraci receipts.
- Změnu příkazů a prostředí.
- Nedostatečné oprávnění.
- Přerušení stagingu, verification a publication.
- Recovery.
- Model failure.
- Malformed model output.
- Artifact privacy.
- Přesné MCP transportní rozpočty.
- Konzistenci mezi jednotlivými rozhraními.

U nepodporovaných nebo nebezpečných případů testuj explicitní bezpečné odmítnutí a zachování původních dat.

Testy nesmí pouze mockovat interní implementaci. Důležité workflow musí ověřovat skutečné chování nad reálným Git repozitářem a skutečnou evidencí.

Neupravuj testy tak, aby tolerovaly chybnou implementaci.

Nesnižuj coverage thresholds, nevypínej lint, typovou kontrolu ani povinné CI testy jen kvůli dosažení zeleného výsledku.

## 22. Povinné vyřešení CI

Poslední známý stav při předání:

- Větev obsahovala 173 commitů a 175 změněných souborů.
- Poslední známý commit byl `ff373cd`.
- Na starší revizi `e8ecb81` prošel native desktop, lint, typové kontroly, fast-contract, optional model/vision a všech 12 platform-smoke jobs.
- Critical coverage odhalila překročení 128tokenového MCP limitu.
- Fix byl implementován v následujících commitech, ale aktuální CI nebylo potvrzeno.
- Lokální ověření celé větve bylo u předchozího agenta omezené dostupností repozitáře a toolchainu.

Tyto údaje ber pouze jako historický výchozí stav. Zjisti aktuální skutečný stav.

Spusť všechny relevantní lokální kontroly a CI workflows.

Povinně oprav všechny skutečné regrese včetně těch, které vznikly v okolních modulech.

Ověř minimálně:

- Python lint.
- Typové kontroly.
- Fast-contract.
- Critical coverage.
- Platform smoke matrix.
- Integration matrix.
- Optional model/vision.
- Native desktop Windows/Linux/macOS.
- Rust build, formatting, lint a testy.
- Packaging.
- Instalaci a aktualizaci.
- Jednorázovou migraci.

Pracuj iterativně, dokud celý aktuální CI matrix skutečně neprojde.

Nezaměňuj výsledky staršího commitu za výsledky aktuálního HEAD.

## 23. Dokumentace

Přepracuj `docs/GIT_CHANGE_INTELLIGENCE.md` na dokumentaci skutečného výsledného systému.

Odstraň zastaralé historické popisy implementace, které již neodpovídají výsledné architektuře. Vývojová historie patří do Git historie a release notes, ne do kanonického návodu.

Dokumentace musí obsahovat:

- Architekturu.
- Datový model.
- Lifecycle změn.
- Snapshot a identity model.
- Cache a invalidaci.
- Provenance a trust model.
- Dependency graph.
- Verification model.
- Bezpečnostní hranice.
- Commit transaction lifecycle.
- Recovery.
- MCP kontrakty.
- HTTP API.
- CLI.
- Desktop.
- Projektovou konfiguraci.
- Agent integrations.
- Git-first ukládání.
- Migraci.
- Instalaci.
- Troubleshooting.
- Benchmark metodiku a skutečné výsledky.
- Přesně definovaná omezení.

Aktualizuj README a související dokumentaci, příklady a generované instrukce.

Žádná dokumentace nesmí popisovat odstraněné legacy rozhraní jako stále podporované.

## 24. Integrace s aktuálním masterem a ostatními PR

Průběžně sleduj změny v masteru a souvisejících větvích.

Zvláštní pozornost věnuj PR #10 a PR #12, protože se mohou překrývat v oblasti desktopu, Agent OS a evidence pracovního pokrytí.

Před finálním merge:

- Aktualizuj pracovní větev proti aktuálnímu masteru.
- Vyřeš všechny merge konflikty na základě zamýšlené architektury.
- Nevybírej mechanicky jednu stranu konfliktu.
- Zachovej kvalitní funkcionalitu obou stran.
- Odstraň vzniklé duplicity.
- Ověř konzistenci datových modelů.
- Ověř konzistenci rozhraní.
- Ověř migrace a packaging.
- Znovu spusť všechny relevantní testy nad výsledným integračním stavem.

Nevracej zpět změny z jiných PR jen proto, že se překrývají s touto implementací.

Neintegruj nezávislé nedokončené feature branches bez skutečné potřeby. Neobcházej branch protection ani povinné approvals.

## 25. Definition of Done

Úkol nepovažuj za dokončený, dokud:

- Nejsou splněny všechny implementační oblasti původního plánu.
- Nejsou vyřešeny všechny konkrétní nálezy z vlastního auditu.
- Nejsou dokončené všechny relevantní funkce.
- Neexistují neodůvodněné TODO, placeholdery, stuby a falešné implementace.
- Neexistuje trvalé legacy chování.
- Neexistují paralelní kompatibilní architektury.
- Neexistuje webový dashboard ani jeho pozůstatky.
- Funguje jednorázová migrace.
- Desktop, CLI, HTTP a MCP používají stejnou kanonickou logiku.
- Git operace neztrácejí ani nepřepisují nesouvisející změny.
- Nejsou potichu vynechávány změny.
- Summary a delta fungují korektně.
- Dependency graph transparentně rozlišuje jistotu a nejistotu.
- Review evidence není zaměňována za verification.
- Verification nelze neoprávněně obejít.
- Commit sequence ověřuje jednotlivé intermediate trees.
- Funguje recovery.
- Jsou aktualizovány všechny integrace a instrukce.
- Jsou dokončeny benchmark nástroje a dostupné evaluace.
- Je aktuální dokumentace.
- Je hotová požadavková trasovací matice.
- Prošel celý relevantní CI matrix na aktuální revizi.
- Je ověřena kompatibilita výsledné implementace s aktuálním masterem, nikoliv podpora starých runtime kontraktů.

Principiálně neprokazatelné vlastnosti, například autorství neinstrumentované externí editace nebo úplná statická analýza všech dynamických runtime závislostí, nesmí vést k falešným tvrzením. Implementuj maximální bezpečně ověřitelnou podporu a zbytek řeš transparentním stavem unknown nebo explicitním blokováním operace.

## 26. Povinná finální integrace do masteru

Po dokončení implementace:

1. Proveď závěrečný nezávislý audit vlastní práce.
2. Oprav všechny nově nalezené problémy.
3. Zkontroluj úplnou trasovací matici.
4. Ověř finální HEAD a aktuální CI.
5. Vytvoř kvalitní logické commity a pushni je do existující feature větve.
6. Aktualizuj PR #11.
7. Označ PR jako ready for review, pokud jsou splněny podmínky.
8. Integruj aktuální master a vyřeš případné konflikty.
9. Ověř výsledný merge stav.
10. Proveď merge PR #11 do masteru prostřednictvím standardního povoleného GitHub workflow.
11. Ověř, že master skutečně obsahuje výslednou implementaci.
12. Zkontroluj post-merge CI a případné regrese.
13. Oprav případné post-merge problémy bezpečným standardním workflow.

Neprováděj merge neověřeného nebo nedokončeného kódu pouze kvůli splnění instrukce o integraci.

Pokud merge blokuje branch protection, chybějící oprávnění, povinné externí schválení nebo jiná skutečná nepřekročitelná podmínka, dokonči všechno ostatní a přesně zdokumentuj jediný zbývající blokující krok. Nepředstírej úspěšný merge.

## 27. Požadovaný způsob práce

Toto je komplexní implementační úloha, nikoliv žádost o doporučení nebo návrh řešení.

Pracuj autonomně.

Nezastavuj se:

- Po vytvoření plánu.
- Po analýze repozitáře.
- Po prvním commitu.
- Po opravě několika testů.
- Po dokončení jedné implementační oblasti.
- Po částečném CI výsledku.
- Po nalezení dalšího problému.
- Po dosažení přibližně funkčního řešení.

Nevyžaduj průběžné potvrzení běžných technických rozhodnutí, která můžeš bezpečně udělat podle projektové architektury.

Pokud objevíš další nedostatek související s tímto úkolem, zahrň jeho opravu do implementace.

Pokud začneš refaktoring, dokonči ho end-to-end včetně všech volajících, kontraktů, testů, migrací a dokumentace.

Neodkládej práci do budoucích PR.

Nesnižuj cílovou kvalitu kvůli snaze rychle úkol uzavřít.

## 28. Finální report

Až bude práce skutečně dokončena, poskytni konkrétní závěrečný report obsahující:

- Co bylo implementováno.
- Co bylo opraveno.
- Co bylo optimalizováno.
- Jaké legacy části byly odstraněny.
- Jak byly konsolidovány datové modely a služby.
- Jak funguje migrace.
- Jaké architektonické změny byly provedeny.
- Jaké bezpečnostní problémy byly vyřešeny.
- Jaké testy byly přidány a skutečně spuštěny.
- Výsledky aktuálního CI.
- Skutečné benchmark výsledky.
- Stav všech požadavků původního plánu.
- Případná principiální technická omezení.
- Případné externí blokery, které nebylo možné odstranit.
- Finální commit SHA.
- Merge commit SHA nebo jiný jednoznačný důkaz integrace.
- Odkaz na PR #11.
- Potvrzení skutečného stavu masteru.

**Konečný cíl: plnohodnotná, bezpečná, efektivní, jednotná a produkčně použitelná Git Change Intelligence integrovaná do Local AI Hubu a masteru, bez legacy chování, bez zbytečné architektonické duplicity a bez nedokončených částí, které bylo možné implementovat a ověřit.**
