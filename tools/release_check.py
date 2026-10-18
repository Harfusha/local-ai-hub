from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import struct
import tempfile
import time
import tomllib
import wave
import zlib
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]

_TOP_LEVEL_FORBIDDEN_DIRS = {
    ".agents",
    ".merge-checks",
    "_local_ai_hub_patch",
    ".pytest_cache",
    ".serena",
    ".superpowers",
    ".venv",
    "build",
    "dist",
    "state",
    "tool-envs",
    "wheel-smoke",
    ".worktrees",
}
_FORBIDDEN_DIR_NAMES = {"__pycache__"}
_FORBIDDEN_FILE_NAMES = {"config.toml", ".local-ai-hub.zip", "ORIGINAL_REQUEST.md"}
_FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".sqlite3", ".whl"}
_ALLOWED_RUNTIME_PLACEHOLDERS = {"data/.gitkeep", "generated/.gitkeep"}


def _live_smoke_png() -> bytes:
    """Build a valid tiny RGB PNG without depending on Pillow."""
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    pixels = b"".join(b"\x00" + (b"\xff\x00\x00" * 64) for _ in range(64))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 64, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")


_PREPROCESSING_ONLY_MODELS = {"qwen2.5-coder:0.5b", "qwen2.5-coder:1.5b"}


def _installed_model_names(payload: dict[str, object]) -> set[str] | None:
    inventory = payload.get("data")
    if payload.get("object") != "list" or not isinstance(inventory, list):
        return None
    names: set[str] = set()
    for item in inventory:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip():
            return None
        names.add(item["id"].strip().casefold())
    return names


def _configured_foreground_model(
    status: dict[str, object], inventory: set[str] | None, roles: tuple[str, ...],
) -> tuple[str | None, str]:
    if inventory is None:
        return None, "model_inventory_unavailable"
    models = status.get("models") if isinstance(status.get("models"), dict) else {}
    configured = {
        str(models.get(role) or "").strip()
        for role in roles
        if str(models.get(role) or "").strip()
    }
    configured = {
        model for model in configured
        if model.casefold() not in _PREPROCESSING_ONLY_MODELS
    }
    if not configured:
        return None, "foreground_model_not_configured"
    active = str(
        status.get("active_model")
        or (status.get("scheduler", {}).get("active_model") if isinstance(status.get("scheduler"), dict) else "")
        or ""
    ).strip()
    candidates = ([active] if active in configured else []) + [
        str(models[role]).strip() for role in roles
        if str(models.get(role) or "").strip() in configured
    ]
    for model in dict.fromkeys(candidates):
        if model.casefold() in inventory:
            return model, "available"
    return None, "configured_model_unavailable"


def _reported_route_state(payload: dict[str, object], expected: str) -> str:
    route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
    actual = str(route.get("model") or "").strip()
    if not actual:
        return "model_route_unreported"
    if actual.casefold() in _PREPROCESSING_ONLY_MODELS:
        return "preprocessing_model_routed"
    if actual.casefold() != expected.casefold():
        return "model_route_mismatch"
    return "available"


def _response_text(payload: dict[str, object]) -> str | None:
    value = payload.get("text") or payload.get("summary") or payload.get("response") or payload.get("result")
    if isinstance(value, dict):
        value = value.get("text") or value.get("summary") or value.get("response")
    return value.strip() if isinstance(value, str) else None


