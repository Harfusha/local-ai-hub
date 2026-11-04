from tools.benchmark_search_quality import evaluate, make_fixture, run


def test_metrics_deduplicate_paths_and_measure_negative_cases():
    result = evaluate(["noise.py", "target.py", "target.py"], ["target.py"])
    assert result["recall_at_k"] == 1.0
    assert result["reciprocal_rank"] == 0.5
    assert result["precision_at_k"] == 0.5
    assert evaluate([], [])["negative_correct"] is True
    assert evaluate(["noise.py"], [])["negative_correct"] is False


def test_fixture_labels_are_grounded_in_source(tmp_path):
    cases = make_fixture(tmp_path, noise_files=2)
    assert len(cases) >= 6
    for case in cases:
        for path in case["relevant"]:
            assert (tmp_path / path).is_file()
        if case["literal"]:
            for path in case["relevant"]:
                assert case["literal"].lower() in (tmp_path / path).read_text(encoding="utf-8").lower()


def test_service_benchmark_reports_its_boundary():
    result = run(repeats=1, noise_files=0, mode="service")
    assert "LocalAIServices.repo_search" in result["scope"]
    assert len(result["cases"]) >= 6
    cpp = next(case for case in result["cases"] if case["query"] == "C++")
    assert cpp["paths"] == ["src/literal.py"]


def test_heldout_suite_is_distinct_from_development_cases():
    result = run(repeats=1, noise_files=0, mode="service", suite="holdout")
    assert result["suite"] == "holdout"
    assert all(case["query"] != "C++" for case in result["cases"])
    assert len(result["cases"]) >= 6
