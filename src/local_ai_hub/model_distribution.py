"""Distribution, verification, and automated provisioning of Local AI Hub fine-tuned models.

Provides secure artifact downloading, strict pinned SHA-256 verification,
automatic Ollama model registration, and offline air-gapped support.
"""
from __future__ import annotations

import hashlib
import json
# import os
from pathlib import Path
import shutil
import subprocess
# import sys
import tempfile
import threading
from typing import Any
import urllib.request
import urllib.error

# Pinned distribution registry for Local AI Hub fine-tuned models
DISTRIBUTION_REGISTRY: dict[str, dict[str, Any]] = {
    "qwen2.5-coder-prep-v4:3b": {
        "kind": "ollama_gguf",
        "model_name": "qwen2.5-coder-prep-v4:3b",
        "quantization": "Q4_K_M",
        "base_family": "qwen2.5-coder",
        "filename": "qwen25-coder-3b-prep-v4-q4_k_m.gguf",
        "urls": ["https://huggingface.co/Harfusha/local-ai-hub-preprocess-qwen25-coder-3b/resolve/3e8c25fc7b6fd839701dad01dfe13a1ef4898543/qwen25-coder-3b-prep-v4-q4_k_m.gguf"],
        "expected_sha256": "f8f815fc8d8992063c294c11a906c38899d2cd8150b5ccf2a1aeefab95983113",
        "size_bytes": 1929902656,
    },
    "qwen2.5-coder-prep-v3:1.5b": {
        "kind": "ollama_gguf",
        "model_name": "qwen2.5-coder-prep-v3:1.5b",
        "quantization": "Q4_K_M",
        "base_family": "qwen2.5-coder",
        "filename": "qwen25-coder-1.5b-prep-v3-q4_k_m.gguf",
        "urls": ["https://huggingface.co/Harfusha/local-ai-hub-preprocess-qwen25-coder-1-5b/resolve/402474e54b881e2ade306a09afc81a29910e26ca/qwen25-coder-1.5b-prep-q4_k_m.gguf"],
        "expected_sha256": "23c2a208cdd8fa33cc0d959f076f8b54d7021f0ce896e5323ce4df715bb2c96b",
        "size_bytes": 986048160,
    },
    "qwen2.5-coder-prep-v3:0.5b": {
        "kind": "ollama_gguf",
        "model_name": "qwen2.5-coder-prep-v3:0.5b",
        "quantization": "Q4_K_M",
        "base_family": "qwen2.5-coder",
        "filename": "qwen25-coder-0.5b-prep-v3-q4_k_m.gguf",
        "urls": ["https://huggingface.co/Harfusha/local-ai-hub-preprocess-qwen25-coder-0-5b/resolve/00205f82897f6a18a6df8b12f27f33dfad82b1f5/qwen25-coder-0.5b-prep-q4_k_m.gguf"],
        "expected_sha256": "1b4a1adc42693edd4c414cbee638706ab0768f5526ba7e37f694337f088d9b54",
        "size_bytes": 397807584,
    },
}


