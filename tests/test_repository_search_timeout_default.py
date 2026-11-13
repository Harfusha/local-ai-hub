from pathlib import Path
import tomllib


def test_repository_search_timeout_default_is_bounded_and_distributions_match():
    root = Path(__file__).resolve().parents[1]
    config_paths = (root / "defaults.toml", root / "src/local_ai_hub/defaults.toml")
    defaults = [
        tomllib.loads(path.read_text(encoding="utf-8"))["resilience"]
        for path in config_paths
    ]

    assert defaults[0] == defaults[1]
    assert defaults[0]["repository_search_timeout_seconds"] == 10

