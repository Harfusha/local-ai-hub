from __future__ import annotations

import json

import pytest

from local_ai_hub.laya_dataset_merge import _validate_row, merge_training_archives


def _row(label: str = "allow", state: str = "The user asks to save this setting.") -> dict[str, object]:
    return {
        "state": state,
        "questions": {"intent": {"type": "choice", "options": ["allow", "deny"]}},
        "expected": {"intent": label},
    }


def _archive(path, rows: list[dict[str, object]], password: str = "passphrase") -> None:
    pyzipper = pytest.importorskip("pyzipper")
    with pyzipper.AESZipFile(path, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as archive:
        archive.setpassword(password.encode("utf-8"))
        archive.setencryption(pyzipper.WZ_AES, nbits=256)
        archive.writestr("laya/candidates.train.jsonl", "".join(json.dumps(row) + "\n" for row in rows))


def test_merge_deduplicates_train_rows_and_marks_output_ineligible_for_evaluation(tmp_path, monkeypatch):
    first, second = tmp_path / "notebook.zip", tmp_path / "desktop.zip"
    first.touch()
    second.touch()
    rows_by_path = {
        first: [_row("allow", "state A"), _row("deny", "state B")],
        second: [_row("allow", "state A"), _row("maybe", "state C")],
    }
    monkeypatch.setattr("local_ai_hub.laya_dataset_merge._read_rows", lambda path, password: rows_by_path[path])
    output = tmp_path / "pooled"

    result = merge_training_archives([(first, "one"), (second, "two")], output)

    rows = [json.loads(line) for line in (output / "laya.train.jsonl").read_text(encoding="utf-8").splitlines()]
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert len(rows) == 3
    assert result["source_count"] == 2
    assert manifest["training_only"] is True
    assert manifest["evaluation_eligible"] is False
    assert manifest["duplicate_rows_removed"] == 1
    assert "notebook.zip" not in json.dumps(manifest)
    assert "desktop.zip" not in json.dumps(manifest)


def test_merge_rejects_conflicting_label_for_same_state_and_questions_atomically(tmp_path, monkeypatch):
    first, second = tmp_path / "first.zip", tmp_path / "second.zip"
    first.touch()
    second.touch()
    rows_by_path = {first: [_row("allow")], second: [_row("deny")]}
    monkeypatch.setattr("local_ai_hub.laya_dataset_merge._read_rows", lambda path, password: rows_by_path[path])
    output = tmp_path / "pooled"

    with pytest.raises(ValueError, match="conflicting labels"):
        merge_training_archives([(first, "passphrase"), (second, "passphrase")], output)

    assert not output.exists()


def test_merge_rejects_unencrypted_archive(tmp_path):
    pyzipper = pytest.importorskip("pyzipper")
    source = tmp_path / "plain.zip"
    valid_source = tmp_path / "valid.zip"
    with pyzipper.ZipFile(source, "w") as archive:
        archive.writestr("laya/candidates.train.jsonl", json.dumps(_row()) + "\n")
    _archive(valid_source, [_row(state="valid state")])

    with pytest.raises(ValueError, match="AES-256 encrypted"):
        merge_training_archives(
            [(source, "passphrase"), (valid_source, "passphrase")],
            tmp_path / "pooled",
        )


def test_merge_rejects_unexpected_row_shape(tmp_path):
    source = tmp_path / "bad.zip"
    valid_source = tmp_path / "valid.zip"
    _archive(source, [{"state": "private", "questions": {}, "expected": {}, "session_id": "leak"}])
    _archive(valid_source, [_row(state="valid state")])

    with pytest.raises(ValueError, match="unexpected fields"):
        merge_training_archives(
            [(source, "passphrase"), (valid_source, "passphrase")],
            tmp_path / "pooled",
        )


def test_validate_row_rejects_non_finite_json_numbers():
    with pytest.raises(ValueError, match="Out of range float values"):
        _validate_row({**_row(), "questions": {"intent": {"score": float("nan")}}})