def compute_file_sha256(path: Path | str) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def is_ollama_model_present(model_name: str, endpoint: str = "http://127.0.0.1:11434") -> bool:
    try:
        req = urllib.request.Request(f"{endpoint}/api/tags", headers={"User-Agent": "local-ai-hub"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for m in data.get("models", []):
                name = m.get("name", "")
                if name == model_name or name == f"{model_name}:latest":
                    return True
    except Exception:
        pass
    return False


def build_modelfile(gguf_path: Path) -> str:
    abs_gguf = str(gguf_path.resolve()).replace("\\", "/")
    return f"""FROM {abs_gguf}
TEMPLATE \"\"\"{{{{- if .Suffix }}}}<|fim_prefix|>{{{{ .Prompt }}}}<|fim_suffix|>{{{{ .Suffix }}}}<|fim_middle|>
{{{{- else if .Messages }}}}
{{{{- if or .System .Tools }}}}<|im_start|>system
{{{{- if .System }}}}
{{{{ .System }}}}
{{{{- end }}}}
{{{{- if .Tools }}}}

# Tools

You may call one or more functions to assist with the user query.

You are provided with function signatures within <tools></tools>:
<tools>
{{{{- range .Tools }}}}
{{"type": "function", "function": {{{{ .Function }}}} }}
{{{{- end }}}}
</tools>

For each function call, return a json object with function name and arguments within <tool_call></tool_call> with NO other text. Do not include any backticks or ```json.
<tool_call>
{{"name": <function-name>, "arguments": <args-json-object>}}
</tool_call>
{{{{- end }}}}<|im_end|>
{{{{ end }}}}
{{{{- range $i, $_ := .Messages }}}}
{{{{- $last := eq (len (slice $.Messages $i)) 1 -}}}}
{{{{- if eq .Role "user" }}}}<|im_start|>user
{{{{ .Content }}}}<|im_end|>
{{{{ else if eq .Role "assistant" }}}}<|im_start|>assistant
{{{{ if .Content }}}}{{{{ .Content }}}}
{{{{- else if .ToolCalls }}}}<tool_call>
{{{{ range .ToolCalls }}}}{{"name": "{{{{ .Function.Name }}}}", "arguments": {{{{ .Function.Arguments }}}} }}
{{{{ end }}}}<|im_end|>
{{{{ end }}}}{{{{ if not $last }}}}<|im_end|>
{{{{ end }}}}
{{{{- else if eq .Role "tool" }}}}<|im_start|>user
<tool_response>
{{{{ .Content }}}}
</tool_response><|im_end|>
{{{{ end }}}}
{{{{- if and (ne .Role "assistant") $last }}}}<|im_start|>assistant
{{{{ end }}}}
{{{{- end }}}}
{{{{- else }}}}
{{{{- if .System }}}}<|im_start|>system
{{{{ .System }}}}<|im_end|>
{{{{ end }}}}{{{{- if .Prompt }}}}<|im_start|>user
{{{{ .Prompt }}}}<|im_end|>
{{{{ end }}}}<|im_start|>assistant
{{{{ end }}}}{{{{ .Response }}}}{{{{- if .Response }}}}<|im_end|>{{{{ end }}}}\"\"\"
SYSTEM You are Qwen, created by Alibaba Cloud. You are a helpful assistant.
PARAMETER stop "<|im_end|>"
PARAMETER stop "<|endoftext|>"
"""


def register_gguf_in_ollama(model_name: str, gguf_path: Path) -> bool:
    if not gguf_path.is_file():
        raise FileNotFoundError(f"GGUF artifact does not exist: {gguf_path}")

    modelfile_content = build_modelfile(gguf_path)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".modelfile") as tf:
        tf.write(modelfile_content)
        temp_modelfile = Path(tf.name)

    try:
        ollama_bin = shutil.which("ollama") or "ollama"
        cmd = [ollama_bin, "create", model_name, "-f", str(temp_modelfile)]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return res.returncode == 0
    finally:
        try:
            temp_modelfile.unlink(missing_ok=True)
        except Exception:
            pass


def _ensure_distribution_model(
    identifier: str,
    root: Path | None = None,
    allow_download: bool = True,
    force_register: bool = False,
    models_dir: Path | None = None,
) -> dict[str, Any]:
    """Ensure a trained model is present, verified, and registered in Ollama / state."""
    if identifier not in DISTRIBUTION_REGISTRY:
        raise ValueError(f"Unknown model identifier: {identifier}. Registered: {list(DISTRIBUTION_REGISTRY.keys())}")

    entry = DISTRIBUTION_REGISTRY[identifier]
    project_root = root or Path.cwd()
    models_dir = models_dir or project_root / "state" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    kind = entry["kind"]
    model_name = entry["model_name"]

    if kind == "ollama_gguf":
        # Check if already in Ollama
        if not force_register and is_ollama_model_present(model_name):
            return {
                "status": "ready",
                "model_name": model_name,
                "source": "ollama_installed",
                "message": f"Model {model_name} is already registered in Ollama",
            }

        target_file = models_dir / entry["filename"]
        # If file exists locally, check hash
        if target_file.is_file():
            actual_sha = compute_file_sha256(target_file)
            print(f"Local file found: {target_file} (SHA256: {actual_sha[:16]}...)")
            if actual_sha != entry.get("expected_sha256"):
                return {
                    "status": "hash_mismatch",
                    "model_name": model_name,
                    "file": str(target_file),
                    "error": "Local GGUF does not match the pinned trained model; refusing registration.",
                }
            # Register in Ollama
            print(f"Registering {model_name} in Ollama from local GGUF...")
            ok = register_gguf_in_ollama(model_name, target_file)
            if ok:
                return {
                    "status": "registered",
                    "model_name": model_name,
                    "source": "local_gguf",
                    "sha256": actual_sha,
                    "file": str(target_file),
                }

        # Need download
        if not allow_download:
            return {
                "status": "missing",
                "model_name": model_name,
                "error": f"GGUF artifact {entry['filename']} missing and download is disabled",
            }

        # Attempt download from URLs
        download_success = False
        last_error = ""
        for url in entry["urls"]:
            print(f"Attempting download of {model_name} from {url}...")
            temp_download = target_file.with_suffix(".download.tmp")
            try:
                with urllib.request.urlopen(url, timeout=120) as response, temp_download.open("wb") as sink:
                    while chunk := response.read(8 * 1024 * 1024):
                        sink.write(chunk)
                # Verify sha256
                downloaded_sha = compute_file_sha256(temp_download)
                exp_sha = entry.get("expected_sha256")
                if exp_sha and downloaded_sha != exp_sha:
                    temp_download.unlink(missing_ok=True)
                    last_error = f"SHA256 mismatch from {url}: got {downloaded_sha}, expected {exp_sha}"
                    continue

                temp_download.rename(target_file)
                download_success = True
                break
            except Exception as exc:
                last_error = str(exc)
                temp_download.unlink(missing_ok=True)

        if not download_success:
            return {
                "status": "download_failed",
                "model_name": model_name,
                "error": last_error or "All download mirrors failed",
            }

        # Register in Ollama
        ok = register_gguf_in_ollama(model_name, target_file)
        return {
            "status": "registered" if ok else "registration_failed",
            "model_name": model_name,
            "source": "downloaded_gguf",
            "file": str(target_file),
        }

    return {"status": "unsupported_kind", "kind": kind}


_DISTRIBUTION_LOCKS_GUARD = threading.Lock()
_DISTRIBUTION_LOCKS: dict[str, threading.Lock] = {}


def ensure_distribution_model(
    identifier: str,
    root: Path | None = None,
    allow_download: bool = True,
    force_register: bool = False,
    models_dir: Path | None = None,
) -> dict[str, Any]:
    """Serialize first-use downloads and Ollama registration per model."""
    with _DISTRIBUTION_LOCKS_GUARD:
        lock = _DISTRIBUTION_LOCKS.setdefault(identifier, threading.Lock())
    with lock:
        return _ensure_distribution_model(
            identifier,
            root=root,
            allow_download=allow_download,
            force_register=force_register,
            models_dir=models_dir,
        )
