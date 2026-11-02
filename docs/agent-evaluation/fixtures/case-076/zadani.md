# Scénář 076 — kontrakt `local_ai_coord` / `task_create`

Použij přidělený izolovaný root a samostatné `task_id` pro každý případ. Každé volání proveď právě jednou skutečným MCP klientem připojeným k testovacímu Hubu. Neměň předávané JSON typy ani neupravuj SQLite.

- Vynechaný `scope`: očekává se výchozí `task`. Hodnota `repository` je platná.
- `scope` hodnoty `Repository`, ` repository `, `""`, `false`, `null` a `0`: odmítnout bez normalizace.
- Vynechané `acceptance_criteria` a prázdné pole `[]` jsou povoleny. Hodnoty `false`, `""`, `null` a `0` odmítnout jako nesprávný typ.
- Pomocí read-only `local_ai_repo` / `search` ověř platný `offset: 0` a vynechaný `offset` s dotazem `CASE076_SEARCH_MARKER`. Pomocí read-only `local_ai_coord` / `task_list` ověř platné `include_stale: false` a vynechané pole. Hodnoť přesné argumenty, stav a vrácené hodnoty; prázdný nebo neúplný index nepředstavuje důkaz chybného typu.

Pro každý případ uveď argumenty, request ID, success/error a zda úloha vznikla. Při nejasném výsledku mutaci neopakuj. Úlohy ponech pouze v izolovaném stavu testovacího Hubu.
