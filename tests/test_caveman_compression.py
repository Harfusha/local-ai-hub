from pathlib import Path
import json
from types import SimpleNamespace

import pytest

import local_ai_hub.caveman_instructions as caveman
from local_ai_hub.caveman_instructions import (
    apply_instruction,
    compact_local_prompt,
    discover_instruction_files,
    _local_openai_endpoint,
    restore_instruction_manifest,
    restore_instruction,
    stage_instruction,
)


def _pass_review(original: str, candidate: str) -> dict[str, object]:
    return {"equivalent": True, "missing": [], "weakened": [], "changed": [], "uncertain": []}


def _stage(source: Path, stage: Path, compressor, reviewer=_pass_review):
    return stage_instruction(source, stage, compressor, reviewer)


def test_stage_keeps_source_and_creates_hash_verified_backup(tmp_path: Path):
    agent = tmp_path / "agent"
    agent.mkdir()
    source = agent / "AGENTS.md"
    original = "Please make sure to run `command --flag` before you start.\n"
    source.write_text(original, encoding="utf-8")
    original_bytes = source.read_bytes()
    staged = _stage(source, tmp_path / "backups", lambda _: "Run `command --flag` first.\n")
    assert source.read_text(encoding="utf-8") == original
    assert staged.backup.read_bytes() == original_bytes
    assert staged.original_sha256 == staged.backup_sha256
    assert staged.candidate_sha256 != staged.original_sha256
    assert staged.semantic_review["equivalent"] is True
    assert (staged.backup.parent / "manifest.json").is_file()


