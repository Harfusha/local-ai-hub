from __future__ import annotations

import hashlib
import json
import subprocess
import threading
from pathlib import Path

import pytest

from local_ai_hub import process_utils, whisper_policy
from local_ai_hub.services import LocalAIServices


def _service() -> LocalAIServices:
    service = object.__new__(LocalAIServices)
    service.config = {"transcription": {"allow_model_downloads": False, "device": "cpu"}}
    return service


@pytest.fixture(autouse=True)
def _verified_whisper_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Exercise real cache verification with task-owned bytes, never user models."""
    cache_dir = tmp_path / "whisper-cache"
    cache_dir.mkdir()
    model_bytes = b"isolated transcription contract model fixture"
    digest = hashlib.sha256(model_bytes).hexdigest()
    for model, filename in whisper_policy.MODEL_FILENAMES.items():
        (cache_dir / filename).write_bytes(model_bytes)
        monkeypatch.setitem(whisper_policy.MODEL_SHA256, model, digest)
    monkeypatch.setattr(whisper_policy, "default_cache_dir", lambda: cache_dir)
    return cache_dir


@pytest.mark.parametrize("payload", [None, [], "malformed"])
def test_transcribe_rejects_non_object_request_payload(payload: object) -> None:
    result = _service().transcribe(payload, "task-17")

    assert result["success"] is False
    assert result["reason"] == "invalid_request"
    assert result["terminal"] is True
    assert result["retryable"] is False


def test_transcribe_honors_requested_model_and_cleans_task_owned_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _verified_whisper_cache: Path
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
        (output_dir / f"{Path(args[1]).stem}.json").write_text(
            json.dumps({"text": " hello world ", "segments": [{"text": "metadata leak"}]}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("local_ai_hub.services.shutil.which", lambda _name: "whisper-cli")
    monkeypatch.setattr(process_utils, "run_hidden", fake_run)

    result = _service().transcribe({"audio": str(audio), "model": "base.en"}, "task-17")

    assert command[command.index("--model") + 1] == str(_verified_whisper_cache / "base.en.pt")
    assert command[command.index("--model_dir") + 1] == str(_verified_whisper_cache)
    assert output_directories[0] != audio.parent
    assert not output_directories[0].exists()
    assert not audio.with_suffix(".json").exists()
    assert result["success"] is True
    assert result["model"] == "base.en"
    assert result["text"] == "hello world"


def test_transcribe_defaults_to_base_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _verified_whisper_cache: Path
) -> None:
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"test audio")
    command: list[str] = []

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        command.extend(args)
        output_dir = Path(args[args.index("--output_dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{Path(args[1]).stem}.json").write_text(
            json.dumps({"text": "hello world"}), encoding="utf-8"
        )
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("local_ai_hub.services.shutil.which", lambda _name: "whisper-cli")
    monkeypatch.setattr(process_utils, "run_hidden", fake_run)

    result = _service().transcribe({"audio": str(audio)}, "task-17")

    assert command[command.index("--model") + 1] == str(_verified_whisper_cache / "base.pt")
    assert command[command.index("--model_dir") + 1] == str(_verified_whisper_cache)
    assert result["success"] is True
    assert result["model"] == "base"


def test_transcribe_forwards_explicit_language_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "czech.wav"
    audio.write_bytes(b"test audio")
    command: list[str] = []

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        command.extend(args)
        output_dir = Path(args[args.index("--output_dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{Path(args[1]).stem}.json").write_text(
            json.dumps({"text": "ahoj světe"}), encoding="utf-8"
        )
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("local_ai_hub.services.shutil.which", lambda _name: "whisper-cli")
    monkeypatch.setattr(process_utils, "run_hidden", fake_run)

    result = _service().transcribe(
        {"audio": str(audio), "model": "base", "language": "cs"}, "task-17"
    )

    assert result["success"] is True
    assert command[command.index("--language") + 1] == "cs"


def test_transcribe_auto_language_keeps_whisper_autodetection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "auto-language.wav"
    audio.write_bytes(b"test audio")
    command: list[str] = []

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        command.extend(args)
        output_dir = Path(args[args.index("--output_dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{audio.stem}.json").write_text(
            json.dumps({"text": "recognized"}), encoding="utf-8"
        )
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("local_ai_hub.services.shutil.which", lambda _name: "whisper-cli")
    monkeypatch.setattr(process_utils, "run_hidden", fake_run)

    result = _service().transcribe(
        {"audio": str(audio), "language": " AUTO "}, "task-17"
    )

    assert "--language" not in command
    assert result["success"] is True


def test_transcribe_rejects_non_string_language_hint_before_running_whisper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("Whisper must not run for an invalid language hint")

    monkeypatch.setattr(process_utils, "run_hidden", unexpected_run)

    result = _service().transcribe(
        {"audio": str(tmp_path / "missing.wav"), "language": 42}, "task-17"
    )

    assert result["success"] is False
    assert result["reason"] == "invalid_language"
    assert not result.get("text")


def test_missing_whisper_cli_does_not_report_metadata_as_transcription(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "metadata-only.wav"
    audio.write_bytes(b"not decoded audio")
    monkeypatch.setattr("local_ai_hub.services.shutil.which", lambda _name: None)

    result = _service().transcribe({"audio": str(audio), "model": "small"}, "task-17")

    assert result["success"] is False
    assert result["reason"] == "cli_missing"
    assert result["engine"] == "whisper_cli"
    assert result["degraded"] is True
    assert not result.get("text")


def test_missing_output_after_cli_success_is_not_reported_as_missing_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "output-race.wav"
    audio.write_bytes(b"test audio")

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        output_dir = Path(args[args.index("--output_dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{audio.stem}.json").write_text('{"text":"valid"}', encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    original_read_text = Path.read_text

    def missing_output(path: Path, *args: object, **kwargs: object) -> str:
        if path.suffix == ".json":
            raise FileNotFoundError(path)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr("local_ai_hub.services.shutil.which", lambda _name: "whisper-cli")
    monkeypatch.setattr(process_utils, "run_hidden", fake_run)
    monkeypatch.setattr(Path, "read_text", missing_output)

    result = _service().transcribe({"audio": str(audio)}, "task-17")

    assert result["success"] is False
    assert result["reason"] == "process_error"




def test_audio_directory_is_not_reported_as_missing_file_preserved_checkpoint_1(tmp_path: Path) -> None:
    result = _service().transcribe({"audio": str(tmp_path), "model": "small"}, "task-17")

    assert result["success"] is False
    assert result["reason"] == "audio_not_regular_file"
    assert not result.get("text")



















def test_missing_audio_has_machine_readable_failure_reason(tmp_path: Path) -> None:
    missing_audio = tmp_path / "missing.wav"

    result = _service().transcribe({"audio": str(missing_audio), "model": "small"}, "task-17")

    assert result["success"] is False
    assert result["reason"] == "audio_not_found"
    assert result["audio_path"] == str(missing_audio.resolve())
    assert not result.get("text")


def test_audio_directory_is_not_reported_as_missing_file(tmp_path: Path) -> None:
    result = _service().transcribe({"audio": str(tmp_path), "model": "small"}, "task-17")

    assert result["success"] is False
    assert result["reason"] == "audio_not_regular_file"


def test_transcribe_reports_cancellation_after_owned_output_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"test audio")
    output_directories: list[Path] = []
    cancel_event = threading.Event()
    cancel_event.set()

    def cancelled_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        output_directories.append(Path(args[args.index("--output_dir") + 1]))
        assert kwargs["cancel_event"] is cancel_event
        raise process_utils.ProcessCancelledError(args)

    monkeypatch.setattr("local_ai_hub.services.shutil.which", lambda _name: "whisper-cli")
    monkeypatch.setattr(process_utils, "run_hidden", cancelled_run)

    result = _service().transcribe({"audio": str(audio)}, "task-17", cancel_event=cancel_event)

    assert result["success"] is False
    assert result["reason"] == "cancelled"
    assert result["cancelled"] is True
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert output_directories and not output_directories[0].exists()
    assert not result.get("text")


def test_transcribe_cancellation_waits_for_worker_and_model_release_before_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"test audio")
    cancel_event = threading.Event()
    worker_started = threading.Event()
    worker_cancelled = threading.Event()
    allow_worker_exit = threading.Event()
    model_released = threading.Event()
    request_finished = threading.Event()
    output_directories: list[Path] = []
    results: list[dict[str, object]] = []

    def fake_worker() -> None:
        try:
            worker_started.set()
            assert cancel_event.wait(timeout=3)
            worker_cancelled.set()
            assert allow_worker_exit.wait(timeout=3)
        finally:
            model_released.set()

    def wait_for_worker(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert kwargs["cancel_event"] is cancel_event
        output_dir = Path(args[args.index("--output_dir") + 1])
        output_directories.append(output_dir)
        worker = threading.Thread(target=fake_worker, daemon=True)
        worker.start()
        assert worker_cancelled.wait(timeout=3)
        worker.join(timeout=3)
        assert not worker.is_alive()
        raise process_utils.ProcessCancelledError(args)

    monkeypatch.setattr("local_ai_hub.services.shutil.which", lambda _name: "whisper-cli")
    monkeypatch.setattr(process_utils, "run_hidden", wait_for_worker)

    def transcribe() -> None:
        results.append(_service().transcribe({"audio": str(audio)}, "task-17", cancel_event=cancel_event))
        request_finished.set()

    request = threading.Thread(target=transcribe, daemon=True)
    request.start()
    try:
        assert worker_started.wait(timeout=3)
        assert output_directories and output_directories[0].exists()
        cancel_event.set()
        assert worker_cancelled.wait(timeout=3)
        assert request_finished.wait(timeout=0.05) is False
        assert model_released.is_set() is False
        assert output_directories[0].exists()
        allow_worker_exit.set()
        request.join(timeout=3)
    finally:
        cancel_event.set()
        allow_worker_exit.set()
        request.join(timeout=3)

    assert not request.is_alive()
    assert request_finished.is_set()
    assert model_released.is_set()
    assert results[0]["reason"] == "cancelled"
    assert output_directories and not output_directories[0].exists()


def test_unreadable_audio_has_degraded_unavailable_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "private.wav"
    audio.write_bytes(b"audio")
    real_stat = Path.stat

    def deny_audio_stat(path: Path, *args: object, **kwargs: object):
        if path == audio.resolve():
            raise PermissionError("access denied")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", deny_audio_stat)

    result = _service().transcribe({"audio": str(audio), "model": "small"}, "task-17")

    assert result["success"] is False
    assert result["reason"] == "audio_unavailable"
    assert result["degraded"] is True
    assert not result.get("text")


def test_audio_resolution_failure_has_invalid_path_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "loop.wav"
    real_resolve = Path.resolve

    def fail_audio_resolution(path: Path, *args: object, **kwargs: object) -> Path:
        if path == audio:
            raise RuntimeError("symlink loop")
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", fail_audio_resolution)

    result = _service().transcribe({"audio": str(audio), "model": "small"}, "task-17")

    assert result["success"] is False
    assert result["reason"] == "audio_path_invalid"
    assert not result.get("text")


def test_whisper_binary_removed_after_lookup_reports_cli_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "race.wav"
    audio.write_bytes(b"audio")
    monkeypatch.setattr("local_ai_hub.services.shutil.which", lambda _name: "whisper")

    def binary_removed(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError(2, "No such file or directory", "whisper")

    monkeypatch.setattr(process_utils, "run_hidden", binary_removed)

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
    output_directories: list[Path] = []
    runner_kwargs: list[dict[str, object]] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        output_directories.append(Path(args[args.index("--output_dir") + 1]))
        runner_kwargs.append(kwargs)
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(args, timeout=60)
        return subprocess.CompletedProcess(args, 2, stdout="", stderr="decoder failed")

    monkeypatch.setattr("local_ai_hub.services.shutil.which", lambda _name: "whisper-cli")
    monkeypatch.setattr(process_utils, "run_hidden", fake_run)

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
    assert runner_kwargs[0]["timeout"] == 60
    assert output_directories
    assert not output_directories[0].exists()


def test_unexpected_whisper_error_uses_process_error_and_cleans_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "process-error.wav"
    audio.write_bytes(b"audio")
    output_directories: list[Path] = []

    def fail_unexpectedly(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        output_directories.append(Path(args[args.index("--output_dir") + 1]))
        raise RuntimeError("unexpected process failure")

    monkeypatch.setattr("local_ai_hub.services.shutil.which", lambda _name: "whisper-cli")
    monkeypatch.setattr(process_utils, "run_hidden", fail_unexpectedly)

    result = _service().transcribe({"audio": str(audio), "model": "small"}, "task-17")

    assert result["success"] is False
    assert result["reason"] == "process_error"
    assert not result.get("text")
    assert output_directories
    assert not output_directories[0].exists()


def test_empty_whisper_output_is_not_a_successful_transcription(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "silent.wav"
    audio.write_bytes(b"audio")
    monkeypatch.setattr("local_ai_hub.services.shutil.which", lambda _name: "whisper-cli")
    monkeypatch.setattr(
        process_utils,
        "run_hidden",
        lambda args, **_kwargs: subprocess.CompletedProcess(args, 0, stdout="", stderr=""),
    )

    result = _service().transcribe({"audio": str(audio), "model": "small"}, "task-17")

    assert result["success"] is False
    assert result["reason"] == "empty_transcript"
    assert result["engine"] == "whisper_cli"
    assert result["error"]
    assert not result.get("text")


def test_whisper_decode_skip_does_not_report_successful_transcription_preserved_checkpoint_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "invalid.wav"
    audio.write_bytes(b"not a RIFF WAV file")
    monkeypatch.setattr("local_ai_hub.services.shutil.which", lambda _name: "whisper-cli")
    monkeypatch.setattr(
        process_utils,
        "run_hidden",
        lambda args, **_kwargs: subprocess.CompletedProcess(
            args,
            0,
            stdout=f"Skipping {audio} due to RuntimeError: Failed to load audio: invalid data",
            stderr="",
        ),
    )

    result = _service().transcribe({"audio": str(audio), "model": "base"}, "task-17")

    assert result["success"] is False
    assert result["reason"] == "invalid_audio"
    assert not result.get("text")








@pytest.mark.parametrize("output_stream", ["stdout", "stderr"])
def test_whisper_decode_skip_does_not_report_successful_transcription(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output_stream: str
) -> None:
    audio = tmp_path / "invalid.wav"
    audio.write_bytes(b"not a RIFF WAV file")
    monkeypatch.setattr("local_ai_hub.services.shutil.which", lambda _name: "whisper-cli")

    def whisper_skip(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        output_dir = Path(args[args.index("--output_dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{audio.stem}.json").write_text(
            json.dumps({"text": "transcript that must be discarded"}), encoding="utf-8"
        )
        notice = f"Skipping {audio} due to RuntimeError: Failed to load audio: invalid data"
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=notice if output_stream == "stdout" else "",
            stderr=notice if output_stream == "stderr" else "",
        )

    monkeypatch.setattr(process_utils, "run_hidden", whisper_skip)

    result = _service().transcribe({"audio": str(audio), "model": "base"}, "task-17")

    assert result["success"] is False
    assert result["reason"] == "invalid_audio"
    assert not result.get("text")


def test_malformed_whisper_json_is_not_a_successful_transcription(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "malformed.wav"
    audio.write_bytes(b"audio")

    def malformed_output(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        output_dir = Path(args[args.index("--output_dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{Path(args[1]).stem}.json").write_text("{invalid json", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("local_ai_hub.services.shutil.which", lambda _name: "whisper-cli")
    monkeypatch.setattr(process_utils, "run_hidden", malformed_output)

    result = _service().transcribe({"audio": str(audio), "model": "small"}, "task-17")

    assert result["success"] is False
    assert result["reason"] == "empty_transcript"
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

    monkeypatch.setattr("local_ai_hub.services.shutil.which", lambda _name: "whisper-cli")
    monkeypatch.setattr(process_utils, "run_hidden", cancel)

    with pytest.raises(KeyboardInterrupt):
        _service().transcribe({"audio": str(audio), "model": "small"}, "task-17")

    assert output_directories
    assert not output_directories[0].exists()


def test_http_transcribe_route_preserves_requested_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import threading
    import urllib.request

    from local_ai_hub.app import LocalAIApp
    from local_ai_hub import http_server

    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                '[server]',
                'bind = "127.0.0.1"',
                'port = 11436',
                f'state_dir = "{(tmp_path / "state").as_posix()}"',
            ]
        ),
        encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(
        app.services,
        "transcribe",
        lambda payload, tenant, **_kwargs: {
            "success": False,
            "model": payload.get("model"),
            "language": payload.get("language"),
            "audio_path": payload.get("audio_path"),
            "tenant": tenant,
        },
    )
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request_id = "t17-transcribe-route-request"
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/task/transcribe",
            data=json.dumps(
                {"audio_path": "/fixture/sample.wav", "model": "base.en", "language": "cs"}
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-LocalAI-Request-ID": request_id,
            },
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            result = json.loads(response.read().decode("utf-8"))
        assert result == {
            "success": False,
            "request_id": request_id,
            "model": "base.en",
            "language": "cs",
            "audio_path": "/fixture/sample.wav",
            "tenant": "http-default",
        }
    finally:
        server.shutdown()
        server.server_close()
        app.close()


def test_whisper_decode_skip_stderr_does_not_report_successful_transcription(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "invalid.wav"
    audio.write_bytes(b"not a RIFF WAV file")
    monkeypatch.setattr("local_ai_hub.services.shutil.which", lambda _name: "whisper-cli")

    def whisper_skip(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        output_dir = Path(args[args.index("--output_dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{audio.stem}.json").write_text(
            json.dumps({"text": "transcript that must be discarded"}), encoding="utf-8"
        )
        notice = f"Skipping {audio} due to RuntimeError: Failed to load audio: invalid data"
        return subprocess.CompletedProcess(args, 0, stdout="", stderr=notice)

    monkeypatch.setattr(process_utils, "run_hidden", whisper_skip)
    result = _service().transcribe({"audio": str(audio), "model": "base"}, "task-17")

    assert result["success"] is False
    assert result["reason"] == "invalid_audio"
    assert not result.get("text")
