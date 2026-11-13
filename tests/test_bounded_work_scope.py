import threading

import pytest

from local_ai_hub.work_orchestrator import WorkOrchestrator, _bounded_work_scope, _WORK_CANCEL_EVENT


def test_scope_preserves_exact_files_and_commands(tmp_path):
    paths, commands = _bounded_work_scope(tmp_path, ["src/main.py", "tests/test_main.py"], ["python -m pytest -q"])
    assert paths == ["src/main.py", "tests/test_main.py"]
    assert commands == ["python -m pytest -q"]


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_git_patch_preserves_utf8_and_existing_line_endings(tmp_path, newline):
    from local_ai_hub.work_orchestrator import _run_git_patch

    target = tmp_path / "sample.txt"
    target.write_bytes(("řádek" + newline + "starý" + newline).encode("utf-8"))
    patch = "--- a/sample.txt\n+++ b/sample.txt\n@@ -1,2 +1,2 @@\n řádek\n-starý\n+nový\n"
    result = _run_git_patch(["git", "-C", str(tmp_path), "apply", "--whitespace=nowarn", "-"], patch)
    assert result.returncode == 0, result.stderr
    assert target.read_bytes() == ("řádek" + newline + "nový" + newline).encode("utf-8")


def test_git_patch_preserves_mixed_file_endings_despite_repo_attributes(tmp_path):
    import subprocess
    from local_ai_hub.work_orchestrator import _run_git_patch

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitattributes").write_text("* text eol=crlf\n", encoding="utf-8")
    (tmp_path / "[x] name.txt").write_bytes(b"a\nb\n")
    (tmp_path / "x name.txt").write_bytes(b"a\r\nb\r\n")
    patch = "".join(f"--- a/{name}\n+++ b/{name}\n@@ -1,2 +1,2 @@\n a\n-b\n+c\n"
                    for name in ("[x] name.txt", "x name.txt"))
    result = _run_git_patch(["git", "-C", str(tmp_path), "apply", "--whitespace=nowarn", "-"], patch)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "[x] name.txt").read_bytes() == b"a\nc\n"
    assert (tmp_path / "x name.txt").read_bytes() == b"a\r\nc\r\n"


def test_git_patch_refuses_mixed_line_endings_within_one_file(tmp_path):
    from local_ai_hub.work_orchestrator import _run_git_patch

    target = tmp_path / "mixed.txt"
    original = b"a\r\nb\n"
    target.write_bytes(original)
    patch = "--- a/mixed.txt\n+++ b/mixed.txt\n@@ -1,2 +1,2 @@\n a\n-b\n+c\n"
    with pytest.raises(ValueError, match="mixed line endings"):
        _run_git_patch(["git", "-C", str(tmp_path), "apply", "-"], patch)
    assert target.read_bytes() == original


def test_bounded_model_calls_receive_deadline_cancellation():
    from types import SimpleNamespace
    event = threading.Event()
    seen = []
    def call(args, *, cancel_event):
        seen.append(cancel_event)
        return {"success": True, "text": "result"}
    wo = object.__new__(WorkOrchestrator)
    wo.services = SimpleNamespace(delegate_repo=call, second_opinion=call)
    token = _WORK_CANCEL_EVENT.set(event)
    try:
        wo._ask("root", "task", "context")
        wo._ask("root", "task", "context", review=True)
    finally:
        _WORK_CANCEL_EVENT.reset(token)
    assert seen == [event, event]


def test_expired_deadline_is_visible_while_backend_is_still_running(tmp_path, monkeypatch):
    import time as real_time
    import local_ai_hub.work_orchestrator as work_module
    from test_work_orchestrator import FakeArtifacts, FakeLeases, FakeServices, config, init_repo, wait_terminal

    class Clock:
        expired = False
        def monotonic(self):
            return real_time.monotonic() + (120 if self.expired else 0)
        def __getattr__(self, name):
            return getattr(real_time, name)

    clock = Clock()
    monkeypatch.setattr(work_module, "time", clock)
    entered, release = threading.Event(), threading.Event()
    class NoncooperativePlanner(FakeServices):
        def delegate_repo(self, args, **kwargs):
            entered.set()
            assert release.wait(10)
            return super().delegate_repo(args)

    root = init_repo(tmp_path)
    services = NoncooperativePlanner("--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n")
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", services, None, FakeLeases(), FakeArtifacts())
    try:
        submitted = wo.submit({"root": str(root), "task": "replace old with new", "mode": "bounded",
            "acceptance_criteria": ["a.txt contains new"], "allowed_paths": ["a.txt"],
            "approved_commands": ["git diff --check"], "budget": {"max_steps": 8, "max_seconds": 60},
            "permissions": {"edit": True, "tests": True, "build": True}})
        assert submitted["success"] is True
        assert entered.wait(20)
        work_id = submitted["work_id"]
        assert wo.status(work_id).get("timed_out") is not True
        clock.expired = True
        for result in (wo.status(work_id), wo.get(work_id, profile="minimal"),
                       wo.get(work_id, return_fields=["summary"], max_output_tokens=64),
                       wo.wait(work_id, timeout_seconds=0)):
            assert result["status"] == "planning", result
            assert result["timed_out"] is True and result["in_progress"] is True, result
            assert result["success"] is False, result
            from local_ai_hub.response_budget import budget_response
            projected = budget_response(result, profile="minimal", max_tokens=128)
            assert projected["timed_out"] is True and projected["in_progress"] is True, projected
        assert (root / "a.txt").read_text().strip() == "old"
        release.set()
        handoff = wait_terminal(wo, work_id, timeout=60)
        assert handoff["status"] == "failed", handoff
        assert (root / "a.txt").read_text().strip() == "old"
    finally:
        release.set()
        wo.close()


@pytest.mark.parametrize("reason", ["budget", "review", "deadline"])
def test_task_bound_rollback_closes_barrier_on_partial_or_review_handoff(tmp_path, monkeypatch, reason):
    import json
    import time as real_time
    import local_ai_hub.work_orchestrator as work_module
    from test_work_orchestrator import FakeArtifacts, FakeLeases, FakeServices, config, init_repo, owned_verification_context, wait_terminal

    class Services(FakeServices):
        def delegate_repo(self, args, **kwargs):
            return super().delegate_repo(args)
        def second_opinion(self, args, **kwargs):
            if reason == "review":
                return {"success": True, "text": json.dumps({"passed": False, "needs_agent": True,
                        "summary": "needs a decision", "question": "Which option?", "risks": []})}
            return super().second_opinion(args)

    root = init_repo(tmp_path)
    artifacts = FakeArtifacts()
    services = Services("--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n")
    verification = owned_verification_context(tmp_path, root, artifacts, "bounded-task")
    initial_generation = verification.task_store.get("bounded-task").checkpoint.state_data.get("mutation_generation", 0)
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", services, None, FakeLeases(), artifacts,
                          verification_store=verification)
    if reason == "deadline":
        class Clock:
            offset = 0
            def monotonic(self):
                return real_time.monotonic() + self.offset
            def __getattr__(self, name):
                return getattr(real_time, name)
        clock = Clock()
        monkeypatch.setattr(work_module, "time", clock)
        original_apply = wo._apply_patch
        def apply_then_expire(*args, **kwargs):
            result = original_apply(*args, **kwargs)
            clock.offset = 120
            return result
        monkeypatch.setattr(wo, "_apply_patch", apply_then_expire)
    try:
        budget = {"max_steps": 8, "max_seconds": 60}
        if reason == "budget":
            budget["max_llm_calls"] = 2
        submitted = wo.submit({"root": str(root), "task_id": "bounded-task", "task": "replace old with new",
            "mode": "bounded", "acceptance_criteria": ["a.txt contains new"], "allowed_paths": ["a.txt"],
            "approved_commands": ["git diff --check"], "budget": budget,
            "permissions": {"edit": True, "tests": True, "build": True}})
        assert submitted["success"] is True
        handoff = wait_terminal(wo, submitted["work_id"], timeout=60)
        assert handoff["status"] == {"budget": "partial", "review": "needs_agent", "deadline": "failed"}[reason], handoff
        if reason == "deadline":
            assert "work time budget exhausted" in handoff["error"]
        assert (root / "a.txt").read_text(encoding="utf-8").strip() == "old"
        task = verification.task_store.get("bounded-task")
        assert "_pending_fenced_work" not in task.checkpoint.state_data
        assert task.checkpoint.state_data["mutation_generation"] == initial_generation + 2
        assert task.verification_receipts == {}
        assert wo._load_journal(submitted["work_id"]) == []
    finally:
        wo.close()


@pytest.mark.parametrize("paths,commands", [
    ([], ["python -m pytest"]),
    (["../outside"], ["python -m pytest"]),
    ([".git/config"], ["python -m pytest"]),
    (["/absolute"], ["python -m pytest"]),
    (["src/main.py"], []),
    (["src/main.py"], ["python -m pytest\nother"]),
    (["src/main.py", "src/main.py"], ["python -m pytest"]),
])
def test_invalid_scope_rejected(tmp_path, paths, commands):
    with pytest.raises(ValueError):
        _bounded_work_scope(tmp_path, paths, commands)


@pytest.mark.parametrize("path", [".git./config", "src/name.", "src/name /file.py", "src/file.py:stream", "src/NUL.txt"])
def test_windows_ambiguous_or_reserved_path_rejected(tmp_path, path):
    import os
    if os.name != "nt":
        pytest.skip("Windows path aliases")
    with pytest.raises(ValueError):
        _bounded_work_scope(tmp_path, [path], ["python -m pytest"])


def test_windows_case_variant_scope_duplicates_rejected(tmp_path):
    import os
    if os.name != "nt":
        pytest.skip("Windows case-insensitive scope")
    with pytest.raises(ValueError):
        _bounded_work_scope(tmp_path, ["src/File.py", "src/file.py"], ["python -m pytest"])


