"""Deterministic citation/ranking checks; these do not prove model truthfulness."""
from __future__ import annotations

import ast
import math


def paired_retrieval_delta(baseline, candidate):
    """Compare measured matching location queries; report signed raw deltas."""
    def cases(report):
        items = report.get("retrieval") if isinstance(report, dict) else None
        if not isinstance(items, list) or not 1 <= len(items) <= 100:
            raise ValueError("bounded measured baseline and candidate required")
        mapped = {}
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("case"), str):
                raise ValueError("explicit case identity required")
            key = item["case"]
            if key in mapped or not item.get("query") or type(item.get("expected_path")) is not str:
                raise ValueError("unique case/query/path required")
            expected_symbols = item.get("expected_symbols")
            if expected_symbols is not None and "intent" not in item:
                raise ValueError("symbol-aware paired cases require explicit intent")
            intent = item.get("intent", "any")
            if type(intent) is not str or intent not in {"any", "production", "test"}:
                raise ValueError("explicit supported retrieval intent required")
            symbol_contract = _normalize_expected_symbols(expected_symbols) if expected_symbols is not None else None
            metrics = item.get("metrics", {})
            if metrics.get("status") != "measured":
                raise ValueError("unverified metrics cannot establish a delta")
            k = item.get("k", metrics.get("k"))
            if k is not None and (type(k) is not int or k < 1):
                raise ValueError("positive exact k required when supplied")
            if symbol_contract is not None and (type(k) is not int or metrics.get("measurement_scope") != "symbol_ast"):
                raise ValueError("symbol-aware cases require bound k and AST measurement scope")
            values = {name: metrics.get(name) for name in ("recall_at_k", "reciprocal_rank", "citation_validity")}
            scope = "symbol_ast" if symbol_contract is not None else "path_only"
            if metrics.get("measurement_scope", "path_only") != scope:
                raise ValueError("baseline and candidate measurement scopes differ")
            if symbol_contract is not None:
                if type(metrics.get("source_evidence_sufficient")) is not bool:
                    raise ValueError("boolean source-evidence result required")
                values.update({
                    "expected_symbol_recall_at_k": metrics.get("expected_symbol_recall_at_k"),
                    "citation_precision": metrics.get("citation_precision"),
                    "source_evidence_sufficient": float(metrics.get("source_evidence_sufficient") is True),
                    "answer_sufficiency": float(metrics.get("source_evidence_sufficient") is True),
                })
            if any(type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1 for value in values.values()):
                raise ValueError("finite measured fractions required")
            if symbol_contract is None:
                values["answer_sufficiency"] = float(values["recall_at_k"] == 1 and values["citation_validity"] == 1)
            mapped[key] = (item["query"], item["expected_path"], symbol_contract, intent, k, values)
        return mapped
    try:
        before, after = cases(baseline), cases(candidate)
        if before.keys() != after.keys() or any(before[key][:5] != after[key][:5] for key in before):
            raise ValueError("baseline query identities differ")
        if any(before[key][5].keys() != after[key][5].keys() for key in before):
            raise ValueError("baseline metric contracts differ")
        deltas = {name: sum(after[key][5][name] - before[key][5][name] for key in before) / len(before)
                  for name in next(iter(before.values()))[5]}
    except (ValueError, TypeError, AttributeError) as exc:
        return {"success": False, "status": "unverified", "reason": str(exc)}
    paired_scope = "symbol_ast" if next(iter(before.values()))[2] is not None else "path_only"
    return {"success": True, "status": "paired", "case_count": len(before),
            "measurement_scope": paired_scope, "signed_deltas": deltas,
            "answer_scope": "source_symbols" if paired_scope == "symbol_ast" else "retrieved_paths_only",
            "model_quality_verified": False}


def _citation_valid(citation, sources):
    if not isinstance(citation, dict):
        return False
    path, line = citation.get("path"), citation.get("line")
    return (
        isinstance(sources, dict) and isinstance(path, str) and isinstance(sources.get(path), str)
        and type(line) is int and 1 <= line <= len(sources[path].splitlines())
    )


def _normalize_expected_symbols(expected_symbols):
    if not isinstance(expected_symbols, dict) or not expected_symbols:
        raise ValueError("expected symbols must map source paths to nonempty symbol names")
    normalized = []
    for path, names in expected_symbols.items():
        if not isinstance(path, str) or not path or not isinstance(names, (list, set, frozenset)) or not names:
            raise ValueError("expected symbol paths and nonempty name lists are required")
        if any(type(name) is not str or not name.isidentifier() for name in names):
            raise ValueError("expected symbols must be exact identifier names")
        names = list(names)
        if len(names) != len(set(names)):
            raise ValueError("duplicate expected symbol names are ambiguous")
        normalized.append((path, tuple(sorted(names))))
    return tuple(sorted(normalized))


def _source_symbols(sources):
    if not isinstance(sources, dict) or any(not isinstance(path, str) or not isinstance(text, str) for path, text in sources.items()):
        raise ValueError("source snapshots must map paths to text")
    result = {}
    for path, source in sources.items():
        try:
            tree = ast.parse(source, filename=path)
        except (SyntaxError, ValueError, TypeError) as exc:
            raise ValueError("malformed source snapshot") from exc
        found = {}

        def visit(node, in_class=False):
            if isinstance(node, ast.ClassDef):
                found.setdefault(node.name, []).append(("class", node.lineno))
                for child in node.body:
                    visit(child, True)
                return
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found.setdefault(node.name, []).append(("method" if in_class else "function", node.lineno))
                for child in node.body:
                    visit(child, False)
                return
            for child in ast.iter_child_nodes(node):
                visit(child, in_class)

        visit(tree)
        result[path] = found
    return result


