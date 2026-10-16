"""The DAG API rejects retired ownership inputs before executing work."""

import pytest

from local_ai_hub.swarm import execute_swarm_dag


def test_retired_coordinator_keyword_rejects_before_callback(tmp_path):
    marker = tmp_path / "callback-ran"

    def callback():
        marker.write_text("unexpected", encoding="utf-8")

    with pytest.raises(TypeError, match="coordinator"):
        execute_swarm_dag(
            [{"id": "first", "callable": callback}],
            coordinator=object(),
            worktree_path=tmp_path,
        )

    assert not marker.exists()
