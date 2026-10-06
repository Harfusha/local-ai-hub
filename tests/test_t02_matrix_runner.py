from pathlib import Path
import os

import pytest

from tools import run_t02_matrix


def test_acceptance_matrix_covers_six_workloads_times_four_concurrency_levels() -> None:
    cells = run_t02_matrix.expected_cells()

    assert len(cells) == 24
    assert len(set(cells)) == 24
    assert {cell[2] for cell in cells} == {1, 4, 16, 32}
    assert {(cell[0], cell[1]) for cell in cells} == {
        (100, 10_000), (100, 100_000),
        (10_000, 10_000), (10_000, 100_000),
        (100_000, 10_000), (100_000, 100_000),
    }


def test_acceptance_command_is_offline_checkpointed_and_never_infers(tmp_path: Path) -> None:
    command = run_t02_matrix.build_command(
        python="python",
        repository_root=tmp_path / "repo",
        output_dir=tmp_path / "evidence",
        file_count=10_000,
        rag_chunk_count=100_000,
        phase="acceptance",
    )

    assert "--full" in command
    assert "--concurrency" in command
    start = command.index("--concurrency") + 1
    assert command[start:start + 4] == ["1", "4", "16", "32"]
    assert "--checkpoint" in command
    assert "--resume" not in command
    assert "--inference" not in command


def test_resume_skips_only_receipted_completed_workloads() -> None:
    manifest = {
        "cases": {
            "files-100-rag-10000": {"status": "complete", "record_sha256": "a" * 64},
            "files-100-rag-100000": {"status": "complete"},
            "files-10000-rag-10000": {"status": "failed", "record_sha256": "b" * 64},
        }
    }

    assert run_t02_matrix.pending_cases(manifest) == [
        (100, 100_000), (10_000, 10_000),
        (10_000, 100_000), (100_000, 10_000), (100_000, 100_000),
    ]


def test_case_record_requires_each_concurrency_sample_count() -> None:
    record = {
        "success": True,
        "metadata": {
            "synthetic_file_count": 100,
            "rag_chunk_count": 10_000,
            "concurrency": [1, 4, 16, 32],
            "stage_repetitions": {"light": 1_000, "paired": 30},
            "inference": "skipped_not_requested",
        },
        "stages": {
            "hub_queue_admission": {
                "status": "passed",
                "by_concurrency": {
                    str(level): {"count": level * 1_000, "error_count": 0}
                    for level in (1, 4, 16, 32)
                },
            },
        },
    }

    assert run_t02_matrix.validate_case_record(record, 100, 10_000, "acceptance") == []
    del record["stages"]["hub_queue_admission"]["by_concurrency"]["16"]
    assert "concurrency_measurement_missing:16" in run_t02_matrix.validate_case_record(
        record, 100, 10_000, "acceptance"
    )


