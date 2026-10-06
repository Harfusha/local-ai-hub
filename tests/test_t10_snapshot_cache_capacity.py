from local_ai_hub.repo_tools import RepositoryTools


def test_snapshot_cache_default_capacity_covers_search_file_limit() -> None:
    tools = RepositoryTools({"search": {"max_files": 10_000}})

    assert tools.snapshot_max_entries >= tools.max_files


def test_explicit_snapshot_cache_capacity_is_preserved() -> None:
    tools = RepositoryTools({
        "search": {"max_files": 10_000},
        "snapshot_cache": {"max_entries": 2048},
    })

    assert tools.snapshot_max_entries == 2048
