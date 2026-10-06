from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import local_ai_hub.services as services_module
from local_ai_hub.services import LocalAIServices


def _service() -> LocalAIServices:
    return object.__new__(LocalAIServices)


def test_transcribe_honors_requested_model_and_cleans_task_owned_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"test audio")
    command: list[str] = []
    output_directories: list[Path] = []

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        command.extend(args)
        output_dir = Path(args[args.index("--output_dir") + 1])
        output_directories.append(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{Path(args[1]).stem}.txt").write_text("hello world", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(services_module.shutil, "which", lambda _name: "whisper-cli")
    monkeypatch.setattr(services_module.subprocess, "run", fake_run)

    result = _service().transcribe({"audio": str(audio), "model": "base.en"}, "task-17")

    assert command[command.index("--model") + 1] == "base.en"
    assert output_directories[0] != audio.parent
    assert not output_directories[0].exists()
    assert not audio.with_suffix(".txt").exists()
    assert result["success"] is True
    assert result["model"] == "base.en"
    assert result["text"] == "hello world"


def test_missing_whisper_cli_does_not_report_metadata_as_transcription(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "metadata-only.wav"
    audio.write_bytes(b"not decoded audio")
    monkeypatch.setattr(services_module.shutil, "which", lambda _name: None)

    result = _service().transcribe({"audio": str(audio), "model": "small"}, "task-17")

    assert result["success"] is False
    assert result["reason"] == "cli_missing"
    assert result["engine"] == "whisper_cli"
    assert result["degraded"] is True
    assert not result.get("text")


def test_whisper_binary_removed_after_lookup_reports_cli_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "race.wav"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(services_module.shutil, "which", lambda _name: "whisper")

    def binary_removed(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError(2, "No such file or directory", "whisper")

    monkeypatch.setattr(services_module.subprocess, "run", binary_removed)

    result = _service().transcribe({"audio": str(audio), "model": "small"}, "task-17")

    assert result["success"] is False
    assert result["reason"] == "cli_missing"
    assert result["degraded"] is True
    assert not result.get("text")


@pytest.mark.parametrize(
    "outcome",
    ["nonzero", "timeout"],
)
def test_whisper_process_failure_never_returns_successful_transcript(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    audio = tmp_path / "broken.wav"
    audio.write_bytes(b"invalid audio")

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        output_directories.append(Path(args[args.index("--output_dir") + 1]))
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(args, timeout=60)
        return subprocess.CompletedProcess(args, 2, stdout="", stderr="decoder failed")

    output_directories: list[Path] = []
    monkeypatch.setattr(services_module.shutil, "which", lambda _name: "whisper-cli")
    monkeypatch.setattr(services_module.subprocess, "run", fake_run)

    result = _service().transcribe({"audio": str(audio), "model": "small"}, "task-17")

    assert result["success"] is False
    assert result["reason"] == ("timeout" if outcome == "timeout" else "process_failed")
    assert not result.get("text")
    assert result["error"]
    if outcome == "timeout":
        assert result["retryable"] is True
    else:
        assert result["returncode"] == 2
        assert result["error"] == "decoder failed"
    assert output_directories
    assert not output_directories[0].exists()


def test_empty_whisper_output_is_not_a_successful_transcription(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "silent.wav"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(services_module.shutil, "which", lambda _name: "whisper-cli")
    monkeypatch.setattr(
        services_module.subprocess,
        "run",
        lambda args, **_kwargs: subprocess.CompletedProcess(args, 0, stdout="", stderr=""),
    )

    result = _service().transcribe({"audio": str(audio), "model": "small"}, "task-17")

    assert result["success"] is False
    assert result["reason"] == "empty_transcript"
    assert result["engine"] == "whisper_cli"
    assert result["error"]
    assert not result.get("text")


def test_cancellation_cleans_task_owned_whisper_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "cancelled.wav"
    audio.write_bytes(b"audio")
    output_directories: list[Path] = []

    def cancel(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        output_directories.append(Path(args[args.index("--output_dir") + 1]))
        raise KeyboardInterrupt

    monkeypatch.setattr(services_module.shutil, "which", lambda _name: "whisper-cli")
    monkeypatch.setattr(services_module.subprocess, "run", cancel)

    with pytest.raises(KeyboardInterrupt):
        _service().transcribe({"audio": str(audio), "model": "small"}, "task-17")

    assert output_directories
    assert not output_directories[0].exists()


@pytest.mark.parametrize("requested_model", [None, "whisper"])
def test_generic_whisper_model_uses_valid_tiny_cli_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    requested_model: str | None,
) -> None:
    audio = tmp_path / "default-model.wav"
    audio.write_bytes(b"audio")
    command: list[str] = []

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        command.extend(args)
        return subprocess.CompletedProcess(args, 0, stdout="recognized speech", stderr="")

    monkeypatch.setattr(services_module.shutil, "which", lambda _name: "whisper-cli")
    monkeypatch.setattr(services_module.subprocess, "run", fake_run)
    request: dict[str, str] = {"audio": str(audio)}
    if requested_model is not None:
        request["model"] = requested_model

    result = _service().transcribe(request, "task-17")

    assert command[command.index("--model") + 1] == "tiny"
    assert result["model"] == "whisper"
    assert result["text"] == "recognized speech"


def test_empty_whisper_file_falls_back_to_nonempty_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "stdout-fallback.wav"
    audio.write_bytes(b"audio")

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        output_dir = Path(args[args.index("--output_dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{Path(args[1]).stem}.txt").write_text("", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="recognized from stdout", stderr="")

    monkeypatch.setattr(services_module.shutil, "which", lambda _name: "whisper-cli")
    monkeypatch.setattr(services_module.subprocess, "run", fake_run)

    result = _service().transcribe({"audio": str(audio), "model": "small"}, "task-17")

    assert result["success"] is True
    assert result["text"] == "recognized from stdout"


def test_missing_transcript_file_is_not_misclassified_as_missing_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "read-race.wav"
    audio.write_bytes(b"audio")
    original_read_text = Path.read_text

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        output_dir = Path(args[args.index("--output_dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{Path(args[1]).stem}.txt").write_text("hello", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    def missing_transcript(path: Path, *args: object, **kwargs: object) -> str:
        if path.name == "read-race.txt":
            raise FileNotFoundError(2, "transcript disappeared", str(path))
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(services_module.shutil, "which", lambda _name: "whisper-cli")
    monkeypatch.setattr(services_module.subprocess, "run", fake_run)
    monkeypatch.setattr(Path, "read_text", missing_transcript)

    result = _service().transcribe({"audio": str(audio), "model": "small"}, "task-17")

    assert result["success"] is False
    assert result["reason"] == "process_error"
