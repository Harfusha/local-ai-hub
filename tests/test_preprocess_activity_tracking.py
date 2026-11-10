from types import SimpleNamespace

from local_ai_hub.services import LocalAIServices


def test_foreground_repository_profile_refreshes_project_activity(tmp_path):
    root = str(tmp_path.resolve())
    touched = []
    services = object.__new__(LocalAIServices)
    services.preprocessor = SimpleNamespace(touch_if_registered=touched.append)
    services.repo_tools = SimpleNamespace(project_profile=lambda _root: {"success": True})
    services.repo_flight = SimpleNamespace(
        get_or_compute=lambda _key, compute: (compute(), False, False)
    )
    services._repo_cache_state = lambda _root: {"fingerprint": "fixture"}

    result = services.repo_profile(root)

    assert result["success"] is True
    assert touched == [root]
