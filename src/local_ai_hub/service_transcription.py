"""Audio transcription service via local Whisper CLI."""

from __future__ import annotations

import json
import shutil
import stat
import subprocess
import sys
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from . import process_utils
from .repository_scope import reject_retired_tenancy_fields
from .whisper_policy import prepare_whisper_model


def _get_shutil(services: Any) -> Any:
    mod = sys.modules.get("local_ai_hub.services")
    if mod and hasattr(mod, "shutil"):
        return mod.shutil
    return getattr(services, "shutil", shutil)


def transcribe(
    services: Any,
    args: dict[str, Any],
    *,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Transcribe audio to text through the local Whisper CLI."""
    if not isinstance(args, dict):
        return {
            "success": False,
            "audio_path": "",
            "model": "base",
            "reason": "invalid_request",
            "terminal": True,
            "retryable": False,
            "error_code": "invalid_request",
            "error": "Audio transcription request must be an object.",
        }

    reject_retired_tenancy_fields(args)
    transcription_config = services.config.get("transcription", {})
    if not isinstance(transcription_config, dict):
        transcription_config = {}
    if transcription_config.get("enabled", True) is False:
        return {
            "success": False,
            "audio_path": "",
            "model": str(args.get("model") or "base"),
            "reason": "transcription_disabled",
            "terminal": True,
            "retryable": False,
            "request_not_sent": True,
            "error": "Audio transcription is disabled by configuration.",
        }
    audio_path = str(args.get("audio", args.get("audio_path", "")))
    model = str(args.get("model") or "base")
    language_arg = args.get("language")
    if language_arg is not None and not isinstance(language_arg, str):
        return {
            "success": False,
            "audio_path": audio_path,
            "model": model,
            "reason": "invalid_language",
            "error": "Language hint must be a string.",
        }
    language = language_arg.strip() if isinstance(language_arg, str) else ""
    if language.casefold() == "auto":
        language = ""

    p = Path(audio_path)
    try:
        p = p.expanduser().resolve(strict=False)
        audio_stat = p.stat()
    except FileNotFoundError:
        return {
            "success": False,
            "audio_path": str(p),
            "model": model,
            "reason": "audio_not_found",
            "error": "Audio file not found.",
        }
    except OSError:
        return {
            "success": False,
            "audio_path": str(p),
            "model": model,
            "reason": "audio_unavailable",
            "degraded": True,
            "error": "Audio path is not accessible.",
        }
    except (RuntimeError, ValueError):
        return {
            "success": False,
            "audio_path": str(p),
            "model": model,
            "reason": "audio_path_invalid",
            "error": "Audio path is invalid.",
        }
    if not stat.S_ISREG(audio_stat.st_mode):
        return {
            "success": False,
            "audio_path": str(p),
            "model": model,
            "reason": "audio_not_regular_file",
            "error": "Audio path does not refer to a regular file.",
        }

    whisper_cmd = _get_shutil(services).which("whisper")
    if not whisper_cmd:
        return {
            "success": False,
            "audio_path": str(p),
            "model": model,
            "engine": "whisper_cli",
            "reason": "cli_missing",
            "degraded": True,
            "error": "Whisper CLI is not installed or unavailable in PATH.",
        }

    policy = prepare_whisper_model(
        model,
        cache_dir=transcription_config.get("cache_dir"),
        allow_downloads=transcription_config.get("allow_model_downloads", False),
        device=transcription_config.get("device", "cpu"),
        cancel_event=cancel_event,
    )
    if not policy.ok:
        return {
            "success": False,
            "audio_path": str(p),
            "model": model,
            "engine": "whisper_cli",
            "reason": policy.reason or "model_unavailable",
            "degraded": policy.reason in {
                "model_missing",
                "model_unavailable",
                "model_corrupt",
                "model_too_large",
                "model_verify_timeout",
            },
            "cancelled": policy.reason == "cancelled",
            "terminal": policy.reason != "model_verify_timeout",
            "retryable": policy.reason == "model_verify_timeout",
            "request_not_sent": True,
            "error": policy.error or "Whisper model policy rejected this request.",
        }

    try:
        with TemporaryDirectory(prefix="local-ai-hub-transcribe-") as output_dir:
            cmd = [
                whisper_cmd,
                str(p),
                "--output_format",
                "json",
                "--model",
                policy.cached_model or model,
                "--model_dir",
                policy.model_dir,
                "--device",
                policy.device,
                "--output_dir",
                output_dir,
            ]
            if language:
                cmd.extend(["--language", language])
            try:
                proc = process_utils.run_hidden(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                    cancel_event=cancel_event,
                    cancel_grace_seconds=1.0,
                )
            except FileNotFoundError:
                return {
                    "success": False,
                    "audio_path": str(p),
                    "model": model,
                    "engine": "whisper_cli",
                    "reason": "cli_missing",
                    "degraded": True,
                    "error": "Whisper CLI became unavailable before it could run.",
                }
            if proc.returncode != 0:
                err_text = str(proc.stderr or "").strip() or f"Whisper CLI exited with status {proc.returncode}."
                return {
                    "success": False,
                    "audio_path": str(p),
                    "model": model,
                    "engine": "whisper_cli",
                    "reason": "process_failed",
                    "returncode": proc.returncode,
                    "error": err_text,
                }

            output_path = Path(output_dir) / f"{p.stem}.json"
            raw_output = (
                output_path.read_text(encoding="utf-8", errors="replace")
                if output_path.is_file()
                else str(proc.stdout or "")
            )
            try:
                result = json.loads(raw_output) if raw_output.strip() else {}
            except (json.JSONDecodeError, TypeError):
                result = {}
            text_value = result.get("text") if isinstance(result, dict) else None
            transcript = text_value.strip() if isinstance(text_value, str) else ""

            def is_audio_decode_skip(value: str) -> bool:
                return any(
                    line.startswith("Skipping ") and " due to RuntimeError:" in line
                    for line in value.splitlines()
                )

            if (
                is_audio_decode_skip(str(proc.stdout or ""))
                or is_audio_decode_skip(str(proc.stderr or ""))
                or is_audio_decode_skip(transcript)
            ):
                return {
                    "success": False,
                    "audio_path": str(p),
                    "model": model,
                    "engine": "whisper_cli",
                    "reason": "invalid_audio",
                    "error": "Whisper CLI could not decode the audio file.",
                }
            if not transcript:
                return {
                    "success": False,
                    "audio_path": str(p),
                    "model": model,
                    "engine": "whisper_cli",
                    "reason": "empty_transcript",
                    "error": "Whisper CLI produced no transcript text.",
                }

            return {
                "success": True,
                "text": transcript,
                "audio_path": str(p),
                "model": model,
                "engine": "whisper_cli",
            }
    except process_utils.ProcessCleanupUnverifiedError:
        raise
    except process_utils.ProcessCancelledError:
        return {
            "success": False,
            "audio_path": str(p),
            "model": model,
            "engine": "whisper_cli",
            "reason": "cancelled",
            "cancelled": True,
            "terminal": True,
            "retryable": False,
            "error": "Whisper CLI was cancelled for resource release.",
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "audio_path": str(p),
            "model": model,
            "engine": "whisper_cli",
            "reason": "timeout",
            "retryable": True,
            "error": "Whisper CLI timed out before transcription completed.",
        }
    except Exception:
        return {
            "success": False,
            "audio_path": str(p),
            "model": model,
            "engine": "whisper_cli",
            "reason": "process_error",
            "error": "Whisper CLI failed before producing a transcript.",
        }
