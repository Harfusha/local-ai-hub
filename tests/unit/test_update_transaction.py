from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_spec = importlib.util.spec_from_file_location(
    "update_transaction_under_test", Path(__file__).resolve().parents[2] / "tools" / "update_transaction.py"
)
if _spec is None or _spec.loader is None:
    raise ImportError("could not load update_transaction.py")
update_transaction = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(update_transaction)


class UpdateTransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.install = self.root / "install"
        self.config = self.root / "input-config.toml"
        self.config.write_text("new config\n", encoding="utf-8")
        for name in ("src", "skills", "tools"):
            directory = self.source / name
            directory.mkdir(parents=True)
            (directory / "payload.txt").write_text(f"new {name}\n", encoding="utf-8")
            old = self.install / name
            old.mkdir(parents=True)
            (old / "payload.txt").write_text(f"old {name}\n", encoding="utf-8")
        self.install.mkdir(exist_ok=True)
        (self.install / "config.toml").write_text("old config\n", encoding="utf-8")
        (self.install / ".local-ai-hub-skill-ownership.json").write_text("manifest\n", encoding="utf-8")
        (self.install / "state").mkdir()
        (self.install / "state" / "state.db").write_text("state\n", encoding="utf-8")
        (self.install / "models").mkdir()
        (self.install / "models" / "user.gguf").write_text("model\n", encoding="utf-8")
        (self.install / ".venv").mkdir()
        (self.install / ".venv" / "marker").write_text("runtime\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_stop_failure_and_unknown_result_fail_closed(self) -> None:
        python = self.install / ".venv" / "python.exe"
        service = self.install / "tools" / "service.py"
        python.write_text("fake python", encoding="utf-8")
        service.write_text("fake service", encoding="utf-8")
        called = []

        failed, detail = update_transaction.stop_existing_runtime(
            self.install, python, service,
            lambda *args, **kwargs: (called.append(args), SimpleNamespace(returncode=2))[1],
        )
        unknown, unknown_detail = update_transaction.stop_existing_runtime(
            self.install, python, service, lambda *args, **kwargs: None,
        )

        self.assertFalse(failed)
        self.assertIn("exit=2", detail)
        self.assertFalse(unknown)
        self.assertIn("not confirmed", unknown_detail)
        self.assertEqual(len(called), 1)

    def test_stop_uses_installed_config_and_preserves_other_environment(self) -> None:
        python = self.install / ".venv" / "python.exe"
        service = self.install / "tools" / "service.py"
        python.write_text("fake python", encoding="utf-8")
        service.write_text("fake service", encoding="utf-8")
        captured: dict[str, object] = {}

        def runner(*args: object, **kwargs: object) -> SimpleNamespace:
            captured.update(kwargs)
            return SimpleNamespace(returncode=0)

        with patch.dict("os.environ", {"LOCAL_AI_CONFIG": "foreign-config", "F31_KEEP": "keep-me"}):
            stopped, detail = update_transaction.stop_existing_runtime(self.install, python, service, runner)

        self.assertTrue(stopped, detail)
        self.assertEqual(captured["env"]["LOCAL_AI_CONFIG"], str(self.install / "config.toml"))
        self.assertEqual(captured["env"]["F31_KEEP"], "keep-me")

    def test_stop_requires_regular_installed_config(self) -> None:
        python = self.install / ".venv" / "python.exe"
        service = self.install / "tools" / "service.py"
        python.write_text("fake python", encoding="utf-8")
        service.write_text("fake service", encoding="utf-8")
        (self.install / "config.toml").unlink()
        called = False

        def runner(*args: object, **kwargs: object) -> SimpleNamespace:
            nonlocal called
            called = True
            return SimpleNamespace(returncode=0)

        stopped, detail = update_transaction.stop_existing_runtime(self.install, python, service, runner)

        self.assertFalse(stopped)
        self.assertIn("no regular installed config.toml", detail)
        self.assertFalse(called)

    def test_staging_copy_failure_leaves_existing_payload_untouched(self) -> None:
        original_copytree = update_transaction.shutil.copytree
        stop_called = False

        def fail_on_skills(source: str | Path, destination: str | Path, **kwargs: object) -> Path:
            if Path(source).name == "skills":
                raise OSError("simulated staging copy failure")
            return original_copytree(source, destination, **kwargs)

        def stop_runtime() -> tuple[bool, str]:
            nonlocal stop_called
            stop_called = True
            return True, "stopped"

        with patch.object(update_transaction.shutil, "copytree", side_effect=fail_on_skills):
            success, detail = update_transaction.replace_install_payload(
                self.source, self.install, self.config, ("requirements.txt",), before_commit=stop_runtime,
            )

        self.assertFalse(success)
        self.assertIn("rollback completed", detail)
        self.assertFalse(stop_called)
        for name in ("src", "skills", "tools"):
            self.assertEqual((self.install / name / "payload.txt").read_text(encoding="utf-8"), f"old {name}\n")

    def test_swap_failure_rolls_back_prior_targets_and_preserves_user_state(self) -> None:
        real_replace = update_transaction.os.replace

        def fail_skills_swap(source: str | Path, destination: str | Path) -> None:
            if Path(source).parent.name == "payload" and Path(source).name == "skills":
                raise OSError("simulated payload swap failure")
            real_replace(source, destination)

        with patch.object(update_transaction.os, "replace", side_effect=fail_skills_swap):
            success, detail = update_transaction.replace_install_payload(
                self.source, self.install, self.config, ("requirements.txt",)
            )

        self.assertFalse(success)
        self.assertIn("rollback completed", detail)
        for name in ("src", "skills", "tools"):
            self.assertEqual((self.install / name / "payload.txt").read_text(encoding="utf-8"), f"old {name}\n")
        self.assertEqual((self.install / "config.toml").read_text(encoding="utf-8"), "old config\n")
        self.assertEqual((self.install / ".local-ai-hub-skill-ownership.json").read_text(encoding="utf-8"), "manifest\n")
        self.assertEqual((self.install / "state" / "state.db").read_text(encoding="utf-8"), "state\n")
        self.assertEqual((self.install / "models" / "user.gguf").read_text(encoding="utf-8"), "model\n")
        self.assertEqual((self.install / ".venv" / "marker").read_text(encoding="utf-8"), "runtime\n")

    def test_swap_rollback_reports_runtime_stays_stopped(self) -> None:
        real_replace = update_transaction.os.replace

        def fail_skills_swap(source: str | Path, destination: str | Path) -> None:
            if Path(source).parent.name == "payload" and Path(source).name == "skills":
                raise OSError("simulated payload swap failure")
            real_replace(source, destination)

        with patch.object(update_transaction.os, "replace", side_effect=fail_skills_swap):
            success, detail = update_transaction.replace_install_payload(
                self.source, self.install, self.config, ("requirements.txt",),
                before_commit=lambda: (True, "stop confirmed"),
            )

        self.assertFalse(success)
        self.assertIn("runtime remains stopped after rollback", detail)
        self.assertIn("service restart skipped", detail)

    def test_rejects_linked_install_and_source_ancestors(self) -> None:
        install_alias = self.root / "install-alias"
        source_alias = self.root / "source-alias"
        try:
            install_alias.symlink_to(self.install, target_is_directory=True)
            source_alias.symlink_to(self.source, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"directory symlinks unavailable: {exc}")

        unsafe_install, install_detail = update_transaction.replace_install_payload(
            self.source, install_alias, self.config, ("requirements.txt",),
        )
        unsafe_source, source_detail = update_transaction.replace_install_payload(
            source_alias, self.install, self.config, ("requirements.txt",),
        )

        self.assertFalse(unsafe_install)
        self.assertIn("link or junction", install_detail)
        self.assertFalse(unsafe_source)
        self.assertIn("link or junction", source_detail)

    def test_stop_failure_blocks_live_swap_and_keeps_old_payload(self) -> None:
        success, detail = update_transaction.replace_install_payload(
            self.source,
            self.install,
            self.config,
            ("requirements.txt",),
            before_commit=lambda: (False, "stop outcome unknown"),
        )

        self.assertFalse(success)
        self.assertIn("before live install swap or service start", detail)
        self.assertIn("stop outcome unknown", detail)
        for name in ("src", "skills", "tools"):
            self.assertEqual((self.install / name / "payload.txt").read_text(encoding="utf-8"), f"old {name}\n")

    def test_successful_swap_preserves_user_runtime_data(self) -> None:
        success, detail = update_transaction.replace_install_payload(
            self.source, self.install, self.config, ("requirements.txt",),
        )

        self.assertTrue(success)
        self.assertIn("staged verification passed", detail)
        self.assertEqual((self.install / "src" / "payload.txt").read_text(encoding="utf-8"), "new src\n")
        self.assertEqual((self.install / "config.toml").read_text(encoding="utf-8"), "new config\n")
        self.assertEqual((self.install / ".local-ai-hub-skill-ownership.json").read_text(encoding="utf-8"), "manifest\n")
        self.assertEqual((self.install / "state" / "state.db").read_text(encoding="utf-8"), "state\n")
        self.assertEqual((self.install / "models" / "user.gguf").read_text(encoding="utf-8"), "model\n")
        self.assertEqual((self.install / ".venv" / "marker").read_text(encoding="utf-8"), "runtime\n")


if __name__ == "__main__":
    unittest.main()
