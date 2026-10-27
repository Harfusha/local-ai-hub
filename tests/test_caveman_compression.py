from pathlib import Path

import pytest

from local_ai_hub.caveman_instructions import stage_instruction, compact_local_prompt


def test_stage_keeps_original_and_writes_verified_backup(tmp_path: Path):
    (tmp_path / "agent").mkdir()
    source = tmp_path / "agent" / "AGENTS.md"
    source.write_text("Keep `command --flag` unchanged.\n", encoding="utf-8")
    stage = tmp_path / "staging"
    result = stage_instruction(source, stage, lambda text: text.replace(" unchanged", ""))
    assert source.read_text(encoding="utf-8") == "Keep `command --flag` unchanged.\n"
    assert result.backup.read_bytes() == source.read_bytes()
    assert result.candidate.read_text(encoding="utf-8") == "Keep `command --flag`.\n"


def test_stage_rejects_missing_protected_inline_code(tmp_path: Path):
    (tmp_path / "agent").mkdir()
    source = tmp_path / "agent" / "AGENTS.md"
    source.write_text("Run `command --flag`.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="protected"):
        stage_instruction(source, tmp_path / "stage", lambda _: "Run command.\n")
    assert source.read_text(encoding="utf-8") == "Run `command --flag`.\n"


def test_cli_stages_each_requested_instruction_without_changing_it(tmp_path: Path, monkeypatch, capsys):
    from local_ai_hub import __main__ as cli
    from local_ai_hub import caveman_instructions
    (tmp_path / "agent").mkdir()
    source = tmp_path / "agent" / "AGENTS.md"
    source.write_text("Run `tests` now.\n", encoding="utf-8")
    monkeypatch.setattr(caveman_instructions, "compress_with_caveman", lambda text, **kwargs: text.replace(" now", ""))
    result = cli.main(["--stage-caveman", str(source), "--caveman-skill-dir", str(tmp_path), "--caveman-model", "local-model", "--caveman-staging-dir", str(tmp_path / "staging")])
    assert result == 0
    assert source.read_text(encoding="utf-8") == "Run `tests` now.\n"
    assert "candidate" in capsys.readouterr().out


def test_local_prompt_compaction_is_opt_in_and_preserves_structured_content():
    text = "Summarize this.\n\n\nMore context."
    prompt, system = compact_local_prompt(text, "system", enabled=True, structured=False)
    assert prompt == "Summarize this.\n\nMore context."
    assert "Preserve all relevant facts" in system
    code = "```python\nx = 1\n\n\ny = 2\n```"
    assert compact_local_prompt(code, "system", enabled=True, structured=False)[0] == code
    assert compact_local_prompt(text, "system", enabled=True, structured=True) == (text, "system")
    assert compact_local_prompt(text, "system", enabled=False, structured=False) == (text, "system")


def test_staging_rejects_secret_name_before_calling_compressor(tmp_path: Path):
    source = tmp_path / "credentials.md"
    source.write_text("sensitive", encoding="utf-8")
    called = []
    with pytest.raises(ValueError, match="eligible"):
        stage_instruction(source, tmp_path / "stage", lambda text: called.append(text))
    assert not called


def test_staging_rejects_source_changed_during_compression(tmp_path: Path):
    agent = tmp_path / "agent"
    agent.mkdir()
    source = agent / "AGENTS.md"
    source.write_text("original", encoding="utf-8")
    def change_source(text):
        source.write_text("other owner change", encoding="utf-8")
        return text
    with pytest.raises(ValueError, match="source changed"):
        stage_instruction(source, tmp_path / "stage", change_source)
    assert source.read_text(encoding="utf-8") == "other owner change"
