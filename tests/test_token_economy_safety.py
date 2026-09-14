from pathlib import Path
import sys
import unittest

# Always test the checkout under development, not an installed Hub copy.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from local_ai_hub.commands import CommandBroker
from local_ai_hub.token_economy import _trim_run_safe_command


class TrimRunSafetyTests(unittest.TestCase):
    def setUp(self):
        self.broker = object.__new__(CommandBroker)
        self.broker.config = {
            "commands": {
                "enabled": True,
                "allow_read": True,
                "allow_validation": True,
                "allow_build": True,
            }
        }

    def test_command_broker_allows_token_economy_readers(self):
        allowed = (
            "tokcount src/",
            "repo-map -n 100 src/",
            "grep-ast CommandBroker src/local_ai_hub/commands.py",
            "files-to-prompt -c README.md",
            "sg scan --pattern 'class CommandBroker' src/",
            "repomix --stdout --compress",
            "trim-run -n 40 pytest -q",
        )
        for command in allowed:
            with self.subTest(command=command):
                result = self.broker._classify_single(command)
                self.assertTrue(result["allowed"], result)

    def test_command_broker_rejects_writer_modes_and_shell_execution(self):
        blocked = (
            "ast-grep -o result.yaml",
            "ast-grep scan --pattern x -o result.yaml",
            "sg -uall",
            "sg scan --pattern x -uall",
            "repomix --stdout --remote https://example.invalid/repo",
            "repomix --compress --output snapshot.md",
            "trim-run python -c 'print(1)'",
        )
        for command in blocked:
            with self.subTest(command=command):
                result = self.broker._classify_single(command)
                self.assertFalse(result["allowed"], result)

    def test_allows_read_only_and_validation_commands(self):
        self.assertTrue(_trim_run_safe_command(["rg", "-n", "token", "src/" ]))
        self.assertTrue(_trim_run_safe_command(["rg", "-u", "token", "src/" ]))
        self.assertTrue(_trim_run_safe_command(["repomix", "--stdout", "--compress"] ))
        self.assertTrue(_trim_run_safe_command(["python", "-m", "pytest", "-q"] ))

    def test_rejects_commands_that_can_write_or_execute_arbitrary_code(self):
        blocked = (
            ["python", "-c", "print('unsafe')"],
            ["repomix", "--compress", "--output", "snapshot.md"],
            ["ast-grep", "scan", "--pattern", "x", "-o", "fixes.yaml"],
            ["sg", "scan", "--pattern", "x", "-u"],
            ["git", "add", "README.md"],
            ["rg", "token", ";", "del", "/q", "important.txt"],
        )
        for command in blocked:
            with self.subTest(command=command):
                self.assertFalse(_trim_run_safe_command(command))


if __name__ == "__main__":
    unittest.main()