def test_symlink_scope_rejected(tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    try:
        (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError):
        _bounded_work_scope(tmp_path, ["linked/file.py"], ["python -m pytest"])


def test_windows_junction_scope_rejected_without_touching_target(tmp_path):
    import os
    import stat
    import subprocess
    from local_ai_hub.process_utils import hidden_run_kwargs

    if os.name != "nt":
        pytest.skip("Windows junctions")
    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "file.py").write_text("sentinel\n", encoding="utf-8")
    junction = root / "linked"
    result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
                            capture_output=True, text=True, timeout=10, **hidden_run_kwargs())
    if result.returncode != 0:
        pytest.skip("junction creation unavailable")
    try:
        assert os.lstat(junction).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
        with pytest.raises(ValueError):
            _bounded_work_scope(root, ["linked/file.py"], ["python -m pytest"])
        assert (outside / "file.py").read_text(encoding="utf-8") == "sentinel\n"
    finally:
        os.rmdir(junction)


def test_windows_junction_swap_after_scope_is_rejected_before_patch(tmp_path):
    import os
    import subprocess
    from local_ai_hub.process_utils import hidden_run_kwargs
    from test_work_orchestrator import FakeArtifacts, FakeLeases, config, init_repo

    if os.name != "nt":
        pytest.skip("Windows junctions")
    root = init_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "file.py").write_text("old\n", encoding="utf-8")
    target_dir = root / "linked"
    target_dir.mkdir()
    allowed, _ = _bounded_work_scope(root, ["linked/file.py"], ["git diff --check"])
    os.rmdir(target_dir)
    result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(target_dir), str(outside)],
                            capture_output=True, text=True, timeout=10, **hidden_run_kwargs())
    if result.returncode != 0:
        pytest.skip("junction creation unavailable")
    orchestrator = None
    try:
        orchestrator = WorkOrchestrator(config(tmp_path), tmp_path / "state", object(), object(), FakeLeases(), FakeArtifacts())
        patch = "--- a/linked/file.py\n+++ b/linked/file.py\n@@ -1 +1 @@\n-old\n+new\n"
        with pytest.raises((ValueError, PermissionError)):
            orchestrator._apply_patch(root, patch, "work", [], allowed_paths=allowed)
        assert (outside / "file.py").read_text(encoding="utf-8") == "old\n"
    finally:
        if orchestrator is not None:
            orchestrator.close()
        os.rmdir(target_dir)


def test_windows_junction_swap_between_git_check_and_apply_does_not_escape(tmp_path, monkeypatch):
    import os
    import subprocess
    from local_ai_hub.process_utils import hidden_run_kwargs
    from local_ai_hub import work_orchestrator as work_module
    from test_work_orchestrator import FakeArtifacts, FakeLeases, config, init_repo

    if os.name != "nt":
        pytest.skip("Windows junctions")
    root = init_repo(tmp_path)
    source_dir, saved_dir = root / "src", root / "saved-src"
    outside = tmp_path / "outside"
    source_dir.mkdir()
    outside.mkdir()
    (source_dir / "file.py").write_text("old\n", encoding="utf-8")
    (outside / "file.py").write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "src/file.py"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=T", "-c", "user.email=t@e",
                    "commit", "-qm", "add source"], check=True)
    original_run = subprocess.run
    swapped = []
    swap_blocked = []
    def swap_after_check(args, **kwargs):
        result = original_run(args, **kwargs)
        if args[0] == "git" and "apply" in args and "--check" in args and result.returncode == 0 and not swapped and not swap_blocked:
            try:
                source_dir.rename(saved_dir)
            except OSError:
                swap_blocked.append(True)
                return result
            made = original_run(["cmd.exe", "/d", "/c", "mklink", "/J", str(source_dir), str(outside)],
                                capture_output=True, text=True, timeout=10, **hidden_run_kwargs())
            if made.returncode != 0:
                saved_dir.rename(source_dir)
                pytest.skip("junction creation unavailable")
            swapped.append(True)
        return result
    orchestrator = WorkOrchestrator(config(tmp_path), tmp_path / "state", object(), object(), FakeLeases(), FakeArtifacts())
    monkeypatch.setattr(work_module.subprocess, "run", swap_after_check)
    try:
        patch = "--- a/src/file.py\n+++ b/src/file.py\n@@ -1 +1 @@\n-old\n+new\n"
        try:
            orchestrator._apply_patch(root, patch, "work", [], allowed_paths=["src/file.py"])
        except (ValueError, RuntimeError, PermissionError):
            pass
        assert swapped or swap_blocked
        assert (outside / "file.py").read_text(encoding="utf-8") == "old\n"
    finally:
        orchestrator.close()
        if swapped:
            os.rmdir(source_dir)
            saved_dir.rename(source_dir)


@pytest.mark.parametrize("outside_text", ["old\n", "foreign\n"], ids=["same", "different"])
def test_windows_hardlink_swap_between_git_check_and_apply_does_not_change_target(tmp_path, monkeypatch, outside_text):
    import os
    import subprocess
    from local_ai_hub import work_orchestrator as work_module
    from test_work_orchestrator import FakeArtifacts, FakeLeases, config, init_repo

    if os.name != "nt":
        pytest.skip("Windows hardlink behavior")
    root = init_repo(tmp_path)
    target = root / "a.txt"
    saved = root / "saved-a.txt"
    outside = tmp_path / "outside.txt"
    outside.write_text(outside_text, encoding="utf-8")
    original_run = subprocess.run
    swapped = []
    def swap_after_check(args, **kwargs):
        result = original_run(args, **kwargs)
        if args[0] == "git" and "apply" in args and "--check" in args and result.returncode == 0 and not swapped:
            target.rename(saved)
            os.link(outside, target)
            swapped.append(True)
        return result
    orchestrator = WorkOrchestrator(config(tmp_path), tmp_path / "state", object(), object(), FakeLeases(), FakeArtifacts())
    monkeypatch.setattr(work_module.subprocess, "run", swap_after_check)
    try:
        patch = "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"
        try:
            orchestrator._apply_patch(root, patch, "work", [], allowed_paths=["a.txt"])
        except (ValueError, RuntimeError, PermissionError):
            pass
        assert swapped
        assert outside.read_text(encoding="utf-8") == outside_text
    finally:
        orchestrator.close()


def test_bounded_create_in_existing_directory_remains_supported(tmp_path):
    from test_work_orchestrator import FakeArtifacts, FakeLeases, config, init_repo

    root = init_repo(tmp_path)
    (root / "src").mkdir()
    orchestrator = WorkOrchestrator(config(tmp_path), tmp_path / "state", object(), object(), FakeLeases(), FakeArtifacts())
    try:
        patch = "diff --git a/src/new.py b/src/new.py\nnew file mode 100644\n--- /dev/null\n+++ b/src/new.py\n@@ -0,0 +1 @@\n+value = 1\n"
        orchestrator._apply_patch(root, patch, "work", [], allowed_paths=["src/new.py"], permissions={"create": True})
        assert (root / "src" / "new.py").read_text(encoding="utf-8") == "value = 1\n"
    finally:
        orchestrator.close()


def test_windows_bounded_create_rejects_missing_parent_without_side_effect(tmp_path):
    import os
    from test_work_orchestrator import FakeArtifacts, FakeLeases, config, init_repo

    if os.name != "nt":
        pytest.skip("Windows directory pinning")
    root = init_repo(tmp_path)
    orchestrator = WorkOrchestrator(config(tmp_path), tmp_path / "state", object(), object(), FakeLeases(), FakeArtifacts())
    try:
        patch = "diff --git a/missing/new.py b/missing/new.py\nnew file mode 100644\n--- /dev/null\n+++ b/missing/new.py\n@@ -0,0 +1 @@\n+value = 1\n"
        with pytest.raises(ValueError, match="existing parent directory"):
            orchestrator._apply_patch(root, patch, "work", [], allowed_paths=["missing/new.py"], permissions={"create": True})
        assert not (root / "missing").exists()
    finally:
        orchestrator.close()


def test_windows_directory_pin_releases_on_exception(tmp_path):
    import os
    from local_ai_hub.work_orchestrator import _pin_windows_work_directories

    if os.name != "nt":
        pytest.skip("Windows directory pinning")
    directory = tmp_path / "src"
    directory.mkdir()
    (directory / "file.py").write_text("old\n", encoding="utf-8")
    moved = tmp_path / "moved"
    with pytest.raises(RuntimeError, match="stop"):
        with _pin_windows_work_directories(tmp_path, ["src/file.py"]):
            with pytest.raises(OSError):
                directory.rename(moved)
            raise RuntimeError("stop")
    directory.rename(moved)
    assert (moved / "file.py").read_text(encoding="utf-8") == "old\n"


def test_windows_rollback_blocks_junction_swap_before_restore(tmp_path, monkeypatch):
    import hashlib
    import os
    import subprocess
    from local_ai_hub.process_utils import hidden_run_kwargs
    from local_ai_hub import work_orchestrator as work_module
    from local_ai_hub.work_orchestrator import _JournalEntry

    if os.name != "nt":
        pytest.skip("Windows junctions")
    root, outside = tmp_path / "repo", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    source_dir, saved_dir = root / "src", root / "saved-src"
    source_dir.mkdir()
    (source_dir / "file.py").write_bytes(b"new\n")
    (outside / "file.py").write_bytes(b"new\n")
    entry = _JournalEntry("src/file.py", True, b"old\n", True, hashlib.sha256(b"new\n").hexdigest())
    original_write = work_module._write_windows_rollback_file
    swapped, blocked = [], []
    def swap_before_write(fd, data):
        if not swapped and not blocked:
            try:
                source_dir.rename(saved_dir)
            except OSError:
                blocked.append(True)
            else:
                result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(source_dir), str(outside)],
                                        capture_output=True, text=True, timeout=10, **hidden_run_kwargs())
                if result.returncode != 0:
                    saved_dir.rename(source_dir)
                    pytest.skip("junction creation unavailable")
                swapped.append(True)
        return original_write(fd, data)
    monkeypatch.setattr(work_module, "_write_windows_rollback_file", swap_before_write)
    try:
        try:
            WorkOrchestrator._rollback(root, [entry])
        except (ValueError, RuntimeError, OSError):
            pass
        assert swapped or blocked
        assert (outside / "file.py").read_bytes() == b"new\n"
    finally:
        if swapped:
            os.rmdir(source_dir)
            saved_dir.rename(source_dir)


