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
