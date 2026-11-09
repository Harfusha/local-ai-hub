import subprocess

from local_ai_hub.services import LocalAIServices


def _git_root(tmp_path):
    subprocess.run(
        ["git", "init", "-q", str(tmp_path)], check=True, timeout=10,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return tmp_path


def test_validate_patch_preserves_lf_for_git_on_windows(tmp_path):
    root = _git_root(tmp_path)
    (root / "fixture.py").write_bytes(b"first = 0\nvalue = 1\nlast = 3\n")
    patch = (
        "diff --git a/fixture.py b/fixture.py\n"
        "--- a/fixture.py\n+++ b/fixture.py\n@@ -1,3 +1,3 @@\n"
        " first = 0\n-value = 1\n+value = 2\n last = 3\n"
    )

    result = LocalAIServices.validate_patch(None, {"root": str(root), "patch": patch})

    assert result["success"] is True
    assert result["valid"] is True, result
    assert result["syntax_valid"] is True
    assert result["applicability_checked"] is True
    assert "syntax is valid" in result["message"].lower()
    assert (root / "fixture.py").read_bytes() == b"first = 0\nvalue = 1\nlast = 3\n"


def test_validate_patch_message_separates_syntax_from_applicability(tmp_path):
    root = _git_root(tmp_path)
    (root / "fixture.py").write_bytes(b"value = 1\n")
    patch = (
        "diff --git a/fixture.py b/fixture.py\n"
        "--- a/fixture.py\n+++ b/fixture.py\n@@ -1 +1 @@\n"
        "-value = 2\n+value = 3\n"
    )

    result = LocalAIServices.validate_patch(None, {"root": str(root), "patch": patch})

    assert result["success"] is True
    assert result["valid"] is False
    assert result["syntax_valid"] is True
    assert result["applicability_checked"] is True
    assert "syntax is valid" in result["message"].lower()


def test_validate_patch_message_marks_corrupt_patch_syntax(tmp_path):
    root = _git_root(tmp_path)
    (root / "fixture.py").write_bytes(b"value = 1\n")
    patch = (
        "diff --git a/fixture.py b/fixture.py\n"
        "--- a/fixture.py\n+++ b/fixture.py\n@@ -1,2 +1,2 @@\n"
        "-value = 1\n+value = 2\n"
    )

    result = LocalAIServices.validate_patch(None, {"root": str(root), "patch": patch})

    assert result["success"] is True
    assert result["valid"] is False
    assert result["syntax_valid"] is False
    assert result["applicability_checked"] is True
    assert "syntax is invalid" in result["message"].lower()