def test_windows_rollback_does_not_write_through_swapped_hardlink(tmp_path, monkeypatch):
    import hashlib
    import os
    from local_ai_hub import work_orchestrator as work_module
    from local_ai_hub.work_orchestrator import _JournalEntry

    if os.name != "nt":
        pytest.skip("Windows hardlinks")
    root = tmp_path / "repo"
    root.mkdir()
    target, saved, outside = root / "file.py", root / "saved.py", tmp_path / "outside.py"
    target.write_bytes(b"new\n")
    outside.write_bytes(b"new\n")
    entry = _JournalEntry("file.py", True, b"old\n", True, hashlib.sha256(b"new\n").hexdigest())
    original_write = work_module._write_windows_rollback_file
    swapped, blocked = [], []
    def swap_before_write(fd, data):
        if not swapped and not blocked:
            try:
                target.rename(saved)
                os.link(outside, target)
                swapped.append(True)
            except OSError:
                blocked.append(True)
        return original_write(fd, data)
    monkeypatch.setattr(work_module, "_write_windows_rollback_file", swap_before_write)
    try:
        WorkOrchestrator._rollback(root, [entry])
    except (ValueError, RuntimeError, OSError):
        pass
    assert swapped or blocked
    assert outside.read_bytes() == b"new\n"


def test_windows_rollback_does_not_delete_replaced_created_file(tmp_path, monkeypatch):
    import hashlib
    import os
    from local_ai_hub import work_orchestrator as work_module
    from local_ai_hub.work_orchestrator import _JournalEntry

    if os.name != "nt":
        pytest.skip("Windows hardlinks")
    root = tmp_path / "repo"
    root.mkdir()
    target, saved, outside = root / "file.py", root / "saved.py", tmp_path / "outside.py"
    target.write_bytes(b"new\n")
    outside.write_bytes(b"new\n")
    entry = _JournalEntry("file.py", False, b"", True, hashlib.sha256(b"new\n").hexdigest())
    original_unlink = work_module._delete_windows_rollback_file
    swapped, blocked = [], []
    def swap_before_unlink(handle):
        if not swapped and not blocked:
            try:
                target.rename(saved)
                os.link(outside, target)
                swapped.append(True)
            except OSError:
                blocked.append(True)
        return original_unlink(handle)
    monkeypatch.setattr(work_module, "_delete_windows_rollback_file", swap_before_unlink)
    try:
        WorkOrchestrator._rollback(root, [entry])
    except (ValueError, RuntimeError, OSError):
        pass
    assert swapped or blocked
    assert outside.read_bytes() == b"new\n"
    if swapped:
        assert target.exists(), "rollback deleted a concurrently replaced file"


@pytest.mark.parametrize("case", ["deleted", "created", "multiple", "delete_then_create"])
def test_windows_handle_rollback_preserves_journal_semantics(tmp_path, case):
    import hashlib
    import os
    from local_ai_hub.work_orchestrator import _JournalEntry

    if os.name != "nt":
        pytest.skip("Windows handle rollback")
    target = tmp_path / "file.py"
    sha = lambda value: hashlib.sha256(value).hexdigest()
    if case == "deleted":
        journal = [_JournalEntry("file.py", True, b"old\n", False, sha(b""))]
    elif case == "created":
        target.write_bytes(b"new\n")
        journal = [_JournalEntry("file.py", False, b"", True, sha(b"new\n"))]
    elif case == "multiple":
        target.write_bytes(b"new\n")
        journal = [_JournalEntry("file.py", True, b"old\n", True, sha(b"mid\n")),
                   _JournalEntry("file.py", True, b"mid\n", True, sha(b"new\n"))]
    else:
        target.write_bytes(b"new\n")
        journal = [_JournalEntry("file.py", True, b"old\n", False, sha(b"")),
                   _JournalEntry("file.py", False, b"", True, sha(b"new\n"))]
    WorkOrchestrator._rollback(tmp_path, journal)
    if case == "created":
        assert not target.exists()
    else:
        assert target.read_bytes() == b"old\n"


def test_windows_rollback_missing_target_uses_exclusive_creation(tmp_path, monkeypatch):
    import hashlib
    import os
    from pathlib import Path
    from local_ai_hub.work_orchestrator import _JournalEntry

    if os.name != "nt":
        pytest.skip("Windows handle rollback")
    root = tmp_path / "repo"
    root.mkdir()
    target, outside = root / "file.py", tmp_path / "outside.py"
    outside.write_bytes(b"foreign\n")
    entry = _JournalEntry("file.py", True, b"old\n", False, hashlib.sha256(b"").hexdigest())
    original_open = Path.open
    inserted = []
    def insert_before_create(path, mode="r", *args, **kwargs):
        if path == target and mode == "xb" and not inserted:
            os.link(outside, target)
            inserted.append(True)
        return original_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", insert_before_create)
    with pytest.raises(FileExistsError):
        WorkOrchestrator._rollback(root, [entry])
    assert inserted and target.read_bytes() == b"foreign\n"
    assert outside.read_bytes() == b"foreign\n"


def test_patch_outside_scope_rejected_before_lease(tmp_path):
    orchestrator = object.__new__(WorkOrchestrator)
    orchestrator.allow_edits = True
    orchestrator.max_patch_bytes = 8192
    orchestrator.max_patch_files = 8
    patch = "diff --git a/other.py b/other.py\n--- a/other.py\n+++ b/other.py\n@@ -1 +1 @@\n-old\n+new\n"
    with pytest.raises(PermissionError, match="scope"):
        orchestrator._apply_patch(tmp_path, patch, "work1", [], allowed_paths=["safe.py"])


@pytest.mark.parametrize("metadata", [
    "diff --git a/outside.py b/outside.py\nold mode 100644\nnew mode 100755\n",
    "diff --git a/outside.py b/other.py\nsimilarity index 100%\nrename from outside.py\nrename to other.py\n",
    "diff --git a/outside.bin b/outside.bin\nGIT binary patch\n",
    "diff --git a/link b/link\nnew file mode 120000\n",
])
def test_unscoped_git_metadata_is_rejected_before_lease(tmp_path, metadata):
    orchestrator = object.__new__(WorkOrchestrator)
    orchestrator.allow_edits = True
    orchestrator.max_patch_bytes = 8192
    orchestrator.max_patch_files = 8
    patch = metadata + "--- a/safe.py\n+++ b/safe.py\n@@ -1 +1 @@\n-old\n+new\n"
    with pytest.raises(PermissionError, match="metadata"):
        orchestrator._apply_patch(tmp_path, patch, "work1", [], allowed_paths=["safe.py"])


def test_mcp_exposes_bounded_scope_parameters():
    import inspect
    from local_ai_hub.mcp_server import local_ai_work

    parameters = inspect.signature(local_ai_work).parameters
    assert "allowed_paths" in parameters
    assert "approved_commands" in parameters


def test_bounded_scope_passes_public_operation_preflight(tmp_path):
    from local_ai_hub.operation_contracts import validate_operation_call
    args = {
        "action": "submit", "root": str(tmp_path), "task": "small fix", "mode": "bounded",
        "allowed_paths": ["a.py"], "approved_commands": ["python -m pytest"],
        "acceptance_criteria": ["tests pass"], "budget": {"max_steps": 8, "max_seconds": 60},
        "permissions": {"edit": True, "tests": True, "build": True},
    }
    assert validate_operation_call("local_ai_work", args) is None


def test_mcp_forwards_bounded_scope(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from local_ai_hub import mcp_server

    calls = []
    monkeypatch.setattr(mcp_server, "FEATURES", SimpleNamespace(work_orchestrator=True, hardware_profile="high", bounded_work_tier=True, bounded_work_qualified=True))
    monkeypatch.setattr(mcp_server, "CLIENT", SimpleNamespace(post=lambda path, payload, **kwargs: calls.append((path, payload)) or {"success": True}))
    monkeypatch.setattr(mcp_server, "_client_root", lambda root: root)
    mcp_server.local_ai_work.__wrapped__(
        action="submit", root=str(tmp_path), task="change", mode="bounded",
        allowed_paths=["a.py"], approved_commands=["python -m pytest"],
        acceptance_criteria=["tests pass"], permissions={"edit": True, "tests": True, "build": True},
        budget={"max_steps": 8, "max_seconds": 60},
    )
    assert calls[0][0] == "/api/work-orders"
    assert calls[0][1]["allowed_paths"] == ["a.py"]
    assert calls[0][1]["approved_commands"] == ["python -m pytest"]


def test_bounded_scope_reaches_work_endpoint_through_mcp(monkeypatch, tmp_path):
    import asyncio
    from types import SimpleNamespace
    from local_ai_hub import mcp_server
    calls = []
    monkeypatch.setattr(mcp_server.FEATURES, "work_orchestrator", True)
    monkeypatch.setattr(mcp_server.FEATURES, "hardware_profile", "high")
    monkeypatch.setattr(mcp_server.FEATURES, "bounded_work_tier", True)
    monkeypatch.setattr(mcp_server.FEATURES, "bounded_work_qualified", True)
    monkeypatch.setattr(mcp_server, "CLIENT", SimpleNamespace(post=lambda path, payload, **kwargs: calls.append((path, payload)) or {"success": True, "status": "queued", "work_id": "w1"}))
    monkeypatch.setattr(mcp_server, "_client_root", lambda root: root)
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *args, **kwargs: None)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **kwargs: None)
    result = asyncio.run(mcp_server.mcp.call_tool("local_ai_work", {
        "action": "submit", "root": str(tmp_path), "task": "small fix", "mode": "bounded",
        "allowed_paths": ["a.py"], "approved_commands": ["python -m pytest"],
        "acceptance_criteria": ["tests pass"], "budget": {"max_steps": 8, "max_seconds": 60},
        "permissions": {"edit": True, "tests": True, "build": True},
    }))
    assert calls and calls[0][0] == "/api/work-orders", result
    assert calls[0][1]["allowed_paths"] == ["a.py"]
    assert calls[0][1]["approved_commands"] == ["python -m pytest"]


