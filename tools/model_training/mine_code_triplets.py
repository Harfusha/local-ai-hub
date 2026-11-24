"""Code Triplet Mining Engine with Hard Negative Sampling.

Extracts high-value training triplets for Embeddings and Reranker fine-tuning:
- Anchor (Query): Natural language description / intent synthesized from docstring, section header, or symbol.
- Positive (Code Chunk): Exact implementation of the function, procedure, method, or semantic block.
- Hard Negative (Confuser Chunk): A sibling function from the same module/subsystem sharing
  high lexical token overlap or domain proximity but implementing a different semantic capability.

Produces JSONL datasets for Cross-Encoder MarginMSE / BCE and Bi-Encoder InfoNCE training.
Operates reliably across all programming languages, markup/config formats, encodings, and project structures.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

try:
    import tree_sitter
    import tree_sitter_language_pack as tslp
except ImportError:
    tree_sitter = None
    tslp = None

logger = logging.getLogger(__name__)

TOKEN_REGEX = re.compile(r"[A-Za-z0-9_\u00C0-\u017F]+")
AST_BIN = shutil.which("ast-grep") or shutil.which("sg")

AST_GREP_LANG_KINDS: dict[str, tuple[str, list[str]]] = {
    "rust": ("rust", ["function_item", "impl_item"]),
    "rs": ("rust", ["function_item", "impl_item"]),
    "python": ("python", ["function_definition"]),
    "py": ("python", ["function_definition"]),
    "go": ("go", ["function_declaration", "method_declaration"]),
    "typescript": ("typescript", ["function_declaration", "method_definition", "arrow_function"]),
    "ts": ("typescript", ["function_declaration", "method_definition"]),
    "tsx": ("tsx", ["function_declaration", "method_definition"]),
    "javascript": ("javascript", ["function_declaration", "method_definition", "arrow_function"]),
    "js": ("javascript", ["function_declaration", "method_definition"]),
    "jsx": ("jsx", ["function_declaration", "method_definition"]),
    "kotlin": ("kotlin", ["function_declaration", "secondary_constructor"]),
    "kt": ("kotlin", ["function_declaration", "secondary_constructor"]),
    "java": ("java", ["method_declaration", "constructor_declaration"]),
    "c": ("c", ["function_definition"]),
    "cpp": ("cpp", ["function_definition"]),
    "c_sharp": ("c_sharp", ["method_declaration", "local_function_statement", "constructor_declaration"]),
    "cs": ("c_sharp", ["method_declaration", "local_function_statement", "constructor_declaration"]),
    "php": ("php", ["function_definition", "method_declaration"]),
    "ruby": ("ruby", ["method", "singleton_method"]),
    "rb": ("ruby", ["method", "singleton_method"]),
    "lua": ("lua", ["function_declaration", "local_function"]),
    "scala": ("scala", ["function_definition", "method_definition"]),
    "swift": ("swift", ["function_declaration"]),
    "bash": ("bash", ["function_definition"]),
    "sh": ("bash", ["function_definition"]),
}


def read_text_safe(f_path: Path, max_bytes: int = 512 * 1024) -> str | None:
    """Read source file across all international encodings, rejecting binaries and minified assets."""
    try:
        raw = f_path.read_bytes()
    except Exception:
        return None

    if not raw or len(raw) < 20 or len(raw) > max_bytes:
        return None

    # Handle UTF-16 BOMs
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        for enc in ("utf-16", "utf-16le", "utf-16be"):
            try:
                return raw.decode(enc)
            except Exception:
                pass
        return None

    # Binary check: null bytes in initial 8KB indicates binary/executable/compiled asset
    if b"\x00" in raw[:8192]:
        return None

    # Text encodings with fallbacks: UTF-8 with BOM, standard UTF-8, Windows CP1250 (Central European/Czech), Latin-1
    for enc in ("utf-8-sig", "utf-8", "cp1250", "latin1"):
        try:
            text = raw.decode(enc)
            first_lines = text.splitlines()[:50]
            if first_lines:
                # Reject minified/bundled files with single massive lines
                if any(len(l) > 1200 for l in first_lines):
                    return None
                avg_len = sum(len(l) for l in first_lines) / max(1, len(first_lines))
                if avg_len > 350:
                    return None
            return text
        except UnicodeDecodeError:
            continue
        except Exception:
            pass

    return None


def _extract_symbol_name_from_text(text: str) -> str:
    """Universal symbol extractor from declaration headers across polyglot languages."""
    first_lines = text.splitlines()[:4]
    header = " ".join(l.strip() for l in first_lines)

    # Markdown section header: ## Section Title or # Title
    m_md = re.match(r"^#{1,6}\s+([^\n\r]+)", header)
    if m_md:
        return re.sub(r"[^A-Za-z0-9_\u00C0-\u017F]+", "_", m_md.group(1).strip()).strip("_")

    # SQL CREATE TABLE / PROCEDURE / FUNCTION / VIEW
    m_sql = re.search(
        r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|PROCEDURE|FUNCTION|VIEW|TRIGGER|INDEX)\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_\u00C0-\u017F\.]+)",
        header,
        re.IGNORECASE,
    )
    if m_sql:
        return m_sql.group(1).replace(".", "_")

    # Polyglot function keyword match
    m = re.search(
        r"\b(?:fn|func|function|def|fun|sub|procedure)\s+(?:\([^)]*\)\s*)?([A-Za-z0-9_\u00C0-\u017F]+)",
        header,
    )
    if m:
        return m.group(1)

    # Rust impl Trait for Type or impl Type
    m_impl = re.search(
        r"\bimpl(?:\s*<[^>]+>)?\s+([A-Za-z0-9_]+)(?:\s+for\s+([A-Za-z0-9_]+))?",
        header,
    )
    if m_impl:
        trait_name = m_impl.group(1)
        type_name = m_impl.group(2)
        return f"impl_{trait_name}_for_{type_name}" if type_name else f"impl_{trait_name}"

    # JS/TS variable assigned to function / arrow function: const myFunc = (args) =>
    m_arrow = re.search(
        r"\b(?:const|let|var)\s+([A-Za-z0-9_\u00C0-\u017F]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z0-9_]+)\s*=>",
        header,
    )
    if m_arrow:
        return m_arrow.group(1)

    # C / C++ / Java / C# signature
    m_sig = re.search(
        r"\b([A-Za-z0-9_\u00C0-\u017F]+)\s*\([^)]*\)\s*(?:->|[:{]|throws|const|noexcept|where)",
        header,
    )
    if m_sig and m_sig.group(1) not in {"if", "for", "while", "switch", "catch", "return", "match"}:
        return m_sig.group(1)

    return ""


_LANGUAGE_QUERIES: dict[str, str] = {
    "rust": "(function_item name: (identifier) @name) @func",
    "python": "(function_definition name: (identifier) @name) @func",
    "javascript": "[(function_declaration name: (identifier) @name) (method_definition name: (property_identifier) @name)] @func",
    "typescript": "[(function_declaration name: (identifier) @name) (method_definition name: (property_identifier) @name)] @func",
    "tsx": "[(function_declaration name: (identifier) @name) (method_definition name: (property_identifier) @name)] @func",
    "go": "[(function_declaration name: (identifier) @name) (method_declaration name: (field_identifier) @name)] @func",
    "c": "(function_definition declarator: (function_declarator declarator: (identifier) @name)) @func",
    "cpp": "(function_definition declarator: (function_declarator declarator: (identifier) @name)) @func",
    "java": "(method_declaration name: (identifier) @name) @func",
    "kotlin": "(function_declaration (simple_identifier) @name) @func",
    "php": "[(function_definition name: (name) @name) (method_declaration name: (name) @name)] @func",
    "c_sharp": "[(method_declaration name: (identifier) @name) (local_function_statement name: (identifier) @name)] @func",
    "ruby": "(method name: (identifier) @name) @func",
}

_QUERIES: dict[str, Any] = {}
_PARSERS: dict[str, Any] = {}


@dataclass(frozen=True)
class CodeChunk:
    symbol_name: str
    file_path: str
    code_text: str
    docstring: str
    tokens: tuple[str, ...]


@dataclass(frozen=True)
class CodeTriplet:
    query: str
    positive: str
    negative: str
    file_path: str
    positive_symbol: str
    negative_symbol: str
    lexical_overlap: float

    def to_dict(self) -> dict[str, str | float]:
        return asdict(self)


class CodeTripletMiner:
    """Universal polyglot triplet miner supporting any programming and human language."""

    _BINARY_EXTENSIONS = {
        ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".tar", ".gz",
        ".7z", ".exe", ".dll", ".so", ".dylib", ".bin", ".pyc", ".pyd", ".o",
        ".obj", ".class", ".wasm", ".sqlite", ".sqlite3", ".db", ".lock", ".sum",
        ".svg", ".webp", ".mp3", ".mp4", ".woff", ".woff2", ".ttf", ".eot",
    }

    _EXCLUDED_DIR_NAMES = {
        "node_modules", ".git", ".venv", "venv", "__pycache__",
        ".pytest_cache", ".next", ".turbo", "dist", "build", "target", "coverage",
        ".gradle", ".idea", ".vscode", "vendor",
    }

    _EXCLUDED_FILE_PATTERNS = [
        ".min.", ".bundle.", ".chunk.", ".map.", ".d.ts",
        "package-lock.json", "yarn.lock", "cargo.lock", "poetry.lock", "composer.lock", "go.sum",
    ]

    def __init__(self, min_chunk_lines: int = 3, max_chunk_lines: int = 80) -> None:
        self.min_chunk_lines = min_chunk_lines
        self.max_chunk_lines = max_chunk_lines

    def _extract_preceding_doc(self, lines: list[str], start_idx: int) -> str:
        """Extract preceding doc comments across any human language and comment convention."""
        doc_lines: list[str] = []
        d_idx = start_idx - 1
        while d_idx >= 0:
            prev = lines[d_idx].strip()
            # Match universal comment prefixes: //, ///, #, --, ;, %, /*, *, """
            if (
                prev.startswith("//") or prev.startswith("///") or prev.startswith("#")
                or prev.startswith("--") or prev.startswith(";") or prev.startswith("%")
                or prev.startswith("*")
            ):
                clean_doc = re.sub(r"^[/*#;%~-]+\s*", "", prev).strip()
                if clean_doc and not any(k in clean_doc.lower() for k in ["copyright", "license", "@ts-"]):
                    doc_lines.insert(0, clean_doc)
                d_idx -= 1
            elif prev.startswith("/*") or prev.startswith('"""') or prev.startswith("'''"):
                d_idx -= 1
                break
            else:
                break
        return " ".join(doc_lines)

    def _extract_via_tree_sitter(
        self,
        source_code: str,
        file_path: str,
        lines: list[str],
    ) -> list[CodeChunk]:
        """Extract exact AST definitions using tree_sitter queries."""
        if not tslp or not tree_sitter:
            return []

        lang = None
        if file_path:
            try:
                lang = tslp.detect_language_from_path(file_path)
            except Exception:
                pass
            if not lang:
                ext = os.path.splitext(file_path)[1].lstrip(".")
                try:
                    lang = tslp.detect_language_from_extension(ext)
                except Exception:
                    pass

        if not lang or not tslp.has_language(lang):
            return []

        chunks: list[CodeChunk] = []
        seen_spans: set[tuple[int, int]] = set()

        try:
            language_obj = tslp.get_language(lang)
            if lang not in _QUERIES:
                q_str = _LANGUAGE_QUERIES.get(lang)
                if not q_str:
                    q_str = "[(function_item name: (identifier) @name) (function_definition name: (identifier) @name) (function_declaration name: (identifier) @name) (method_declaration name: (identifier) @name)] @func"
                try:
                    _QUERIES[lang] = tree_sitter.Query(language_obj, q_str)
                except Exception:
                    _QUERIES[lang] = None

            query = _QUERIES.get(lang)
            if not query:
                return []

            if lang not in _PARSERS:
                _PARSERS[lang] = tslp.get_parser(lang)
            parser = _PARSERS[lang]

            source_bytes = source_code.encode("utf-8", errors="ignore")
            tree = parser.parse(source_bytes)
            cursor = tree_sitter.QueryCursor(query)
            matches = cursor.matches(tree.root_node)

            for idx, (_, match_dict) in enumerate(matches):
                func_nodes = match_dict.get("func", [])
                name_nodes = match_dict.get("name", [])
                if not func_nodes or not name_nodes:
                    continue

                fn = func_nodes[0]
                nn = name_nodes[0]
                try:
                    sym = source_bytes[nn.start_byte:nn.end_byte].decode("utf-8", errors="ignore")
                except Exception:
                    continue
                if not sym:
                    continue

                start = fn.start_point.row
                end = fn.end_point.row + 1
                if start < 0 or start >= len(lines) or end > len(lines) + 1:
                    continue
                length = end - start
                span = (start, end)
                if self.min_chunk_lines <= length <= self.max_chunk_lines and span not in seen_spans:
                    seen_spans.add(span)
                    chunk_text = "\n".join(lines[start:end])
                    doc = self._extract_preceding_doc(lines, start)
                    if not doc:
                        for cl in lines[start + 1:min(start + 4, end)]:
                            cls = cl.strip()
                            if cls.startswith(('"""', "'''")):
                                clean = re.sub(r'^["\'\s]+|["\'\s]+$', '', cls).strip()
                                if len(clean) > 8:
                                    doc = clean
                                    break
                    tokens = tuple(sorted(list(set(TOKEN_REGEX.findall(chunk_text.lower())))))
                    chunks.append(CodeChunk(
                        symbol_name=sym,
                        file_path=file_path,
                        code_text=chunk_text,
                        docstring=doc,
                        tokens=tokens,
                    ))
        except Exception as exc:
            logger.debug("Tree-sitter parse failed for %s: %s", file_path, exc)

        return chunks

    def _extract_via_ast_grep(
        self,
        source_code: str,
        file_path: str,
        lines: list[str],
    ) -> list[CodeChunk]:
        """Extract exact AST definitions using industry-standard, high-performance ast-grep."""
        if not AST_BIN:
            return []

        ext = os.path.splitext(file_path)[1].lstrip(".").lower() if file_path else ""
        mapping = AST_GREP_LANG_KINDS.get(ext)
        if not mapping:
            return []

        lang_name, kinds = mapping
        chunks: list[CodeChunk] = []
        seen_spans: set[tuple[int, int]] = set()

        for kind in kinds:
            try:
                if os.path.exists(file_path):
                    cmd = [AST_BIN, "run", "--kind", kind, "--json", str(file_path)]
                    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", shell=False, timeout=5)
                else:
                    cmd = [AST_BIN, "run", "--kind", kind, "--stdin", "--lang", lang_name, "--json"]
                    proc = subprocess.run(cmd, input=source_code, capture_output=True, text=True, encoding="utf-8", shell=False, timeout=5)

                if proc.returncode != 0:
                    if proc.stderr:
                        logger.debug("ast-grep exited %d for %s (kind %s): %s", proc.returncode, file_path, kind, proc.stderr[:500])
                    continue
                if not proc.stdout.strip():
                    continue

                items = json.loads(proc.stdout)
                for item in items:
                    range_info = item.get("range", {})
                    start_line = range_info.get("start", {}).get("line", 0)
                    end_line = range_info.get("end", {}).get("line", start_line + 1) + 1
                    span = (start_line, end_line)
                    length = end_line - start_line
                    if self.min_chunk_lines <= length <= self.max_chunk_lines and span not in seen_spans:
                        seen_spans.add(span)
                        code_text = item.get("text", "")
                        sym = _extract_symbol_name_from_text(code_text) or f"func_L{start_line}"
                        doc = self._extract_preceding_doc(lines, start_line)
                        if not doc:
                            for cl in lines[start_line + 1:min(start_line + 4, end_line)]:
                                cls = cl.strip()
                                if cls.startswith(('"""', "'''")):
                                    clean = re.sub(r'^["\'\s]+|["\'\s]+$', '', cls).strip()
                                    if len(clean) > 8:
                                        doc = clean
                                        break
                        tokens = tuple(sorted(list(set(TOKEN_REGEX.findall(code_text.lower())))))
                        chunks.append(CodeChunk(
                            symbol_name=sym,
                            file_path=file_path,
                            code_text=code_text,
                            docstring=doc,
                            tokens=tokens,
                        ))
            except Exception as exc:
                logger.debug("ast-grep extraction failed for %s (kind %s): %s", file_path, kind, exc)

        return chunks

    def _extract_via_markdown_chunker(self, lines: list[str], file_path: str) -> list[CodeChunk]:
        """Extract structured Markdown sections with headings as symbols and docstrings."""
        chunks: list[CodeChunk] = []
        current_heading = ""
        current_lines: list[str] = []

        for line in lines:
            m = re.match(r"^(#{1,6})\s+([^\n\r]+)", line)
            if m:
                if len(current_lines) >= self.min_chunk_lines:
                    chunk_text = "\n".join(current_lines[:self.max_chunk_lines])
                    tokens = tuple(sorted(list(set(TOKEN_REGEX.findall(chunk_text.lower())))))
                    sym = re.sub(r"[^A-Za-z0-9_\u00C0-\u017F]+", "_", current_heading).strip("_") or "section"
                    chunks.append(CodeChunk(
                        symbol_name=sym,
                        file_path=file_path,
                        code_text=chunk_text,
                        docstring=current_heading,
                        tokens=tokens,
                    ))
                current_heading = m.group(2).strip()
                current_lines = [line]
            else:
                current_lines.append(line)

        if len(current_lines) >= self.min_chunk_lines:
            chunk_text = "\n".join(current_lines[:self.max_chunk_lines])
            tokens = tuple(sorted(list(set(TOKEN_REGEX.findall(chunk_text.lower())))))
            sym = re.sub(r"[^A-Za-z0-9_\u00C0-\u017F]+", "_", current_heading).strip("_") or "section"
            chunks.append(CodeChunk(
                symbol_name=sym,
                file_path=file_path,
                code_text=chunk_text,
                docstring=current_heading,
                tokens=tokens,
            ))

        return chunks

    def _extract_via_sql_chunker(self, lines: list[str], file_path: str) -> list[CodeChunk]:
        """Extract cohesive SQL statements (DDL, queries, procedures) as distinct units."""
        chunks: list[CodeChunk] = []
        block_lines: list[str] = []
        block_start = 0

        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                if len(block_lines) >= self.min_chunk_lines:
                    chunk_text = "\n".join(block_lines[:self.max_chunk_lines])
                    tokens = tuple(sorted(list(set(TOKEN_REGEX.findall(chunk_text.lower())))))
                    sym = _extract_symbol_name_from_text(chunk_text) or f"sql_block_L{block_start}"
                    doc = self._extract_preceding_doc(lines, block_start)
                    chunks.append(CodeChunk(
                        symbol_name=sym,
                        file_path=file_path,
                        code_text=chunk_text,
                        docstring=doc,
                        tokens=tokens,
                    ))
                block_lines = []
                block_start = idx + 1
            else:
                block_lines.append(line)

        if len(block_lines) >= self.min_chunk_lines:
            chunk_text = "\n".join(block_lines[:self.max_chunk_lines])
            tokens = tuple(sorted(list(set(TOKEN_REGEX.findall(chunk_text.lower())))))
            sym = _extract_symbol_name_from_text(chunk_text) or f"sql_block_L{block_start}"
            doc = self._extract_preceding_doc(lines, block_start)
            chunks.append(CodeChunk(
                symbol_name=sym,
                file_path=file_path,
                code_text=chunk_text,
                docstring=doc,
                tokens=tokens,
            ))

        return chunks

    def extract_chunks_from_source(self, source_code: str, file_path: str = "") -> list[CodeChunk]:
        """Extract code chunks using AST tools with Python AST, Markdown, SQL, and semantic fallbacks."""
        lines = source_code.splitlines()
        ext = os.path.splitext(file_path)[1].lower() if file_path else ""

        # Markdown / Documentation extractor
        if ext in {".md", ".markdown", ".rst"}:
            md_chunks = self._extract_via_markdown_chunker(lines, file_path)
            if md_chunks:
                return md_chunks

        # SQL extractor
        if ext in {".sql", ".ddl", ".psql"}:
            sql_chunks = self._extract_via_sql_chunker(lines, file_path)
            if sql_chunks:
                return sql_chunks

        # Python AST parser for .py (rock solid, fastest)
        if ext == ".py" or not file_path:
            try:
                tree = ast.parse(source_code)
                py_chunks: list[CodeChunk] = []
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        start = getattr(node, "lineno", 1) - 1
                        end = getattr(node, "end_lineno", len(lines))
                        length = end - start
                        if self.min_chunk_lines <= length <= self.max_chunk_lines:
                            chunk_text = "\n".join(lines[start:end])
                            doc = ast.get_docstring(node) or ""
                            tokens = tuple(sorted(list(set(TOKEN_REGEX.findall(chunk_text.lower())))))
                            py_chunks.append(CodeChunk(
                                symbol_name=node.name,
                                file_path=file_path,
                                code_text=chunk_text,
                                docstring=doc,
                                tokens=tokens,
                            ))
                if py_chunks:
                    return py_chunks
            except SyntaxError:
                pass

        # Tier 1: In-process Tree-Sitter AST extractor (ultra fast, polyglot)
        if tslp and tree_sitter and file_path:
            ts_chunks = self._extract_via_tree_sitter(source_code, file_path, lines)
            if ts_chunks:
                return ts_chunks

        # Tier 2: Industry-standard ast-grep AST extractor for all polyglot languages
        if AST_BIN and file_path:
            ag_chunks = self._extract_via_ast_grep(source_code, file_path, lines)
            if ag_chunks:
                return ag_chunks

        # Tier 3: Universal Semantic Block / Paragraph Fallback
        fallback_chunks: list[CodeChunk] = []
        block_lines: list[str] = []
        block_start = 0
        for idx, line in enumerate(lines):
            if not line.strip():
                if len(block_lines) >= self.min_chunk_lines:
                    chunk_text = "\n".join(block_lines[:self.max_chunk_lines])
                    tokens = tuple(sorted(list(set(TOKEN_REGEX.findall(chunk_text.lower())))))
                    sym = _extract_symbol_name_from_text(chunk_text)
                    if not sym:
                        first_text = block_lines[0].strip()
                        sym = re.sub(r"[^A-Za-z0-9_\u00C0-\u017F]+", "_", first_text[:30]).strip("_") or f"block_L{block_start}"
                    doc = self._extract_preceding_doc(lines, block_start)
                    fallback_chunks.append(CodeChunk(
                        symbol_name=sym,
                        file_path=file_path,
                        code_text=chunk_text,
                        docstring=doc,
                        tokens=tokens,
                    ))
                block_lines = []
                block_start = idx + 1
            else:
                block_lines.append(line)

        if len(block_lines) >= self.min_chunk_lines:
            chunk_text = "\n".join(block_lines[:self.max_chunk_lines])
            tokens = tuple(sorted(list(set(TOKEN_REGEX.findall(chunk_text.lower())))))
            sym = _extract_symbol_name_from_text(chunk_text)
            if not sym:
                first_text = block_lines[0].strip()
                sym = re.sub(r"[^A-Za-z0-9_\u00C0-\u017F]+", "_", first_text[:30]).strip("_") or f"block_L{block_start}"
            doc = self._extract_preceding_doc(lines, block_start)
            fallback_chunks.append(CodeChunk(
                symbol_name=sym,
                file_path=file_path,
                code_text=chunk_text,
                docstring=doc,
                tokens=tokens,
            ))

        return fallback_chunks

    def synthesize_query(self, chunk: CodeChunk) -> str:
        """Derive natural query in any human language without enforcing English templates."""
        # If author provided docstrings/comments in ANY human language (Czech, German, English, etc.), use it directly
        if chunk.docstring:
            first_sentence = re.split(r"[.\n;]", chunk.docstring.strip())[0].strip()
            if len(first_sentence) > 8:
                return first_sentence

        # Handle Rust impl Trait for Struct
        if chunk.symbol_name.startswith("impl_") and "_for_" in chunk.symbol_name:
            parts = chunk.symbol_name[5:].split("_for_")
            return f"implement {parts[0]} for {parts[1]}"

        # Universal symbol decomposition preserving multilingual / Unicode tokens
        words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", chunk.symbol_name)
        words = words.replace("_", " ").strip()
        fname = os.path.basename(chunk.file_path) if chunk.file_path else ""

        if fname:
            return f"{words} in {fname}"
        return words or "code implementation"

    def mine_triplets(self, chunks: Sequence[CodeChunk]) -> list[CodeTriplet]:
        """Pair each chunk with an intra-corpus hard negative based on token overlap and structural proximity."""
        triplets: list[CodeTriplet] = []
        if len(chunks) < 2:
            return triplets

        for i, pos in enumerate(chunks):
            query = self.synthesize_query(pos)
            pos_tokens = set(pos.tokens)
            pos_parent = Path(pos.file_path).parent if pos.file_path else None
            pos_ext = Path(pos.file_path).suffix.lower() if pos.file_path else ""

            best_neg: CodeChunk | None = None
            best_score = -1.0

            for j, neg in enumerate(chunks):
                if i == j or neg.symbol_name == pos.symbol_name:
                    continue
                # Skip duplicate identical code snippets
                if pos.code_text.strip() == neg.code_text.strip():
                    continue

                neg_tokens = set(neg.tokens)
                common = len(pos_tokens & neg_tokens)
                total = len(pos_tokens | neg_tokens)
                jaccard = common / max(1, total)

                # Penalize trivial near-duplicates
                if jaccard > 0.95:
                    continue

                # Hierarchical proximity boost: same file > same directory > same language
                proximity_boost = 0.0
                if pos.file_path and neg.file_path:
                    if pos.file_path == neg.file_path:
                        proximity_boost = 0.30
                    elif pos_parent and Path(neg.file_path).parent == pos_parent:
                        proximity_boost = 0.15
                    elif pos_ext and Path(neg.file_path).suffix.lower() == pos_ext:
                        proximity_boost = 0.05

                effective_score = jaccard + proximity_boost

                if effective_score > best_score:
                    best_score = effective_score
                    best_neg = neg

            # Fallback: if no negative found via high overlap, pick any distinct sibling chunk
            if not best_neg:
                for j, neg in enumerate(chunks):
                    if i != j and neg.symbol_name != pos.symbol_name and pos.code_text.strip() != neg.code_text.strip():
                        best_neg = neg
                        best_score = 0.01
                        break

            if best_neg:
                triplets.append(CodeTriplet(
                    query=query,
                    positive=pos.code_text,
                    negative=best_neg.code_text,
                    file_path=pos.file_path,
                    positive_symbol=pos.symbol_name,
                    negative_symbol=best_neg.symbol_name,
                    lexical_overlap=round(max(0.0, best_score), 4),
                ))

        return triplets

    def mine_from_directory(
        self,
        directory: str | Path,
        output_file: str | Path | None = None,
        max_files: int = 100,
        allowed_extensions: Sequence[str] | None = None,
    ) -> list[CodeTriplet]:
        """Scan directory of any source files and write mined triplets to JSONL with universal fallback."""
        dir_p = Path(directory)
        all_chunks: list[CodeChunk] = []
        ext_filter = set(allowed_extensions) if allowed_extensions else None

        files_scanned = 0
        for root, dirs, files in os.walk(dir_p):
            dirs[:] = [d for d in dirs if d.lower() not in self._EXCLUDED_DIR_NAMES]
            for f in sorted(files):
                ext = Path(f).suffix.lower()
                if ext in self._BINARY_EXTENSIONS:
                    continue
                if any(pat in f.lower() for pat in self._EXCLUDED_FILE_PATTERNS):
                    continue
                if ext_filter and ext not in ext_filter:
                    continue
                if f.startswith("test_") or f.endswith("_test.go") or f.endswith(".test.ts") or f.endswith(".spec.ts"):
                    continue

                f_path = Path(root) / f
                content = read_text_safe(f_path)
                if not content or len(content.strip()) < 40:
                    continue

                chunks = self.extract_chunks_from_source(content, file_path=str(f_path))
                if chunks:
                    all_chunks.extend(chunks)
                    files_scanned += 1
                    if files_scanned >= max_files:
                        break
            if files_scanned >= max_files:
                break

        triplets = self.mine_triplets(all_chunks)

        if output_file:
            out_p = Path(output_file)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            with open(out_p, "w", encoding="utf-8") as out_f:
                for t in triplets:
                    out_f.write(json.dumps(t.to_dict(), ensure_ascii=False) + "\n")

        return triplets
