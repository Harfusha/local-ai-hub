from __future__ import annotations

from local_ai_hub import repo_tools as repo_tools_module
from local_ai_hub.repo_tools import RepositoryTools


def test_context_pack_renders_without_reestimating_growing_prefix(monkeypatch):
    tools = RepositoryTools({})
    results = [
        {
            "path": f"src/module_{index}.py",
            "start_line": 1,
            "end_line": 2,
            "score": float(3 - index),
            "file_sha256": f"hash-{index}",
            "text": f"def item_{index}(): return {'x' * 80}",
        }
        for index in range(3)
    ]
    search = {"root": ".", "results": results, "scanned_files": 3}
    pieces = [
        f"--- {item['path']}:{item['start_line']}-{item['end_line']} score={item['score']} ---\n"
        f"{item['text']}\n"
        for item in results
    ]
    expected_context = "\n".join(pieces[:2])
    token_budget = repo_tools_module.estimate_tokens(expected_context)
    original_estimate_tokens = repo_tools_module.estimate_tokens
    estimated_inputs: list[str] = []

    def track_estimate(text: str) -> int:
        estimated_inputs.append(text)
        return original_estimate_tokens(text)

    monkeypatch.setattr(repo_tools_module, "estimate_tokens", track_estimate)

    packed = tools._pack_ranked_context(search, "query", token_budget)

    assert packed["context"] == expected_context
    assert packed["estimated_tokens"] == original_estimate_tokens(expected_context)
    assert packed["original_estimated_tokens"] == sum(
        original_estimate_tokens(
            f"--- {item['path']}:{item['start_line']}-{item['end_line']} score={item['score']} ---\n"
            f"{item['text']}\n"
        )
        for item in results
    )
    assert set(estimated_inputs) <= {*pieces, expected_context}


def _original_context_selection(results, max_tokens: int) -> tuple[str, list[str], int, int]:
    pieces: list[str] = []
    selected_paths: list[str] = []
    candidate_tokens = 0
    for item in results:
        header = f"--- {item['path']}:{item['start_line']}-{item['end_line']} score={item['score']} ---\n"
        candidate_tokens += repo_tools_module.estimate_tokens(header + item["text"] + "\n")
    for item in results:
        header = f"--- {item['path']}:{item['start_line']}-{item['end_line']} score={item['score']} ---\n"
        piece = header + item["text"] + "\n"
        if repo_tools_module.estimate_tokens("\n".join([*pieces, piece])) > max(0, int(max_tokens)):
            break
        pieces.append(piece)
        selected_paths.append(item["path"])
    context = "\n".join(pieces)
    estimated_tokens = repo_tools_module.estimate_tokens(context)
    return context, selected_paths, estimated_tokens, max(candidate_tokens, estimated_tokens)


def test_context_pack_selection_matches_original_tokenizer_at_budget_edges():
    tools = RepositoryTools({})
    for case_index, texts in enumerate((
        ("a" * 75, "b" * 147, "c" * 9),
        ("é漢😀" * 35, "λ🧪" * 61, "終" * 8),
        ("", "🙂" * 4, "plain text"),
        (),
    )):
        results = [
            {
                "path": f"src/module_{case_index}_{index}_é.py",
                "start_line": 1,
                "end_line": 2,
                "score": float(len(texts) - index),
                "file_sha256": f"hash-{case_index}-{index}",
                "text": text,
            }
            for index, text in enumerate(texts)
        ]
        full_context = "\n".join(
            f"--- {item['path']}:{item['start_line']}-{item['end_line']} score={item['score']} ---\n"
            f"{item['text']}\n"
            for item in results
        )
        boundaries = {0, 1, repo_tools_module.estimate_tokens(full_context),
                      repo_tools_module.estimate_tokens(full_context) + 100}
        pieces = [
            f"--- {item['path']}:{item['start_line']}-{item['end_line']} score={item['score']} ---\n"
            f"{item['text']}\n"
            for item in results
        ]
        for prefix_length in range(1, len(pieces) + 1):
            prefix_tokens = repo_tools_module.estimate_tokens("\n".join(pieces[:prefix_length]))
            boundaries.update({
                max(0, prefix_tokens - 1),
                prefix_tokens,
            })
        for budget in sorted(boundaries):
            expected = _original_context_selection(results, budget)
            actual = tools._pack_ranked_context(
                {"root": ".", "results": results, "scanned_files": len(results)},
                "query",
                budget,
            )
            assert (
                actual["context"],
                [item["path"] for item in actual["evidence"]],
                actual["estimated_tokens"],
                actual["original_estimated_tokens"],
            ) == expected
