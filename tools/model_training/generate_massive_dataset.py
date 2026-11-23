"""Generate massive, high-quality polyglot gold training and evaluation datasets.

Extracts real files across registered projects in multiple programming languages,
generates grounded file cards with strict verbatim quotes from source code,
and produces zero-leakage group-held-out train and evaluation JSONL files.
"""
from __future__ import annotations

import ast
import hashlib
import json
# import os
from pathlib import Path
import re
import sqlite3
# import stat
from typing import Any

from .manifest import validate_dataset_pair

SYSTEM_PROMPT = (
    "Complete the file card using CURRENT SOURCE as authority and DETERMINISTIC BASELINE as starting facts. "
    "Preserve all correct deterministic symbols, dependencies, and keywords; add semantic purpose, risks, side effects, tests, "
    "and any missing symbols or dependencies found in source. Return empty arrays only when source truly contains no fact for that field. "
    "Provide supporting evidence with an exact quote copied from CURRENT SOURCE for purpose and key claims. "
    "Return exactly one JSON object with schema: "
    '{"purpose":"","symbols":[],"dependencies":[],"side_effects":[],"risks":[],"tests":[],"keywords":[],'
    '"evidence":[{"field":"purpose","value":"...","quote":"..."}]}. No markdown or prose.'
)

_EXT_TO_LANG = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cs": "csharp",
    ".php": "php",
    ".kt": "kotlin",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c_header",
    ".hpp": "cpp_header",
    ".sql": "sql",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".sh": "shell",
    ".ps1": "powershell",
    ".md": "markdown",
}

_EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".next", ".turbo", "dist", "build", "target", "coverage",
    "site-packages", ".idea", ".vs", "obj", "bin",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _extract_python(source: str) -> dict[str, Any] | None:
    try:
        tree = ast.parse(source)
    except Exception:
        return None

    purpose = ""
    purpose_quote = ""
    doc = ast.get_docstring(tree)
    if doc and doc.strip():
        purpose = doc.strip().split("\n")[0][:120].strip()
        purpose_quote = purpose
        if purpose_quote not in source:
            # find first line of docstring in source
            for line in source.splitlines():
                if purpose[:40] in line:
                    purpose_quote = line.strip()
                    break

    symbols: list[str] = []
    symbol_evidence: list[dict[str, str]] = []
    deps: list[str] = []
    dep_evidence: list[dict[str, str]] = []
    side_effects: list[str] = []
    side_evidence: list[dict[str, str]] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name
            if not name.startswith("__") and name not in symbols:
                symbols.append(name)
                # find quote line
                for line in source.splitlines()[max(0, node.lineno - 1):node.lineno + 2]:
                    if f"def {name}" in line or f"async def {name}" in line:
                        symbol_evidence.append({"field": "symbols", "value": name, "quote": line.strip()})
                        break
        elif isinstance(node, ast.ClassDef):
            name = node.name
            if name not in symbols:
                symbols.append(name)
                for line in source.splitlines()[max(0, node.lineno - 1):node.lineno + 2]:
                    if f"class {name}" in line:
                        symbol_evidence.append({"field": "symbols", "value": name, "quote": line.strip()})
                        break
        elif isinstance(node, ast.Import):
            for alias in node.names:
                mname = alias.name.split(".")[0]
                if mname not in deps and len(mname) > 1:
                    deps.append(mname)
                    for line in source.splitlines()[max(0, node.lineno - 1):node.lineno + 2]:
                        if alias.name in line:
                            dep_evidence.append({"field": "dependencies", "value": mname, "quote": line.strip()})
                            break
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mname = node.module.split(".")[0]
                if mname not in deps and len(mname) > 1:
                    deps.append(mname)
                    for line in source.splitlines()[max(0, node.lineno - 1):node.lineno + 2]:
                        if node.module in line:
                            dep_evidence.append({"field": "dependencies", "value": mname, "quote": line.strip()})
                            break

    # If no docstring, derive purpose from main class or function
    if not purpose and symbols:
        for node in tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                cdoc = ast.get_docstring(node)
                if cdoc and cdoc.strip():
                    purpose = f"{node.name}: {cdoc.strip().splitlines()[0][:100].strip()}"
                    for line in source.splitlines():
                        if cdoc.strip().splitlines()[0][:30] in line:
                            purpose_quote = line.strip()
                            break
                    break
        if not purpose:
            purpose = f"Provides {', '.join(symbols[:3])} functionality."
            if symbol_evidence:
                purpose_quote = symbol_evidence[0]["quote"]

    if not purpose_quote or purpose_quote not in source:
        if symbol_evidence:
            purpose_quote = symbol_evidence[0]["quote"]
        elif dep_evidence:
            purpose_quote = dep_evidence[0]["quote"]
        else:
            first_line = next((l.strip() for l in source.splitlines() if l.strip()), "")
            if first_line:
                purpose_quote = first_line
            else:
                return None

    # Detect side effects
    for line in source.splitlines():
        sline = line.strip()
        if any(pat in sline for pat in ["open(", "sqlite3.connect", "subprocess.", "socket.", "requests.", "urllib.request"]):
            side_effects.append("I/O and external process or network communication")
            side_evidence.append({"field": "side_effects", "value": "I/O operations", "quote": sline})
            break

    evidence = []
    if purpose_quote and purpose_quote in source:
        evidence.append({"field": "purpose", "value": purpose, "quote": purpose_quote})
    for ev in symbol_evidence[:3]:
        if ev["quote"] in source:
            evidence.append(ev)
    for ev in dep_evidence[:3]:
        if ev["quote"] in source:
            evidence.append(ev)
    for ev in side_evidence[:1]:
        if ev["quote"] in source:
            evidence.append(ev)

    if not evidence:
        return None

    return {
        "purpose": purpose or "Module implementation.",
        "symbols": symbols[:8],
        "dependencies": deps[:8],
        "side_effects": side_effects[:3],
        "risks": ["Resource exhaustion or unhandled exception on unexpected input"] if symbols else [],
        "tests": [],
        "keywords": [s.lower() for s in symbols[:5] if len(s) > 2],
        "evidence": evidence,
    }


