"""Cross-File Context & Architectural Neighborhood Injector for Preprocessing.

Extracts immediate import/caller neighbors of a target source file and queries
their existing content cards to build an architectural neighborhood summary.
Injected into the preprocessing model prompt to establish broader systemic invariants.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NeighborSummary:
    """Summary of one related neighboring file in the architectural graph."""

    rel_path: str
    relation: str  # "imports" or "imported_by"
    purpose: str
    key_symbols: tuple[str, ...]


def find_file_neighbors(
    db_con: sqlite3.Connection,
    root: str,
    file_rel_path: str,
    limit: int = 3,
) -> list[NeighborSummary]:
    """Retrieve top neighboring files and their summarized purpose from cards."""
    norm_path = str(file_rel_path).replace("\\", "/").strip("/")
    neighbors: list[NeighborSummary] = []

    try:
        # 1. Files imported by this file
        imported_rows = db_con.execute(
            "SELECT value FROM facts WHERE root=? AND path=? AND kind='import' LIMIT ?",
            (root, norm_path, limit),
        ).fetchall()

        for r in imported_rows:
            imp_name = str(r[0]).strip()
            # Look up card for module
            card_row = db_con.execute(
                """
                SELECT c.card_json FROM content_cards c
                JOIN file_refs f ON c.card_key = f.card_key
                WHERE f.root=? AND (f.path LIKE ? OR f.path LIKE ?)
                LIMIT 1
                """,
                (root, f"%/{imp_name}.py", f"%/{imp_name}/__init__.py"),
            ).fetchone()

            purpose = f"Module {imp_name}"
            syms: tuple[str, ...] = ()
            if card_row:
                import json
                try:
                    cdata = json.loads(card_row[0])
                    purpose = str(cdata.get("purpose", purpose))
                    syms = tuple(cdata.get("symbols", [])[:5])
                except Exception:
                    pass

            neighbors.append(NeighborSummary(
                rel_path=imp_name,
                relation="imports",
                purpose=purpose[:200],
                key_symbols=syms,
            ))

        # 2. Files that import this file (reverse lookup)
        stem = Path(norm_path).stem
        caller_rows = db_con.execute(
            "SELECT path FROM facts WHERE root=? AND kind='import' AND value=? LIMIT ?",
            (root, stem, limit),
        ).fetchall()

        for r in caller_rows:
            caller_path = str(r[0]).replace("\\", "/").strip("/")
            if caller_path != norm_path:
                neighbors.append(NeighborSummary(
                    rel_path=caller_path,
                    relation="imported_by",
                    purpose="Upstream caller module",
                    key_symbols=(),
                ))
    except Exception as exc:
        logger.debug("Neighborhood lookup failed for %s: %s", norm_path, exc)

    return neighbors[:limit * 2]


def format_neighborhood_prompt_section(neighbors: Sequence[NeighborSummary]) -> str:
    """Format neighbors into a concise architectural prompt block."""
    if not neighbors:
        return ""

    lines = ["ARCHITECTURAL NEIGHBORHOOD CONTEXT:"]
    for n in neighbors:
        if n.relation == "imports":
            sym_str = f" (exports: {', '.join(n.key_symbols)})" if n.key_symbols else ""
            lines.append(f"- Imports '{n.rel_path}': {n.purpose}{sym_str}")
        else:
            lines.append(f"- Imported by upstream caller '{n.rel_path}'")

    return "\n".join(lines)
