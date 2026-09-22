from local_ai_hub.prompt_contracts import build_prompt, capability_for


def test_capability_matrix_distinguishes_all_configured_model_sizes():
    tiny = capability_for("qwen2.5-coder:0.5b")
    fast = capability_for("qwen2.5-coder:1.5b")
    ordinary = capability_for("qwen2.5-coder:3b")
    reasoning = capability_for("qwen2.5-coder:7b")
    vision = capability_for("qwen3-vl:4b", role="vision")
    heavy_vision = capability_for("qwen3.5:9b", role="vision")

    assert "preprocess" in tiny.can
    assert "root_cause" in tiny.cannot
    assert "single_file_explain" in fast.can
    assert "architecture" in fast.cannot
    assert "bounded_review" in ordinary.can
    assert "security_decision" in ordinary.cannot
    assert "root_cause" in reasoning.can
    assert "apply_changes" in reasoning.cannot
    assert "visual_review" in vision.can
    assert "source_only_reasoning" in vision.cannot
    assert "visual_review" in heavy_vision.can
    assert "root_cause" in heavy_vision.can


def test_integrated_profile_prompt_is_bounded_and_explicit():
    package = build_prompt(
        operation="reason",
        model="qwen2.5-coder:1.5b",
        profile="integrated",
        task="Najdi příčinu chyby v autentizaci.",
        context="[E1] src/auth.py:42 validation branch returns early.",
        changed_paths=["src/auth.py"],
        evidence_ids=["E1"],
    )

    assert len(package.system) < 2200
    assert len(package.user) < 5000
    assert "integrated" in package.system
    assert "E1" in package.user
    assert "Nevymýšlej" in package.user
    assert "Konkrétní závěr" in package.user


def test_specialized_diff_review_has_static_contract():
    package = build_prompt(
        operation="review_diff",
        model="qwen2.5-coder:7b",
        task="Zkontroluj regresní rizika.",
        context="diff --git a/src/auth.py b/src/auth.py\n+return True\n- return check(token)",
        changed_paths=["src/auth.py"],
        evidence_ids=["E-DIFF"],
    )

    assert "REVIEW_DIFF" in package.user
    assert "regression" in package.system.lower()
    assert "changed hunk" in package.user.lower()
    assert "E-DIFF" in package.user
    assert "None found" in package.user