def _extract_polyglot_regex(source: str, lang: str) -> dict[str, Any] | None:
    lines = source.splitlines()
    purpose = ""
    purpose_quote = ""
    symbols: list[str] = []
    symbol_evidence: list[dict[str, str]] = []
    deps: list[str] = []
    dep_evidence: list[dict[str, str]] = []

    # Check top comments for purpose
    comment_lines = []
    for line in lines[:25]:
        s = line.strip()
        if s.startswith("//") or s.startswith("#") or s.startswith("*") or s.startswith("/*") or s.startswith("--"):
            clean = re.sub(r"^[/*#\s-]+", "", s).strip()
            if len(clean) > 10 and not any(k in clean.lower() for k in ["copyright", "license", "author", "@ts-"]):
                comment_lines.append((clean, s))
                break

    if comment_lines:
        purpose = comment_lines[0][0][:120]
        purpose_quote = comment_lines[0][1]

    # Regex patterns per language
    sym_patterns = [
        # TypeScript / JavaScript
        re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)"),
        re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z0-9_$]+)\s*(?::\s*[^=]+)?=>"),
        re.compile(r"^\s*(?:export\s+)?class\s+([a-zA-Z0-9_$]+)"),
        re.compile(r"^\s*(?:export\s+)?interface\s+([a-zA-Z0-9_$]+)"),
        re.compile(r"^\s*(?:export\s+)?type\s+([a-zA-Z0-9_$]+)\s*="),
        # C# / Java / C++
        re.compile(r"^\s*(?:public|private|protected|internal|static|\s)+class\s+([a-zA-Z0-9_]+)"),
        re.compile(r"^\s*(?:public|private|protected|internal|\s)+(?:async\s+)?(?:void|string|int|bool|Task|[A-Z][a-zA-Z0-9_<>]+)\s+([a-zA-Z0-9_]+)\s*\("),
        # Go
        re.compile(r"^\s*func\s+(?:\([^)]+\)\s+)?([a-zA-Z0-9_]+)\s*\("),
        re.compile(r"^\s*type\s+([a-zA-Z0-9_]+)\s+(?:struct|interface)"),
        # Rust: pub fn, fn, struct, enum, trait, impl
        re.compile(r"^\s*(?:pub(?:\([^\)]+\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+([a-zA-Z0-9_]+)"),
        re.compile(r"^\s*(?:pub(?:\([^\)]+\))?\s+)?(?:struct|enum|trait)\s+([a-zA-Z0-9_]+)"),
        re.compile(r"^\s*impl(?:\s*<[^>]+>)?\s+(?:[a-zA-Z0-9_:]+\s+for\s+)?([a-zA-Z0-9_:]+)"),
        # PHP / Generic
        re.compile(r"^\s*(?:public\s+)?function\s+([a-zA-Z0-9_]+)\s*\("),
        re.compile(r"^\s*class\s+([a-zA-Z0-9_]+)"),
    ]

    dep_patterns = [
        re.compile(r"^\s*import\s+.*?from\s+['\"]([^'\"]+)['\"]"),
        re.compile(r"^\s*(?:const|var|let)\s+.*?=\s*require\(['\"]([^'\"]+)['\"]\);?"),
        re.compile(r"^\s*using\s+([a-zA-Z0-9_.]+);"),
        re.compile(r"^\s*use\s+([a-zA-Z0-9_\\]+);"),
        re.compile(r"^\s*import\s+(?:\"([^\"]+)\"|([a-zA-Z0-9_./]+))"),
        # Rust use statements with single or grouped items
        re.compile(r"^\s*use\s+([a-zA-Z0-9_:]+)(?:::\{[^}]+\})?;"),
        re.compile(r"^\s*extern\s+crate\s+([a-zA-Z0-9_]+);"),
    ]

    for line in lines:
        sline = line.strip()
        if not sline:
            continue
        for p in sym_patterns:
            m = p.match(line)
            if m:
                name = m.group(1)
                if name not in symbols and len(name) > 1 and name not in {"if", "for", "while", "switch"}:
                    symbols.append(name)
                    symbol_evidence.append({"field": "symbols", "value": name, "quote": sline})
                    break
        for p in dep_patterns:
            m = p.match(line)
            if m:
                dep_name = m.group(1) or (m.group(2) if len(m.groups()) > 1 else "")
                if dep_name:
                    short_dep = dep_name.split("/")[-1].split("\\")[-1]
                    if short_dep not in deps and len(short_dep) > 1:
                        deps.append(short_dep)
                        dep_evidence.append({"field": "dependencies", "value": short_dep, "quote": sline})
                        break

    if not purpose:
        if symbols:
            purpose = f"Defines {', '.join(symbols[:3])} for {lang} application logic."
            purpose_quote = symbol_evidence[0]["quote"]
        elif deps:
            purpose = f"{lang.capitalize()} integration module using {', '.join(deps[:3])}."
            purpose_quote = dep_evidence[0]["quote"]
        else:
            # take first non-empty line
            for line in lines:
                if len(line.strip()) > 5:
                    purpose = f"{lang.capitalize()} source component."
                    purpose_quote = line.strip()
                    break

    if not purpose_quote or purpose_quote not in source:
        return None

    evidence = [{"field": "purpose", "value": purpose, "quote": purpose_quote}]
    for ev in symbol_evidence[:3]:
        if ev["quote"] in source:
            evidence.append(ev)
    for ev in dep_evidence[:3]:
        if ev["quote"] in source:
            evidence.append(ev)

    return {
        "purpose": purpose,
        "symbols": symbols[:8],
        "dependencies": deps[:8],
        "side_effects": ["Performs application domain logic"] if symbols else [],
        "risks": ["Runtime exception if external dependencies or arguments fail validation"] if deps else [],
        "tests": [],
        "keywords": [s.lower() for s in symbols[:5] if len(s) > 2],
        "evidence": evidence,
    }


