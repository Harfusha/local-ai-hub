from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
import pytest

from local_ai_hub.code_index_demand import (
    one_hop_related_files,
    two_hop_related_files,
    two_hop_weighted_files,
)


def test_two_hop_demand_graph_resolution() -> None:
    # Set up a mock repo structure:
    # app.py -> service.py -> IRepository.py (interface)
    # app.py -> utils.py -> logger.py
    repo_tools = MagicMock()
    file_contents = {
        "app.py": "import service\nimport utils",
        "service.py": "from IRepository import RepoInterface",
        "utils.py": "import logger",
        "IRepository.py": "class RepoInterface: pass",
        "logger.py": "def log(msg): pass",
    }

    def fake_read_snapshot(path: Path) -> tuple[dict, list[str]]:
        rel = path.name
        content = file_contents.get(rel, "")
        return ({}, content.splitlines())

    repo_tools._read_snapshot.side_effect = fake_read_snapshot
    root = Path(".")
    eligible = set(file_contents.keys())

    # 1-hop from app.py: should only find service.py and utils.py
    hop1 = one_hop_related_files(root, ["app.py"], eligible, repo_tools)
    assert set(hop1) == {"service.py", "utils.py"}

    # 2-hop from app.py: should find hop 1 and hop 2 (IRepository.py and logger.py)
    hop2 = two_hop_related_files(root, ["app.py"], eligible, repo_tools)
    assert "service.py" in hop2
    assert "utils.py" in hop2
    assert "IRepository.py" in hop2
    assert "logger.py" in hop2

    # Weighted check: IRepository.py has interface boost (1.5 * decay or 1.5 direct)
    weighted = two_hop_weighted_files(root, ["app.py"], eligible, repo_tools)
    weights = dict(weighted)
    assert weights["service.py"] >= 1.0
    assert weights["utils.py"] >= 1.0
    # IRepository is hop2 from service.py, but has interface boost
    assert weights["IRepository.py"] > weights["logger.py"]
