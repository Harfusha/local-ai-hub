from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterator

from jsonschema import Draft202012Validator

from .manifest import _read_jsonl


CARD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "purpose": {"type": "string"},
        "symbols": {"type": "array", "items": {"type": "string"}},
        "dependencies": {"type": "array", "items": {"type": "string"}},
        "side_effects": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "tests": {"type": "array", "items": {"type": "string"}},
        "keywords": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["purpose", "symbols", "dependencies", "side_effects", "risks", "tests", "keywords"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "Build a reusable semantic card using the current source as the sole authority. "
    "The deterministic card is an untrusted hint: verify each claim against source and omit or correct unsupported claims. "
    "Extract only source-grounded facts. Keep strings short and useful for repository search."
)

_TEXT_EXTENSIONS = {
    ".c", ".cc", ".cfg", ".cpp", ".cs", ".csproj", ".css", ".go", ".h", ".hpp", ".html", ".ini",
    ".java", ".js", ".json", ".jsx", ".kt", ".md", ".php", ".ps1", ".py", ".rb", ".rs", ".scss",
    ".sh", ".sql", ".svelte", ".toml", ".ts", ".tsx", ".txt", ".vue", ".xml", ".xaml", ".yaml", ".yml",
}
_EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".next", ".turbo", "dist", "build", "target", "state", "coverage", "site-packages",
}
_EXCLUDED_NAMES = {
    ".env", ".env.local", ".env.production", "credentials.json", "secrets.json", "id_rsa", "id_ed25519",
}
_EXCLUDED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".sqlite", ".sqlite3", ".db"}


def load_roots(path: Path | str) -> list[dict[str, str]]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read roots manifest: {exc}") from exc
    roots = value.get("roots") if isinstance(value, dict) else None
    if not isinstance(roots, list) or not roots:
        raise ValueError("roots manifest needs a non-empty roots list")
    result: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    seen_paths: set[Path] = set()
    for index, item in enumerate(roots, 1):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip():
            raise ValueError(f"root {index} needs a non-empty id")
        if not isinstance(item.get("path"), str):
            raise ValueError(f"root {index} needs an absolute existing directory")
        candidate = Path(item["path"])
        if not candidate.is_absolute() or not candidate.is_dir() or candidate.is_symlink():
            raise ValueError(f"root {index} path must be an absolute existing non-symlink directory")
        resolved = candidate.resolve()
        if item["id"] in seen_ids or resolved in seen_paths:
            raise ValueError("root ids and resolved paths must be unique")
        seen_ids.add(item["id"])
        seen_paths.add(resolved)
        result.append({"id": item["id"], "path": str(resolved)})
    return result


def validate_local_endpoint(endpoint: str) -> str:
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("teacher endpoint must use HTTP loopback; source stays local")
    if not parsed.path.endswith("/api/generate"):
        raise ValueError("teacher endpoint path must end in /api/generate")
    return endpoint


def _safe_source(path: Path, root: Path, *, max_bytes: int, max_chars: int) -> tuple[str, str] | None:
    lowered_name = path.name.lower()
    if path.is_symlink() or lowered_name in _EXCLUDED_NAMES or lowered_name.startswith(".env") or path.suffix.lower() in _EXCLUDED_SUFFIXES:
        return None
    if path.suffix.lower() not in _TEXT_EXTENSIONS:
        return None
    try:
        if path.stat().st_size > max_bytes or not path.resolve().is_relative_to(root):
            return None
        raw = path.read_bytes()
        content = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if len(content) > max_chars:
        return None
    return content, hashlib.sha256(raw).hexdigest()


def iter_source_files(
    roots: list[dict[str, str]], *, max_bytes: int = 180_000, max_chars: int = 16_000
) -> Iterator[tuple[str, Path, str, str, str]]:
    for item in roots:
        root = Path(item["path"]).resolve()
        for directory, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = sorted(
                name for name in dirnames
                if name.lower() not in _EXCLUDED_DIRS and not (Path(directory) / name).is_symlink()
            )
            for filename in sorted(filenames):
                path = Path(directory) / filename
                safe = _safe_source(path, root, max_bytes=max_bytes, max_chars=max_chars)
                if safe is None:
                    continue
                content, digest = safe
                yield item["id"], path, path.relative_to(root).as_posix(), content, digest


