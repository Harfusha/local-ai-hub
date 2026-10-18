"""Static checks for supplemental offline-conversion contracts; no SQL runs."""

import re

from tools.single_owner_additional_store_contracts import (
    ADDITIONAL_JSON_CONTAINERS,
    ADDITIONAL_RETIRED_COLUMNS,
    ADDITIONAL_STORE_DDL,
)


def test_additional_store_registry_has_literal_table_and_index_contracts():
    assert set(ADDITIONAL_STORE_DDL) == {
        "async_jobs", "work_orchestrator", "debug_traces", "telemetry",
    }
    for tables, indexes in ADDITIONAL_STORE_DDL.values():
        assert tables and isinstance(indexes, tuple)
        for table, statement in tables.items():
            assert re.fullmatch(r"[a-z_]+", table)
            assert statement.lstrip().upper().startswith("CREATE TABLE IF NOT EXISTS ")
            assert re.search(rf"CREATE TABLE IF NOT EXISTS\s+{table}\s*\(", statement, re.I)
            assert not re.search(r"\btenant(?:_id|_key|_scope|_identity|_partition)?\b", statement, re.I)
        for statement in indexes:
            assert statement.upper().startswith("CREATE ") and " INDEX " in statement.upper()


def test_retired_columns_registry_only_lists_removed_non_tenant_credentials():
    assert ADDITIONAL_RETIRED_COLUMNS == {}


def test_json_rules_are_exact_and_leave_trace_capture_opaque():
    assert set(ADDITIONAL_JSON_CONTAINERS) == {"async_jobs", "telemetry"}
    assert set(ADDITIONAL_JSON_CONTAINERS["async_jobs"]) == {
        ("async_jobs", "payload_json"), ("async_jobs", "result_json"),
    }
    assert set(ADDITIONAL_JSON_CONTAINERS["telemetry"]) == {
        ("snapshots", "metrics_json"),
    }
    assert all("manual review" in rule or "structured snapshot" in rule
               for store_rules in ADDITIONAL_JSON_CONTAINERS.values()
               for rule in store_rules.values())
    trace_json_columns = {
        ("traces", "request_json"), ("traces", "effective_payload_json"),
        ("traces", "response_json"), ("trace_events", "payload_json"),
    }
    assert trace_json_columns.isdisjoint(ADDITIONAL_JSON_CONTAINERS.get("debug_traces", {}))
