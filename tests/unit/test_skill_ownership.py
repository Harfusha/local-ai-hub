from __future__ import annotations

import importlib.util
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "skill_ownership_under_test", Path(__file__).resolve().parents[2] / "tools" / "skill_ownership.py"
)
if _spec is None or _spec.loader is None:
    raise ImportError("could not load skill_ownership.py")
skill_ownership = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(skill_ownership)
install_skill = skill_ownership.install_skill
remove_skill = skill_ownership.remove_skill


class SkillOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.install = self.root / "install"
        self.source_root = self.install / "skills"
        self.tools = self.install / "tools"
        self.skills_root = self.root / "fake-home" / ".agents" / "skills"
        self.manifest = self.install / ".local-ai-hub-skill-ownership.json"
        self.source = self.source_root / "example-skill"
        self.target = self.skills_root / "example-skill"
        self.source.mkdir(parents=True)
        self.tools.mkdir(parents=True)
        (self.source / "SKILL.md").write_text("Hub version\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_removes_only_unchanged_hub_owned_tree(self) -> None:
        result = install_skill(self.source, self.target, self.skills_root, self.manifest, "example-skill")
        self.assertIn("installed Hub-owned", result)
        self.assertTrue(self.target.exists())

        result = remove_skill(self.target, self.skills_root, self.manifest, "example-skill")

        self.assertIn("removed Hub-owned", result)
        self.assertFalse(self.target.exists())

    def test_preserves_unmanaged_existing_tree(self) -> None:
        self.target.mkdir(parents=True)
        marker = self.target / "user.txt"
        marker.write_text("keep", encoding="utf-8")

        result = install_skill(self.source, self.target, self.skills_root, self.manifest, "example-skill")

        self.assertIn("preserved unmanaged", result)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
        self.assertFalse(self.manifest.exists())

    def test_preserves_modified_owned_tree_during_install_and_uninstall(self) -> None:
        install_skill(self.source, self.target, self.skills_root, self.manifest, "example-skill")
        (self.target / "user.txt").write_text("keep", encoding="utf-8")

        install_result = install_skill(self.source, self.target, self.skills_root, self.manifest, "example-skill")
        remove_result = remove_skill(self.target, self.skills_root, self.manifest, "example-skill")

        self.assertIn("preserved unmanaged or modified", install_result)
        self.assertIn("preserved modified Hub-owned", remove_result)
        self.assertTrue((self.target / "user.txt").exists())

    def test_rejects_target_outside_skills_root(self) -> None:
        outside = self.root / "outside" / "example-skill"

        with self.assertRaises(ValueError):
            remove_skill(outside, self.skills_root, self.manifest, "example-skill")

    def test_rejects_symlink_inside_skill_tree(self) -> None:
        install_skill(self.source, self.target, self.skills_root, self.manifest, "example-skill")
        external = self.root / "outside.txt"
        external.write_text("keep", encoding="utf-8")
        try:
            (self.target / "linked.txt").symlink_to(external)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable in this environment")

        result = remove_skill(self.target, self.skills_root, self.manifest, "example-skill")

        self.assertIn("preserved conflicting", result)
        self.assertTrue(external.exists())

    def test_replacement_failure_restores_previous_owned_tree(self) -> None:
        install_skill(self.source, self.target, self.skills_root, self.manifest, "example-skill")
        original = (self.target / "SKILL.md").read_text(encoding="utf-8")
        (self.source / "SKILL.md").write_text("Updated Hub version\n", encoding="utf-8")
        real_replace = skill_ownership.os.replace

        def fail_staged_swap(source: str | Path, destination: str | Path) -> None:
            if Path(source).name == "replacement":
                raise OSError("simulated staged replacement failure")
            real_replace(source, destination)

        with patch.object(skill_ownership.os, "replace", side_effect=fail_staged_swap):
            result = install_skill(self.source, self.target, self.skills_root, self.manifest, "example-skill")

        self.assertIn("replacement failed", result)
        self.assertEqual((self.target / "SKILL.md").read_text(encoding="utf-8"), original)


    def test_concurrent_installs_preserve_all_manifest_entries(self) -> None:
        skills = []
        for name in ("concurrent-a", "concurrent-b"):
            source = self.source_root / name
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text(f"{name}\\n", encoding="utf-8")
            target = self.skills_root / name
            skills.append((source, target, name))

        first_write_entered = threading.Event()
        second_lock_attempted = threading.Event()
        release_first_write = threading.Event()
        original_write = skill_ownership._manifest_write
        original_lock = skill_ownership._ownership_lock

        def observe_lock(manifest: Path):
            if threading.current_thread().name.endswith("_1"):
                second_lock_attempted.set()
            return original_lock(manifest)

        def pause_first_write(manifest: Path, entries: dict[str, dict[str, str]]) -> None:
            if threading.current_thread().name.endswith("_0"):
                first_write_entered.set()
                if not release_first_write.wait(timeout=5):
                    raise TimeoutError("test did not release the first manifest writer")
            original_write(manifest, entries)

        with patch.object(skill_ownership, "_ownership_lock", side_effect=observe_lock), patch.object(
            skill_ownership, "_manifest_write", side_effect=pause_first_write
        ):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(
                    install_skill, skills[0][0], skills[0][1], self.skills_root, self.manifest, skills[0][2]
                )
                self.assertTrue(first_write_entered.wait(timeout=5))
                second = pool.submit(
                    install_skill, skills[1][0], skills[1][1], self.skills_root, self.manifest, skills[1][2]
                )
                self.assertTrue(second_lock_attempted.wait(timeout=5))
                release_first_write.set()
                self.assertIn("installed Hub-owned skill", first.result(timeout=10))
                self.assertIn("installed Hub-owned skill", second.result(timeout=10))

        entries = json.loads(self.manifest.read_text(encoding="utf-8"))["skills"]
        self.assertEqual(set(entries), {skill_ownership._canonical(target) for _, target, _ in skills})


    def test_uninstall_revalidates_tree_after_atomic_quarantine(self) -> None:
        install_skill(self.source, self.target, self.skills_root, self.manifest, "example-skill")
        real_replace = skill_ownership.os.replace

        def modify_before_quarantine(source: str | Path, destination: str | Path) -> None:
            if Path(source) == self.target and ".removing-" in Path(destination).name:
                (self.target / "SKILL.md").write_text("operator change\\n", encoding="utf-8")
            real_replace(source, destination)

        with patch.object(skill_ownership.os, "replace", side_effect=modify_before_quarantine):
            result = remove_skill(self.target, self.skills_root, self.manifest, "example-skill")

        self.assertIn("preserved changed skill tree", result)
        self.assertEqual((self.target / "SKILL.md").read_text(encoding="utf-8"), "operator change\\n")
        self.assertTrue(self.manifest.exists())


if __name__ == "__main__":
    unittest.main()
