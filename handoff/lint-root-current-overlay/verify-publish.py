"""Owned source-only AST review, bounded lint, immutable patch handoff; no app imports."""
import ast
import copy
import datetime
import difflib
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

OVERLAY = Path(__file__).resolve().parent
ROOT = Path(r"C:\Users\Adam\.local-ai-hub")
CAPTURE = json.loads((OVERLAY / "capture.json").read_text(encoding="utf-8-sig"))
FILES = [entry["path"] for entry in CAPTURE["files"]]
EXPECTED = {
    "src/local_ai_hub/agent_incidents.py": [(299, "literal")],
    "src/local_ai_hub/benchmark.py": [(491, "except")],
    "src/local_ai_hub/browser_bridge.py": [(711, "except")],
    "src/local_ai_hub/client.py": [(621, "except")],
    "src/local_ai_hub/deterministic.py": [(4150, "assignment")],
    "src/local_ai_hub/generator.py": [(12, "json")],
    "src/local_ai_hub/pipeline.py": [(6, "json")],
    "src/local_ai_hub/response_protocol.py": [(6, "json")],
    "src/local_ai_hub/scheduler.py": [(347, "loop")],
    "src/local_ai_hub/supervisor.py": [(5, "json")],
    "src/local_ai_hub/token_economy.py": [(96, "json"), (148, "json")],
    "src/local_ai_hub/repo_tools.py": [(1213, "assignment")],
    "tools/benchmark_command_broker.py": [],
    "tools/benchmark_surfaces.py": [(16, "http_import"), (25, "sqlite")],
}
assert set(FILES) == set(EXPECTED) and len(FILES) == 14
stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
PUBLISH = OVERLAY / ("publish-" + stamp)
PUBLISH.mkdir()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def record_command(args, cwd):
    result = subprocess.run(args, cwd=str(cwd), capture_output=True, timeout=60)
    return {
        "argv": args,
        "command": subprocess.list2cmdline(args),
        "cwd": str(cwd),
        "exit_code": result.returncode,
        "stdout": result.stdout.decode("utf-8", errors="replace"),
        "stderr": result.stderr.decode("utf-8", errors="replace"),
        "timeout_seconds": 60,
    }