@pytest.mark.parametrize("response", [
    {"success": False, "text": ""},
    {"text": '{"steps": []}'},
    {"success": True, "outcome_unknown": True,
     "text": '{"steps": [{"id": "s1", "kind": "edit", "task": "change", "depends_on": []}]}'},
    {"success": True, "timed_out": None,
     "text": '{"steps": [{"id": "s1", "kind": "edit", "task": "change", "depends_on": []}]}'},
])
def test_bounded_plan_rejects_malformed_model_response(tmp_path, response):
    from test_work_orchestrator import FakeArtifacts, FakeLeases, FakeServices, config

    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", FakeServices(""), None, FakeLeases(), FakeArtifacts())
    wo._ask = lambda *args, **kwargs: response
    try:
        with pytest.raises(ValueError, match="planner"):
            wo._plan(str(tmp_path), "change", {
                "mode": "bounded", "budget": {"max_steps": 8},
                "acceptance_criteria": ["change is correct"],
                "allowed_paths": ["a.py"], "approved_commands": ["python -m pytest"],
            }, {})
    finally:
        wo.close()


@pytest.mark.parametrize("stage", ["edit", "repair", "review", "final"])
@pytest.mark.parametrize("flag,value", [(flag, True) for flag in
    ("outcome_unknown", "timed_out", "cancelled", "cleanup_unconfirmed", "_lah_partial_response", "preempted", "output_truncated")]
    + [("final_response_produced", False), ("final_response_status", "empty")])
def test_uncertain_model_response_never_yields_bounded_handoff(tmp_path, stage, flag, value):
    from test_work_orchestrator import FakeArtifacts, FakeLeases, FakeServices, config, init_repo, wait_terminal

    class UncertainModel(FakeServices):
        def delegate_repo(self, args, **kwargs):
            response = super().delegate_repo(args)
            if (stage == "edit" and self.delegate_calls > 1) or (stage == "repair" and self.delegate_calls > 2):
                response[flag] = value
            return response

        def second_opinion(self, args, **kwargs):
            response = super().second_opinion(args)
            if stage == "review" or (stage == "final" and "FINAL WHOLE-TASK VERIFIER" in args.get("question", "")):
                response[flag] = value
            return response

    root = init_repo(tmp_path)
    services = UncertainModel("--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n", validation_ok=stage != "repair")
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", services, None, FakeLeases(), FakeArtifacts())
    try:
        submitted = wo.submit({"root": str(root), "task": "replace old with new", "mode": "bounded",
            "acceptance_criteria": ["a.txt contains new"], "allowed_paths": ["a.txt"],
            "approved_commands": ["git diff --check"], "budget": {"max_steps": 8, "max_seconds": 60},
            "permissions": {"edit": True, "tests": True, "build": True}})
        assert submitted["success"] is True
        handoff = wait_terminal(wo, submitted["work_id"], timeout=60)
        assert handoff["status"] == "failed", handoff
        assert flag in handoff["error"]
        assert (root / "a.txt").read_text(encoding="utf-8").strip() == "old"
    finally:
        wo.close()


def test_bounded_order_does_not_infer_create_or_delete_permission(tmp_path):
    import json
    from test_work_orchestrator import FakeArtifacts, FakeLeases, FakeServices, config

    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", FakeServices(""), None, FakeLeases(), FakeArtifacts())
    wo._ensure_workers = lambda: None
    try:
        result = wo.submit({
            "root": str(tmp_path), "task": "small change", "mode": "bounded",
            "acceptance_criteria": ["change verified"], "allowed_paths": ["a.py"],
            "approved_commands": ["python -m pytest"], "budget": {"max_steps": 8, "max_seconds": 60},
            "permissions": {"edit": True, "tests": True, "build": True},
        })
        assert result["success"] is True
        stored = json.loads(wo._row(result["work_id"])["payload_json"])
        assert stored["permissions"]["create"] is False
        assert stored["permissions"]["delete"] is False
    finally:
        wo.close()


def test_bounded_validation_only_does_not_require_edit_permission(tmp_path):
    from test_work_orchestrator import FakeArtifacts, FakeLeases, FakeServices, config
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", FakeServices(""), None, FakeLeases(), FakeArtifacts())
    wo._ensure_workers = lambda: None
    try:
        result = wo.submit({
            "root": str(tmp_path), "task": "run tests", "mode": "bounded",
            "acceptance_criteria": ["tests pass"], "allowed_paths": ["test_a.py"],
            "approved_commands": ["python -m pytest"], "budget": {"max_steps": 8, "max_seconds": 60},
            "permissions": {"edit": False, "tests": True, "build": True},
        })
        assert result["success"] is True
    finally:
        wo.close()


def test_bounded_order_rejects_command_list_larger_than_budget(tmp_path):
    from test_work_orchestrator import FakeArtifacts, FakeLeases, FakeServices, config
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", FakeServices(""), None, FakeLeases(), FakeArtifacts())
    try:
        result = wo.submit({
            "root": str(tmp_path), "task": "small change", "mode": "bounded",
            "acceptance_criteria": ["change verified"], "allowed_paths": ["a.py"],
            "approved_commands": ["first", "second"],
            "budget": {"max_steps": 8, "max_seconds": 60, "max_commands": 1},
            "permissions": {"edit": True, "tests": True, "build": True},
        })
        assert result["success"] is False
        assert "command" in result["error"]
    finally:
        wo.close()


@pytest.mark.parametrize("status", ["partial", "needs_agent"])
def test_bounded_incomplete_handoff_is_not_success(status):
    wo = object.__new__(WorkOrchestrator)
    result = wo._canonical({"state": status, "work_id": "w", "payload_json": '{"mode":"bounded"}', "result_json": "{}"})
    assert result["success"] is False
    assert result["status"] == status


@pytest.mark.parametrize("allowed, expected_status", [(["a.txt"], "needs_agent"), (["other.txt"], "failed")])
def test_bounded_order_applies_only_allowed_patch_and_runs_only_approved_command(tmp_path, allowed, expected_status):
    import json
    from test_work_orchestrator import (
        FakeArtifacts, FakeLeases, FakeServices, config, init_repo,
        owned_verification_context, wait_terminal,
    )

    class PlannedCommands(FakeServices):
        def __init__(self):
            super().__init__("--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n")
            self.commands = []

        def delegate_repo(self, args, **kwargs):
            result = super().delegate_repo(args)
            if self.delegate_calls == 1:
                plan = json.loads(result["text"])
                plan["validation_commands"] = ["unapproved command"]
                result["text"] = json.dumps(plan)
            return result

        def second_opinion(self, args, **kwargs):
            return super().second_opinion(args)

        def command(self, args, *, request_cancel_event=None):
            self.commands.append(dict(args))
            return super().command(args)

    root = init_repo(tmp_path)
    services, artifacts = PlannedCommands(), FakeArtifacts()
    verification = owned_verification_context(tmp_path, root, artifacts, "bounded-task")
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", services, None, FakeLeases(), artifacts,
                          verification_store=verification)
    try:
        submitted = wo.submit({
            "root": str(root), "task": "replace old with new", "task_id": "bounded-task",
            "acceptance_criteria": ["a.txt contains new"], "mode": "bounded",
            "permissions": {"edit": True, "tests": True, "build": True},
            "allowed_paths": allowed, "approved_commands": ["git diff --check"],
            "budget": {"max_steps": 8, "max_seconds": 60},
        })
        assert submitted["success"] is True
        result = wait_terminal(wo, submitted["work_id"], timeout=60)
        assert result["status"] == expected_status
        assert (root / "a.txt").read_text().strip() == ("new" if expected_status == "needs_agent" else "old")
        assert all(call.get("command") == "git diff --check" for call in services.commands)
        if expected_status == "needs_agent":
            assert services.commands
            assert result["requires_primary_review"] is True
            assert result["success"] is False
            assert not any(receipt.get("evidence_type") == "source_review" for receipt in result["verification_receipts"])
            assert wo.get(submitted["work_id"], profile="compact")["requires_primary_review"] is True
    finally:
        wo.close()


@pytest.mark.parametrize("response", [
    {"success": True},
    {"success": True, "exit_code": 0, "timed_out": True},
    {"success": True, "exit_code": 0, "outcome_unknown": True},
    {"success": True, "exit_code": 0, "cleanup_unconfirmed": True},
    {"success": True, "exit_code": 0, "output_capture_unconfirmed": True},
    {"success": True, "exit_code": 0, "in_progress": True},
    {"success": True, "exit_code": 0, "cancelled": None},
    {"success": False, "exit_code": 1, "timed_out": True},
])
def test_bounded_order_rolls_back_ambiguous_validation(tmp_path, response):
    import json
    from test_work_orchestrator import (
        FakeArtifacts, FakeLeases, FakeServices, config, init_repo,
        owned_verification_context, wait_terminal,
    )

    class AmbiguousValidation(FakeServices):
        def delegate_repo(self, args, **kwargs):
            return super().delegate_repo(args)

        def second_opinion(self, args, **kwargs):
            return super().second_opinion(args)

        def command(self, args, *, request_cancel_event=None):
            self.command_calls = getattr(self, "command_calls", 0) + 1
            return response

    root = init_repo(tmp_path)
    artifacts = FakeArtifacts()
    services = AmbiguousValidation("--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n")
    verification = owned_verification_context(tmp_path, root, artifacts, "bounded-task")
    cfg = config(tmp_path)
    cfg.setdefault("features", {})["local_diagnostic_dispatch"] = True
    wo = WorkOrchestrator(cfg, tmp_path / "state", services, None, FakeLeases(), artifacts,
                          verification_store=verification)
    try:
        submitted = wo.submit({
            "root": str(root), "task": "replace old with new", "task_id": "bounded-task",
            "acceptance_criteria": ["a.txt contains new"], "mode": "bounded",
            "permissions": {"edit": True, "tests": True, "build": True},
            "allowed_paths": ["a.txt"], "approved_commands": ["git diff --check"],
            "budget": {"max_steps": 8, "max_seconds": 60},
        })
        result = wait_terminal(wo, submitted["work_id"], timeout=60)
        assert result["status"] == "failed"
        assert services.command_calls == 1
        assert (root / "a.txt").read_text().strip() == "old"
        failure = json.loads(artifacts.data[result["artifact_id"]]["text"])
        assert failure["validation"][0]["success"] is False
        assert failure["validation"][0]["broker_success"] is response.get("success")
        assert failure["validation"][0]["exit_code"] == response.get("exit_code")
        assert "local_handoff" not in result
    finally:
        wo.close()


