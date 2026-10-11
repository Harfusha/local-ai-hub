from benchmarks.bench_context_element_identity import _context, _legacy_etag


def test_benchmark_exercises_large_payload_path_and_preserves_etag() -> None:
    baseline = _context(4)
    updated = _context(4)
    assert len(baseline.elements[0].content) >= 768
    object.__setattr__(updated.elements[0], "freshness", 999.0)

    assert updated.etag() == baseline.etag()
    assert _legacy_etag(updated) == _legacy_etag(baseline) == updated.etag()
