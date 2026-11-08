# Local AI Hub — Čtvrté kolo hloubkového auditu
**Commit:** `2176b0e210cbd64fb2260f721f8546d5365b463f` · **Datum:** 8. listopadu 2026  
**Hub plán:** `plan_audit_round4_fixes_20261108`  
**Paměťový záznam:** `mem_8e49f664aee5`

Toto kolo auditu se zaměřilo na dříve nepokryté subsystémy: důvěryhodnost zdrojových důkazů, bezpečná manipulace s Git worktrees, transakční snapshoty a klasifikace změn zdrojového kódu.

---

## 1. Důvěryhodnost evidence

### A01 — EvidenceStore neověřuje, že uložený text skutečně pochází z deklarovaných řádků
- **Priorita:** P1 · Potvrzený mechanismus
- **Soubor:** `src/local_ai_hub/evidence.py` (`put`, `get`, `validate_current`)
- **Popis:** `EvidenceStore.put()` vytváří content-addressed ID z `{root, path, file_hash, start, end, text}`. To garantuje integritu uloženého záznamu, nikoliv však to, že text skutečně odpovídá danému rozsahu v souboru. Při `validate_current()` se kontroluje pouze `file_sha256` na disku. Záznam se správným hashem souboru, ale chybným textem, projde jako validní.
- **Oprava:** Rozdělit vlastnosti na `record_integrity` a `source_verified`. Při `put()` ověřit shodu deklarovaného textu se skutečným obsahem na daných řádcích. `validate_current()` smí označit důkaz jako platný jen při `source_verified=True`.
- **Akceptační kritérium:** Záznam se správným hashem, ale nesprávným textem nebo souřadnicemi, nikdy nezíská `source_verified=True`.

### A17 — EvidenceStore nemá vlastní kontrolu, že path zůstává uvnitř deklarovaného rootu
- **Priorita:** P1
- **Soubor:** `src/local_ai_hub/evidence.py` (`get`, `validate_current`)
- **Popis:** Sestavení `Path(root) / path` bez kontroly `path.relative_to(root)` nezabraňuje úniku mimo root při absolutní cestě nebo traversal sekvencích (`..`).
- **Oprava:** Kanonizovat root i cílovou cestu, odmítnout absolutní cesty a úniky mimo root v `put`, `put_many`, `get` i `validate_current`.

### A02 — Ověřování evidence načítá celý soubor do paměti najednou
- **Priorita:** P2
- **Soubor:** `src/local_ai_hub/evidence.py` (`validate_current`)
- **Popis:** `hashlib.sha256(path.read_bytes()).hexdigest()` alokuje celý soubor v RAM (např. 300 MB buffer).
- **Oprava:** Blokové inkrementální čtení po 1 MiB, zavedení limitu maximální velikosti ověřovaného souboru dle evidence policy a ověření identity souboru před a po čtení.

---

## 2. Git worktrees

### A03 — get_worktree_status() může chybně hlásit, že worktree není zamčený
- **Priorita:** P1 · Reprodukováno na Git
- **Soubor:** `src/local_ai_hub/worktrees.py` (`get_worktree_status`)
- **Popis:** Kontrola zámku předpokládá, že `target.parent` je Git repozitář (`parent_repo = target.parent; is_worktree_locked(parent_repo, target)`). U layoutu `C:/projects/worktrees/task-123/` však adresář `worktrees/` není Git repo, `git worktree list` selže a vrátí tiché `locked=False`.
- **Oprava:** Spouštět `git worktree list` přímo nad cílovým worktree. Při nedostupnosti Git metadat vracet stav `unknown` místo `unlocked`.

### A04 — Fallback při odemykání worktree odvozuje Git metadata pouze z názvu adresáře
- **Priorita:** P1
- **Soubor:** `src/local_ai_hub/worktrees.py` (`unlock_worktree`)
- **Popis:** Cesta k zámku je odvozována jako `worktrees_root / target.name / "locked"`. Interní administrativní jméno worktree v Gitu se však při kolizích názvů liší od basename checkoutu. Odstranění souboru může minout správný worktree nebo zasáhnout jiný.
- **Oprava:** Nepoužívat basename jako důkaz Git identity. Ověřit skutečná administrativní metadata a vazbu na fyzickou cestu. Při nejednoznačnosti ruční unlock odmítnout.

---

## 3. TransactionStashHook

### A05 — Obnova může aplikovat cizí stash místo vlastního
- **Priorita:** P1 · Reprodukováno na Git
- **Soubor:** `src/local_ai_hub/command_transactions.py` (`TransactionStashHook`)
- **Popis:** `save()` ukládá `self._stash_sha`, ale `restore()` volá `git stash pop` a `drop()` volá `git stash drop`. Pokud mezitím vznikne jiný stash, dojde k obnovení nebo smazání cizího stashe ze špičky zásobníku.
- **Oprava:** Vázat `restore()` a `drop()` na konkrétní `_stash_sha`. Před mutací ověřit, na který commit položka ukazuje. Selhat bez mutace, pokud vlastní stash nelze jednoznačně určit.