def _source_role(path):
    if type(path) is not str:
        return "unknown"
    parts = path.replace("\\", "/").lower().split("/")
    name = parts[-1]
    return "test" if "tests" in parts or "test" in parts or name.startswith("test_") or name.endswith("_test.py") else "production"


def retrieval_metrics(report, relevant, sources, *, k=5, expected_symbols=None, intent=None):
    if type(k) is not int or k < 1 or not isinstance(relevant, (list, tuple, set, frozenset)) or not relevant:
        raise ValueError("positive k and explicit relevant paths are required")
    if intent is None and expected_symbols is None:
        intent = "any"
    if type(intent) is not str or intent not in {"any", "production", "test"}:
        return {"success": False, "status": "unverified", "reason": "intent must be any, production, or test", "model_quality_verified": False}
    try:
        symbol_contract = _normalize_expected_symbols(expected_symbols) if expected_symbols is not None else None
    except (ValueError, TypeError) as exc:
        return {"success": False, "status": "unverified", "reason": str(exc), "model_quality_verified": False}
    if not isinstance(report, dict) or report.get("success") is not True or report.get("stale") is True:
        return {"success": False, "status": "unverified"}
    symbols = report.get("symbols")
    if not isinstance(symbols, list) or any(not isinstance(item, dict) for item in symbols):
        return {"success": False, "status": "unverified"}
    ranked = symbols[:k]
    hits = {item.get("path") for item in ranked if type(item.get("path")) is str and item.get("path") in relevant}
    first = next((rank for rank, item in enumerate(ranked, 1)
                  if type(item.get("path")) is str and item.get("path") in relevant), None)
    valid = sum(_citation_valid(item, sources) for item in ranked)
    result = {
        "success": True, "status": "measured", "k": k,
        "unique_relevant_hits": len(hits), "recall_at_k": len(hits) / len(relevant),
        "reciprocal_rank": 1 / first if first else 0,
        "citation_validity": valid / len(ranked) if ranked else None,
        "answer_sufficiency": len(hits) == len(relevant) and bool(ranked) and valid == len(ranked),
        "citation_scope": "path_exists_and_line_in_supplied_source_snapshot",
        "measurement_scope": "path_only",
        "intent": intent,
        "source_evidence_sufficient": False,
        "model_quality_verified": False,
    }
    if symbol_contract is None:
        return result

    try:
        ast_symbols = _source_symbols(sources)
    except ValueError as exc:
        return {"success": False, "status": "unverified", "reason": str(exc), "model_quality_verified": False}
    expected = set()
    for path, names in symbol_contract:
        if path not in sources or path not in relevant:
            return {"success": False, "status": "unverified", "reason": "expected symbol source must be supplied and relevant", "model_quality_verified": False}
        if intent != "any" and _source_role(path) != intent:
            return {"success": False, "status": "unverified", "reason": "expected symbol source conflicts with retrieval intent", "model_quality_verified": False}
        for name in names:
            definitions = ast_symbols[path].get(name, [])
            if len(definitions) != 1:
                return {"success": False, "status": "unverified", "reason": "expected symbol must identify exactly one AST definition", "model_quality_verified": False}
            expected.add((path, name, definitions[0][0], definitions[0][1]))

    def exact_citation(item):
        path, name, kind, line = item.get("path"), item.get("name"), item.get("kind"), item.get("line")
        if not _citation_valid(item, sources) or type(name) is not str or type(kind) is not str:
            return None
        if (kind, line) not in ast_symbols.get(path, {}).get(name, []):
            return None
        return (path, name, kind, line)

    def role_matches(path):
        return intent == "any" or _source_role(path) == intent

    exact = [exact_citation(item) for item in ranked]
    role_valid = [citation is not None and role_matches(citation[0]) for citation in exact]
    contamination = sum(not role_matches(item.get("path", "")) for item in ranked)
    retrieved = {citation for citation, matches_role in zip(exact, role_valid) if citation is not None and matches_role}
    symbol_recall = len(expected & retrieved) / len(expected)
    precision = sum(role_valid) / len(ranked) if ranked else 0.0
    sufficient = bool(ranked) and symbol_recall == 1 and precision == 1 and contamination == 0
    result.update({
        "measurement_scope": "symbol_ast",
        "expected_symbol_count": len(expected),
        "expected_symbol_recall_at_k": symbol_recall,
        "citation_precision": precision,
        "test_source_contamination_count": contamination,
        "source_evidence_sufficient": sufficient,
        "answer_sufficiency": sufficient,
        "intent": intent,
        "citation_scope": "exact_ast_symbol_name_kind_line_and_intent_role",
        "expected_symbols": {path: list(names) for path, names in symbol_contract},
    })
    return result


def review_metrics(report, sources):
    if not isinstance(report, dict) or report.get("success") is not True:
        return {"success": False, "status": "unverified", "semantic_truth_verified": False}
    findings, verdict = report.get("findings"), report.get("verdict")
    if not isinstance(findings, list) or verdict not in {"pass", "fail"}:
        return {"success": False, "status": "unverified", "semantic_truth_verified": False}
    invalid = [i for i, item in enumerate(findings) if not isinstance(item, dict) or not _citation_valid(item.get("citation"), sources)]
    consistent = (verdict == "pass") == (not findings)
    return {
        "success": not invalid and consistent, "status": "measured",
        "findings_count": len(findings), "invalid_citation_indices": invalid,
        "verdict_consistent": consistent,
        "semantic_truth_verified": False, "advisory_only": True,
    }
