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
    return "\n".join(
        f"--- {item['path']}:{item['start_line']}-{item['end_line']} "
        f"score={item['score']} ---\n{item['raw']}\n"
        for item in evidence
    )


def test_targeted_context_uses_ranked_whole_snippets_with_provenance_budget(tmp_path: Path):
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
    assert len(result["evidence"]) == 1
    assert result["evidence"][0]["path"] == candidates[0]["path"] == "src/a.py"
    assert result["context"] == _rendered_from_evidence(result["evidence"])
    assert "[snippet truncated]" not in result["context"]
    assert result["evidence"][0]["raw"] == candidates[0]["text"]
    assert estimate_tokens(json.dumps(result, ensure_ascii=False)) <= budget


def test_snippet_merge_harmony_preserves_ranked_prefix_and_transport_budget():
    from local_ai_hub.response_budget import budget_response
    from local_ai_hub.token_accounting import json_tokens

    tools = RepositoryTools({})
    candidates = [
        {
            "path": path, "start_line": 1, "end_line": 1,
            "score": float(3 - index), "file_sha256": f"hash-{index}",
            "text": text,
        }
        for index, (path, text) in enumerate((
            ("src/high.py", "HIGH_WHOLE_SNIPPET " + "a" * 850),
            ("src/middle.py", "MIDDLE_TOO_LARGE " + "b" * 5000),
            ("src/low.py", "LOW_MUST_NOT_SKIP_MIDDLE"),
        ))
    ]
    budget = 512
    packed = tools._pack_ranked_context(
        {"root": ".", "results": candidates, "scanned_files": 3},
        "ranked prefix", budget, targeted=True,
    )

    # Preserve whole snippets and aligned provenance from the isolated branch,
    # plus master's rule that a smaller lower-ranked item cannot jump the queue.
    assert packed["success"] is True
    assert packed["targeted"] is True
    assert [item["path"] for item in packed["evidence"]] == ["src/high.py"]
    assert packed["evidence"][0]["raw"] == candidates[0]["text"]
    assert packed["context"] == _rendered_from_evidence(packed["evidence"])
    assert "[snippet truncated]" not in packed["context"]
    assert packed["estimated_tokens"] <= budget
    assert estimate_tokens(json.dumps(packed, ensure_ascii=False)) > budget

    # The repository's context budget and the public serialized response budget
    # are distinct. Exercise the existing transport limiter without changing it.
    evidence_id = "E0123456789abcdef0123"
    envelope = {
        **packed, "context_id": "ctx-snippet-harmony", "repo_revision": "rev-harmony",
        "evidence_ids": [evidence_id],
        "evidence": [{**packed["evidence"][0], "evidence_id": evidence_id}],
    }
    bounded = budget_response(
        envelope, max_tokens=budget, profile="compact",
        protected_keys=("success", "context_id", "repo_revision", "evidence_ids"),
    )
    assert bounded["success"] is True
    assert bounded["context_id"] == envelope["context_id"]
    assert bounded["repo_revision"] == envelope["repo_revision"]
    assert bounded["evidence_ids"] == [evidence_id]
    assert bounded["response_budget"]["original_tokens"] > budget
    assert bounded["response_budget"]["returned_tokens"] == json_tokens(bounded) <= budget


def test_general_context_keeps_deterministic_order_and_exclusions(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / ".local-ai-hub").mkdir()
    (root / "src" / "z.py").write_text("needle zed\n", encoding="utf-8")
    (root / "src" / "a.py").write_text("needle alpha\n", encoding="utf-8")
    (root / ".local-ai-hub" / "secret.py").write_text(
        "needle private\n", encoding="utf-8"
    )
    tools = _tools(tmp_path)
    tools._rg = None
    monkeypatch.setattr(tools, "_git_grep_candidates", lambda *_args: (None, False))

    result = tools.context_pack(str(root), "needle", max_tokens=1200, top_k=10)

    assert result["success"] is True
    assert [item["path"] for item in result["evidence"]] == ["src/a.py", "src/z.py"]
    assert ".local-ai-hub/secret.py" not in result["context"]
    assert result["context"] == _rendered_from_evidence(result["evidence"])
