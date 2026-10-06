from local_ai_hub.repo_tools import RepositoryTools


def test_retired_external_codegraph_data_stays_excluded_from_scan():
    tools = RepositoryTools({})
    assert ".codegraphcontext" in tools.ignore_dirs
