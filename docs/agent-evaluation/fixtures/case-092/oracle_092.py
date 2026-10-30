"""Oracle for a disposable case-092 copy; not an Agent OS receipt."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().with_name("report.py")


class OutputContract(unittest.TestCase):
    def run_report(self, *args):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, timeout=10, env=env)

    def test_stdout_without_output_argument(self):
        result = self.run_report("--name", "Žofie")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout.decode("utf-8")), {"greeting": "Hello, Žofie!"})
        self.assertTrue(result.stdout.endswith(b"\n"))

    def test_output_matches_stdout_and_overwrites_existing_target(self):
        with tempfile.TemporaryDirectory(dir=SCRIPT.parent) as directory:
            target = Path(directory) / "report.json"
            target.write_bytes(b"old data")
            result = self.run_report("--name", "Žofie", "--output", str(target))
            self.assertEqual(result.returncode, 0)
            self.assertEqual(target.read_bytes(), result.stdout)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"greeting": "Hello, Žofie!"})

    def test_write_failure_is_nonzero(self):
        with tempfile.TemporaryDirectory(dir=SCRIPT.parent) as directory:
            target = Path(directory) / "missing" / "report.json"
            result = self.run_report("--output", str(target))
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
