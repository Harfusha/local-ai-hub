from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from local_ai_hub.services import LocalAIServices


def test_repo_search_lexical_does_not_force_fingerprint(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "file.txt").write_text("hello world\n", encoding="utf-8")

    mock_repo_state = MagicMock()
    mock_repo_state.fingerprint.return_value = {
        "fingerprint": "mock_revision_123",
        "stale": False,
        "degraded": False,
    }

    mock_repo_tools = MagicMock()
    mock_repo_tools.search.return_value = {
        "success": True,
        "results": [{"path": "file.txt", "text": "hello world"}],
        "total_matches": 1,
        "count_exact": True,
        "has_more": False,
    }

    services = LocalAIServices(
        config={"server": {"state_dir": str(tmp_path / "state")}},
        runtime=MagicMock(),
        scheduler=MagicMock(),
        embeddings=MagicMock(),
        artifacts=MagicMock(),
        telemetry=MagicMock(),
        repo_tools=mock_repo_tools,
        repo_state=mock_repo_state,
    )

    res = services._repo_search_lexical(str(repo_dir), "hello")
    assert res.get("success") is True

    # mock_repo_state.fingerprint must be called, but NEVER with force=True
    assert mock_repo_state.fingerprint.called
    for call in mock_repo_state.fingerprint.call_args_list:
        args, kwargs = call
        assert kwargs.get("force") is not True, f"fingerprint was called with force=True: {call}"
