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
    result = resolve_runtime(device="cuda", torch_module=_FakeTorch())

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
                card_key TEXT PRIMARY KEY, card_json TEXT, model TEXT, analyzer_version TEXT
            );
            CREATE TABLE file_refs(
                root TEXT, path TEXT, content_hash TEXT, needs_hash INTEGER, card_key TEXT
            );
            CREATE TABLE source_index(root TEXT, path TEXT, text TEXT, content_hash TEXT);
            """
        )
        connection.execute("INSERT INTO projects(root) VALUES (?)", (str(project),))
        connection.execute(
            "INSERT INTO content_cards VALUES (?, ?, ?, ?)",
            (card_key, json.dumps({"summary": "example"}), "local-teacher", "v1"),
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
            "INSERT INTO content_cards VALUES (?, ?, ?, ?)",
            ("src/second.py", json.dumps({"summary": "second example"}), "local-teacher", "v1"),
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


def test_laya_dataset_accepts_verified_double_reviewed_synthetic_rows(tmp_path: Path) -> None:
    from tools.model_training.laya_backend import validate_laya_dataset_pair

    target = {"source": "indexed"}
    label_provenance = {
        "status": "verified",
        "method": "blind_double_annotation",
        "target_sha256": _target_sha256(target),
        "annotation_identity_sha256": [
            hashlib.sha256(b"annotation-1").hexdigest(),
            hashlib.sha256(b"annotation-2").hexdigest(),
        ],
        "agreement": False,
        "adjudicator_identity_sha256": hashlib.sha256(b"adjudicator-1").hexdigest(),
        "verification_identity_sha256": hashlib.sha256(b"verifier-1").hexdigest(),
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
                        "annotation_identity_sha256": [
                            hashlib.sha256(b"annotation-3").hexdigest(),
                            hashlib.sha256(b"annotation-4").hexdigest(),
                        ],
                        "agreement": True,
                        "adjudicator_identity_sha256": hashlib.sha256(b"adjudicator-2").hexdigest(),
                        "verification_identity_sha256": hashlib.sha256(b"verifier-2").hexdigest(),
                    },
                },
            )
        ],
    )

    result = validate_laya_dataset_pair(train, evaluation)
    assert result["group_overlap"] == []


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
            "INSERT INTO content_cards VALUES (?, ?, ?, ?)",
            ("src/second.py", json.dumps({"summary": "second example"}), "local-teacher", "v1"),
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
        "method": "blind_double_annotation",
        "target_sha256": _target_sha256(target),
        "annotation_identity_sha256": [
            hashlib.sha256(b"annotation-a").hexdigest(),
            hashlib.sha256(b"annotation-b").hexdigest(),
        ],
        "agreement": True,
        "adjudicator_identity_sha256": hashlib.sha256(b"adjudicator-a").hexdigest(),
        "verification_identity_sha256": hashlib.sha256(b"verifier-a").hexdigest(),
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
        "label_provenance": {
            **label_provenance,
            "annotation_identity_sha256": [
                hashlib.sha256(b"annotation-c").hexdigest(),
                hashlib.sha256(b"annotation-d").hexdigest(),
            ],
            "adjudicator_identity_sha256": hashlib.sha256(b"adjudicator-b").hexdigest(),
            "verification_identity_sha256": hashlib.sha256(b"verifier-b").hexdigest(),
        },
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
        "method": "blind_double_annotation",
        "target_sha256": _target_sha256(target),
        "annotation_identity_sha256": [
            hashlib.sha256(b"reviewer-x").hexdigest(),
            hashlib.sha256(b"reviewer-y").hexdigest(),
        ],
        "agreement": True,
        "adjudicator_identity_sha256": hashlib.sha256(b"adjudicator-x").hexdigest(),
        "verification_identity_sha256": hashlib.sha256(b"verifier-x").hexdigest(),
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