def test_evidence_directory_must_be_outside_repository(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()

    with pytest.raises(ValueError, match="outside the repository"):
        run_t02_matrix.resolve_external_output(repository / "evidence", repository)


def _complete_record(file_count: int, rag_chunk_count: int) -> dict[str, object]:
    return {
        "success": True,
        "metadata": {
            "synthetic_file_count": file_count,
            "rag_chunk_count": rag_chunk_count,
            "concurrency": [1, 4, 16, 32],
            "stage_repetitions": {"light": 1_000, "paired": 30},
            "inference": "skipped_not_requested",
        },
        "stages": {
            "hub_queue_admission": {
                "status": "passed",
                "by_concurrency": {
                    str(level): {"count": level * 1_000, "error_count": 0}
                    for level in (1, 4, 16, 32)
                }
            }
        },
    }


def test_resume_skips_only_hash_verified_valid_records_inside_output(tmp_path: Path) -> None:
    import hashlib
    import json

    output = tmp_path / "evidence"
    record_path = output / "record.json"
    record_path.parent.mkdir()
    record_path.write_text(json.dumps(_complete_record(100, 10_000)), encoding="utf-8")
    digest = hashlib.sha256(record_path.read_bytes()).hexdigest()
    manifest = {
        "cases": {
            "files-100-rag-10000": {
                "status": "complete", "record_path": str(record_path),
                "record_sha256": digest,
            }
        }
    }

    assert run_t02_matrix._verified_completed_cases(
        manifest, output_dir=output, phase="acceptance"
    ) == {(100, 10_000)}

    record_path.write_text("tampered", encoding="utf-8")
    assert run_t02_matrix._verified_completed_cases(
        manifest, output_dir=output, phase="acceptance"
    ) == set()


def test_case_record_rejects_missing_or_failed_queue_stage() -> None:
    record = _complete_record(100, 10_000)
    del record["stages"]

    errors = run_t02_matrix.validate_case_record(record, 100, 10_000, "acceptance")

    assert "queue_admission_stage_not_passed" in errors
    assert all(f"concurrency_measurement_missing:{level}" in errors for level in (1, 4, 16, 32))


def test_aggregation_reads_six_receipts_and_emits_24_synthetic_cells(tmp_path: Path) -> None:
    import hashlib
    import json

    output = tmp_path / "evidence"
    cases: dict[str, object] = {}
    for file_count, rag_chunk_count in run_t02_matrix.EXPECTED_CASES:
        key = run_t02_matrix.case_key(file_count, rag_chunk_count)
        path = output / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(_complete_record(file_count, rag_chunk_count)).encode("utf-8")
        path.write_bytes(payload)
        cases[key] = {
            "status": "complete", "record_path": str(path),
            "record_sha256": hashlib.sha256(payload).hexdigest(),
            "benchmark_exit_code": 0, "checkpoint_path": None, "checkpoint_sha256": None,
        }

    manifest: dict[str, object] = {"cases": cases}
    aggregate = run_t02_matrix._aggregate_matrix(
        manifest, output_dir=output, phase="acceptance"
    )

    assert aggregate["completed_cell_count"] == 24
    assert aggregate["workload_count"] == 6
    assert aggregate["quality_acceptance"] == "blocked_real_input_evidence"
    assert len(aggregate["cells"]) == 24
    assert manifest["aggregate"]["sha256"]


def test_benchmark_subprocess_environment_forces_offline_mode_and_worktree_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "worktree"
    (repository / "src").mkdir(parents=True)
    monkeypatch.setenv("PYTHONPATH", r"C:\Users\Adam\.local-ai-hub\src")
    environment = run_t02_matrix._offline_environment(repository)

    assert environment["HF_HUB_OFFLINE"] == "1"
    assert environment["TRANSFORMERS_OFFLINE"] == "1"
    assert environment["HF_HUB_DISABLE_TELEMETRY"] == "1"
    assert environment["PYTHONPATH"].split(os.pathsep)[0] == str(repository / "src")


def test_matrix_orchestrator_records_all_cases_and_aggregate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    from types import SimpleNamespace

    repository = tmp_path / "repo"
    output = tmp_path / "evidence"
    repository.mkdir()
    calls: list[list[str]] = []

    def fake_benchmark(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(command)
        file_count = int(command[command.index("--files") + 1])
        rag_chunk_count = int(command[command.index("--rag-chunks") + 1])
        state_dir = Path(command[command.index("--state-dir") + 1])
        checkpoint = Path(command[command.index("--checkpoint") + 1])
        state_dir.mkdir(parents=True, exist_ok=True)
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_text("checkpoint", encoding="utf-8")
        record_path = state_dir / f"{file_count}-{rag_chunk_count}.json"
        record = _complete_record(file_count, rag_chunk_count)
        record["record_path"] = str(record_path)
        record_path.write_text(json.dumps(record), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout=json.dumps(record), stderr="")

    monkeypatch.setattr(run_t02_matrix.subprocess, "run", fake_benchmark)
    result = run_t02_matrix.run_matrix(
        repository_root=repository, output_dir=output, phase="acceptance", python="python"
    )

    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert result["success"] is True
    assert result["completed_cells"] == 24
    assert result["quality_acceptance"] == "blocked_real_input_evidence"
    assert len(calls) == 6
    assert all("--inference" not in command for command in calls)
    assert all(case["command"] and case["checkpoint_sha256"] for case in manifest["cases"].values())
