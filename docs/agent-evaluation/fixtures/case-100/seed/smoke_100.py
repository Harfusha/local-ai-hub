"""Exercise the fixture export in a disposable directory, without issuing receipts."""
import csv
from pathlib import Path
from tempfile import TemporaryDirectory

from exporter import ExportCancelled, export


def main():
    with TemporaryDirectory(prefix="case-100-smoke-") as directory:
        path = Path(directory) / "export.csv"
        rows = [{"id": "1", "name": "Příliš žluťoučký"}]
        export(path, rows)
        with path.open(encoding="utf-8", newline="") as stream:
            if list(csv.DictReader(stream)) != rows:
                raise RuntimeError("export content did not round-trip")
        before = path.read_bytes()
        calls = 0

        def cancelled():
            nonlocal calls
            calls += 1
            return calls >= 3

        try:
            export(path, rows, cancelled=cancelled)
        except ExportCancelled:
            pass
        else:
            raise RuntimeError("late cancellation was not reported")
        if path.read_bytes() != before or set(path.parent.iterdir()) != {path}:
            raise RuntimeError("cancellation changed the export or left extra files")
    print("case-100 fixture smoke passed")


if __name__ == "__main__":
    main()
