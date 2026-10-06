"""Static Git-object archival only; never imports/executes overlays or runs tests."""
from __future__ import annotations

import ast
import collections
import difflib
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PIN = "7c932b6f31d81a5c6e331e7537d687fb0c8d9c12"
PACKET = "84cb230b7164f7f25cf8463503acdc2ba0690917"


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True, timeout=60).stdout


def tree(commit: str) -> dict:
    result = {}
    for entry in git("ls-tree", "-r", "-z", commit).split(b"\0"):
        if entry:
            meta, path = entry.split(b"\t", 1)
            mode, kind, oid = meta.decode().split()
            if kind == "blob":
                result[path.decode("utf-8")] = {"mode": mode, "oid": oid}
    return result


def symbols(text: str) -> dict:
    try:
        parsed = ast.parse(text)
    except (SyntaxError, ValueError):
        return {}
    result = {}

    def visit(nodes, prefix=""):
        for node in nodes:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = prefix + node.name
                result[name] = {"ast": ast.dump(node, include_attributes=False), "line": node.lineno, "end": node.end_lineno}
                if isinstance(node, ast.ClassDef):
                    visit(node.body, name + ".")
    visit(parsed.body)
    return result


def target_for(path: str, current: dict) -> str | None:
    match = re.search(r"(?:^|/)((?:src|tests|tools|docs|browser_bridge)/.+)$", path)
    if match:
        return match.group(1)
    matches = [p for p in current if p.startswith(("src/", "tests/", "tools/")) and Path(p).name == Path(path).name]
    return matches[0] if len(matches) == 1 else None


