# Scénář 090: sjednocení checkpoint kontraktu

Oprav v této kopii průchod checkpointu přes SDK, adaptér a HTTP server. Jediným přijatým tvarem je objekt `checkpoint` se šesti explicitními poli: `phase` a `next_action` jsou neprázdné řetězce, `affected_paths`, `evidence_ids` a `blockers` jsou seznamy řetězců, `state_data` je objekt. Prázdné seznamy a objekt jsou platné; chybějící, null a jiné neplatné hodnoty se nesmějí potichu měnit na výchozí hodnoty. Starý plochý tvar odmítni. Aktualizuj oba soubory promptů a ověř průchod lokálním HTTP serverem. Spusť `python oracle_090.py`.
