# Audit Local AI Hub — 24. 11. 2026

Plný audit: [detailní report](2026-11-24-local-ai-hub-detailni-audit.md).

## Snapshot a rozsah

- Auditovaný commit: `f05c1ed403b713e288a5911c5f29d0ffc8dae5b1`, větev `master`, produkt 8.0.0, state schema 11.
- Inventory: 509 Python modulů v `src/local_ai_hub`, 127 Python nástrojů v `tools`, 1 573 Python souborů v `tests` a 296 dokumentačních souborů.
- Dirty workspace obsahoval TaskPage refaktor, plugin změny, telemetrii a nesledované lokální state/config artefakty. Zálohy a telemetry jsem neotevíral ani neměnil.
- Široká inventory plus hluboká kontrola rizikových hranic; ne ruční čtení každého řádku. Bez testů, buildů, modelů a živého Hubu.

## Verdikt

**Vydání nyní neprohlašovat za připravené.** Kritické: release check odmítá state backup payloady; AST-Grep tréninkový parser používá `shell=True` nad cestou z cizího repozitáře; Ruff hlásí 5 chyb; agent surface audit hlásí 8 stale rozhodnutí. Workspace config bez povinného schema markeru se nenačte. Ve změně TaskStore je také neoznámená nekompatibilní změna návratového typu.

## Nálezy k řešení

1. **P1 — Možné spuštění příkazu přes název souboru.** `tools/model_training/mine_code_triplets.py:381,384` posílá cestu z procházeného repozitáře do `subprocess.run(..., shell=True)`. Použít `shell=False` a argv.
2. **P1 — Zálohy v distribučním stromu blokují release.** `tools/release_check.py --allow-installed` odmítá mnoho SQLite/build payloadů pod `state.backup-v6-*`; `.gitignore` nepokrývá tyto backup názvy. Zálohy zachovat, přesunout mimo checkout a upravit přesná pravidla.
3. **P1 — Ruff neprojde.** Pět chyb v test fixture: čtyři nedefinovaná jména a duplicitní dict klíč. CI vyžaduje `ruff check src tools tests`.
4. **P1 — Ruční MCP agent surface audit je zastaralý.** Osm `local_ai_repo` položek je stale. Porovnat se současnou registrací a zdůvodnit retain/remove.
5. **P1 provozní — Workspace config odmítnut loaderem.** `config.toml` a `config.runtime.toml` postrádají `[local_ai_hub].config_schema_version = 1`; migrovat podporovaným updaterem, marker nepřidávat ručně.
6. **P2 — TaskStore API změnilo list návrat na `TaskPage`.** První party callers aktualizovány, ale konzument `for x in store.list_tasks()` nebo `len(...)` se rozbije. Zveřejněný kontrakt/verzování před vydáním rozhodnout.
7. **P2 — `SECURITY.md` říká podporovaná řada 1.x, metadata projektu jsou 8.0.0.** Opravit policy na skutečný release lifecycle.
8. **P2 — RAG reindex/relevance není potvrzen.** Poslední uložený snapshot v `docs/FINAL_COMPLETION_PLAN.md` ukazuje všechny tehdejší vektory prázdné. Opravená detekce obnovuje kandidáty; nedokazuje embedding ani kvalitu.
9. **P2 — Provider setup není host runtime acceptance.** Trust, permission sharing, handshake a běh u skutečných host aplikací nejsou ověřené.
10. **P3 — Fast-contract workflow obsahuje stejný test node dvakrát.** Odebrat duplikát nebo ho nahradit chybějícím scénářem.
11. **P3 — Strict mypy pokrývá jen 14 z 509 Python modulů.** Rozšířit coverage nejprve přes auth, migrations, task contracts a RAG.

## Statické kontroly

**Aktuální auditní běh:** `ruff check src tools tests` FAIL (5); `pyflakes src tools` PASS; `python tools/audit_agent_surface.py` FAIL (8 stale); `python tools/surface_inventory.py --check` PASS (674 řádků); `python tools/release_check.py --allow-installed` FAIL; `git diff --check` PASS.

**Testy:** v této práci jsem žádný test runner nespustil. CI běhy pro přesný commit nebyly ověřené. Hub plánový příkaz vrátil terminální transport failure před odesláním; plán ani receipt nebyl aktualizovaný.

## Pořadí

1. Opravit AST-Grep `shell=True` a vyřešit P1 release/quality gates.
2. Rozhodnout TaskStore compatibility, opravit SECURITY.md a workflow duplikát.
3. Migrovat config podporovaným postupem; zálohy uchovat mimo checkout.
4. Potom, při schváleném provozním ověření, provést RAG reindex, clean install/update/rollback, provider handshake a endpoint SLA měření pro přesný SHA.

