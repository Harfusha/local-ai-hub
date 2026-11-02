import json
from pathlib import Path
import subprocess
import sys
import unittest


class ListingTests(unittest.TestCase):
    def test_existing_listing_preserves_input(self):
        root = Path(__file__).resolve().parent
        result = subprocess.run([sys.executable, "-B", "-m", "task_export", "tasks.json"],
                                cwd=root, capture_output=True, text=True, encoding="utf-8", check=True)
        self.assertEqual(json.loads(result.stdout), json.loads((root / "tasks.json").read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
