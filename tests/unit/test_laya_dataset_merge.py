from __future__ import annotations

import json
import hashlib

import pytest

from local_ai_hub.laya_dataset_merge import _validate_row, merge_training_archives


def _row(label: str = "allow", state: str = "The user asks to save this setting.") -> dict[str, object]:
    base = {
        "state": state,
        "questions": {"intent": {"type": "choice", "options": ["allow", "deny"]}},
        "expected": {"intent": label},
    }
    digest = hashlib.sha256(json.dumps(base, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    target_sha256 = hashlib.sha256(
        json.dumps(base["expected"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    reviewer_hashes = [hashlib.sha256(f"reviewer-{index}".encode()).hexdigest() for index in range(4)]
    return {
        "id": f"candidate-{digest[:16]}",
        "group_id": f"group-{digest[16:32]}",
        "source_sha256": digest,
        **base,
        "provenance": {
            "source": "laya_candidate_store",
            "data_class": "local_scoped",
            "candidate_id": f"candidate-{digest[:16]}",
            "candidate_sha256": digest,
            "repository_scope_sha256": "a" * 64,
            "task_id": "task-merge",
            "session_id": "session-merge",
            "evidence_ids": ["ev-verified-1"],
            "label_provenance": {
                "status": "verified",
                "method": "blind_double_annotation",
                "rubric_version": "laya-source-label-v1",
                "target_sha256": target_sha256,
                "annotation_identity_sha256": sorted(reviewer_hashes[:2]),
                "agreement": True,
                "adjudicator_identity_sha256": reviewer_hashes[2],
                "verification_identity_sha256": reviewer_hashes[3],
            },
        },
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


def test_merge_reads_and_merges_real_encrypted_zip_members(tmp_path):
    first, second = tmp_path / "notebook.zip", tmp_path / "desktop.zip"
    _archive(first, [_row("allow", "same state"), _row("deny", "notebook state")], password="one")
    _archive(second, [_row("allow", "same state"), _row("maybe", "desktop state")], password="two")
    output = tmp_path / "pooled"

    manifest = merge_training_archives([(first, "one"), (second, "two")], output)

    rows = [json.loads(line) for line in (output / "laya.train.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows == [_row("allow", "same state"), _row("deny", "notebook state"), _row("maybe", "desktop state")]
    assert manifest["input_rows"] == 4
    assert manifest["unique_rows"] == 3
    assert manifest["duplicate_rows_removed"] == 1
    assert manifest["evaluation_eligible"] is False


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


@pytest.mark.parametrize("mutation, message", [
    ("missing", "verified label provenance"),
    ("pending", "status must be verified"),
    ("wrong_target", "target labels"),
    ("duplicate_annotators", "two distinct annotator identity hashes"),
    ("overlapping_adjudicator", "adjudicator must be independent"),
    ("overlapping_verifier", "verification reviewer must be independent"),
])
def test_validate_row_requires_verified_label_provenance(mutation, message):
    row = _row()
    proof = row["provenance"]["label_provenance"]
    if mutation == "missing":
        row["provenance"].pop("label_provenance")
    elif mutation == "pending":
        proof["status"] = "pending"
    elif mutation == "wrong_target":
        proof["target_sha256"] = "0" * 64
    elif mutation == "duplicate_annotators":
        proof["annotation_identity_sha256"][1] = proof["annotation_identity_sha256"][0]
    elif mutation == "overlapping_adjudicator":
        proof["adjudicator_identity_sha256"] = proof["annotation_identity_sha256"][0]
    else:
        proof["verification_identity_sha256"] = proof["adjudicator_identity_sha256"]

    with pytest.raises(ValueError, match=message):
        _validate_row(row)


@pytest.mark.parametrize("field", [
    "repository_scope_sha256", "task_id", "session_id", "evidence_ids",
])
def test_validate_row_requires_scoped_evidence_provenance(field):
    row = _row()
    row["provenance"].pop(field)

    with pytest.raises(ValueError, match=f"provenance.{field}"):
        _validate_row(row)


@pytest.mark.parametrize("changes", [
    {"consent": True},
    {"consent_receipt_id": "receipt-raw"},
    {"per_example_consented": True},
    {"consent_receipt_sha256": "short"},
])
def test_validate_row_rejects_retired_consent_fields(changes):
    row = _row()
    row["provenance"].update(changes)

    with pytest.raises(ValueError, match="consent"):
        _validate_row(row)


def test_merge_rejects_conflicting_labels_for_identical_inputs(tmp_path, monkeypatch):
    first, second = tmp_path / "first.zip", tmp_path / "second.zip"
    first.touch()
    second.touch()
    rows_by_path = {
        first: [_row("allow", "same content")],
        second: [_row("deny", "same content")],
    }
    monkeypatch.setattr("local_ai_hub.laya_dataset_merge._read_rows", lambda path, password: rows_by_path[path])

    with pytest.raises(ValueError, match="conflicting labels"):
        merge_training_archives([(first, "one"), (second, "two")], tmp_path / "merged")

