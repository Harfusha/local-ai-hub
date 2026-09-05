from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from .sqlite_support import connect_sqlite, initialize_wal


class ArtifactStore:
    """Stores verbose local outputs outside the agent context and returns compact references."""

    def __init__(self, state_dir: Path, ttl_hours: int = 72, max_inline_chars: int = 6000):
        self.path = state_dir / "artifacts.sqlite3"
        self.ttl_seconds = max(3600, int(ttl_hours) * 3600)
        self.max_inline_chars = max(1000, int(max_inline_chars))
        self._last_purge = 0.0
        self._purge_interval = 1800.0
        state_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = connect_sqlite(self.path, timeout_seconds=0.75)
        con.execute("PRAGMA cache_size=-32768")
        con.execute("PRAGMA mmap_size=268435456")
        return con

    def _init_db(self) -> None:
        with closing(self._connect()) as con:
            initialize_wal(con)
            con.execute(
                """CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    tenant TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    text TEXT NOT NULL
                )"""
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_created ON artifacts(created_at)")
            con.commit()

    def _purge(self, con: sqlite3.Connection, force: bool = False) -> None:
        now = time.time()
        if not force and (now - self._last_purge) < self._purge_interval:
            return
        self._last_purge = now
        con.execute("DELETE FROM artifacts WHERE created_at < ?", (now - self.ttl_seconds,))

    def put(self, text: str, tenant: str, kind: str) -> str:
        digest = hashlib.sha256((kind + "\0" + text).encode("utf-8")).hexdigest()[:24]
        artifact_id = f"art_{digest}"
        with closing(self._connect()) as con:
            self._purge(con)
            con.execute(
                "INSERT OR REPLACE INTO artifacts(artifact_id, created_at, tenant, kind, text) VALUES(?,?,?,?,?)",
                (artifact_id, time.time(), tenant, kind, text),
            )
            con.commit()
        return artifact_id

    @staticmethod
    def _section_map(text: str) -> dict[str, tuple[int, int]]:
        """Return deterministic, addressable sections without asking an LLM to rewrite anything."""
        sections: dict[str, tuple[int, int]] = {}
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            # JSON artifacts are uncommon, but top-level keys are useful addresses. The offsets
            # below are intentionally omitted because serializing one value is cheaper/safer.
            return {f"json:{str(k)}": (-1, -1) for k in parsed.keys()}

        matches: list[tuple[str, int]] = []
        heading = re.compile(r"(?m)^(?:#{1,6}\s+([^\n#].*?)|([A-Z][A-Z0-9 _/.-]{2,48}):)\s*$")
        for m in heading.finditer(text):
            label = (m.group(1) or m.group(2) or "").strip().rstrip(":")
            if label:
                slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:64] or "section"
                base = slug; n = 2
                while slug in sections or any(name == slug for name, _ in matches):
                    slug = f"{base}-{n}"; n += 1
                matches.append((slug, m.start()))
        for i, (name, start) in enumerate(matches):
            end = matches[i + 1][1] if i + 1 < len(matches) else len(text)
            sections[name] = (start, end)
        return sections

    def compact(self, result: dict[str, Any], tenant: str, kind: str, *, field: str = "text") -> dict[str, Any]:
        if field not in result or not isinstance(result.get(field), str):
            return result
        text = result[field]
        if len(text) <= self.max_inline_chars:
            result.setdefault("artifact", None)
            return result
        artifact_id = self.put(text, tenant, kind)
        head = int(self.max_inline_chars * 0.82)
        tail = self.max_inline_chars - head
        preview = text[:head] + "\n\n[... full local output stored as artifact ...]\n\n" + text[-tail:]
        sections = list(self._section_map(text).keys())[:24]
        result[field] = preview
        result["artifact"] = {
            "id": artifact_id,
            "full_chars": len(text),
            "inline_chars": len(preview),
            "sections": sections,
            "hint": "Fetch only the needed section/slice if the compact preview is insufficient.",
        }
        return result

    def get(self, artifact_id: str, offset: int = 0, max_chars: int = 6000, section: str = "") -> dict[str, Any]:
        offset = max(0, int(offset))
        max_chars = max(256, min(int(max_chars), 50_000))
        cutoff = time.time() - self.ttl_seconds
        with closing(self._connect()) as con:
            # Reads stay read-only; expiry cleanup happens on writes. This avoids
            # turning every artifact slice fetch into a WAL writer.
            row = con.execute(
                "SELECT kind, text, created_at FROM artifacts WHERE artifact_id=? AND created_at>=?",
                (artifact_id, cutoff),
            ).fetchone()
        if not row:
            return {"success": False, "error": "artifact not found or expired", "artifact_id": artifact_id}
        text = row[1]
        section = str(section or "").strip()
        sections = self._section_map(text)
        if section:
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = None
            if section.startswith("json:") and isinstance(parsed, dict):
                key = section[5:]
                if key not in parsed:
                    return {"success": False, "error": "artifact section not found", "artifact_id": artifact_id, "sections": list(sections)[:50]}
                value = json.dumps(parsed[key], ensure_ascii=False, indent=2) if not isinstance(parsed[key], str) else parsed[key]
                piece = value[:max_chars]
                return {"success": True, "artifact_id": artifact_id, "kind": row[0], "section": section, "text": piece,
                        "next_offset": len(piece) if len(piece) < len(value) else None, "total_chars": len(value), "sections": list(sections)[:50]}
            if section not in sections:
                return {"success": False, "error": "artifact section not found", "artifact_id": artifact_id, "sections": list(sections)[:50]}
            start, end = sections[section]
            section_text = text[start:end]
            piece = section_text[offset:offset + max_chars]
            return {"success": True, "artifact_id": artifact_id, "kind": row[0], "section": section, "text": piece,
                    "offset": offset, "next_offset": offset + len(piece) if offset + len(piece) < len(section_text) else None,
                    "total_chars": len(section_text), "sections": list(sections)[:50]}

        piece = text[offset:offset + max_chars]
        return {
            "success": True,
            "artifact_id": artifact_id,
            "kind": row[0],
            "text": piece,
            "offset": offset,
            "next_offset": offset + len(piece) if offset + len(piece) < len(text) else None,
            "total_chars": len(text),
            "sections": list(sections)[:50],
        }