def _version_from_init(root: Path) -> str:
    text = (root / "src" / "local_ai_hub" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    if not match:
        raise ValueError("src/local_ai_hub/__init__.py does not define __version__")
    return match.group(1)


_INSTALLED_ENV_DIRS = {".venv", "tool-envs", "state", ".serena", ".agents", ".superpowers", ".worktrees", ".merge-checks"}


def _iter_release_hygiene_violations(
    root: Path, *, post_test: bool = False, allow_installed: bool = False,
    strict_tree: bool = False,
) -> Iterable[str]:
    """Yield working-tree or strict release-tree violations.

    Working-tree and strict-tree checks ignore disposable Python and pytest
    caches; package contents are validated separately during release checks.

    ``post_test`` tolerates only known test/install caches that are expected to be
    cleaned before packaging. Runtime databases, local configuration, generated
    payloads and internal workspace files remain fatal so cleanup cannot mask them.

    ``allow_installed`` additionally allows managed runtime/tool environments
    (``.venv``, ``tool-envs``, ``state``) present in active developer checkouts.
    """
    if strict_tree and (post_test or allow_installed):
        raise ValueError("strict_tree cannot allow test or installed payloads")
    if allow_installed:
        post_test = True

    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        parts = path.relative_to(root).parts
        if ".git" in parts:
            continue
        if (
            "__pycache__" in parts or ".pytest_cache" in parts
            or (path.is_file() and path.suffix in {".pyc", ".pyo"})
        ):
            continue
        if allow_installed:
            if parts and parts[0] in _INSTALLED_ENV_DIRS:
                continue
            if parts and parts[0] in {"generated", "data"}:
                continue
            if path.name in {"config.toml", ".local-ai-hub.zip"}:
                continue
            if ".local-ai-hub-backup-" in path.name:
                continue
            if path.name.startswith("config.toml.bak"):
                continue
        if post_test:
            if ".pytest_cache" in parts or "__pycache__" in parts or any(part.endswith(".egg-info") for part in parts):
                continue
            if path.is_file() and path.name.startswith(".coverage"):
                continue
        if parts and parts[0] in _TOP_LEVEL_FORBIDDEN_DIRS:
            if len(parts) == 1:
                yield f"forbidden directory: {rel}/"
            continue
        if path.is_dir():
            if path.name in _FORBIDDEN_DIR_NAMES or path.name.endswith(".egg-info"):
                yield f"forbidden directory: {rel}/"
            continue
        if any(part in _FORBIDDEN_DIR_NAMES for part in parts):
            yield f"compiled cache payload: {rel}"
            continue
        if rel in _ALLOWED_RUNTIME_PLACEHOLDERS:
            continue
        if parts and parts[0] in {"data", "generated"}:
            yield f"generated/runtime payload: {rel}"
            continue
        if path.name in _FORBIDDEN_FILE_NAMES:
            yield f"local-only file: {rel}"
            continue
        if path.name.startswith("config.toml.bak"):
            yield f"local-only file: {rel}"
            continue
        if path.name.startswith(".coverage"):
            yield f"coverage payload: {rel}"
            continue
        if ".local-ai-hub-backup-" in path.name:
            yield f"backup payload: {rel}"
            continue
        if path.suffix in _FORBIDDEN_SUFFIXES or ".sqlite3-" in path.name:
            yield f"runtime/build payload: {rel}"


def run_checks(root: Path, *, expected_version: str | None = None, post_test: bool = False, allow_installed: bool = False, strict_tree: bool = False) -> dict[str, object]:
    errors: list[str] = []
    checks: list[dict[str, object]] = []

    try:
        pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        package_version = str(pyproject["project"]["version"])
        init_version = _version_from_init(root)
        release = json.loads((root / "RELEASE.json").read_text(encoding="utf-8"))
        release_version = str(release.get("version", ""))
        version_ok = len({package_version, init_version, release_version}) == 1
        checks.append({
            "name": "version-consistency",
            "ok": version_ok,
            "versions": {"pyproject": package_version, "package": init_version, "release": release_version},
        })
        if not version_ok:
            errors.append("version metadata is inconsistent")
        if release.get("status") != "production-ready":
            errors.append("RELEASE.json status must be production-ready")
        if expected_version:
            normalized_expected = str(expected_version).strip()
            if normalized_expected.startswith("v"):
                normalized_expected = normalized_expected[1:]
            expected_ok = normalized_expected == package_version
            checks.append({"name": "expected-version", "ok": expected_ok, "expected": normalized_expected, "actual": package_version})
            if not expected_ok:
                errors.append(f"expected release version {normalized_expected!r}, found {package_version!r}")
    except Exception as exc:
        checks.append({"name": "version-consistency", "ok": False, "error": str(exc)})
        errors.append(f"version metadata check failed: {exc}")
        package_version = ""

    source_defaults = root / "src" / "local_ai_hub" / "defaults.toml"
    root_defaults = root / "defaults.toml"
    defaults_ok = False
    if source_defaults.is_file() and root_defaults.is_file():
        try:
            source_values = tomllib.loads(source_defaults.read_text(encoding="utf-8"))
            packaged_values = tomllib.loads(root_defaults.read_text(encoding="utf-8"))
            defaults_ok = source_values == packaged_values
        except (OSError, UnicodeError, tomllib.TOMLDecodeError):
            defaults_ok = False
    checks.append({"name": "defaults-consistency", "ok": defaults_ok})
    if not defaults_ok:
        errors.append("root defaults.toml and packaged defaults.toml differ")

    manifest = (root / "MANIFEST.in").read_text(encoding="utf-8")
    manifest_ok = (
        "include config.toml\n" not in manifest
        and "include config.toml.example" in manifest
        and "include requirements-openvino.txt" in manifest
    )
    checks.append({"name": "manifest-hygiene", "ok": manifest_ok})
    if not manifest_ok:
        errors.append("MANIFEST.in must ship config.toml.example and requirements-openvino.txt, never local config.toml")

    required_docs = {
        "README.md",
        "LICENSE",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "docs/INSTALLATION.md",
        "docs/CONFIGURATION.md",
        "docs/MCP_AND_AGENTS.md",
        "docs/OPERATIONS.md",
    }
    missing_docs = sorted(item for item in required_docs if not (root / item).is_file())
    checks.append({"name": "public-docs", "ok": not missing_docs, "missing": missing_docs})
    errors.extend(f"missing public release file: {item}" for item in missing_docs)

    hygiene = list(_iter_release_hygiene_violations(
        root, post_test=post_test, allow_installed=allow_installed, strict_tree=strict_tree,
    ))
    checks.append({"name": "workspace-hygiene", "ok": not hygiene, "violations": hygiene})
    errors.extend(hygiene)

    if package_version:
        readme = (root / "README.md").read_text(encoding="utf-8")
        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        docs_version_ok = package_version in readme and re.search(rf"^##\s+{re.escape(package_version)}\b", changelog, re.MULTILINE) is not None
        checks.append({"name": "release-doc-version", "ok": docs_version_ok})
        if not docs_version_ok:
            errors.append(f"README.md/CHANGELOG.md are not aligned to {package_version}")

    return {"success": not errors, "root": str(root), "errors": errors, "checks": checks}


def run_live_smoke(root: Path) -> dict[str, object]:
    """Run bounded production-path checks against the configured live Hub.

    Kept opt-in: packaging checks must remain usable without a running Ollama
    instance, while the release operator can explicitly require live evidence.
    """
    sys.path.insert(0, str(root / "src"))
    from local_ai_hub.client import HubClient

    config = root / "config.toml"
    client = HubClient(config_path=str(config) if config.is_file() else None)
    checks: list[dict[str, object]] = []
    errors: list[str] = []

    try:
        try:
            model_inventory_payload = client.get("/api/models", timeout=10)
        except Exception:
            model_inventory_payload = {}
        installed_models = _installed_model_names(model_inventory_payload)
        checks.append({
            "name": "live-model-inventory", "ok": installed_models is not None,
            "status": "available" if installed_models is not None else "not_verified",
            "model_count": len(installed_models) if installed_models is not None else None,
        })
        if installed_models is None:
            errors.append("live model inventory was not verified")

        health = client.get("/health")
        health_ok = health.get("success") is True and bool(health.get("hub_online"))
        checks.append({"name": "live-health", "ok": health_ok, "version": health.get("version")})
        if not health_ok:
            errors.append("live health check failed")

        status = client.status(detail="brief")
        scheduler = status.get("scheduler") if isinstance(status.get("scheduler"), dict) else {}
        benchmark_model, benchmark_model_state = _configured_foreground_model(
            status, installed_models, ("fast_code", "general", "heavy_code", "reasoning"),
        )
        reasoning_model, reasoning_model_state = _configured_foreground_model(status, installed_models, ("reasoning",))
        dependency_status = status.get("dependency_status") if isinstance(status.get("dependency_status"), dict) else {}
        degraded_dependencies = [
            {
                "service": name,
                "classification": "probe_timeout" if detail.get("reason") == "probe_timeout" else "degraded",
            }
            for name, detail in dependency_status.items()
            if isinstance(detail, dict) and detail.get("degraded") is True
        ]
        status_ok = (
            status.get("success") is True
            and status.get("hub_online") is True
            and status.get("degraded") is not True
        )
        checks.append({
            "name": "live-status", "ok": status_ok, "hub_online": status.get("hub_online"),
            "degraded": bool(status.get("degraded", False)),
            "degraded_dependencies": degraded_dependencies,
        })
        if not status_ok:
            errors.append("live status check failed")

        ollama_ready = status.get("ollama_online") is True
        reason_available = ollama_ready and reasoning_model is not None
        reason = client.post("/api/reason", {
            "task": "Answer with exactly the word READY.",
            "context": "Release smoke test. No repository changes.",
            "max_tokens": 160,
            "delivery": "sync",
            "response_profile": "compact",
        }, timeout=45) if reason_available else {}
        reason_route_state = _reported_route_state(reason, reasoning_model) if reason_available else reasoning_model_state
        reason_text = _response_text(reason)
        model_ok = (
            reason_available and reason.get("success") is True
            and reason_route_state == "available" and reason_text == "READY"
        )
        model_state = (
            "verified" if model_ok
            else "not_verified" if not reason_available or (
                reason.get("success") is True
                and (reason_route_state == "model_route_unreported" or reason_text is None)
            )
            else "failed"
        )
        if model_ok:
            model_classification = "success"
        elif not reason_available:
            model_classification = "ollama_offline" if not ollama_ready else reasoning_model_state
        elif reason.get("success") is not True:
            model_classification = "request_failed"
        elif reason_route_state != "available":
            model_classification = reason_route_state
        elif reason_text is None:
            model_classification = "response_not_available"
        else:
            model_classification = "response_mismatch"
        checks.append({
            "name": "live-model", "ok": model_ok,
            "status": model_state,
            "model": reason.get("model") or reasoning_model,
            "expected_response": "READY",
            "classification": model_classification,
        })
        if not model_ok:
            errors.append("live model smoke failed or was not verified")

        async_job = client.post("/api/async-jobs", {
            "action": "submit", "job_action": "reason",
            "task": "Answer with exactly the word ASYNC_READY.",
            "context": "Release async smoke test.", "max_tokens": 160,
        }, timeout=15) if reason_available else {}
        job_id = str(async_job.get("job_id") or "")
        async_result: dict[str, object] = async_job
        async_wait: dict[str, object] = {}
        if job_id:
            async_wait = client.post("/api/async-jobs", {"action": "wait", "job_id": job_id, "timeout_seconds": 45}, timeout=50)
            async_result = async_wait
            if async_wait.get("terminal") is True and async_wait.get("state") == "done":
                async_result = client.post("/api/async-jobs", {"action": "result", "job_id": job_id}, timeout=15)
        async_payload = async_result.get("result") if isinstance(async_result.get("result"), dict) else async_result
        async_result_verified = (
            async_wait.get("terminal") is True and async_wait.get("state") == "done"
            and async_result.get("terminal") is True and async_result.get("state") == "done"
            and async_result.get("success") is True
        )
        async_route_state = _reported_route_state(async_payload, reasoning_model) if async_result_verified else ""
        async_text = _response_text(async_payload)
        async_ok = (
            reason_available and bool(job_id)
            and async_result_verified
            and async_route_state == "available"
            and async_text == "ASYNC_READY"
        )
        async_terminal_failure = async_wait.get("terminal") is True and async_wait.get("state") != "done"
        async_not_verified = (
            not reason_available
            or bool(job_id) and async_wait.get("terminal") is not True
            or async_wait.get("state") == "done" and not async_result_verified
            or async_result_verified and (
                async_route_state == "model_route_unreported" or async_text is None
            )
        )
        admission = async_job.get("admission") if isinstance(async_job.get("admission"), dict) else {}
        admission_rejected = (
            not job_id
            and async_job.get("state") == "rejected"
            and async_job.get("retryable") is True
            and async_job.get("terminal") is False
        )
        async_blocked = (
            admission_rejected and admission.get("reason") == "resource_pressure"
        )
        async_queue_limited = admission_rejected and admission.get("reason") == "queue_limit"
        if async_ok:
            async_classification = "success"
        elif not reason_available:
            async_classification = "ollama_offline" if not ollama_ready else reasoning_model_state
        elif async_blocked:
            async_classification = "blocked_resource_pressure"
        elif async_queue_limited:
            async_classification = "queue_limit"
        elif not job_id:
            async_classification = "request_failed"
        elif async_wait.get("terminal") is not True:
            async_classification = "async_not_terminal"
        elif async_terminal_failure:
            async_classification = "async_terminal_failure"
        elif not async_result_verified:
            async_classification = "async_result_not_verified"
        elif async_route_state != "available":
            async_classification = async_route_state
        elif async_text is None:
            async_classification = "async_response_not_available"
        else:
            async_classification = "response_mismatch"
        checks.append({
            "name": "live-async-job", "ok": async_ok, "job_id_present": bool(job_id),
            "status": "verified" if async_ok else "not_verified" if async_not_verified else "failed",
            "expected_response": "ASYNC_READY",
            "blocked": async_blocked, "retryable": async_job.get("retryable"),
            "terminal": async_result.get("terminal"),
            "wait_state": async_wait.get("state"),
            "result_state": async_result.get("state"),
            "classification": async_classification,
        })
        if not async_ok:
            errors.append("live async job smoke failed or was not verified")

        hardware = client.get("/api/hardware/gpu")
        hardware_ok = hardware.get("available") is True or hardware.get("available") is False
        checks.append({"name": "live-hardware-probe", "ok": hardware_ok, "backend": hardware.get("backend")})
        if not hardware_ok:
            errors.append("live hardware probe returned an invalid result")

        benchmark_attempted = ollama_ready and benchmark_model is not None
        benchmark = client.post("/api/benchmark/run", {
            "model": benchmark_model, "prompt": "Return a short response.", "num_tokens": 8,
        }, timeout=60) if benchmark_attempted else {}
        benchmark_ok = (
            ollama_ready and benchmark_model is not None
            and benchmark.get("success") is True
            and str(benchmark.get("model") or "").casefold() == benchmark_model.casefold()
        )
        checks.append({
            "name": "live-hardware-benchmark", "ok": benchmark_ok,
            "status": "available" if benchmark_ok else "failed" if benchmark_attempted else "not_verified",
            "model": benchmark.get("model") or benchmark_model,
            "model_state": benchmark_model_state,
            "response_quality": "not_verified",
        })
        if not benchmark_ok:
            errors.append("live hardware benchmark failed or model was not verified")

        vision_model, vision_model_state = _configured_foreground_model(status, installed_models, ("vision",))
        # Valid 64x64 RGB PNG. Tiny malformed fixtures can fail before the model
        # is reached, so keep the release probe independent of image-decoder quirks.
        image_data = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAfElEQVR4nNXOQREAMAjAsK7+PTMRPLhGQd7QJnESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ES53Vg6wNShQF/fRSLfgAAAABJRU5ErkJggg=="
        )
        image_data = _live_smoke_png()
        vision_attempted = ollama_ready and vision_model is not None
        vision = client.post("/api/task/vision", {
            "prompt": "Describe this image briefly.",
            "image": "data:image/png;base64," + base64.b64encode(image_data).decode("ascii"),
            "model": vision_model,
        }, timeout=90) if vision_attempted else {}
        vision_ok = ollama_ready and vision_model is not None and vision.get("success") is True and bool(vision.get("response") or vision.get("review"))
        checks.append({
            "name": "live-vision", "ok": vision_ok,
            "status": "available" if vision_ok else "failed" if vision_attempted else "not_verified",
            "model": vision_model, "model_state": vision_model_state,
        })
        if not vision_ok:
            errors.append("live vision smoke failed")

        with tempfile.TemporaryDirectory(prefix="local-ai-hub-smoke-") as temp_dir:
            audio_path = Path(temp_dir) / "silence.wav"
            with wave.open(str(audio_path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(8000)
                audio.writeframes(b"\0\0" * 800)
            transcription = client.post("/api/task/transcribe", {
                "audio_path": str(audio_path),
            }, timeout=90)
        expected_silence = (
            transcription.get("engine") == "whisper_cli"
            and transcription.get("reason") == "empty_transcript"
            and not str(transcription.get("text") or "").strip()
        )
        transcription_reason = transcription.get("reason")
        transcription_failure_class = (
            transcription_reason
            if isinstance(transcription_reason, str)
            and transcription_reason in {"cli_missing", "process_failed", "invalid_audio"}
            else None
        )
        transcription_failed = transcription_failure_class is not None
        transcribe_ok = not transcription_failed and (
            expected_silence
            or (transcription.get("success") is True and bool(str(transcription.get("text") or "").strip()))
        )
        checks.append({
            "name": "live-transcribe", "ok": transcribe_ok, "engine": transcription.get("engine"),
            "degraded": bool(transcription.get("degraded", False)),
            "classification": (
                "expected_empty_input" if expected_silence and transcribe_ok
                else transcription_failure_class if transcription_failed
                else "success" if transcribe_ok else "request_failed"
            ),
        })
        if not transcribe_ok:
            errors.append("live transcription smoke failed")

        smoke_root = str(root.resolve())
        key = f"release-smoke-{int(time.time())}"
        memory = client.coord("memory_record", root=smoke_root, key=key, value="ok", scope="repository", kind="fact")
        record_id = str((memory.get("record") or {}).get("record_id") or "")
        readback = client.coord("memory_get", root=smoke_root, record_id=record_id, scope="repository")
        memory_ok = memory.get("success") is True and bool(record_id) and readback.get("success") is True and bool(readback.get("record"))
        client.coord("memory_delete", root=smoke_root, record_id=record_id, scope="repository")
        checks.append({"name": "live-agent-state-memory", "ok": memory_ok})
        if not memory_ok:
            errors.append("live Agent OS memory round-trip failed")
    except Exception as exc:
        errors.append(f"live smoke exception: {type(exc).__name__}")

    return {"success": not errors, "checks": checks, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate that a Local AI Hub checkout is safe to package/release.")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (defaults to this checkout)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--expected-version", default=None, help="require package metadata to match this version (leading v is accepted)")
    parser.add_argument("--post-test", action="store_true", help="allow only known test/install caches while still rejecting runtime side effects")
    parser.add_argument("--allow-installed", action="store_true", help="allow managed tool environments (.venv, tool-envs, state) in live checkouts")
    parser.add_argument("--strict-tree", action="store_true", help="reject generated caches when validating a clean release tree")
    parser.add_argument("--live-smoke", action="store_true", help="also require bounded live Hub, model, async-job and Agent OS evidence")
    args = parser.parse_args(argv)
    if args.strict_tree and (args.post_test or args.allow_installed):
        parser.error("--strict-tree cannot be combined with --post-test or --allow-installed")
    root = args.root.expanduser().resolve()
    result = run_checks(root, expected_version=args.expected_version, post_test=args.post_test, allow_installed=args.allow_installed, strict_tree=args.strict_tree)
    if args.live_smoke:
        live = run_live_smoke(root)
        result["live_smoke"] = live
        result["checks"] = [*result["checks"], *live["checks"]]
        result["errors"] = [*result["errors"], *live["errors"]]
        result["success"] = not result["errors"]
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["success"]:
        print("release-check: OK")
    else:
        print("release-check: FAILED", file=sys.stderr)
        for error in result["errors"]:
            print(f"- {error}", file=sys.stderr)
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
