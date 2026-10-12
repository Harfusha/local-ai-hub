from pathlib import Path

import pytest

from local_ai_hub.repo_tools import RepositoryTools, is_root_archive_path


@pytest.mark.parametrize(
    "relative",
    [
        ".validation/t17-sync-20261006/package-pytest/test_generated_mcp_config/generated/schemas/local_ai_repo.json",
        "artifacts/t08-root-current-agent-tasks-preimage.py",
        "artifacts/t08-root-current-agent-tasks-replay.py",
        "artifacts/t08-root-current-agent-tasks-memory-transition.py",
        "artifacts/t08-ast-check-current-source.py",
        "artifacts/t08-ast-check-run/source_copy.py",
        "artifacts/t08-global-tombstone-kaql2q6e/src/local_ai_hub/agent_memory.py",
        "artifacts/t08-refresh-8t1jjznh/src/local_ai_hub/agent_memory.py",
        "artifacts/t08-t05-final-check-vtmyznvd/tests/test_agent_memory.py",
        "artifacts/t08-private-check/tools/doctor.py",
    ],
)
def test_known_root_validation_and_source_copies_are_archives(relative: str) -> None:
    assert is_root_archive_path(Path(relative))


@pytest.mark.parametrize(
    "relative",
    [
        "artifacts/release/current.py",
        "artifacts/resources/diagram.svg",
        "artifacts/t08-private-check/resources/diagram.svg",
        "artifacts/release/src/local_ai_hub/current.py",
        "artifacts/t08-root-current-agent-tasks.md",
        "src/t08-ast-check-example.py",
        ".validation/project-docs/overview.md",
        ".validation/t17-sync-20261006/notes/overview.md",
        ".validation/t17-sync-20261006/package-pytest/test_example/output.txt",
    ],
)
def test_regular_resources_and_unrecognized_validation_files_remain_searchable(relative: str) -> None:
    assert not is_root_archive_path(Path(relative))


def test_repository_inventory_filters_known_copies_and_keeps_regular_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    relative_paths = (
        ".validation/t17-sync-20261006/package-pytest/test_generated_mcp_config/generated/schemas/local_ai_repo.json",
        "artifacts/t08-root-current-agent-tasks-preimage.py",
        "artifacts/release/current.py",
        ".validation/project-docs/overview.md",
    )
    for relative in relative_paths:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("marker\n", encoding="utf-8")

    tools = RepositoryTools({"rag": {"extensions": [".py", ".json", ".md"]}})
    scanned = {path.relative_to(root).as_posix() for path in tools.iter_files(str(root))}

    assert scanned == {"artifacts/release/current.py", ".validation/project-docs/overview.md"}
