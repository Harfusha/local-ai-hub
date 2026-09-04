from __future__ import annotations

import pytest
from local_ai_hub.deterministic import DeterministicEngine


def test_python_removed_public_function():
    engine = DeterministicEngine(repo_tools=None)
    diff = """--- a/src/api.py
+++ b/src/api.py
@@ -10,5 +10,2 @@
-def fetch_user_record(user_id: str) -> dict:
-    return {"id": user_id}
-
 def get_status():
     return "ok"
"""
    facts = engine.diff_facts(diff)
    assert facts["deterministic"] is True
    assert "breaking_changes" in facts
    bc = facts["breaking_changes"]
    assert len(bc) == 1
    assert bc[0]["type"] == "removed_symbol"
    assert bc[0]["symbol"] == "fetch_user_record"
    assert bc[0]["file"] == "src/api.py"
    assert facts["risk_level"] == "high"


def test_python_private_function_ignored():
    engine = DeterministicEngine(repo_tools=None)
    diff = """--- a/src/utils.py
+++ b/src/utils.py
@@ -10,4 +10,1 @@
-def _internal_helper(x, y):
-    return x + y
-
 def public_api():
"""
    facts = engine.diff_facts(diff)
    assert len(facts.get("breaking_changes", [])) == 0


def test_python_signature_added_required_param():
    engine = DeterministicEngine(repo_tools=None)
    diff = """--- a/src/calc.py
+++ b/src/calc.py
@@ -5,3 +5,3 @@
-def compute_tax(amount, rate):
+def compute_tax(amount, rate, currency):
     pass
"""
    facts = engine.diff_facts(diff)
    bc = facts.get("breaking_changes", [])
    assert len(bc) == 1
    assert bc[0]["type"] == "signature_changed"
    assert bc[0]["symbol"] == "compute_tax"
    assert "required parameter" in bc[0]["description"].lower() or "signature" in bc[0]["description"].lower()
    assert facts["risk_level"] == "high"


def test_python_signature_added_optional_param_safe():
    engine = DeterministicEngine(repo_tools=None)
    diff = """--- a/src/calc.py
+++ b/src/calc.py
@@ -5,3 +5,3 @@
-def compute_tax(amount, rate):
+def compute_tax(amount, rate, currency="USD"):
     pass
"""
    facts = engine.diff_facts(diff)
    assert len(facts.get("breaking_changes", [])) == 0


def test_test_files_ignored_for_breaking_changes():
    engine = DeterministicEngine(repo_tools=None)
    diff = """--- a/tests/test_api.py
+++ b/tests/test_api.py
@@ -10,4 +10,0 @@
-def test_old_behavior():
-    assert True
"""
    facts = engine.diff_facts(diff)
    assert len(facts.get("breaking_changes", [])) == 0


def test_typescript_removed_export():
    engine = DeterministicEngine(repo_tools=None)
    diff = """--- a/frontend/src/api.ts
+++ b/frontend/src/api.ts
@@ -15,4 +15,0 @@
-export function fetchUserData(userId: string): Promise<User> {
-    return api.get(`/users/${userId}`);
-}
"""
    facts = engine.diff_facts(diff)
    bc = facts.get("breaking_changes", [])
    assert len(bc) == 1
    assert bc[0]["type"] == "removed_symbol"
    assert bc[0]["symbol"] == "fetchUserData"
    assert facts["risk_level"] == "high"


def test_csharp_removed_public_method():
    engine = DeterministicEngine(repo_tools=None)
    diff = """--- a/Assets/Scripts/GameManager.cs
+++ b/Assets/Scripts/GameManager.cs
@@ -20,4 +20,0 @@
-    public void ResetGameState(bool keepScore)
-    {
-    }
"""
    facts = engine.diff_facts(diff)
    bc = facts.get("breaking_changes", [])
    assert len(bc) == 1
    assert bc[0]["type"] == "removed_symbol"
    assert bc[0]["symbol"] == "ResetGameState"
    assert facts["risk_level"] == "high"


def test_go_removed_public_func():
    engine = DeterministicEngine(repo_tools=None)
    diff = """--- a/pkg/service/user.go
+++ b/pkg/service/user.go
@@ -10,3 +10,0 @@
-func GetUserRecord(id string) (*User, error) {
-	return nil, nil
-}
"""
    facts = engine.diff_facts(diff)
    bc = facts.get("breaking_changes", [])
    assert len(bc) == 1
    assert bc[0]["type"] == "removed_symbol"
    assert bc[0]["symbol"] == "GetUserRecord"
    assert facts["risk_level"] == "high"


def test_rust_removed_pub_fn():
    engine = DeterministicEngine(repo_tools=None)
    diff = """--- a/src/lib.rs
+++ b/src/lib.rs
@@ -5,3 +5,0 @@
-pub fn parse_header(input: &str) -> Result<Header, Error> {
-    unimplemented!()
-}
"""
    facts = engine.diff_facts(diff)
    bc = facts.get("breaking_changes", [])
    assert len(bc) == 1
    assert bc[0]["type"] == "removed_symbol"
    assert bc[0]["symbol"] == "parse_header"
    assert facts["risk_level"] == "high"

