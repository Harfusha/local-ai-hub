"""Code assistance services: compression, FIM code completion, test generation, and patch validation."""

from __future__ import annotations

import copy
import json
import re
import subprocess
import threading
from pathlib import Path
from typing import Any

from .budget import chars_for_tokens, estimate_tokens
from .cache import stable_hash
from .process_utils import hidden_run_kwargs
from .prompt_contracts import build_prompt
from .repository_scope import reject_retired_tenancy_fields
from .trace_context import observer


def compress(
    services: Any,
    args: dict[str, Any],
    *,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    reject_retired_tenancy_fields(args)
    def cancelled() -> dict[str, Any]:
        return {"success": False, "cancelled": True, "reason": "cancelled", "terminal": True, "retryable": False}

    if cancel_event is not None and cancel_event.is_set():
        return cancelled()
    text = str(args.get("text", ""))
    instruction = str(args.get("instruction", "Compress this while preserving facts, identifiers, numbers, decisions, errors and uncertainty."))
    target_tokens = max(128, int(args.get("target_tokens", 900)))
    if not text.strip():
        return {"success": True, "text": "", "input_tokens": 0}

    # Local AI deterministic compressor handles logs/repetitive diagnostics without
    # spending any local-model inference. Narrative text falls through to Ollama.
    if services.deterministic is not None and bool(services.config.get("deterministic", {}).get("compression", True)):
        try:
            det = services.deterministic.compress_text(text, target_tokens)
        except Exception:
            det = {"success": False}
        if cancel_event is not None and cancel_event.is_set():
            return cancelled()
        if det.get("success") and float(det.get("confidence", 0.0)) >= float(services.config.get("deterministic", {}).get("compression_confidence", 0.88)):
            det["compression"] = {
                "input_tokens_est": estimate_tokens(text),
                "output_tokens_est": estimate_tokens(str(det.get("text", ""))),
                "chunks": 0, "method": "deterministic-script", "ollama_calls": 0,
            }
            return det

    chunk_tokens = int(services.config.get("token_saving", {}).get("compression_chunk_tokens", 4800))
    chunk_chars = chars_for_tokens(chunk_tokens)
    chunks = [text[i:i + chunk_chars] for i in range(0, len(text), chunk_chars)]
    summaries: list[str] = []
    per_chunk_out = max(180, min(700, target_tokens // max(1, len(chunks)) + 120))
    models = services.config.get("models", {})
    models = models if isinstance(models, dict) else {}
    general_model = str(models.get("general", models.get("fast_code", "qwen2.5-coder:7b")))
    requested_role = args.get("model_role")
    requested_model = args.get("model")
    if requested_role is not None and requested_model not in (None, ""):
        return {
            "success": False, "status_code": 400, "terminal": True, "retryable": False,
            "error": "compress accepts only one of model_role or model",
        }
    if requested_role is not None:
        if type(requested_role) is not str or requested_role not in {"fast_code", "general"}:
            return {
                "success": False, "status_code": 400, "terminal": True, "retryable": False,
                "error": "compress model_role must be fast_code or general",
            }
        selected_model = models.get(requested_role)
        if type(selected_model) is not str or not selected_model.strip():
            return {
                "success": False, "status_code": 400, "terminal": True, "retryable": False,
                "error": f"compress model_role {requested_role!r} is not configured",
            }
        general_model = selected_model
    elif requested_model not in (None, ""):
        configured_models = {
            configured
            for configured in models.values()
            if type(configured) is str and configured.strip()
        }
        if type(requested_model) is not str or requested_model not in configured_models:
            return {
                "success": False, "status_code": 400, "terminal": True, "retryable": False,
                "error": "compress model must match a configured model",
            }
        general_model = requested_model
    for index, chunk in enumerate(chunks):
        if cancel_event is not None and cancel_event.is_set():
            return cancelled()
        package = build_prompt(
            operation="compress",
            model=general_model,
            profile=str(getattr(services, "config", {}).get("_hardware", {}).get("profile", "auto")),
            task=f"{instruction}\nChunk {index + 1}/{len(chunks)}",
            context=chunk,
        )
        result = services._generate(
            general_model, package.user,
            package.system,
            per_chunk_out, 0.1, source="compress:map", priority=int(args.get("priority", 4)),
            internal=True,
            **({"cancel_event": cancel_event} if cancel_event is not None else {}),
        )
        if not result.get("success"):
            return result
        summaries.append(str(result.get("text", "")))

    combined = "\n\n".join(summaries)
    if cancel_event is not None and cancel_event.is_set():
        return cancelled()
    if len(chunks) > 1 or estimate_tokens(combined) > target_tokens:
        package = build_prompt(
            operation="compress",
            model=general_model,
            profile=str(getattr(services, "config", {}).get("_hardware", {}).get("profile", "auto")),
            task=f"{instruction}\nTarget: <= {target_tokens} estimated tokens.",
            context=combined,
        )
        final = services._generate(
            general_model,
            package.user,
            package.system,
            target_tokens, 0.1, source="compress:reduce", priority=int(args.get("priority", 4)),
            internal=True,
            **({"cancel_event": cancel_event} if cancel_event is not None else {}),
        )
    else:
        final = {"success": True, "model": general_model, "text": combined}
    if final.get("cancelled") is True or (cancel_event is not None and cancel_event.is_set()):
        return final if final.get("cancelled") is True else cancelled()
    final["compression"] = {
        "input_tokens_est": estimate_tokens(text),
        "output_tokens_est": estimate_tokens(str(final.get("text", ""))),
        "chunks": len(chunks),
    }
    return services.artifacts.compact(final, kind="compress")


def complete_code(
    services: Any,
    args: dict[str, Any],
    *,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Low-latency FIM (Fill-In-The-Middle) code completion for tab auto-complete."""
    reject_retired_tenancy_fields(args)
    if cancel_event is not None and cancel_event.is_set():
        return {"success": False, "cancelled": True, "reason": "cancelled", "validated": False}
    prefix = str(args.get("prefix", ""))
    suffix = str(args.get("suffix", ""))
    max_tokens = min(256, max(8, int(args.get("max_tokens", 80))))
    model = str(services.config.get("models", {}).get("fast_code", "qwen2.5-coder:3b"))
    request_timeout = max(6.0, min(30.0, max_tokens / 4))

    # Standard Qwen FIM prompt template
    prompt = f"<|fim_prefix|>{prefix[-3000:]}<|fim_suffix|>{suffix[:1500]}<|fim_middle|>"
    payload = {
        "model": model,
        "prompt": prompt,
        "raw": True,
        "stream": False,
        "options": {
            "num_predict": max_tokens,
            "temperature": 0.0,
            "stop": ["<|fim_prefix|>", "<|fim_suffix|>", "<|fim_middle|>", "<|endoftext|>", "<|file_separator|>"],
        },
    }
    cache_key = stable_hash({"complete_code": True, "model": model, "prompt": prompt, "max_tokens": max_tokens})
    def compute() -> dict[str, Any]:
        def execute() -> dict[str, Any]:
            trace_observer = observer()
            if trace_observer is not None:
                trace_observer.model_request(payload)
            if cancel_event is not None:
                result = services.runtime.request_interruptible("/api/generate", payload, should_stop=cancel_event.is_set, timeout=request_timeout)
            else:
                result = services.runtime.request("/api/generate", payload, timeout=request_timeout)
            if trace_observer is not None and isinstance(result, dict):
                output = result.get("response")
                if isinstance(output, str):
                    trace_observer.output_delta(output)
            return result
        res = services.scheduler.submit(model, source="complete_code", execute=execute,
                                        **({"cancel_event": cancel_event} if cancel_event is not None else {}))
        if cancel_event is not None and cancel_event.is_set():
            return {"success": False, "cancelled": True, "reason": "cancelled", "validated": False}
        if isinstance(res, dict) and res.get("_lah_repetition_loop_detected"):
            failure = {
                "success": False,
                "error": str(res.get("error") or "model output repetition loop detected"),
                "error_code": "model_repetition_loop",
                "model": str(res.get("model") or model),
                "validated": False,
                "terminal": True,
                "retryable": False,
                "repetition_loop_detected": True,
                "retry_count": int(res.get("_lah_retry_count", 0) or 0),
            }
            if res.get("outcome_unknown") is True:
                failure["outcome_unknown"] = True
            return failure
        if isinstance(res, dict) and "error" in res:
            failure = {"success": False, "error": res["error"], "validated": False}
            for key in (
                "error_code", "terminal", "retryable", "timed_out", "outcome_unknown",
                "cleanup_unconfirmed", "preempted", "cancelled", "_lah_partial_response",
                "operation_not_started", "output_truncated", "stop_reason",
            ):
                if key in res:
                    failure[key] = res[key]
            if res.get("_lah_partial_response") is True:
                failure["partial"] = True
            return failure
        if isinstance(res, dict) and res.get("done_reason") == "length":
            partial_completion = res.get("response")
            return {
                "success": False,
                "error": "local model output reached its token limit",
                "error_code": "model_output_truncated",
                "model": model,
                "validated": False,
                "output_truncated": True,
                "stop_reason": "length",
                "final_response_produced": (
                    isinstance(partial_completion, str) and bool(partial_completion.strip())
                ),
                "final_response_status": "truncated",
                "terminal": True,
                "retryable": False,
            }
        response_value = res.get("response") if isinstance(res, dict) else None
        if not isinstance(response_value, str) or not response_value.strip():
            return {
                "success": False,
                "error": "Model returned an empty completion.",
                "validated": False,
            }
        return {
            "success": True,
            "model": model,
            "completion": response_value,
            "validated": False,
        }
    if cancel_event is not None:
        raw, hit, coalesced = compute(), False, False
    else:
        raw, hit, coalesced = services.generation_cache.get_or_compute(cache_key, compute)
    if cancel_event is not None and cancel_event.is_set():
        return {"success": False, "cancelled": True, "reason": "cancelled", "validated": False}
    result = copy.deepcopy(raw)
    result["cache_hit"] = hit or coalesced
    return result


def generate_tests(
    services: Any,
    payload: dict[str, Any],
    *,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Generate complete unit test code for a symbol or file."""
    reject_retired_tenancy_fields(payload)
    if cancel_event is not None and cancel_event.is_set():
        return {"success": False, "cancelled": True, "reason": "cancelled"}
    symbol = str(payload.get("symbol", ""))
    code_context = str(payload.get("code", ""))
    framework = str(payload.get("framework", "auto")).lower()
    path = str(payload.get("path", payload.get("file", "")))
    root = str(payload.get("root", "."))

    if not code_context and symbol and services.code_index is not None:
        try:
            sym_info = services.code_index.inspect_symbol(root, symbol)
            if sym_info.get("success"):
                code_context = sym_info.get("snippet", "")
                if not path:
                    path = sym_info.get("path", "")
        except Exception:
            pass

    if not framework or framework == "auto":
        if path.endswith(".cs"):
            framework = "nunit"
        elif path.endswith(".py"):
            framework = "pytest"
        elif path.endswith((".ts", ".js", ".tsx", ".jsx")):
            framework = "jest"
        else:
            framework = "pytest"

    if cancel_event is not None and cancel_event.is_set():
        return {"success": False, "cancelled": True, "reason": "cancelled"}
    if payload.get("fast_scaffold") or payload.get("template_only") or payload.get("deterministic"):
        clean_sym = re.sub(r"[^A-Za-z0-9_]", "_", symbol) or "target"
        pending_reason = "Replace scaffold with behavior-based assertions before enabling this test."
        if framework == "pytest":
            scaffold = (
                "import pytest\n\n"
                f"@pytest.mark.skip(reason={json.dumps(pending_reason, separators=(',', ':'))})\n"
                f"def test_{clean_sym}_basic():\n"
                f"    \"\"\"Unit test scaffold for {clean_sym}.\"\"\"\n"
                f"    # TODO: instantiate and verify {clean_sym} behavior\n"
                "    assert True\n"
            )
        elif framework == "jest":
            scaffold = (
                f"describe('{clean_sym}', () => {{\n"
                f"    it.skip('basic behavior', () => {{\n"
                f"        // TODO: test {clean_sym}\n"
                "        expect(true).toBe(true);\n"
                "    });\n"
                "});\n"
            )
        else:
            scaffold = (
                "using NUnit.Framework;\n\n"
                "[TestFixture]\n"
                f"public class {clean_sym}Tests {{\n"
                f"    [Test, Ignore({json.dumps(pending_reason, separators=(',', ':'))})]\n"
                "    public void Test_Basic() {\n"
                "        Assert.Pass();\n"
                "    }\n"
                "}\n"
            )
        return {
            "success": True,
            "framework": framework,
            "test_code": scaffold,
            "method": "template-scaffold",
            "symbol": symbol,
            "path": path,
        }

    prompt = (
        f"Generate idiomatic, self-contained unit tests using {framework} for this code:\n\n"
        f"File: {path}\nSymbol: {symbol}\n\n```\n{code_context[:3000]}\n```\n\n"
        "Requirements:\n"
        "- Cover happy path, edge cases, and error conditions\n"
        "- Use proper assertions\n"
        "- Return ONLY the executable test code inside markdown code blocks\n"
    )
    model = str(services.config.get("models", {}).get("fast_code", "qwen2.5-coder:7b"))
    res = services._generate(model, prompt, "You are an expert test engineer.", 1500, 0.2, source="generate_tests",
                             **({"cancel_event": cancel_event} if cancel_event is not None else {}))
    if cancel_event is not None and cancel_event.is_set():
        return {"success": False, "cancelled": True, "reason": "cancelled"}
    if not res.get("success"):
        return res
    raw_code = str(res.get("text", ""))
    match = re.search(r"```(?:\w+)?\n(.*?)```", raw_code, re.DOTALL)
    test_code = match.group(1).strip() if match else raw_code.strip()
    return {
        "success": True,
        "framework": framework,
        "test_code": test_code,
        "model": model,
        "symbol": symbol,
        "path": path,
    }


def validate_patch(services: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate whether a diff patch applies cleanly and preserves valid syntax."""
    reject_retired_tenancy_fields(payload)
    diff_text = payload.get("patch", payload.get("diff", ""))
    if not isinstance(diff_text, str):
        return {
            "success": False,
            "status_code": 400,
            "terminal": True,
            "retryable": False,
            "error_code": "invalid_patch",
            "error": "patch must be a string",
        }
    if not diff_text.strip():
        return {
            "success": False,
            "status_code": 400,
            "terminal": True,
            "retryable": False,
            "error_code": "patch_required",
            "error": "empty patch",
        }

    affected_files: list[str] = []
    syntax_errors: list[str] = []
    previous_old: str | None = None
    hunks = 0

    def patch_path(raw: str) -> str | None:
        value = raw.strip().split("\t", 1)[0].replace("\\", "/")
        if value == "/dev/null":
            return value
        if value.startswith(("a/", "b/")):
            value = value[2:]
        parts = value.split("/")
        if not value or value.startswith("/") or any(part in {"", ".", ".."} for part in parts):
            return None
        return value

    for line in diff_text.splitlines():
        if line.startswith("--- "):
            previous_old = patch_path(line[4:])
            if previous_old is None:
                syntax_errors.append("invalid old patch path")
        elif line.startswith("+++ "):
            current = patch_path(line[4:])
            if previous_old is None or current is None:
                syntax_errors.append("patch file header is malformed")
            elif current != "/dev/null":
                affected_files.append(current)
            previous_old = None
        elif line.startswith("@@ "):
            if not re.match(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@", line):
                syntax_errors.append("invalid hunk header")
            else:
                hunks += 1

    if previous_old is not None:
        syntax_errors.append("patch has an unpaired file header")
    if not affected_files:
        syntax_errors.append("patch changes no files")
    if not hunks:
        syntax_errors.append("patch contains no hunks")
    errors = list(syntax_errors)
    valid = not errors
    applicability_checked = False
    if valid and payload.get("root"):
        root = Path(str(payload["root"])).expanduser().resolve()
        applicability_checked = True
        if not root.is_dir():
            errors.append("patch root directory does not exist")
        else:
            try:
                timeout = 8.0 if services is None else max(1.0, min(30.0, float(services.config.get("commands", {}).get("patch_check_timeout_seconds", 8.0))))
                checked = subprocess.run(
                    ["git", "-C", str(root), "apply", "--check", "--"], input=diff_text.encode("utf-8"), capture_output=True,
                    timeout=timeout, check=False, **hidden_run_kwargs(text=False),
                )
                if checked.returncode != 0:
                    check_error = (checked.stderr or checked.stdout or b"git apply --check failed").decode(
                        "utf-8", errors="replace"
                    ).strip()[:500]
                    errors.append(check_error)
                    if any(marker in check_error.casefold() for marker in (
                        "corrupt patch", "patch fragment without header", "unrecognized input",
                    )):
                        syntax_errors.append(check_error)
            except FileNotFoundError:
                errors.append("git is unavailable for applicability check")
            except subprocess.TimeoutExpired:
                errors.append("git apply --check timed out")
        valid = not errors

    return {
        "success": True,
        "valid": valid,
        "syntax_valid": not syntax_errors,
        "applicability_checked": applicability_checked,
        "files_affected": list(dict.fromkeys(affected_files)),
        "errors": errors,
        "message": f"Patch syntax {'is valid' if not syntax_errors else 'is invalid'}; applicability {'was checked' if applicability_checked else 'was not checked'}.",
    }
