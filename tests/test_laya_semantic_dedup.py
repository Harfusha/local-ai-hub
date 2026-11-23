import pytest
from src.local_ai_hub.laya_semantic_dedup import LayaSemanticDeduplicator


def test_semantic_deduplication_exact_and_paraphrase():
    dedup = LayaSemanticDeduplicator(default_threshold=0.75)

    # Index an entry
    prompt1 = "how to run full pytest regression suite on windows"
    payload1 = {"command": "python -m pytest tests/ -q", "exit_code": 0}
    dedup.index_prompt("p1", prompt1, payload1)

    # 1. Exact match
    match_exact = dedup.find_match("how to run full pytest regression suite on windows")
    assert match_exact is not None
    assert match_exact.matched_id == "p1"
    assert match_exact.similarity == 1.0
    assert match_exact.cached_payload == payload1

    # 2. Paraphrased query with minor variation
    match_para = dedup.find_match("run full pytest regression suite on windows fast")
    assert match_para is not None
    assert match_para.matched_id == "p1"
    assert match_para.similarity > 0.80

    # 3. Completely unrelated query should not match
    match_unrelated = dedup.find_match("initialize docker container database on linux")
    assert match_unrelated is None
