import json
from pathlib import Path
from tools.model_training.generate_dpo_pairs import (
    create_rejected_card,
    generate_dpo_dataset,
    _inject_antipattern,
    _mutate_verbatim_quote,
)


def test_antipattern_injection():
    # 1. Off-by-one
    assert _inject_antipattern("for i in 0 < len") == "for i in 0 <= len"
    assert _inject_antipattern("i > 0") == "i >= 0"
    assert _inject_antipattern("x + 1") == "x - 1"

    # 2. Inverted boolean
    assert _inject_antipattern("if a == b:") == "if a != b:"
    assert _inject_antipattern("if status != 200:") == "if status == 200:"
    assert _inject_antipattern("return True if valid else False") == "return True if not valid else False"

    # 3. Unchecked unwrap
    assert _inject_antipattern("let r = Ok(val);") == "let r = Err(val);"


def test_create_rejected_card():
    chosen = {
        "purpose": "Memory allocator pool",
        "symbols": ["acquire_buffer", "release_buffer"],
        "dependencies": ["std::sync::Arc"],
        "evidence": [
            {"field": "purpose", "value": "Memory allocator pool", "quote": "fn acquire_buffer() -> Buffer"}
        ],
    }
    source = "fn acquire_buffer() -> Buffer { Buffer::new() }\nfn release_buffer(b: Buffer) {}"

    # Generate 20 rejected cards to verify all perturbations execute cleanly
    for _ in range(20):
        rejected = create_rejected_card(chosen, source)
        assert rejected != chosen
        assert isinstance(rejected, dict)


def test_generate_dpo_dataset(tmp_path: Path):
    sft_file = tmp_path / "sft.jsonl"
    out_dpo = tmp_path / "dpo.jsonl"

    card = {
        "purpose": "Calculates cryptographic signature",
        "symbols": ["sign_message"],
        "dependencies": ["sha2"],
        "evidence": [{"field": "purpose", "value": "Calculates signature", "quote": "fn sign_message()"}],
    }
    sample_row = {
        "id": "row_1",
        "group_id": "crypto",
        "source_sha256": "abcdef123456",
        "messages": [
            {"role": "system", "content": "You are a code analyzer."},
            {"role": "user", "content": "CURRENT SOURCE (authority):\nfn sign_message() -> Sig { Sig::default() }"},
            {"role": "assistant", "content": json.dumps(card)},
        ],
    }
    sft_file.write_text(json.dumps(sample_row) + "\n", encoding="utf-8")

    count = generate_dpo_dataset(sft_file, out_dpo, max_pairs=10)
    assert count == 1
    assert out_dpo.exists()

    dpo_data = json.loads(out_dpo.read_text(encoding="utf-8").strip())
    assert dpo_data["id"] == "row_1"
    assert "prompt" in dpo_data
    assert "chosen" in dpo_data
    assert "rejected" in dpo_data
    assert dpo_data["chosen"] != dpo_data["rejected"]