---

## 4. Řízení experimentálních vylepšení (LearningStore)

### A06 — Obecná změna stavu umožňuje obejít schvalovací metodu
- **Priorita:** P1
- **Soubor:** `src/local_ai_hub/agent_learning.py` (`advance`, `promote`)
- **Popis:** `promote()` vyžaduje `approver == "user"`, ale `advance()` akceptuje libovolný stav z `CandidateStatus` a nekontroluje povolené stavové přechody. Lze tak přímo nastavit `CandidateStatus.PROMOTED`.
- **Oprava:** Centralizovaná validace stavových přechodů. Přechod do `PROMOTED` povolen výhradně přes schválenou promotion transakci.

### A07 — Event log a databázová projekce kandidáta se zapisují odděleně
- **Priorita:** P1
- **Soubor:** `src/local_ai_hub/agent_learning.py`
- **Popis:** `state_store.append(event)` a `_save(candidate)` probíhají mimo společnou transakci. `append()` navíc může vrátit chybu v `AppendResult` bez vyvolání výjimky, což `LearningStore` nekontroluje.
- **Oprava:** Zápis eventu i projekce v jediné SQLite transakci pomocí `append_in_transaction()`. Zajištění idempotence přechodů.

### A08 — SLO min_success_rate není vyhodnocováno jako míra úspěšnosti
- **Priorita:** P2
- **Soubor:** `src/local_ai_hub/agent_learning.py` (`observe`)
- **Popis:** Podmínka `if min_success is not None and not observation.success:` vyvolá rollback při jediném neúspěšném požadavku, přestože deklarované SLO mělo být např. 90 % z celku.
- **Oprava:** Zavedení posuvného okna nebo počítadla vzorků (`success_count`, `failure_count`, `min_sample_count`) a vyhodnocování skutečné míry selhání.

---

## 5. Consistency Guard

### A09 — Backend a frontend se párují podle pořadí vyhledávání, nikoli podle skutečného rozhraní
- **Priorita:** P1
- **Soubor:** `src/local_ai_hub/agent_consistency.py` (`build_contract_mappings`)
- **Popis:** Bere se `back[0]` a `front[0]`. Dva nesouvisející soubory jsou porovnány na shodu schématu. Navíc `_is_frontend()` chybně klasifikuje všechny `.ts` soubory jako frontend (včetně backendů v Node/NestJS).
- **Oprava:** Vyžadovat konkrétní rozhraní (HTTP endpoint, OpenAPI operation ID, DTO typ, explicitní import). Při absenci vazby vracet `contract_mapping_status = insufficient_evidence`.

### A10 — Guard může provést stejné vyhledání reuse kandidátů dvakrát
- **Priorita:** P2
- **Soubor:** `src/local_ai_hub/services.py`, `src/local_ai_hub/agent_consistency.py` (`check_drift`)
- **Popis:** `services.py` zavolá `find_reuse_candidates()`, a následně `check_drift()` tutéž metodu volá znovu se stejnými parametry.
- **Oprava:** Předávat již spočítané kandidáty jako neměnný vstup do `check_drift()`.

### A11 — Neúspěšná diff analýza není explicitně odlišena od stavu bez driftu
- **Priorita:** P2
- **Soubor:** `src/local_ai_hub/agent_consistency.py` (`check_drift`)
- **Popis:** Při nedostupném nebo nevalidním diffu vrací `check_drift()` prázdnou množinu varování, což je nerozeznatelné od bezchybného stavu.
- **Oprava:** Vracet explicitní pole `analysis_status` (`complete`, `partial`, `unavailable`).

---

## 6. Work fencing a transakční snapshoty

### A12 — commit_guard() serializuje také operace nad různými repozitáři
- **Priorita:** P1 (výkon při souběhu)
- **Soubor:** `src/local_ai_hub/work_fencing.py` (`commit_guard`), `src/local_ai_hub/work_orchestrator.py`
- **Popis:** `BEGIN IMMEDIATE` drží SQLite write transaction po celou dobu chráněné operace (včetně git apply). Globální `work_fencing.sqlite3` tím blokuje lease renewals i u zcela nezávislých projektů.
- **Doporučení:** Oddělení fencing databází podle kanonické projektové identity. Před změnou provést benchmark souběhu.