def test_bounded_intermediate_review_rejects_non_boolean_passed(tmp_path):
    import json
    from test_work_orchestrator import FakeArtifacts, FakeLeases, FakeServices, config, init_repo, wait_terminal

    class AmbiguousReview(FakeServices):
        def delegate_repo(self, args, **kwargs):
            return super().delegate_repo(args)

        def second_opinion(self, args, **kwargs):
            self.verify_calls += 1
            return {"success": True, "text": json.dumps({"passed": "false", "summary": "ambiguous"})}

    root = init_repo(tmp_path)
    services = AmbiguousReview("--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n")
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", services, None, FakeLeases(), FakeArtifacts())
    try:
        submitted = wo.submit({
            "root": str(root), "task": "replace old with new", "mode": "bounded",
            "acceptance_criteria": ["a.txt contains new"], "allowed_paths": ["a.txt"],
            "approved_commands": ["git diff --check"], "budget": {"max_steps": 8, "max_seconds": 60},
            "permissions": {"edit": True, "tests": True, "build": True},
        })
        result = wait_terminal(wo, submitted["work_id"], timeout=60)
        assert result["status"] == "failed"
        assert services.verify_calls == 1
        assert (root / "a.txt").read_text().strip() == "old"
    finally:
        wo.close()


@pytest.mark.parametrize("save_artifact", [True, False])
def test_cancel_during_validation_does_not_record_late_receipt(tmp_path, save_artifact):
    import json
    from test_work_orchestrator import (
        FakeArtifacts, FakeLeases, FakeServices, config, init_repo,
        owned_verification_context, wait_terminal,
    )

    entered, release = threading.Event(), threading.Event()

    class LateValidation(FakeServices):
        def delegate_repo(self, args, **kwargs):
            return super().delegate_repo(args)

        def second_opinion(self, args, **kwargs):
            return super().second_opinion(args)

        def command(self, args, *, request_cancel_event=None):
            entered.set()
            assert release.wait(30)
            return {"success": True, "exit_code": 0, "execution_id": "late", "repository_revision": "rev"}

    root = init_repo(tmp_path)
    class Artifacts(FakeArtifacts):
        def put(self, text, *, kind):
            if kind == "work-cancellation" and not save_artifact:
                return None
            return super().put(text, kind=kind)

    artifacts = Artifacts()
    services = LateValidation("--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n")
    verification = owned_verification_context(tmp_path, root, artifacts, "bounded-task")
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", services, None, FakeLeases(), artifacts,
                          verification_store=verification)
    try:
        submitted = wo.submit({
            "root": str(root), "task": "replace old with new", "task_id": "bounded-task", "mode": "bounded",
            "acceptance_criteria": ["tests pass"], "allowed_paths": ["a.txt"],
            "approved_commands": ["python -m pytest"], "budget": {"max_steps": 8, "max_seconds": 60},
            "permissions": {"edit": True, "tests": True, "build": True},
        })
        assert entered.wait(30)
        assert wo.cancel(submitted["work_id"])["success"] is True
        release.set()
        result = wait_terminal(wo, submitted["work_id"], timeout=30)
        assert result["status"] == "cancelled"
        assert not any(item["kind"] == "command_verification" for item in artifacts.data.values())
        if save_artifact:
            report = json.loads(artifacts.data[result["artifact_id"]]["text"])
            assert report["validation"][0]["broker_success"] is True
            assert report["validation"][0]["success"] is False
            assert report["validation"][0]["work_cancelled"] is True
        else:
            assert result["error"] == "cancellation validation artifact unavailable"
    finally:
        release.set()
        wo.close()


def test_deadline_after_broker_reply_retains_validation_evidence(tmp_path, monkeypatch):
    import json
    import time
    import local_ai_hub.work_orchestrator as work_module
    from test_work_orchestrator import FakeArtifacts, FakeLeases, FakeServices, config, init_repo, wait_terminal

    class Clock:
        expired = False
        def monotonic(self):
            return time.monotonic() + (120 if self.expired else 0)
        def __getattr__(self, name):
            return getattr(time, name)

    clock = Clock()
    monkeypatch.setattr(work_module, "time", clock)

    class LateValidation(FakeServices):
        def delegate_repo(self, args, **kwargs):
            return super().delegate_repo(args)

        def second_opinion(self, args, **kwargs):
            return super().second_opinion(args)

        def command(self, args, *, request_cancel_event=None):
            clock.expired = True
            return {"success": True, "exit_code": 0, "execution_id": "late", "repository_revision": "rev"}

    root = init_repo(tmp_path)
    artifacts = FakeArtifacts()
    services = LateValidation("--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n")
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", services, None, FakeLeases(), artifacts)
    try:
        submitted = wo.submit({
            "root": str(root), "task": "replace old with new", "mode": "bounded",
            "acceptance_criteria": ["tests pass"], "allowed_paths": ["a.txt"],
            "approved_commands": ["python -m pytest"], "budget": {"max_steps": 8, "max_seconds": 60},
            "permissions": {"edit": True, "tests": True, "build": True},
        })
        result = wait_terminal(wo, submitted["work_id"], timeout=60)
        assert result["status"] == "failed"
        assert "artifact_id" in result, result
        report = json.loads(artifacts.data[result["artifact_id"]]["text"])
        assert report["validation"][0]["broker_success"] is True
        assert report["validation"][0]["success"] is False
        assert report["validation"][0]["work_timed_out"] is True
        assert (root / "a.txt").read_text().strip() == "old"
    finally:
        wo.close()


@pytest.mark.parametrize("save_artifact", [True, False])
def test_cancel_during_local_edit_retains_observation_and_does_not_apply_late_patch(tmp_path, save_artifact):
    import json
    from test_work_orchestrator import FakeArtifacts, FakeLeases, FakeServices, config, init_repo, wait_terminal

    entered = threading.Event()

    class SlowEdit(FakeServices):
        def delegate_repo(self, args, *, cancel_event=None):
            if self.delegate_calls == 0:
                return super().delegate_repo(args)
            entered.set()
            assert cancel_event is not None and cancel_event.wait(10)
            return {"success": True, "model": "synthetic:9b", "text": self.patch}

        def second_opinion(self, args, **kwargs):
            return super().second_opinion(args)

    root = init_repo(tmp_path)
    class Artifacts(FakeArtifacts):
        def put(self, text, *, kind):
            if kind == "work-cancellation" and not save_artifact:
                return None
            return super().put(text, kind=kind)

    artifacts = Artifacts()
    services = SlowEdit("--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n")
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", services, None, FakeLeases(), artifacts)
    try:
        submitted = wo.submit({"root": str(root), "task": "replace old with new", "mode": "bounded",
            "acceptance_criteria": ["a.txt contains new"], "allowed_paths": ["a.txt"],
            "approved_commands": ["git diff --check"], "budget": {"max_steps": 8, "max_seconds": 60},
            "permissions": {"edit": True, "tests": True, "build": True}})
        assert submitted["success"] is True
        assert entered.wait(20)
        assert wo.cancel(submitted["work_id"])["success"] is True
        handoff = wait_terminal(wo, submitted["work_id"], timeout=60)
        assert handoff["status"] == "cancelled"
        assert (root / "a.txt").read_text(encoding="utf-8").strip() == "old"
        if save_artifact:
            report = json.loads(artifacts.get(handoff["artifact_id"])["text"])
            assert report["cancelled_step"]["success"] is False
            assert report["cancelled_step"]["model_observations"][0]["reported_model"] == "synthetic:9b"
            assert report["cancelled_step"]["model_observations"][0]["identity_verified"] is False
        else:
            assert handoff["error"] == "cancellation step artifact unavailable"
    finally:
        wo.close()


@pytest.mark.parametrize("planner_result", ["late_success", "cancelled", "exception"])
@pytest.mark.parametrize("deadline_elapsed", [False, True])
def test_cancel_during_planning_finishes_without_mutation(tmp_path, monkeypatch, planner_result, deadline_elapsed):
    import time as real_time
    import local_ai_hub.work_orchestrator as work_module
    from test_work_orchestrator import FakeArtifacts, FakeLeases, FakeServices, config, init_repo, wait_terminal

    entered = threading.Event()

    class Clock:
        expired = False
        def monotonic(self):
            return real_time.monotonic() + (120 if self.expired else 0)
        def __getattr__(self, name):
            return getattr(real_time, name)
    clock = Clock()
    monkeypatch.setattr(work_module, "time", clock)

    class SlowPlanner(FakeServices):
        def delegate_repo(self, args, *, cancel_event=None):
            entered.set()
            assert cancel_event is not None and cancel_event.wait(10)
            if planner_result == "cancelled":
                return {"success": False, "cancelled": True}
            if planner_result == "exception":
                raise RuntimeError("cancelled backend")
            return super().delegate_repo(args)

    root = init_repo(tmp_path)
    services = SlowPlanner("--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n")
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", services, None, FakeLeases(), FakeArtifacts())
    try:
        submitted = wo.submit({"root": str(root), "task": "replace old with new", "mode": "bounded",
            "acceptance_criteria": ["a.txt contains new"], "allowed_paths": ["a.txt"],
            "approved_commands": ["git diff --check"], "budget": {"max_steps": 8, "max_seconds": 60},
            "permissions": {"edit": True, "tests": True, "build": True}})
        assert submitted["success"] is True
        assert entered.wait(20)
        clock.expired = deadline_elapsed
        assert wo.cancel(submitted["work_id"])["success"] is True
        handoff = wait_terminal(wo, submitted["work_id"], timeout=60)
        assert handoff["status"] == "cancelled", handoff
        assert (root / "a.txt").read_text(encoding="utf-8").strip() == "old"
        assert services.delegate_calls == (1 if planner_result == "late_success" else 0)
    finally:
        wo.close()


