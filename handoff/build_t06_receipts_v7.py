from __future__ import annotations

import difflib
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(r"C:\Users\Adam\.local-ai-hub")
T06 = Path(r"C:\Users\Adam\.codex\worktrees\t06-safe-commands\.local-ai-hub")
BASE = ROOT / "src" / "local_ai_hub" / "commands.py"
V6 = T06 / "handoff" / "T06-T09-validation-receipts-v6-root-namespace-current.patch"
V7 = T06 / "handoff" / "T06-T09-validation-receipts-v7-root-namespace-current.patch"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing expected source block: {label}")
    return text.replace(old, new, 1)


def main() -> int:
    original = BASE.read_bytes()
    newline = "\r\n" if b"\r\n" in original else "\n"
    with tempfile.TemporaryDirectory(prefix="t06-v7-build-") as temp:
        work = Path(temp)
        package = work / "src" / "local_ai_hub"
        shutil.copytree(ROOT / "src" / "local_ai_hub", package)
        applied = subprocess.run(["git", "apply", str(V6)], cwd=work, capture_output=True, text=True)
        if applied.returncode:
            raise RuntimeError(applied.stderr or applied.stdout)

        source = package / "commands.py"
        raw = source.read_bytes()
        nl = "\r\n" if b"\r\n" in raw else "\n"
        text = raw.decode().replace("\r\n", "\n")
        text = replace_once(
            text,
            '''        caller_arguments_sha256: str = "",\n    ) -> None:''',
            '''        caller_arguments_sha256: str = "",\n        project_alias_required: bool = False,\n    ) -> None:''',
            "receipt parameters",
        )
        text = replace_once(
            text,
            '''            if (\n                not project_alias\n                or project_alias != criterion\n                or not project_config_digest\n                or not project_environment_sha256\n                or not configured_command_sha256\n                or not caller_arguments_sha256\n                or criterion_evidence_type(criterion) != evidence_type\n            ):\n                return\n            tokens = [token.lower() for token in shlex.split(command, posix=(os.name != "nt"))]\n            no_execution_options = {\n                "-h", "--help", "--version", "-version", "-v",\n                "--collect-only", "--co", "--fixtures", "--fixtures-per-test",\n                "--list-tests", "--dry-run",\n            }\n            if any(\n                token in no_execution_options\n                or token.startswith(("--help=", "--version="))\n                for token in tokens\n            ) or any(token in {";", "&&", "||", "|", ">", "<"} for token in tokens):\n                return\n            if evidence_type == "source_review":\n                validator_tools = {\n                    "ruff", "pyflakes", "flake8", "mypy", "pylint", "eslint",\n                    "tsc", "bandit", "shellcheck", "yamllint", "markdownlint",\n                    "biome", "phpstan", "phpcs", "clippy",\n                }\n                command_words = {Path(token.strip("\\\"'")).stem.lower() for token in tokens}\n                if not command_words.intersection(validator_tools):\n                    return\n''',
            '''            project_bound = any((\n                project_alias, project_config_digest, project_environment_sha256,\n                configured_command_sha256, caller_arguments_sha256,\n            ))\n            if project_bound and (\n                not project_alias\n                or project_alias != criterion\n                or not project_config_digest\n                or not project_environment_sha256\n                or not configured_command_sha256\n                or not caller_arguments_sha256\n            ):\n                return\n            if not project_bound and (project_alias_required or evidence_type == "source_review"):\n                return\n            if criterion_evidence_type(criterion) != evidence_type:\n                return\n            tokens = [token.lower() for token in shlex.split(command, posix=(os.name != "nt"))]\n            no_execution_options = {\n                "-h", "--help", "--version", "-version", "-V",\n                "--collect-only", "--co", "--fixtures", "--fixtures-per-test",\n                "--list-tests", "--dry-run",\n            }\n            if any(\n                token in no_execution_options\n                or token.startswith(("--help=", "--version="))\n                for token in tokens\n            ) or any(token in {";", "&&", "||", "|", ">", "<"} for token in tokens):\n                return\n            executable = Path(tokens[0].strip("\\\"'")).stem.lower() if tokens else ""\n            invoked_tools = {executable}\n            if (executable.startswith("python") or executable in {"pythonw", "py"}) and "-m" in tokens:\n                module_index = tokens.index("-m") + 1\n                if module_index < len(tokens):\n                    invoked_tools.add(tokens[module_index].split(".", 1)[0])\n            if executable in {"npm", "pnpm", "yarn", "dotnet", "cargo", "go"} and len(tokens) > 1:\n                invoked_tools.add(tokens[1])\n                invoked_tools.update(tokens[2:4])\n            test_subcommand = executable in {"npm", "pnpm", "yarn", "dotnet", "cargo", "go"} and "test" in tokens[1:5]\n            test_runners = {\n                "pytest", "py.test", "unittest", "jest", "vitest", "mocha",\n                "phpunit", "pester", "tox", "nox", "ctest", "hyperfine",\n            }\n            if evidence_type in {"test", "benchmark"} and not (invoked_tools.intersection(test_runners) or test_subcommand):\n                return\n            if evidence_type == "source_review":\n                validator_tools = {\n                    "ruff", "pyflakes", "flake8", "mypy", "pylint", "eslint",\n                    "tsc", "bandit", "shellcheck", "yamllint", "markdownlint",\n                    "biome", "phpstan", "phpcs", "clippy",\n                }\n                if not invoked_tools.intersection(validator_tools):\n                    return\n''',
            "admission rules",
        )
        text = replace_once(
            text,
            '''            execution_binding = hashlib.sha256(\n                json.dumps(\n                    {\n                        "project_alias": project_alias,\n                        "project_config_digest": project_config_digest,\n                        "configured_command_sha256": configured_command_sha256,\n                        "caller_arguments_sha256": caller_arguments_sha256,\n                        "command_sha256": command_digest,\n                        "project_environment_sha256": project_environment_sha256,\n                    },\n                    sort_keys=True,\n                    separators=(",", ":"),\n                ).encode("utf-8")\n            ).hexdigest()\n            proof = {''',
            '''            proof = {''',
            "conditional project binding",
        )
        text = replace_once(
            text,
            '''                "command_classification": evidence_type,\n                "command": command,\n                "project_alias": project_alias,\n                "project_config_digest": project_config_digest,\n                "project_environment_sha256": project_environment_sha256,\n                "configured_command_sha256": configured_command_sha256,\n                "caller_arguments_sha256": caller_arguments_sha256,\n                "project_execution_binding_sha256": execution_binding,\n                "command_sha256": command_digest,''',
            '''                "command_classification": evidence_type,\n                "command": command,\n                "command_sha256": command_digest,''',
            "generic proof shape",
        )
        text = replace_once(
            text,
            '''            if hasattr(self.artifacts, "put_json"):''',
            '''            if project_bound:\n                binding = {\n                    "project_alias": project_alias,\n                    "project_config_digest": project_config_digest,\n                    "configured_command_sha256": configured_command_sha256,\n                    "caller_arguments_sha256": caller_arguments_sha256,\n                    "command_sha256": command_digest,\n                    "project_environment_sha256": project_environment_sha256,\n                }\n                proof.update(binding)\n                proof["project_execution_binding_sha256"] = hashlib.sha256(\n                    json.dumps(binding, sort_keys=True, separators=(",", ":")).encode("utf-8")\n                ).hexdigest()\n            if hasattr(self.artifacts, "put_json"):''',
            "optional project binding",
        )

        run_start = text.index("    def run(\n")
        insert = '''        if not self.enabled:\n            return {"success": False, "error": "command broker disabled"}\n'''
        index = text.find(insert, run_start)
        if index < 0:
            raise RuntimeError("missing run entry")
        extended = insert + '''        project_alias_required = False\n        if record_verification and task_id and criterion and _project_command_context is None:\n            try:\n                project_context = self._cached_project_command_context(\n                    cwd, configured_state_dir(self.config)\n                )\n                if project_context.resolution.error_codes:\n                    project_alias_required = True\n                else:\n                    project_alias_required = criterion.strip() in project_context.settings.verification_rules\n            except Exception:\n                project_alias_required = True\n'''
        text = text[:index] + text[index:].replace(insert, extended, 1)
        text = text.replace(
            "                    caller_arguments_sha256=caller_arguments_sha256,\n                )",
            "                    caller_arguments_sha256=caller_arguments_sha256,\n                    project_alias_required=project_alias_required,\n                )",
        )
        if text.count("project_alias_required=project_alias_required") != 2:
            raise RuntimeError("expected both cache and execution receipt paths")
        text = replace_once(text, "                    import uuid\n", "", "remove redundant local uuid import")
        source.write_bytes(text.replace("\n", nl).encode())

        test_copy = work / "test_receipts.py"
        shutil.copy2(T06 / "tests" / "test_t06_project_validation_receipts.py", test_copy)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(work / "src")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short", str(test_copy)],
            cwd=work, env=env, capture_output=True, text=True,
        )
        print("pytest_exit=" + str(result.returncode))
        print((result.stdout + result.stderr)[-2400:])
        if result.returncode:
            return result.returncode

        updated = source.read_bytes()
        patch = "".join(difflib.unified_diff(
            original.decode().splitlines(True), updated.decode().splitlines(True),
            fromfile="a/src/local_ai_hub/commands.py", tofile="b/src/local_ai_hub/commands.py",
        ))
        V7.write_text(patch, encoding="utf-8", newline="")
        check = work / "check"
        (check / "src" / "local_ai_hub").mkdir(parents=True)
        shutil.copy2(BASE, check / "src" / "local_ai_hub" / "commands.py")
        checked = subprocess.run(["git", "apply", "--check", str(V7)], cwd=check, capture_output=True, text=True)
        print("git_apply_check_exit=" + str(checked.returncode))
        print("base_sha256=" + hashlib.sha256(original).hexdigest())
        print("result_sha256=" + hashlib.sha256(updated).hexdigest())
        print("patch_sha256=" + hashlib.sha256(V7.read_bytes()).hexdigest())
        if checked.returncode:
            print(checked.stderr or checked.stdout)
            return checked.returncode
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
