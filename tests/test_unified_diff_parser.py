from local_ai_hub.deterministic import DeterministicEngine


def test_malformed_hunk_does_not_consume_following_file_headers():
    diff = """--- a/first.py
+++ b/first.py
@@ -1,3 +1 @@
-old
--- a/second.py
+++ b/second.py
@@ -1 +1 @@
-before
+after
"""
    facts = DeterministicEngine(repo_tools=None).diff_facts(diff)

    assert facts["files"] == ["first.py", "second.py"]
    assert facts["additions"] == 1
    assert facts["deletions"] == 2
