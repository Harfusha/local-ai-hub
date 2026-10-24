"""Actual diagram persistence keeps server provenance and never invokes a model."""

from __future__ import annotations

import base64
from contextlib import closing
import json

import pytest

from local_ai_hub.rag import RAGStore


def _store(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    store = RAGStore({
        "server": {"state_dir": str(tmp_path / "state")},
        "security": {"allowed_roots": [str(root)]},
    }, services=None)
    return root, store


@pytest.mark.parametrize("suffix", [".png", ".svg"])
def test_persisted_diagram_text_and_response_have_same_real_source(tmp_path, suffix):
    root, store = _store(tmp_path)
    image = root / f"actual-diagram{suffix}"
    if suffix == ".svg":
        image.write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>actual label</text></svg>', encoding="utf-8")
    else:
        image.write_bytes(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aS1cAAAAASUVORK5CYII="
        ))
    metadata = {"operator_note": "explicit user metadata"}
    result = store.ingest_diagram(
        root=str(root), workspace="diagram-acceptance", image_path=str(image),
        caption="actual fixture caption", metadata=metadata,
    )
    assert result["success"] is True, result
    assert result["diagram_indexed"] is True
    assert result["image_path"] == str(image.resolve())
    assert result["vision_or_ocr_used"] is False
    assert result["diagram_content_mode"] == ("svg_text_nodes" if suffix == ".svg" else "metadata_only")
    assert metadata == {"operator_note": "explicit user metadata"}
    with closing(store._connect()) as connection:
        rows = connection.execute(
            "SELECT text, embedding FROM chunks WHERE workspace=? ORDER BY path, chunk_no",
            ("diagram-acceptance",),
        ).fetchall()
    assert rows, result
    assert all(not row[1] for row in rows)
    text = "\n".join(row[0] for row in rows)
    metadata_lines = [line.removeprefix("Metadata: ") for line in text.splitlines() if line.startswith("Metadata: ")]
    assert len(metadata_lines) == 1, text
    persisted = json.loads(metadata_lines[0])
    assert persisted == {"type": "diagram", "format": suffix,
                         "image_path": result["image_path"], **metadata}
    assert image.name in text and "actual fixture caption" in text
    if suffix == ".svg":
        assert "actual label" in text
    else:
        assert f"File path: {result['image_path']}" in text
    foreign_root = tmp_path / "other-repository"
    foreign_root.mkdir()
    other_image = foreign_root / image.name
    other_image.write_bytes(image.read_bytes())
    refused = store.ingest_diagram(
        root=str(foreign_root), workspace="diagram-acceptance", image_path=str(other_image),
    )
    assert refused["success"] is False
    assert "different repository root" in refused["error"]
    with closing(store._connect()) as connection:
        after = connection.execute(
            "SELECT text, embedding FROM chunks WHERE workspace=? ORDER BY path, chunk_no",
            ("diagram-acceptance",),
        ).fetchall()
    assert [tuple(row) for row in after] == [tuple(row) for row in rows]


@pytest.mark.parametrize("reserved", [
    "type", "format", "image_path", "root", "workspace", "source",
    "diagram_content_mode", "vision_or_ocr_used",
])
def test_reserved_diagram_metadata_never_reaches_persistent_chunks(tmp_path, reserved):
    root, store = _store(tmp_path)
    image = root / "actual.svg"
    image.write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>real</text></svg>', encoding="utf-8")
    result = store.ingest_diagram(
        root=str(root), workspace="diagram-acceptance", image_path=str(image),
        metadata={reserved: "forged-source"},
    )
    assert result["success"] is False
    assert result["diagram_indexed"] is False
    assert "reserved provenance" in result["error"]
    with closing(store._connect()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0
