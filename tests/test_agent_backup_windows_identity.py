"""Backups use the process token, not a deadline-sensitive whoami child."""
from contextlib import closing
import os
import sqlite3
import subprocess

import pytest

from local_ai_hub import agent_events, process_utils
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.leases import ScopeLeaseStore


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows token/ACL contract")


def test_verified_backups_survive_unavailable_whoami(tmp_path, monkeypatch):
    """A slow identity child must not prevent byte-verified durable backups."""
    real_run = process_utils.run_hidden
    commands = []

    def no_whoami(argv, **kwargs):
        commands.append(argv)
        if argv[0] == "whoami":
            raise subprocess.TimeoutExpired(argv, 1.0)
        return real_run(argv, **kwargs)

    monkeypatch.setattr(process_utils, "run_hidden", no_whoami)
    monkeypatch.setenv("USERNAME", "not-the-process-account")
    source_path = tmp_path / "source.sqlite3"
    with closing(sqlite3.connect(source_path)) as source:
        source.execute("CREATE TABLE durable(value TEXT)")
        source.execute("INSERT INTO durable VALUES ('must survive')")
        source.commit()
        before = source_path.read_bytes()
        for index in range(2):
            path = tmp_path / f"backup-{index}.sqlite3"
            assert AgentStateStore._verified_backup(source, destination_path=path) == path
            with closing(sqlite3.connect(path)) as backup:
                assert backup.execute("SELECT * FROM durable").fetchall() == [("must survive",)]
                assert backup.execute("PRAGMA quick_check").fetchone() == ("ok",)
    assert source_path.read_bytes() == before
    assert len(commands) == 2
    for command in commands:
        assert command[0] == "icacls"
        assert command[2:4] == ["/inheritance:r", "/grant:r"]
        assert command[-1].startswith("*S-1-")
        assert command[-1].endswith(":(F)")


def test_identity_failure_preserves_durable_source(tmp_path, monkeypatch):
    source_path = tmp_path / "source.sqlite3"
    with closing(sqlite3.connect(source_path)) as source:
        source.execute("CREATE TABLE durable(value TEXT)")
        source.execute("INSERT INTO durable VALUES ('must survive')")
        source.commit()
        before = source_path.read_bytes()
        error = PermissionError("token query denied")

        def denied():
            raise error

        monkeypatch.setattr(agent_events, "_windows_process_user_sid", denied)
        path = tmp_path / "backup.sqlite3"
        with pytest.raises(PermissionError) as raised:
            AgentStateStore._verified_backup(source, destination_path=path)
        assert raised.value.__cause__ is error
        assert not path.exists()
        assert source_path.read_bytes() == before
        assert source.execute("SELECT * FROM durable").fetchall() == [("must survive",)]


@pytest.mark.parametrize("error", [PermissionError("ACL denied"), subprocess.TimeoutExpired("icacls", 1)])
def test_acl_failure_still_removes_only_reserved_backup(tmp_path, monkeypatch, error):
    def denied(argv, **kwargs):
        raise error

    monkeypatch.setattr(process_utils, "run_hidden", denied)
    path = tmp_path / "backup.sqlite3"
    with pytest.raises(PermissionError) as raised:
        AgentStateStore._reserve_backup_destination(path)
    assert raised.value.__cause__ is error
    assert not path.exists()


@pytest.mark.parametrize("operation", ["OpenProcessToken", "GetTokenInformation", "ConvertSidToStringSidW"])
def test_native_identity_failure_closes_token_and_fails_closed(tmp_path, monkeypatch, operation):
    import ctypes

    real_dll = ctypes.WinDLL
    closed = []

    class Function:
        def __init__(self, name, function):
            self.name, self.function = name, function

        def __setattr__(self, name, value):
            object.__setattr__(self, name, value)
            if name in ("argtypes", "restype"):
                setattr(self.function, name, value)

        def __call__(self, *args):
            if self.name == operation:
                ctypes.set_last_error(5)
                return 0
            if self.name == "CloseHandle":
                closed.append(args[0].value)
            return self.function(*args)

    class Library:
        def __init__(self, name, **kwargs):
            self.real = real_dll(name, **kwargs)

        def __getattr__(self, name):
            function = Function(name, getattr(self.real, name))
            setattr(self, name, function)
            return function

    monkeypatch.setattr(ctypes, "WinDLL", Library)
    path = tmp_path / "backup.sqlite3"
    with pytest.raises(PermissionError):
        AgentStateStore._reserve_backup_destination(path)
    assert not path.exists()
    assert len(closed) == (0 if operation == "OpenProcessToken" else 1)