def test_stage_rejects_missing_protected_inline_code_before_review(tmp_path: Path):
    source = tmp_path / "agent" / "AGENTS.md"
    source.parent.mkdir()
    source.write_text("Run `command --flag`.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="protected"):
        _stage(source, tmp_path / "stage", lambda _: "Run command.\n", lambda *_: pytest.fail("review must not run"))
    assert source.read_text(encoding="utf-8") == "Run `command --flag`.\n"


def test_stage_rejects_missing_versions_and_headings(tmp_path: Path):
    source = tmp_path / "agent" / "AGENTS.md"
    source.parent.mkdir()
    source.write_text("# Release 5.1.0\nUse version 5.1.0.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="protected"):
        _stage(source, tmp_path / "stage", lambda _: "# Release\nUse current version.\n")
    assert source.read_text(encoding="utf-8") == "# Release 5.1.0\nUse version 5.1.0.\n"


def test_semantic_review_failure_keeps_backup_but_never_returns_candidate(tmp_path: Path):
    source = tmp_path / "agent" / "AGENTS.md"
    source.parent.mkdir()
    original = "Always keep the source read-only.\n"
    source.write_text(original, encoding="utf-8")
    def failed_review(*_):
        return {"equivalent": False, "missing": ["read-only"], "weakened": [], "changed": [], "uncertain": []}
    with pytest.raises(ValueError, match="missing"):
        _stage(source, tmp_path / "stage", lambda _: "Keep source.\n", failed_review)
    backups = list((tmp_path / "stage").glob("instruction-*/original.md"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == original
    assert source.read_text(encoding="utf-8") == original


def test_apply_and_restore_are_hash_guarded_and_reversible(tmp_path: Path):
    source = tmp_path / "agent" / "AGENTS.md"
    source.parent.mkdir()
    original = "Please make sure to run tests before you start.\n"
    source.write_text(original, encoding="utf-8")
    staged = _stage(source, tmp_path / "stage", lambda _: "Run tests first.\n")
    apply_instruction(staged)
    assert source.read_bytes() == staged.candidate.read_bytes()
    restore_instruction(staged)
    assert source.read_text(encoding="utf-8") == original


def test_restore_from_manifest_is_available_after_process_restart(tmp_path: Path):
    source = tmp_path / "agent" / "AGENTS.md"
    source.parent.mkdir()
    original = "Please make sure to run tests before start.\n"
    source.write_text(original, encoding="utf-8")
    staged = _stage(source, tmp_path / "stage", lambda _: "Run tests first.\n")
    apply_instruction(staged)
    restore_instruction_manifest(staged.backup.parent / "manifest.json")
    assert source.read_text(encoding="utf-8") == original


def test_restore_manifest_refuses_paths_outside_staging_folder(tmp_path: Path):
    source = tmp_path / "agent" / "AGENTS.md"
    source.parent.mkdir()
    source.write_text("Please run tests before start.\n", encoding="utf-8")
    staged = _stage(source, tmp_path / "stage", lambda _: "Run tests first.\n")
    apply_instruction(staged)
    manifest_path = staged.backup.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["candidate"] = str(tmp_path / "outside.md")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="escape"):
        restore_instruction_manifest(manifest_path)
    assert source.read_bytes() == staged.candidate.read_bytes()


def test_local_openai_endpoint_adds_v1_and_rejects_remote_hosts():
    assert _local_openai_endpoint("http://127.0.0.1:11434") == "http://127.0.0.1:11434/v1"
    assert _local_openai_endpoint("http://localhost:11434") == "http://localhost:11434/v1"
    with pytest.raises(ValueError, match="local HTTP"):
        _local_openai_endpoint("https://example.com/v1")


def test_compressor_failure_reports_safe_reason_without_model_output(tmp_path: Path, monkeypatch):
    skill = tmp_path / "skill"
    (skill / "scripts").mkdir(parents=True)
    (skill / "scripts" / "__main__.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(
        caveman.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=2,
            stdout="Compression aborted: output is identical to input.\nsecret instruction text",
            stderr="",
        ),
    )
    with pytest.raises(RuntimeError, match="no useful reduction") as exc:
        caveman.compress_with_caveman("secret instruction text", skill_dir=skill, model="local", endpoint="http://127.0.0.1:11434")
    assert "secret instruction text" not in str(exc.value)


def test_apply_refuses_source_modified_after_staging(tmp_path: Path):
    source = tmp_path / "agent" / "AGENTS.md"
    source.parent.mkdir()
    source.write_text("Please run tests before start.\n", encoding="utf-8")
    staged = _stage(source, tmp_path / "stage", lambda _: "Run tests first.\n")
    source.write_text("another owner's update\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source changed"):
        apply_instruction(staged)
    assert source.read_text(encoding="utf-8") == "another owner's update\n"


def test_restore_refuses_later_source_edit(tmp_path: Path):
    source = tmp_path / "agent" / "AGENTS.md"
    source.parent.mkdir()
    source.write_text("Please run tests before start.\n", encoding="utf-8")
    staged = _stage(source, tmp_path / "stage", lambda _: "Run tests first.\n")
    apply_instruction(staged)
    source.write_text("later edit\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source changed"):
        restore_instruction(staged)
    assert source.read_text(encoding="utf-8") == "later edit\n"


def test_discovery_selects_agent_files_and_skips_managed_caches(tmp_path: Path):
    (tmp_path / "repo" / ".cursor" / "rules").mkdir(parents=True)
    (tmp_path / "repo" / ".codex" / "plugins" / "cache" / "vendor" / "skills").mkdir(parents=True)
    (tmp_path / "repo" / "docs").mkdir()
    agents = tmp_path / "repo" / "AGENTS.md"
    skill = tmp_path / "repo" / ".agents" / "skills" / "build" / "SKILL.md"
    rule = tmp_path / "repo" / ".cursor" / "rules" / "python.mdc"
    managed = tmp_path / "repo" / ".codex" / "plugins" / "cache" / "vendor" / "skills" / "SKILL.md"
    readme = tmp_path / "repo" / "docs" / "README.md"
    skill.parent.mkdir(parents=True)
    agents.write_text("agent", encoding="utf-8")
    skill.write_text("skill", encoding="utf-8")
    rule.write_text("rule", encoding="utf-8")
    managed.write_text("managed", encoding="utf-8")
    readme.write_text("ordinary doc", encoding="utf-8")
    found = set(discover_instruction_files([tmp_path / "repo"]))
    assert found == {agents.resolve(), skill.resolve(), rule.resolve()}


def test_discovery_rejects_managed_plugin_root(tmp_path: Path):
    root = tmp_path / "plugins" / "cache"
    root.mkdir(parents=True)
    with pytest.raises(ValueError, match="managed plugin/cache"):
        discover_instruction_files([root])


def test_cli_verifies_all_backups_before_first_compression(tmp_path: Path, monkeypatch, capsys):
    from local_ai_hub import __main__ as cli
    from local_ai_hub import caveman_instructions

    root = tmp_path / "repo"
    first = root / "one" / "AGENTS.md"
    second = root / "two" / "SKILL.md"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("Please make sure to run tests before committing.\n", encoding="utf-8")
    second.write_text("Please make sure to review changes before merging.\n", encoding="utf-8")
    monkeypatch.setattr(caveman_instructions, "discover_instruction_files", lambda _: [first, second])
    original_backup = caveman_instructions.backup_instruction
    prepared = []
    def backup(source, stage):
        result = original_backup(source, stage)
        prepared.append(result)
        return result
    def compress(text, **kwargs):
        assert len(prepared) == 2
        return "Run tests before commit.\n" if "committing" in text else "Review changes before merge.\n"
    monkeypatch.setattr(caveman_instructions, "backup_instruction", backup)
    monkeypatch.setattr(caveman_instructions, "compress_with_caveman", compress)
    monkeypatch.setattr(caveman_instructions, "review_instruction_semantics", lambda original, candidate, **kwargs: _pass_review(original, candidate))
    result = cli.main([
        "--discover-caveman", str(root), "--caveman-skill-dir", str(tmp_path),
        "--caveman-model", "qwen2.5-coder:7b", "--caveman-review-model", "qwen3.5:9b",
        "--caveman-staging-dir", str(tmp_path / "backups"),
    ])
    assert result == 0
    output = capsys.readouterr().out
    assert "verified byte-for-byte backups: 2/2" in output


def test_local_prompt_compaction_is_defaultable_and_preserves_structured_payloads():
    text = "Summarize this.  \n\n\nMore context."
    prompt, system = compact_local_prompt(text, "system", input_enabled=True, output_enabled=True, structured=False)
    assert prompt == "Summarize this.\n\nMore context."
    assert "Caveman style" in system
    assert "uncertainty" in system
    assert "answer directly" in system
    assert "prefer fragments over prose" in system
    assert "generic caveats" in system
    code = "```python\nx = 1\n\n\ny = 2\n```"
    assert compact_local_prompt(code, "system", input_enabled=True, output_enabled=True, structured=False)[0] == code
    hard_break = "Keep this line.  \nKeep next line separate."
    assert compact_local_prompt(
        hard_break, "system", input_enabled=True, output_enabled=False, structured=False
    )[0] == hard_break
    assert compact_local_prompt(text, "system", input_enabled=True, output_enabled=True, structured=True) == (text, "system")
    assert compact_local_prompt(text, "system", input_enabled=False, output_enabled=False, structured=False) == (text, "system")


def test_stage_rejects_secret_name_before_calling_compressor(tmp_path: Path):
    source = tmp_path / "credentials.md"
    source.write_text("sensitive", encoding="utf-8")
    called = []
    with pytest.raises(ValueError, match="eligible"):
        _stage(source, tmp_path / "stage", lambda text: called.append(text))
    assert not called


def test_staging_rejects_source_changed_during_compression(tmp_path: Path):
    source = tmp_path / "agent" / "AGENTS.md"
    source.parent.mkdir()
    source.write_text("original instruction body long enough for a candidate.\n", encoding="utf-8")
    def change_source(text):
        source.write_text("other owner change", encoding="utf-8")
        return "short candidate\n"
    with pytest.raises(ValueError, match="source changed"):
        _stage(source, tmp_path / "stage", change_source)
    assert source.read_text(encoding="utf-8") == "other owner change"


def test_cli_stages_and_applies_only_after_semantic_review(tmp_path: Path, monkeypatch, capsys):
    from local_ai_hub import __main__ as cli
    from local_ai_hub import caveman_instructions

    skill = tmp_path / "skill"
    (skill / "scripts").mkdir(parents=True)
    source = tmp_path / "agent" / "AGENTS.md"
    source.parent.mkdir()
    source.write_text("Please make sure to run `tests` now.\n", encoding="utf-8")
    monkeypatch.setattr(caveman_instructions, "compress_with_caveman", lambda text, **kwargs: "Run `tests` now.\n")
    monkeypatch.setattr(caveman_instructions, "review_instruction_semantics", lambda original, candidate, **kwargs: _pass_review(original, candidate))
    result = cli.main([
        "--stage-caveman", str(source), "--caveman-skill-dir", str(skill),
        "--caveman-model", "qwen2.5-coder:7b", "--caveman-review-model", "qwen3.5:9b",
        "--caveman-staging-dir", str(tmp_path / "stage"), "--apply-caveman",
    ])
    assert result == 0
    assert source.read_text(encoding="utf-8") == "Run `tests` now.\n"
    output = capsys.readouterr().out
    assert "semantic review: PASS" in output
    assert "sha256=" in output
    assert "applied: True" in output
