from __future__ import annotations

import hashlib
import sqlite3
import time
from contextlib import closing

import pytest

from local_ai_hub.artifacts import ArtifactStore, ArtifactTextReadError


def _identity(tenant: str) -> str:
    return hashlib.sha256(tenant.encode("utf-8")).hexdigest()


def _insert_text(store: ArtifactStore, artifact_id: str, text: str, *, tenant: str = "owner", age: float = 0) -> None:
    with closing(sqlite3.connect(store.path)) as connection:
        connection.execute(
            f"INSERT INTO {store._table} "
            "(artifact_id, created_at, tenant, tenant_identity, kind, text) VALUES(?,?,?,?,?,?)",
            (artifact_id, time.time() - age, tenant, _identity(tenant), "text", text),
        )
        connection.commit()


@pytest.mark.parametrize("encoding", ["UTF-8", "UTF-16le", "UTF-16be"])
def test_streaming_reads_round_trip_unicode_nul_and_distant_spans(tmp_path, encoding) -> None:
    db_path = tmp_path / "artifacts.sqlite3"
    if encoding != "UTF-8":
        with closing(sqlite3.connect(db_path)) as connection:
            connection.execute(f"PRAGMA encoding='{encoding}'")
    store = ArtifactStore(tmp_path)
    text = "x" * 65_530 + "界😀\x00tail" + "z" * 70_000
    _insert_text(store, "art_stream", text)

    result = store.get_slices(
        "art_stream",
        [
            {"offset": 65_530, "max_chars": 8},
            {"offset": len(text) - 9, "max_chars": 9},
        ],
        tenant="owner",
    )
    assert result["success"] is True
    assert result["slices"] == [
        {"offset": 65_530, "text": text[65_530:65_538]},
        {"offset": len(text) - 9, "text": text[-9:]},
    ]
    assert result["total_chars"] == len(text)

    single = store.get("art_stream", offset=65_531, max_chars=256, tenant="owner")
    assert single["success"] is True
    assert single["text"] == text[65_531:65_531 + 256]
    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute(
            "SELECT 1 FROM artifact_paging_metadata WHERE artifact_id='art_stream'",
        ).fetchone() is None


def test_streaming_read_uses_one_snapshot_and_does_not_backfill(tmp_path, monkeypatch) -> None:
    store = ArtifactStore(tmp_path)
    original = "A" * 100_000 + "old"
    _insert_text(store, "art_snapshot", original)
    stream = store._stream_text
    changed = False

    def update_after_snapshot(connection, rowid, encoding, spans=None, **kwargs):
        nonlocal changed
        if not changed:
            changed = True
            with closing(sqlite3.connect(store.path)) as writer:
                writer.execute(
                    f"UPDATE {store._table} SET text=? WHERE artifact_id=?",
                    ("new", "art_snapshot"),
                )
                writer.commit()
        return stream(connection, rowid, encoding, spans, **kwargs)

    monkeypatch.setattr(store, "_stream_text", update_after_snapshot)
    result = store.get("art_snapshot", offset=100_000, max_chars=256, tenant="owner")
    assert result["success"] is True
    assert result["text"] == "old"
    with closing(sqlite3.connect(store.path)) as connection:
        assert connection.execute(
            "SELECT text FROM artifacts WHERE artifact_id='art_snapshot'",
        ).fetchone() == ("new",)
        assert connection.execute(
            "SELECT 1 FROM artifact_paging_metadata WHERE artifact_id='art_snapshot'",
        ).fetchone() is None


