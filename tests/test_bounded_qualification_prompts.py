from pathlib import Path


def test_canonical_prompts_preserve_qualified_inspection_contract():
    docs = Path(__file__).resolve().parents[1] / "docs"
    paragraphs = []
    for name in ("INSTALL_PROMPT.md", "UPDATE_PROMPT.md"):
        text = (docs / name).read_text(encoding="utf-8")
        paragraph = next(p for p in text.split("\n\n") if p.startswith("Bounded work may optionally use read-only tool exploration"))
        for required in ("`high`", "operator-reviewed C1/C2/C3", "exact serving model digest",
                         "default is disabled", "does not activate", "untrusted context",
                         "approved commands", "primary-agent diff/test/integration review",
                         "unknown or failed evidence is not success"):
            assert required in paragraph
        paragraphs.append(paragraph)
    assert paragraphs[0] == paragraphs[1]


def test_canonical_prompts_require_review_before_receipt_acceptance():
    docs = Path(__file__).resolve().parents[1] / "docs"
    paragraphs = []
    for name in ("INSTALL_PROMPT.md", "UPDATE_PROMPT.md"):
        text = (docs / name).read_text(encoding="utf-8")
        paragraph = next(p for p in text.split("\n\n") if p.startswith("For task-bound bounded work, `recorded_unmapped`"))
        for required in ("without attaching it to task completion", "mutation generation", "repository revision",
                         "earlier receipt stale", "do not establish complete verification",
                         "primary agent must review the result and integration"):
            assert required in paragraph
        paragraphs.append(paragraph)
    assert paragraphs[0] == paragraphs[1]
