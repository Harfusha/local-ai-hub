from __future__ import annotations

import ast
from pathlib import Path
from local_ai_hub.deterministic import DeterministicEngine


def test_call_graph_diff_detects_missing_required_argument(tmp_path: Path) -> None:
    lib_py = tmp_path / "lib.py"
    caller_py = tmp_path / "caller.py"

    lib_py.write_text("def compute(x: int, y: int) -> int:\n    return x + y\n", encoding="utf-8")
    caller_py.write_text("from lib import compute\n\ndef run():\n    return compute(10, 20)\n", encoding="utf-8")

    extractor = DeterministicEngine()

    # Unified diff changing compute signature to require z
    diff = """--- a/lib.py
+++ b/lib.py
@@ -1,2 +1,2 @@
-def compute(x: int, y: int) -> int:
+def compute(x: int, y: int, z: int) -> int:
     return x + y + z
"""

    result = extractor.call_graph_diff(tmp_path, diff=diff)
    assert result["success"] is True
    assert len(result["modified_symbols"]) >= 1
    assert any(s["symbol"] == "compute" for s in result["modified_symbols"])

    breaking = result["breaking_callers"]
    assert len(breaking) == 1
    assert "caller.py" in breaking[0]["file"]
    assert breaking[0]["callee"] == "compute"
    assert "missing" in breaking[0]["reason"].lower() or "parameter" in breaking[0]["reason"].lower()


def test_call_graph_diff_detects_removed_symbol_call(tmp_path: Path) -> None:
    lib_py = tmp_path / "lib.py"
    caller_py = tmp_path / "caller.py"

    lib_py.write_text("def legacy_api():\n    return 42\n", encoding="utf-8")
    caller_py.write_text("from lib import legacy_api\n\ndef do_work():\n    return legacy_api()\n", encoding="utf-8")

    extractor = DeterministicEngine()

    diff = """--- a/lib.py
+++ b/lib.py
@@ -1,2 +0,0 @@
-def legacy_api():
-    return 42
"""

    result = extractor.call_graph_diff(tmp_path, diff=diff)
    assert result["success"] is True
    assert any(s["type"] == "removed_symbol" and s["symbol"] == "legacy_api" for s in result["modified_symbols"])
    breaking = result["breaking_callers"]
    assert len(breaking) == 1
    assert breaking[0]["callee"] == "legacy_api"
    assert "removed" in breaking[0]["reason"].lower()


def test_call_graph_diff_detects_removed_keyword_param(tmp_path: Path) -> None:
    lib_py = tmp_path / "lib.py"
    caller_py = tmp_path / "caller.py"

    lib_py.write_text("def render(title: str, legacy_flag: bool = False):\n    pass\n", encoding="utf-8")
    caller_py.write_text("from lib import render\n\ndef view():\n    render('test', legacy_flag=True)\n", encoding="utf-8")

    extractor = DeterministicEngine()

    diff = """--- a/lib.py
+++ b/lib.py
@@ -1,2 +1,2 @@
-def render(title: str, legacy_flag: bool = False):
+def render(title: str, modern_flag: bool = False):
     pass
"""

    result = extractor.call_graph_diff(tmp_path, diff=diff)
    assert result["success"] is True
    breaking = result["breaking_callers"]
    assert len(breaking) == 1
    assert breaking[0]["callee"] == "render"
    assert "legacy_flag" in breaking[0]["reason"]
