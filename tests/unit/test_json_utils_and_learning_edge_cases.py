from __future__ import annotations

from pathlib import Path

from local_ai_hub import json_utils
from local_ai_hub.json_utils import (
    backend_name,
    dumps_bytes,
    is_fast_backend,
    safe_loads,
)
from local_ai_hub.learning import UsageLearner


def test_json_utils_surrogate_bytes_and_safe_loads(monkeypatch) -> None:
    monkeypatch.setattr(json_utils, "_orjson", None)
    monkeypatch.setattr(json_utils, "_msgspec", None)

    assert is_fast_backend() is False
    assert backend_name() == "stdlib"

    encoded = dumps_bytes({"bad": "surrogate\ud800"}, sort_keys=True)
    assert isinstance(encoded, bytes)
    assert b"surrogate" in encoded

    assert safe_loads('{"a": 1}') == {"a": 1}
    assert safe_loads(b'{"a": 2}') == {"a": 2}
    assert safe_loads("{invalid json", default={"fallback": True}) == {"fallback": True}
    assert safe_loads(None, default=[]) == []
    assert safe_loads(123, default="none") == "none"
    assert safe_loads(True, default=None) is None


def test_usage_learner_nan_inf_bool_surrogates_and_helpers(tmp_path: Path) -> None:
    learner = UsageLearner(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "learning": {
                "enabled": 1,
                "max_queries_per_project": float("nan"),
                "max_query_chars": float("inf"),
            },
        }
    )
    assert learner.max_queries == 64
    assert learner.max_query_chars == 240
    assert learner.count() == 0

    bool_learner = UsageLearner(
        {
            "server": {"state_dir": str(tmp_path / "state_bool")},
            "learning": {
                "enabled": True,
                "max_queries_per_project": False,
                "max_query_chars": False,
            },
        }
    )
    assert bool_learner.max_queries == 64
    assert bool_learner.max_query_chars == 240

    assert UsageLearner.intent(None) == "general"  # type: ignore[arg-type]
    assert UsageLearner.intent(True) == "general"  # type: ignore[arg-type]
    assert UsageLearner.intent("fix\x00 crash in auth") == "security"

    repo = tmp_path / "repo"
    repo.mkdir()

    # Empty or null-only root should be ignored instead of resolving to CWD
    learner.record("   ", "valid query string here")
    learner.record("\x00", "valid query string here")
    assert learner.count() == 0
    assert learner.hot_queries("   ") == []

    # Surrogates and null bytes in query should be sanitized without UnicodeEncodeError
    learner.record(f"  {repo}\x00 ", "pytest\x00 failure with surrogate \ud800 token")
    assert learner.count() == 1
    assert learner.count(str(repo)) == 1

    hot_nan = learner.hot_queries(str(repo), limit=float("nan"))  # type: ignore[arg-type]
    assert len(hot_nan) == 1
    assert "\x00" not in hot_nan[0]
    assert "\ud800" not in hot_nan[0]

    hot_bool = learner.hot_queries(str(repo), limit=False)  # type: ignore[arg-type]
    assert len(hot_bool) == 1

    learner.clear(str(repo))
    assert learner.count(str(repo)) == 0
    assert learner.count() == 0
