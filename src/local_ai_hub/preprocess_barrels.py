from __future__ import annotations

from pathlib import Path
import re
from typing import Any

__all__ = [
    "derive_barrel_card_data",
    "is_trivial_barrel_module",
]


def is_trivial_barrel_module(rel_name: str, size: int, file_text: str) -> bool:
    """Determine whether a source file is a trivial re-export, barrel, or type declaration module."""
    if int(size or 0) < 1500:
        name = rel_name.lower()
        if name in {"__init__.py", "index.ts", "index.js", "index.mjs"}:
            return True
        if name.endswith((".d.ts", "_types.py", ".types.ts")):
            return True
        if any(file_text.strip().startswith(prefix) for prefix in ("export *", "from .", "__all__ =")):
            return True
    return False


def derive_barrel_card_data(rel_name: str, file_text: str, file_path: str) -> dict[str, Any]:
    """Derive deterministic metadata card payload for a trivial barrel or declaration module."""
    return {
        "purpose": f"re-export / declaration module ({rel_name})",
        "symbols": [p.strip() for p in re.findall(r"\b(?:export|class|def|type|interface)\s+([a-zA-Z0-9_]+)", file_text)[:12]],
        "dependencies": [],
        "side_effects": [],
        "risks": [],
        "tests": [],
        "keywords": [Path(str(file_path)).stem],
    }
