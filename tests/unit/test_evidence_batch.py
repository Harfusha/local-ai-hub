from __future__ import annotations

import hashlib
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.evidence import EvidenceStore
from local_ai_hub.source_slice import MAX_SOURCE_BYTES
from local_ai_hub.repo_tools import RepositoryTools


def test_get_many_shares_source_verification_and_preserves_order(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "module.py"
    source.write_text("one = 1\ntwo = 2\nthree = 3\nfour = 4\n", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    store = EvidenceStore(tmp_path / "state")
    items = store.put_many(str(root), [
        {"path": "module.py", "file_sha256": digest, "start_line": 1, "end_line": 2, "text": "one = 1\ntwo = 2"},
        {"path": "module.py", "file_sha256": digest, "start_line": 3, "end_line": 4, "text": "three = 3\nfour = 4"},
    ])
    ids = [str(item["evidence_id"]) for item in items]
    source_checks = []
    original_verify = store._verify_source_rows

    def counted_verify(root, path, rows):
        source_checks.append((root, path))
        return original_verify(root, path, rows)

    monkeypatch.setattr(store, "_verify_source_rows", counted_verify)
    results = store.get_many([ids[1], ids[0], ids[1], "missing"], verify=True, root=str(root))

    assert [row.get("evidence_id") for row in results[:3]] == [ids[1], ids[0], ids[1]]
    assert all(row["success"] is True and row["stale"] is False for row in results[:3])
    assert all(row["source_verified"] is True for row in results[:3])
    assert results[3] == {"success": False, "error": "evidence not found"}
    assert len(source_checks) == 1

    source.write_text("changed = True\n", encoding="utf-8")
    stale = store.get_many(ids, verify=True)
    assert all(row["success"] is True and row["stale"] is True for row in stale)


def test_put_many_rejects_paths_outside_root(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("secret = 1\n", encoding="utf-8")
    digest = hashlib.sha256(outside.read_bytes()).hexdigest()
    store = EvidenceStore(tmp_path / "state")

    stored = store.put_many(str(root), [{
        "path": "../outside.py",
        "file_sha256": digest,
        "start_line": 1,
        "end_line": 1,
        "text": "secret = 1",
    }])

    assert stored == [{"path": "../outside.py", "file_sha256": digest,
                       "start_line": 1, "end_line": 1, "text": "secret = 1"}]
    assert store.count() == 0


def test_stored_text_is_not_marked_verified_until_source_matches(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "module.py"
    source.write_text("actual = 1\n", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    store = EvidenceStore(tmp_path / "state")

    stored = store.put_many(str(root), [{
        "path": "module.py",
        "file_sha256": digest,
        "start_line": 1,
        "end_line": 1,
        "text": "claimed = 1",
    }])
    evidence_id = stored[0]["evidence_id"]

    assert stored[0]["source_verified"] is False
    current = store.get(evidence_id, verify=True)
    assert current["success"] is True and current["stale"] is True
    assert current["source_verified"] is False
    assert store.validate_current(evidence_id) is False
    assert store.validate_current_many([evidence_id]) is False


def test_get_and_validation_reject_corrupted_path_outside_root(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "module.py"
    outside = tmp_path / "outside.py"
    text = "secret = 1\n"
    source.write_text(text, encoding="utf-8")
    outside.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    store = EvidenceStore(tmp_path / "state")
    stored = store.put_many(str(root), [{
        "path": "module.py",
        "file_sha256": digest,
        "start_line": 1,
        "end_line": 1,
        "text": "secret = 1",
    }])
    evidence_id = stored[0]["evidence_id"]
    with store._lock, closing(store._connect()) as con:
        con.execute("UPDATE evidence SET path=? WHERE id=?", ("../outside.py", evidence_id))
        con.commit()

    single = store.get(evidence_id, verify=True)
    batch = store.get_many([evidence_id], verify=True)[0]
    assert single["success"] is True and single["stale"] is True
    assert batch["success"] is True and batch["stale"] is True
    assert single["source_verified"] is False
    assert batch["source_verified"] is False
    assert store.validate_current(evidence_id) is False
    assert store.validate_current_many([evidence_id]) is False


def test_source_verification_enforces_shared_size_bound(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "module.py"
    contents = b"secret = 1\n" + b"#" * (MAX_SOURCE_BYTES - len(b"secret = 1\n"))
    source.write_bytes(contents)
    store = EvidenceStore(tmp_path / "state")
    evidence_id = store.put_many(str(root), [{
        "path": "module.py",
        "file_sha256": hashlib.sha256(contents).hexdigest(),
        "start_line": 1,
        "end_line": 1,
        "text": "secret = 1",
    }])[0]["evidence_id"]

    assert store._hash_source_file(source) == hashlib.sha256(contents).hexdigest()
    assert store.get(evidence_id, verify=True)["source_verified"] is True
    source.write_bytes(contents + b"#")
    with pytest.raises(ValueError, match="4 MiB"):
        store._hash_source_file(source)
    current = store.get(evidence_id, verify=True)
    assert current["source_verified"] is False
    assert current["stale"] is True


def test_get_rejects_path_that_moves_outside_root_during_verification(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "module.py"
    outside = tmp_path / "outside.py"
    text = "secret = 1\n"
    source.write_text(text, encoding="utf-8")
    outside.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    store = EvidenceStore(tmp_path / "state")
    evidence_id = store.put_many(str(root), [{
        "path": "module.py",
        "file_sha256": digest,
        "start_line": 1,
        "end_line": 1,
        "text": "secret = 1",
    }])[0]["evidence_id"]

    original_resolve = Path.resolve
    candidate = root / "module.py"
    resolve_calls = 0

    def path_swap(path, *args, **kwargs):
        nonlocal resolve_calls
        if path == candidate:
            resolve_calls += 1
            if resolve_calls >= 2:
                return outside
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", path_swap)
    current = store.get(evidence_id, verify=True)

    assert resolve_calls >= 2, "verification did not recheck the opened path"
    assert current["success"] is True and current["stale"] is True
    assert current["source_verified"] is False


def test_get_and_get_many_reject_symlink_retarget_outside_root(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "module.py"
    outside = tmp_path / "outside.py"
    text = "secret = 1\n"
    source.write_text(text, encoding="utf-8")
    outside.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    store = EvidenceStore(tmp_path / "state")
    stored = store.put_many(str(root), [{
        "path": "module.py",
        "file_sha256": digest,
        "start_line": 1,
        "end_line": 1,
        "text": "secret = 1",
    }])
    evidence_id = stored[0]["evidence_id"]

    source.unlink()
    try:
        source.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("file symlinks unavailable on this host")

    single = store.get(evidence_id, verify=True)
    batch = store.get_many([evidence_id], verify=True)[0]
    assert single["success"] is True and single["stale"] is True
    assert batch["success"] is True and batch["stale"] is True
    assert single["source_verified"] is False
    assert batch["source_verified"] is False
    assert store.validate_current_many([evidence_id]) is False


def test_context_pack_uses_batched_evidence_fetch(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "module.py"
    source.write_text("first = 1\nsecond = 2\n", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    store = EvidenceStore(tmp_path / "state")
    items = store.put_many(str(root), [
        {"path": "module.py", "file_sha256": digest, "start_line": 1, "end_line": 1, "text": "first = 1"},
        {"path": "module.py", "file_sha256": digest, "start_line": 2, "end_line": 2, "text": "second = 2"},
    ])
    ids = [str(item["evidence_id"]) for item in items]
    fetch_batches = []
    original_get_many = store.get_many

    def tracked_get_many(evidence_ids, **kwargs):
        fetch_batches.append(list(evidence_ids))
        return original_get_many(evidence_ids, **kwargs)

    monkeypatch.setattr(store, "get_many", tracked_get_many)
    engine = SimpleNamespace(
        query=lambda *_args, **_kwargs: {"evidence": [{"evidence_id": eid} for eid in ids]},
        render_answer=lambda *_args, **_kwargs: "facts",
        evidence=store,
        code_index=None,
        _root=lambda value: value,
    )

    packed = DeterministicEngine.context_pack(engine, str(root), "probe", max_chars=1000, max_raw_evidence=1)

    assert packed["success"] is True
    assert "first = 1" in packed["context"]
    assert "second = 2" not in packed["context"]
    assert fetch_batches == [[ids[0]]]


def test_exact_evidence_batches_persistence_and_keeps_exact_items(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    first = root / "first.py"
    second = root / "second.py"
    first.write_text("first = 1\n", encoding="utf-8")
    second.write_text("second = 2\n", encoding="utf-8")
    store = EvidenceStore(tmp_path / "state")
    batch_calls = []
    original_put_many = store.put_many

    def tracked_put_many(batch_root, items):
        batch_calls.append([item["path"] for item in items])
        return original_put_many(batch_root, items)

    def unexpected_put(*_args, **_kwargs):
        raise AssertionError("exact evidence should use the batch writer")

    monkeypatch.setattr(store, "put_many", tracked_put_many)
    monkeypatch.setattr(store, "put", unexpected_put)
    engine = SimpleNamespace(
        evidence=store,
        max_evidence=8,
        repo_tools=RepositoryTools({}),
        code_index=None,
    )
    engine.merge_overlapping_slices = lambda batch_root, slices: (
        DeterministicEngine.merge_overlapping_slices(engine, batch_root, slices)
    )

    items = DeterministicEngine._exact_evidence(
        engine,
        str(root),
        [{"path": "first.py", "line": 1}, {"path": "second.py", "line": 1}],
    )

    assert batch_calls == [["first.py", "second.py"]]
    assert len(items) == 2
    assert all("text" not in item and item.get("evidence_id") for item in items)
    stored = store.get_many(
        [str(item["evidence_id"]) for item in items], verify=False, root=str(root)
    )
    assert [item["text"] for item in stored] == ["first = 1", "second = 2"]
