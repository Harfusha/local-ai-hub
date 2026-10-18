from __future__ import annotations

import hashlib
import re

from tools.single_owner_complete_agent_state_contract import (
    COMPLETE_AGENT_STATE_DDL,
    EXPECTED_OBJECT_SQL_HASHES,
    FTS_REBUILD_FROM_METADATA_ONLY,
    FTS_REBUILD_SOURCE,
    GENERATED_OBJECT_HASHES,
    LEGACY_SOURCE_OBJECT_HASHES,
    LEGACY_SOURCE_REVISION,
    PRESERVE_SQLITE_SEQUENCE_HIGH_WATER,
    RETIRED_ARCHIVE_TABLES,
    SOURCE_OBJECT_HASHES,
)


def _normalized_source_hash(sql: str) -> str:
    without_guard = re.sub(r"\bIF\s+NOT\s+EXISTS\b", "", sql, flags=re.IGNORECASE)
    normalized = " ".join(without_guard.strip().rstrip(";").strip().split()).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def test_complete_ddl_literals_cover_every_non_engine_generated_pin():
    assert set(SOURCE_OBJECT_HASHES) | set(GENERATED_OBJECT_HASHES) == set(EXPECTED_OBJECT_SQL_HASHES)
    assert set(SOURCE_OBJECT_HASHES).isdisjoint(GENERATED_OBJECT_HASHES)

    for name, sql in COMPLETE_AGENT_STATE_DDL["tables"].items():
        key = ("table", name, name)
        assert SOURCE_OBJECT_HASHES[key] == EXPECTED_OBJECT_SQL_HASHES[key]
        assert _normalized_source_hash(sql) == SOURCE_OBJECT_HASHES[key]

    for sql in COMPLETE_AGENT_STATE_DDL["indexes"]:
        match = re.match(r"\s*CREATE\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?([^\s]+)\s+ON\s+([^\s(]+)", sql, re.IGNORECASE)
        assert match is not None
        key = ("index", match.group(1), match.group(2))
        assert _normalized_source_hash(sql) == SOURCE_OBJECT_HASHES[key]


def test_generated_objects_and_conversion_metadata_are_explicit():
    assert set(name for _, name, _ in GENERATED_OBJECT_HASHES) == {
        "sqlite_sequence",
        "agent_memory_fts_config",
        "agent_memory_fts_content",
        "agent_memory_fts_data",
        "agent_memory_fts_docsize",
        "agent_memory_fts_idx",
    }
    assert PRESERVE_SQLITE_SEQUENCE_HIGH_WATER is True
    assert FTS_REBUILD_SOURCE == "agent_memory_records"
    assert FTS_REBUILD_FROM_METADATA_ONLY is True
    assert RETIRED_ARCHIVE_TABLES == ("agent_state_migrations", "agent_state_schema_versions")


def test_legacy_conversion_pins_are_separate_and_source_revision_bound():
    assert LEGACY_SOURCE_REVISION == "d40d268f60ba8b27686b652f76cb8edf80c699c4"
    assert len(LEGACY_SOURCE_OBJECT_HASHES) == 68
    assert len(EXPECTED_OBJECT_SQL_HASHES) == 65
    assert set(LEGACY_SOURCE_OBJECT_HASHES) - set(EXPECTED_OBJECT_SQL_HASHES) == {
        ("index", "idx_agent_memory_provenance_tenant", "agent_memory_records"),
        ("index", "idx_lease_waits_tenant", "lease_waits"),
        ("table", "agent_state_migrations", "agent_state_migrations"),
        ("table", "agent_state_schema_versions", "agent_state_schema_versions"),
    }
    assert LEGACY_SOURCE_OBJECT_HASHES is not EXPECTED_OBJECT_SQL_HASHES