def test_planning_deadline_is_not_misreported_as_backend_cancellation(tmp_path, monkeypatch):
    import time as real_time
    import local_ai_hub.work_orchestrator as work_module
    from test_work_orchestrator import FakeArtifacts, FakeLeases, FakeServices, config, init_repo, wait_terminal

    class Clock:
        expired = False
        def monotonic(self):
            return real_time.monotonic() + (120 if self.expired else 0)
        def __getattr__(self, name):
            return getattr(real_time, name)

    clock = Clock()
    monkeypatch.setattr(work_module, "time", clock)
    class DeadlinePlanner(FakeServices):
        def delegate_repo(self, args, **kwargs):
            clock.expired = True
            return {"success": False, "cancelled": True}

    root = init_repo(tmp_path)
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", DeadlinePlanner(""), None, FakeLeases(), FakeArtifacts())
    try:
        submitted = wo.submit({"root": str(root), "task": "change", "mode": "bounded",
            "acceptance_criteria": ["change is correct"], "allowed_paths": ["a.txt"],
            "approved_commands": ["git diff --check"], "budget": {"max_steps": 8, "max_seconds": 60},
            "permissions": {"edit": True, "tests": True, "build": True}})
        assert submitted["success"] is True
        handoff = wait_terminal(wo, submitted["work_id"], timeout=60)
        assert handoff["status"] == "failed", handoff
        assert "work time budget exhausted" in handoff["error"]
        assert (root / "a.txt").read_text(encoding="utf-8").strip() == "old"
    finally:
        wo.close()


def test_real_deadline_stops_late_planner_before_patch(tmp_path, monkeypatch):
    from test_work_orchestrator import FakeArtifacts, FakeLeases, FakeServices, config, init_repo, wait_terminal

    class LateModel(FakeServices):
        def delegate_repo(self, args, *, cancel_event=None):
            assert cancel_event is not None and cancel_event.wait(35)
            return super().delegate_repo(args)

        def second_opinion(self, args, **kwargs):
            return super().second_opinion(args)

    root = init_repo(tmp_path)
    services = LateModel("--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n")
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", services, None, FakeLeases(), FakeArtifacts())
    original_execute = wo._execute_fenced
    applied = []
    original_apply = wo._apply_patch

    def delayed_execute(*args, **kwargs):
        # The outer timer starts first; simulate a scheduler pause before work starts.
        threading.Event().wait(0.5)
        return original_execute(*args, **kwargs)

    def observe_apply(*args, **kwargs):
        applied.append(True)
        return original_apply(*args, **kwargs)

    monkeypatch.setattr(wo, "_execute_fenced", delayed_execute)
    monkeypatch.setattr(wo, "_apply_patch", observe_apply)
    try:
        submitted = wo.submit({"root": str(root), "task": "change", "mode": "bounded",
            "acceptance_criteria": ["a.txt contains new"], "allowed_paths": ["a.txt"],
            "approved_commands": ["git diff --check"], "budget": {"max_steps": 8, "max_seconds": 30},
            "permissions": {"edit": True, "tests": True, "build": True}})
        assert submitted["success"] is True
        handoff = wait_terminal(wo, submitted["work_id"], timeout=40)
        assert handoff["status"] == "failed", handoff
        assert "work time budget exhausted" in handoff["error"]
        assert not applied
        assert services.delegate_calls == 1
        assert (root / "a.txt").read_text(encoding="utf-8").strip() == "old"
    finally:
        wo.close()


def test_bounded_elapsed_time_includes_delay_after_deadline_starts(tmp_path, monkeypatch):
    import json
    import time as real_time
    import local_ai_hub.work_orchestrator as work_module
    from test_work_orchestrator import FakeArtifacts, FakeLeases, FakeServices, config, init_repo, wait_terminal

    class Clock:
        offset = 0
        def monotonic(self):
            return real_time.monotonic() + self.offset
        def __getattr__(self, name):
            return getattr(real_time, name)

    class Services(FakeServices):
        def delegate_repo(self, args, **kwargs):
            return super().delegate_repo(args)
        def second_opinion(self, args, **kwargs):
            return super().second_opinion(args)

    clock = Clock()
    monkeypatch.setattr(work_module, "time", clock)
    root = init_repo(tmp_path)
    artifacts = FakeArtifacts()
    services = Services("--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n")
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", services, None, FakeLeases(), artifacts)
    original_execute = wo._execute_fenced
    def delayed_execute(*args, **kwargs):
        clock.offset = 3
        return original_execute(*args, **kwargs)
    monkeypatch.setattr(wo, "_execute_fenced", delayed_execute)
    try:
        submitted = wo.submit({"root": str(root), "task": "replace old with new", "mode": "bounded",
            "acceptance_criteria": ["a.txt contains new"], "allowed_paths": ["a.txt"],
            "approved_commands": ["git diff --check"], "budget": {"max_steps": 8, "max_seconds": 60},
            "permissions": {"edit": True, "tests": True, "build": True}})
        assert submitted["success"] is True
        handoff = wait_terminal(wo, submitted["work_id"], timeout=60)
        assert handoff["status"] == "needs_agent", handoff
        report = json.loads(artifacts.get(handoff["artifact_id"])["text"])
        assert 3 <= report["elapsed_seconds"] < 15
    finally:
        wo.close()


@pytest.mark.parametrize("contents", ["{}", "null", '"not-a-journal"', "0", "false"])
def test_non_array_journal_is_corrupt_not_empty(tmp_path, contents):
    from test_work_orchestrator import FakeArtifacts, FakeLeases, FakeServices, config

    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", FakeServices(""), None, FakeLeases(), FakeArtifacts())
    try:
        path = wo._journal_path("journal-test")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        assert wo._load_journal("journal-test") is None
        assert path.read_text(encoding="utf-8") == contents
    finally:
        wo.close()


def test_non_file_journal_is_corrupt_not_empty(tmp_path):
    from test_work_orchestrator import FakeArtifacts, FakeLeases, FakeServices, config

    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", FakeServices(""), None, FakeLeases(), FakeArtifacts())
    try:
        path = wo._journal_path("journal-test")
        path.mkdir(parents=True)
        assert wo._load_journal("journal-test") is None
        assert path.is_dir()
    finally:
        wo.close()


def test_planning_cancellation_preserves_corrupt_journal_for_recovery(tmp_path, monkeypatch):
    from test_work_orchestrator import FakeArtifacts, FakeLeases, FakeServices, config, init_repo

    entered, recovery_scheduled = threading.Event(), threading.Event()

    class SlowPlanner(FakeServices):
        def delegate_repo(self, args, *, cancel_event=None):
            entered.set()
            assert cancel_event is not None and cancel_event.wait(10)
            return {"success": False, "cancelled": True}

    root = init_repo(tmp_path)
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", SlowPlanner(""), None, FakeLeases(), FakeArtifacts())
    try:
        submitted = wo.submit({"root": str(root), "task": "change", "mode": "bounded",
            "acceptance_criteria": ["change is correct"], "allowed_paths": ["a.txt"],
            "approved_commands": ["git diff --check"], "budget": {"max_steps": 8, "max_seconds": 60},
            "permissions": {"edit": True, "tests": True, "build": True}})
        assert submitted["success"] is True
        assert entered.wait(20)
        journal = wo._journal_path(submitted["work_id"])
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text('{"corrupt": true}', encoding="utf-8")
        monkeypatch.setattr(wo, "_schedule_recovery_retry", recovery_scheduled.set)
        assert wo.cancel(submitted["work_id"])["success"] is True
        assert recovery_scheduled.wait(10)
        assert wo.get(submitted["work_id"])["status"] != "cancelled"
        assert journal.read_text(encoding="utf-8") == '{"corrupt": true}'
        assert (root / "a.txt").read_text(encoding="utf-8").strip() == "old"
    finally:
        wo.close()


def test_cancel_signals_running_bounded_validation(tmp_path):
    from test_work_orchestrator import FakeArtifacts, FakeLeases, FakeServices, config, init_repo, wait_terminal

    entered = threading.Event()
    observed = []

    class CancellableValidation(FakeServices):
        def delegate_repo(self, args, **kwargs):
            return super().delegate_repo(args)

        def second_opinion(self, args, **kwargs):
            return super().second_opinion(args)

        def command(self, args, *, request_cancel_event=None):
            entered.set()
            observed.append(request_cancel_event is not None and request_cancel_event.wait(3))
            return {"success": False, "cancelled": True, "exit_code": None}

    root = init_repo(tmp_path)
    services = CancellableValidation("--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n")
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", services, None, FakeLeases(), FakeArtifacts())
    try:
        submitted = wo.submit({
            "root": str(root), "task": "replace old with new", "mode": "bounded",
            "acceptance_criteria": ["a.txt contains new"], "allowed_paths": ["a.txt"],
            "approved_commands": ["git diff --check"], "budget": {"max_steps": 8, "max_seconds": 60},
            "permissions": {"edit": True, "tests": True, "build": True},
        })
        assert entered.wait(20)
        assert wo.cancel(submitted["work_id"])["success"] is True
        wo.close()
        assert observed == [True]
        assert wait_terminal(wo, submitted["work_id"])["status"] == "cancelled"
    finally:
        wo.close()


