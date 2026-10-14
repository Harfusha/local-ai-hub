import tracemalloc
import sqlite3

from local_ai_hub.artifacts import ArtifactStore


def test_large_paged_artifact_uses_bounded_sql_slice_and_keeps_full_sections(tmp_path):
    store = ArtifactStore(tmp_path)
    body = "x" * (2 * 1024 * 1024)
    headings = "\n".join(f"## Late {index}" for index in range(60))
    text = f"# Beginning\n{body}\n{headings}\nlast line"
    artifact_id = store.put(text, tenant="slice-sql", kind="log")

    statements = []
    connect = store._connect

    def traced_connect():
        connection = connect()
        connection.set_trace_callback(statements.append)
        return connection

    store._connect = traced_connect
    offset = len(text) // 2
    tracemalloc.start()
    page = store.get(artifact_id, offset=offset, max_chars=256, tenant="slice-sql")
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    selects = [statement.lower() for statement in statements if statement.lstrip().lower().startswith("select")]
    assert peak_bytes < len(text) // 2
    assert any("substr(" in statement and "select kind, text," not in statement for statement in selects)
    assert page["text"] == text[offset : offset + 256]
    assert page["total_chars"] == len(text)
    assert page["next_offset"] == offset + len(page["text"])
    assert page["sections"] == ["beginning", *(f"late-{index}" for index in range(49))]


def test_sql_paged_artifact_preserves_unicode_and_nul_offsets(tmp_path):
    store = ArtifactStore(tmp_path)
    text = ("α🙂\x00\ufffd" * 150) + ("終" * 350)
    artifact_id = store.put(text, tenant="slice-sql", kind="log")

    statements = []
    connect = store._connect

    def traced_connect():
        connection = connect()
        connection.set_trace_callback(statements.append)
        return connection

    store._connect = traced_connect
    page = store.get(artifact_id, offset=255, max_chars=256, tenant="slice-sql")

    selects = [statement.lower() for statement in statements if statement.lstrip().lower().startswith("select")]
    assert any("substr(" in statement and "select kind, text," not in statement for statement in selects)
    assert page["text"] == text[255:511]
    assert page["total_chars"] == len(text)
    assert page["next_offset"] == 511


def test_legacy_rows_are_backfilled_before_bounded_paging(tmp_path):
    store = ArtifactStore(tmp_path)
    text = "legacy\n" + ("a\x00\ufffdb" * 100)
    artifact_id = store.put(text, tenant="slice-sql", kind="log")
    connection = sqlite3.connect(store.path)
    try:
        connection.execute(
            f"UPDATE {store._table} SET char_count=NULL, section_names=NULL, page_text=NULL, nul_mask=NULL WHERE artifact_id=?",
            (artifact_id,),
        )
        connection.commit()
    finally:
        connection.close()

    migrated = ArtifactStore(tmp_path)
    statements = []
    connect = migrated._connect

    def traced_connect():
        connection = connect()
        connection.set_trace_callback(statements.append)
        return connection

    migrated._connect = traced_connect
    page = migrated.get(artifact_id, offset=99, max_chars=256, tenant="slice-sql")

    selects = [statement.lower() for statement in statements if statement.lstrip().lower().startswith("select")]
    assert any("substr(" in statement and "select kind, text," not in statement for statement in selects)
    assert page["text"] == text[99:355]
    assert page["total_chars"] == len(text)
    assert page["next_offset"] == 355
