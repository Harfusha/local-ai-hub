"""Create a fresh, non-sensitive long-input sandbox for Case 066."""
from pathlib import Path
import sys


def prepare(destination: str, repetitions: int = 64) -> Path:
    candidate = Path(destination)
    if not candidate.is_absolute():
        raise ValueError("sandbox root must be absolute")
    root = candidate.resolve()
    if not root.parent.is_dir():
        raise ValueError("sandbox parent must already exist")
    if root.exists():
        raise FileExistsError(root)
    if not 1 <= repetitions <= 128:
        raise ValueError("repetitions must be between 1 and 128")

    seed = Path(__file__).with_name("long_input.md").read_text(encoding="utf-8")
    root.mkdir()
    sections = [f"## Segment {index + 1}\n\n{seed}" for index in range(repetitions)]
    (root / "long_input.md").write_text("\n\n".join(sections), encoding="utf-8", newline="\n")
    return root


if __name__ == "__main__":
    if len(sys.argv) not in {2, 3}:
        raise SystemExit("Usage: prepare.py ABSOLUTE_NEW_ROOT [REPETITIONS]")
    count = int(sys.argv[2]) if len(sys.argv) == 3 else 64
    print(prepare(sys.argv[1], count))
