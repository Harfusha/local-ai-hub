from local_ai_hub.search_fusion import fuse_search_candidates


def test_fusion_counts_each_source_once_per_file_and_keeps_provenance():
    lexical = [{"path": "doc/a.md", "text": "lexical"},
               {"path": "doc/a.md", "text": "duplicate"},
               {"path": "doc/b.md", "text": "other"}]
    semantic = [{"path": "doc/b.md", "text": "semantic"},
                {"path": "doc/b.md", "text": "another chunk"}]
    results = fuse_search_candidates(lexical, semantic)
    assert [item["path"] for item in results] == ["doc/b.md", "doc/a.md"]
    assert results[0]["sources"] == ["lexical", "semantic"]
    assert results[1]["sources"] == ["lexical"]


def test_fusion_is_deterministic_and_prefers_lexical_on_equal_score():
    results = fuse_search_candidates([{"path": "z.py"}], [{"path": "a.md"}])
    assert [item["path"] for item in results] == ["z.py", "a.md"]
    assert results == fuse_search_candidates([{"path": "z.py"}], [{"path": "a.md"}])


def test_fusion_keeps_only_bounded_candidates_and_rejects_invalid_paths():
    results = fuse_search_candidates(
        [{"path": "../escape"}, {"path": "/absolute"}, {"path": "good.py"}],
        [{"path": "good.py"}, {"path": "other.py"}], limit=1,
    )
    assert [item["path"] for item in results] == ["good.py"]


def test_fusion_retains_relevant_chunk_evidence_from_both_sources():
    results = fuse_search_candidates(
        [{"path": "src/Foo.php", "chunk_id": "lex-1", "source_id": "repo", "content_hash": "a", "text": "wrong snippet", "relevance": 0.2}],
        [{"path": "src/Foo.php", "chunk_id": "sem-2", "source_id": "repo", "content_hash": "b", "text": "right snippet", "relevance": 0.9}],
    )

    item = results[0]
    assert item["sources"] == ["lexical", "semantic"]
    assert item["primary_match"]["text"] == "right snippet"
    assert {match["text"] for match in item["alternative_matches"]} == {"wrong snippet"}
    assert item["source_breakdown"].keys() == {"lexical", "semantic"}


def test_fusion_keeps_multiple_chunks_for_a_file_and_deduplicates_only_identical_evidence():
    shared = {"path": "src/Foo.php", "source_id": "repo", "chunk_id": "chunk-1", "content_hash": "hash-1", "text": "same"}
    results = fuse_search_candidates(
        [shared, {**shared, "text": "duplicate"}, {**shared, "chunk_id": "chunk-2", "content_hash": "hash-2", "text": "other"}],
        [shared],
    )

    assert len(results) == 1
    assert len(results[0]["matches"]) == 2
    assert results[0]["matches"][0]["sources"] == ["lexical", "semantic"]
    assert results[0]["truncated"] is False


def test_fusion_default_path_identity_is_case_sensitive_and_host_independent():
    results = fuse_search_candidates(
        [{"path": "Src/Foo.php", "chunk_id": "a", "content_hash": "1"}],
        [{"path": "src/foo.php", "chunk_id": "b", "content_hash": "2"}],
    )

    assert len(results) == 2
    assert fuse_search_candidates(
        [{"path": r"./src\Foo.php", "chunk_id": "a", "content_hash": "1"}],
        [],
    )[0]["path"] == "src/Foo.php"


def test_fusion_can_use_explicit_case_insensitive_repository_policy():
    results = fuse_search_candidates(
        [{"path": "Src/Foo.php", "chunk_id": "a", "content_hash": "1"}],
        [{"path": "src/foo.php", "chunk_id": "b", "content_hash": "2"}],
        case_sensitive=False,
    )

    assert len(results) == 1
    assert results[0]["path"] == "Src/Foo.php"


def test_fusion_duplicate_chunk_preserves_higher_relevance_independent_of_order():
    lex_low = [{"path": "src/Foo.php", "chunk_id": "c1", "source_id": "repo", "content_hash": "h1", "text": "snippet", "relevance": 0.1}]
    sem_high = [{"path": "src/Foo.php", "chunk_id": "c1", "source_id": "repo", "content_hash": "h1", "text": "snippet", "relevance": 0.9}]

    lex_high = [{"path": "src/Foo.php", "chunk_id": "c1", "source_id": "repo", "content_hash": "h1", "text": "snippet", "relevance": 0.9}]
    sem_low = [{"path": "src/Foo.php", "chunk_id": "c1", "source_id": "repo", "content_hash": "h1", "text": "snippet", "relevance": 0.1}]

    res1 = fuse_search_candidates(lex_low, sem_high)
    res2 = fuse_search_candidates(lex_high, sem_low)

    assert len(res1) == 1 and len(res2) == 1
    match1 = res1[0]["primary_match"]
    match2 = res2[0]["primary_match"]

    assert match1["relevance"] == 0.9
    assert match2["relevance"] == 0.9
    assert match1["relevance_by_source"] == {"lexical": 0.1, "semantic": 0.9}
    assert match2["relevance_by_source"] == {"lexical": 0.9, "semantic": 0.1}
    assert match1["sources"] == ["lexical", "semantic"]
    assert match2["sources"] == ["lexical", "semantic"]


def test_fusion_handles_nan_inf_and_string_scores_safely():
    c1 = [{"path": "a.py", "chunk_id": "c1", "content_hash": "h1", "relevance": float("nan")}]
    c2 = [{"path": "a.py", "chunk_id": "c1", "content_hash": "h1", "relevance": float("inf")}]
    c3 = [{"path": "b.py", "chunk_id": "c2", "content_hash": "h2", "relevance": "0.75"}]

    res = fuse_search_candidates(c1, c2)
    assert len(res) == 1
    assert "relevance" not in res[0]["primary_match"] or res[0]["primary_match"]["relevance"] is None

    res_str = fuse_search_candidates(c3, [])
    assert len(res_str) == 1
    assert res_str[0]["primary_match"]["relevance"] == 0.75

