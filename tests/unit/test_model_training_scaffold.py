from __future__ import annotations

import json
import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from tools.model_training.manifest import validate_dataset_pair
from tools.model_training.runtime import resolve_runtime


def _row(
    item_id: str,
    group_id: str,
    role: str = "assistant",
    *,
    source_hash: str | None = None,
) -> dict[str, object]:
    messages = [
        {"role": "system", "content": "Return JSON."},
        {"role": "user", "content": "Summarize source."},
    ]
    if role == "assistant":
        messages.append({"role": "assistant", "content": "{}"})
    provenance: dict[str, str] = {"dataset": "fixture-v1"}
    if source_hash is not None:
        provenance.update({"source_path": f"{item_id}.py", "source_sha256": source_hash})
    row = {
        "id": item_id,
        "group_id": group_id,
        "messages": messages,
        "provenance": provenance,
    }
    if role == "user":
        row["expected"] = "{}"
    return row


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_dataset_pair_accepts_disjoint_project_groups(tmp_path: Path) -> None:
    train = tmp_path / "train.jsonl"
    evaluation = tmp_path / "eval.jsonl"
    _write_jsonl(train, [_row("train-1", "repo-a", source_hash="a" * 64)])
    _write_jsonl(evaluation, [_row("eval-1", "repo-b", "user", source_hash="b" * 64)])

    result = validate_dataset_pair(train, evaluation)

    assert result["train_rows"] == 1
    assert result["evaluation_rows"] == 1
    assert result["group_overlap"] == []


def test_dataset_pair_rejects_project_leakage(tmp_path: Path) -> None:
    train = tmp_path / "train.jsonl"
    evaluation = tmp_path / "eval.jsonl"
    _write_jsonl(train, [_row("train-1", "same-repo")])
    _write_jsonl(evaluation, [_row("eval-1", "same-repo", "user")])

    with pytest.raises(ValueError, match="group leakage"):
        validate_dataset_pair(train, evaluation)


def test_dataset_pair_rejects_content_hash_leakage(tmp_path: Path) -> None:
    train = tmp_path / "train.jsonl"
    evaluation = tmp_path / "eval.jsonl"
    digest = "c" * 64
    _write_jsonl(train, [_row("train-1", "repo-a", source_hash=digest)])
    _write_jsonl(evaluation, [_row("eval-1", "repo-b", "user", source_hash=digest)])

    with pytest.raises(ValueError, match="source hash leakage"):
        validate_dataset_pair(train, evaluation)


def test_dataset_pair_requires_provenance_and_unique_ids(tmp_path: Path) -> None:
    train = tmp_path / "train.jsonl"
    evaluation = tmp_path / "eval.jsonl"
    row = _row("duplicate", "repo-a")
    _write_jsonl(train, [row, row])
    _write_jsonl(evaluation, [_row("duplicate", "repo-b", "user")])

    with pytest.raises(ValueError, match="duplicate id"):
        validate_dataset_pair(train, evaluation)

    row["provenance"] = {}
    _write_jsonl(train, [row])
    with pytest.raises(ValueError, match="provenance"):
        validate_dataset_pair(train, evaluation)


class _FakeCuda:
    def __init__(self, available: bool, bfloat16: bool) -> None:
        self._available = available
        self._bfloat16 = bfloat16

    def is_available(self) -> bool:
        return self._available

    def is_bf16_supported(self) -> bool:
        return self._bfloat16


class _FakeTorch:
    float32 = "float32"
    bfloat16 = "bfloat16"
    float16 = "float16"

    def __init__(self, *, available: bool = True, bfloat16: bool = True) -> None:
        self.cuda = _FakeCuda(available, bfloat16)
        self.nn = type("NN", (), {"functional": type("F", (), {"scaled_dot_product_attention": True})})


def test_cuda_request_fails_instead_of_falling_back_to_cpu() -> None:
    with pytest.raises(RuntimeError, match="CUDA requested but unavailable"):
        resolve_runtime(device="cuda", torch_module=_FakeTorch(available=False))


def test_cuda_runtime_prefers_bf16_sdpa_and_fused_optimizer() -> None:
    result = resolve_runtime(device="cuda", precision="bf16", torch_module=_FakeTorch())

    assert result["device"] == "cuda"
    assert result["precision"] == "bf16"
    assert result["attention"] == "sdpa"
    assert result["fused_optimizer"] is True


def test_split_dataset_keeps_projects_and_duplicate_sources_together(tmp_path: Path) -> None:
    from tools.model_training.dataset import split_dataset

    source = tmp_path / "all.jsonl"
    train = tmp_path / "train.jsonl"
    evaluation = tmp_path / "eval.jsonl"
    _write_jsonl(
        source,
        [
            _row("a-1", "repo-a", source_hash="a" * 64),
            _row("b-1", "repo-b", source_hash="a" * 64),
            _row("c-1", "repo-c", source_hash="c" * 64),
        ],
    )

    summary = split_dataset(source, train, evaluation, evaluation_fraction=0.34, seed=17)
    pair = validate_dataset_pair(train, evaluation)
    eval_rows = [json.loads(line) for line in evaluation.read_text(encoding="utf-8").splitlines()]

    assert summary["evaluation_groups"] >= 1
    assert pair["group_overlap"] == []
    assert all(len(row["messages"]) == 2 and "expected" in row for row in eval_rows)