### A13 — Soukromý transaction snapshot opakovaně čte a hashuje celý projekt
- **Priorita:** P2
- **Soubor:** `src/local_ai_hub/command_transactions.py` (`create_private_transaction_snapshot_with_manifest`)
- **Popis:** Vytvoření snapshotu provádí až 4 úplné průchody souborovým stromem (`_tree_manifest` src → `_copy_tree` → `_tree_manifest` dst → `_tree_manifest` src verify). U velkých projektů generuje masivní I/O režii.
- **Doporučení:** Benchmark na NTFS, zvážení reflinků, inkrementálního manifestu a omezení write scope při zachování bezpečnostních vlastností.

---

## 7. Model quality a podpůrné subsystémy

### A14 — Kandidát může projít quality gate se samostatně deklarovanými metrikami a slabým receiptem
- **Priorita:** P2
- **Soubor:** `src/local_ai_hub/model_quality.py` (`promote_candidate`)
- **Popis:** Stačí pouhá přítomnost pole např. `evaluation_hash` bez ověření modelu, verze testovací sady nebo integrity datasetu.
- **Oprava:** Vázat promotion na silný auditovatelný receipt s digestem modelu, verzí suite, hash datasetu a časovým razítkem.

### A15 — Speculative lint může tiše vynechat část změněných souborů
- **Priorita:** P2
- **Soubor:** `src/local_ai_hub/speculative_lint.py` (`submit`)
- **Popis:** Ořezání na `self.max_paths` (výchozí 64) probíhá tiše bez indikátoru v návratovém kontraktu.
- **Oprava:** Vracet metadata `requested_paths_count`, `accepted_paths_count`, `truncated: bool`, `omitted_paths_count`.

### A16 — Advisory completion audit používá truthiness pro passed
- **Priorita:** P2
- **Soubor:** `src/local_ai_hub/agent_consistency.py` (`completion_audit`)
- **Popis:** `passed = any(bool(field(item, "passed", False)) for item in current)` vyhodnotí string `"false"` jako `True`.
- **Oprava:** Striktní kontrola `passed is True`, nevalidní typy označit jako `invalid_receipt`.

---

## 8. Nápravný plán (14 úkolů)

| Úkol | ID v plánu | Modul | Cíl | Priorita |
|---|---|---|---|---|
| 1 | `task_t01_evidence_integrity` | `evidence.py` | A01+A17: `source_verified` a path confinement | Critical |
| 2 | `task_t02_evidence_hash_streaming` | `evidence.py` | A02: Inkrementální hashování (1 MiB bloky) | High |
| 3 | `task_t03_worktree_locking` | `worktrees.py` | A03+A04: Spouštět z target worktree, ne parent | Critical |
| 4 | `task_t04_stash_ownership` | `command_transactions.py` | A05: `_stash_sha` vázat na restore/drop | Critical |
| 5 | `task_t05_learning_state_machine` | `agent_learning.py` | A06: Striktní validační funkce přechodů | Critical |
| 6 | `task_t06_learning_atomicity` | `agent_learning.py` | A07: Jedna SQLite transakce pro event+projekci | High |
| 7 | `task_t07_slo_success_rate` | `agent_learning.py` | A08: Okno vzorků místo okamžitého rollbacku | High |
| 8 | `task_t08_contract_mapping` | `agent_consistency.py` | A09: Doložená API vazba, oprava `.ts` backendu | High |
| 9 | `task_t09_guard_reuse` | `agent_consistency.py` | A10+A11: Recyklace reuse candidates, `analysis_status` | Medium |
| 10 | `task_t10_fencing_contention` | `work_fencing.py` | A12: Izolace fencing DB per projekt (benchmark) | High |
| 11 | `task_t11_snapshot_optimization` | `command_transactions.py` | A13: Optimalizace snapshot I/O (benchmark) | Medium |
| 12 | `task_t12_quality_receipts` | `model_quality.py` | A14: Silný receipt navázaný na digest a suite | High |
| 13 | `task_t13_lint_completeness` | `speculative_lint.py` | A15: Explicitní `truncated` indikátor | Medium |
| 14 | `task_t14_audit_contracts` | `agent_consistency.py` | A16: Striktní `passed is True` | High |

---

## 9. Pozitivní architektonické vlastnosti k zachování

1. **`work_fencing.py`**: Fencing tokeny a dvojí validace attemptu před a po operaci chrání před souběžnými zápisy.
2. **`command_transactions.py`**: Privátní snapshot s pre/post porovnáním bezpečně izoluje dirty overlay.
3. **`evidence.py`**: Content-addressed identifikátory zajišťují neměnnost identity záznamů.
4. **`ast_diff.py`**: Striktní oddělení strukturálních změn od tvrzení o ekvivalenci (`behavior_equivalence_proven=False`).
5. **`treesitter_parser.py`**: Serializace nativního parseru a izolace problematických Windows workerů.
6. **`agent_consistency.py`**: Lokální model nemá autoritu nad deterministickými důkazy; striktní evidence IDs.
7. **`agent_verification.py`**: Completion gate kontroluje ownera, revizi, generační čítač mutací a artefakty.
