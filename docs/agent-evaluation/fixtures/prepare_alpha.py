"""Prepare the alpha evaluation seed without carrying runtime metadata into it."""

from pathlib import Path
import shutil
import stat
import sys


SEED = Path(__file__).resolve().parent / "alpha"
FILES = (
    "docs/example.md",
    "src/demo_api/routes.py",
    "src/demo_core/__init__.py",
    "src/demo_core/client.py",
    "src/demo_core/config.py",
    "src/demo_core/consumer.py",
    "src/demo_core/export.py",
    "src/demo_core/paths.py",
    "src/demo_core/task_service.py",
    "src/demo_core/task_store.py",
    "src/demo_core/validation.py",
    "src/demo_ui/paths.py",
    "src/legacy/invoice.php",
    "tests/helpers.py",
)


def is_link_or_reparse(path: Path) -> bool:
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except FileNotFoundError:
        return False
    return path.is_symlink() or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def prepare(target: str) -> Path:
    path = Path(target)
    if not path.is_absolute() or path.exists() or is_link_or_reparse(path):
        raise ValueError("target must be an absolute, new directory")
    parent = path.parent.resolve(strict=True)
    if any((ancestor / ".git").exists() for ancestor in (parent, *parent.parents)):
        raise ValueError("target parent must not be inside a Git repository")
    seed = SEED.resolve(strict=True)
    for relative in FILES:
        candidate = seed / relative
        if any(is_link_or_reparse(p) for p in (candidate, *candidate.parents) if p != seed.parent):
            raise ValueError(f"linked seed path is not allowed: {relative}")
        if not candidate.is_file() or not candidate.resolve(strict=True).is_relative_to(seed):
            raise ValueError(f"invalid seed path: {relative}")
    result = parent / path.name
    result.mkdir()
    for relative in FILES:
        destination = result / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(seed / relative, destination)
    return result


if __name__ == "__main__":
    print(prepare(sys.argv[1]))
