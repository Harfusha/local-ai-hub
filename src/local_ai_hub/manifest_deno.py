from __future__ import annotations

import json
import re
from collections.abc import Callable


ManifestRows = tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]


def parse_deno_manifest(
    name: str,
    raw: bytes,
    purpose: Callable[[str], str],
) -> ManifestRows | None:
    """Parse Deno imports and tasks from JSON or conservatively cleaned JSONC."""
    if name not in {"deno.json", "deno.jsonc"}:
        return None

    text = raw.decode("utf-8", errors="replace")
    if name.endswith(".jsonc"):
        # Conservative JSONC cleanup sufficient for top-level imports/tasks.
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        text = re.sub(r"(^|\s)//.*$", r"\1", text, flags=re.M)
        text = re.sub(r",\s*([}\]])", r"\1", text)
    data = json.loads(text)
    deps: list[tuple[str, str, str]] = []
    scripts: list[tuple[str, str, str]] = []
    if isinstance(data, dict):
        imports = data.get("imports", {})
        if isinstance(imports, dict):
            deps.extend((str(key), str(value), "deno-import") for key, value in imports.items())
        tasks = data.get("tasks", {})
        if isinstance(tasks, dict):
            scripts.extend((str(key), str(value), purpose(str(key))) for key, value in tasks.items())
    return deps, scripts
