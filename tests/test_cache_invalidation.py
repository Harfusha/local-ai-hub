from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from local_ai_hub import cache as cache_module
from local_ai_hub.cache import SQLiteCache, TieredCache


def _cache(root: Path, namespace: str = "command:success") -> TieredCache:
    return TieredCache(SQLiteCache(root / "cache.sqlite3", namespace), l1_entries=8, l1_ttl_seconds=300)


def test_delete_failure_quarantines_stale_l1_and_l2_for_another_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _cache(tmp_path)
    second = _cache(tmp_path)
    first.set("key", {"state": "before rollback"})
    assert second.get("key") == {"state": "before rollback"}

    def busy(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cache_module, "retry_busy", busy)
    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        first.delete("key")

    assert second.get("key") is None


def test_delete_failure_quarantine_is_visible_to_another_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _cache(tmp_path, "command:failure")
    first.set("key", "old failure")

    def busy(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cache_module, "retry_busy", busy)
    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        first.delete("key")

    source_root = str(Path(__file__).resolve().parents[1] / "src")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    script = (
        "import json, sys; from pathlib import Path; "
        "from local_ai_hub.cache import SQLiteCache, TieredCache; "
        "c=TieredCache(SQLiteCache(Path(sys.argv[1])/'cache.sqlite3','command:failure')); "
        "print(json.dumps(c.get('key')))"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert json.loads(result.stdout) is None


def test_successful_delete_invalidates_another_instances_l1(tmp_path: Path) -> None:
    first = _cache(tmp_path, "command:suppression")
    second = _cache(tmp_path, "command:suppression")
    first.set("key", "old")
    assert second.get("key") == "old"

    first.delete("key")

    assert second.get("key") is None


def test_primary_poison_publication_failure_uses_shared_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _cache(tmp_path, "command:success")
    first.set("key", "stale after unpublished invalidation")

    def fail_publication(*_args, **_kwargs):
        raise OSError("coordination sidecar write failed")

    assert first._coordinator is not None
    monkeypatch.setattr(first._coordinator, "write_locked", fail_publication)
    first.delete("key")

    source_root = str(Path(__file__).resolve().parents[1] / "src")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    script = (
        "import json, sys; from pathlib import Path; "
        "from local_ai_hub.cache import SQLiteCache, TieredCache; "
        "c=TieredCache(SQLiteCache(Path(sys.argv[1])/'cache.sqlite3','command:success')); "
        "print(json.dumps(c.get('key')))"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert json.loads(result.stdout) is None


def test_clear_primary_publication_failure_invalidates_other_instance_l1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _cache(tmp_path, "command:success")
    second = _cache(tmp_path, "command:success")
    first.set("key", "stale")
    assert second.get("key") == "stale"
    assert first._coordinator is not None

    def fail_publication(*_args, **_kwargs):
        raise OSError("coordination sidecar write failed")

    monkeypatch.setattr(first._coordinator, "write_locked", fail_publication)
    assert first.clear() == 1
    assert second.get("key") is None


def test_secondary_process_does_not_serve_stale_l1_or_l2_after_primary_marker_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _cache(tmp_path, "command:failure")
    first.set("key", "old")

    source_root = str(Path(__file__).resolve().parents[1] / "src")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    script = (
        "import json, sys, time\n"
        "from pathlib import Path\n"
        "from local_ai_hub.cache import SQLiteCache, TieredCache\n"
        "root=Path(sys.argv[1])\n"
        "c=TieredCache(SQLiteCache(root/'cache.sqlite3','command:failure'))\n"
        "print(json.dumps(c.get('key')), flush=True)\n"
        "(root/'reader-ready').write_text('ready')\n"
        "deadline=time.monotonic()+10\n"
        "while not (root/'reader-go').exists() and time.monotonic()<deadline:\n"
        "    time.sleep(.01)\n"
        "print(json.dumps(c.get('key')), flush=True)\n"
    )
    reader = subprocess.Popen(
        [sys.executable, "-B", "-c", script, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert reader.stdout is not None
        initial_value = reader.stdout.readline().strip()
        assert initial_value == '"old"'
        deadline = time.monotonic() + 5
        while not (tmp_path / "reader-ready").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert (tmp_path / "reader-ready").exists()

        def busy(*_args, **_kwargs):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(cache_module, "retry_busy", busy)
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            first.delete("key")
        assert first._coordinator is not None
        first._coordinator.state_path.unlink()
        (tmp_path / "reader-go").write_text("read", encoding="utf-8")

        stdout, stderr = reader.communicate(timeout=15)
        assert reader.returncode == 0, stderr
        assert [initial_value, *stdout.splitlines()] == ['"old"', "null"]
    finally:
        if reader.poll() is None:
            reader.terminate()
            reader.wait(timeout=5)


def test_successful_delete_is_visible_to_another_process(tmp_path: Path) -> None:
    first = _cache(tmp_path, "command:success")
    first.set("key", "old")
    first.delete("key")

    source_root = str(Path(__file__).resolve().parents[1] / "src")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    script = (
        "import json, sys; from pathlib import Path; "
        "from local_ai_hub.cache import SQLiteCache, TieredCache; "
        "c=TieredCache(SQLiteCache(Path(sys.argv[1])/'cache.sqlite3','command:success')); "
        "print(json.dumps(c.get('key')))"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert json.loads(result.stdout) is None


def test_poisoned_namespace_recovers_by_clearing_l2_before_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _cache(tmp_path, "command:failure")
    second = _cache(tmp_path, "command:failure")
    first.set("key", "old")
    assert second.get("key") == "old"

    def busy(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cache_module, "retry_busy", busy)
    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        first.delete("key")
    monkeypatch.undo()

    assert second.get("key") is None
    second.set("key", "fresh")
    assert first.get("key") == "fresh"


def test_clear_failure_keeps_other_instance_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _cache(tmp_path, "command:failure")
    second = _cache(tmp_path, "command:failure")
    first.set("key", "old")
    assert second.get("key") == "old"

    def busy(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cache_module, "retry_busy", busy)
    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        first.clear()

    assert second.get("key") is None


def test_reader_waits_for_cross_instance_delete_and_observes_failure_quarantine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _cache(tmp_path, "command:success")
    second = _cache(tmp_path, "command:success")
    first.set("key", "old")
    assert second.get("key") == "old"
    entered = threading.Event()
    release = threading.Event()
    reader_done = threading.Event()
    observed: list[object] = []

    def busy_after_pause(*_args, **_kwargs):
        entered.set()
        assert release.wait(2)
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cache_module, "retry_busy", busy_after_pause)

    def delete() -> None:
        with pytest.raises(sqlite3.OperationalError):
            first.delete("key")

    def read() -> None:
        observed.append(second.get("key"))
        reader_done.set()

    delete_thread = threading.Thread(target=delete)
    delete_thread.start()
    assert entered.wait(2)
    reader_thread = threading.Thread(target=read)
    reader_thread.start()
    assert not reader_done.wait(0.05)
    release.set()
    delete_thread.join(2)
    reader_thread.join(2)

    assert not delete_thread.is_alive()
    assert not reader_thread.is_alive()
    assert observed == [None]


def test_other_process_reader_waits_for_delete_and_observes_poison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _cache(tmp_path, "command:failure")
    first.set("key", "old")
    entered = threading.Event()
    release = threading.Event()

    def busy_after_pause(*_args, **_kwargs):
        entered.set()
        assert release.wait(3)
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cache_module, "retry_busy", busy_after_pause)
    delete_errors: list[BaseException] = []

    def delete() -> None:
        try:
            first.delete("key")
        except BaseException as exc:
            delete_errors.append(exc)

    delete_thread = threading.Thread(target=delete)
    delete_thread.start()
    assert entered.wait(2)

    source_root = str(Path(__file__).resolve().parents[1] / "src")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    script = (
        "import json, sys; from pathlib import Path; "
        "from local_ai_hub.cache import SQLiteCache, TieredCache; "
        "c=TieredCache(SQLiteCache(Path(sys.argv[1])/'cache.sqlite3','command:failure')); "
        "(Path(sys.argv[1])/'reader-ready').write_text('ready'); "
        "print(json.dumps(c.get('key')), flush=True)"
    )
    reader = subprocess.Popen(
        [sys.executable, "-B", "-c", script, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        ready_path = tmp_path / "reader-ready"
        deadline = time.monotonic() + 5
        while not ready_path.exists() and reader.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready_path.exists()
        time.sleep(0.1)
        assert reader.poll() is None
    except BaseException:
        release.set()
        reader.kill()
        reader.communicate(timeout=5)
        delete_thread.join(3)
        raise
    release.set()
    stdout, stderr = reader.communicate(timeout=10)
    delete_thread.join(3)

    assert not delete_thread.is_alive()
    assert delete_errors and isinstance(delete_errors[0], sqlite3.OperationalError)
    assert reader.returncode == 0, stderr
    assert json.loads(stdout.strip().splitlines()[-1]) is None


def test_concurrent_set_then_delete_cannot_resurrect_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _cache(tmp_path, "command:success")
    second = _cache(tmp_path, "command:success")
    first.set("key", "old")
    set_entered = threading.Event()
    release_set = threading.Event()
    delete_done = threading.Event()
    errors: list[BaseException] = []
    original_set = first.l2.set

    def paused_set(key: str, value: object) -> None:
        set_entered.set()
        assert release_set.wait(3)
        original_set(key, value)

    monkeypatch.setattr(first.l2, "set", paused_set)

    def set_fresh() -> None:
        try:
            first.set("key", "fresh")
        except BaseException as exc:
            errors.append(exc)

    def delete() -> None:
        try:
            second.delete("key")
        except BaseException as exc:
            errors.append(exc)
        finally:
            delete_done.set()

    setter = threading.Thread(target=set_fresh)
    setter.start()
    assert set_entered.wait(2)
    deleter = threading.Thread(target=delete)
    deleter.start()
    assert not delete_done.wait(0.05)
    release_set.set()
    setter.join(3)
    deleter.join(3)

    assert not setter.is_alive()
    assert not deleter.is_alive()
    assert errors == []
    assert second.get("key") is None


def test_coordination_lock_timeout_clears_l1_and_returns_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _cache(tmp_path, "command:success")
    second = _cache(tmp_path, "command:success")
    first.set("key", "stale")
    assert second.get("key") == "stale"
    assert second._coordinator is not None

    @contextmanager
    def timed_out():
        raise TimeoutError("command-cache coordination lock timed out")
        yield

    monkeypatch.setattr(second._coordinator, "locked", timed_out)
    assert second.get("key") is None
    assert second.l1.get("key") is None


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX advisory flock")
def test_posix_lock_timeout_clears_stale_l1_and_returns_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _cache(tmp_path, "command:success")
    second = _cache(tmp_path, "command:success")
    first.set("key", "stale")
    assert second.get("key") == "stale"
    assert first._coordinator is not None
    monkeypatch.setattr(cache_module, "_COMMAND_CACHE_LOCK_TIMEOUT_SECONDS", 0.15)

    ready = tmp_path / "lock-ready"
    release = tmp_path / "lock-release"
    script = (
        "import fcntl, sys, time; from pathlib import Path; "
        "lock=Path(sys.argv[1]); ready=Path(sys.argv[2]); release=Path(sys.argv[3]); "
        "stream=lock.open('r+b'); fcntl.flock(stream.fileno(), fcntl.LOCK_EX); "
        "ready.write_text('ready'); deadline=time.monotonic()+5; "
        "\nwhile not release.exists() and time.monotonic()<deadline: time.sleep(0.01)\n"
        "fcntl.flock(stream.fileno(), fcntl.LOCK_UN); stream.close()"
    )
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    holder = subprocess.Popen(
        [
            sys.executable,
            "-B",
            "-c",
            script,
            str(first._coordinator.lock_path),
            str(ready),
            str(release),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    observed: list[object] = []
    reader: threading.Thread | None = None
    elapsed = 0.0
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and holder.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), holder.communicate(timeout=2)[1]
        started = time.monotonic()
        reader = threading.Thread(target=lambda: observed.append(second.get("key")))
        reader.start()
        reader.join(1)
        elapsed = time.monotonic() - started
    finally:
        release.touch()
        holder.communicate(timeout=5)
        if reader is not None:
            reader.join(2)

    assert reader is not None and not reader.is_alive()
    assert elapsed < 1
    assert observed == [None]
    assert second.l1.get("key") is None


def test_both_sidecar_atomic_replacements_failing_keep_cross_process_l1_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _cache(tmp_path, "command:failure")
    first.set("key", "old")
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    script = (
        "import json, sys, time\n"
        "from pathlib import Path\n"
        "from local_ai_hub.cache import SQLiteCache, TieredCache\n"
        "root=Path(sys.argv[1])\n"
        "c=TieredCache(SQLiteCache(root/'cache.sqlite3','command:failure'))\n"
        "print(json.dumps(c.get('key')), flush=True)\n"
        "(root/'reader-ready').write_text('ready')\n"
        "deadline=time.monotonic()+10\n"
        "while not (root/'reader-go').exists() and time.monotonic()<deadline: time.sleep(.01)\n"
        "print(json.dumps(c.get('key')), flush=True)\n"
    )
    reader = subprocess.Popen(
        [sys.executable, "-B", "-c", script, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1], env=environment,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert reader.stdout is not None
        assert reader.stdout.readline().strip() == '\"old\"'
        deadline = time.monotonic() + 5
        while not (tmp_path / "reader-ready").exists() and time.monotonic() < deadline: time.sleep(.01)
        assert (tmp_path / "reader-ready").exists()
        assert first._coordinator is not None
        replace = cache_module.os.replace
        def fail_sidecar_replace(source, destination):
            if Path(destination).parent == first._coordinator.directory:
                raise OSError("coordination sidecar replace failed")
            return replace(source, destination)
        monkeypatch.setattr(cache_module.os, "replace", fail_sidecar_replace)
        assert first.delete("key") is True
        (tmp_path / "reader-go").write_text("read", encoding="utf-8")
        stdout, stderr = reader.communicate(timeout=15)
        assert reader.returncode == 0, stderr
        assert stdout.splitlines() == ["null"]
    finally:
        if reader.poll() is None:
            reader.terminate()
            reader.wait(timeout=5)
