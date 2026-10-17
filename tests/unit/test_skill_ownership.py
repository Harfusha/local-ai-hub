from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
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

    def test_clean_uninstall_deactivates_skill_and_tracks_preserved_quarantine(self) -> None:
        result = install_skill(self.source, self.target, self.skills_root, self.manifest, "example-skill")
        self.assertIn("installed Hub-owned", result)
        self.assertTrue(self.target.exists())
        baseline = json.loads(self.manifest.read_text(encoding="utf-8"))["skills"][
            skill_ownership._canonical(self.target)
        ]["sha256"]

        with patch.object(skill_ownership.shutil, "rmtree", side_effect=AssertionError("must not delete")) as delete:
            result = remove_skill(self.target, self.skills_root, self.manifest, "example-skill")

        delete.assert_not_called()
        self.assertIn("uninstalled Hub-owned skill", result)
        self.assertFalse(self.target.exists())
        entries = json.loads(self.manifest.read_text(encoding="utf-8"))["skills"]
        self.assertNotIn(skill_ownership._canonical(self.target), entries)
        quarantine_key, record = next(iter(entries.items()))
        quarantine = Path(record["quarantine_path"])
        self.assertEqual(quarantine_key, skill_ownership._canonical(quarantine))
        self.assertEqual(quarantine.parent, self.skills_root.parent / ".local-ai-hub-skill-quarantine")
        self.assertTrue(quarantine.name.startswith("example-skill-"))
        self.assertFalse(quarantine.is_relative_to(self.skills_root))
        self.assertEqual(record["status"], "unverified")
        self.assertEqual(record["hash_state"], "unverified")
        self.assertEqual(record["original_target"], skill_ownership._canonical(self.target))
        self.assertEqual(record["recorded_sha256"], baseline)
        self.assertEqual((quarantine / "SKILL.md").read_text(encoding="utf-8"), "Hub version\n")

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


    def test_replaced_owned_tree_is_retained_in_tracked_quarantine(self) -> None:
        install_skill(self.source, self.target, self.skills_root, self.manifest, "example-skill")
        (self.source / "SKILL.md").write_text("Updated Hub version\n", encoding="utf-8")
        real_rmtree = skill_ownership.shutil.rmtree

        def reject_backup_delete(path, *args, **kwargs):
            if Path(path).name == "previous":
                raise AssertionError("verified backup must be retained by identity")
            return real_rmtree(path, *args, **kwargs)

        with patch.object(skill_ownership.shutil, "rmtree", side_effect=reject_backup_delete):
            result = install_skill(self.source, self.target, self.skills_root, self.manifest, "example-skill")

        self.assertIn("previous version retained", result)
        entries = json.loads(self.manifest.read_text(encoding="utf-8"))["skills"]
        quarantine_records = [record for record in entries.values() if "quarantine_path" in record]
        self.assertEqual(len(quarantine_records), 1)
        quarantine = Path(quarantine_records[0]["quarantine_path"])
        self.assertEqual(quarantine.parent, self.skills_root.parent / ".local-ai-hub-skill-quarantine")
        self.assertEqual((quarantine / "SKILL.md").read_text(encoding="utf-8"), "Hub version\n")
        self.assertEqual(quarantine_records[0]["status"], "unverified")


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

        def pause_first_write(manifest: Path, entries: dict[str, dict[str, object]]) -> None:
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
        real_move = skill_ownership._rename_noreplace

        def modify_before_quarantine(source: Path, destination: Path, **kwargs: object) -> None:
            if source == self.target:
                (self.target / "SKILL.md").write_text("operator change\\n", encoding="utf-8")
            real_move(source, destination, **kwargs)

        with patch.object(skill_ownership, "_rename_noreplace", side_effect=modify_before_quarantine):
            result = remove_skill(self.target, self.skills_root, self.manifest, "example-skill")

        self.assertIn("hash_state=unverified", result)
        self.assertFalse(self.target.exists())
        entries = json.loads(self.manifest.read_text(encoding="utf-8"))["skills"]
        record = next(iter(entries.values()))
        recovery = Path(record["quarantine_path"])
        self.assertEqual((recovery / "SKILL.md").read_text(encoding="utf-8"), "operator change\\n")
        self.assertEqual(record["status"], "unverified")
        self.assertEqual(record["hash_state"], "unverified")

    def test_rejects_symlinked_lock_file_without_touching_external_file(self) -> None:
        lock_path = self.manifest.with_name(self.manifest.name + ".lock")
        external = self.root / "external-lock-target"
        external.write_bytes(b"operator data")
        try:
            lock_path.symlink_to(external)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable in this environment")

        with self.assertRaises(OSError):
            install_skill(self.source, self.target, self.skills_root, self.manifest, "example-skill")

        self.assertEqual(external.read_bytes(), b"operator data")
        self.assertFalse(self.target.exists())

    def test_rejects_hardlinked_lock_file_without_touching_external_file(self) -> None:
        lock_path = self.manifest.with_name(self.manifest.name + ".lock")
        external = self.root / "external-lock-target"
        external.write_bytes(b"")
        try:
            os.link(external, lock_path)
        except (OSError, NotImplementedError):
            self.skipTest("hard links unavailable in this environment")

        with self.assertRaises(OSError):
            install_skill(self.source, self.target, self.skills_root, self.manifest, "example-skill")

        self.assertEqual(external.read_bytes(), b"")
        self.assertFalse(self.target.exists())

    @unittest.skipIf(os.name == "nt", "POSIX lock open flags are not used on Windows")
    def test_lock_fails_closed_when_posix_nofollow_is_unavailable(self) -> None:
        lock_path = self.manifest.with_name(self.manifest.name + ".lock")
        with patch.object(skill_ownership.os, "O_NOFOLLOW", 0, create=True), patch.object(
            skill_ownership.os, "open"
        ) as open_file:
            with self.assertRaisesRegex(OSError, "O_NOFOLLOW"):
                install_skill(self.source, self.target, self.skills_root, self.manifest, "example-skill")

        open_file.assert_not_called()
        self.assertFalse(lock_path.exists())

    def test_cross_process_installs_preserve_all_manifest_entries(self) -> None:
        skills = []
        for name in ("process-a", "process-b"):
            source = self.source_root / name
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text(f"{name}\\n", encoding="utf-8")
            skills.append((source, self.skills_root / name, name))

        first_waiting = self.root / "first-writer-entered"
        second_attempt = self.root / "second-lock-attempt"
        release_first = self.root / "release-first-writer"
        module_dir = Path(skill_ownership.__file__).resolve().parent
        child = """
import pathlib
import sys
import time
import os

sys.path.insert(0, sys.argv[1])
import skill_ownership as so

source = pathlib.Path(sys.argv[2])
target = pathlib.Path(sys.argv[3])
root = pathlib.Path(sys.argv[4])
manifest = pathlib.Path(sys.argv[5])
name = sys.argv[6]
first_waiting = pathlib.Path(sys.argv[7])
second_attempt = pathlib.Path(sys.argv[8])
release_first = pathlib.Path(sys.argv[9])
write = so._manifest_write

def delayed(path, entries):
    if name == "process-a" and not first_waiting.exists():
        first_waiting.write_text("ready", encoding="utf-8")
        deadline = time.monotonic() + 10
        while not release_first.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not release_first.exists():
            raise TimeoutError("test did not release first manifest writer")
    write(path, entries)

if name == "process-b":
    if os.name == "nt":
        import msvcrt
        original_lock = msvcrt.locking
        def observed_lock(fd, mode, count):
            try:
                result = original_lock(fd, mode, count)
            except OSError:
                if mode == msvcrt.LK_NBLCK and not second_attempt.exists():
                    second_attempt.write_text("blocked", encoding="utf-8")
                    while not release_first.exists():
                        time.sleep(0.01)
                raise
            if mode == msvcrt.LK_NBLCK and not second_attempt.exists():
                second_attempt.write_text("acquired", encoding="utf-8")
            return result
        msvcrt.locking = observed_lock
    else:
        import fcntl
        original_flock = fcntl.flock
        def observed_flock(fd, operation):
            try:
                result = original_flock(fd, operation)
            except BlockingIOError:
                if operation == fcntl.LOCK_EX | fcntl.LOCK_NB and not second_attempt.exists():
                    second_attempt.write_text("blocked", encoding="utf-8")
                    while not release_first.exists():
                        time.sleep(0.01)
                raise
            if operation == fcntl.LOCK_EX | fcntl.LOCK_NB and not second_attempt.exists():
                second_attempt.write_text("acquired", encoding="utf-8")
            return result
        fcntl.flock = observed_flock

so._manifest_write = delayed
so.install_skill(source, target, root, manifest, name)
"""

        first = subprocess.Popen(
            [sys.executable, "-c", child, str(module_dir), str(skills[0][0]), str(skills[0][1]),
             str(self.skills_root), str(self.manifest), skills[0][2], str(first_waiting), str(second_attempt),
             str(release_first)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        second = None
        first_output = ("", "")
        second_output = ("", "")
        try:
            deadline = time.monotonic() + 5
            while not first_waiting.exists() and first.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(first_waiting.exists(), "first process did not enter manifest write")
            second = subprocess.Popen(
                [sys.executable, "-c", child, str(module_dir), str(skills[1][0]), str(skills[1][1]),
                 str(self.skills_root), str(self.manifest), skills[1][2], str(first_waiting), str(second_attempt),
                 str(release_first)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            deadline = time.monotonic() + 10
            while not second_attempt.exists() and second.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(second_attempt.exists(), "second process did not attempt the OS lock")
            self.assertEqual(second_attempt.read_text(encoding="utf-8"), "blocked", "second process acquired lock early")
            release_first.write_text("release", encoding="utf-8")
            first_output = first.communicate(timeout=15)
            second_output = second.communicate(timeout=15)
        finally:
            release_first.touch(exist_ok=True)
            if first.poll() is None:
                first.kill()
                first.communicate()
            if second is not None and second.poll() is None:
                second.kill()
                second.communicate()

        self.assertEqual(first.returncode, 0, first_output[1])
        self.assertEqual(second.returncode, 0, second_output[1])
        entries = json.loads(self.manifest.read_text(encoding="utf-8"))["skills"]
        self.assertEqual(set(entries), {skill_ownership._canonical(target) for _, target, _ in skills})

    def test_quarantine_collision_retry_preserves_and_reports_all_recovery_paths(self) -> None:
        install_skill(self.source, self.target, self.skills_root, self.manifest, "example-skill")
        original_move = skill_ownership._rename_noreplace
        competing_paths: list[Path] = []

        def occupy_quarantine(source: Path, destination: Path, **kwargs: object) -> None:
            if source == self.target:
                destination.mkdir()
                (destination / "competitor.txt").write_text("do not overwrite", encoding="utf-8")
                competing_paths.append(destination)
            original_move(source, destination, **kwargs)

        with patch.object(skill_ownership, "_rename_noreplace", side_effect=occupy_quarantine):
            result = remove_skill(self.target, self.skills_root, self.manifest, "example-skill")

        self.assertIn("move outcome uncertain", result)
        self.assertIn(str(competing_paths[0]), result)
        self.assertTrue(self.target.is_dir())
        self.assertEqual((self.target / "SKILL.md").read_text(encoding="utf-8"), "Hub version\n")
        self.assertEqual((competing_paths[0] / "competitor.txt").read_text(encoding="utf-8"), "do not overwrite")
        entries = json.loads(self.manifest.read_text(encoding="utf-8"))["skills"]
        self.assertIn(skill_ownership._canonical(self.target), entries)
        self.assertEqual(len(entries), 2)
        quarantine_key = skill_ownership._canonical(competing_paths[0])
        self.assertEqual(entries[quarantine_key]["status"], "conflict")
        self.assertEqual(entries[quarantine_key]["quarantine_path"], str(competing_paths[0]))
        self.assertEqual(
            entries[quarantine_key]["recorded_sha256"],
            entries[skill_ownership._canonical(self.target)]["sha256"],
        )
        self.assertNotEqual(
            entries[quarantine_key]["observed_sha256"], entries[quarantine_key]["recorded_sha256"]
        )

        retry_result = remove_skill(self.target, self.skills_root, self.manifest, "example-skill")
        self.assertIn("uninstalled Hub-owned skill", retry_result)
        self.assertFalse(self.target.exists())
        retry_entries = json.loads(self.manifest.read_text(encoding="utf-8"))["skills"]
        actual_skill_path = next(
            Path(record["quarantine_path"])
            for record in retry_entries.values()
            if record["status"] == "unverified"
        )
        self.assertTrue((actual_skill_path / "SKILL.md").is_file())
        self.assertTrue((competing_paths[0] / "competitor.txt").is_file())
        self.assertEqual(retry_entries[quarantine_key]["status"], "conflict")
        self.assertEqual(retry_entries[skill_ownership._canonical(actual_skill_path)]["status"], "unverified")

        missing_result = remove_skill(self.target, self.skills_root, self.manifest, "example-skill")
        self.assertIn(str(actual_skill_path), missing_result)
        self.assertIn(str(competing_paths[0]), missing_result)
        self.assertIn("status=conflict", missing_result)
        self.assertIn("recorded_sha256=", missing_result)
        self.assertIn("hash_state=unverified", missing_result)
        self.assertIn("presence=present", missing_result)

    def test_malformed_quarantine_record_is_reported_without_path_or_set_errors(self) -> None:
        install_skill(self.source, self.target, self.skills_root, self.manifest, "example-skill")
        remove_skill(self.target, self.skills_root, self.manifest, "example-skill")
        payload = json.loads(self.manifest.read_text(encoding="utf-8"))
        record = next(iter(payload["skills"].values()))
        record["quarantine_path"] = ""
        record["status"] = []
        record["recorded_sha256"] = {"invalid": "shape"}
        self.manifest.write_text(json.dumps(payload), encoding="utf-8")

        result = remove_skill(self.target, self.skills_root, self.manifest, "example-skill")

        self.assertIn("presence=unknown", result)
        self.assertIn("status=[]", result)
        self.assertIn("sha256={'invalid': 'shape'}", result)

    def test_quarantine_path_outside_expected_root_is_not_inspected(self) -> None:
        install_skill(self.source, self.target, self.skills_root, self.manifest, "example-skill")
        remove_skill(self.target, self.skills_root, self.manifest, "example-skill")
        outside = self.root / "unrelated-user-data"
        outside.mkdir()
        (outside / "marker.txt").write_text("preserve", encoding="utf-8")
        payload = json.loads(self.manifest.read_text(encoding="utf-8"))
        record = next(iter(payload["skills"].values()))
        record["quarantine_path"] = str(outside)
        self.manifest.write_text(json.dumps(payload), encoding="utf-8")

        with patch.object(skill_ownership, "_safe_tree_hash", side_effect=AssertionError("untrusted path read")):
            result = remove_skill(self.target, self.skills_root, self.manifest, "example-skill")

        self.assertIn("presence=unknown", result)
        self.assertEqual((outside / "marker.txt").read_text(encoding="utf-8"), "preserve")

    def test_reparse_quarantine_root_is_rejected_before_path_inspection(self) -> None:
        expected_root = self.skills_root.parent / ".local-ai-hub-skill-quarantine"
        expected_root.mkdir(parents=True)
        quarantine = expected_root / "example-skill-test"
        quarantine.mkdir()
        record = {
            "name": "example-skill",
            "original_target": str(self.target),
            "quarantine_path": str(quarantine),
            "sha256": "a" * 64,
            "status": "unverified",
        }

        with patch.object(skill_ownership, "_is_link", return_value=True), patch.object(
            skill_ownership, "_safe_tree_hash", side_effect=AssertionError("reparse root must not be read")
        ):
            classified, presence = skill_ownership._inspect_quarantine_record(record, expected_root)

        self.assertEqual(presence, "unknown")
        self.assertEqual(classified["quarantine_path"], str(quarantine))

    @unittest.skipUnless(os.name == "nt", "Windows quarantine-root handle pin check")
    def test_windows_pinned_quarantine_root_rejects_replacement_during_move(self) -> None:
        install_skill(self.source, self.target, self.skills_root, self.manifest, "example-skill")
        quarantine_root = self.skills_root.parent / ".local-ai-hub-skill-quarantine"
        replacement_root = quarantine_root.with_name(quarantine_root.name + "-replacement")
        original_move = skill_ownership._rename_noreplace

        def attempt_root_replacement(source: Path, destination: Path, **kwargs: object) -> None:
            with self.assertRaises(OSError):
                os.replace(quarantine_root, replacement_root)
            self.assertFalse(replacement_root.exists())
            self.assertTrue(quarantine_root.is_dir())
            self.assertFalse(quarantine_root.is_symlink())
            original_move(source, destination, **kwargs)

        with patch.object(skill_ownership, "_rename_noreplace", side_effect=attempt_root_replacement):
            result = remove_skill(self.target, self.skills_root, self.manifest, "example-skill")

        self.assertIn("uninstalled Hub-owned skill", result)
        self.assertFalse(self.target.exists())
        self.assertTrue(quarantine_root.is_dir())
        self.assertFalse(replacement_root.exists())
        entries = json.loads(self.manifest.read_text(encoding="utf-8"))["skills"]
        quarantine_path = Path(
            next(record["quarantine_path"] for record in entries.values() if record["status"] == "unverified")
        )
        self.assertTrue(quarantine_path.is_relative_to(quarantine_root))
        self.assertTrue((quarantine_path / "SKILL.md").is_file())

    @unittest.skipIf(os.name == "nt", "POSIX quarantine-root replacement check")
    def test_quarantine_root_swap_cannot_redirect_noreplace_move(self) -> None:
        install_skill(self.source, self.target, self.skills_root, self.manifest, "example-skill")
        quarantine_root = self.skills_root.parent / ".local-ai-hub-skill-quarantine"
        moved_root = quarantine_root.with_name(quarantine_root.name + "-pinned")
        external = self.root / "external-quarantine"
        external.mkdir()
        original_move = skill_ownership._rename_noreplace

        def swap_root_then_move(source: Path, destination: Path, **kwargs: object) -> None:
            os.replace(quarantine_root, moved_root)
            os.symlink(external, quarantine_root, target_is_directory=True)
            original_move(source, destination, **kwargs)

        with patch.object(skill_ownership, "_rename_noreplace", side_effect=swap_root_then_move):
            result = remove_skill(self.target, self.skills_root, self.manifest, "example-skill")

        self.assertIn("quarantine root changed during uninstall", result)
        self.assertIn("recovery location is unknown", result)
        self.assertFalse(self.target.exists())
        self.assertEqual(list(external.iterdir()), [])
        self.assertEqual(len(list(moved_root.iterdir())), 1)
        entries = json.loads(self.manifest.read_text(encoding="utf-8"))["skills"]
        self.assertNotIn(skill_ownership._canonical(self.target), entries)
        recovery_key, recovery = next(
            (entry_key, record)
            for entry_key, record in entries.items()
            if record.get("original_target") == skill_ownership._canonical(self.target)
        )
        self.assertTrue(recovery_key.startswith("ambiguous:"))
        self.assertEqual(recovery["quarantine_path"], "unknown")
        self.assertEqual(recovery["status"], "ambiguous")
        self.assertEqual(recovery["location_state"], "unknown")
        pinned_quarantine = moved_root / next(iter(moved_root.iterdir())).name
        self.assertTrue((pinned_quarantine / "SKILL.md").is_file())
        self.assertNotIn(skill_ownership._canonical(external), entries)

    @unittest.skipIf(os.name == "nt", "POSIX source-leaf identity race check")
    def test_source_leaf_swap_is_restored_without_overwrite_and_marked_ambiguous(self) -> None:
        install_skill(self.source, self.target, self.skills_root, self.manifest, "example-skill")
        moved_original = self.root / "original-skill-moved-by-racer"
        real_is_current = skill_ownership._source_is_current
        calls = 0

        def swap_leaf_after_validation(source_pin) -> bool:
            nonlocal calls
            current = real_is_current(source_pin)
            calls += 1
            if calls == 2:
                os.replace(self.target, moved_original)
                self.target.mkdir()
                (self.target / "operator.txt").write_text("preserve these bytes", encoding="utf-8")
            return current

        with patch.object(skill_ownership, "_source_is_current", side_effect=swap_leaf_after_validation):
            result = remove_skill(self.target, self.skills_root, self.manifest, "example-skill")

        self.assertIn("move outcome ambiguous", result)
        self.assertIn("recovery location is unknown", result)
        self.assertEqual((self.target / "operator.txt").read_text(encoding="utf-8"), "preserve these bytes")
        self.assertEqual((moved_original / "SKILL.md").read_text(encoding="utf-8"), "Hub version\n")
        entries = json.loads(self.manifest.read_text(encoding="utf-8"))["skills"]
        self.assertNotIn(skill_ownership._canonical(self.target), entries)
        ambiguous = [record for record in entries.values() if record.get("status") == "ambiguous"]
        self.assertEqual(len(ambiguous), 1)
        self.assertEqual(ambiguous[0]["quarantine_path"], "unknown")
        self.assertEqual(ambiguous[0]["location_state"], "unknown")

    @unittest.skipUnless(os.name == "nt", "Windows quarantine path identity check")
    def test_windows_error_reconciliation_skips_presence_when_quarantine_root_changed(self) -> None:
        install_skill(self.source, self.target, self.skills_root, self.manifest, "example-skill")
        with (
            patch.object(skill_ownership, "_rename_noreplace", side_effect=OSError("move failed")),
            patch.object(skill_ownership._PinnedQuarantine, "is_current", return_value=False) as is_current,
            patch.object(
                skill_ownership._PinnedQuarantine,
                "entry_presence",
                side_effect=AssertionError("must not inspect a substituted quarantine path"),
            ) as entry_presence,
        ):
            result = remove_skill(self.target, self.skills_root, self.manifest, "example-skill")

        self.assertIn("recovery location is unknown", result)
        is_current.assert_called_once_with()
        entry_presence.assert_not_called()
        entries = json.loads(self.manifest.read_text(encoding="utf-8"))["skills"]
        ambiguous = [record for record in entries.values() if record.get("status") == "ambiguous"]
        self.assertEqual(len(ambiguous), 1)
        self.assertEqual(ambiguous[0]["quarantine_path"], "unknown")

    @unittest.skipUnless(os.name == "nt", "Windows path-based quarantine presence is unsupported")
    def test_windows_unknown_quarantine_presence_propagates_without_path_lookup(self) -> None:
        install_skill(self.source, self.target, self.skills_root, self.manifest, "example-skill")
        real_lstat = Path.lstat
        quarantine_name = ".local-ai-hub-skill-quarantine"

        def reject_quarantine_lookup(path: Path):
            if path.name == quarantine_name or path.parent.name == quarantine_name:
                raise AssertionError("must not perform path-based quarantine lookup")
            return real_lstat(path)

        with (
            patch.object(skill_ownership, "_rename_noreplace", side_effect=OSError("move failed")),
            patch.object(skill_ownership._PinnedQuarantine, "is_current", return_value=True),
            patch.object(Path, "lstat", autospec=True, side_effect=reject_quarantine_lookup),
        ):
            result = remove_skill(self.target, self.skills_root, self.manifest, "example-skill")

        self.assertIn("recovery location is unknown", result)
        entries = json.loads(self.manifest.read_text(encoding="utf-8"))["skills"]
        ambiguous = [record for record in entries.values() if record.get("status") == "ambiguous"]
        self.assertEqual(len(ambiguous), 1)
        self.assertEqual(ambiguous[0]["quarantine_path"], "unknown")
        self.assertEqual(ambiguous[0]["location_state"], "unknown")

    def test_nul_quarantine_path_and_lstat_value_error_are_unknown(self) -> None:
        expected_root = self.skills_root.parent / ".local-ai-hub-skill-quarantine"
        expected_root.mkdir(parents=True)
        record = {
            "name": "example-skill",
            "original_target": str(self.target),
            "quarantine_path": str(expected_root / "bad\x00path"),
            "sha256": "a" * 64,
            "status": "pending",
        }

        classified, presence = skill_ownership._inspect_quarantine_record(record, expected_root)
        self.assertEqual(presence, "unknown")

        with patch.object(skill_ownership, "_valid_quarantine_record", return_value=True):
            classified, forced_presence = skill_ownership._inspect_quarantine_record(record, expected_root)

        self.assertEqual(forced_presence, "unknown")
        self.assertEqual(classified["quarantine_path"], str(expected_root / "bad\x00path"))

    def test_unavailable_hash_sentinel_never_confirms_quarantine(self) -> None:
        expected_root = self.skills_root.parent / ".local-ai-hub-skill-quarantine"
        path = expected_root / "example-skill-test"
        path.mkdir(parents=True)
        base_record = {
            "name": "example-skill",
            "original_target": str(self.target),
            "quarantine_path": str(path),
            "recorded_sha256": "unavailable",
            "status": "pending",
        }

        with patch.object(skill_ownership, "_safe_tree_hash", return_value="unavailable"):
            pending, pending_presence = skill_ownership._inspect_quarantine_record(base_record, expected_root)
            quarantined, quarantined_presence = skill_ownership._inspect_quarantine_record(
                {**base_record, "status": "quarantined"}, expected_root
            )

        self.assertEqual(pending_presence, "present")
        self.assertEqual(pending["status"], "pending")
        self.assertEqual(pending["recorded_sha256"], "unavailable")
        self.assertEqual(pending["observed_sha256"], "unavailable")
        self.assertEqual(quarantined_presence, "present")
        self.assertEqual(quarantined["status"], "conflict")
        self.assertEqual(quarantined["recorded_sha256"], "unavailable")
        self.assertEqual(quarantined["observed_sha256"], "unavailable")

    def test_final_manifest_write_failure_keeps_quarantine_recoverable_and_tracked(self) -> None:
        install_skill(self.source, self.target, self.skills_root, self.manifest, "example-skill")
        baseline = json.loads(self.manifest.read_text(encoding="utf-8"))["skills"][
            skill_ownership._canonical(self.target)
        ]["sha256"]
        original_write = skill_ownership._manifest_write
        writes = 0

        def fail_final_once(manifest: Path, entries: dict[str, dict[str, object]]) -> None:
            nonlocal writes
            writes += 1
            if writes == 2:
                raise OSError("simulated final manifest failure")
            original_write(manifest, entries)

        with patch.object(skill_ownership, "_manifest_write", side_effect=fail_final_once):
            result = remove_skill(self.target, self.skills_root, self.manifest, "example-skill")

        self.assertIn("data recoverable at", result)
        self.assertFalse(self.target.exists())
        entries = json.loads(self.manifest.read_text(encoding="utf-8"))["skills"]
        quarantine_key, record = next(iter(entries.items()))
        quarantine = Path(record["quarantine_path"])
        self.assertEqual(quarantine_key, skill_ownership._canonical(quarantine))
        self.assertEqual(record["status"], "pending")
        self.assertEqual(record["recorded_sha256"], baseline)
        self.assertTrue((quarantine / "SKILL.md").is_file())
        retry_result = remove_skill(self.target, self.skills_root, self.manifest, "example-skill")
        self.assertIn(f"tracked recovery path: {quarantine}", retry_result)

    def test_post_move_quarantine_mutation_is_preserved_without_rehash(self) -> None:
        install_skill(self.source, self.target, self.skills_root, self.manifest, "example-skill")
        real_hash = skill_ownership._safe_tree_hash
        real_move = skill_ownership._rename_noreplace
        hashed_paths: list[Path] = []

        def hash_only_active_tree(path: Path) -> str:
            hashed_paths.append(path)
            self.assertEqual(path, self.target, "persisted quarantine must not be recursively hashed")
            return real_hash(path)

        def mutate_after_move(source: Path, destination: Path, **kwargs: object) -> None:
            real_move(source, destination, **kwargs)
            if source == self.target:
                (destination / "SKILL.md").write_text("changed after move\\n", encoding="utf-8")

        with patch.object(skill_ownership, "_safe_tree_hash", side_effect=hash_only_active_tree), patch.object(
            skill_ownership, "_rename_noreplace", side_effect=mutate_after_move
        ), patch.object(
            skill_ownership.shutil, "rmtree", side_effect=AssertionError("quarantine must never be deleted")
        ) as delete:
            result = remove_skill(self.target, self.skills_root, self.manifest, "example-skill")

        delete.assert_not_called()
        self.assertIn("hash_state=unverified", result)
        self.assertFalse(self.target.exists())
        entries = json.loads(self.manifest.read_text(encoding="utf-8"))["skills"]
        record = next(iter(entries.values()))
        quarantine = Path(record["quarantine_path"])
        self.assertEqual((quarantine / "SKILL.md").read_text(encoding="utf-8"), "changed after move\\n")
        self.assertEqual(hashed_paths, [self.target])
        self.assertEqual(record["hash_state"], "unverified")

    def test_recovery_move_never_overwrites_competing_active_target(self) -> None:
        install_skill(self.source, self.target, self.skills_root, self.manifest, "example-skill")
        remove_skill(self.target, self.skills_root, self.manifest, "example-skill")
        entries = json.loads(self.manifest.read_text(encoding="utf-8"))["skills"]
        record = next(iter(entries.values()))
        quarantine = Path(record["quarantine_path"])
        self.target.mkdir()
        (self.target / "operator.txt").write_text("keep", encoding="utf-8")

        with self.assertRaises(OSError):
            skill_ownership._rename_noreplace(quarantine, self.target)

        self.assertTrue((quarantine / "SKILL.md").is_file())
        self.assertEqual((self.target / "operator.txt").read_text(encoding="utf-8"), "keep")
        current = json.loads(self.manifest.read_text(encoding="utf-8"))["skills"]
        self.assertIn(skill_ownership._canonical(quarantine), current)

    def test_quarantined_tree_can_be_recovered_to_vacant_target(self) -> None:
        install_skill(self.source, self.target, self.skills_root, self.manifest, "example-skill")
        remove_skill(self.target, self.skills_root, self.manifest, "example-skill")
        entries = json.loads(self.manifest.read_text(encoding="utf-8"))["skills"]
        quarantine_key, record = next(iter(entries.items()))
        quarantine = Path(record["quarantine_path"])

        skill_ownership._rename_noreplace(quarantine, self.target)

        self.assertFalse(quarantine.exists())
        self.assertEqual((self.target / "SKILL.md").read_text(encoding="utf-8"), "Hub version\n")
        self.assertEqual(quarantine_key, skill_ownership._canonical(quarantine))
        self.assertEqual(record["recorded_sha256"], skill_ownership._safe_tree_hash(self.target))


if __name__ == "__main__":
    unittest.main()