def test_section_scan_caps_names_and_header_retention(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    text = "\n".join([f"## Heading {index}" for index in range(55)])
    text += "\n## " + ("H" * 100_000) + "\nbody"
    _insert_text(store, "art_sections", text)

    result = store.get("art_sections", max_chars=256, tenant="owner")
    assert result["success"] is True
    assert len(result["sections"]) == 50
    assert result["sections_truncated"] is True
    assert result["text"] == text[:256]


def test_markdown_section_reads_stop_at_boundary_and_clamp_past_end(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    text = "## First\nfirst body\n## Second\nsecond body"
    _insert_text(store, "art_section_boundary", text)
    first_end = text.index("## Second")
    first_length = first_end

    result = store.get("art_section_boundary", section="first", tenant="owner")
    assert result["success"] is True
    assert result["text"] == text[:first_end]
    assert "## Second" not in result["text"]
    assert result["total_chars"] == first_length

    past_end = store.get(
        "art_section_boundary", offset=first_length + 9, section="first", tenant="owner",
    )
    assert past_end["success"] is True
    assert past_end["text"] == ""
    assert past_end["next_offset"] is None


def test_section_map_closes_last_retained_section_at_first_omitted_heading() -> None:
    lines = [f"## Heading {index}" for index in range(51)]
    text = "\n".join(lines) + "\nremaining body"
    sections, truncated = ArtifactStore._section_data(text)
    omitted_heading_start = text.index(lines[50])
    assert truncated is True
    assert len(sections) == 50
    assert sections["heading-49"][1] == omitted_heading_start


def test_compact_marks_sections_omitted_from_preview_list(tmp_path) -> None:
    store = ArtifactStore(tmp_path, max_inline_chars=1000)
    text = "\n".join(f"## Heading {index}" for index in range(30)) + "\n" + ("x" * 1200)
    result = store.compact({"text": text}, "owner", "text")
    assert len(result["artifact"]["sections"]) == 24
    assert result["artifact"]["sections_truncated"] is True


def test_json_section_over_admission_limit_returns_bounded_error(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    _insert_text(store, "art_large_json", '{"large":"' + ("x" * 1_100_000) + '"}')

    result = store.get("art_large_json", section="json:large", tenant="owner")
    assert result["success"] is False
    assert result["error_code"] == "artifact_section_too_large"


def test_missing_json_metadata_reports_bounded_names_and_rejects_duplicate_keys(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    _insert_text(store, "art_json_names", '{"first":1,"second":2}')
    _insert_text(store, "art_json_duplicate", '{"same":1,"same":2}')
    _insert_text(store, "art_json_long_key", '{"' + ("k" * 600) + '":1}')

    names = store.get("art_json_names", tenant="owner")
    assert names["success"] is True
    assert names["sections"] == ["json:first", "json:second"]
    assert names["sections_truncated"] is False

    duplicate = store.get("art_json_duplicate", section="json:same", tenant="owner")
    assert duplicate["success"] is False
    assert duplicate["error_code"] == "artifact_json_invalid"

    oversized_key = store.get("art_json_long_key", tenant="owner")
    assert oversized_key["success"] is True
    assert oversized_key["sections"] == []
    assert oversized_key["sections_truncated"] is True
    oversized_request = store.get(
        "art_json_long_key", section="json:" + ("k" * 600), tenant="owner",
    )
    assert oversized_request["success"] is False
    assert oversized_request["error_code"] == "artifact_section_invalid"


def test_expired_wrong_tenant_and_binary_rows_do_not_stream_text(tmp_path, monkeypatch) -> None:
    store = ArtifactStore(tmp_path, ttl_hours=1)
    _insert_text(store, "art_expired", "expired", age=7_200)
    _insert_text(store, "art_private", "private", tenant="other")
    binary_id = store.put_bytes(b"image-data", "owner", "vision-image", "image/png")
    monkeypatch.setattr(
        store,
        "_stream_text",
        lambda *_args, **_kwargs: pytest.fail("unauthorized or binary row reached text reader"),
    )

    assert store.get("art_expired", tenant="owner")["success"] is False
    assert store.get("art_private", tenant="owner")["success"] is False
    assert store.get(binary_id, tenant="owner")["success"] is False


def test_expired_stream_deadline_returns_typed_read_timeout(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    with closing(sqlite3.connect(store.path)) as connection:
        with pytest.raises(ArtifactTextReadError) as exc_info:
            store._stream_text(connection, 1, "UTF-8", deadline=time.monotonic() - 1)
    assert exc_info.value.code == "artifact_text_read_timeout"
