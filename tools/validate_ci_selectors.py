"""validate_ci_selectors.py — LAH-002 CI selector & collection guard.

Parses ``.github/workflows/ci.yml`` (or an explicit ``--workflow``), extracts every
pytest invocation and selector token (file paths, ``::node_id`` targets, and
``-k`` filter expressions), checks for missing files or duplicate selectors in the
same invocation, and runs ``pytest --collect-only`` (unless ``--no-collect``) to
fail if any node ID is stale or any selector/sub-filter collects 0 tests.

Usage (local / CI lint job):
    python tools/validate_ci_selectors.py --root .
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

_TEST_TOKEN_RE = re.compile(r"tests/[^\s\"'<>|;`)]+\.py(?:::[^\s\"'<>|;`)]+)?")


def _extract_test_tokens(yaml_text: str) -> list[str]:
    """Return every unique ``tests/...py`` or ``tests/...py::node`` selector in YAML."""
    return sorted(set(_TEST_TOKEN_RE.findall(yaml_text)))


def _extract_pytest_invocations(yaml_text: str) -> list[dict[str, Any]]:
    """Extract pytest commands and their selectors / ``-k`` expressions from ``ci.yml``."""
    invocations: list[dict[str, Any]] = []
    lines = yaml_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        m = re.match(r"^(?:-\s*)?run:\s*(.*)$", stripped)
        if not m:
            i += 1
            continue
        rhs = m.group(1).strip()
        if rhs in {">", ">-", "|", "|-"}:
            block_lines: list[str] = []
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if not nxt.strip():
                    block_lines.append("")
                    j += 1
                    continue
                nxt_indent = len(nxt) - len(nxt.lstrip())
                if nxt_indent <= indent:
                    break
                block_lines.append(nxt.strip())
                j += 1
            command_text = " ".join(part for part in block_lines if part)
            i = j
        else:
            command_text = rhs
            i += 1

        if "pytest" not in command_text:
            continue
        # Only parse actual pytest execution commands (avoid string mentions)
        if not re.search(r"(?:^|\s)(?:python\s+(?:-m\s+(?:coverage\s+run\s+-m\s+)?)?)?pytest\b", command_text):
            continue

        try:
            tokens = shlex.split(command_text, posix=True)
        except ValueError:
            tokens = command_text.split()

        targets = [tok for tok in tokens if _TEST_TOKEN_RE.fullmatch(tok)]
        k_expr: str | None = None
        for idx, tok in enumerate(tokens):
            if tok == "-k" and idx + 1 < len(tokens):
                k_expr = tokens[idx + 1]
                break
            if tok.startswith("-k") and len(tok) > 2:
                k_expr = tok[2:]
                break

        invocations.append({
            "targets": targets,
            "k_expr": k_expr,
            "has_unconstrained_run": not targets,
        })
    return invocations


def _run_collect_only(
    root: Path,
    args: list[str],
    *,
    python_exe: str = sys.executable,
) -> tuple[int, int, list[str], str]:
    """Run ``pytest --collect-only -q`` cleanly against ``root``."""
    cmd = [python_exe, "-m", "pytest", "--collect-only", "-q", "--rootdir", str(root)]
    if not (root / "pyproject.toml").is_file():
        cmd.extend(["-o", "pythonpath=."])
    cmd.extend(args)
    env = dict(os.environ)
    env["NO_TEST_CACHE"] = "1"
    proc = subprocess.run(
        cmd,
        cwd=str(root),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    collected = 0
    for line in output.splitlines():
        s = line.strip()
        m_num = re.search(r"(\d+)\s+(?:/\d+\s+)?tests?\s+collected", s)
        if m_num:
            collected = int(m_num.group(1))
            break
    nodeids = [
        ln.strip().replace("\\", "/")
        for ln in (proc.stdout or "").splitlines()
        if "::" in ln and not ln.lstrip().startswith(("=", "-")) and not ln.startswith("ERROR")
    ]
    if collected == 0 and proc.returncode == 0:
        collected = len(nodeids)
    return proc.returncode, collected, nodeids, output.strip()


def validate_selectors(
    root: Path,
    *,
    workflow_path: Path | None = None,
    collect: bool = True,
) -> dict[str, Any]:
    """Validate all pytest paths, node IDs, and ``-k`` filters in ``ci.yml``."""
    root = root.resolve()
    ci_yaml = (workflow_path or (root / ".github" / "workflows" / "ci.yml")).resolve()
    if not ci_yaml.is_file():
        return {"ok": False, "error": f"CI workflow not found: {ci_yaml}", "missing_files": [], "failures": [f"CI workflow not found: {ci_yaml}"]}

    yaml_text = ci_yaml.read_text(encoding="utf-8")
    all_tokens = _extract_test_tokens(yaml_text)
    invocations = _extract_pytest_invocations(yaml_text)

    missing_files: list[str] = []
    seen_files: set[str] = set()
    for tok in all_tokens:
        file_rel = tok.split("::", 1)[0]
        if file_rel not in seen_files:
            seen_files.add(file_rel)
            if not (root / file_rel).is_file():
                missing_files.append(file_rel)

    duplicates: list[str] = []
    for idx, inv in enumerate(invocations):
        seen_t: set[str] = set()
        for t in inv["targets"]:
            if t in seen_t:
                duplicates.append(f"invocation#{idx}: duplicate selector {t}")
            seen_t.add(t)

    failures: list[str] = []
    if missing_files:
        failures.extend(f"MISSING_FILE: {p}" for p in missing_files)
    if duplicates:
        failures.extend(duplicates)

    collected_total = 0
    node_checks = 0
    if collect and not missing_files and all_tokens:
        # 1) Batch-collect all explicit file & node_id tokens cleanly in one pass.
        code, count, nodeids, out = _run_collect_only(root, all_tokens)
        collected_total = count
        if code != 0 or count == 0:
            failures.append(f"BATCH_COLLECT_FAILED (exit={code}, collected={count}): {out[-600:]}")
        else:
            node_tokens = [t for t in all_tokens if "::" in t]
            node_checks = len(node_tokens)
            # Ensure every single token (file or ::node_id) matched at least 1 collected test!
            for tok in all_tokens:
                if "::" in tok:
                    matched = any(nid == tok or nid.startswith(tok + "[") or nid.startswith(tok + "::") for nid in nodeids)
                else:
                    matched = any(nid.startswith(tok + "::") for nid in nodeids)
                if not matched:
                    failures.append(f"EMPTY_SELECTOR: {tok} collected 0 tests")
            # Check each -k invocation (and split 'or' clauses so no dead term hides).
            for idx, inv in enumerate(invocations):
                k_expr = inv.get("k_expr")
                if not k_expr:
                    continue
                targets = inv["targets"]
                subterms = [part.strip() for part in re.split(r"\s+or\s+", k_expr) if part.strip()]
                for term in subterms:
                    c_code, c_count, _c_nodes, c_out = _run_collect_only(root, [*targets, "-k", term])
                    if c_code != 0 or c_count == 0:
                        failures.append(
                            f"EMPTY_OR_FAILED_K_TERM (invocation#{idx}, term={term!r}, exit={c_code}, collected={c_count}): {c_out[-300:]}"
                        )

    return {
        "ok": not failures,
        "root": str(root),
        "workflow": str(ci_yaml),
        "unique_files": len(seen_files),
        "unique_selectors": len(all_tokens),
        "invocations": len(invocations),
        "node_selectors": node_checks,
        "collected_total": collected_total,
        "missing_files": missing_files,
        "duplicates": duplicates,
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root containing .github/workflows/ci.yml")
    parser.add_argument("--workflow", type=Path, default=None, help="Optional explicit workflow YAML path")
    parser.add_argument("--no-collect", action="store_true", help="Skip pytest --collect-only verification (check file existence only)")
    parser.add_argument("--manifest-out", type=Path, default=None, help="Optional path to write JSON selector manifest")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args(argv)

    result = validate_selectors(
        args.root,
        workflow_path=args.workflow,
        collect=not args.no_collect,
    )
    if args.manifest_out is not None:
        args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
        args.manifest_out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result["ok"]:
        print(
            f"OK: {result['unique_selectors']} CI selectors across {result['unique_files']} files validated "
            f"(collected={result['collected_total']}, nodes={result['node_selectors']})."
        )
    else:
        print(f"ERROR: CI selector validation failed ({len(result['failures'])} issue(s)):", file=sys.stderr)
        for item in result["failures"]:
            print(f"  - {item}", file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
