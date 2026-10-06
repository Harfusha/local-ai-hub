from __future__ import annotations

from pathlib import Path
import hashlib
import os
import sys
import tempfile

import pytest


ROOT = Path(r"C:\Users\Adam\.local-ai-hub")
WORKTREE = Path(__file__).resolve().parents[1]
ROOT_SRC = ROOT / "src"
ROOT_PKG = ROOT_SRC / "local_ai_hub"
TENANT_GUARD_OLD = '''                    if not isinstance(provenance, dict):
                        provenance = {}
                    for identity_key, expected in identity_values.items():
'''
TENANT_GUARD_NEW = '''                    if not isinstance(provenance, dict):
                        provenance = {}
                    stored_tenant = str(provenance.get("tenant", "") or "").strip()
                    if (
                        parsed_scope is not AgentScope.GLOBAL
                        and stored_tenant
                        and stored_tenant != identity_values["tenant"]
                    ):
                        con.execute("COMMIT")
                        return False, None
                    for identity_key, expected in identity_values.items():
'''


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> int:
    expected_root_files = {
        "src/local_ai_hub/agent_memory.py": "B3736D39B44722C9030CD9F47F58B58A5F86C1197921375310604EF31F79D8E7",
        "src/local_ai_hub/agent_events.py": "7BBA75A0A335A1BEF0370F636D65F36477BF0638261723A1778E4DC06BB8B949",
        "tests/test_agent_memory.py": "F4F12E52C105D23E88A6F0F69A6D5AC2C23580BF9515E5DD1EA5C1EC6206E29C",
        "tests/test_identity_contracts.py": "C4FD7340F6AC649022908851CAB9DFD81536077EE0E33B6EC179FF4610CE4993",
        "tests/test_evidence_contract.py": "50794A86A3381A8EE0504DE466A7A69FB1C77AB0B305A3280CD1F308263A14B0",
        "tests/test_t05_memory_delete_artifacts.py": "4F79E0C19498706AB351E8EC4F9CA617E95592EA9B351269DC87710B4FF22940",
        "tests/test_agent_state_migrations.py": "E65BD621876ED30F647B1E68C6C6460FF9520457F45A2C48E1FA40C1C67386F2",
        "tests/test_identity_contracts.py": "C4FD7340F6AC649022908851CAB9DFD81536077EE0E33B6EC179FF4610CE4993",
        "tests/test_t05_cache_state_isolation.py": "AEB9C347F94FF420B7995FBC18417375110D9C595F6E775CEE3C6F2309AD5F9C",
    }
    for relative, expected in expected_root_files.items():
        actual = sha256(ROOT / relative)
        print(f"ROOT_SHA256 {relative}={actual}")
        assert actual == expected, f"root preimage changed: {relative}"

    copied_tests = (
        ("tests/test_t05_memory_delete_artifacts.py", "tests/test_t05_memory_delete_artifacts.py"),
        ("tests/test_agent_state_migrations.py", "tests/test_agent_state_migrations_root.py"),
        ("tests/test_agent_memory.py", "tests/test_agent_memory_root_snapshot.py"),
        ("tests/test_identity_contracts.py", "tests/test_identity_contracts_root_snapshot.py"),
        ("tests/test_evidence_contract.py", "tests/test_evidence_contract_root_snapshot.py"),
    )
    for source_relative, candidate_relative in copied_tests:
        assert sha256(ROOT / source_relative) == sha256(WORKTREE / candidate_relative)

    source = (ROOT_PKG / "agent_memory.py").read_text(encoding="utf-8")
    assert source.count(TENANT_GUARD_OLD) == 1
    overlay_src = Path(tempfile.mkdtemp(prefix="t05-combined-root-overlay-")) / "src"
    overlay_pkg = overlay_src / "local_ai_hub"
    overlay_pkg.mkdir(parents=True)
    (overlay_pkg / "agent_memory.py").write_text(
        source.replace(TENANT_GUARD_OLD, TENANT_GUARD_NEW, 1),
        encoding="utf-8",
        newline="\n",
    )
    (overlay_pkg / "__init__.py").write_text(
        '__version__ = "4.0.0"\n'
        "from pathlib import Path\n"
        f'__path__.append(r"{ROOT_PKG}")\n',
        encoding="utf-8",
        newline="\n",
    )
    os.environ["PYTHONPATH"] = str(ROOT_SRC) + os.pathsep + str(WORKTREE / "src")
    os.environ["T05_ROOT_SOURCE_DIR"] = str(ROOT_SRC)
    sys.path.insert(0, str(overlay_src))

    import local_ai_hub.agent_memory as agent_memory
    import local_ai_hub.agent_events as agent_events
    import local_ai_hub.agent_tasks as agent_tasks
    import local_ai_hub.agent_verification as agent_verification
    import local_ai_hub.cache as cache
    import local_ai_hub.http_server as http_server
    import local_ai_hub.memory as memory

    assert Path(agent_memory.__file__).resolve() == (overlay_pkg / "agent_memory.py").resolve()
    print(f"PATCHED_AGENT_MEMORY={Path(agent_memory.__file__).resolve()}")
    for name, module in (
        ("agent_events", agent_events),
        ("agent_tasks", agent_tasks),
        ("agent_verification", agent_verification),
        ("cache", cache),
        ("http_server", http_server),
        ("memory", memory),
    ):
        path = Path(module.__file__).resolve()
        print(f"ROOT_IMPORT {name}={path}")
        assert path.is_relative_to(ROOT_SRC)

    args = [
        "tests/test_t05_memory_delete_artifacts.py::test_scoped_delete_purges_fts_and_embedding_artifacts",
        "tests/test_t05_memory_delete_artifacts.py::test_delete_fts_failure_rolls_back_record_and_embeddings",
        "tests/test_t05_memory_fts_atomicity.py::test_record_update_fts_write_failure_rolls_back_durable_record_and_event",
        "tests/test_t05_memory_fts_atomicity.py::test_record_write_succeeds_when_optional_fts_table_is_absent",
        "tests/test_agent_memory_root_snapshot.py::test_find_filters_global_and_repository_rows_by_tenant_and_root",
        "tests/test_agent_memory_root_snapshot.py::test_find_skips_corrupt_rows_without_aborting_scoped_read",
        "tests/test_agent_memory_root_snapshot.py::test_memory_write_redacts_private_fields_and_blocks_sensitive_records",
        "tests/test_agent_memory_root_snapshot.py::test_memory_correction_lineage_and_delete_survive_reopen",
        "tests/test_agent_memory_root_snapshot.py::test_global_memory_delete_ignores_transport_tenant_but_keeps_scope",
        "tests/test_agent_memory_root_snapshot.py::test_scoped_memory_delete_still_enforces_tenant",
        "tests/test_agent_memory_root_snapshot.py::test_memory_find_enforces_root_repository_and_tenant_identity",
        "tests/test_agent_memory_root_snapshot.py::test_memory_write_failure_rolls_back_record_event_and_cursor",
        "tests/test_agent_memory.py::test_scoped_memory_delete_requires_matching_tenant",
        "tests/test_agent_state_migrations_root.py::test_current_unversioned_agent_state_migrates_with_verified_backup_and_restart",
        "tests/test_agent_state_migrations_root.py::test_unsupported_future_schema_version_fails_closed_without_mutation",
        "tests/test_agent_state_migrations_root.py::test_migration_backup_failure_prevents_schema_version_write",
        "tests/test_agent_state_migrations_root.py::test_corrupt_agent_state_fails_closed_without_replacing_bytes",
        "tests/test_t05_root_migration_faults.py::test_root_migration_ddl_failure_keeps_source_and_retry_preserves_event",
        "tests/test_t05_root_migration_faults.py::test_root_migration_backup_failure_keeps_source_and_retry_preserves_event",
        "tests/test_t05_cache_state_isolation.py::test_derived_sqlite_recovery_preserves_agent_state_and_leases[cache]",
        "tests/test_t05_cache_state_isolation.py::test_derived_sqlite_recovery_preserves_agent_state_and_leases[code-index]",
        "tests/test_t05_cache_state_isolation.py::test_scoped_memory_delete_preserves_all_relations_until_authorized",
        "tests/test_t05_cache_state_isolation.py::test_sqlite_cache_recovers_corruption_after_first_initialization",
        "tests/test_t05_cache_state_isolation.py::test_cache_rebuild_failure_keeps_durable_state_intact_and_retries",
        "tests/test_t05_cache_state_isolation.py::test_process_crash_after_cache_rebuild_preserves_durable_agent_state",
        "tests/test_t05_cache_clear_durable_state.py",
        "tests/test_identity_contracts_root_snapshot.py::test_workspace_memos_report_shared_scope_and_isolate_repositories",
        "tests/test_identity_contracts_root_snapshot.py::test_workspace_memo_rejects_malformed_key_value_or_tenant",
        "tests/test_identity_contracts_root_snapshot.py::test_repository_memory_foreign_id_requires_matching_repository",
        "tests/test_identity_contracts_root_snapshot.py::test_global_memory_store_requires_approval_marker_and_then_is_shared",
        "tests/test_identity_contracts_root_snapshot.py::test_tenant_label_does_not_authenticate_http_request",
        "tests/test_identity_contracts_root_snapshot.py::test_mixed_memory_identity_context_is_rejected",
        "tests/test_identity_contracts_root_snapshot.py::test_worktree_memory_idempotency_isolated_by_scope_id",
        "tests/test_identity_contracts_root_snapshot.py::test_worktree_memory_idempotency_stream_key_is_unambiguous",
        "tests/test_identity_contracts_root_snapshot.py::test_memory_delete_requires_matching_scope_identity",
        "tests/test_evidence_contract_root_snapshot.py::test_current_evidence_identity_requires_current_source_and_stored_row",
        "tests/test_agent_memory_http_identity.py::test_http_global_memory_identity_ignores_transport_tenant_but_keeps_scope",
    ]
    return int(pytest.main(args))


if __name__ == "__main__":
    raise SystemExit(main())
