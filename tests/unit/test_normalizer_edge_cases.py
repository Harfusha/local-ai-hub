from __future__ import annotations

import pytest
from local_ai_hub.normalizer import postprocess_model_output, postprocess_patch


def test_postprocess_model_output_unclosed_thinking_tag() -> None:
    raw = "<think>Analyzing the issue...\nNeed to check the database connection."
    cleaned, thinking = postprocess_model_output(raw, role="code")
    assert cleaned == ""
    assert thinking == "Analyzing the issue...\nNeed to check the database connection."


def test_postprocess_model_output_closed_then_unclosed_tag() -> None:
    raw = "<think>First thought</think>\nHere is the answer.\n<scratchpad>Partial unclosed notes"
    cleaned, thinking = postprocess_model_output(raw, role="general")
    assert cleaned == "Here is the answer."
    assert thinking == "First thought\n\nPartial unclosed notes"


def test_postprocess_model_output_orphaned_closing_tag() -> None:
    raw = "Normal answer text without open tag.</think>"
    cleaned, thinking = postprocess_model_output(raw, role="code")
    assert cleaned == "Normal answer text without open tag."
    assert thinking is None


def test_postprocess_model_output_repairs_unclosed_tilde_fence() -> None:
    raw = "~~~python\ndef hello():\n    print('world')"
    cleaned, _ = postprocess_model_output(raw, role="code", repair_fences=True)
    assert cleaned == "~~~python\ndef hello():\n    print('world')\n~~~"


def test_postprocess_patch_starts_at_hunk_header_when_preamble_present() -> None:
    diff_text = "Here is the fix for your issue:\n@@ -1,3 +1,3 @@\n-foo\n+bar\n baz"
    cleaned = postprocess_patch(diff_text)
    assert cleaned == "@@ -1,3 +1,3 @@\n-foo\n+bar\n baz\n"


def test_postprocess_patch_strips_trailing_fences_and_pleasantries() -> None:
    diff_text = (
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-x = 1\n"
        "+x = 2\n"
        "```\n"
        "Let me know if you need anything else!\n"
    )
    cleaned = postprocess_patch(diff_text)
    expected = (
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-x = 1\n"
        "+x = 2\n"
    )
    assert cleaned == expected
