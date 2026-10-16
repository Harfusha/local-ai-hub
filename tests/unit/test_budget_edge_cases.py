from __future__ import annotations

from local_ai_hub.budget import (
    PackedText,
    RootFamilyBudget,
    chars_for_tokens,
    estimate_tokens,
    fit_text,
)


def test_estimate_tokens_and_chars_for_tokens_edge_cases() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens(None) == 0  # type: ignore[arg-type]
    # Unpaired UTF-16 surrogate must not raise UnicodeEncodeError
    assert estimate_tokens("surrogate\ud800text") > 0

    assert chars_for_tokens(0) == 0
    assert chars_for_tokens(-10) == 0
    assert chars_for_tokens(float("nan")) == 0  # type: ignore[arg-type]
    assert chars_for_tokens(float("inf")) == 0  # type: ignore[arg-type]
    assert chars_for_tokens(True) == 0  # type: ignore[arg-type]
    assert chars_for_tokens(10) == 34


def test_packed_text_sanitization_and_helpers() -> None:
    pt = PackedText(
        text="hello\x00world",
        estimated_tokens=-5,
        truncated=False,
        original_tokens=-10,
    )
    assert pt.text == "helloworld"
    assert pt.estimated_tokens == 0
    assert pt.original_tokens == 0
    assert pt.is_empty() is False
    assert pt.saved_tokens() == 0
    assert pt.compression_ratio() == 1.0

    pt_trunc = PackedText(
        text="short",
        estimated_tokens=25,
        truncated=True,
        original_tokens=100,
    )
    assert pt_trunc.saved_tokens() == 75
    assert pt_trunc.compression_ratio() == 0.25
    d = pt_trunc.to_dict()
    assert d["estimated_tokens"] == 25
    assert d["original_tokens"] == 100
    assert d["truncated"] is True


def test_root_family_budget_sanitization_and_lifecycle_helpers() -> None:
    budget = RootFamilyBudget(default_limit=float("nan"), max_active_scopes=-5)  # type: ignore[arg-type]
    assert budget.default_limit == 0
    assert budget.max_active_scopes == 1

    res = budget.reserve(
        "  fam\x00 ",
        input_tokens=float("nan"),  # type: ignore[arg-type]
        output_tokens=50,
        scope=" sc1\x00 ",
        task_id=" t1\x00 ",
    )
    assert res["status"] == "accepted"
    assert res["family"] == "fam"
    assert res["used"] == 50
    assert res["task_id"] == "t1"
    assert budget.used_tokens("fam") == 50
    assert budget.active_scopes_count("fam") == 1

    # Release with NaN tokens does not crash
    rel = budget.release("fam", tokens=float("nan"), scope="sc1")  # type: ignore[arg-type]
    assert rel["status"] == "released"
    assert budget.active_scopes_count("fam") == 0

    budget.reset("fam")
    assert budget.used_tokens("fam") == 0


def test_fit_text_surrogate_and_nan_max_tokens_safety() -> None:
    res_none = fit_text(None, 100)  # type: ignore[arg-type]
    assert res_none.text == ""
    assert res_none.is_empty() is True

    long_text = ("line_content_\ud800_" * 1000)
    fitted = fit_text(long_text, float("nan"))  # type: ignore[arg-type]
    assert fitted.truncated is True
    assert fitted.saved_tokens() > 0
