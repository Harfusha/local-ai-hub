from __future__ import annotations

import json
import math
import sqlite3
import time
from pathlib import Path

import pytest

from local_ai_hub.agent_blackboard import (
    BlackboardSection,
    BlackboardStore,
    merge_sections,
)


def test_section_from_dict_defensive_parsing() -> None:
    # Non-dict returns safe default
    sec_empty = BlackboardSection.from_dict(None, default_section="fallback")  # type: ignore[arg-type]
    assert sec_empty.section == "fallback"
    assert sec_empty.author == "agent"
    assert sec_empty.version == 1
    assert sec_empty.clock == {}

    # Corrupted clock with non-numeric, negative or non-dict
    sec_corrupt_clock = BlackboardSection.from_dict({
        "section": "sec1",
        "clock": {"a": "invalid", "b": 5, "c": None, "d": -2},
        "timestamp": float("nan"),
        "version": -10,
    })
    assert sec_corrupt_clock.section == "sec1"
    assert sec_corrupt_clock.clock == {"b": 5}
    assert math.isfinite(sec_corrupt_clock.timestamp)
    assert sec_corrupt_clock.version == 1

    # Clock not a dict
    sec_list_clock = BlackboardSection.from_dict({
        "section": "sec2",
        "clock": ["invalid", "list"],
    })
    assert sec_list_clock.clock == {}


def test_merge_sections_mismatched_sections_raises() -> None:
    s1 = BlackboardSection(section="sec_a", content=1, author="a")
    s2 = BlackboardSection(section="sec_b", content=2, author="b")
    with pytest.raises(ValueError, match="Cannot merge sections with different names"):
        merge_sections(s1, s2)


def test_blackboard_store_input_validation(tmp_path: Path) -> None:
    store = BlackboardStore(tmp_path / "bb.sqlite3")

    # Empty board_id or null bytes rejected in update
    res = store.update(board_id="", section="sec", content="val", author="a")
    assert res["success"] is False
    assert "board_id and section" in res["error"]

    res = store.update(board_id="board\x00id", section="sec", content="val", author="a")
    assert res["success"] is False

    res = store.update(board_id="b1", section="   ", content="val", author="a")
    assert res["success"] is False

    # Empty board_id or section in get
    res = store.get(board_id="")
    assert res["success"] is False
    assert "board_id" in res["error"]

    res = store.get(board_id="b1", section="  ")
    assert res["success"] is False
    assert "section" in res["error"]

    # Empty board_id or section in delete
    res = store.delete(board_id="")
    assert res["success"] is False
    assert "board_id" in res["error"]

    res = store.delete(board_id="b1", section="  \x00")
    assert res["success"] is False
    assert "section" in res["error"]

    # Empty board_id in merge
    res = store.merge(board_id="", remote_sections={})
    assert res["success"] is False
    assert "board_id" in res["error"]


def test_blackboard_store_corrupted_json_recovery(tmp_path: Path) -> None:
    db_file = tmp_path / "corrupt_bb.sqlite3"
    store = BlackboardStore(db_file)

    # First write a normal section
    store.update(board_id="b1", section="sec1", content={"k": "v"}, author="agent")

    # Intentionally corrupt the vector_clock and content in SQLite
    con = sqlite3.connect(db_file)
    with con:
        con.execute(
            "UPDATE agent_blackboard SET vector_clock = '{corrupt json', content = 'not-json-raw' WHERE board_id='b1' AND section='sec1'"
        )
    con.close()

    # Get should not crash with JSONDecodeError, but should safely recover
    res = store.get(board_id="b1", section="sec1")
    assert res["success"] is True
    assert res["section"]["clock"] == {}
    assert res["section"]["content"] == "not-json-raw"

    # Updating the corrupted row should not crash and should reset clock cleanly
    upd = store.update(board_id="b1", section="sec1", content={"k": "v2"}, author="agent")
    assert upd["success"] is True
    assert upd["version"] == 2
    assert upd["section"]["clock"] == {"agent": 1}


def test_blackboard_store_inspection_helpers(tmp_path: Path) -> None:
    store = BlackboardStore(tmp_path / "inspect.sqlite3")

    assert store.has_board("non_existent") is False
    assert store.has_section("non_existent", "sec") is False
    assert store.get_section_version("non_existent", "sec") is None

    stats_empty = store.get_board_stats("non_existent")
    assert stats_empty["exists"] is False
    assert stats_empty["section_count"] == 0

    # Populate
    store.update(board_id="b1", section="arch", content="plan", author="alice")
    store.update(board_id="b1", section="tasks", content=[1, 2, 3], author="bob")

    assert store.has_board("b1") is True
    assert store.has_section("b1", "arch") is True
    assert store.has_section("b1", "missing") is False
    assert store.get_section_version("b1", "arch") == 1

    stats = store.get_board_stats("b1")
    assert stats["exists"] is True
    assert stats["section_count"] == 2
    assert stats["max_version"] == 1
    assert stats["latest_timestamp"] is not None
