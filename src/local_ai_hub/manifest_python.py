from __future__ import annotations

import re
import tomllib
from collections.abc import Callable


ManifestRows = tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]


def parse_python_manifest(
    name: str,
    raw: bytes,
    purpose: Callable[[str], str],
) -> ManifestRows | None:
    """Parse requirements files and Pipfile dependency/script rows."""
    deps: list[tuple[str, str, str]] = []
    scripts: list[tuple[str, str, str]] = []
    if name.startswith("requirements") and name.endswith((".txt", ".in")):
        text = raw.decode("utf-8", errors="replace")
        for line in text.splitlines():
            item = line.strip()
            if not item or item.startswith("#") or item.startswith(("-r ", "--requirement", "-c ", "--constraint")):
                continue
            item = item.split(" #", 1)[0].strip()
            token = re.split(r"[<>=!~ ;\[]", item, maxsplit=1)[0].strip()
            if token and not token.startswith(("git+", "http://", "https://", "-e")):
                deps.append((token, item, "requirements"))
        return deps, scripts

    if name == "pipfile":
        data = tomllib.loads(raw.decode("utf-8", errors="replace"))
        for section in ("packages", "dev-packages"):
            obj = data.get(section, {}) if isinstance(data, dict) else {}
            if isinstance(obj, dict):
                deps.extend((str(key), str(value), section) for key, value in obj.items())
        obj = data.get("scripts", {}) if isinstance(data, dict) else {}
        if isinstance(obj, dict):
            scripts.extend((str(key), str(value), purpose(str(key))) for key, value in obj.items())
        return deps, scripts

    return None
