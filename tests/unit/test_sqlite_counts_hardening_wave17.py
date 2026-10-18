import sqlite3

import pytest

from local_ai_hub.sqlite_counts import (
    get_table_count,
    global_row_counts,
    initialize_row_counts,
    is_row_counts_initialized,
)


@pytest.fixture
def test_db():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE foo (id INTEGER PRIMARY KEY, val TEXT)")
    con.execute("INSERT INTO foo (val) VALUES ('a'), ('b')")
    yield con
    con.close()


def test_sqlite_counts_rejects_non_connection_inputs(test_db):
    with pytest.raises(ValueError, match="sqlite3.Connection"):
        initialize_row_counts(12345, ("foo",))
    with pytest.raises(ValueError, match="sqlite3.Connection"):
        global_row_counts(12345, ("foo",))
    assert get_table_count(12345, "foo") is None
    assert is_row_counts_initialized(12345) is False


@pytest.mark.parametrize("tables", [True, 12345])
def test_sqlite_counts_rejects_invalid_table_collections(test_db, tables):
    with pytest.raises(ValueError):
        initialize_row_counts(test_db, tables)
    with pytest.raises(ValueError):
        global_row_counts(test_db, tables)
    assert is_row_counts_initialized(test_db, tables) is False


def test_sqlite_counts_rejects_null_byte_table_name(test_db):
    initialize_row_counts(test_db, ("foo",))
    assert get_table_count(test_db, "foo\x00") is None
    with pytest.raises(ValueError, match="invalid count table name"):
        initialize_row_counts(test_db, ("foo\x00",))
