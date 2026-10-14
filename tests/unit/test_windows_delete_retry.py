from __future__ import annotations

import math

import pytest

from local_ai_hub import process_utils


def _winerror5(path) -> PermissionError:
    error = PermissionError(5, "Access is denied", str(path))
    error.winerror = 5
    return error


def test_safe_unlink_retries_transient_winerror5_and_unlinks_real_file(tmp_path, monkeypatch):
    path = tmp_path / "locked.tmp"
    path.write_text("owned", encoding="utf-8")
    original_unlink = type(path).unlink
    attempts = []
    delays = []

    def unlink(candidate, *args, **kwargs):
        attempts.append(candidate)
        if len(attempts) < 3:
            raise _winerror5(candidate)
        return original_unlink(candidate, *args, **kwargs)

    monkeypatch.setattr(type(path), "unlink", unlink)
    monkeypatch.setattr(process_utils.time, "sleep", delays.append)

    process_utils.safe_unlink(path, max_attempts=4, delay=0.1)

    assert attempts == [path, path, path]
    assert delays == [0.1, 0.2]
    assert not path.exists()


def test_safe_unlink_first_attempt_success_does_not_sleep(tmp_path, monkeypatch):
    path = tmp_path / "ready.tmp"
    path.write_text("owned", encoding="utf-8")
    delays = []
    monkeypatch.setattr(process_utils.time, "sleep", delays.append)

    process_utils.safe_unlink(path)

    assert not path.exists()
    assert delays == []


def test_safe_unlink_exhausts_exact_attempts_and_rethrows_winerror5(tmp_path, monkeypatch):
    path = tmp_path / "persistent.tmp"
    path.write_text("owned", encoding="utf-8")
    attempts = []
    delays = []

    def unlink(candidate, *args, **kwargs):
        attempts.append(candidate)
        raise _winerror5(candidate)

    monkeypatch.setattr(type(path), "unlink", unlink)
    monkeypatch.setattr(process_utils.time, "sleep", delays.append)

    with pytest.raises(PermissionError) as caught:
        process_utils.safe_unlink(path, max_attempts=3, delay=0.025)

    assert caught.value.winerror == 5
    assert attempts == [path, path, path]
    assert delays == [0.025, 0.05]
    assert path.read_text(encoding="utf-8") == "owned"


def test_safe_unlink_does_not_retry_unrelated_permission_error(tmp_path, monkeypatch):
    path = tmp_path / "other.tmp"
    path.write_text("owned", encoding="utf-8")
    error = PermissionError("different failure")
    attempts = []
    delays = []

    def unlink(candidate, *args, **kwargs):
        attempts.append(candidate)
        raise error

    monkeypatch.setattr(type(path), "unlink", unlink)
    monkeypatch.setattr(process_utils.time, "sleep", delays.append)

    with pytest.raises(PermissionError) as caught:
        process_utils.safe_unlink(path)

    assert caught.value is error
    assert attempts == [path]
    assert delays == []
    assert path.read_text(encoding="utf-8") == "owned"


def test_safe_unlink_preserves_replacement_created_during_retry(tmp_path, monkeypatch):
    path = tmp_path / "replace.tmp"
    original = tmp_path / "original.tmp"
    path.write_text("original", encoding="utf-8")
    original_unlink = type(path).unlink
    calls = []
    delays = []

    def unlink(candidate, *args, **kwargs):
        calls.append(candidate)
        if len(calls) == 1:
            path.rename(original)
            path.write_text("replacement", encoding="utf-8")
            raise _winerror5(candidate)
        return original_unlink(candidate, *args, **kwargs)

    monkeypatch.setattr(type(path), "unlink", unlink)
    monkeypatch.setattr(process_utils.time, "sleep", delays.append)

    with pytest.raises(PermissionError):
        process_utils.safe_unlink(path, max_attempts=3, delay=0.1)

    assert calls == [path]
    assert delays == []
    assert path.read_text(encoding="utf-8") == "replacement"
    assert original.read_text(encoding="utf-8") == "original"


