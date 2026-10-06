from __future__ import annotations

import json
from pathlib import Path

from local_ai_hub.budget import estimate_tokens
from local_ai_hub.config import load_config
from local_ai_hub.repo_tools import RepositoryTools


def _tools(tmp_path: Path) -> RepositoryTools:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[server]\nstate_dir = "{(tmp_path / "state").as_posix()}"\n'
        '[hardware]\nprofile = "cpu"\n',
        encoding="utf-8",
    )
    return RepositoryTools(load_config(str(config_path)))


def _rendered_from_evidence(evidence: list[dict]) -> str:
    pieces = []
    for item in evidence:
        header = (
            f"--- {item['path']}:{item['start_line']}-{item['end_line']} "
            f"score={item['score']} ---\n"
        )
        pieces.append(header + item["raw"] + "\n")
    return "\n".join(pieces)


def test_context_pack_paths_keeps_ranked_snippets_whole_and_evidence_aligned(tmp_path: Path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text(
        "needle needle " + "A" * 50 + "\n", encoding="utf-8"
    )
    (root / "src" / "b.py").write_text(
        "needle " + "B" * 1800 + "\n", encoding="utf-8"
    )
    tools = _tools(tmp_path)
    tools.snippet_lines = 0
    tools.max_snippets_per_file = 1
    budget = 300

    candidates = tools.search_paths(
        str(root), "needle", ["src/b.py", "src/a.py"], top_k=10
    )["results"]
    result = tools.context_pack_paths(
        str(root), "needle", ["src/b.py", "src/a.py"], max_tokens=budget, top_k=10
    )

    assert result["success"] is True
    assert result["evidence"]
    assert result["evidence"][0]["path"] == candidates[0]["path"] == "src/a.py"
    assert result["context"] == _rendered_from_evidence(result["evidence"])
    assert "[snippet truncated]" not in result["context"]
    assert len(result["evidence"]) == 1
    assert all(item["raw"] == candidate["text"] for item, candidate in zip(result["evidence"], candidates))
    assert estimate_tokens(json.dumps(result, ensure_ascii=False)) <= budget


def test_context_pack_preserves_stable_order_and_repository_exclusions(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / ".local-ai-hub").mkdir()
    (root / "src" / "z.py").write_text("needle zed\n", encoding="utf-8")
    (root / "src" / "a.py").write_text("needle alpha\n", encoding="utf-8")
    (root / ".local-ai-hub" / "secret.py").write_text("needle private\n", encoding="utf-8")
    tools = _tools(tmp_path)
    tools._rg = None
    monkeypatch.setattr(tools, "_git_grep_candidates", lambda *_args: (None, False))

    result = tools.context_pack(str(root), "needle", max_tokens=1200, top_k=10)

    assert result["success"] is True
    assert [item["path"] for item in result["evidence"]] == ["src/a.py", "src/z.py"]
    assert ".local-ai-hub/secret.py" not in result["context"]
    assert result["context"] == _rendered_from_evidence(result["evidence"])