def withheld_reason(paths: list[str], content: bytes) -> str | None:
    if b"\0" in content:
        return "binary/data: original Git object retained; no automatic archive copy"
    text = content.decode("utf-8", errors="replace")
    if re.search(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|\bAKIA[A-Z0-9]{16}\b|\bsk-[A-Za-z0-9]{20,}", text):
        return "potential secret material: preserve immutable object, do not copy automatically"
    if any(re.search(r"(?:\.stdout|\.stderr|\.log)(?:\.|$)|(?:^|/)(?:state|runtime|cache|__pycache__)/", p) for p in paths):
        return "raw runtime output: original Git object retained outside new committed archive"
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        value = None

    def sensitive(obj):
        if isinstance(obj, dict):
            for key, item in obj.items():
                if re.fullmatch(r"(?:api[_-]?key|password|access[_-]?token|refresh[_-]?token|secret)", str(key), re.I) and isinstance(item, str):
                    if item and not re.search(r"test|dummy|fixture|fake|example|redacted|placeholder|changeme|^\$|^<", item, re.I):
                        return True
                if sensitive(item):
                    return True
        if isinstance(obj, list):
            return any(sensitive(item) for item in obj)
        return False
    if sensitive(value):
        return "potential credential/data field: original Git object retained; manual privacy review required"
    if any(Path(p).suffix == ".csv" for p in paths):
        first = text.splitlines()[0].lower() if text.splitlines() else ""
        if not any(word in first for word in ("operation", "path", "selector", "action", "owner", "test", "route", "method", "alias", "id", "surface", "status")):
            return "unclassified CSV data: immutable original retained; manual data review required"
    return None


def main():
    report = (ROOT / "docs/STASH_COVERAGE_20261006.md").read_text(encoding="utf-8")
    rows, excluded = [], []
    meta = {}
    for line_number, line in enumerate(report.splitlines(), 1):
        match = re.match(r"Stash `([0-9a-f]{40})`; base `([0-9a-f]{40})`; index `([0-9a-f]{40})`; untracked `([0-9a-f]{40})`", line)
        if match:
            meta = dict(zip(("stash_sha", "base_sha", "index_sha", "untracked_parent_sha"), match.groups()))
        if line.startswith("| U |") and "| needsmanualhunkreview |" in line:
            cells = [cell.strip().strip("`") for cell in line.split("|")[1:-1]]
            mode, oid = cells[4].split(":")
            row = {**meta, "path": cells[2], "mode": mode, "original_git_blob_sha": oid, "coverage_report_line": line_number}
            (excluded if re.match(r"^(src|tests|tools|docs)/", row["path"]) else rows).append(row)
    assert len(rows) == 382 and len(excluded) == 22, (len(rows), len(excluded))
    current = tree(PIN)
    index_by_blob = collections.defaultdict(list)
    for path, entry in current.items():
        index_by_blob[entry["oid"]].append(path)
    base_trees, blobs, parsed_symbols = {}, {}, {}

    def blob(oid):
        if oid not in blobs:
            blobs[oid] = git("cat-file", "blob", oid)
        return blobs[oid]

    def source(oid):
        if oid not in parsed_symbols:
            parsed_symbols[oid] = symbols(blob(oid).decode("utf-8", errors="replace"))
        return parsed_symbols[oid]

    cohorts = collections.defaultdict(list)
    parent_trees = {}
    for row in rows:
        if row["untracked_parent_sha"] not in parent_trees:
            parent_trees[row["untracked_parent_sha"]] = tree(row["untracked_parent_sha"])
        entry = parent_trees[row["untracked_parent_sha"]][row["path"]]
        assert entry == {"mode": row["mode"], "oid": row["original_git_blob_sha"]}
        cohorts[row["original_git_blob_sha"]].append(row)
    manifests, analyses = [], []
    (OUT / "originals").mkdir(exist_ok=True)
    (OUT / "deltas").mkdir(exist_ok=True)
    for oid, occurrences in sorted(cohorts.items()):
        content = blob(oid)
        actual = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        assert actual == oid
        paths = sorted({row["path"] for row in occurrences})
        reason = withheld_reason(paths, content)
        archive = None
        if reason is None:
            archive = "originals/" + oid + ".original.txt"
            destination = OUT / archive
            if destination.exists():
                assert destination.read_bytes() == content
            else:
                destination.write_bytes(content)
            assert destination.read_bytes() == content
        manifests.append({"original_git_blob_sha": oid, "content_sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content), "archive_path": archive, "withheld_reason": reason, "occurrence_count": len(occurrences), "occurrences": occurrences, "exact_pinned_master_witnesses": index_by_blob.get(oid, [])})
        text = content.decode("utf-8", errors="replace")
        patch = any(Path(path).suffix in {".patch", ".diff"} for path in paths)
        if patch:
            target, hunk = None, None
            for number, line in enumerate(text.splitlines(), 1):
                if line.startswith("+++ "):
                    target = line[4:].split("\t")[0].removeprefix("b/")
                    target = target_for(target, current) or target
                elif line.startswith("@@ "):
                    hunk = {"blob_sha": oid, "kind": "patch_hunk", "target_path": target, "original_line": number, "hunk_header": line, "added": [], "removed": [], "origin_paths": paths}
                    analyses.append(hunk)
                elif hunk and line.startswith("+") and not line.startswith("+++"):
                    hunk["added"].append(line[1:])
                elif hunk and line.startswith("-") and not line.startswith("---"):
                    hunk["removed"].append(line[1:])
            continue
        if any(Path(path).suffix == ".py" for path in paths):
            target = next((target_for(path, current) for path in paths if target_for(path, current)), None)
            if target:
                original_symbols = source(oid)
                current_symbols = source(current[target]["oid"]) if target in current else {}
                bases = sorted({row["base_sha"] for row in occurrences})
                for base in bases:
                    if base not in base_trees:
                        base_trees[base] = tree(base)
                    base_entry = base_trees[base].get(target)
                    base_symbols = source(base_entry["oid"]) if base_entry else {}
                    base_text = blob(base_entry["oid"]).decode("utf-8", errors="replace") if base_entry else ""
                    delta = "".join(difflib.unified_diff(base_text.splitlines(keepends=True), text.splitlines(keepends=True), fromfile="a/" + target, tofile="b/" + target))
                    delta_name = "deltas/" + oid + "-" + base[:8] + "-" + hashlib.sha256(target.encode()).hexdigest()[:8] + ".patch"
                    (OUT / delta_name).write_text(delta, encoding="utf-8", newline="")
                    analyses.append({"blob_sha": oid, "kind": "source_file_delta", "target_path": target, "base_sha": base, "base_blob_sha": base_entry["oid"] if base_entry else None, "delta_path": delta_name, "delta_sha256": hashlib.sha256(delta.encode()).hexdigest(), "base_to_original_hunk_count": sum(line.startswith("@@ ") for line in delta.splitlines()), "status": "authored_delta_requires_current_hunk_review", "origin_paths": paths})
                    for name, entry in original_symbols.items():
                        if isinstance(entry, dict) and (name not in base_symbols or entry["ast"] != base_symbols[name]["ast"]):
                            live = current_symbols.get(name)
                            status = "covered_ast" if live and live["ast"] == entry["ast"] else "missing_symbol" if live is None else "different_current_hunk"
                            analyses.append({"blob_sha": oid, "kind": "source_symbol", "target_path": target, "symbol": name, "original_line": entry["line"], "original_end": entry["end"], "current_line": live["line"] if live else None, "base_sha": base, "base_blob_sha": base_entry["oid"] if base_entry else None, "status": status, "origin_paths": paths})
                    for name in sorted(base_symbols.keys() - original_symbols.keys()):
                        live = current_symbols.get(name)
                        analyses.append({"blob_sha": oid, "kind": "source_removed_symbol", "target_path": target, "symbol": name, "base_sha": base, "current_line": live["line"] if live else None, "status": "covered_deletion" if live is None else "different_current_deletion", "origin_paths": paths})
            else:
                analyses.append({"blob_sha": oid, "kind": "authored_handoff_script", "status": "preserved_not_executed", "origin_paths": paths})
        else:
            analyses.append({"blob_sha": oid, "kind": "historical_receipt_or_document", "status": "preserved_historical_not_acceptance" if reason is None else "withheld_original_retained", "origin_paths": paths})
    for item in analyses:
        if item["kind"] != "patch_hunk":
            continue
        entry = current.get(item["target_path"])
        live_lines = blob(entry["oid"]).decode("utf-8", errors="replace").splitlines() if entry else []
        normalized = {re.sub(r"\s+", " ", line.strip()) for line in live_lines}
        meaningful = [line for line in item["added"] if line.strip() and not line.lstrip().startswith("#")]
        missing = [line for line in meaningful if re.sub(r"\s+", " ", line.strip()) not in normalized]
        item["missing_added_lines"] = missing
        item["status"] = "missing_target" if not entry else "added_lines_present_not_behavior_proof" if not missing else "candidate_missing_hunk"
        original_definitions = [re.match(r"\s*(?:async )?def (\w+)", line).group(1) for line in item["added"] if re.match(r"\s*(?:async )?def (\w+)", line)]
        item["added_symbols"] = original_definitions
        item["current_symbol_candidates"] = [name for name in source(entry["oid"]) if name.rsplit(".", 1)[-1] in original_definitions] if entry and item["target_path"].endswith(".py") else []
        meaningful_normalized = {re.sub(r"\s+", " ", added.strip()) for added in meaningful}
        anchors = [(index + 1, line) for index, line in enumerate(live_lines) if len(line.strip()) > 20 and re.sub(r"\s+", " ", line.strip()) in meaningful_normalized]
        if anchors:
            anchor_line, _ = max(anchors, key=lambda pair: len(pair[1]))
            item["current_anchor_line"] = anchor_line
            candidates = [(name, info) for name, info in source(entry["oid"]).items() if info["line"] <= anchor_line <= info["end"]] if entry and item["target_path"].endswith(".py") else []
            item["current_enclosing_symbol"] = min(candidates, key=lambda pair: pair[1]["end"] - pair[1]["line"])[0] if candidates else None
    for item in analyses:
        if item["kind"] == "patch_hunk":
            item["added_line_count"] = len(item["added"])
            item["removed_line_count"] = len(item["removed"])
            item["missing_added_line_count"] = len(item["missing_added_lines"])
            item["added_lines_sha256"] = hashlib.sha256("\n".join(item["added"]).encode()).hexdigest()
            item["removed_lines_sha256"] = hashlib.sha256("\n".join(item["removed"]).encode()).hexdigest()
            item["missing_added_preview"] = item.pop("missing_added_lines")[:8]
            item.pop("added")
            item.pop("removed")
    payload = {"schema": 1, "pinned_master_sha": PIN, "entry_packet_sha": PACKET, "queue_versions": len(rows), "excluded_direct_versions": excluded, "unique_content_cohorts": len(manifests), "archived_cohorts": sum(x["archive_path"] is not None for x in manifests), "cohorts": manifests}
    (OUT / "manifest.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT / "hunk-map.json").write_text(json.dumps(analyses, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"versions": len(rows), "cohorts": len(manifests), "archived": payload["archived_cohorts"], "archive_bytes": sum(x["size_bytes"] for x in manifests if x["archive_path"]), "withheld": [{"sha": x["original_git_blob_sha"], "reason": x["withheld_reason"], "paths": sorted({r["path"] for r in x["occurrences"]})} for x in manifests if x["withheld_reason"]], "mapping_statuses": dict(collections.Counter(x["status"] for x in analyses))}))


if __name__ == "__main__":
    main()