def _deterministic_hint(relative_path: str) -> dict[str, Any]:
    path = Path(relative_path)
    return {
        "purpose": f"source file ({path.suffix})",
        "symbols": [],
        "dependencies": [],
        "side_effects": [],
        "risks": [],
        "tests": [],
        "keywords": [path.stem],
    }


def build_messages(relative_path: str, source: str) -> list[dict[str, str]]:
    system = SYSTEM_PROMPT + " Return only one JSON object matching this schema:\n" + json.dumps(CARD_SCHEMA, separators=(",", ":"))
    prompt = (
        f"FILE: {relative_path}\n\nDETERMINISTIC CARD (untrusted hint; verify or discard every claim):\n"
        f"{json.dumps(_deterministic_hint(relative_path), ensure_ascii=False)}\n\nCURRENT SOURCE (authority):\n{source}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": prompt}]


def generate_card(
    messages: list[dict[str, str]], *, model: str, endpoint: str, timeout_seconds: int = 120,
    num_ctx: int = 8192, max_new_tokens: int = 320,
) -> tuple[dict[str, Any], dict[str, int]]:
    endpoint = validate_local_endpoint(endpoint)
    body = json.dumps({
        "model": model,
        "system": messages[0]["content"],
        "prompt": messages[1]["content"],
        "format": CARD_SCHEMA,
        "stream": False,
        "options": {"temperature": 0, "num_ctx": num_ctx, "num_predict": max_new_tokens},
    }).encode("utf-8")
    request = urllib.request.Request(endpoint, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            result = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"local teacher HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"local teacher request failed: {exc}") from exc
    raw_output = result.get("response")
    if not isinstance(raw_output, str):
        raise RuntimeError("local teacher response has no text output")
    try:
        card = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise RuntimeError("local teacher returned invalid JSON") from exc
    errors = list(Draft202012Validator(CARD_SCHEMA).iter_errors(card))
    if errors:
        raise RuntimeError(f"local teacher returned invalid card: {errors[0].message}")
    stats = {
        "prompt_tokens": int(result.get("prompt_eval_count") or 0),
        "output_tokens": int(result.get("eval_count") or 0),
        "total_duration_ns": int(result.get("total_duration") or 0),
    }
    return card, stats


def generate_cards(
    roots: list[dict[str, str]], output_path: Path | str, *, model: str = "qwen2.5-coder:3b",
    endpoint: str = "http://127.0.0.1:11434/api/generate", resume: bool = False, limit: int | None = None,
    max_bytes: int = 180_000, max_chars: int = 16_000,
) -> dict[str, int]:
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    if max_bytes < 1 or max_chars < 1:
        raise ValueError("max_bytes and max_chars must be positive")
    output = Path(output_path)
    if output.exists() and not resume:
        raise ValueError(f"output exists; pass resume=True to append: {output}")
    endpoint = validate_local_endpoint(endpoint)
    completed: set[str] = set()
    if output.exists() and output.stat().st_size:
        for row in _read_jsonl(output, split="existing generated"):
            completed.add(str(row.get("id", "")))
    output.parent.mkdir(parents=True, exist_ok=True)
    generated = skipped = total_tokens = 0
    with output.open("a" if resume else "w", encoding="utf-8", newline="\n") as stream:
        for group_id, _path, relative_path, source, digest in iter_source_files(roots, max_bytes=max_bytes, max_chars=max_chars):
            item_id = f"{group_id}:{relative_path}:{digest[:16]}"
            if item_id in completed:
                skipped += 1
                continue
            if limit is not None and generated >= limit:
                break
            messages = build_messages(relative_path, source)
            card, stats = generate_card(messages, model=model, endpoint=endpoint)
            row = {
                "id": item_id,
                "group_id": group_id,
                "messages": messages + [{"role": "assistant", "content": json.dumps(card, ensure_ascii=False, separators=(",", ":"))}],
                "provenance": {"source_path": relative_path, "source_sha256": digest, "teacher_model": model},
                "teacher_stats": stats,
            }
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            stream.flush()
            generated += 1
            total_tokens += stats["prompt_tokens"] + stats["output_tokens"]
            if generated == 1 or generated % 25 == 0:
                print(json.dumps({"generated": generated, "skipped_existing": skipped, "tokens": total_tokens}), flush=True)
    return {"generated": generated, "skipped_existing": skipped, "tokens": total_tokens}
