from __future__ import annotations

import ast
import copy
import json
import re
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from . import __version__
from .cache import MemoryLRUCache, stable_hash
from .normalizer import tokenize_query_terms
from .process_utils import canonical_root
from .sqlite_support import connect_sqlite, initialize_wal, is_busy_error

IDENT = re.compile(r"\b[A-Za-z_$][A-Za-z0-9_$]{2,}\b")
GENERIC_DEF = re.compile(r"^\s*(?:(?:public|private|protected|internal|static|final|async|export|abstract|virtual|override|sealed|readonly)\s+)*(class|interface|trait|enum|struct|record|function|func|fn|def|type)\s+([A-Za-z_$][A-Za-z0-9_$]*)")
IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w./@-]+)|(?:use|require|require_once|include|include_once|using)\s*\(?[\'\"]?([^\'\";]+)[\'\"]?\)?)")
ARROW_DEF = re.compile(r"^\s*(?:(?:export|default|public|private|protected|internal|static|readonly|const|let|var)\s+)*([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][A-Za-z0-9_$]*)\s*=>")
GO_METHOD = re.compile(r"^\s*func\s*(?:\([^)]*\)\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*\(")
TYPED_METHOD = re.compile(r"^\s*(?:(?:public|private|protected|internal|static|final|async|virtual|override|abstract|sealed|synchronized|native)\s+)*(?:[A-Za-z_$][\w.$<>,?\[\]]*\s+)+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(([^;{}]*)\)\s*(?:\{|=>|throws\b|where\b)")
JS_METHOD = re.compile(r"^\s*(?:async\s+)?([A-Za-z_$][A-Za-z0-9_$]*)\s*\(([^)]*)\)\s*\{")
_CONTROL_NAMES = {"if","for","while","switch","catch","return","new","throw","using","lock","foreach","typeof","sizeof","default"}


class CodeIndex:
    def __init__(self, config: dict[str, Any], repo_tools: Any):
        self.config = config
        self.repo_tools = repo_tools
        self.db_path = Path(config["server"]["state_dir"]) / "code-index.sqlite3"
        self.parse_blob_max = int(config.get("code_index", {}).get("parse_blob_max_entries", 100000))
        self._lock = threading.RLock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._status_cache: dict[str, Any] = {}
        self._rev_cache = {}
        self._rev_lock = threading.Lock()
        self._parse_blob_l1 = MemoryLRUCache(max_entries=4096, ttl_seconds=3600)
        self._query_l1 = MemoryLRUCache(max_entries=2048, ttl_seconds=1800)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = connect_sqlite(self.db_path, timeout_seconds=0.75, row_factory=sqlite3.Row)
        try:
            con.execute("PRAGMA cache_size=-65536")
            con.execute("PRAGMA mmap_size=536870912")
            con.execute("PRAGMA synchronous=NORMAL")
            return con
        except Exception:
            con.close()
            raise

    def _schema(self, con: sqlite3.Connection) -> None:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS files(
            root TEXT,
            path TEXT,
            content_hash TEXT,
            language TEXT,
            updated_at REAL,
            PRIMARY KEY(root, path)
        );
        CREATE TABLE IF NOT EXISTS symbols(
            root TEXT,
            path TEXT,
            name TEXT,
            kind TEXT,
            line INTEGER,
            end_line INTEGER,
            container TEXT,
            name_path TEXT,
            signature TEXT,
            access TEXT,
            docstring TEXT,
            PRIMARY KEY(root, path, name_path, line)
        );
        CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(root, name);
        CREATE INDEX IF NOT EXISTS idx_symbols_name_lc ON symbols(root, lower(name));
        CREATE INDEX IF NOT EXISTS idx_symbols_name_path ON symbols(root, name_path);
        CREATE INDEX IF NOT EXISTS idx_symbols_name_path_lc ON symbols(root, lower(name_path));
        CREATE INDEX IF NOT EXISTS idx_symbols_path ON symbols(root, path);
        CREATE INDEX IF NOT EXISTS idx_symbols_container ON symbols(root, container);

        CREATE TABLE IF NOT EXISTS refs(
            root TEXT,
            path TEXT,
            name TEXT,
            line INTEGER,
            kind TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_refs_name ON refs(root, name);
        CREATE INDEX IF NOT EXISTS idx_refs_name_lc ON refs(root, lower(name));
        CREATE INDEX IF NOT EXISTS idx_refs_path ON refs(root, path);

        CREATE TABLE IF NOT EXISTS edges(
            root TEXT,
            src TEXT,
            dst TEXT,
            kind TEXT,
            path TEXT,
            line INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(root, src);
        CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(root, dst);
        CREATE INDEX IF NOT EXISTS idx_edges_path ON edges(root, path);

        CREATE TABLE IF NOT EXISTS parse_blobs(
            content_hash TEXT,
            analyzer_version TEXT,
            language TEXT,
            payload_json TEXT,
            updated_at REAL,
            PRIMARY KEY(content_hash, analyzer_version, language)
        );
        CREATE INDEX IF NOT EXISTS idx_parse_blobs_updated ON parse_blobs(updated_at);
        """)
        
    def _init_db(self) -> None:
        try:
            with self._lock, closing(self._connect()) as con:
                initialize_wal(con)
                ok = con.execute("PRAGMA quick_check").fetchone()[0]
                if ok != "ok":
                    raise sqlite3.DatabaseError(str(ok))
                self._schema(con)
                con.commit()
        except sqlite3.DatabaseError as exc:
            if is_busy_error(exc):
                return
            stamp = int(time.time())
            try:
                if self.db_path.exists():
                    self.db_path.replace(self.db_path.with_name(self.db_path.name + f".corrupt-{stamp}"))
                for suffix in ("-wal", "-shm"):
                    side = Path(str(self.db_path) + suffix)
                    if side.exists():
                        side.unlink(missing_ok=True)
            except OSError:
                pass
            with self._lock, closing(self._connect()) as con:
                initialize_wal(con)
                self._schema(con)
                con.commit()

    @staticmethod
    def _lang(path: str) -> str:
        suffix = Path(path).suffix.lower()
        return {
            ".py": "python",
            ".cs": "csharp",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".js": "javascript",
            ".jsx": "javascript",
            ".php": "php",
            ".java": "java",
            ".go": "go",
            ".rs": "rust",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
        }.get(suffix, "generic")

    def _parse_python(self, text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        syms: list[dict[str, Any]] = []
        refs: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return syms, refs, edges

        stack: list[str] = []
        overloads: dict[str, int] = {}

        class V(ast.NodeVisitor):
            def visit_ClassDef(s, n):
                container = "/".join(stack)
                name_path = (container + "/" if container else "") + n.name
                doc = ast.get_docstring(n) or ""
                doc_summary = doc.strip().splitlines()[0] if doc.strip() else ""
                bases = [ast.unparse(b) for b in n.bases]

                syms.append({
                    "name": n.name,
                    "kind": "class",
                    "line": n.lineno,
                    "end_line": getattr(n, "end_lineno", n.lineno),
                    "container": container,
                    "name_path": name_path,
                    "signature": f"class {n.name}({', '.join(bases)})" if bases else f"class {n.name}",
                    "access": "public" if not n.name.startswith("_") else "private",
                    "docstring": doc_summary[:200],
                })
                for b in bases:
                    edges.append({"src": name_path, "dst": b, "kind": "inherits", "line": n.lineno})

                stack.append(n.name)
                s.generic_visit(n)
                stack.pop()

            def visit_FunctionDef(s, n):
                container = "/".join(stack)
                base_name_path = (container + "/" if container else "") + n.name
                idx = overloads.get(base_name_path, 0)
                overloads[base_name_path] = idx + 1
                name_path = base_name_path if idx == 0 else f"{base_name_path}[{idx}]"

                doc = ast.get_docstring(n) or ""
                doc_summary = doc.strip().splitlines()[0] if doc.strip() else ""
                args_str = ", ".join(a.arg for a in n.args.args)
                ret = ast.unparse(n.returns) if n.returns else ""
                sig = f"def {n.name}({args_str})" + (f" -> {ret}" if ret else "")

                is_method = bool(stack)
                kind = "method" if is_method else "function"
                if any(isinstance(d, ast.Name) and d.id == "property" for d in n.decorator_list):
                    kind = "property"

                syms.append({
                    "name": n.name,
                    "kind": kind,
                    "line": n.lineno,
                    "end_line": getattr(n, "end_lineno", n.lineno),
                    "container": container,
                    "name_path": name_path,
                    "signature": sig,
                    "access": "public" if not n.name.startswith("_") else "private",
                    "docstring": doc_summary[:200],
                })

                stack.append(n.name)
                s.generic_visit(n)
                stack.pop()

            def visit_AsyncFunctionDef(s, n):
                s.visit_FunctionDef(n)

            def visit_Call(s, n):
                name = ""
                if isinstance(n.func, ast.Name):
                    name = n.func.id
                elif isinstance(n.func, ast.Attribute):
                    name = n.func.attr
                if name:
                    refs.append({"name": name, "line": getattr(n, "lineno", 0), "kind": "call"})
                    edges.append({"src": "/".join(stack) or "<module>", "dst": name, "kind": "calls", "line": getattr(n, "lineno", 0)})
                s.generic_visit(n)

            def visit_Import(s, n):
                for a in n.names:
                    edges.append({"src": "<module>", "dst": a.name, "kind": "imports", "line": n.lineno})

            def visit_ImportFrom(s, n):
                edges.append({"src": "<module>", "dst": n.module or "", "kind": "imports", "line": n.lineno})

        V().visit(tree)
        return syms, refs, edges

    @staticmethod
    def _brace_metadata(lines: list[str]) -> tuple[dict[int, int], list[int | None]]:
        """Build brace pairs and next-opening positions in one linear pass.

        End-line metadata is only informational, but repeatedly scanning hundreds
        of lines for every symbol made large C#/JS files quadratic to parse.
        """
        pairs: dict[int, int] = {}
        stack: list[int] = []
        has_open = ["{" in line.split("//", 1)[0] for line in lines]
        for index, line in enumerate(lines):
            for char in line.split("//", 1)[0]:
                if char == "{":
                    stack.append(index)
                elif char == "}" and stack:
                    pairs[stack.pop()] = index
        next_open: list[int | None] = [None] * len(lines)
        nearest: int | None = None
        for index in range(len(lines) - 1, -1, -1):
            if has_open[index]:
                nearest = index
            next_open[index] = nearest
        return pairs, next_open

    @staticmethod
    def _block_end_line(start_index: int, pairs: dict[int, int], next_open: list[int | None], max_lines: int) -> int:
        opening = next_open[start_index] if 0 <= start_index < len(next_open) else None
        if opening is None or opening - start_index >= max_lines:
            return start_index + 1
        closing = pairs.get(opening)
        return (closing + 1) if closing is not None else start_index + 1

    def _parse_csharp(self, text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        syms: list[dict[str, Any]] = []
        refs: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        lines = text.splitlines()
        brace_pairs, next_open = self._brace_metadata(lines)

        class_re = re.compile(
            r"^\s*(?:\[[^\]]+\]\s*)*(?:(public|private|protected|internal|static|abstract|sealed|partial)\s+)*(class|interface|struct|enum|record)\s+([A-Za-z0-9_]+)(?:<[^>]+>)?(?:\s*:\s*([A-Za-z0-9_,\s<>]+))?",
            re.M,
        )
        method_re = re.compile(
            r"^\s*(?:\[[^\]]+\]\s*)*(?:(public|private|protected|internal|static|virtual|override|abstract|async|sealed)\s+)*(?:([A-Za-z0-9_<>\[\]?]+)\s+)?([A-Za-z0-9_]+)\s*\(([^;{}]*)\)\s*(?:where\s+.*?)?(?:\{|=>|;)",
            re.M,
        )
        prop_re = re.compile(
            r"^\s*(?:(public|private|protected|internal|static|virtual|override|abstract)\s+)+([A-Za-z0-9_<>\[\]?]+)\s+([A-Za-z0-9_]+)\s*\{[^}]*\}",
            re.M,
        )
        using_re = re.compile(r"^\s*using\s+(?:static\s+)?([A-Za-z0-9_.]+);")

        container_stack: list[tuple[str, str, int, int]] = []
        overloads: dict[str, int] = {}

        for i, line in enumerate(lines, 1):
            um = using_re.match(line)
            if um:
                edges.append({"src": "<module>", "dst": um.group(1), "kind": "imports", "line": i})

        for i, line in enumerate(lines, 1):
            container_stack = [c for c in container_stack if c[3] >= i]
            curr_container = "/".join(c[0] for c in container_stack)

            cm = class_re.match(line)
            if cm:
                access = cm.group(1) or "internal"
                kind = cm.group(2)
                name = cm.group(3)
                heritage = cm.group(4) or ""

                end_l = self._block_end_line(i - 1, brace_pairs, next_open, 3500)

                container_stack.append((name, kind, i, end_l))
                name_path = (curr_container + "/" if curr_container else "") + name

                doc = ""
                if i > 1:
                    prev = lines[i - 2].strip()
                    if prev.startswith("///"):
                        doc = re.sub(r"<[^>]+>", "", prev.replace("///", "")).strip()

                syms.append({
                    "name": name,
                    "kind": kind,
                    "line": i,
                    "end_line": end_l,
                    "container": curr_container,
                    "name_path": name_path,
                    "signature": f"{access} {kind} {name}" + (f" : {heritage.strip()}" if heritage else ""),
                    "access": access,
                    "docstring": doc[:200],
                })

                if heritage:
                    for base in heritage.split(","):
                        b = base.strip().split("<")[0].strip()
                        if b:
                            edges.append({"src": name_path, "dst": b, "kind": "inherits" if "class" in kind else "implements", "line": i})
                continue

            mm = method_re.match(line)
            if mm and mm.group(3) not in _CONTROL_NAMES:
                access = mm.group(1) or "private"
                ret_type = mm.group(2) or "void"
                name = mm.group(3)
                params = mm.group(4) or ""

                end_l = i
                if "{" in line:
                    closing = brace_pairs.get(i - 1)
                    if closing is not None and closing - (i - 1) < 800:
                        end_l = closing + 1

                base_name_path = (curr_container + "/" if curr_container else "") + name
                idx = overloads.get(base_name_path, 0)
                overloads[base_name_path] = idx + 1
                name_path = base_name_path if idx == 0 else f"{base_name_path}[{idx}]"

                syms.append({
                    "name": name,
                    "kind": "method" if curr_container else "function",
                    "line": i,
                    "end_line": max(i, end_l),
                    "container": curr_container,
                    "name_path": name_path,
                    "signature": f"{access} {ret_type} {name}({params.strip()})",
                    "access": access,
                    "docstring": "",
                })

            pm = prop_re.match(line)
            if pm:
                access = pm.group(1)
                prop_type = pm.group(2)
                prop_name = pm.group(3)
                name_path = (curr_container + "/" if curr_container else "") + prop_name
                syms.append({
                    "name": prop_name,
                    "kind": "property",
                    "line": i,
                    "end_line": i,
                    "container": curr_container,
                    "name_path": name_path,
                    "signature": f"{access} {prop_type} {prop_name} {{ get; set; }}",
                    "access": access,
                    "docstring": "",
                })

        call_pattern = re.compile(r"\b([A-Za-z_$][A-Za-z0-9_$]{2,})\s*\(")
        for i, line in enumerate(lines, 1):
            cleaned = line.split("//")[0]
            for m in call_pattern.finditer(cleaned):
                cname = m.group(1)
                if cname not in _CONTROL_NAMES:
                    refs.append({"name": cname, "line": i, "kind": "call"})
                    edges.append({"src": "<module>", "dst": cname, "kind": "calls", "line": i})

        return syms, refs, edges

    def _parse_generic(self, text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        syms: list[dict[str, Any]] = []
        refs: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        lines = text.splitlines()
        brace_pairs, next_open = self._brace_metadata(lines)

        ns_pattern = re.compile(r"^\s*namespace\s+([A-Za-z0-9_\\]+)")
        curr_namespace = ""
        for line in lines:
            nm = ns_pattern.match(line)
            if nm:
                curr_namespace = nm.group(1).rstrip(";")
                break

        raw_syms: list[dict[str, Any]] = []
        for i, line in enumerate(lines, 1):
            m = GENERIC_DEF.match(line)
            kind = "symbol"
            name = ""
            if m:
                kind = m.group(1)
                name = m.group(2)
            else:
                for pattern in (ARROW_DEF, GO_METHOD, TYPED_METHOD, JS_METHOD):
                    mm = pattern.match(line)
                    if mm and mm.group(1).lower() not in _CONTROL_NAMES:
                        name = mm.group(1)
                        kind = "function"
                        break
            if name:
                raw_syms.append({
                    "name": name,
                    "kind": kind,
                    "line": i,
                    "end_line": i,
                    "container": curr_namespace,
                    "name_path": f"{curr_namespace}\\{name}" if curr_namespace else name,
                    "signature": line.strip()[:100],
                    "access": "public",
                    "docstring": "",
                })

            im = IMPORT.match(line)
            if im:
                dst = next((x for x in im.groups() if x), "")
                edges.append({"src": "<module>", "dst": dst, "kind": "imports", "line": i})

        for s in raw_syms:
            start_l = s["line"] - 1
            end_l = self._block_end_line(start_l, brace_pairs, next_open, 2500)
            s["end_line"] = max(s["line"], end_l)
            syms.append(s)

        call_re = re.compile(r"\b([A-Za-z_$][A-Za-z0-9_$]{2,})\s*\(")
        for i, line in enumerate(lines, 1):
            for m in call_re.finditer(line):
                name = m.group(1)
                if name.lower() not in _CONTROL_NAMES:
                    refs.append({"name": name, "line": i, "kind": "call"})
                    edges.append({"src": "<module>", "dst": name, "kind": "calls", "line": i})

        return syms, refs, edges

    def _parse_file_content(self, text: str, lang: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        if lang == "python":
            return self._parse_python(text)
        elif lang == "csharp":
            return self._parse_csharp(text)
        else:
            return self._parse_generic(text)

    def _parse_blob_get(self, content_hash: str, language: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]] | None:
        key = f"{content_hash}:{__version__}:{language}"
        cached = self._parse_blob_l1.get(key)
        if cached is not None:
            return cached
        try:
            with self._lock, closing(self._connect()) as con:
                row = con.execute("SELECT payload_json FROM parse_blobs WHERE content_hash=? AND analyzer_version=? AND language=?", (content_hash, __version__, language)).fetchone()
            if row:
                data = json.loads(str(row[0]))
                if isinstance(data, dict):
                    res = (list(data.get("symbols", [])), list(data.get("refs", [])), list(data.get("edges", [])))
                    self._parse_blob_l1.set(key, res)
                    return res
        except Exception:
            pass
        return None

    def _parse_blob_put(self, content_hash: str, language: str, syms: list[dict[str, Any]], refs: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
        key = f"{content_hash}:{__version__}:{language}"
        self._parse_blob_l1.set(key, (syms, refs, edges))
        try:
            payload = json.dumps({"symbols": syms, "refs": refs, "edges": edges}, ensure_ascii=False, separators=(",", ":"))
            with self._lock, closing(self._connect()) as con:
                con.execute("INSERT OR REPLACE INTO parse_blobs(content_hash, analyzer_version, language, payload_json, updated_at) VALUES(?,?,?,?,?)", (content_hash, __version__, language, payload, time.time()))
                count = int(con.execute("SELECT COUNT(*) FROM parse_blobs").fetchone()[0])
                if count > self.parse_blob_max:
                    con.execute("DELETE FROM parse_blobs WHERE rowid IN (SELECT rowid FROM parse_blobs ORDER BY updated_at ASC LIMIT ?)", (max(100, count - self.parse_blob_max),))
                con.commit()
        except Exception:
            pass

    def update_file(self, root: str, path: str, content_hash: str | None = None) -> dict[str, Any]:
        base = Path(canonical_root(root))
        target = (base / path).resolve(strict=False)
        try:
            target.relative_to(base)
        except ValueError:
            return {"success": False, "error": "invalid path"}
        if not target.is_file():
            with self._lock, closing(self._connect()) as con:
                for t in ("files", "symbols", "refs", "edges"):
                    con.execute(f"DELETE FROM {t} WHERE root=? AND path=?", (str(base), path))
                con.commit()
            return {"success": True, "deleted": True}

        digest, lines = self.repo_tools._read_snapshot(target)
        content_hash = content_hash or digest
        with self._lock, closing(self._connect()) as con:
            row = con.execute("SELECT content_hash FROM files WHERE root=? AND path=?", (str(base), path)).fetchone()
            if row and row[0] == content_hash:
                return {"success": True, "cached": True, "path": path}

        lang = self._lang(path)
        parsed = self._parse_blob_get(content_hash, lang)
        if parsed is None:
            text = "\n".join(lines)
            syms, refs, edges = self._parse_file_content(text, lang)
            self._parse_blob_put(content_hash, lang, syms, refs, edges)
        else:
            syms, refs, edges = parsed

        with self._lock, closing(self._connect()) as con:
            con.execute("BEGIN IMMEDIATE")
            for t in ("symbols", "refs", "edges"):
                con.execute(f"DELETE FROM {t} WHERE root=? AND path=?", (str(base), path))
            con.execute("INSERT OR REPLACE INTO files(root, path, content_hash, language, updated_at) VALUES(?,?,?,?,?)", (str(base), path, content_hash, lang, time.time()))
            con.executemany(
                "INSERT OR REPLACE INTO symbols(root, path, name, kind, line, end_line, container, name_path, signature, access, docstring) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                [(str(base), path, s["name"], s["kind"], s["line"], s["end_line"], s.get("container", ""), s.get("name_path", s["name"]), s.get("signature", ""), s.get("access", "public"), s.get("docstring", "")) for s in syms],
            )
            con.executemany("INSERT INTO refs(root, path, name, line, kind) VALUES(?,?,?,?,?)", [(str(base), path, r["name"], r["line"], r["kind"]) for r in refs])
            con.executemany("INSERT INTO edges(root, src, dst, kind, path, line) VALUES(?,?,?,?,?,?)", [(str(base), e["src"], e["dst"], e["kind"], path, e["line"]) for e in edges])
            con.commit()

        return {"success": True, "cached": False, "path": path, "symbols": len(syms), "refs": len(refs), "edges": len(edges)}

    def update_files_batch(self, root: str, items: list[str] | list[tuple[str, str]]) -> dict[str, Any]:
        """Batch-process files with one read phase and one SQLite write transaction."""
        base = Path(canonical_root(root))
        normalized: list[tuple[str, str | None]] = []
        for item in items:
            if isinstance(item, (tuple, list)) and len(item) >= 2:
                normalized.append((str(item[0]), str(item[1]) or None))
            else:
                normalized.append((str(item), None))
        if not normalized:
            return {"success": True, "files_processed": 0, "cached": 0, "symbols": 0, "refs": 0, "edges": 0}

        with self._lock, closing(self._connect()) as con:
            existing = dict(con.execute("SELECT path,content_hash FROM files WHERE root=?", (str(base),)).fetchall())

        candidates: list[tuple[str, str, str, list[str]]] = []
        cached = 0
        for path, supplied_hash in normalized:
            file_path = (base / path).resolve(strict=False)
            try:
                file_path.relative_to(base)
            except ValueError:
                continue
            if not file_path.is_file():
                continue
            lang = self._lang(path)
            if supplied_hash:
                if existing.get(path) == supplied_hash:
                    cached += 1
                    continue
                # A clean new worktree can reuse a parse blob from another root.
                # Check that content-addressed cache before opening the file.
                if self._parse_blob_get(supplied_hash, lang) is not None:
                    candidates.append((path, supplied_hash, lang, []))
                    continue
            try:
                digest, lines = self.repo_tools._read_snapshot(file_path)
            except OSError:
                continue
            content_hash = supplied_hash or digest
            if existing.get(path) == content_hash:
                cached += 1
                continue
            candidates.append((path, content_hash, lang, lines))

        blob_map: dict[tuple[str, str], tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]] = {}
        if candidates:
            pairs = list(dict.fromkeys((h, lang) for _, h, lang, _ in candidates))
            try:
                for i in range(0, len(pairs), 400):
                    batch = pairs[i:i + 400]
                    clauses = " OR ".join("(content_hash=? AND language=?)" for _ in batch)
                    params: list[Any] = []
                    for h, lang in batch:
                        params.extend([h, lang])
                    with self._lock, closing(self._connect()) as con:
                        rows = con.execute(f"SELECT content_hash,language,payload_json FROM parse_blobs WHERE analyzer_version=? AND ({clauses})", (__version__, *params)).fetchall()
                    for row in rows:
                        data = json.loads(str(row[2]))
                        if isinstance(data, dict):
                            blob_map[(str(row[0]), str(row[1]))] = (list(data.get("symbols", [])), list(data.get("refs", [])), list(data.get("edges", [])))
            except Exception:
                blob_map = {}

        files_to_insert: list[tuple[Any, ...]] = []
        syms_to_insert: list[tuple[Any, ...]] = []
        refs_to_insert: list[tuple[Any, ...]] = []
        edges_to_insert: list[tuple[Any, ...]] = []
        parse_blob_rows: list[tuple[Any, ...]] = []
        paths_to_clean: list[tuple[str, str]] = []
        now = time.time()
        for path, content_hash, lang, lines in candidates:
            parsed = blob_map.get((content_hash, lang))
            if parsed is None:
                syms, refs, edges = self._parse_file_content("\n".join(lines), lang)
                parse_blob_rows.append((content_hash, __version__, lang, json.dumps({"symbols": syms, "refs": refs, "edges": edges}, ensure_ascii=False, separators=(",", ":")), now))
            else:
                syms, refs, edges = parsed
            paths_to_clean.append((str(base), path))
            files_to_insert.append((str(base), path, content_hash, lang, now))
            syms_to_insert.extend((str(base), path, x["name"], x["kind"], x["line"], x["end_line"], x.get("container", ""), x.get("name_path", x["name"]), x.get("signature", ""), x.get("access", "public"), x.get("docstring", "")) for x in syms)
            refs_to_insert.extend((str(base), path, x["name"], x["line"], x["kind"]) for x in refs)
            edges_to_insert.extend((str(base), x["src"], x["dst"], x["kind"], path, x["line"]) for x in edges)

        if files_to_insert:
            with self._lock, closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                if parse_blob_rows:
                    con.executemany("INSERT OR REPLACE INTO parse_blobs(content_hash,analyzer_version,language,payload_json,updated_at) VALUES(?,?,?,?,?)", parse_blob_rows)
                _IDX_TABLES = frozenset({"symbols", "refs", "edges"})
                for table in ("symbols", "refs", "edges"):
                    assert table in _IDX_TABLES  # defence-in-depth whitelist
                    con.executemany(f"DELETE FROM {table} WHERE root=? AND path=?", paths_to_clean)  # noqa: S608
                con.executemany("INSERT OR REPLACE INTO files(root,path,content_hash,language,updated_at) VALUES(?,?,?,?,?)", files_to_insert)
                con.executemany("INSERT OR REPLACE INTO symbols(root,path,name,kind,line,end_line,container,name_path,signature,access,docstring) VALUES(?,?,?,?,?,?,?,?,?,?,?)", syms_to_insert)
                con.executemany("INSERT INTO refs(root,path,name,line,kind) VALUES(?,?,?,?,?)", refs_to_insert)
                con.executemany("INSERT INTO edges(root,src,dst,kind,path,line) VALUES(?,?,?,?,?,?)", edges_to_insert)
                con.commit()
        self._status_cache.pop(str(base), None)
        return {"success": True, "files_processed": len(files_to_insert), "cached": cached, "symbols": len(syms_to_insert), "refs": len(refs_to_insert), "edges": len(edges_to_insert), "parse_blob_hits": len(candidates) - len(parse_blob_rows)}

    @staticmethod
    def _query_terms(query: str) -> list[str]:
        return [t.lower() for t in tokenize_query_terms(query, min_len=2, max_terms=16)]

    def query(self, root: str, query: str, limit: int = 20) -> dict[str, Any]:
        """Search the built-in symbol index without requiring an external model.

        The endpoint intentionally returns compact symbol metadata. Agents can follow
        with ``find_symbol``/``inspect_symbol`` when source bodies are actually needed.
        """
        resolved_root = canonical_root(root)
        if not Path(resolved_root).is_dir():
            return {"success": False, "root": resolved_root, "error": "root directory does not exist", "stale_root": True}
        terms = self._query_terms(query)
        if not terms:
            return {"success": True, "root": resolved_root, "query": query, "terms": [], "matches_count": 0, "symbols": [], "confidence": 0.0}
        limit = max(1, min(int(limit), int(self.config.get("code_index", {}).get("max_query_results", 30))))
        cache_key = stable_hash({"root": resolved_root, "terms": terms, "limit": limit})
        cached = self._query_l1.get(cache_key)
        if isinstance(cached, dict):
            return copy.deepcopy(cached)

        clauses: list[str] = []
        args: list[Any] = [resolved_root]
        for term in terms:
            like = f"%{term}%"
            clauses.append("(lower(name) LIKE ? OR lower(name_path) LIKE ? OR lower(container) LIKE ? OR lower(path) LIKE ?)")
            args.extend([like, like, like, like])
        sql = (
            "SELECT path,name,kind,line,end_line,container,name_path,signature,access,docstring "
            "FROM symbols WHERE root=? AND (" + " OR ".join(clauses) + ") LIMIT ?"
        )
        args.append(max(limit * 12, 120))
        with self._lock, closing(self._connect()) as con:
            rows = con.execute(sql, args).fetchall()

        ranked: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            name = str(row["name"])
            name_l = name.lower()
            name_path = str(row["name_path"] or "")
            haystack = " ".join((name_l, name_path.lower(), str(row["container"] or "").lower(), str(row["path"]).lower()))
            score = 0.0
            for term in terms:
                if name_l == term:
                    score += 8.0
                elif name_l.startswith(term):
                    score += 5.0
                elif term in name_l:
                    score += 3.0
                elif term in haystack:
                    score += 1.0
            item = {
                "name": name,
                "name_path": name_path,
                "kind": str(row["kind"]),
                "path": str(row["path"]),
                "line": int(row["line"]),
                "end_line": int(row["end_line"] or row["line"]),
                "container": str(row["container"] or ""),
                "signature": str(row["signature"] or ""),
                "access": str(row["access"] or "public"),
                "score": round(score, 2),
            }
            ranked.append((score, item))
        ranked.sort(key=lambda x: (-x[0], x[1]["path"], x[1]["line"]))
        symbols = [item for _, item in ranked[:limit]]
        out = {
            "success": True,
            "root": resolved_root,
            "query": query,
            "terms": terms,
            "matches_count": len(symbols),
            "symbols": symbols,
            "confidence": round(min(1.0, len(symbols) * 0.1), 2) if symbols else 0.0,
        }
        self._query_l1.set(cache_key, out)
        return out

    def find_symbol(
        self,
        root: str,
        name_path_pattern: str,
        depth: int = 0,
        include_body: bool = False,
        include_info: bool = True,
        include_kinds: list[str] | None = None,
        exclude_kinds: list[str] | None = None,
        substring_matching: bool = False,
        relative_path: str | None = None,
        limit: int = 30,
    ) -> dict[str, Any]:
        resolved_root = canonical_root(root)
        pat = name_path_pattern.strip()
        if not pat:
            return {"success": False, "error": "name_path_pattern required"}

        where = ["root = ?"]
        args: list[Any] = [resolved_root]

        if relative_path:
            norm_path = relative_path.replace("\\", "/").strip("/")
            if "." in Path(norm_path).name:
                where.append("path = ?")
                args.append(norm_path)
            else:
                where.append("path LIKE ?")
                args.append(f"{norm_path}/%")

        if include_kinds:
            placeholders = ",".join("?" for _ in include_kinds)
            where.append(f"kind IN ({placeholders})")
            args.extend(include_kinds)

        if exclude_kinds:
            placeholders = ",".join("?" for _ in exclude_kinds)
            where.append(f"kind NOT IN ({placeholders})")
            args.extend(exclude_kinds)

        if substring_matching:
            where.append("(name_path LIKE ? OR name LIKE ?)")
            args.extend([f"%{pat}%", f"%{pat}%"])
        elif "/" in pat:
            where.append("(name_path = ? OR name_path LIKE ?)")
            args.extend([pat, f"%/{pat}"])
        else:
            where.append("(lower(name) = lower(?) OR name_path LIKE ? OR lower(name) LIKE ?)")
            args.extend([pat, f"%/{pat}", f"%{pat.lower()}%"])

        sql = f"SELECT path, name, kind, line, end_line, container, name_path, signature, access, docstring FROM symbols WHERE {' AND '.join(where)} ORDER BY path, line LIMIT ?"
        args.append(limit)

        with self._lock, closing(self._connect()) as con:
            rows = con.execute(sql, args).fetchall()

        results: list[dict[str, Any]] = []
        base_path = Path(resolved_root)

        for r in rows:
            p, name, kind, line = str(r["path"]), str(r["name"]), str(r["kind"]), int(r["line"])
            end_line = int(r["end_line"] or r["line"])
            name_path = str(r["name_path"])
            container = str(r["container"] or "")
            sig = str(r["signature"] or "")
            doc = str(r["docstring"] or "")

            item: dict[str, Any] = {
                "name": name,
                "name_path": name_path,
                "kind": kind,
                "path": p,
                "line": line,
                "end_line": end_line,
                "container": container,
            }

            if include_info:
                item["signature"] = sig
                item["docstring"] = doc
                item["access"] = str(r["access"] or "public")

            if include_body:
                file_full = base_path / p
                if file_full.is_file():
                    try:
                        flines = file_full.read_text(encoding="utf-8", errors="replace").splitlines()
                        item["body"] = "\n".join(flines[max(0, line - 1):min(len(flines), end_line)])
                    except Exception:
                        item["body"] = ""

            if depth > 0 and kind in {"class", "interface", "struct"}:
                with self._lock, closing(self._connect()) as con:
                    child_rows = con.execute(
                        "SELECT path, name, kind, line, end_line, name_path, signature FROM symbols WHERE root=? AND path=? AND container=? LIMIT 50",
                        (resolved_root, p, name),
                    ).fetchall()
                    item["children"] = [
                        {
                            "name": str(cr["name"]),
                            "name_path": str(cr["name_path"]),
                            "kind": str(cr["kind"]),
                            "line": int(cr["line"]),
                            "end_line": int(cr["end_line"] or cr["line"]),
                            "signature": str(cr["signature"] or ""),
                        }
                        for cr in child_rows
                    ]

            results.append(item)

        return {
            "success": True,
            "root": resolved_root,
            "pattern": pat,
            "matches_count": len(results),
            "symbols": results,
        }

    def find_declaration(self, root: str, symbol_name: str, path: str | None = None) -> dict[str, Any]:
        res = self.find_symbol(root, symbol_name, depth=0, include_body=True, include_info=True, relative_path=path, limit=5)
        symbols = res.get("symbols", [])
        if not symbols:
            return {"success": False, "error": f"Declaration of '{symbol_name}' not found"}
        return {"success": True, "declaration": symbols[0]}

    def find_implementations(self, root: str, symbol_name: str, path: str | None = None) -> dict[str, Any]:
        resolved_root = canonical_root(root)
        where = "root=? AND (lower(dst)=lower(?) OR dst LIKE ?) AND kind IN ('inherits', 'implements')"
        args: list[Any] = [resolved_root, symbol_name, f"%{symbol_name}%"]
        if path:
            where += " AND path=?"
            args.append(path.replace("\\", "/").strip("/"))
        with self._lock, closing(self._connect()) as con:
            edges = con.execute(
                f"SELECT src, dst, kind, path, line FROM edges WHERE {where} LIMIT 50",
                tuple(args),
            ).fetchall()

        implementations: list[dict[str, Any]] = []
        for e in edges:
            src_name = str(e["src"])
            p = str(e["path"])
            ln = int(e["line"])
            implementations.append({
                "implementer": src_name,
                "target": str(e["dst"]),
                "relationship": str(e["kind"]),
                "path": p,
                "line": ln,
            })

        return {
            "success": True,
            "symbol": symbol_name,
            "implementations_count": len(implementations),
            "implementations": implementations,
        }

    def find_referencing_symbols(self, root: str, symbol_name: str, path: str | None = None) -> dict[str, Any]:
        resolved_root = canonical_root(root)
        where = "root=? AND (lower(name)=lower(?) OR name LIKE ?)"
        args: list[Any] = [resolved_root, symbol_name, f"%{symbol_name}%"]
        if path:
            where += " AND path=?"
            args.append(path.replace("\\", "/").strip("/"))
        with self._lock, closing(self._connect()) as con:
            rows = con.execute(
                f"SELECT path, name, line, kind FROM refs WHERE {where} ORDER BY path, line LIMIT 100",
                tuple(args),
            ).fetchall()

        references = [
            {"path": str(r["path"]), "symbol": str(r["name"]), "line": int(r["line"]), "kind": str(r["kind"])}
            for r in rows
        ]

        return {
            "success": True,
            "symbol": symbol_name,
            "references_count": len(references),
            "references": references,
        }

    def get_symbols_overview(self, root: str, path: str, depth: int = 1) -> dict[str, Any]:
        resolved_root = canonical_root(root)
        norm_path = path.replace("\\", "/").strip("/")

        with self._lock, closing(self._connect()) as con:
            rows = con.execute(
                "SELECT name, kind, line, end_line, container, name_path, signature, access FROM symbols WHERE root=? AND path=? ORDER BY line",
                (resolved_root, norm_path),
            ).fetchall()

        overview: list[dict[str, Any]] = []
        for r in rows:
            overview.append({
                "name": str(r["name"]),
                "kind": str(r["kind"]),
                "line": int(r["line"]),
                "end_line": int(r["end_line"] or r["line"]),
                "container": str(r["container"] or ""),
                "name_path": str(r["name_path"] or r["name"]),
                "signature": str(r["signature"] or ""),
                "access": str(r["access"] or "public"),
            })

        return {
            "success": True,
            "path": norm_path,
            "symbols_count": len(overview),
            "symbols": overview,
        }

    def get_diagnostics_for_file(self, root: str, path: str) -> dict[str, Any]:
        resolved_root = Path(canonical_root(root)).resolve()
        target = (resolved_root / path).resolve()
        try:
            target.relative_to(resolved_root)
        except ValueError:
            return {"success": False, "error": f"path escapes root: {path}"}
        if not target.is_file():
            return {"success": False, "error": f"file not found: {path}"}

        errors: list[dict[str, Any]] = []
        lang = self._lang(path)

        if lang == "python":
            try:
                txt = target.read_text(encoding="utf-8", errors="replace")
                ast.parse(txt, filename=str(target))
            except (SyntaxError, OSError) as e:
                errors.append({
                    "line": getattr(e, "lineno", 1) or 1,
                    "column": getattr(e, "offset", 1) or 1,
                    "severity": "ERROR",
                    "message": str(getattr(e, "msg", e)),
                    "source": "python-ast",
                })
        elif lang == "json":
            try:
                txt = target.read_text(encoding="utf-8", errors="replace")
                json.loads(txt)
            except (json.JSONDecodeError, OSError) as e:
                errors.append({
                    "line": getattr(e, "lineno", 1),
                    "column": getattr(e, "colno", 1),
                    "severity": "ERROR",
                    "message": str(getattr(e, "msg", e)),
                    "source": "json-parser",
                })

        return {
            "success": True,
            "path": path,
            "clean": len(errors) == 0,
            "diagnostics_count": len(errors),
            "diagnostics": errors,
        }

    @staticmethod
    def _norm_rel(path: str) -> str:
        return str(path or "").replace("\\", "/").strip("/")

    @staticmethod
    def _is_test_path(path: str) -> bool:
        low = "/" + str(path or "").replace("\\", "/").lower()
        name = Path(low).name
        stem = Path(low).stem
        return (
            "/test" in low or "/spec" in low or name.startswith("test_")
            or any(marker in stem for marker in ("_test", ".test", "_spec", ".spec"))
        )

    def file_summary(self, root: str, path: str, limit: int = 80) -> dict[str, Any]:
        """Return compact pre-indexed facts for one file without reopening source text."""
        resolved_root = canonical_root(root)
        norm_path = self._norm_rel(path)
        limit = max(1, min(int(limit), 250))
        try:
            with self._lock, closing(self._connect()) as con:
                file_row = con.execute(
                    "SELECT content_hash,language,updated_at FROM files WHERE root=? AND path=?",
                    (resolved_root, norm_path),
                ).fetchone()
                symbols = [dict(r) for r in con.execute(
                    "SELECT name,kind,line,end_line,container,name_path,signature,access,docstring "
                    "FROM symbols WHERE root=? AND path=? ORDER BY line LIMIT ?",
                    (resolved_root, norm_path, limit),
                ).fetchall()]
                refs = [dict(r) for r in con.execute(
                    "SELECT name,line,kind FROM refs WHERE root=? AND path=? ORDER BY line LIMIT ?",
                    (resolved_root, norm_path, limit),
                ).fetchall()]
                edges = [dict(r) for r in con.execute(
                    "SELECT src,dst,kind,line FROM edges WHERE root=? AND path=? ORDER BY line LIMIT ?",
                    (resolved_root, norm_path, limit),
                ).fetchall()]
        except sqlite3.DatabaseError as exc:
            return {"success": False, "root": resolved_root, "path": norm_path, "error": str(exc), "busy": is_busy_error(exc)}
        if file_row is None:
            return {"success": False, "root": resolved_root, "path": norm_path, "indexed": False, "symbols": [], "references": [], "edges": []}
        return {
            "success": True,
            "root": resolved_root,
            "path": norm_path,
            "indexed": True,
            "content_hash": str(file_row["content_hash"] or ""),
            "language": str(file_row["language"] or "generic"),
            "updated_at": float(file_row["updated_at"] or 0.0),
            "symbols": symbols,
            "references": refs,
            "edges": edges,
        }

    def related_paths(self, root: str, query: str, limit: int = 30) -> list[str]:
        """Rank likely files entirely from the persistent code index.

        This is intentionally bounded and does not read repository files. It is used as
        a cheap candidate generator before lexical/RAG fallbacks.
        """
        resolved_root = canonical_root(root)
        terms = self._query_terms(query)
        if not terms:
            return []
        limit = max(1, min(int(limit), 100))
        scores: dict[str, float] = {}
        symbol_result = self.query(resolved_root, query, min(max(limit * 2, 20), 100))
        for item in symbol_result.get("symbols", []) if isinstance(symbol_result, dict) else []:
            path = self._norm_rel(str(item.get("path", "")))
            if path:
                scores[path] = scores.get(path, 0.0) + 8.0 + float(item.get("score", 0.0) or 0.0)

        clauses = " OR ".join("(lower(name) LIKE ? OR lower(path) LIKE ?)" for _ in terms)
        ref_args: list[Any] = [resolved_root]
        for term in terms:
            like = f"%{term}%"
            ref_args.extend([like, like])
        edge_clauses = " OR ".join("(lower(src) LIKE ? OR lower(dst) LIKE ? OR lower(path) LIKE ?)" for _ in terms)
        edge_args: list[Any] = [resolved_root]
        for term in terms:
            like = f"%{term}%"
            edge_args.extend([like, like, like])
        file_clauses = " OR ".join("lower(path) LIKE ?" for _ in terms)
        file_args: list[Any] = [resolved_root, *[f"%{term}%" for term in terms]]
        row_cap = max(80, limit * 12)
        try:
            with self._lock, closing(self._connect()) as con:
                for row in con.execute(
                    f"SELECT path,name,kind FROM refs WHERE root=? AND ({clauses}) LIMIT ?",
                    (*ref_args, row_cap),
                ).fetchall():
                    path = self._norm_rel(str(row["path"]))
                    scores[path] = scores.get(path, 0.0) + (4.0 if str(row["name"]).lower() in terms else 2.0)
                for row in con.execute(
                    f"SELECT path,src,dst,kind FROM edges WHERE root=? AND ({edge_clauses}) LIMIT ?",
                    (*edge_args, row_cap),
                ).fetchall():
                    path = self._norm_rel(str(row["path"]))
                    scores[path] = scores.get(path, 0.0) + (3.0 if str(row["kind"]) in {"imports", "inherits"} else 1.5)
                for row in con.execute(
                    f"SELECT path FROM files WHERE root=? AND ({file_clauses}) LIMIT ?",
                    (*file_args, row_cap),
                ).fetchall():
                    path = self._norm_rel(str(row["path"]))
                    scores[path] = scores.get(path, 0.0) + 2.0
        except sqlite3.DatabaseError:
            pass
        return [path for path, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit]]

    def prune(self, root: str, current_paths: list[str]) -> dict[str, Any]:
        """Remove stale per-workspace index rows in one short transaction."""
        resolved_root = canonical_root(root)
        current = {self._norm_rel(p) for p in current_paths if self._norm_rel(p)}
        try:
            with self._lock, closing(self._connect()) as con:
                indexed = {self._norm_rel(str(r[0])) for r in con.execute("SELECT path FROM files WHERE root=?", (resolved_root,)).fetchall()}
                stale = sorted(indexed - current)
                if not stale:
                    return {"success": True, "root": resolved_root, "pruned": 0}
                con.execute("BEGIN IMMEDIATE")
                pairs = [(resolved_root, path) for path in stale]
                for table in ("symbols", "refs", "edges", "files"):
                    con.executemany(f"DELETE FROM {table} WHERE root=? AND path=?", pairs)
                con.commit()
            self._status_cache.pop(resolved_root, None)
            return {"success": True, "root": resolved_root, "pruned": len(stale), "paths": stale[:100]}
        except sqlite3.DatabaseError as exc:
            return {"success": False, "root": resolved_root, "pruned": 0, "error": str(exc), "busy": is_busy_error(exc)}

    def impact(self, root: str, changed_paths: list[str], max_symbols: int = 48, max_dependents: int = 30) -> dict[str, Any]:
        """Resolve changed symbols, dependents and likely tests from SQLite only."""
        resolved_root = canonical_root(root)
        changed = list(dict.fromkeys(self._norm_rel(p) for p in changed_paths if self._norm_rel(p)))
        max_symbols = max(1, min(int(max_symbols), 200))
        max_dependents = max(1, min(int(max_dependents), 100))
        if not changed:
            return {"success": True, "root": resolved_root, "changed_symbols": [], "likely_dependents": [], "suggested_tests": [], "confidence": 1.0}

        try:
            with self._lock, closing(self._connect()) as con:
                # Bound host parameters so large diffs remain safe on every supported SQLite build.
                indexed_rows: list[sqlite3.Row] = []
                symbol_rows: list[sqlite3.Row] = []
                for offset in range(0, len(changed), 400):
                    chunk = changed[offset:offset + 400]
                    placeholders = ",".join("?" for _ in chunk)
                    indexed_rows.extend(con.execute(
                        f"SELECT path FROM files WHERE root=? AND path IN ({placeholders})",
                        (resolved_root, *chunk),
                    ).fetchall())
                    if len(symbol_rows) < max_symbols:
                        symbol_rows.extend(con.execute(
                            f"SELECT path,name,kind,line,name_path FROM symbols WHERE root=? AND path IN ({placeholders}) ORDER BY path,line LIMIT ?",
                            (resolved_root, *chunk, max_symbols - len(symbol_rows)),
                        ).fetchall())
                symbol_rows = symbol_rows[:max_symbols]
                changed_symbols = [
                    {"name": str(r["name"]), "name_path": str(r["name_path"] or r["name"]), "kind": str(r["kind"]), "path": str(r["path"]), "line": int(r["line"])}
                    for r in symbol_rows
                ]
                names = list(dict.fromkeys(str(r["name"]) for r in symbol_rows if str(r["name"])))
                dependent_scores: dict[str, dict[str, Any]] = {}
                if names:
                    name_placeholders = ",".join("?" for _ in names)
                    ref_rows = con.execute(
                        f"SELECT path,name,COUNT(*) AS mentions FROM refs WHERE root=? AND name IN ({name_placeholders}) GROUP BY path,name LIMIT ?",
                        (resolved_root, *names, max(200, max_dependents * 20)),
                    ).fetchall()
                    for r in ref_rows:
                        path = self._norm_rel(str(r["path"]))
                        if path in changed:
                            continue
                        item = dependent_scores.setdefault(path, {"path": path, "symbols": [], "mentions": 0})
                        name = str(r["name"])
                        if name not in item["symbols"] and len(item["symbols"]) < 8:
                            item["symbols"].append(name)
                        item["mentions"] += int(r["mentions"] or 0)
                    edge_rows = con.execute(
                        f"SELECT path,dst,kind FROM edges WHERE root=? AND dst IN ({name_placeholders}) LIMIT ?",
                        (resolved_root, *names, max(200, max_dependents * 20)),
                    ).fetchall()
                    for r in edge_rows:
                        path = self._norm_rel(str(r["path"]))
                        if path in changed:
                            continue
                        item = dependent_scores.setdefault(path, {"path": path, "symbols": [], "mentions": 0})
                        dst = str(r["dst"])
                        if dst not in item["symbols"] and len(item["symbols"]) < 8:
                            item["symbols"].append(dst)
                        item["mentions"] += 2 if str(r["kind"]) in {"imports", "inherits"} else 1

                likely_dependents = sorted(dependent_scores.values(), key=lambda x: (-int(x["mentions"]), str(x["path"])))[:max_dependents]
                indexed_tests = [self._norm_rel(str(r[0])) for r in con.execute(
                    "SELECT path FROM files WHERE root=? AND (lower(path) LIKE '%test%' OR lower(path) LIKE '%spec%') LIMIT 500",
                    (resolved_root,),
                ).fetchall()]
        except sqlite3.DatabaseError as exc:
            return {"success": False, "root": resolved_root, "error": str(exc), "busy": is_busy_error(exc), "confidence": 0.0}

        changed_stems = {Path(p).stem.lower().replace("test_", "").replace("_test", "").replace(".test", "").replace("_spec", "").replace(".spec", "") for p in changed}
        symbol_names_l = [str(x["name"]).lower() for x in changed_symbols]
        test_scores: list[tuple[int, str]] = []
        for path in indexed_tests:
            stem = Path(path).stem.lower().replace("test_", "").replace("_test", "").replace(".test", "").replace("_spec", "").replace(".spec", "")
            score = sum(3 for changed_stem in changed_stems if changed_stem and (changed_stem in stem or stem in changed_stem))
            score += sum(1 for name in symbol_names_l[:20] if name and name in path.lower())
            if score:
                test_scores.append((score, path))
        for item in likely_dependents:
            path = str(item["path"])
            if self._is_test_path(path):
                test_scores.append((max(1, int(item["mentions"])), path))
        suggested_tests = [{"path": path, "score": score} for score, path in sorted(set(test_scores), key=lambda x: (-x[0], x[1]))[:20]]
        indexed_count = len(indexed_rows)
        coverage = indexed_count / max(1, len(changed))
        confidence = round(min(0.98, 0.35 + 0.60 * coverage + (0.03 if changed_symbols else 0.0)), 3)
        return {
            "success": True,
            "root": resolved_root,
            "changed_symbols": changed_symbols,
            "likely_dependents": likely_dependents,
            "suggested_tests": suggested_tests,
            "confidence": confidence,
            "indexed_changed_files": indexed_count,
            "changed_files_count": len(changed),
        }

    def inspect_symbol(self, root: str, symbol_name: str) -> dict[str, Any]:
        decl = self.find_declaration(root, symbol_name)
        if decl.get("success"):
            d = decl["declaration"]
            return {
                "success": True,
                "root": canonical_root(root),
                "name": d["name"],
                "kind": d["kind"],
                "path": d["path"],
                "line": d["line"],
                "end_line": d["end_line"],
                "container": d.get("container", ""),
                "signature": d.get("signature", ""),
                "snippet": d.get("body", ""),
            }
        return {"success": False, "error": f"Symbol '{symbol_name}' not found"}

    def status(self, root: str | None = None) -> dict[str, Any]:
        now = time.monotonic()
        key = str(root or "__all__")
        with self._lock:
            cached = self._status_cache.get(key)
            if cached and now - cached["time"] < 5.0:
                return dict(cached["data"])
        try:
            # Table names are compile-time constants; validate against explicit whitelist
            # before f-string interpolation as defence-in-depth.
            _ALLOWED_TABLES = {"files", "symbols", "refs", "edges"}
            with self._lock, closing(self._connect()) as con:
                where = " WHERE root=?" if root else ""
                args = (canonical_root(root),) if root else ()
                vals = {t: int(con.execute(f"SELECT COUNT(*) FROM {t}{where}", args).fetchone()[0])  # noqa: S608
                        for t in _ALLOWED_TABLES}
            res = {"success": True, "healthy": True, **vals}
            with self._lock:
                self._status_cache[key] = {"time": now, "data": res}
            return res
        except sqlite3.DatabaseError as exc:
            return {"success": False, "healthy": False, "error": str(exc)}