def test_split_dataset_refuses_to_overwrite_its_input(tmp_path: Path) -> None:
    from tools.model_training.dataset import split_dataset

    source = tmp_path / "all.jsonl"
    _write_jsonl(source, [_row("a-1", "repo-a"), _row("b-1", "repo-b")])

    with pytest.raises(ValueError, match="paths must be distinct"):
        split_dataset(source, source, tmp_path / "eval.jsonl")


def test_teacher_roots_require_explicit_absolute_directories(tmp_path: Path) -> None:
    from tools.model_training.teacher_cards import load_roots

    roots_path = tmp_path / "roots.json"
    project = tmp_path / "project"
    project.mkdir()
    roots_path.write_text(json.dumps({"roots": [{"id": "project-a", "path": str(project)}]}), encoding="utf-8")
    assert load_roots(roots_path)[0]["id"] == "project-a"

    roots_path.write_text(json.dumps({"roots": [{"id": "project-a", "path": "relative/project"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="absolute existing non-symlink directory"):
        load_roots(roots_path)


def test_teacher_endpoint_must_be_loopback() -> None:
    from tools.model_training.teacher_cards import validate_local_endpoint

    assert validate_local_endpoint("http://127.0.0.1:11434/api/generate").startswith("http://")
    with pytest.raises(ValueError, match="loopback"):
        validate_local_endpoint("https://example.com/api/generate")


def test_task_scorer_reports_schema_exact_match_facts_and_forbidden_claims() -> None:
    from tools.model_training.scoring import score_prediction

    row = {
        "expected": {"label": "allow", "note": "no admin bypass"},
        "required_facts": [{"field": "label", "value": "allow"}],
        "forbidden_claims": ["admin bypass"],
    }
    result = score_prediction(
        '{"label":"allow","note":"no admin bypass"}',
        row,
        {"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"]},
    )

    assert result["schema_pass"] is True
    assert result["exact_match"] is True
    assert result["required_fact_recall"] == 1.0
    assert result["forbidden_claim_count"] == 1


def test_task_scorer_marks_malformed_output_as_schema_failure() -> None:
    from tools.model_training.scoring import score_prediction

    result = score_prediction("not json", {"expected": {"label": "allow"}}, {"type": "object"})

    assert result["schema_pass"] is False
    assert result["exact_match"] is False


def test_teacher_source_walk_skips_secrets_and_generated_directories(tmp_path: Path) -> None:
    from tools.model_training.teacher_cards import iter_source_files

    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "node_modules").mkdir()
    (root / "src").mkdir()
    (root / "src" / "good.py").write_text("print('ok')\n", encoding="utf-8")
    (root / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    (root / ".git" / "ignored.py").write_text("ignored = True\n", encoding="utf-8")
    (root / "node_modules" / "ignored.js").write_text("ignored()\n", encoding="utf-8")
    (root / "large.py").write_text("x" * 50, encoding="utf-8")

    found = list(iter_source_files([{"id": "repo-a", "path": str(root)}], max_bytes=100, max_chars=20))

    assert [(group_id, relative_path) for group_id, _, relative_path, _, _ in found] == [
        ("repo-a", "src/good.py")
    ]


def test_teacher_messages_include_exact_schema_contract() -> None:
    from tools.model_training.teacher_cards import CARD_SCHEMA, build_messages

    messages = build_messages("src/example.py", "def example(): return 1")

    assert messages[0]["role"] == "system"
    assert json.dumps(CARD_SCHEMA, separators=(",", ":")) in messages[0]["content"]


def test_matrix_manifest_rejects_path_traversal_model_name(tmp_path: Path) -> None:
    from tools.model_training.run_matrix import load_matrix_manifest

    manifest = {
        "schema_version": 1,
        "name": "preprocess",
        "task_type": "preprocess_card",
        "train_file": "train.jsonl",
        "evaluation_file": "eval.jsonl",
        "output_root": "runs",
        "output_schema": {"type": "object"},
        "models": [{"name": "../outside", "base_model": "Qwen/model"}],
    }
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="unsafe model run name"):
        load_matrix_manifest(path)


def test_run_matrix_orders_baseline_training_and_after_benchmark(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import tools.model_training.run_matrix as matrix_runner

    train_file = tmp_path / "train.jsonl"
    eval_file = tmp_path / "eval.jsonl"
    _write_jsonl(train_file, [_row("train-1", "repo-train")])
    _write_jsonl(eval_file, [_row("eval-1", "repo-eval", "user")])
    manifest = {
        "schema_version": 1,
        "name": "preprocess-card",
        "task_type": "preprocess_card",
        "train_file": str(train_file),
        "evaluation_file": str(eval_file),
        "output_root": str(tmp_path / "runs"),
        "system_prompt": "Return JSON.",
        "output_schema": {"type": "object"},
        "training": {"device": "cuda"},
        "benchmark": {"device": "cuda"},
        "models": [{"name": "tiny", "base_model": "local-base"}],
    }
    manifest_path = tmp_path / "matrix.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    events: list[str] = []

    def fake_benchmark(run_path: Path, *, adapter_path: Path | None, output_path: Path, allow_model_download: bool) -> dict[str, object]:
        run_data = json.loads(run_path.read_text(encoding="utf-8"))
        model = run_data["base_model"]
        phase = "before" if adapter_path is None else "after"
        events.append(phase)
        value = {
            "base_model": model,
            "run_manifest_sha256": hashlib.sha256(run_path.read_bytes()).hexdigest(),
            "evaluation_sha256": hashlib.sha256(eval_file.read_bytes()).hexdigest(),
            "summary": {"base": {"runs": 1}, "adapter": None if adapter_path is None else {"runs": 1}},
        }
        output_path.write_text(json.dumps(value), encoding="utf-8")
        return value

    def fake_train(run_path: Path, *, allow_model_download: bool) -> dict[str, object]:
        run_data = json.loads(run_path.read_text(encoding="utf-8"))
        events.append("train")
        adapter = Path(run_data["output_dir"])
        adapter.mkdir(parents=True, exist_ok=True)
        value = {
            "base_model": run_data["base_model"],
            "run_manifest_sha256": hashlib.sha256(run_path.read_bytes()).hexdigest(),
            "evaluation_sha256": hashlib.sha256(eval_file.read_bytes()).hexdigest(),
            "train_sha256": hashlib.sha256(train_file.read_bytes()).hexdigest(),
        }
        (adapter / "training_run.json").write_text(json.dumps(value), encoding="utf-8")
        return value

    monkeypatch.setattr(matrix_runner, "benchmark_from_manifest", fake_benchmark)
    monkeypatch.setattr(matrix_runner, "train_from_manifest", fake_train)

    result = matrix_runner.run_matrix(manifest_path)

    assert events == ["before", "train", "after"]
    assert len(result) == 1


def _write_existing_card_index(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "project"
    project.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    source = "def secret(): return 'private source text'\n"
    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    card_key = "src/example.py"
    with closing(sqlite3.connect(state / "preprocess.sqlite3")) as connection:
        connection.executescript(
            """
            CREATE TABLE projects(root TEXT PRIMARY KEY);
            CREATE TABLE content_cards(
                card_key TEXT PRIMARY KEY, content_hash TEXT NOT NULL, card_json TEXT, model TEXT, analyzer_version TEXT
            );
            CREATE TABLE file_refs(
                root TEXT, path TEXT, content_hash TEXT, needs_hash INTEGER, card_key TEXT
            );
            CREATE TABLE source_index(root TEXT, path TEXT, text TEXT, content_hash TEXT);
            CREATE TABLE module_cards(root TEXT, module TEXT, revision_hash TEXT, card_json TEXT);
            CREATE TABLE project_cards(root TEXT, revision_hash TEXT, card_json TEXT);
            """
        )
        connection.execute("INSERT INTO projects(root) VALUES (?)", (str(project),))
        connection.execute(
            "INSERT INTO content_cards VALUES (?, ?, ?, ?, ?)",
            (card_key, source_hash, json.dumps({"summary": "example"}), "local-teacher", "v1"),
        )
        connection.execute(
            "INSERT INTO file_refs VALUES (?, ?, ?, ?, ?)",
            (str(project), card_key, source_hash, 0, card_key),
        )
        connection.execute(
            "INSERT INTO source_index VALUES (?, ?, ?, ?)",
            (str(project), card_key, source, source_hash),
        )
        connection.commit()
    return state, project


def test_existing_card_export_lists_metadata_then_exports_local_rows(tmp_path: Path) -> None:
    from tools.model_training.existing_cards import (
        export_existing_cards,
        list_existing_card_candidates,
    )

    state, _project = _write_existing_card_index(tmp_path)
    candidates = list_existing_card_candidates(state_dir=state, format="card-training")
    assert len(candidates["candidates"]) == 1
    candidate = candidates["candidates"][0]
    assert "private source text" not in json.dumps(candidates)
    assert set(candidate) == {
        "row_id", "root_id", "card_kind", "relative_path", "card_sha256",
        "source_sha256", "card_model", "card_version",
    }

    output = state / "cards.jsonl"
    result = export_existing_cards(
        state_dir=state,
        output_path=output,
        format="card-training",
    )
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert result["row_count"] == 1
    assert rows[0]["provenance"]["source"] == "existing_hub_preprocess_card"
    assert rows[0]["provenance"]["data_class"] == "existing_local"
    assert "per_example_consented" not in rows[0]["provenance"]
    assert "consent_receipt_sha256" not in rows[0]["provenance"]
    assert any("private source text" in message["content"] for message in rows[0]["messages"])


def test_existing_card_export_resume_drops_rows_missing_from_current_index(tmp_path: Path) -> None:
    from tools.model_training.existing_cards import export_existing_cards, list_existing_card_candidates

    state, project = _write_existing_card_index(tmp_path)
    second_source = "def second(): return 'private second source text'\\n"
    second_hash = hashlib.sha256(second_source.encode("utf-8")).hexdigest()
    with closing(sqlite3.connect(state / "preprocess.sqlite3")) as connection:
        connection.execute(
            "INSERT INTO content_cards VALUES (?, ?, ?, ?, ?)",
            ("src/second.py", second_hash, json.dumps({"summary": "second example"}), "local-teacher", "v1"),
        )
        connection.execute(
            "INSERT INTO file_refs VALUES (?, ?, ?, ?, ?)",
            (str(project), "src/second.py", second_hash, 0, "src/second.py"),
        )
        connection.execute(
            "INSERT INTO source_index VALUES (?, ?, ?, ?)",
            (str(project), "src/second.py", second_source, second_hash),
        )
        connection.commit()
    candidates = list_existing_card_candidates(state_dir=state, format="card-training")["candidates"]
    output = state / "cards.jsonl"
    export_existing_cards(state_dir=state, output_path=output, format="card-training")
    selected = next(row for row in candidates if row["relative_path"] == "src/example.py")
    with closing(sqlite3.connect(state / "preprocess.sqlite3")) as connection:
        connection.execute("DELETE FROM file_refs WHERE path=?", ("src/second.py",))
        connection.commit()

    result = export_existing_cards(
        state_dir=state, output_path=output, format="card-training",
        resume=True,
    )

    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert result["row_count"] == 1
    assert [row["id"] for row in rows] == [selected["row_id"]]


@pytest.mark.parametrize("dataset_format", ["card-training", "embedding-corpus"])
def test_existing_card_export_resume_drops_card_with_stale_stored_source_hash(tmp_path: Path, dataset_format: str) -> None:
    from tools.model_training.existing_cards import export_existing_cards, list_existing_card_candidates

    state, _project = _write_existing_card_index(tmp_path)
    output = state / "cards.jsonl"
    original = export_existing_cards(state_dir=state, output_path=output, format=dataset_format)
    assert original["row_count"] == 1

    new_text = "def updated(): return 'current source'\n"
    new_hash = hashlib.sha256(new_text.encode("utf-8")).hexdigest()
    with closing(sqlite3.connect(state / "preprocess.sqlite3")) as connection:
        connection.execute("UPDATE file_refs SET content_hash=?", (new_hash,))
        connection.execute("UPDATE source_index SET text=?,content_hash=?", (new_text, new_hash))
        connection.commit()

    with pytest.raises(ValueError, match="no eligible existing Hub cards"):
        list_existing_card_candidates(state_dir=state, format=dataset_format)
    with pytest.raises(ValueError, match="no eligible existing Hub cards"):
        export_existing_cards(state_dir=state, output_path=state / "unused.jsonl", format=dataset_format)
    resumed = export_existing_cards(state_dir=state, output_path=output, format=dataset_format, resume=True)
    assert resumed["row_count"] == 0
    assert resumed["counts"]["missing_source_pairs"] == 1
    assert output.read_bytes() == b""
    manifest = json.loads(Path(resumed["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["row_count"] == 0
    assert manifest["dataset_sha256"] == hashlib.sha256(b"").hexdigest()

    with closing(sqlite3.connect(state / "preprocess.sqlite3")) as connection:
        connection.execute("UPDATE content_cards SET content_hash=?,card_json=?",
                           (new_hash, json.dumps({"summary": "new card"})))
        connection.commit()
    restored = export_existing_cards(state_dir=state, output_path=output, format=dataset_format, resume=True)
    assert restored["row_count"] == 1
    row = json.loads(output.read_text(encoding="utf-8"))
    assert row["provenance"]["source_sha256"] == new_hash
    assert "new card" in json.dumps(row)


def test_existing_card_export_reads_one_index_snapshot_during_wal_update(tmp_path: Path, monkeypatch) -> None:
    from tools.model_training import existing_cards

    state, _project = _write_existing_card_index(tmp_path)
    database = state / "preprocess.sqlite3"
    original_authorize = existing_cards._authorized_roots
    updated_source = "def updated(): return 42\n"
    updated_hash = hashlib.sha256(updated_source.encode("utf-8")).hexdigest()
    with closing(sqlite3.connect(database, timeout=2.0)) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)

        def authorize_then_update(connection, roots_file):
            roots = original_authorize(connection, roots_file)
            writer.execute("UPDATE file_refs SET content_hash=?", (updated_hash,))
            writer.execute("UPDATE source_index SET text=?,content_hash=?", (updated_source, updated_hash))
            writer.execute("UPDATE content_cards SET content_hash=?,card_json=?",
                           (updated_hash, json.dumps({"summary": "new snapshot"})))
            writer.commit()
            return roots

        monkeypatch.setattr(existing_cards, "_authorized_roots", authorize_then_update)
        output = state / "cards.jsonl"
        report = existing_cards.export_existing_cards(state_dir=state, output_path=output, format="card-training")
        assert report["row_count"] == 1
        assert writer.execute("SELECT content_hash FROM source_index").fetchone() == (updated_hash,)

    row = json.loads(output.read_text(encoding="utf-8"))
    assert row["provenance"]["source_sha256"] != updated_hash
    assert any("private source text" in message["content"] for message in row["messages"])
    assert json.loads(row["messages"][-1]["content"]) == {"summary": "example"}


def test_existing_card_export_resume_preserves_unrelated_state_files(tmp_path: Path) -> None:
    from tools.model_training.existing_cards import export_existing_cards

    state, _project = _write_existing_card_index(tmp_path)
    database = state / "preprocess.sqlite3"
    unrelated = state / "other-data.jsonl"
    unrelated.write_bytes(b'{"id":"unrelated","text":"keep this"}\n')
    for output in (unrelated, database):
        original = output.read_bytes()
        with pytest.raises(ValueError, match="existing card export|preprocessing index"):
            export_existing_cards(state_dir=state, output_path=output, format="card-training", resume=True)
        assert output.read_bytes() == original

    output = state / "unstarted.jsonl"
    manifest = output.with_name(output.name + ".manifest.json")
    manifest.write_bytes(b'{"unrelated":true}\n')
    with pytest.raises(ValueError, match="existing card export manifest"):
        export_existing_cards(state_dir=state, output_path=output, format="card-training", resume=True)
    assert not output.exists()
    assert manifest.read_bytes() == b'{"unrelated":true}\n'


@pytest.mark.parametrize("manifest_missing", [True, False])
def test_existing_card_export_recovers_interrupted_manifest_publication(tmp_path: Path, manifest_missing: bool) -> None:
    from tools.model_training.existing_cards import export_existing_cards

    state, _project = _write_existing_card_index(tmp_path)
    output = state / "cards.jsonl"
    exported = export_existing_cards(state_dir=state, output_path=output, format="card-training")
    manifest_path = Path(exported["manifest_path"])
    expected = output.read_bytes()
    if manifest_missing:
        manifest_path.unlink()
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["dataset_sha256"] = hashlib.sha256(b"earlier complete export").hexdigest()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    resumed = export_existing_cards(state_dir=state, output_path=output, format="card-training", resume=True)

    assert output.read_bytes() == expected
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["dataset_sha256"] == resumed["dataset_sha256"] == hashlib.sha256(expected).hexdigest()


def test_existing_card_export_serializes_same_output_across_processes(tmp_path: Path) -> None:
    import subprocess
    import sys
    import time

    from local_ai_hub.process_utils import hidden_run_kwargs

    state, _project = _write_existing_card_index(tmp_path)
    output = state / "cards.jsonl"
    manifest_path = output.with_name(output.name + ".manifest.json")
    ready = tmp_path / "ready"
    release = tmp_path / "release"
    pause_first = """
import os
import sys
import time
from pathlib import Path
from tools.model_training.cli import main

ready, release, manifest = map(Path, sys.argv[1:4])
replace = os.replace
def pause_at_manifest(source, target):
    if Path(target) == manifest:
        ready.touch()
        deadline = time.monotonic() + 25
        while not release.exists():
            if time.monotonic() >= deadline:
                raise TimeoutError('test did not release first exporter')
            time.sleep(0.02)
    return replace(source, target)

os.replace = pause_at_manifest
sys.argv = [sys.argv[0], *sys.argv[4:]]
raise SystemExit(main())
"""
    args = ["export-existing-cards", "--state-dir", str(state), "--all-indexed",
            "--output", str(output), "--format", "card-training"]
    cli = [sys.executable, "-m", "tools.model_training.cli", *args, "--resume"]
    first = subprocess.Popen(
        [sys.executable, "-c", pause_first, str(ready), str(release), str(manifest_path), *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, **hidden_run_kwargs(),
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and first.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), "first exporter never reached manifest publication"
        first_bytes = output.read_bytes()
        assert not manifest_path.exists()

        with closing(sqlite3.connect(state / "preprocess.sqlite3")) as connection:
            connection.execute("UPDATE content_cards SET card_json=?", (json.dumps({"summary": "later card"}),))
            connection.commit()
        second = subprocess.run(cli, capture_output=True, timeout=12, **hidden_run_kwargs())
        assert second.returncode != 0
        assert b"file update lock timed out" in second.stderr
        assert output.read_bytes() == first_bytes
        assert not manifest_path.exists()
    finally:
        release.touch()
        try:
            _stdout, stderr = first.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            first.kill()
            first.communicate(timeout=5)
            raise

    assert first.returncode == 0, stderr.decode(errors="replace")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["dataset_sha256"] == hashlib.sha256(first_bytes).hexdigest()
    completed = subprocess.run(cli, capture_output=True, check=True, timeout=12, **hidden_run_kwargs())
    report = json.loads(completed.stdout)
    final_bytes = output.read_bytes()
    assert final_bytes != first_bytes
    assert b"later card" in final_bytes
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["dataset_sha256"] == report["dataset_sha256"] == hashlib.sha256(final_bytes).hexdigest()


def test_existing_card_export_keeps_cases_separate_for_outputs_with_same_stem(tmp_path: Path) -> None:
    from tools.model_training.existing_cards import export_existing_cards

    state, project = _write_existing_card_index(tmp_path)
    prepared = []
    for suffix, case_id in [(".jsonl", "first"), (".copy", "second")]:
        cases = project / f"{case_id}.json"
        cases.write_text(json.dumps({
            "schema_version": 1,
            "case_set": case_id,
            "cases": [{"id": case_id, "query": "find the example", "expected_paths": ["src/example.py"]}],
        }), encoding="utf-8")
        report = export_existing_cards(
            state_dir=state, output_path=f"cards{suffix}", format="embedding-corpus",
            benchmark_cases_file=cases, benchmark_root=project,
        )
        manifest = json.loads(Path(report["manifest_path"]).read_text(encoding="utf-8"))
        evaluation = manifest["benchmark_inputs"]["retrieval_evaluation"]
        assert evaluation["prepared"] is True
        prepared.append((state / evaluation["prepared_cases"], evaluation["prepared_cases_sha256"], case_id))

    assert prepared[0][0] != prepared[1][0]
    for path, digest, case_id in prepared:
        content = path.read_bytes()
        assert hashlib.sha256(content).hexdigest() == digest
        assert json.loads(content)["cases"][0]["id"] == case_id


def test_existing_card_export_resume_cleans_staging_left_by_process_exit(tmp_path: Path) -> None:
    import subprocess
    import sys

    from local_ai_hub.process_utils import hidden_run_kwargs

    state, _project = _write_existing_card_index(tmp_path)
    output = state / "cards.jsonl"
    manifest_path = output.with_name(output.name + ".manifest.json")
    source_index = (state / "preprocess.sqlite3").read_bytes()
    crash = """
import os
import sys
from pathlib import Path
from tools.model_training.cli import main

manifest = Path(sys.argv.pop(1))
replace = os.replace
def crash_at_manifest(source, target):
    if Path(target) == manifest:
        os._exit(77)
    return replace(source, target)

os.replace = crash_at_manifest
raise SystemExit(main())
"""
    args = ["export-existing-cards", "--state-dir", str(state), "--all-indexed",
            "--output", str(output), "--format", "card-training"]
    first = subprocess.run(
        [sys.executable, "-c", crash, str(manifest_path), *args], capture_output=True, timeout=15,
        **hidden_run_kwargs(),
    )
    assert first.returncode == 77, first.stderr.decode(errors="replace")
    assert output.is_file() and not manifest_path.exists()
    leftover, = state.rglob("*.tmp")
    untouched = leftover.with_name("unrelated.tmp")
    untouched.write_bytes(b"preserve")
    exported = output.read_bytes()

    resumed = subprocess.run(
        [sys.executable, "-m", "tools.model_training.cli", *args, "--resume"],
        capture_output=True, check=True, timeout=15, **hidden_run_kwargs(),
    )
    assert not leftover.exists()
    assert untouched.read_bytes() == b"preserve"
    assert output.read_bytes() == exported
    digest = hashlib.sha256(exported).hexdigest()
    assert json.loads(resumed.stdout)["dataset_sha256"] == digest
    assert json.loads(manifest_path.read_bytes())["dataset_sha256"] == digest
    assert (state / "preprocess.sqlite3").read_bytes() == source_index


def test_existing_card_export_leaves_unowned_staging_directory_untouched(tmp_path: Path) -> None:
    from tools.model_training.existing_cards import export_existing_cards

    state, _project = _write_existing_card_index(tmp_path)
    output = state / "cards.jsonl"
    report = export_existing_cards(state_dir=state, output_path=output, format="card-training")
    stage, = (path for path in state.glob(".card-export-*") if path.is_dir())
    (stage / "owner").unlink()
    foreign = stage / "dataset.tmp"
    foreign.write_bytes(b"unrelated fixture")
    published = output.read_bytes()
    manifest = Path(report["manifest_path"])
    published_manifest = manifest.read_bytes()

    with pytest.raises(ValueError, match="has no ownership marker"):
        export_existing_cards(state_dir=state, output_path=output, format="card-training", resume=True)

    assert foreign.read_bytes() == b"unrelated fixture"
    assert output.read_bytes() == published
    assert manifest.read_bytes() == published_manifest


def _laya_row(
    item_id: str,
    group_id: str,
    *,
    provenance: dict[str, object] | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "id": item_id,
        "group_id": group_id,
        "state": {"gap_code": "unresolved_evidence_gap", "case": item_id},
        "questions": {"source": {"options": ["indexed", "rag"]}},
        "expected": {"source": "indexed"},
    }
    if provenance is not None:
        row["provenance"] = provenance
    return row


def _target_sha256(targets: dict[str, str]) -> str:
    canonical = json.dumps(targets, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_laya_dataset_rejects_rows_without_verified_label_provenance(tmp_path: Path) -> None:
    from tools.model_training.laya_backend import validate_laya_dataset_pair

    train = tmp_path / "laya-train.jsonl"
    evaluation = tmp_path / "laya-eval.jsonl"
    _write_jsonl(train, [_laya_row("train-1", "repo-train")])
    _write_jsonl(evaluation, [_laya_row("eval-1", "repo-eval")])

    with pytest.raises(ValueError, match="provenance"):
        validate_laya_dataset_pair(train, evaluation)


def test_laya_dataset_accepts_verified_synthetic_fixture_oracle_rows(tmp_path: Path) -> None:
    from tools.model_training.laya_backend import validate_laya_dataset_pair

    target = {"source": "indexed"}
    label_provenance = {
        "status": "verified",
        "method": "synthetic_fixture_oracle",
        "target_sha256": _target_sha256(target),
    }
    train = tmp_path / "laya-train.jsonl"
    evaluation = tmp_path / "laya-eval.jsonl"
    _write_jsonl(
        train,
        [
            _laya_row(
                "train-1",
                "repo-train",
                provenance={
                    "data_class": "synthetic_non_private",
                    "fixture_id": "fixture-train",
                    "label_provenance": label_provenance,
                },
            )
        ],
    )
    _write_jsonl(
        evaluation,
        [
            _laya_row(
                "eval-1",
                "repo-eval",
                provenance={
                    "data_class": "synthetic_non_private",
                    "fixture_id": "fixture-eval",
                    "label_provenance": {
                        **label_provenance,
                    },
                },
            )
        ],
    )

    result = validate_laya_dataset_pair(train, evaluation)
    assert result["group_overlap"] == []


def test_laya_dataset_rejects_legacy_multi_reviewer_labels(tmp_path: Path) -> None:
    from tools.model_training.laya_backend import validate_laya_dataset_pair

    target = {"source": "indexed"}
    proof = {
        "status": "verified",
        "method": "blind_double_annotation",
        "target_sha256": _target_sha256(target),
        "annotation_identity_sha256": ["a" * 64, "b" * 64],
        "agreement": True,
        "adjudicator_identity_sha256": "c" * 64,
        "verification_identity_sha256": "d" * 64,
    }
    paths = [tmp_path / "train.jsonl", tmp_path / "eval.jsonl"]
    rows = [
        _laya_row("train", "train-group", provenance={
            "data_class": "local_scoped", "candidate_id": "train", "candidate_sha256": "a" * 64,
            "label_provenance": proof,
        }),
        _laya_row("eval", "eval-group", provenance={
            "data_class": "local_scoped", "candidate_id": "eval", "candidate_sha256": "b" * 64,
            "label_provenance": proof,
        }),
    ]
    for path, row in zip(paths, rows):
        row["source_sha256"] = row["provenance"]["candidate_sha256"]
        _write_jsonl(path, [row])

    with pytest.raises(ValueError, match="unsupported verified label provenance"):
        validate_laya_dataset_pair(*paths)


def test_laya_dataset_rejects_unbound_deterministic_evidence_labels(tmp_path: Path) -> None:
    from tools.model_training.laya_backend import validate_laya_dataset_pair

    target = {"source": "indexed"}
    proof = {
        "status": "verified",
        "method": "deterministic_evidence",
        "target_sha256": _target_sha256(target),
        "evidence_ids": ["caller-supplied-id"],
    }
    paths = [tmp_path / "train.jsonl", tmp_path / "eval.jsonl"]
    rows = [
        _laya_row("train", "train-group", provenance={
            "data_class": "local_scoped", "candidate_id": "train", "candidate_sha256": "a" * 64,
            "label_provenance": proof,
        }),
        _laya_row("eval", "eval-group", provenance={
            "data_class": "local_scoped", "candidate_id": "eval", "candidate_sha256": "b" * 64,
            "label_provenance": proof,
        }),
    ]
    for path, row in zip(paths, rows):
        row["source_sha256"] = row["provenance"]["candidate_sha256"]
        _write_jsonl(path, [row])

    with pytest.raises(ValueError, match="unsupported verified label provenance"):
        validate_laya_dataset_pair(*paths)


def test_existing_card_export_includes_all_authorized_indexed_rows(tmp_path: Path) -> None:
    from tools.model_training.existing_cards import (
        export_existing_cards,
        list_existing_card_candidates,
    )

    state, project = _write_existing_card_index(tmp_path)
    second_source = "def secret_two(): return 'private second source text'\n"
    second_hash = hashlib.sha256(second_source.encode("utf-8")).hexdigest()
    with closing(sqlite3.connect(state / "preprocess.sqlite3")) as connection:
        connection.execute(
            "INSERT INTO content_cards VALUES (?, ?, ?, ?, ?)",
            ("src/second.py", second_hash, json.dumps({"summary": "second example"}), "local-teacher", "v1"),
        )
        connection.execute(
            "INSERT INTO file_refs VALUES (?, ?, ?, ?, ?)",
            (str(project), "src/second.py", second_hash, 0, "src/second.py"),
        )
        connection.execute(
            "INSERT INTO source_index VALUES (?, ?, ?, ?)",
            (str(project), "src/second.py", second_source, second_hash),
        )
        connection.commit()

    candidates = list_existing_card_candidates(state_dir=state, format="card-training")
    assert candidates["candidate_count"] == 2
    output = state / "cards.jsonl"
    result = export_existing_cards(
        state_dir=state,
        output_path=output,
        format="card-training",
    )
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert result["row_count"] == 2
    assert {row["id"] for row in rows} == {candidate["row_id"] for candidate in candidates["candidates"]}
    assert all(row["provenance"]["data_class"] == "existing_local" for row in rows)
    assert all("consent_receipt_sha256" not in row["provenance"] for row in rows)


def test_existing_card_export_requires_no_per_example_consent(tmp_path: Path) -> None:
    from tools.model_training.existing_cards import export_existing_cards

    state, _project = _write_existing_card_index(tmp_path)
    result = export_existing_cards(state_dir=state, output_path=state / "cards.jsonl", format="card-training")
    assert result["row_count"] == 1


def test_laya_dataset_accepts_verified_local_scoped_rows(tmp_path: Path) -> None:
    from tools.model_training.laya_backend import validate_laya_dataset_pair

    target = {"source": "indexed"}
    label_provenance = {
        "status": "verified",
        "method": "local_operator_confirmation",
        "rubric_version": "laya-target-rubric-v1",
        "target_sha256": _target_sha256(target),
    }
    train = tmp_path / "laya-train.jsonl"
    evaluation = tmp_path / "laya-eval.jsonl"
    train_provenance = {
        "data_class": "local_scoped",
        "candidate_id": "train-1",
        "candidate_sha256": "a" * 64,
        "label_provenance": label_provenance,
    }
    eval_provenance = {
        "data_class": "local_scoped",
        "candidate_id": "eval-1",
        "candidate_sha256": "b" * 64,
        "label_provenance": label_provenance,
    }
    train_row = _laya_row("train-1", "repo-train", provenance=train_provenance)
    train_row["source_sha256"] = "a" * 64
    evaluation_row = _laya_row("eval-1", "repo-eval", provenance=eval_provenance)
    evaluation_row["source_sha256"] = "b" * 64
    _write_jsonl(train, [train_row])
    _write_jsonl(evaluation, [evaluation_row])

    assert validate_laya_dataset_pair(train, evaluation)["group_overlap"] == []
    evaluation_row["group_id"] = train_row["group_id"]
    _write_jsonl(evaluation, [evaluation_row])
    with pytest.raises(ValueError, match="group"):
        validate_laya_dataset_pair(train, evaluation)


def test_laya_dataset_accepts_keyless_local_operator_confirmed_rows(tmp_path: Path) -> None:
    from tools.model_training.laya_backend import validate_laya_dataset_pair

    target = {"source": "indexed"}
    proof = {
        "status": "verified",
        "method": "local_operator_confirmation",
        "rubric_version": "laya-target-rubric-v1",
        "target_sha256": _target_sha256(target),
    }
    train_row = _laya_row("train-1", "repo-train", provenance={
        "data_class": "local_scoped",
        "candidate_id": "train-1",
        "candidate_sha256": "a" * 64,
        "label_provenance": proof,
    })
    evaluation_row = _laya_row("eval-1", "repo-eval", provenance={
        "data_class": "local_scoped",
        "candidate_id": "eval-1",
        "candidate_sha256": "b" * 64,
        "label_provenance": proof,
    })
    train_row["source_sha256"] = "a" * 64
    evaluation_row["source_sha256"] = "b" * 64
    train = tmp_path / "laya-train.jsonl"
    evaluation = tmp_path / "laya-eval.jsonl"
    _write_jsonl(train, [train_row])
    _write_jsonl(evaluation, [evaluation_row])

    assert validate_laya_dataset_pair(train, evaluation)["group_overlap"] == []


def test_laya_dataset_rejects_retired_consent_fields(tmp_path: Path) -> None:
    from tools.model_training.laya_backend import validate_laya_dataset_pair

    train = tmp_path / "laya-train.jsonl"
    evaluation = tmp_path / "laya-eval.jsonl"
    target = {"source": "indexed"}
    proof = {
        "status": "verified",
        "method": "local_operator_confirmation",
        "rubric_version": "laya-target-rubric-v1",
        "target_sha256": _target_sha256(target),
    }
    train_row = _laya_row("train-1", "repo-train", provenance={
        "data_class": "local_scoped",
        "candidate_id": "train-1",
        "candidate_sha256": "a" * 64,
        "consent_receipt_id": "receipt-reused",
        "label_provenance": proof,
    })
    evaluation_row = _laya_row("eval-1", "repo-eval", provenance={
        "data_class": "local_scoped",
        "candidate_id": "eval-1",
        "candidate_sha256": "b" * 64,
        "consent_receipt_id": "receipt-reused",
        "label_provenance": proof,
    })
    train_row["source_sha256"] = "a" * 64
    evaluation_row["source_sha256"] = "b" * 64
    _write_jsonl(train, [train_row])
    _write_jsonl(evaluation, [evaluation_row])

    with pytest.raises(ValueError, match="retired consent fields"):
        validate_laya_dataset_pair(train, evaluation)

    train_row["provenance"].pop("consent_receipt_id")
    evaluation_row["provenance"].pop("consent_receipt_id")
    _write_jsonl(train, [train_row])
    _write_jsonl(evaluation, [evaluation_row])
    assert validate_laya_dataset_pair(train, evaluation)["group_overlap"] == []

    train_row["provenance"]["per_example_consented"] = False
    _write_jsonl(train, [train_row])
    with pytest.raises(ValueError, match="retired consent fields"):
        validate_laya_dataset_pair(train, evaluation)

    train_row["provenance"].pop("per_example_consented")
    train_row["consent_receipt_id"] = "receipt-reused"
    _write_jsonl(train, [train_row])
    with pytest.raises(ValueError, match="retired consent fields"):
        validate_laya_dataset_pair(train, evaluation)