def test_nonempty_leases_database_backs_up_outside_transaction_without_whoami(
    tmp_path, monkeypatch
):
    real_run = process_utils.run_hidden
    real_connect = sqlite3.connect
    transaction_states = []
    commands = []

    class TracedConnection(sqlite3.Connection):
        def backup(self, *args, **kwargs):
            transaction_states.append(self.in_transaction)
            return super().backup(*args, **kwargs)

    class SQLite:
        def __getattr__(self, name):
            return getattr(sqlite3, name)

        def connect(self, *args, **kwargs):
            return real_connect(*args, **kwargs, factory=TracedConnection)

    ScopeLeaseStore(tmp_path)
    path = tmp_path / "agent_state.sqlite"
    with closing(sqlite3.connect(path)) as source:
        source.execute(
            """INSERT INTO leases (
                   lease_id, tenant, root_id, root_path, path, purpose, created_at, expires_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("lease-keep", "tenant-a", "root-a", "repo", "src/keep.py",
             "repository_search", 1.0, 2.0),
        )
        source.commit()

    def no_whoami(argv, **kwargs):
        commands.append(tuple(argv))
        if argv[0] == "whoami":
            raise subprocess.TimeoutExpired(argv, 1.0)
        return real_run(argv, **kwargs)

    monkeypatch.setattr(process_utils, "run_hidden", no_whoami)
    monkeypatch.setattr(agent_events, "sqlite3", SQLite())
    store = AgentStateStore(path)
    store._ensure_schema()

    assert transaction_states == [False]
    assert not any(command[0] == "whoami" for command in commands)
    backups = list(tmp_path.glob("*.bak"))
    assert len(backups) == 1
    with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(backups[0])) as backup:
        assert source.execute("PRAGMA user_version").fetchone() == (store._SCHEMA_VERSION,)
        assert source.execute("SELECT COUNT(*) FROM agent_events").fetchone() == (0,)
        assert source.execute(
            "SELECT lease_id, path FROM leases WHERE lease_id = ?", ("lease-keep",)
        ).fetchone() == ("lease-keep", "src/keep.py")
        assert backup.execute("PRAGMA user_version").fetchone() == (0,)
        assert backup.execute(
            "SELECT lease_id, path FROM leases WHERE lease_id = ?", ("lease-keep",)
        ).fetchone() == ("lease-keep", "src/keep.py")
        assert backup.execute("PRAGMA quick_check").fetchone() == ("ok",)


def test_precreated_empty_database_initializes_without_identity_child(tmp_path, monkeypatch):
    real_connect = sqlite3.connect
    transaction_states = []
    backup_calls = []
    commands = []

    class TracedConnection(sqlite3.Connection):
        def backup(self, *args, **kwargs):
            transaction_states.append(self.in_transaction)
            return super().backup(*args, **kwargs)

    class SQLite:
        def __getattr__(self, name):
            return getattr(sqlite3, name)

        def connect(self, *args, **kwargs):
            return real_connect(*args, **kwargs, factory=TracedConnection)

    def unexpected_backup(cls, source, **kwargs):
        backup_calls.append(source.in_transaction)
        raise AssertionError("pristine empty database must not be backed up")

    def unexpected_identity():
        raise AssertionError("pristine empty database must not resolve process identity")

    def unexpected_subprocess(argv, **kwargs):
        commands.append(tuple(argv))
        raise AssertionError("pristine empty database must not launch subprocesses")

    path = tmp_path / "agent_state.sqlite3"
    with closing(sqlite3.connect(path)):
        pass
    monkeypatch.setattr(
        AgentStateStore, "_verified_backup", classmethod(unexpected_backup)
    )
    monkeypatch.setattr(agent_events, "_windows_process_user_sid", unexpected_identity)
    monkeypatch.setattr(process_utils, "run_hidden", unexpected_subprocess)
    monkeypatch.setattr(agent_events, "sqlite3", SQLite())
    store = AgentStateStore(path)
    store._ensure_schema()

    assert backup_calls == []
    assert transaction_states == []
    assert commands == []
    assert not list(tmp_path.glob("*.bak"))
    with closing(sqlite3.connect(path)) as source:
        tables = {
            str(row[0])
            for row in source.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            if not str(row[0]).startswith("sqlite_")
        }
        assert {"agent_events", "agent_snapshots"} <= tables
        assert source.execute("PRAGMA user_version").fetchone() == (store._SCHEMA_VERSION,)
        assert source.execute("SELECT COUNT(*) FROM agent_events").fetchone() == (0,)


def test_real_backup_dacl_grants_only_process_user(tmp_path):
    import ctypes
    from ctypes import wintypes

    path = tmp_path / "backup.sqlite3"
    AgentStateStore._reserve_backup_destination(path)
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    security.GetFileSecurityW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    security.GetFileSecurityW.restype = wintypes.BOOL
    security.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(wintypes.DWORD),
    ]
    security.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    size = wintypes.DWORD()
    security.GetFileSecurityW(str(path), 4, None, 0, ctypes.byref(size))
    assert ctypes.get_last_error() == 122
    descriptor = ctypes.create_string_buffer(size.value)
    assert security.GetFileSecurityW(str(path), 4, descriptor, len(descriptor), ctypes.byref(size))
    text = wintypes.LPWSTR()
    assert security.ConvertSecurityDescriptorToStringSecurityDescriptorW(
        descriptor, 1, 4, ctypes.byref(text), None,
    )
    try:
        sid = agent_events._windows_process_user_sid()
        flags, ace = text.value.split("(", 1)
        assert flags in ("D:P", "D:PAI")  # AI bookkeeping does not grant inherited ACEs.
        assert ace == f"A;;FA;;;{sid})"
    finally:
        kernel.LocalFree(ctypes.cast(text, ctypes.c_void_p))


def test_acl_time_remains_inside_backup_deadline(tmp_path, monkeypatch):
    real_run = process_utils.run_hidden
    clock = [0.0]

    def elapsed_acl(argv, **kwargs):
        result = real_run(argv, **kwargs)
        clock[0] += 6.0
        return result

    monkeypatch.setattr(process_utils, "run_hidden", elapsed_acl)
    monkeypatch.setattr(agent_events, "time", type("Clock", (), {"monotonic": staticmethod(lambda: clock[0])}))
    path = tmp_path / "backup.sqlite3"
    with closing(sqlite3.connect(tmp_path / "source.sqlite3")) as source:
        source.execute("CREATE TABLE durable(value TEXT)")
        source.commit()
        with pytest.raises(TimeoutError, match="stage=secure_destination"):
            AgentStateStore._verified_backup(source, destination_path=path)
    assert not path.exists()


def test_uncommitted_source_is_rejected_without_self_block_or_commit(tmp_path, monkeypatch):
    path = tmp_path / "source.sqlite3"
    backup = tmp_path / "backup.sqlite3"
    # Keep the pre-fix real SQLite self-block reproduction bounded.
    monkeypatch.setattr(AgentStateStore, "_MIGRATION_BACKUP_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(process_utils, "run_hidden", lambda *args, **kwargs: None)
    with closing(sqlite3.connect(path)) as source:
        source.execute("CREATE TABLE durable(value TEXT)")
        source.commit()
        before = path.read_bytes()
        source.execute("INSERT INTO durable VALUES ('uncommitted caller data')")
        assert source.in_transaction
        with pytest.raises(RuntimeError, match="requires a source without an active transaction"):
            AgentStateStore._verified_backup(source, destination_path=backup)
        assert source.in_transaction
        assert source.execute("SELECT * FROM durable").fetchall() == [("uncommitted caller data",)]
        assert path.read_bytes() == before
        assert not backup.exists()
        source.rollback()


def test_external_sqlite_lock_reports_busy_deadline_and_preserves_source(tmp_path, monkeypatch):
    path = tmp_path / "source.sqlite3"
    backup = tmp_path / "backup.sqlite3"
    monkeypatch.setattr(AgentStateStore, "_MIGRATION_BACKUP_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(process_utils, "run_hidden", lambda *args, **kwargs: None)
    with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(path)) as writer:
        source.execute("CREATE TABLE durable(value TEXT)")
        source.execute("INSERT INTO durable VALUES ('committed')")
        source.commit()
        before = path.read_bytes()
        writer.execute("BEGIN EXCLUSIVE")
        assert not source.in_transaction
        try:
            with pytest.raises(TimeoutError, match="stage=copy sqlite_status=5 source_in_transaction=False"):
                AgentStateStore._verified_backup(source, destination_path=backup)
        finally:
            writer.rollback()
        assert path.read_bytes() == before
        assert not backup.exists()
        assert source.execute("SELECT * FROM durable").fetchall() == [("committed",)]