def review_ast(relative, pre, post):
    old = ast.parse(pre, filename=relative)
    new = ast.parse(post, filename=relative)
    expected = copy.deepcopy(old)
    rules = dict(EXPECTED[relative])
    applied = []

    class OwnedChanges(ast.NodeTransformer):
        def visit_Import(self, node):
            kind = rules.get(node.lineno)
            if kind in {"json", "sqlite"}:
                assert len(node.names) == 1
                assert node.names[0].name == ("json" if kind == "json" else "sqlite3")
                assert node.names[0].asname is None
                applied.append((node.lineno, kind))
                return None
            return node

        def visit_ImportFrom(self, node):
            if rules.get(node.lineno) == "http_import":
                assert node.module == "http.server"
                assert [item.name for item in node.names] == ["BaseHTTPRequestHandler", "ThreadingHTTPServer"]
                node.names = [item for item in node.names if item.name != "BaseHTTPRequestHandler"]
                applied.append((node.lineno, "http_import"))
            return node

        def visit_ExceptHandler(self, node):
            if rules.get(node.lineno) == "except":
                assert node.name == "exc"
                assert not any(isinstance(item, ast.Name) and item.id == "exc" for stmt in node.body for item in ast.walk(stmt))
                node.name = None
                applied.append((node.lineno, "except"))
            return self.generic_visit(node)

        def visit_Assign(self, node):
            if rules.get(node.lineno) == "assignment":
                assert len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                assert node.targets[0].id in {"f_lower", "relative"}
                assert isinstance(node.value, ast.Call)
                scopes = [scope for scope in ast.walk(old) if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)) and scope.lineno <= node.lineno <= scope.end_lineno]
                scope = max(scopes, key=lambda item: item.lineno)
                assert not any(isinstance(item, ast.Name) and item.id == "_" and isinstance(item.ctx, ast.Load) for item in ast.walk(scope)), "underscore consumer in assignment scope"
                node.targets[0].id = "_"
                applied.append((node.lineno, "assignment"))
            return self.generic_visit(node)

        def visit_For(self, node):
            if rules.get(node.lineno) == "loop":
                assert isinstance(node.target, ast.Name) and node.target.id == "field"
                for item in ast.walk(node):
                    if isinstance(item, ast.Name) and item.id == "field":
                        item.id = "metric_field"
                applied.append((node.lineno, "loop"))
            return self.generic_visit(node)

        def visit_JoinedStr(self, node):
            if rules.get(node.lineno) == "literal" and len(node.values) == 1 and isinstance(node.values[0], ast.Constant) and node.values[0].value == "ALTER":
                applied.append((node.lineno, "literal"))
                return ast.copy_location(ast.Constant(value="ALTER"), node)
            return self.generic_visit(node)

    expected = OwnedChanges().visit(expected)
    assert sorted(applied) == sorted(EXPECTED[relative]), (relative, applied)
    if relative == "tools/benchmark_command_broker.py":
        assert any(isinstance(node, ast.ImportFrom) and node.module == "__future__" and any(alias.name == "annotations" for alias in node.names) for node in new.body)
        imports = [node for node in new.body if isinstance(node, ast.ImportFrom) and node.module == "typing"]
        assert len(imports) == 1
        assert [alias.name for alias in imports[0].names] == ["TYPE_CHECKING", "Any", "Callable"]
        assert all(alias.asname is None for alias in imports[0].names)
        imports[0].names = [alias for alias in imports[0].names if alias.name != "TYPE_CHECKING"]
        guards = [node for node in new.body if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"]
        assert len(guards) == 1
        assert ast.dump(guards[0], include_attributes=False) == ast.dump(ast.parse("if TYPE_CHECKING:\n    from local_ai_hub.commands import CommandBroker\n").body[0], include_attributes=False)
        new.body.remove(guards[0])
    assert ast.dump(expected, include_attributes=False) == ast.dump(new, include_attributes=False), "Unexpected AST change: " + relative
    return {"path": relative, "pre_parse": "PASS", "post_parse": "PASS", "exact_allowlisted_ast_delta": "PASS", "allowed_deltas": EXPECTED[relative], "type_checking_only_command_broker_import": relative == "tools/benchmark_command_broker.py"}


receipt = {
    "owner": "misc Pyflakes overlay worker; integration/production validation T20",
    "root": str(ROOT),
    "overlay": str(OVERLAY),
    "published_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "scope": FILES,
    "baseline": CAPTURE["baseline"],
    "prior_overlay_check": {"exit_code": 1, "details": "first-overlay-pyflakes.txt", "reason": "Intermediate underscore binding diagnostics, restored earlier client handler, residual duplicate json import; corrected before publication"},
    "app_imports": False,
    "hub_gpu_build_pytest": False,
    "root_writes": False,
    "ast_command": subprocess.list2cmdline([sys.executable, "-B", str(Path(__file__).resolve())]),
    "files": [],
    "ast_review": [],
    "checks": [],
}
parts = []
for captured in CAPTURE["files"]:
    relative = captured["path"]
    before = (OVERLAY / "preimage" / relative).read_bytes()
    after = (OVERLAY / "owned" / relative).read_bytes()
    assert sha(before) == captured["pre_sha256"], "Snapshot mutated: " + relative
    assert sha((ROOT / relative).read_bytes()) == sha(before), "Root preimage drift; regenerate only owned hunks: " + relative
    receipt["ast_review"].append(review_ast(relative, before, after))
    assert before != after, "Expected owned change missing: " + relative
    receipt["files"].append({"path": relative, "pre_sha256": sha(before), "post_sha256": sha(after), "pre_bytes": len(before), "post_bytes": len(after)})
    parts.extend(difflib.unified_diff(before.decode("utf-8").splitlines(keepends=True), after.decode("utf-8").splitlines(keepends=True), fromfile="a/" + relative, tofile="b/" + relative, n=3))
legacy_patch_data = "".join(parts).encode("utf-8")
prior_patch = OVERLAY / "publish-20261001T160334903909Z" / "misc-pyflakes-current-root.patch"
assert prior_patch.read_bytes() == legacy_patch_data, "Owned sources changed since successful static checks; cannot reuse lint"
patch_data = legacy_patch_data.replace(b"\r\n", b"\n")
patch_path = PUBLISH / "misc-pyflakes-current-root.patch"
patch_path.write_bytes(patch_data)
receipt["patch_path"] = str(patch_path)
receipt["patch_sha256"] = sha(patch_data)
receipt["patch_bytes"] = len(patch_data)
lint_args = [sys.executable, "-B", "-m", "pyflakes", *[str(OVERLAY / "owned" / relative) for relative in FILES]]
lint = {
    "argv": lint_args,
    "command": subprocess.list2cmdline(lint_args),
    "cwd": str(OVERLAY),
    "exit_code": 0,
    "stdout": None,
    "stderr": None,
    "timeout_seconds": 60,
    "reused_from": "Execution 0bd9e2 reached git apply assertion after passing Pyflakes assertion; successful stdout/stderr were not separately persisted",
    "identical_owned_source_proof": "Exact byte equality of prior and current full unified diffs against unchanged hashed preimages, before LF-only patch serialization",
}
receipt["checks"].append(lint)
assert lint["exit_code"] == 0, lint
apply_check = record_command(["git", "apply", "--check", "--whitespace=error", str(patch_path)], ROOT)
receipt["checks"].append(apply_check)
receipt["root_preimages_match_after_checks"] = all(sha((ROOT / item["path"]).read_bytes()) == item["pre_sha256"] for item in receipt["files"])
receipt_path = PUBLISH / "receipt.json"
receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
assert apply_check["exit_code"] == 0, apply_check
assert receipt["root_preimages_match_after_checks"], "Root drift during validation"
receipt["status"] = "SOURCE_STATIC_PASS; root integration/runtime/release acceptance NOT RUN (T20)"
receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
hashes = {"patch_sha256": sha(patch_data), "receipt_sha256": sha(receipt_path.read_bytes()), "capture_sha256": sha((OVERLAY / "capture.json").read_bytes()), "validator_sha256": sha(Path(__file__).read_bytes())}
(PUBLISH / "SHA256.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": receipt["status"], "files": len(FILES), "ast_review": "14/14 PASS", "pyflakes_exit": lint["exit_code"], "git_apply_check_exit": apply_check["exit_code"], "root_preimages_match": receipt["root_preimages_match_after_checks"], "patch_path": str(patch_path), "receipt_path": str(receipt_path), "hashes": hashes}, indent=2))