def test_other_process_cancellation_signals_running_bounded_validation(tmp_path):
    import subprocess
    import sys
    from local_ai_hub.process_utils import hidden_run_kwargs
    from test_work_orchestrator import FakeArtifacts, FakeLeases, FakeServices, config, init_repo, wait_terminal

    entered = threading.Event()
    observed = []

    class CancellableValidation(FakeServices):
        def delegate_repo(self, args, **kwargs):
            return super().delegate_repo(args)
        def command(self, args, *, request_cancel_event=None):
            entered.set()
            observed.append(request_cancel_event is not None and request_cancel_event.wait(8))
            return {"success": False, "cancelled": True, "exit_code": None}

    root = init_repo(tmp_path)
    state = tmp_path / "state"
    services = CancellableValidation("--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n")
    wo = WorkOrchestrator(config(tmp_path), state, services, None, FakeLeases(), FakeArtifacts())
    try:
        submitted = wo.submit({"root": str(root), "task": "replace old with new", "mode": "bounded",
                               "acceptance_criteria": ["a.txt contains new"], "allowed_paths": ["a.txt"],
                               "approved_commands": ["git diff --check"], "budget": {"max_steps": 8, "max_seconds": 60},
                               "permissions": {"edit": True, "tests": True, "build": True}})
        assert entered.wait(20)
        script = ("import sys,threading; from pathlib import Path; from local_ai_hub.work_orchestrator import WorkOrchestrator; "
                  "w=object.__new__(WorkOrchestrator); w.path=Path(sys.argv[1])/'work_orders.sqlite3'; "
                  "w._lock=threading.RLock(); w._active_cancellations={}; w._waiters={}; w._wake=threading.Event(); "
                  "r=w.cancel(sys.argv[2]); print(r); sys.exit(0 if r.get('success') is True else 1)")
        child = subprocess.run([sys.executable, "-c", script, str(state), submitted["work_id"]],
                               capture_output=True, text=True, timeout=10, **hidden_run_kwargs())
        assert child.returncode == 0, (child.stdout, child.stderr)
        result = wait_terminal(wo, submitted["work_id"], timeout=60)
        assert observed == [True]
        assert result["status"] == "cancelled"
    finally:
        wo.close()


@pytest.mark.parametrize("automatic_recovery", [False, True], ids=["restart", "timer"])
def test_cancel_recovers_after_terminal_state_write_failure(tmp_path, monkeypatch, automatic_recovery):
    from test_work_orchestrator import FakeArtifacts, FakeLeases, FakeServices, config, init_repo, wait_terminal

    entered = threading.Event()
    terminal_attempted = threading.Event()
    recovery_scheduled = threading.Event()

    class CancellableValidation(FakeServices):
        def delegate_repo(self, args, **kwargs):
            return super().delegate_repo(args)

        def command(self, args, *, request_cancel_event=None):
            entered.set()
            assert request_cancel_event.wait(10)
            return {"success": False, "cancelled": True, "exit_code": None}

    root = init_repo(tmp_path)
    state = tmp_path / "state"
    services = CancellableValidation("--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n")
    artifacts = FakeArtifacts()
    wo = WorkOrchestrator(config(tmp_path), state, services, None, FakeLeases(), artifacts)
    original_terminal = wo._set_terminal_if_active

    def fail_first_terminal(*args, **kwargs):
        terminal_attempted.set()
        raise OSError("simulated state write interruption")

    monkeypatch.setattr(wo, "_set_terminal_if_active", fail_first_terminal)
    original_schedule = wo._schedule_recovery_retry
    def schedule_recovery():
        if automatic_recovery:
            original_schedule()
        recovery_scheduled.set()
    monkeypatch.setattr(wo, "_schedule_recovery_retry", schedule_recovery)
    try:
        submitted = wo.submit({"root": str(root), "task": "replace old with new", "mode": "bounded",
                               "acceptance_criteria": ["a.txt contains new"], "allowed_paths": ["a.txt"],
                               "approved_commands": ["git diff --check"], "budget": {"max_steps": 8, "max_seconds": 60},
                               "permissions": {"edit": True, "tests": True, "build": True}})
        assert entered.wait(20)
        assert wo.cancel(submitted["work_id"])["success"] is True
        assert terminal_attempted.wait(10)
        assert recovery_scheduled.wait(5)
        assert (root / "a.txt").read_text(encoding="utf-8").strip() == "old"
        if automatic_recovery:
            monkeypatch.setattr(wo, "_set_terminal_if_active", original_terminal)
            result = wait_terminal(wo, submitted["work_id"], timeout=45)
            assert result["status"] == "cancelled", result
            assert (root / "a.txt").read_text(encoding="utf-8").strip() == "old"
    finally:
        monkeypatch.setattr(wo, "_set_terminal_if_active", original_terminal)
        wo.close()

    if automatic_recovery:
        return
    recovered = WorkOrchestrator(config(tmp_path), state, services, None, FakeLeases(), artifacts)
    try:
        result = wait_terminal(recovered, submitted["work_id"], timeout=60)
        assert result["status"] == "cancelled", result
        assert (root / "a.txt").read_text(encoding="utf-8").strip() == "old"
    finally:
        recovered.close()


def test_repeated_validation_cannot_exceed_command_budget(tmp_path):
    import json
    from test_work_orchestrator import FakeArtifacts, FakeLeases, FakeServices, config, init_repo, wait_terminal

    class RepeatedValidation(FakeServices):
        def __init__(self):
            super().__init__("")
            self.command_count = 0

        def delegate_repo(self, args, **kwargs):
            self.delegate_calls += 1
            plan = {"steps": [
                {"id": "s1", "kind": "validate", "task": "first", "depends_on": []},
                {"id": "s2", "kind": "validate", "task": "second", "depends_on": ["s1"]},
            ], "validation_commands": ["git diff --check"]}
            return {"success": True, "text": json.dumps(plan)}

        def command(self, args, *, request_cancel_event=None):
            self.command_count += 1
            return {"success": True, "exit_code": 0}

    root = init_repo(tmp_path)
    services = RepeatedValidation()
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", services, None, FakeLeases(), FakeArtifacts())
    try:
        submitted = wo.submit({
            "root": str(root), "task": "validate", "mode": "bounded",
            "acceptance_criteria": ["validation succeeded"],
            "permissions": {"edit": False, "tests": True, "build": True},
            "allowed_paths": ["a.txt"], "approved_commands": ["git diff --check"],
            "budget": {"max_steps": 8, "max_seconds": 60, "max_commands": 1},
        })
        assert submitted["success"] is True
        assert wait_terminal(wo, submitted["work_id"])["status"] == "failed"
        assert services.command_count == 1
    finally:
        wo.close()


def test_unbound_bounded_work_returns_test_evidence_without_fabricating_task_receipt(tmp_path):
    import json
    from test_work_orchestrator import FakeArtifacts, FakeLeases, FakeServices, config, init_repo, wait_terminal

    class UnboundWork(FakeServices):
        def __init__(self):
            super().__init__("--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n")

        def delegate_repo(self, args, **kwargs):
            result = super().delegate_repo(args)
            if self.delegate_calls == 1:
                plan = json.loads(result["text"])
                result["text"] = json.dumps(plan)
            return result

        def second_opinion(self, args, **kwargs):
            return {"success": True, "text": json.dumps({
                "passed": True, "summary": "local check",
                "criteria": [{"criterion": "tests pass", "passed": True}], "risks": [],
            })}

        def command(self, args, *, request_cancel_event=None):
            return {"success": True, "exit_code": 0, "execution_id": "cmd1", "repository_revision": "revision1"}

    root = init_repo(tmp_path)
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", UnboundWork(), None, FakeLeases(), FakeArtifacts())
    try:
        submitted = wo.submit({
            "root": str(root), "task": "replace old with new", "mode": "bounded",
            "acceptance_criteria": ["tests pass"],
            "permissions": {"edit": True, "tests": True, "build": True},
            "allowed_paths": ["a.txt"], "approved_commands": ["git diff --check"],
            "budget": {"max_steps": 8, "max_seconds": 60},
        })
        result = wait_terminal(wo, submitted["work_id"], timeout=60)
        assert result["status"] == "needs_agent", result
        assert result["requires_primary_review"] is True
        assert result["verification_receipts"] == []
        assert result["verification"]["receipt_gate"]["complete"] is False
        assert (root / "a.txt").read_text().strip() == "new"
    finally:
        wo.close()


def test_bound_bounded_work_does_not_synthesize_broker_receipt(tmp_path):
    import json
    from test_work_orchestrator import (
        FakeArtifacts, FakeLeases, FakeServices, config, init_repo,
        owned_verification_context, wait_terminal,
    )

    class NoBrokerReceipt(FakeServices):
        def delegate_repo(self, args, **kwargs):
            return super().delegate_repo(args)

        def second_opinion(self, args, **kwargs):
            return {"success": True, "text": json.dumps({
                "passed": True, "summary": "local check",
                "criteria": [{"criterion": "tests pass", "passed": True}], "risks": [],
            })}

        def command(self, args, *, request_cancel_event=None):
            return {"success": True, "exit_code": 0, "execution_id": "not-a-broker-receipt", "repository_revision": "rev"}

    root = init_repo(tmp_path)
    artifacts = FakeArtifacts()
    verification = owned_verification_context(tmp_path, root, artifacts, "bounded-task")
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", NoBrokerReceipt(
        "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"), None, FakeLeases(), artifacts,
        verification_store=verification)
    try:
        submitted = wo.submit({
            "root": str(root), "task": "replace old with new", "task_id": "bounded-task", "mode": "bounded",
            "acceptance_criteria": ["tests pass"], "allowed_paths": ["a.txt"],
            "approved_commands": ["python -m pytest"], "budget": {"max_steps": 8, "max_seconds": 60},
            "permissions": {"edit": True, "tests": True, "build": True},
        })
        result = wait_terminal(wo, submitted["work_id"], timeout=60)
        assert result["status"] == "needs_agent", result
        assert result["verification_receipts"] == []
        assert result["verification"]["receipt_gate"]["complete"] is False
        assert not any(item["kind"] == "command_verification" for item in artifacts.data.values())
        assert (root / "a.txt").read_text().strip() == "new"
    finally:
        wo.close()