def test_safe_unlink_preserves_replacement_during_backoff(tmp_path, monkeypatch):
    path = tmp_path / "backoff-replace.tmp"
    original = tmp_path / "backoff-original.tmp"
    path.write_text("original", encoding="utf-8")
    calls = []

    def unlink(candidate, *args, **kwargs):
        calls.append(candidate)
        raise _winerror5(candidate)

    def replace_during_sleep(_seconds):
        path.rename(original)
        path.write_text("replacement", encoding="utf-8")

    monkeypatch.setattr(type(path), "unlink", unlink)
    monkeypatch.setattr(process_utils.time, "sleep", replace_during_sleep)

    with pytest.raises(PermissionError):
        process_utils.safe_unlink(path, max_attempts=3, delay=0.1)

    assert calls == [path]
    assert path.read_text(encoding="utf-8") == "replacement"
    assert original.read_text(encoding="utf-8") == "original"


@pytest.mark.parametrize("attempts", [0, -1, 11, True])
def test_safe_unlink_rejects_invalid_attempt_limits(tmp_path, attempts):
    with pytest.raises(ValueError):
        process_utils.safe_unlink(tmp_path / "missing", max_attempts=attempts)


@pytest.mark.parametrize("delay", [-0.1, math.inf, math.nan, True, 10**1000])
def test_safe_unlink_rejects_invalid_delays(tmp_path, delay):
    with pytest.raises(ValueError):
        process_utils.safe_unlink(tmp_path / "missing", delay=delay)


def test_safe_unlink_rechecks_deadline_after_identity_stat(tmp_path, monkeypatch):
    path = tmp_path / "locked.txt"
    path.write_text("original", encoding="utf-8")
    now = [0.0]
    stat_calls = []
    unlink_calls = []
    sleeps = []
    original_stat = process_utils.Path.stat

    def delayed_retry_stat(candidate, *args, **kwargs):
        result = original_stat(candidate, *args, **kwargs)
        if candidate == path:
            stat_calls.append(candidate)
            if len(stat_calls) == 3:
                now[0] += 0.2
        return result

    def locked(candidate):
        unlink_calls.append(candidate)
        raise _winerror5(candidate)

    def fake_sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(process_utils.Path, "stat", delayed_retry_stat)
    monkeypatch.setattr(type(path), "unlink", locked)
    monkeypatch.setattr(process_utils.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(process_utils.time, "sleep", fake_sleep)

    with pytest.raises(PermissionError) as caught:
        process_utils.safe_unlink(path, max_attempts=3, delay=4.9)

    assert caught.value.winerror == 5
    assert unlink_calls == [path]
    assert sleeps == [4.9]
    assert len(stat_calls) == 3
    assert path.read_text(encoding="utf-8") == "original"


def test_safe_unlink_bounds_worst_case_aggregate_backoff(tmp_path, monkeypatch):
    path = tmp_path / "locked.txt"
    path.write_text("original", encoding="utf-8")
    attempts = []
    sleeps = []
    now = [100.0]

    def locked(candidate):
        attempts.append(candidate)
        raise _winerror5(candidate)

    def fake_sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(type(path), "unlink", locked)
    monkeypatch.setattr(process_utils.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(process_utils.time, "sleep", fake_sleep)

    with pytest.raises(PermissionError) as caught:
        process_utils.safe_unlink(path, max_attempts=10, delay=60)

    assert caught.value.winerror == 5
    assert sum(sleeps) <= 5.0
    assert all(seconds <= 5.0 for seconds in sleeps)
    assert len(attempts) == 1
    assert path.read_text(encoding="utf-8") == "original"


def test_safe_unlink_preserves_missing_file_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        process_utils.safe_unlink(tmp_path / "missing")
