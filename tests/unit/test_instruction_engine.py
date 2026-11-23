from __future__ import annotations

from pathlib import Path
import pytest

from local_ai_hub.client_adapters.instruction_engine import (
    InstructionEngine,
)

from local_ai_hub.client_adapters.registry import (
    get_adapter,
)


def test_instruction_engine_target_paths(tmp_path: Path):
    engine_ag = InstructionEngine("antigravity", repo_root=tmp_path)
    paths_ag = [p.name for _, p in engine_ag.target_paths()]
    assert "GEMINI.md" in paths_ag or "AGENTS.md" in paths_ag

    engine_claude = InstructionEngine("claude", repo_root=tmp_path)
    paths_claude = [p.name for _, p in engine_claude.target_paths()]
    assert "CLAUDE.md" in paths_claude

    engine_cursor = InstructionEngine("cursor", repo_root=tmp_path)
    paths_cursor = [p.name for _, p in engine_cursor.target_paths()]
    assert ".cursorrules" in paths_cursor


def test_instruction_engine_inject_and_remove(tmp_path: Path):
    engine = InstructionEngine("codex", repo_root=tmp_path)
    target_file = tmp_path / "AGENTS.md"
    target_file.write_text("# Existing User Guide\nDo not delete me.\n", encoding="utf-8")

    res_inject = engine.inject(dry_run=False)
    assert res_inject[str(target_file)]["success"] is True
    assert res_inject[str(target_file)]["changed"] is True

    content_after = target_file.read_text(encoding="utf-8")
    assert "# Existing User Guide" in content_after
    assert "LOCAL AI HUB" in content_after

    res_remove = engine.remove(dry_run=False)
    assert res_remove[str(target_file)]["success"] is True
    assert res_remove[str(target_file)]["changed"] is True

    content_final = target_file.read_text(encoding="utf-8")
    assert "# Existing User Guide" in content_final
    assert "LOCAL AI HUB" not in content_final
