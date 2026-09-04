from __future__ import annotations

from pathlib import Path

from local_ai_hub.rag import RAGStore, _simhash, _fragment_hash


class _Services:
    def __init__(self) -> None:
        self.embedded: list[str] = []

    def embed(self, texts, _tenant, **_kwargs):
        batch = list(texts)
        self.embedded.extend(batch)
        return {"success": True, "embeddings": [[1.0, 0.0] for _ in batch]}


class _Reranker:
    pass


def test_simhash_near_duplicate_vs_distinct():
    text1 = (
        "def compute_payroll(employee_id, hours, rate):\n"
        "    base_pay = hours * rate\n"
        "    tax = base_pay * 0.2\n"
        "    net = base_pay - tax\n"
        "    return {'employee': employee_id, 'net': net}\n"
    )
    # text2 is 95% identical to text1 with one comment added
    text2 = (
        "def compute_payroll(employee_id, hours, rate):\n"
        "    # calculate base pay\n"
        "    base_pay = hours * rate\n"
        "    tax = base_pay * 0.2\n"
        "    net = base_pay - tax\n"
        "    return {'employee': employee_id, 'net': net}\n"
    )
    # text3 is completely distinct
    text3 = (
        "class NetworkProtocolHandler:\n"
        "    def send_handshake(self, socket):\n"
        "        payload = b'\\x01\\x02\\x03\\x04'\n"
        "        socket.write(payload)\n"
    )

    fp1 = _simhash(text1)
    fp2 = _simhash(text2)
    fp3 = _simhash(text3)
    dist = (fp1 ^ fp2).bit_count()
    assert dist <= 4, f"expected near-duplicate dist <= 4, got {dist}"
    assert (fp1 ^ fp3).bit_count() > 10


def test_rag_index_skips_near_duplicate_chunks(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()

    # Create a source file where chunker produces multiple chunks, one of which is near duplicate
    chunk1 = (
        "def calculate_total_balance(account_number, transactions):\n"
        "    total = 0\n"
        "    for tx in transactions:\n"
        "        total += tx.amount\n"
        "    return total\n"
    ) * 4

    chunk2 = (
        "def calculate_total_balance(account_number, transactions):\n"
        "    # debug log for audit trail\n"
        "    total = 0\n"
        "    for tx in transactions:\n"
        "        total += tx.amount\n"
        "    return total\n"
    ) * 4

    distinct_chunk = (
        "def verify_rsa_signature(pub_key, data, signature):\n"
        "    return cryptography.verify(pub_key, data, signature)\n"
    ) * 4

    content = f"{chunk1}\n\n{chunk2}\n\n{distinct_chunk}"
    (root / "module.py").write_text(content, encoding="utf-8")

    services = _Services()
    store = RAGStore(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "models": {},
            "cpu_retrieval": {},
            "workspace_cache": {},
            "rag": {
                "extensions": [".py"],
                "ignore_dirs": [],
                "chunk_chars": 200,
                "chunk_overlap_chars": 0,
                "dedup_near_duplicates": True,
                "near_duplicate_max_hamming": 3,
            },
            "resilience": {"singleflight_wait_timeout_seconds": 2},
        },
        services,
        _Reranker(),
    )

    res = store.index(str(root), "tenant-test")
    assert res["success"] is True
    assert res["near_duplicates_skipped"] >= 1
