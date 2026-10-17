from __future__ import annotations

from pathlib import Path
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.repo_tools import RepositoryTools


def test_repo_topology_layered_detection(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    
    # Entrypoint
    (tmp_path / "cli.py").write_text("from services.user_service import run\nif __name__ == '__main__': run()\n", encoding="utf-8")

    # Services
    srv = tmp_path / "services"
    srv.mkdir()
    (srv / "user_service.py").write_text("from models.user import User\nfrom storage.db import Database\ndef run(): pass\n", encoding="utf-8")

    # Models
    mdl = tmp_path / "models"
    mdl.mkdir()
    (mdl / "user.py").write_text("class User: pass\n", encoding="utf-8")

    # Storage
    stg = tmp_path / "storage"
    stg.mkdir()
    (stg / "db.py").write_text("class Database: pass\n", encoding="utf-8")

    # Tests
    tst = tmp_path / "tests"
    tst.mkdir()
    (tst / "test_cli.py").write_text("def test_cli(): pass\n", encoding="utf-8")

    rt = RepositoryTools({})
    det = DeterministicEngine({}, repo_tools=rt)

    topo = det.repo_topology(str(tmp_path))
    assert topo["success"] is True
    assert "heuristic_layers" in topo
    layers = topo["heuristic_layers"]
    assert any("cli.py" in p for p in layers.get("entrypoints", []))
    assert any("user_service.py" in p for p in layers.get("core_services", []))
    assert any("user.py" in p for p in layers.get("domain_models", []))
    assert any("db.py" in p for p in layers.get("infrastructure", []))
    assert all("test_cli.py" not in p for paths in layers.values() for p in paths)
    assert "summary_markdown" in topo
    assert "cli.py" in topo["summary_markdown"]
    assert topo["coverage"]["module_graph_resolved"] is True
    assert any(edge["target"].endswith("models/user.py") for edge in topo["module_graph"]["edges"])
