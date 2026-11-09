# Local AI Hub — Čtvrté kolo hloubkového auditu & Nápravný plán

**Datum:** 8. listopadu 2026  
**Cílová revize:** `master` · Commit `2176b0e210cbd64fb2260f721f8546d5365b463f`  
**Hub Plan ID:** `plan_audit_round4_fixes_20261108`  
**Paměťový záznam:** `mem_8e49f664aee5`

---

## 1. Manažerské shrnutí

Čtvrté kolo auditu se zaměřilo na dříve nepokryté subsystémy: důvěryhodnost zdrojových důkazů (`evidence.py`), bezpečná manipulace s Git worktrees (`worktrees.py`), transakční snapshoty a stashe (`command_transactions.py`), stavový stroj experimentálních vylepšení (`agent_learning.py`), detekce driftu kontraktů (`agent_consistency.py`), work fencing contention (`work_fencing.py`), modely a linting.

Z celkem 17 nových zjištění (A01–A17) jsou 2 přímo reprodukovány na Gitu a 5 představuje kritické implementační anomálie:

1. **A01 (Kritická — Evidence Integrity):** `EvidenceStore.put()` vytváří ID, ale neověřuje shodu textu s deklarovaným rozsahem řádků. Správný `file_sha256` s podvrženým textem projde `validate_current()` jako platný.
2. **A05 (Kritická — Stash Ownership):** `TransactionStashHook.restore()` a `drop()` volají `git stash pop/drop` bez vazby na `_stash_sha`. Při souběhu dojde k obnově nebo smazání cizího stashe. Reprodukováno na Gitu.
3. **A03+A04 (Kritická — Worktree Management):** `get_worktree_status()` kontroluje zámek přes `target.parent` (pokud není Git repo, hlásí `locked=False`). Fallback odemykání odvozuje cestu z `target.name`, což při kolizi jmen zasáhne cizí worktree.
4. **A06 (Kritická — Learning Promotion Gate):** `advance()` akceptuje přímý přechod do `PROMOTED` a obchází uživatelské schválení vyžadované v `promote()`.
5. **A07 (Vysoká — Learning Atomicity):** Zápis události a databázové projekce probíhá odděleně bez SQLite transakce; chyba v `append()` není kontrolována.

---

## 2. Přehled nálezů (A01–A17)

| ID | Komponenta | Popis zjištění | Priorita | Stav v kódu |
|:---|:---|:---|:---:|:---:|
| **A01** | EvidenceStore | `put()` neověřuje text vůči souboru; správný hash + chybný text projde validací | 🔴 P1 (Kritická) | `evidence.py:109-140, 202-262` |
| **A02** | EvidenceStore | `validate_current()` načítá celý soubor přes `read_bytes()` do paměti (OOM) | 🟡 P2 | `evidence.py:202-262` |
| **A03** | Git Worktrees | `get_worktree_status()` zjišťuje zámek z parentu; selhává když parent není git repo | 🔴 P1 (Kritická) | Reprodukováno (`worktrees.py:447-535`) |
| **A04** | Git Worktrees | Fallback `unlock_worktree` odvozuje cestu z basename; riziko zásahu jiného worktree | 🔴 P1 (Kritická) | `worktrees.py:238-289` |
| **A05** | TransactionStashHook | `restore()` a `drop()` neověřují `_stash_sha`, berou vrcholek stacku | 🔴 P1 (Kritická) | Reprodukováno (`command_transactions.py:485-608`) |
| **A06** | LearningStore | `advance()` umožňuje přímý skok do `PROMOTED` bez schválení uživatelem | 🔴 P1 (Kritická) | `agent_learning.py:387-456` |
| **A07** | LearningStore | Event log a projekce se zapisují odděleně mimo společnou transakci | 🟠 P1 (Vysoká) | `agent_learning.py:374-456` |
| **A08** | LearningStore | SLO `min_success_rate` vyvolá rollback při jediném neúspěšném požadavku | 🟡 P2 | `agent_learning.py:457-520` |
| **A09** | ConsistencyGuard | `build_contract_mappings()` páruje `back[0]` a `front[0]` bez ověření API vazby | 🟠 P1 (Vysoká) | `agent_consistency.py:1383-1433` |
| **A10** | ConsistencyGuard | `check_drift()` spouští vyhledání reuse kandidátů znovu po `services.py` | 🟡 P2 | `services.py:6250-6310`, `agent_consistency.py:1520` |
| **A11** | ConsistencyGuard | Neúspěšná diff analýza vrací prázdnou množinu nerozeznatelnou od čistého stavu | 🟡 P2 | `agent_consistency.py:1510-1550` |
| **A12** | Work Fencing | `commit_guard()` drží SQLite transakci přes celý git apply; blokuje jiné repozitáře | 🟠 P1 (Výkon) | `work_fencing.py:727-755` |
| **A13** | CommandTransactions | Privátní snapshot provádí 4+ průchody celým stromem souborů (I/O režie) | 🟡 P2 | `command_transactions.py:408-470` |
| **A14** | Model Quality | `promote_candidate()` akceptuje receipt pouze s neprázdným `evaluation_hash` | 🟡 P2 | `model_quality.py:239-310` |
| **A15** | Speculative Lint | `submit()` tiše ořezává vstupní soubory na limit (výchozí 64) bez indikátoru | 🟡 P2 | `speculative_lint.py:82-125` |
| **A16** | Agent Consistency | `completion_audit()` používá truthiness (`bool('false') == True`) | 🟠 P1 (Vysoká) | `agent_consistency.py:1730-1785` |
| **A17** | EvidenceStore | Chybí path confinement check (`path.relative_to(root)`) v `get`/`validate_current` | 🔴 P1 (Kritická) | `evidence.py:202-239` |

