from pathlib import Path


def test_case136_has_one_terminal_final_gate_after_all_actions():
    text = (Path(__file__).resolve().parents[1] / "docs/agent-evaluation/prompts.md").read_text(
        encoding="utf-8"
    )
    case = text.split("### 136 —", 1)[1]

    assert "Před první finální zprávou uzavři všech 16 větví" in case
    assert "Nikdy nevracej `actions: []` ani méně než 16 položek" in case
    assert "bez hostově doloženého úplného enumu nastav enum_status přesně na agent-reported/NOT_VERIFIED" in case
    assert "Duplicitní final zprávy znamenají `FAIL`" in case
    assert case.rstrip().removesuffix("~~~").rstrip().endswith(
        "Po této jediné finální odpovědi okamžitě zastav; žádná další zpráva, commentary, final ani nástroj."
    )
