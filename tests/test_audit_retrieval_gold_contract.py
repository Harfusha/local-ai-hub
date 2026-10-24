from local_ai_hub.evaluation_quality import paired_retrieval_delta, retrieval_metrics


PRODUCTION_PATH = "src/target.py"
PRODUCTION_SOURCE = """def desired_entry():
    return True

def nearby_but_wrong():
    return False
"""
TEST_PATH = "tests/test_target.py"
TEST_SOURCE = """def test_desired_entry():
    assert True
"""


def _report(*symbols):
    return {"success": True, "stale": False, "symbols": list(symbols)}


def _citation(path, line, name, kind="function"):
    return {"path": path, "line": line, "name": name, "kind": kind}


def test_symbol_contract_rejects_wrong_symbol_in_expected_file():
    metrics = retrieval_metrics(
        _report(_citation(PRODUCTION_PATH, 4, "nearby_but_wrong")),
        [PRODUCTION_PATH],
        {PRODUCTION_PATH: PRODUCTION_SOURCE},
        expected_symbols={PRODUCTION_PATH: ["desired_entry"]},
        intent="production",
    )

    assert metrics["expected_symbol_recall_at_k"] == 0
    assert metrics["citation_precision"] == 1
    assert metrics["source_evidence_sufficient"] is False
    assert metrics["model_quality_verified"] is False


def test_symbol_contract_rejects_wrong_line_for_expected_symbol():
    metrics = retrieval_metrics(
        _report(_citation(PRODUCTION_PATH, 2, "desired_entry")),
        [PRODUCTION_PATH],
        {PRODUCTION_PATH: PRODUCTION_SOURCE},
        expected_symbols={PRODUCTION_PATH: ["desired_entry"]},
        intent="production",
    )

    assert metrics["expected_symbol_recall_at_k"] == 0
    assert metrics["citation_precision"] == 0
    assert metrics["source_evidence_sufficient"] is False


def test_test_symbol_is_contamination_for_production_intent():
    metrics = retrieval_metrics(
        _report(_citation(TEST_PATH, 1, "test_desired_entry")),
        [PRODUCTION_PATH],
        {PRODUCTION_PATH: PRODUCTION_SOURCE, TEST_PATH: TEST_SOURCE},
        expected_symbols={PRODUCTION_PATH: ["desired_entry"]},
        intent="production",
    )

    assert metrics["test_source_contamination_count"] == 1
    assert metrics["citation_precision"] == 0
    assert metrics["source_evidence_sufficient"] is False


def test_explicit_test_intent_accepts_exact_test_symbol():
    metrics = retrieval_metrics(
        _report(_citation(TEST_PATH, 1, "test_desired_entry")),
        [TEST_PATH],
        {TEST_PATH: TEST_SOURCE},
        expected_symbols={TEST_PATH: ["test_desired_entry"]},
        intent="test",
    )

    assert metrics["expected_symbol_recall_at_k"] == 1
    assert metrics["citation_precision"] == 1
    assert metrics["test_source_contamination_count"] == 0
    assert metrics["source_evidence_sufficient"] is True
    assert metrics["model_quality_verified"] is False


def test_paired_delta_rejects_changed_target_or_intent_contract():
    baseline = {
        "retrieval": [{
            "case": "entrypoint",
            "query": "find target entrypoint",
            "expected_path": PRODUCTION_PATH,
            "expected_symbols": {PRODUCTION_PATH: ["desired_entry"]},
            "intent": "production",
            "metrics": {
                "status": "measured",
                "measurement_scope": "symbol_ast",
                "k": 5,
                "recall_at_k": 1,
                "reciprocal_rank": 1,
                "citation_validity": 1,
                "expected_symbol_recall_at_k": 1,
                "citation_precision": 1,
                "source_evidence_sufficient": True,
            },
        }]
    }
    changed_target = {"retrieval": [{**baseline["retrieval"][0], "expected_symbols": {PRODUCTION_PATH: ["nearby_but_wrong"]}}]}
    changed_intent = {"retrieval": [{**baseline["retrieval"][0], "intent": "test"}]}
    changed_k = {"retrieval": [{**baseline["retrieval"][0], "metrics": {**baseline["retrieval"][0]["metrics"], "k": 6}}]}
    missing_scope = {"retrieval": [{**baseline["retrieval"][0], "metrics": {key: value for key, value in baseline["retrieval"][0]["metrics"].items() if key != "measurement_scope"}}]}
    regressed = {"retrieval": [{**baseline["retrieval"][0], "metrics": {
        **baseline["retrieval"][0]["metrics"],
        "expected_symbol_recall_at_k": 0.5,
        "citation_precision": 0.75,
        "source_evidence_sufficient": False,
    }}]}

    assert paired_retrieval_delta(baseline, changed_target)["status"] == "unverified"
    assert paired_retrieval_delta(baseline, changed_intent)["status"] == "unverified"
    assert paired_retrieval_delta(baseline, changed_k)["status"] == "unverified"
    assert paired_retrieval_delta(baseline, missing_scope)["status"] == "unverified"
    delta = paired_retrieval_delta(baseline, regressed)
    assert delta["success"] is True
    assert delta["signed_deltas"]["expected_symbol_recall_at_k"] == -0.5
    assert delta["signed_deltas"]["citation_precision"] == -0.25
    assert delta["signed_deltas"]["source_evidence_sufficient"] == -1.0


def test_malformed_symbol_contract_fails_closed():
    for expected_symbols, intent in (
        ({PRODUCTION_PATH: []}, "production"),
        ({PRODUCTION_PATH: ["desired_entry", 2]}, "production"),
        ({PRODUCTION_PATH: ["desired_entry"]}, "Production"),
        ({"../outside.py": ["desired_entry"]}, "production"),
    ):
        metrics = retrieval_metrics(
            _report(_citation(PRODUCTION_PATH, 1, "desired_entry")),
            [PRODUCTION_PATH],
            {PRODUCTION_PATH: PRODUCTION_SOURCE},
            expected_symbols=expected_symbols,
            intent=intent,
        )
        assert metrics["success"] is False
        assert metrics["status"] == "unverified"


def test_path_only_results_remain_explicitly_path_scoped():
    metrics = retrieval_metrics(
        _report(_citation(PRODUCTION_PATH, 1, "a different symbol")),
        [PRODUCTION_PATH],
        {PRODUCTION_PATH: PRODUCTION_SOURCE},
    )

    assert metrics["measurement_scope"] == "path_only"
    assert metrics["source_evidence_sufficient"] is False
    assert metrics["model_quality_verified"] is False


def test_malformed_symbol_citations_fail_closed_without_type_errors():
    for bad in (
        {"path": [], "line": 1, "name": "desired_entry", "kind": "function"},
        {"path": PRODUCTION_PATH, "line": True, "name": "desired_entry", "kind": "function"},
        {"path": PRODUCTION_PATH, "line": 1, "name": [], "kind": "function"},
        {"path": PRODUCTION_PATH, "line": 1, "name": "desired_entry", "kind": []},
    ):
        metrics = retrieval_metrics(
            _report(bad),
            [PRODUCTION_PATH],
            {PRODUCTION_PATH: PRODUCTION_SOURCE},
            expected_symbols={PRODUCTION_PATH: ["desired_entry"]},
            intent="production",
        )
        assert metrics["success"] is True
        assert metrics["citation_precision"] == 0
        assert metrics["source_evidence_sufficient"] is False