def test_bounded_handoff_preserves_actual_command_output_evidence(tmp_path):
    import json
    from test_work_orchestrator import FakeArtifacts, FakeLeases, FakeServices, config, init_repo, wait_terminal

    class OutputServices(FakeServices):
        def delegate_repo(self, args, **kwargs):
            return super().delegate_repo(args)
        def second_opinion(self, args, **kwargs):
            return super().second_opinion(args)
        def command(self, args, *, request_cancel_event=None):
            return {"success": True, "exit_code": 0, "stdout": "one test passed", "stderr": "",
                    "output_artifact_id": "actual-output", "output_truncated": True,
                    "cache_hit": True, "coalesced": False}

    root = init_repo(tmp_path)
    artifacts = FakeArtifacts()
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", OutputServices(
        "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"), None, FakeLeases(), artifacts)
    try:
        submitted = wo.submit({"root": str(root), "task": "replace old with new", "mode": "bounded",
                               "acceptance_criteria": ["a.txt contains new"], "allowed_paths": ["a.txt"],
                               "approved_commands": ["git diff --check"], "budget": {"max_steps": 8, "max_seconds": 60},
                               "permissions": {"edit": True, "tests": True, "build": True}})
        result = wait_terminal(wo, submitted["work_id"], timeout=60)
        assert result["status"] == "needs_agent", result
        report = json.loads(artifacts.data[result["artifact_id"]]["text"])
        validation = report["validation"][0]
        assert validation["output_artifact_id"] == "actual-output"
        assert validation["stdout_preview"] == "one test passed"
        assert validation["output_truncated"] is True
        assert validation["cache_hit"] is True
        assert validation["coalesced"] is False
    finally:
        wo.close()


@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("command", ["git diff --check", "python -m pytest -q test_small.py"])
def test_bounded_work_executes_approved_command_through_real_broker(tmp_path, bound, command):
    import json
    import subprocess
    from local_ai_hub.commands import CommandBroker
    from local_ai_hub.services import LocalAIServices
    from types import SimpleNamespace
    from test_work_orchestrator import (FakeArtifacts, FakeLeases, FakeServices, config, init_repo,
                                        owned_verification_context, wait_terminal)

    root = init_repo(tmp_path)
    (root / "test_small.py").write_text("def test_small():\n    assert True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "test_small.py"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=T", "-c", "user.email=t@e", "commit", "-qm", "fixture"], check=True)
    cfg = config(tmp_path)
    cfg["server"] = {"state_dir": str(tmp_path / "broker-state")}
    cfg["security"] = {"allowed_roots": [str(root)]}
    broker = CommandBroker(cfg)

    class BrokerServices(FakeServices):
        def __init__(self):
            super().__init__("--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n")
            self.broker_results = []
            self.command_requests = []
            self.denied_probes = []

        def delegate_repo(self, args, **kwargs):
            return super().delegate_repo(args)

        def second_opinion(self, args, **kwargs):
            return super().second_opinion(args)

        def command(self, args, *, request_cancel_event=None):
            self.command_requests.append(dict(args))
            self.denied_probes.append(broker.run(
                args["command"], args["cwd"], task_id="foreign-task", record_verification=False,
                _work_attempt_fence=args["writer_fence"], _work_order_id=args["work_id"],
            ))
            self.denied_probes.append(broker.run(
                "git status", args["cwd"], task_id=args.get("task_id", ""), record_verification=False,
                _work_attempt_fence=args["writer_fence"], _work_order_id=args["work_id"],
            ))
            adapter = SimpleNamespace(commands=broker, agent_state=None,
                                      _authorize_command_action=lambda *a, **kw: None)
            result = LocalAIServices.command(adapter, args, request_cancel_event=request_cancel_event)
            self.broker_results.append(result)
            return result

    services = BrokerServices()
    artifacts = FakeArtifacts()
    verification = owned_verification_context(tmp_path, root, artifacts, "agent-task") if bound else None
    wo = WorkOrchestrator(cfg, tmp_path / "work-state", services, None, FakeLeases(), artifacts,
                          verification_store=verification)
    broker.set_fencing_lease_store(wo.fencing_store)
    broker.set_bounded_work_authorizer(wo.authorize_bounded_command)
    try:
        submitted = wo.submit({
            "root": str(root), "task": "replace old with new", "mode": "bounded",
            "acceptance_criteria": ["a.txt contains new"], "allowed_paths": ["a.txt"],
            "approved_commands": [command], "budget": {"max_steps": 8, "max_seconds": 60},
            "permissions": {"edit": True, "tests": True, "build": True},
            **({"task_id": "agent-task"} if bound else {}),
        })
        result = wait_terminal(wo, submitted["work_id"], timeout=30)
        assert services.broker_results and services.broker_results[0]["success"] is True, services.broker_results
        assert result["status"] == "needs_agent", (result, services.broker_results)
        assert services.broker_results[0]["exit_code"] == 0
        report = json.loads(artifacts.data[result["artifact_id"]]["text"])
        recorded = report["validation"][0]
        assert recorded.get("output_artifact_id") == services.broker_results[0].get("output_artifact_id")
        if "cache_hit" in services.broker_results[0]:
            assert recorded["cache_hit"] == services.broker_results[0]["cache_hit"]
        assert all(item["success"] is False for item in services.denied_probes)
        assert services.command_requests[0]["work_id"] == submitted["work_id"]
        assert services.command_requests[0].get("task_id", "") == ("agent-task" if bound else "")
        assert not wo.authorize_bounded_command(submitted["work_id"], "agent-task" if bound else "", str(root), command)
        assert result["requires_primary_review"] is True
        assert (root / "a.txt").read_text().strip() == "new"
    finally:
        wo.close()


def test_broker_work_order_identity_requires_matching_current_fence_and_root(tmp_path):
    from local_ai_hub.commands import CommandBroker
    from local_ai_hub.work_fencing import FencingLeaseStore
    from test_work_orchestrator import init_repo

    root = init_repo(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    cfg = {"server": {"state_dir": str(tmp_path / "broker-state")},
           "security": {"allowed_roots": [str(tmp_path)]}}
    broker = CommandBroker(cfg)
    store = FencingLeaseStore(tmp_path / "fencing.sqlite3")
    broker.set_fencing_lease_store(store)
    attempt = store.claim_attempt(str(root), "work-1", "worker-1", ttl_seconds=30, coordination_id="repo-1")
    cases = [
        {"cwd": root, "_work_order_id": "other-work", "_work_attempt_fence": attempt},
        {"cwd": other, "_work_order_id": "work-1", "_work_attempt_fence": attempt},
        {"cwd": root, "_work_order_id": "work-1"},
    ]
    for case in cases:
        result = broker.run("git diff --check", str(case.pop("cwd")), task_id="agent-task", **case)
        assert result["success"] is False, result
        assert result["failure_kind"] == "work_attempt_fence_invalid"
    result = broker.run("git diff --check", str(root), task_id="agent-task",
                        _work_order_id="work-1", _work_attempt_fence=attempt)
    assert result["success"] is False
    assert "authorize" in result["error"]
    assert store.release_attempt(attempt) is True
    result = broker.run("git diff --check", str(root), task_id="agent-task",
                        _work_order_id="work-1", _work_attempt_fence=attempt)
    assert result["success"] is False
    assert result["failure_kind"] == "work_attempt_fence_invalid"


def test_cancelling_bounded_work_stops_real_validation_process(tmp_path):
    import subprocess
    import time
    from types import SimpleNamespace
    from local_ai_hub.commands import CommandBroker
    from local_ai_hub.services import LocalAIServices
    from test_work_orchestrator import FakeArtifacts, FakeLeases, FakeServices, config, init_repo, wait_terminal

    root = init_repo(tmp_path)
    (root / "test_wait.py").write_text(
        "import time\nfrom pathlib import Path\ndef test_wait():\n"
        "    Path('started.flag').write_text('started')\n    time.sleep(30)\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "test_wait.py"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=T", "-c", "user.email=t@e", "commit", "-qm", "fixture"], check=True)
    cfg = config(tmp_path)
    cfg["server"] = {"state_dir": str(tmp_path / "broker-state")}
    cfg["security"] = {"allowed_roots": [str(root)]}
    broker = CommandBroker(cfg)

    class BrokerServices(FakeServices):
        def __init__(self):
            super().__init__("--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n")
            self.broker_results = []
        def delegate_repo(self, args, **kwargs):
            return super().delegate_repo(args)
        def command(self, args, *, request_cancel_event=None):
            adapter = SimpleNamespace(commands=broker, agent_state=None,
                                      _authorize_command_action=lambda *a, **kw: None)
            result = LocalAIServices.command(adapter, args, request_cancel_event=request_cancel_event)
            self.broker_results.append(result)
            return result

    services = BrokerServices()
    wo = WorkOrchestrator(cfg, tmp_path / "work-state", services, None, FakeLeases(), FakeArtifacts())
    broker.set_fencing_lease_store(wo.fencing_store)
    broker.set_bounded_work_authorizer(wo.authorize_bounded_command)
    try:
        submitted = wo.submit({"root": str(root), "task": "replace old with new", "mode": "bounded",
                               "acceptance_criteria": ["a.txt contains new"], "allowed_paths": ["a.txt"],
                               "approved_commands": ["python -m pytest -q test_wait.py"],
                               "budget": {"max_steps": 8, "max_seconds": 60},
                               "permissions": {"edit": True, "tests": True, "build": True}})
        deadline = time.monotonic() + 10
        while not (root / "started.flag").exists() and time.monotonic() < deadline:
            threading.Event().wait(0.05)
        assert (root / "started.flag").exists(), "validation did not start"
        assert wo.cancel(submitted["work_id"])["success"] is True
        result = wait_terminal(wo, submitted["work_id"], timeout=10)
        assert result["status"] == "cancelled"
        assert services.broker_results and services.broker_results[0].get("cancelled") is True
        assert (root / "a.txt").read_text().strip() == "old"
    finally:
        wo.close()
