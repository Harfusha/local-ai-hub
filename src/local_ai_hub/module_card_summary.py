"""Pure deterministic module-card summary construction."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_module_card_summary(
    module: str,
    file_cards: list[dict[str, Any]],
    paths: list[str],
    rows: list[Any],
) -> dict[str, Any]:
    """Aggregate file cards and exact parser coordinates without prose inference."""
    dependencies: list[str] = []
    risks: list[str] = []
    validation: list[str] = []
    entry_points: list[str] = []
    side_effects: list[str] = []
    symbols = 0

    def add_unique(dst: list[str], value: Any, limit: int = 40) -> None:
        text = str(value).strip()
        if text and text not in dst and len(dst) < limit:
            dst.append(text)

    for item in file_cards:
        card = item.get("card", item) if isinstance(item, dict) else {}
        path = str(item.get("path", "")) if isinstance(item, dict) else ""
        syms = card.get("symbols", []) if isinstance(card, dict) else []
        symbols += len(syms or [])
        for dep in card.get("dependencies", []) if isinstance(card, dict) else []:
            add_unique(dependencies, dep)
        for risk in card.get("risks", []) if isinstance(card, dict) else []:
            add_unique(risks, risk)
        for test in card.get("tests", []) if isinstance(card, dict) else []:
            add_unique(validation, test)
        for side in card.get("side_effects", []) if isinstance(card, dict) else []:
            add_unique(side_effects, side)
        low = Path(path).name.lower()
        if low in {"main.py", "app.py", "index.js", "index.ts", "server.js", "server.ts", "program.cs", "main.go", "main.rs"}:
            add_unique(entry_points, path)
        for symbol in syms or []:
            if str(symbol).lower() in {"main", "run", "app", "create_app", "startup", "program"}:
                add_unique(entry_points, f"{path}::{symbol}")

    for row in rows:
        kind = str(row["kind"])
        if kind in {"entrypoint", "entrypoint_file", "route"}:
            add_unique(entry_points, f"{row['path']}:{row['line']} {row['name']}")
        elif kind == "test_file":
            add_unique(validation, str(row["path"]))

    purpose_parts = [f"module {module}", f"{len(paths)} files"]
    if side_effects:
        purpose_parts.append("effects=" + ",".join(side_effects[:5]))
    invariants: list[str] = []
    # Only structural invariants are safe to state deterministically.
    if validation:
        invariants.append("validation files are mapped from indexed test paths")
    if entry_points:
        invariants.append("entry points are parser/index coordinates, not inferred behavior")
    richness = symbols + len(dependencies) + 2 * len(entry_points) + 2 * len(validation) + len(side_effects)
    confidence = (min(0.98, 0.82 + min(0.14, richness * 0.012) + (0.02 if len(paths) >= 2 else 0.0)) if paths else 0.4)
    card = {
        "purpose": "; ".join(purpose_parts),
        "entry_points": entry_points[:30],
        "dependencies": dependencies[:40],
        "invariants": invariants[:12],
        "risks": risks[:24],
        "validation": validation[:30],
    }
    return {"success": True, "deterministic": True, "confidence": round(confidence, 4), "card": card}
