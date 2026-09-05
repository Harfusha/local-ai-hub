from __future__ import annotations

from contextlib import closing
from pathlib import Path
import pytest
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.code_index import CodeIndex


def test_cross_repo_symbol_find_and_impact(tmp_path: Path):
    cfg = {"server": {"state_dir": str(tmp_path / "state")}}
    index = CodeIndex(cfg, repo_tools=None)
    engine = DeterministicEngine(cfg, repo_tools=None, code_index=index)

    repo_backend = str(tmp_path / "backend")
    repo_frontend = str(tmp_path / "frontend")

    # Seed symbols and refs into code_index
    # Backend defines UserAuthenticationService and AuthenticateUser
    with index._lock, closing(index._connect()) as con:
        con.execute(
            "INSERT INTO symbols (root, path, name, kind, line, end_line, name_path) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (repo_backend, "services/auth.py", "UserAuthenticationService", "class", 10, 50, "UserAuthenticationService"),
        )
        con.execute(
            "INSERT INTO symbols (root, path, name, kind, line, end_line, name_path) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (repo_backend, "services/auth.py", "AuthenticateUser", "function", 20, 35, "AuthenticateUser"),
        )
        # Frontend references AuthenticateUser
        con.execute(
            "INSERT INTO refs (root, path, name, line, kind) VALUES (?, ?, ?, ?, ?)",
            (repo_frontend, "src/api/authClient.ts", "AuthenticateUser", 15, "call"),
        )
        con.execute(
            "INSERT INTO refs (root, path, name, line, kind) VALUES (?, ?, ?, ?, ?)",
            (repo_frontend, "src/views/Login.vue", "AuthenticateUser", 42, "call"),
        )
        con.commit()

    # 1. Test cross_repo_symbol_find
    find_res = engine.cross_repo_symbol_find([repo_backend, repo_frontend], "AuthenticateUser")
    assert find_res["success"] is True
    assert find_res["total"] >= 1
    assert any(s["name"] == "AuthenticateUser" and s["repo"] == repo_backend for s in find_res["symbols"])

    # 2. Test cross_project_impact
    impact_res = engine.cross_project_impact("AuthenticateUser", [repo_backend, repo_frontend])
    assert impact_res["success"] is True
    assert impact_res["symbol"] == "AuthenticateUser"
    assert impact_res["origin_repo"] == repo_backend
    assert repo_frontend in impact_res["impacted_repos"]
    assert impact_res["cross_boundary_references_count"] == 2
    assert impact_res["risk_score"] in ("medium", "high", "critical")
    assert impact_res["suggested_order_of_edits"] == [repo_backend, repo_frontend]