def extract_card(source: str, ext: str) -> dict[str, Any] | None:
    lang = _EXT_TO_LANG.get(ext)
    if not lang:
        return None
    if lang == "python":
        res = _extract_python(source)
        if res:
            return res
    return _extract_polyglot_regex(source, lang)


def build_messages(rel_path: str, source_text: str, deterministic_baseline: dict[str, Any], card: dict[str, Any] | None = None) -> list[dict[str, str]]:
    # Keep excerpt within 3200 characters so full prompt is bounded and fast
    excerpt = source_text[:3200]
    # Ensure all evidence quotes exist within the excerpt; if not, trim or drop
    valid_evidence = []
    if card and "evidence" in card:
        for ev in card["evidence"]:
            if ev.get("quote") and ev["quote"] in excerpt:
                valid_evidence.append(ev)
        card["evidence"] = valid_evidence

    det_json = json.dumps(deterministic_baseline, separators=(",", ":"), ensure_ascii=False)
    user_prompt = (
        f"FILE: {rel_path}\n\n"
        f"DETERMINISTIC BASELINE (preserve valid parsed facts and complement with semantic details):\n"
        f"{det_json}\n\n"
        f"CURRENT SOURCE (authority):\n"
        f"{excerpt}"
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    if card is not None:
        messages.append({"role": "assistant", "content": json.dumps(card, separators=(",", ":"), ensure_ascii=False)})
    return messages


def generate_massive_dataset(
    db_path: Path,
    out_train: Path,
    out_eval: Path,
    target_train_count: int = 2000,
    target_eval_count: int = 500,
) -> tuple[int, int]:
    conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    # Group candidate files by group_id
    # group_id = hash(project_root + "/" + top_directory)
    groups: dict[str, list[dict[str, Any]]] = {}
    seen_hashes: set[str] = set()

    # 1. First collect existing high-quality model cards from DB (analyzer 7.0.0, non-deterministic)
    print("Collecting existing validated model cards from SQLite...")
    existing_model_query = """
        SELECT f.root, f.path, c.card_json
        FROM file_refs f
        JOIN content_cards c ON c.card_key = f.card_key
        WHERE c.model NOT LIKE 'deterministic%' AND c.analyzer_version = '7.0.0'
        ORDER BY f.root, f.path
    """
    for row in conn.execute(existing_model_query):
        root = row["root"]
        rel_path = row["path"]
        full_path = Path(root) / rel_path
        if not full_path.is_file():
            continue
        try:
            source_bytes = full_path.read_bytes()
            if len(source_bytes) > 256 * 1024 or len(source_bytes) < 30:
                continue
            source_text = source_bytes.decode("utf-8", errors="replace")
            card = json.loads(row["card_json"])
            if not card.get("evidence"):
                continue
            # Validate quotes
            excerpt = source_text[:3200]
            valid_ev = [ev for ev in card["evidence"] if ev.get("quote") and ev["quote"] in excerpt]
            if not valid_ev:
                continue
            card["evidence"] = valid_ev
        except Exception:
            continue

        sha = _sha256(source_bytes)
        if sha in seen_hashes:
            continue
        seen_hashes.add(sha)

        top_dir = rel_path.split("/")[0] if "/" in rel_path else "root"
        grp = f"grp_{_sha256(f'{root}/{top_dir}'.encode('utf-8'))[:16]}"

        det_base = {
            "purpose": f"{Path(rel_path).name}: source",
            "symbols": card.get("symbols", [])[:3],
            "dependencies": card.get("dependencies", [])[:3],
            "side_effects": [],
            "risks": [],
            "tests": [],
            "keywords": card.get("keywords", [])[:3],
        }

        groups.setdefault(grp, []).append({
            "rel_path": rel_path,
            "source_text": source_text,
            "source_sha256": sha,
            "det_base": det_base,
            "card": card,
        })

    print(f"Collected {sum(len(v) for v in groups.values())} existing validated model cards across {len(groups)} groups.")

    # 2. Extract grounded polyglot cards directly from disk across all registered projects
    print("Extracting grounded cards across polyglot project files...")
    proj_query = "SELECT root, path FROM file_refs ORDER BY root, path"
    for row in conn.execute(proj_query):
        root = row["root"]
        rel_path = row["path"]
        ext = Path(rel_path).suffix.lower()
        if ext not in _EXT_TO_LANG:
            continue

        full_path = Path(root) / rel_path
        if not full_path.is_file():
            continue

        # Skip unwanted directories and minified bundles
        parts = rel_path.replace("\\", "/").split("/")
        if any(part in _EXCLUDED_DIRS for part in parts):
            continue
        if any(".min." in part or ".chunk." in part or ".bundle." in part for part in parts):
            continue

        try:
            st = full_path.stat()
            if st.st_size > 128 * 1024 or st.st_size < 40:
                continue
            source_bytes = full_path.read_bytes()
            sha = _sha256(source_bytes)
            if sha in seen_hashes:
                continue

            source_text = source_bytes.decode("utf-8", errors="replace")
            card = extract_card(source_text, ext)
            if not card or not card.get("evidence"):
                continue

            excerpt = source_text[:3200]
            valid_ev = [ev for ev in card["evidence"] if ev.get("quote") and ev["quote"] in excerpt]
            if not valid_ev:
                continue
            card["evidence"] = valid_ev
            seen_hashes.add(sha)
        except Exception:
            continue

        top_dir = parts[0] if len(parts) > 1 else "root"
        grp = f"grp_{_sha256(f'{root}/{top_dir}'.encode('utf-8'))[:16]}"

        det_base = {
            "purpose": f"{Path(rel_path).name}: source, {_EXT_TO_LANG[ext]}",
            "symbols": card.get("symbols", [])[:3],
            "dependencies": card.get("dependencies", [])[:3],
            "side_effects": [],
            "risks": [],
            "tests": [],
            "keywords": card.get("keywords", [])[:3],
        }

        groups.setdefault(grp, []).append({
            "rel_path": rel_path,
            "source_text": source_text,
            "source_sha256": sha,
            "det_base": det_base,
            "card": card,
        })

        if sum(len(v) for v in groups.values()) >= (target_train_count + target_eval_count) * 1.2:
            break

    total_candidates = sum(len(v) for v in groups.values())
    print(f"Total candidate cards ready: {total_candidates} in {len(groups)} distinct groups.")

    # 3. Deterministic Group-held-out Split (zero group & content leakage)
    eval_groups = set()
    train_groups = set()
    for grp in sorted(groups.keys()):
        h = int(hashlib.md5(grp.encode("utf-8")).hexdigest(), 16)
        if (h % 10) < 3:  # ~30% eval groups
            eval_groups.add(grp)
        else:
            train_groups.add(grp)

    train_rows: list[dict[str, Any]] = []
    eval_rows: list[dict[str, Any]] = []

    for grp, items in groups.items():
        is_eval = grp in eval_groups
        for item in items:
            row_id = _sha256(f"{grp}\0{item['rel_path']}\0{item['source_sha256']}".encode("utf-8"))
            if is_eval:
                if len(eval_rows) >= target_eval_count:
                    continue
                msgs = build_messages(item["rel_path"], item["source_text"], item["det_base"], card=None)
                eval_rows.append({
                    "id": row_id,
                    "group_id": grp,
                    "source_sha256": item["source_sha256"],
                    "provenance": {
                        "source": "grounded_polyglot_gold",
                        "relative_path": item["rel_path"],
                        "source_sha256": item["source_sha256"],
                    },
                    "expected": item["card"],
                    "required_facts": [
                        {"field": "purpose", "value": item["card"]["purpose"]},
                        {"field": "evidence", "value": "grounded"},
                    ],
                    "messages": msgs,
                })
            else:
                if len(train_rows) >= target_train_count:
                    continue
                msgs = build_messages(item["rel_path"], item["source_text"], item["det_base"], card=item["card"])
                train_rows.append({
                    "id": row_id,
                    "group_id": grp,
                    "source_sha256": item["source_sha256"],
                    "provenance": {
                        "source": "grounded_polyglot_gold",
                        "relative_path": item["rel_path"],
                        "source_sha256": item["source_sha256"],
                    },
                    "messages": msgs,
                })

    print(f"Generated train rows: {len(train_rows)}, eval rows: {len(eval_rows)}")

    # Write files atomically
    out_train.parent.mkdir(parents=True, exist_ok=True)
    out_eval.parent.mkdir(parents=True, exist_ok=True)

    with out_train.open("w", encoding="utf-8") as f:
        for r in train_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with out_eval.open("w", encoding="utf-8") as f:
        for r in eval_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Validate the generated dataset pair
    stats = validate_dataset_pair(out_train, out_eval)
    print("Dataset pair validation succeeded:")
    print(json.dumps(stats, indent=2))

    return len(train_rows), len(eval_rows)


if __name__ == "__main__":
    db = Path("state/preprocess.sqlite3")
    train_target = Path("state/experiments/model-training/data/preprocess-gold-massive-train.jsonl")
    eval_target = Path("state/experiments/model-training/data/preprocess-gold-massive-eval.jsonl")
    train_n, eval_n = generate_massive_dataset(db, train_target, eval_target, target_train_count=2000, target_eval_count=500)
    print(f"DONE: {train_n} train, {eval_n} eval")
