from local_ai_hub.prompt_contracts import build_prompt, capability_for, list_supported_models


def test_candidate_fast_model_has_own_conservative_advisory_scope():
    candidate = capability_for("qwen3.5:4b-nvfp4")
    assert candidate.model == "qwen3.5:4b-nvfp4"
    assert "bounded_review" in candidate.can and "test_plan" in candidate.can
    assert "apply_changes" in candidate.cannot
    assert "security_decision" in candidate.cannot
    assert "final_verification" in candidate.cannot
    package = build_prompt(operation="review_diff", model="qwen3.5:4b-nvfp4", task="Review this change")
    assert package.capability.model == candidate.model
    assert "bounded_review" in package.system


def test_supported_vision_model_keeps_identity_without_assuming_backend_support():
    candidate = capability_for("qwen3-vl:4b")
    assert candidate.model == "qwen3-vl:4b"
    assert "visual_review" in candidate.can
    assert "apply_changes" in candidate.cannot
    assert "security_decision" in candidate.cannot
    assert "final_verification" in candidate.cannot
    package = build_prompt(operation="vision", model="qwen3-vl:4b", task="Describe the UI")
    assert package.capability.model == candidate.model
    assert "visual_review" in package.system


def test_retired_model_tags_are_not_in_the_prompt_capability_registry():
    supported = list_supported_models()

    assert "qwen3.5:4b-nvfp4" in supported
    assert "qwen3.5:4b-q4_K_M" not in supported
    assert "gemma4:12b" not in supported
    assert "qwen2.5-coder:14b" in supported


def test_heavy_model_names_preserve_security_and_write_boundaries():
    for model in ("qwen3.5:9b-q4_K_M", "unregistered-coder:14b"):
        candidate = capability_for(model)
        assert candidate.model == model
        assert "security_decision" in candidate.cannot
        assert "apply_changes" in candidate.cannot
        assert "final_verification" in candidate.cannot
        package = build_prompt(operation="code", model=model, task="Propose a bounded diff")
        assert "security_decision" in package.system
        assert "apply_changes" in package.system
    vision = capability_for("qwen3.5:9b-q4_K_M", role="vision")
    assert "security_decision" in vision.cannot
    assert "apply_changes" in vision.cannot
    assert "final_verification" in vision.cannot


def test_capability_matrix_distinguishes_all_configured_model_sizes():
    tiny = capability_for("qwen2.5-coder:0.5b")
    preprocessor = capability_for("qwen2.5-coder:1.5b")
    ordinary = capability_for("qwen2.5-coder:3b")
    reasoning = capability_for("qwen2.5-coder:7b")
    vision = capability_for("qwen3-vl:4b", role="vision")
    heavy_vision = capability_for("qwen3.5:9b", role="vision")

    assert "preprocess" in tiny.can
    assert "root_cause" in tiny.cannot
    assert "preprocess" in preprocessor.can
    assert "inference" in preprocessor.cannot
    assert "single_file_explain" in preprocessor.cannot
    assert "architecture" in preprocessor.cannot
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


def test_default_review_prompt_matches_consistency_validator_contract():
    package = build_prompt(operation="review", model="qwen2.5-coder:7b", task="Review supplied code.", changed_paths=["src/example.py"])
    response = package.user.split("REQUIRED RESPONSE:\n", 1)[1]
    assert "JSON" in response
    assert '"verdict"' in response
    assert '"findings"' in response
    assert '"citation"' in response
    assert "SUMMARY:" not in response
    assert len(package.system) < 2200


def test_compress_prompt_returns_only_compressed_context():
    package = build_prompt(
        operation="compress",
        model="qwen2.5-coder:7b",
        task="Compress supplied instruction text.",
        context="Source instruction: preserve all exact CLI flags and failure conditions.",
    )
    response = package.user.split("REQUIRED RESPONSE:\n", 1)[1]

    assert "Return only the compressed CONTEXT" in response
    assert "Do not summarize TASK" in response
    assert "1. SUMMARY:" not in response
    assert "EVIDENCE:" not in response
    assert "Každý řádek" not in package.user

