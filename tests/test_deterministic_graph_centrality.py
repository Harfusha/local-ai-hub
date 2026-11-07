from pathlib import Path
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.repo_tools import RepositoryTools


def test_deterministic_engine_computes_in_degree_centrality(tmp_path: Path):
    cfg = {"server": {"state_dir": str(tmp_path / "state")}}
    engine = DeterministicEngine(cfg, RepositoryTools({}))

    root = str(tmp_path / "repo")
    Path(root).mkdir()

    # file_core is imported by 3 files: a, b, c
    # file_leaf is imported by 0 files
    (Path(root) / "core.py").write_text("class CoreEngine: pass\n", encoding="utf-8")
    (Path(root) / "a.py").write_text("from core import CoreEngine\n", encoding="utf-8")
    (Path(root) / "b.py").write_text("from core import CoreEngine\n", encoding="utf-8")
    (Path(root) / "c.py").write_text("from core import CoreEngine\n", encoding="utf-8")
    (Path(root) / "leaf.py").write_text("x = 1\n", encoding="utf-8")

    engine.update_file(root, "core.py", "hash-core")
    engine.update_file(root, "a.py", "hash-a")
    engine.update_file(root, "b.py", "hash-b")
    engine.update_file(root, "c.py", "hash-c")
    engine.update_file(root, "leaf.py", "hash-leaf")

    ranks = engine.get_centrality_ranks(root)
    assert "core.py" in ranks
    assert "leaf.py" in ranks
    assert ranks["core.py"] > ranks["leaf.py"]
    assert ranks["core.py"] == 1.0
    assert ranks["leaf.py"] == 0.0