---

## 3. Nápravný plán (14 úkolů v Hub Planu `plan_audit_round4_fixes_20261108`)

Všechny úkoly jsou přímo uloženy v projektovém plánu:

1. **`task_t01_evidence_integrity`** (Critical): `evidence.py` — Implementace `source_verified` v `put()` a `validate_current()`. Path confinement kontrola (`path.relative_to(root)`).
2. **`task_t02_evidence_hash_streaming`** (High): `evidence.py` — Inkrementální hashování souborů po 1 MiB blocích, policy limit velikosti souboru.
3. **`task_t03_worktree_locking`** (Critical): `worktrees.py` — Spouštění `git worktree list` přímo z worktree, bezpečný fallback unlocku s ověřením skutečných Git metadat.
4. **`task_t04_stash_ownership`** (Critical): `command_transactions.py` — `restore()` a `drop()` navázané na `_stash_sha`, odmítnutí neznámých stashes.
5. **`task_t05_learning_state_machine`** (Critical): `agent_learning.py` — Validační matice povolených stavových přechodů, zákaz přímého skoku do `PROMOTED`.
6. **`task_t06_learning_atomicity`** (High): `agent_learning.py` — Atomický zápis eventu a projekce pomocí `append_in_transaction()`.
7. **`task_t07_slo_success_rate`** (High): `agent_learning.py` — Agregace SLO přes počítadla a okno vzorků.
8. **`task_t08_contract_mapping`** (High): `agent_consistency.py` — Prokázaná vazba pro backend/frontend párování, náprava `.ts` backend klasifikace.
9. **`task_t09_guard_reuse`** (Medium): `agent_consistency.py` & `services.py` — Předávání hotových reuse kandidátů, pole `analysis_status` v `check_drift()`.
10. **`task_t10_fencing_contention`** (High): `work_fencing.py` — Benchmark a izolace per-projektové SQLite databáze fencing zámků.
11. **`task_t11_snapshot_optimization`** (Medium): `command_transactions.py` — Profilace a optimalizace I/O průchodů transakčního snapshotu.
12. **`task_t12_quality_receipts`** (High): `model_quality.py` — Striktní vazba evaluation receiptu na model digest, suite a dataset.
13. **`task_t13_lint_completeness`** (Medium): `speculative_lint.py` — Návratová pole `truncated`, `requested_paths_count`, `omitted_paths_count`.
14. **`task_t14_audit_contracts`** (High): `agent_consistency.py` — Striktní typová kontrola `passed is True`.

---

## 4. Pozitivní architektonické vlastnosti k zachování

Při realizaci úprav je nutné striktně zachovat následující fungující mechanismy:
- **`work_fencing.py`**: Fencing tokeny a dvojí validace attemptu před a po operaci.
- **`command_transactions.py`**: Privátní snapshot s pre/post porovnáním a izolací dirty overlay.
- **`evidence.py`**: Content-addressed identifikátory zajišťující neměnnost identit záznamů.
- **`ast_diff.py`**: Explicitní `behavior_equivalence_proven=False` oddělující syntaktické a sémantické změny.
- **`treesitter_parser.py`**: Serializovaný přístup k native parseru a izolace problematických Windows workerů.
- **`agent_consistency.py`**: Zákaz nadřazené autority lokálního modelu nad deterministickými důkazy.
- **`agent_verification.py`**: Propojení completion gate s ownerem, revizí repozitáře a mutation generací.
