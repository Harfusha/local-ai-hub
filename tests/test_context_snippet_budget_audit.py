from __future__ import annotations

from pathlib import Path

from local_ai_hub.budget import estimate_tokens
from local_ai_hub.config import load_config
from local_ai_hub.repo_tools import RepositoryTools


def test_context_pack_keeps_ranked_snippets_whole_and_aligned_with_evidence(tmp_path: Path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("needle needle " + "A" * 50 + "\n", encoding="utf-8")
    (root / "src" / "b.py").write_text("needle " + "B" * 1800 + "\n", encoding="utf-8")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[server]\nstate_dir = "{(tmp_path / "state").as_posix()}"\n[hardware]\nprofile = "cpu"\n',
        encoding="utf-8",
    )
    tools = RepositoryTools(load_config(str(config_path)))
    tools.snippet_lines = 0
    tools.max_snippets_per_file = 1
    budget = 300

    candidates = tools.search_paths(str(root), "needle", ["src/b.py", "src/a.py"], top_k=10)["results"]
    result = tools.context_pack_paths(
        str(root), "needle", ["src/b.py", "src/a.py"], max_tokens=budget, top_k=10
    )

    assert result["success"] is True
    assert result["evidence"]
    assert result["evidence"][0]["path"] == candidates[0]["path"]
    expected = "\n".join(
        f"--- {item['path']}:{item['start_line']}-{item['end_line']} score={item['score']} ---\n"
        f"{item['raw']}\n"
        for item in result["evidence"]
    )
    assert result["context"] == expected
    assert "[snippet truncated]" not in result["context"]
    assert estimate_tokens(result["context"]) <= budget
