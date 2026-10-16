from __future__ import annotations

from contextlib import closing
import sqlite3
import pytest

from local_ai_hub.sqlite_counts import (
    get_table_count,
    global_row_counts,
    initialize_row_counts,
    is_row_counts_initialized,
)


def test_initialize_row_counts_validations() -> None:
    with closing(sqlite3.connect(":memory:")) as con:
        # None connection rejected
        with pytest.raises(ValueError, match="con cannot be None"):
            initialize_row_counts(None, ("files",))  # type: ignore[arg-type]

        # None tables rejected
        with pytest.raises(ValueError, match="tables cannot be None"):
            initialize_row_counts(con, None)  # type: ignore[arg-type]

        # Non-string element in tables raises ValueError instead of TypeError
        with pytest.raises(ValueError, match="invalid count table name"):
            initialize_row_counts(con, (123,))  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="invalid count table name"):
            initialize_row_counts(con, (None,))  # type: ignore[arg-type]


def test_global_row_counts_raises_database_error_when_table_missing() -> None:
    with closing(sqlite3.connect(":memory:")) as con:
        # Before initialization, calling global_row_counts raises sqlite3.DatabaseError("derived row counts are not initialized")
        with pytest.raises(sqlite3.DatabaseError, match="derived row counts are not initialized"):
            global_row_counts(con, ("files",))


def test_get_table_count_and_is_initialized() -> None:
    with closing(sqlite3.connect(":memory:")) as con:
        con.execute("CREATE TABLE files(id INTEGER PRIMARY KEY, name TEXT)")
        con.execute("INSERT INTO files VALUES(1, 'foo')")
        con.commit()

        # Before init
        assert is_row_counts_initialized(con, ("files",)) is False
        assert get_table_count(con, "files") is None

        # After init
        initialize_row_counts(con, ("files",))
        assert is_row_counts_initialized(con, ("files",)) is True
        assert is_row_counts_initialized(con, ["files"]) is True
        assert get_table_count(con, "files") == 1
        assert get_table_count(con, "nonexistent") is None

        # global_row_counts accepts list as well as tuple
        res = global_row_counts(con, ["files"])
        assert res == {"files": 1}
