from __future__ import annotations

from contextlib import contextmanager
from contextlib import closing
import hashlib
import copy
import tempfile
import json
import math
import os
import queue
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from .json_utils import dumps as json_dumps
from .pubsub_limits import bounded_name, snapshot_message
from .sqlite_support import (
    DurableSchemaMismatchError,
    connect_sqlite,
    initialize_wal,
    is_busy_error,
    retry_busy,
)

_MAX_EVENT_GAP_RANGES = 128


@dataclass(frozen=True)
class AgentEvent:
    event_id: str
    stream_id: str
    kind: str
    payload: Mapping[str, Any]
    idempotency_key: str
    correlation_id: str
    actor: str
    created_at: float
    seq: int | None = None

    def __post_init__(self) -> None:
        for name in ("event_id", "stream_id", "kind", "idempotency_key", "correlation_id", "actor"):
            value = getattr(self, name)
            if not isinstance(value, str) or "\x00" in value or (name != "correlation_id" and not value.strip()):
                raise ValueError(f"{name} must be a valid string identity")
        if not isinstance(self.payload, Mapping):
            raise TypeError("payload must be a mapping")
        if isinstance(self.created_at, bool) or not isinstance(self.created_at, (int, float)):
            raise ValueError("created_at must be finite and non-negative")
        try:
            created_at = float(self.created_at)
        except (ValueError, OverflowError) as exc:
            raise ValueError("created_at must be finite and non-negative") from exc
        if not math.isfinite(created_at) or created_at < 0:
            raise ValueError("created_at must be finite and non-negative")
        if self.seq is not None and (isinstance(self.seq, bool) or not isinstance(self.seq, int) or self.seq < 0):
            raise ValueError("seq must be a non-negative integer or None")
        object.__setattr__(self, "payload", dict(self.payload))
        object.__setattr__(self, "created_at", created_at)

    def is_persisted(self) -> bool:
        return self.seq is not None and self.seq > 0

    def has_correlation(self) -> bool:
        return bool(self.correlation_id)

    @classmethod
    def create(
        cls,
        stream_id: str,
        kind: str,
        payload: Mapping[str, Any] | None = None,
        idempotency_key: str = "",
        actor: str = "agent",
        correlation_id: str = "",
        created_at: float | None = None,
    ) -> AgentEvent:
        return cls(
            event_id=f"evt_{uuid.uuid4().hex}",
            stream_id=stream_id,
            kind=kind,
            payload={} if payload is None else payload,
            idempotency_key=idempotency_key or f"idemp_{uuid.uuid4().hex}",
            correlation_id=correlation_id,
            actor=actor,
            created_at=time.time() if created_at is None else created_at,
            seq=None,
        )

    def with_seq(self, seq: int) -> AgentEvent:
        return AgentEvent(
            event_id=self.event_id,
            stream_id=self.stream_id,
            kind=self.kind,
            payload=self.payload,
            idempotency_key=self.idempotency_key,
            correlation_id=self.correlation_id,
            actor=self.actor,
            created_at=self.created_at,
            seq=int(seq),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "stream_id": self.stream_id,
            "kind": self.kind,
            "payload": dict(self.payload),
            "idempotency_key": self.idempotency_key,
            "correlation_id": self.correlation_id,
            "actor": self.actor,
            "created_at": self.created_at,
            "seq": self.seq,
        }

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> AgentEvent:
        stream_id, seq, event_id, kind, payload_raw, idempotency_key, correlation_id, actor, created_at = row
        payload = json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw
        return cls(
            event_id=event_id,
            stream_id=stream_id,
            kind=kind,
            payload=payload,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            actor=actor,
            created_at=created_at,
            seq=seq,
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AgentEvent:
        if not isinstance(data, Mapping):
            raise TypeError("AgentEvent data must be a mapping")
        required_fields = (
            "event_id", "stream_id", "kind", "payload", "idempotency_key",
            "correlation_id", "actor", "created_at", "seq",
        )
        allowed_fields = set(required_fields)
        for field in required_fields:
            if field not in data:
                raise KeyError(field)
        unexpected_fields = set(data) - allowed_fields
        if unexpected_fields:
            raise ValueError(f"unexpected AgentEvent fields: {sorted(map(repr, unexpected_fields))}")
        return cls(
            event_id=data["event_id"],
            stream_id=data["stream_id"],
            kind=data["kind"],
            payload=data["payload"],
            idempotency_key=data["idempotency_key"],
            correlation_id=data["correlation_id"],
            actor=data["actor"],
            created_at=data["created_at"],
            seq=data["seq"],
        )



@dataclass(frozen=True)
class AppendResult:
    seq: int
    duplicate: bool
    event: AgentEvent | None = None
    retryable: bool = False
    error: str | None = None

    def succeeded(self) -> bool:
        return (
            self.error is None
            and not self.retryable
            and self.seq > 0
            and self.event is not None
        )

    def is_error(self) -> bool:
        return not self.succeeded()

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "duplicate": self.duplicate,
            "event": self.event.to_dict() if self.event is not None else None,
            "retryable": self.retryable,
            "error": self.error,
        }



class AgentStateStore:
    _schema_init_guard = threading.RLock()
    _append_publish_locks_guard = threading.Lock()
    _append_publish_locks: dict[str, Any] = {}
    # PRAGMA user_version belongs to the canonical database-wide core schema.
    # Runtime does not accept retired migration/version bookkeeping tables.
    _SCHEMA_VERSION = 1
    _SCHEMA_PREFLIGHT_TIMEOUT_SECONDS = 5.0
    _SCHEMA_OBJECT_SQL_MAX_BYTES = 8192
    _EVENT_COLUMNS = [
        "stream_id", "seq", "event_id", "kind", "payload", "idempotency_key",
        "correlation_id", "actor", "created_at",
    ]
    _SNAPSHOT_COLUMNS = ["snapshot_id", "stream_id", "seq", "state", "created_at"]
    _EXPECTED_OBJECT_SQL_HASHES = {
        ("table", "agent_questions", "agent_questions"): "6e32f781ef50c6664ce70e93dbb767a6889d1cffc80f766a83548209eaebd19c",
        ("index", "idx_agent_questions_session", "agent_questions"): "895948e4ff978d089295a00870cb4109bc3b86498d592e089e5bdd16073ca6cd",
        ('index', 'idx_lease_waits_owner', 'lease_waits'): '94c3e39e5224c63a4a855ea3843bd86cb490af2c1e993d567af26dc5ba9bc851',
        ("index", "idx_leases_root", "leases"): "a0ede5303197cc5172c5583f33a72ee1636083712d84e9d618a642a34671cc85",
        ("table", "lease_waits", "lease_waits"): 'f2c1464f4eb093891578b4de6a56e3f36473ac056d700ce2afc7a5a0ec098aaa',
        ("table", "leases", "leases"): '7a4ef9cfe8d7f31cef9ee8918b214495454dc551e5888a6125e03b95f93f2254',
        ("index", "idx_lease_waits_blocked", "lease_waits"): "366fe3b81e54f9032edecf9d798a2b2d23160bba578438a89591b929c1e87cab",
        ("table", "agent_swarms", "agent_swarms"): "5ccda29c6b858caae83c2ca78296c4ff939f7ae41cdab14054e67bf374592a81",
        ("table", "sqlite_sequence", "sqlite_sequence"): "9e042902d97481bf7dccaaff2183d686b3344691bb622fdfc017096ef4080c65",
        ("index", "idx_agent_budgets_task", "agent_budgets"): "bcf430cc5b43169c32c9a6493b85943f219431ea8e688bdfe76f7284734c20f9",
        ("index", "idx_agent_change_task", "agent_change_intents"): "59e49e948f8ccd127cd4698378e49e66af98e872ec9fcf1e23445854cb88440b",
        ("index", "idx_agent_events_created", "agent_events"): "bc5acedde3a15256f0c4de4628d1beadfe846b30f7b89738f3e7f030de635dba",
        ("index", "idx_agent_events_kind", "agent_events"): "ea38ef5ba6de50080cd324a3a41177914e9b37f12ffc62a76d37b2f7fe7a5b9b",
        ("index", "idx_agent_incidents_fp", "agent_incidents"): "4b67662bd5955574d1cce114df205ba62a1e0f5165613b4edd16072d34339709",
        ("index", "idx_agent_incidents_lookup", "agent_incidents"): "f170ab3ca4813c2fde1ef264a4a148c1ad08c0a6ea7243119864d2f7d35e58d9",
        ("index", "idx_agent_incidents_recent", "agent_incidents"): "2dabb490a313b3f49ec8cf3bbec38e5dd7d7869db9dc9ea69474d96fe86260a8",
        ("index", "idx_agent_incidents_scope", "agent_incidents"): "00d5a148686c8a351822ae7a5a15ad152b05b877f94720f691e56c399a2ddfb0",
        ("index", "idx_agent_klinks_path", "agent_knowledge_links"): "a765bbe0d7e69856c925200094c53bbd726cfaec770d274d4451b18b40e52b32",
        ("index", "idx_agent_memory_expires", "agent_memory_records"): "2b572d27d7aeff30fd4f5bac34028828f8cea53b3e7a33a365ecd2ac8d62bda6",
        ("index", "idx_agent_memory_provenance_branch", "agent_memory_records"): "d2bbcbdc38fffca0533cc1fb185773d0d7063c91e7318838a15bfb4a3ef919ff",
        ("index", "idx_agent_memory_provenance_clone_id", "agent_memory_records"): "1a9eb17c7d175eecbfadac0a08d55217eef4b0edf1c4c05d66a2eb5730a3682a",
        ("index", "idx_agent_memory_provenance_repository", "agent_memory_records"): "54eb35186ea96928612021440a3a8a41e69c7af684011efcc2dd7d97900f80fe",
        ("index", "idx_agent_memory_provenance_root", "agent_memory_records"): "368aa7550b0f3c86744f5c88741b5d6fa30fe1fd8a5f218561920cf5aff86c0e",
        ("index", "idx_agent_memory_provenance_worktree_id", "agent_memory_records"): "ede3797ba9a084d4e4a1539166ce72e442830fd0f4a7148ee288bd29e476fa34",
        ("index", "idx_agent_memory_scope_identity", "agent_memory_records"): "e09ea6e01564f92238fa9aac558fff356d8663bb92a1b00a3cc8484d1316e23c",
        ("index", "idx_agent_memory_scope_key", "agent_memory_records"): "87c860ab42d5e672c4c6fc123fcca090dc52e6a0382a15855d4dde2b73e49448",
        ("index", "idx_agent_memory_updated", "agent_memory_records"): "776e3e88b071833f15e7db3c0b57ca63c9485b092090df307ff29b774c49515a",
        ("index", "idx_agent_outcomes_change", "agent_outcomes"): "dc6d7b5ac5f463fb8abeed07c55fb5c88a2c51430eeb67b16858ee634dfb269b",
        ("index", "idx_agent_outcomes_task", "agent_outcomes"): "225296df966ea88b0d47e85fb1a4b90f93b29d666d35da0ae2dfb55bcee3323b",
        ("index", "idx_agent_snapshots_stream", "agent_snapshots"): "974fd8531f2206bcfa74ed26c733469ef576b19515b91ce78fe941d83fbcc1e8",
        ("index", "idx_agent_tasks_status", "agent_tasks_projection"): "0ac7b279372bdaed3b7c47acd6c70e4cd7b1e0df1e1890edfc66eac4bdc03330",
        ("index", "idx_agent_tasks_status_updated", "agent_tasks_projection"): "1d0fdd9dab8677f811492c31f26bab3af568f441de5e64b4b94b6c710598a211",
        ("index", "idx_agent_tasks_updated", "agent_tasks_projection"): "1c25fa23c988e8b730986555513e083454c134172930baf51dad9eb18f11ff67",
        ("index", "idx_agent_verif_task", "agent_verification_receipts"): "2b5073bea40ea5e312fc9aa761494ec53718927f90eae8dbe2987ec4765f2760",
        ("index", "idx_agent_verif_task_observed", "agent_verification_receipts"): "462c305e52d335c8368e5c0c4540c4936c83a8c3932746402403c5d8e91e8dc1",
        ("index", "idx_blackboard_board", "agent_blackboard"): "8766cf9835a46d47cdca628a456ab1b0a807c11d588fa671b64ba19fb699b5e4",
        ("index", "idx_entity_rel_source", "agent_entity_relations"): "816b220dbed8e3d6d99610d66e1254d90e381c25fef2902dddba2714220053d5",
        ("index", "idx_entity_rel_target", "agent_entity_relations"): "aa0be23cd9565e612f9252c63fb003fbabcd9fc5fe04df590eb1db2754a91f00",
        ("index", "idx_entity_rel_type", "agent_entity_relations"): "77fbc5362e7da269cdc53ee755d690d0f762d8ff3e5ab9c6e87a6e358bdd8330",
        ("table", "agent_blackboard", "agent_blackboard"): "fb18c17d6581de546f148b5b302188dda9013374d653dc7cb9511021ebc6c1e3",
        ("table", "agent_budgets", "agent_budgets"): "fbcda82d934dce0695d9cb9edd9d7c1386e5320a2aac79c5194eee55471982df",
        ("table", "agent_change_intents", "agent_change_intents"): "52ed988b0a31f820b145261f7c586ea869369958b8adcd21d6bd1ad7e1f8a9ca",
        ("table", "agent_entity_relations", "agent_entity_relations"): "7cb3cdb25d201d7e2e264eb0d2b3dda5bb831ffd531d7aea2dab79df6db26590",
        ("table", "agent_events", "agent_events"): "1dfef49210889dc707aa8405b65262a5a86acbc14bd940ca338293dde150b2a2",
        ("table", "agent_incidents", "agent_incidents"): "4b4e60c8124637cb345f05d386428fc7bcb9c23b518af0b17125f3a4bfaf85d7",
        ("table", "agent_knowledge_links", "agent_knowledge_links"): "729e5c852a59ef150c488ccfb998a8a4dab606a052d353d94360aa2793a62426",
        ("table", "agent_learning_candidates", "agent_learning_candidates"): "3b8650b155c972e370825d72cf2222c005401a696b7f996a991c1f9d552b5caa",
        ("table", "agent_memory_embeddings", "agent_memory_embeddings"): "468df99dabe588d9475009d02108f2fdadfcf63e83a7aedf6d7a36a9ead965b5",
        ("table", "agent_memory_fts", "agent_memory_fts"): "a3f3691e421244a8516c26f942a893b8b7a112b7771e9ba84ecded8eab4e3755",
        ("table", "agent_memory_fts_config", "agent_memory_fts_config"): "e78061e43ffaa4b703c9aa4a44e02c6bae4128c3b1aad6a4324e6d3b97772c02",
        ("table", "agent_memory_fts_content", "agent_memory_fts_content"): "3ad7416c82b07bb41be9b2d30e58886c16cef8d5ab7a31f2834dc2d087fd6368",
        ("table", "agent_memory_fts_data", "agent_memory_fts_data"): "069959f382044c08715841b26cef2b51fd926354471f1fe5a680d976760ba2b0",
        ("table", "agent_memory_fts_docsize", "agent_memory_fts_docsize"): "39dc58937b569ac9aac16ef8e847d4a647b5e35feff50261c75b8eb8447f3567",
        ("table", "agent_memory_fts_idx", "agent_memory_fts_idx"): "68d1a21899a38af4e033e9dcd254abe1aff6dfed08bfbaac4916d8873a290cfd",
        ("table", "agent_memory_records", "agent_memory_records"): "5cd8a7e88151416c741554d667ef08dfd8469b645870f26ccadc436cfddc25c0",
        ("table", "agent_outcomes", "agent_outcomes"): "624b2b6c004fe2d59814db6d948d1bd043a73dfc10a9d83127e7450a05d90144",
        ("table", "agent_snapshots", "agent_snapshots"): "323b038ec2305f3aa746737408a3a024da0f222285101d5e0bea9729cf5fdb69",
        ("table", "agent_tasks_projection", "agent_tasks_projection"): "d4283f29e8560ff94ae0877f38c1fdd8020a2d8e2fc6c66aa01a58dca6339cc4",
        ("table", "agent_verification_receipts", "agent_verification_receipts"): "6aeb2ffafd9572d5325f56e99f7c62455989c3d44772bd83d3e47b6f3abe953a",
    }
    _EXPECTED_OBJECT_SQL_HASHES.update({
        ("index", "idx_agent_task_search_grams_gram", "agent_task_search_grams"): "47289e8fa6b5eb7e6837a56d77ad684e26fbc466f43f0f7af252e77fb8af5e0a",
        ("index", "idx_agent_verif_task_outbox_pending", "agent_verification_task_outbox"): "50dff1b755ee28d10c80d199270f9f6b12fb2ca958b4a8948cb59ac6ff751f48",
        ("table", "agent_event_cursors", "agent_event_cursors"): "0ecf2e08637aef9d2f4a9167feb61de083e1a9d9b8b927f79ae7a58e74b2ef71",
        ("table", "agent_task_search_documents", "agent_task_search_documents"): "a291a7122e95c8b2f3f6b9a9a73269489b1794ceea3f4378d9ff6155fd900f93",
        ("table", "agent_task_search_grams", "agent_task_search_grams"): "d2f7c3b733bc0ffcee4d9ee72804edc3fedc36f73f7ceca5ce18662941a13b78",
        ("table", "agent_verification_task_outbox", "agent_verification_task_outbox"): "2f17423836ca86bf09a701a71a27ead55a2c458d02bb9f29e1445a0c0fc11d17",
    })
    def __init__(
        self,
        db_path: Path | str,
        *,
        enabled: bool = True,
        max_payload_bytes: int = 65536,
    ) -> None:
        self.db_path = Path(db_path)
        self.enabled = bool(enabled)
        self.max_payload_bytes = int(max_payload_bytes)
        lock_key = os.path.normcase(str(self.db_path.resolve()))
        with self._append_publish_locks_guard:
            self._append_publish_lock = self._append_publish_locks.setdefault(
                lock_key, threading.RLock()
            )
        self._lock = threading.RLock()
        self._initialized = False
        self._subscribers: list[queue.Queue[AgentEvent]] = []
        self._subscribers_lock = threading.Lock()
        self._dropped_event_count = 0
        self._drop_count_lock = threading.Lock()

    @property
    def dropped_event_count(self) -> int:
        with self._drop_count_lock:
            return self._dropped_event_count

    def _ensure_schema(self) -> None:
        if self._initialized or not self.enabled:
            return
        with self._schema_init_guard, self._lock:
            if self._initialized or not self.enabled:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            expected = {
                "agent_events": [
                    ("stream_id", "TEXT", 1, 1), ("seq", "INTEGER", 1, 2),
                    ("event_id", "TEXT", 1, 0), ("kind", "TEXT", 1, 0),
                    ("payload", "TEXT", 1, 0), ("idempotency_key", "TEXT", 1, 0),
                    ("correlation_id", "TEXT", 1, 0), ("actor", "TEXT", 1, 0),
                    ("created_at", "REAL", 1, 0),
                ],
                "agent_snapshots": [
                    ("snapshot_id", "INTEGER", 0, 1), ("stream_id", "TEXT", 1, 0),
                    ("seq", "INTEGER", 1, 0), ("state", "TEXT", 1, 0),
                    ("created_at", "REAL", 1, 0),
                ],
                "agent_event_cursors": [
                    ("stream_id", "TEXT", 0, 1), ("last_seq", "INTEGER", 1, 0),
                    ("first_retained_seq", "INTEGER", 1, 0),
                ],
            }

            def _setup() -> None:
                existed_before_open = self.db_path.exists()
                if existed_before_open and self.db_path.stat().st_size > 0:
                    self._preflight_schema_read_only()
                con = sqlite3.connect(self.db_path, timeout=5.0)
                try:
                    if not con.in_transaction:
                        con.execute("BEGIN IMMEDIATE")
                    with con:
                        con.execute("""
                            CREATE TABLE IF NOT EXISTS agent_events (
                                stream_id TEXT NOT NULL,
                                seq INTEGER NOT NULL,
                                event_id TEXT NOT NULL,
                                kind TEXT NOT NULL,
                                payload TEXT NOT NULL,
                                idempotency_key TEXT NOT NULL,
                                correlation_id TEXT NOT NULL,
                                actor TEXT NOT NULL,
                                created_at REAL NOT NULL,
                                PRIMARY KEY (stream_id, seq),
                                UNIQUE (stream_id, idempotency_key)
                            )
                        """)
                        con.execute(
                            "CREATE INDEX IF NOT EXISTS idx_agent_events_created "
                            "ON agent_events (created_at)"
                        )
                        con.execute(
                            "CREATE INDEX IF NOT EXISTS idx_agent_events_kind "
                            "ON agent_events (kind)"
                        )
                        con.execute("""
                            CREATE TABLE IF NOT EXISTS agent_snapshots (
                                snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                                stream_id TEXT NOT NULL,
                                seq INTEGER NOT NULL,
                                state TEXT NOT NULL,
                                created_at REAL NOT NULL
                            )
                        """)
                        con.execute(
                            "CREATE INDEX IF NOT EXISTS idx_agent_snapshots_stream "
                            "ON agent_snapshots (stream_id, seq DESC)"
                        )
                        con.execute("""
                            CREATE TABLE IF NOT EXISTS agent_event_cursors (
                                stream_id TEXT PRIMARY KEY,
                                last_seq INTEGER NOT NULL,
                                first_retained_seq INTEGER NOT NULL
                            )
                        """)
                        con.execute("""
                            INSERT OR IGNORE INTO agent_event_cursors (
                                stream_id, last_seq, first_retained_seq
                            )
                            SELECT stream_id, MAX(seq), MIN(seq)
                            FROM agent_events
                            GROUP BY stream_id
                        """)
                        con.execute(f"PRAGMA user_version={self._SCHEMA_VERSION}")
                        self._classify_schema(con)

                        from .sqlite_support import validate_durable_schema

                        validate_durable_schema(
                            con,
                            self.db_path,
                            expected,
                            complete_groups=(tuple(expected),),
                            required_unique={
                                "agent_events": (("stream_id", "idempotency_key"),),
                            },
                        )
                    initialize_wal(con)
                finally:
                    con.close()

            retry_busy(_setup, retries=5, base_delay_seconds=0.02)
            self._initialized = True

    def _preflight_schema_read_only(self) -> None:
        deadline = time.monotonic() + self._SCHEMA_PREFLIGHT_TIMEOUT_SECONDS
        with tempfile.TemporaryDirectory(prefix="agent-state-preflight-") as temporary:
            snapshot_db = Path(temporary) / self.db_path.name
            source_uri = f"{self.db_path.resolve().as_uri()}?mode=ro"
            progress_error: list[TimeoutError] = []

            def check_backup_progress(_status: int, _remaining: int, _total: int) -> None:
                if time.monotonic() >= deadline:
                    error = TimeoutError("agent_state schema preflight time limit exceeded")
                    progress_error.append(error)
                    raise error

            try:
                remaining = max(0.001, deadline - time.monotonic())
                with closing(sqlite3.connect(source_uri, uri=True, timeout=min(0.05, remaining))) as source:
                    with closing(sqlite3.connect(snapshot_db)) as snapshot:
                        source.backup(snapshot, pages=128, progress=check_backup_progress, sleep=0.01)
                        snapshot.commit()
                if time.monotonic() >= deadline:
                    raise TimeoutError("agent_state schema preflight time limit exceeded")
                uri = f"{snapshot_db.resolve().as_uri()}?mode=ro"
                remaining = max(0.001, deadline - time.monotonic())
                with closing(sqlite3.connect(uri, uri=True, timeout=min(0.01, remaining))) as con:
                    busy_ms = max(1, min(10, int(remaining * 1000)))
                    con.execute(f"PRAGMA busy_timeout={busy_ms}")
                    con.set_progress_handler(lambda: 1 if time.monotonic() >= deadline else 0, 1000)
                    try:
                        self._classify_schema(con)
                    except RuntimeError as exc:
                        raise DurableSchemaMismatchError(
                            self.db_path,
                            [str(exc)],
                            None,
                        ) from exc
            except RuntimeError:
                raise
            except sqlite3.DatabaseError as exc:
                if progress_error:
                    raise progress_error[-1] from exc
                if time.monotonic() >= deadline:
                    raise TimeoutError("agent_state schema preflight time limit exceeded") from exc
                raise
            if time.monotonic() >= deadline:
                raise TimeoutError("agent_state schema preflight time limit exceeded")

    @classmethod
    def _classify_schema(cls, con: sqlite3.Connection) -> tuple[Any, ...]:
        version = int(con.execute("PRAGMA user_version").fetchone()[0])
        if version > cls._SCHEMA_VERSION or version < 0:
            raise RuntimeError(f"unsupported agent state schema version: {version}")

        event_columns = cls._columns(con, "agent_events")
        snapshot_columns = cls._columns(con, "agent_snapshots")
        cursor_columns = cls._columns(con, "agent_event_cursors")
        objects = []
        for object_type, name, table, sql_length, sql_prefix in con.execute(
            "SELECT type, name, tbl_name, length(CAST(sql AS BLOB)), "
            "substr(CAST(sql AS BLOB), 1, ?) FROM sqlite_master "
            "WHERE (name NOT LIKE 'sqlite_%' OR name='sqlite_sequence') "
            "AND type IN ('table','index','view','trigger') ORDER BY type, name",
            (cls._SCHEMA_OBJECT_SQL_MAX_BYTES + 1,),
        ):
            if sql_length is not None and int(sql_length) > cls._SCHEMA_OBJECT_SQL_MAX_BYTES:
                raise RuntimeError(
                    f"unsupported agent_state schema definition exceeds "
                    f"{cls._SCHEMA_OBJECT_SQL_MAX_BYTES} bytes: {object_type} {name}"
                )
            sql = bytes(sql_prefix).decode("utf-8") if sql_prefix is not None else ""
            normalized_sql = " ".join(sql.split()).casefold()
            key = (str(object_type), str(name), str(table))
            expected_hash = cls._EXPECTED_OBJECT_SQL_HASHES.get(key)
            actual_hash = hashlib.sha256(normalized_sql.encode("utf-8")).hexdigest()
            if expected_hash is None:
                raise RuntimeError(
                    f"unsupported agent_state schema object: {object_type} {name}"
                )
            if isinstance(expected_hash, (set, frozenset, tuple, list)):
                if actual_hash not in expected_hash:
                    raise RuntimeError(
                        f"unsupported agent_state schema object definition: {object_type} {name}"
                    )
            elif actual_hash != expected_hash:
                raise RuntimeError(
                    f"unsupported agent_state schema object definition: {object_type} {name}"
                )
            objects.append((str(object_type), str(name), str(table), normalized_sql))
        objects = tuple(objects)
        tables = {name for kind, name, _table, _sql in objects if kind == "table"}

        core_columns_present = bool(event_columns or snapshot_columns or cursor_columns)
        if core_columns_present:
            if version != cls._SCHEMA_VERSION:
                raise RuntimeError("unsupported agent_state schema version for event tables")
            if (
                event_columns != cls._EVENT_COLUMNS
                or snapshot_columns != cls._SNAPSHOT_COLUMNS
                or cursor_columns != ["stream_id", "last_seq", "first_retained_seq"]
            ):
                raise RuntimeError("unsupported agent_state schema layout")
            required = {
                ("table", "agent_events", "agent_events"),
                ("table", "agent_snapshots", "agent_snapshots"),
                ("table", "agent_event_cursors", "agent_event_cursors"),
                ("index", "idx_agent_events_created", "agent_events"),
                ("index", "idx_agent_events_kind", "agent_events"),
                ("index", "idx_agent_snapshots_stream", "agent_snapshots"),
            }
            present = {(kind, name, table) for kind, name, table, _sql in objects}
            missing = required - present
            if missing:
                detail = ", ".join(f"{kind} {name}" for kind, name, _ in sorted(missing))
                raise RuntimeError(f"unsupported agent_state schema missing required schema objects: {detail}")
        elif "agent_events" in tables or "agent_snapshots" in tables or "agent_event_cursors" in tables:
            raise RuntimeError("unsupported agent_state schema layout")

        if "agent_incidents" in tables:
            incident_required = {
                ("table", "agent_incidents", "agent_incidents"),
                ("index", "idx_agent_incidents_fp", "agent_incidents"),
                ("index", "idx_agent_incidents_lookup", "agent_incidents"),
                ("index", "idx_agent_incidents_recent", "agent_incidents"),
                ("index", "idx_agent_incidents_scope", "agent_incidents"),
            }
            present = {(kind, name, table) for kind, name, table, _sql in objects}
            missing = incident_required - present
            if missing:
                detail = ", ".join(f"{kind} {name}" for kind, name, _ in sorted(missing))
                raise RuntimeError(
                    f"unsupported agent_state schema missing required schema objects: {detail}"
                )

        task_profile_tables = {
            "agent_tasks_projection", "agent_verification_receipts", "agent_budgets",
            "agent_change_intents", "agent_outcomes",
        }
        has_task_events = bool(event_columns) and con.execute(
            "SELECT 1 FROM agent_events WHERE kind LIKE 'task.%' "
            "AND kind != 'task.updated' LIMIT 1"
        ).fetchone() is not None
        if tables & task_profile_tables or has_task_events:
            if "agent_tasks_projection" not in tables:
                raise RuntimeError(
                    "unsupported agent_state schema missing required schema objects: "
                    "table agent_tasks_projection"
                )

        layout = "current" if core_columns_present else "empty"
        return (version, layout, event_columns, snapshot_columns, objects)

    @staticmethod
    def _columns(con: sqlite3.Connection, table: str) -> list[str]:
        return [str(row[1]) for row in con.execute(f'PRAGMA table_info("{table}")')]

    def append_in_transaction(
        self,
        con: Any,
        event: AgentEvent,
        *,
        strict_idempotency: bool = False,
    ) -> AppendResult:
        """Append event and advance durable sequence cursor in caller transaction."""
        if not self.enabled:
            raise RuntimeError("agent_state is disabled")
        if not bool(getattr(con, "in_transaction", False)):
            raise RuntimeError("append_in_transaction requires a caller-owned transaction")
        if not self._initialized:
            raise ValueError("schema must be initialized before opening a caller-owned transaction")
        payload = json_dumps(event.payload, separators=(",", ":"))
        payload_bytes = payload.encode("utf-8")
        if len(payload_bytes) > self.max_payload_bytes:
            raise ValueError(
                f"payload exceeds maximum allowed {self.max_payload_bytes} bytes (got {len(payload_bytes)})"
            )
        existing = con.execute(
            """
            SELECT stream_id, seq, event_id, kind, payload, idempotency_key, correlation_id, actor, created_at
            FROM agent_events WHERE stream_id = ? AND idempotency_key = ?
            """,
            (event.stream_id, event.idempotency_key),
        ).fetchone()
        if existing:
            stored = AgentEvent.from_row(existing)
            if strict_idempotency and (
                stored.kind != event.kind
                or dict(stored.payload) != dict(event.payload)
                or stored.actor != event.actor
                or stored.correlation_id != event.correlation_id
            ):
                raise ValueError(
                    "idempotency key was already used for a different event payload"
                )
            bounds = con.execute(
                "SELECT MIN(seq), MAX(seq) FROM agent_events WHERE stream_id = ?",
                (event.stream_id,),
            ).fetchone()
            cursor = con.execute(
                "SELECT last_seq, first_retained_seq FROM agent_event_cursors WHERE stream_id = ?",
                (event.stream_id,),
            ).fetchone()
            retained = int(bounds[0]) if bounds and bounds[0] is not None else (stored.seq or 1)
            stream_high_water = int(bounds[1]) if bounds and bounds[1] is not None else 0
            high_water = max(
                int(cursor[0]) if cursor else 0,
                stream_high_water,
                int(stored.seq or 0),
            )
            first_retained = min(int(cursor[1]), retained) if cursor else retained
            con.execute(
                """
                INSERT INTO agent_event_cursors (stream_id, last_seq, first_retained_seq)
                VALUES (?, ?, ?)
                ON CONFLICT(stream_id) DO UPDATE SET
                    last_seq = MAX(agent_event_cursors.last_seq, excluded.last_seq),
                    first_retained_seq = MIN(agent_event_cursors.first_retained_seq, excluded.first_retained_seq)
                """,
                (event.stream_id, high_water, first_retained),
            )
            return AppendResult(seq=stored.seq or 0, duplicate=True, event=stored)

        cursor = con.execute(
            "SELECT last_seq, first_retained_seq FROM agent_event_cursors WHERE stream_id = ?",
            (event.stream_id,),
        ).fetchone()
        if cursor is None:
            bounds = con.execute(
                "SELECT MIN(seq), MAX(seq) FROM agent_events WHERE stream_id = ?",
                (event.stream_id,),
            ).fetchone()
            if bounds and bounds[1] is not None:
                last_seq = int(bounds[1])
                first_retained = int(bounds[0])
            else:
                last_seq = 0
                first_retained = 1
            con.execute(
                "INSERT INTO agent_event_cursors (stream_id, last_seq, first_retained_seq) VALUES (?, ?, ?)",
                (event.stream_id, last_seq, first_retained),
            )
        else:
            last_seq, first_retained = int(cursor[0]), int(cursor[1])

        new_seq = last_seq + 1
        if first_retained > last_seq:
            first_retained = new_seq
        persisted = event.with_seq(new_seq)
        con.execute(
            """
            INSERT INTO agent_events (
                stream_id, seq, event_id, kind, payload, idempotency_key,
                correlation_id, actor, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.stream_id,
                new_seq,
                event.event_id,
                event.kind,
                payload,
                event.idempotency_key,
                event.correlation_id,
                event.actor,
                event.created_at,
            ),
        )
        con.execute(
            "UPDATE agent_event_cursors SET last_seq = ?, first_retained_seq = ? WHERE stream_id = ?",
            (new_seq, first_retained, event.stream_id),
        )
        return AppendResult(seq=new_seq, duplicate=False, event=persisted)

    @contextmanager
    def ordered_event_publication(
        self, con: Any
    ) -> Iterator[Callable[[Sequence[AgentEvent]], None]]:
        """Serialize a caller-owned commit with publication to live subscribers.

        Enter before the caller starts its transaction. The caller retains ownership
        of BEGIN, COMMIT, and ROLLBACK; call the yielded publisher only after COMMIT.
        The publisher verifies committed rows before emitting any event. A rollback
        therefore cannot produce a live event, even if the caller mistakenly tries
        to publish its pending result.
        """
        if not self.enabled:
            raise RuntimeError("agent_state is disabled")
        if bool(getattr(con, "in_transaction", False)):
            raise RuntimeError(
                "ordered_event_publication must be entered before caller transaction begins"
            )
        with self._append_publish_lock:
            scope_active = True

            def publish_committed(events: Sequence[AgentEvent]) -> None:
                if not scope_active:
                    raise RuntimeError("ordered event publication scope is closed")
                if bool(getattr(con, "in_transaction", False)):
                    raise RuntimeError("caller transaction is still open")
                committed: list[AgentEvent] = []
                last_seq_by_stream: dict[str, int] = {}
                for event in events:
                    if event.seq is None:
                        raise RuntimeError("event is not committed")
                    prior_seq = last_seq_by_stream.get(event.stream_id)
                    if prior_seq is not None and event.seq <= prior_seq:
                        raise ValueError("committed events must be supplied in stream sequence order")
                    last_seq_by_stream[event.stream_id] = event.seq
                    row = con.execute(
                        """
                        SELECT stream_id, seq, event_id, kind, payload, idempotency_key,
                               correlation_id, actor, created_at
                        FROM agent_events
                        WHERE stream_id = ? AND seq = ? AND event_id = ?
                        """,
                        (event.stream_id, event.seq, event.event_id),
                    ).fetchone()
                    if row is None or AgentEvent.from_row(row) != event:
                        raise RuntimeError("event is not committed")
                    committed.append(event)
                for event in committed:
                    self._publish(event)

            try:
                yield publish_committed
            finally:
                scope_active = False

    def append(self, event: AgentEvent, *, strict_idempotency: bool = False) -> AppendResult:
        if not self.enabled:
            return AppendResult(seq=0, duplicate=False, error="agent_state is disabled")
        payload_bytes = json_dumps(event.payload, separators=(",", ":")).encode("utf-8")
        if len(payload_bytes) > self.max_payload_bytes:
            raise ValueError(
                f"payload exceeds maximum allowed {self.max_payload_bytes} bytes (got {len(payload_bytes)})"
            )
        self._ensure_schema()

        def _do_append() -> AppendResult:
            con = connect_sqlite(self.db_path, isolation_level=None, timeout_seconds=2.0)
            try:
                con.execute("BEGIN IMMEDIATE")
                result = self.append_in_transaction(
                    con, event, strict_idempotency=strict_idempotency
                )
                con.execute("COMMIT")
                return result
            except Exception as exc:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                if is_busy_error(exc):
                    raise
                return AppendResult(seq=0, duplicate=False, error=str(exc))
            finally:
                con.close()

        try:
            with self._append_publish_lock:
                result = retry_busy(_do_append, retries=5, base_delay_seconds=0.02)
                if not result.duplicate and result.event is not None:
                    self._publish(result.event)
                return result
        except Exception as exc:
            if is_busy_error(exc):
                return AppendResult(seq=0, duplicate=False, retryable=True, error=str(exc))
            raise

    def subscribe(self, maxsize: int = 100) -> queue.Queue[AgentEvent]:
        q: queue.Queue[AgentEvent] = queue.Queue(maxsize=maxsize)
        with self._subscribers_lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[AgentEvent]) -> None:
        with self._subscribers_lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def _publish(self, event: AgentEvent) -> None:
        with self._subscribers_lock:
            subscribers = list(self._subscribers)
        dead_queues: list[queue.Queue[AgentEvent]] = []
        for q in subscribers:
            try:
                q.put_nowait(event)
            except queue.Full:
                dropped: list[AgentEvent] = []
                target_size = max(0, q.maxsize - 2)
                while q.qsize() > target_size:
                    try:
                        dropped.append(q.get_nowait())
                    except queue.Empty:
                        break

                by_stream: dict[str, list[tuple[int, int]]] = {}
                lost_count = 0
                newly_lost_count = 0
                gap_ranges_truncated = False
                for item in dropped:
                    ranges = item.payload.get("gap_ranges", []) if item.kind == "stream.gap" else []
                    if item.kind == "stream.gap":
                        lost_count += int(item.payload.get("lost_count", 0) or 0)
                        gap_ranges_truncated = gap_ranges_truncated or bool(
                            item.payload.get("gap_ranges_truncated", False)
                        )
                    for gap in ranges:
                        if not isinstance(gap, Mapping):
                            continue
                        stream_id = str(gap.get("stream_id", item.stream_id))
                        start, end = gap.get("from_seq"), gap.get("to_seq")
                        if start is not None and end is not None:
                            by_stream.setdefault(stream_id, []).append((int(start), int(end)))
                    if item.kind != "stream.gap" and item.seq is not None:
                        by_stream.setdefault(item.stream_id, []).append((int(item.seq), int(item.seq)))
                        lost_count += 1
                        newly_lost_count += 1

                # A one-slot queue cannot carry both the gap marker and the newest event.
                # In that case the marker includes the newest sequence as lost, so a
                # consumer can recover it through durable replay.
                if q.maxsize == 1:
                    if event.seq is not None:
                        by_stream.setdefault(event.stream_id, []).append((int(event.seq), int(event.seq)))
                    lost_count += 1
                    newly_lost_count += 1

                gap_ranges: list[dict[str, int | str]] = []
                for stream_id, intervals in by_stream.items():
                    merged: list[list[int]] = []
                    for start, end in sorted(intervals):
                        if merged and start <= merged[-1][1] + 1:
                            merged[-1][1] = max(merged[-1][1], end)
                        else:
                            merged.append([start, end])
                    gap_ranges.extend(
                        {"stream_id": stream_id, "from_seq": start, "to_seq": end}
                        for start, end in merged
                    )
                if len(gap_ranges) > _MAX_EVENT_GAP_RANGES:
                    gap_ranges_truncated = True
                    gap_ranges = gap_ranges[:_MAX_EVENT_GAP_RANGES]

                marker = AgentEvent.create(
                    stream_id=event.stream_id,
                    kind="stream.gap",
                    payload={
                        "reason": "subscriber queue overflow",
                        "gap_ranges": gap_ranges,
                        "gap_ranges_truncated": gap_ranges_truncated,
                        "lost_count": lost_count,
                        "replay_required": self.enabled,
                        "cursor": event.seq,
                    },
                    actor="system",
                )
                try:
                    q.put_nowait(marker)
                    if q.maxsize > 1:
                        q.put_nowait(event)
                except Exception:
                    dead_queues.append(q)
                if newly_lost_count:
                    with self._drop_count_lock:
                        self._dropped_event_count += newly_lost_count
            except Exception:
                dead_queues.append(q)
        if dead_queues:
            with self._subscribers_lock:
                for q in dead_queues:
                    if q in self._subscribers:
                        self._subscribers.remove(q)

    def event_page(
        self,
        stream_id: str,
        after_seq: int = 0,
        limit: int = 1000,
        through_seq: int | None = None,
    ) -> dict[str, Any]:
        """Read a bounded sequence page and report replay gaps explicitly."""
        try:
            requested_after = max(0, int(after_seq))
        except (TypeError, ValueError, OverflowError):
            requested_after = 0
            return self._event_page_error(requested_after)
        try:
            page_limit = max(1, min(int(limit), 10000))
        except (TypeError, ValueError, OverflowError):
            return self._event_page_error(requested_after)
        try:
            requested_through = (
                None if through_seq is None else max(0, int(through_seq))
            )
        except (TypeError, ValueError, OverflowError):
            return self._event_page_error(requested_after)
        if not self.enabled:
            return {
                "success": False,
                "events": [],
                "next_seq": requested_after,
                "first_retained_seq": 0,
                "last_seq": 0,
                "has_more": False,
                "gap_ranges": [],
                "cursor_reset": False,
                "error": {
                    "code": "agent_state_disabled",
                    "message": "agent state is disabled",
                },
            }
        if not self.db_path.exists():
            return {
                "success": True,
                "events": [],
                "next_seq": requested_after,
                "first_retained_seq": 0,
                "last_seq": 0,
                "has_more": False,
                "gap_ranges": [],
                "cursor_reset": False,
            }
        con: sqlite3.Connection | None = None
        try:
            self._ensure_schema()
            con = connect_sqlite(self.db_path, isolation_level=None)
            con.execute("BEGIN")
            cursor = con.execute(
                "SELECT last_seq, first_retained_seq FROM agent_event_cursors WHERE stream_id = ?",
                (stream_id,),
            ).fetchone()
            bounds = con.execute(
                "SELECT MIN(seq), MAX(seq) FROM agent_events WHERE stream_id = ?",
                (stream_id,),
            ).fetchone()
            if cursor is None:
                if bounds and bounds[1] is not None:
                    current_last_seq = int(bounds[1])
                else:
                    current_last_seq = 0
            else:
                current_last_seq = max(
                    int(cursor[0]),
                    int(bounds[1]) if bounds and bounds[1] is not None else 0,
                )
            last_seq = (
                current_last_seq
                if requested_through is None
                else min(current_last_seq, requested_through)
            )
            first_retained = int(bounds[0]) if bounds and bounds[0] is not None else None
            cursor_reset = requested_after > current_last_seq
            effective_after = requested_after
            if cursor_reset:
                effective_after = (
                    max(0, first_retained - 1)
                    if first_retained is not None
                    else current_last_seq
                )
            rows = con.execute(
                """
                SELECT stream_id, seq, event_id, kind, payload, idempotency_key, correlation_id, actor, created_at
                FROM agent_events
                WHERE stream_id = ? AND seq > ? AND seq <= ?
                ORDER BY seq ASC
                LIMIT ?
                """,
                (stream_id, effective_after, last_seq, page_limit + 1),
            ).fetchall()
            has_more = len(rows) > page_limit
            events = [AgentEvent.from_row(row) for row in rows[:page_limit]]
            next_seq = events[-1].seq if events else effective_after
            gap_ranges: list[dict[str, int]] = []
            expected_seq = effective_after + 1
            for event in events:
                if event.seq > expected_seq:
                    gap_ranges.append({"from_seq": expected_seq, "to_seq": event.seq - 1})
                expected_seq = event.seq + 1
            if not has_more and expected_seq <= last_seq:
                trailing_gap = {"from_seq": expected_seq, "to_seq": last_seq}
                gap_ranges.append(trailing_gap)
                next_seq = trailing_gap["to_seq"]
            result = {
                "success": True,
                "events": [event.to_dict() for event in events],
                "next_seq": next_seq,
                "first_retained_seq": first_retained,
                "last_seq": last_seq,
                "has_more": has_more,
                "gap_ranges": gap_ranges,
                "cursor_reset": cursor_reset,
            }
            con.execute("COMMIT")
            return result
        except Exception as exc:
            if con is not None:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
            detail = (
                str(exc)
                if isinstance(exc, (TimeoutError,))
                else None
            )
            return self._event_page_error(requested_after, detail)
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass

    @staticmethod
    def _event_page_error(next_seq: int, message: str | None = None) -> dict[str, Any]:
        return {
            "success": False,
            "events": [],
            "next_seq": next_seq,
            "first_retained_seq": None,
            "last_seq": 0,
            "has_more": False,
            "gap_ranges": [],
            "cursor_reset": False,
            "error": {
                "code": "event_page_unavailable",
                "message": message or "Event page could not be read.",
            },
        }



    def events(self, stream_id: str, after_seq: int = 0, limit: int = 1000) -> list[AgentEvent]:
        # Initialize first so durable-schema failures remain typed and actionable.
        if self.enabled and self.db_path.exists():
            self._ensure_schema()
        page = self.event_page(stream_id, after_seq=after_seq, limit=limit)
        if page["success"] is not True:
            error = page["error"]
            message = str(error["message"])
            if "time limit exceeded" in message.casefold():
                raise TimeoutError(message)
            raise RuntimeError(f"{error['code']}: {message}")
        return [AgentEvent.from_dict(event) for event in page["events"]]


    def snapshot(self, stream_id: str, state: Mapping[str, Any], seq: int | None = None) -> int:
        if not self.enabled:
            return 0
        self._ensure_schema()
        raw_state = json_dumps(state, separators=(",", ":"))

        def _do_snapshot() -> int:
            con = connect_sqlite(self.db_path, isolation_level=None)
            try:
                con.execute("BEGIN IMMEDIATE")
                target_seq = seq
                if target_seq is None:
                    row = con.execute(
                        "SELECT COALESCE(MAX(seq), 0) FROM agent_events WHERE stream_id = ?",
                        (stream_id,),
                    ).fetchone()
                    target_seq = int(row[0]) if row else 0

                cur = con.execute(
                    """
                    INSERT INTO agent_snapshots (stream_id, seq, state, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (stream_id, target_seq, raw_state, time.time()),
                )
                snap_id = cur.lastrowid or 0
                con.execute("COMMIT")
                return snap_id
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                con.close()

        return retry_busy(_do_snapshot, retries=5, base_delay_seconds=0.02)

    def latest_snapshot(self, stream_id: str) -> dict[str, Any] | None:
        if not self.enabled or not self.db_path.exists():
            return None
        self._ensure_schema()
        con = connect_sqlite(self.db_path)
        try:
            row = con.execute(
                """
                SELECT snapshot_id, seq, state, created_at
                FROM agent_snapshots
                WHERE stream_id = ?
                ORDER BY seq DESC, snapshot_id DESC
                LIMIT 1
                """,
                (stream_id,),
            ).fetchone()
            if not row:
                return None
            snap_id, seq, raw_state, created_at = row
            try:
                state_data = json.loads(raw_state) if isinstance(raw_state, str) else dict(raw_state)
            except Exception:
                state_data = {}
            return {
                "snapshot_id": snap_id,
                "seq": seq,
                "state": state_data,
                "created_at": created_at,
            }
        finally:
            con.close()

    def cleanup(self, retention_days: int = 30) -> dict[str, Any]:
        if not self.enabled or not self.db_path.exists():
            return {"success": True, "deleted_events": 0, "deleted_snapshots": 0}
        self._ensure_schema()
        cutoff = time.time() - (max(1, int(retention_days)) * 86400)

        def _do_cleanup() -> dict[str, Any]:
            con = connect_sqlite(self.db_path, isolation_level=None)
            try:
                con.execute("BEGIN IMMEDIATE")
                stream_rows = con.execute(
                    "SELECT stream_id FROM agent_event_cursors ORDER BY stream_id"
                ).fetchall()
                deleted_events = 0
                for stream_row in stream_rows:
                    clean_stream = str(stream_row[0])
                    cursor = con.execute(
                        "SELECT last_seq FROM agent_event_cursors WHERE stream_id = ?",
                        (clean_stream,),
                    ).fetchone()
                    last_seq = int(cursor[0]) if cursor else 0
                    first_recent = con.execute(
                        """
                        SELECT MIN(seq) FROM agent_events
                        WHERE stream_id = ? AND created_at >= ?
                        """,
                        (clean_stream, cutoff),
                    ).fetchone()
                    if first_recent and first_recent[0] is not None:
                        first_retained_seq = int(first_recent[0])
                        cur_ev = con.execute(
                            "DELETE FROM agent_events WHERE stream_id = ? AND seq < ?",
                            (clean_stream, first_retained_seq),
                        )
                    else:
                        cur_ev = con.execute(
                            "DELETE FROM agent_events WHERE stream_id = ?",
                            (clean_stream,),
                        )
                    deleted_events += max(0, cur_ev.rowcount if cur_ev else 0)
                    retained = con.execute(
                        "SELECT MIN(seq) FROM agent_events WHERE stream_id = ?",
                        (clean_stream,),
                    ).fetchone()
                    first_retained = int(retained[0]) if retained and retained[0] is not None else last_seq + 1
                    con.execute(
                        "UPDATE agent_event_cursors SET first_retained_seq = ? WHERE stream_id = ?",
                        (first_retained, clean_stream),
                    )
                cur_snap = con.execute("DELETE FROM agent_snapshots WHERE created_at < ?", (cutoff,))
                deleted_snaps = cur_snap.rowcount if cur_snap else 0
                con.execute("COMMIT")
                return {"success": True, "deleted_events": deleted_events, "deleted_snapshots": deleted_snaps}
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                con.close()

        return retry_busy(_do_cleanup, retries=5, base_delay_seconds=0.02)

    def export_delta(self, stream_id: str = "", after_seq: int = 0, limit: int = 1000) -> dict[str, Any]:
        if not self.enabled or not self.db_path.exists():
            return {"success": True, "events": [], "count": 0}
        self._ensure_schema()
        con = connect_sqlite(self.db_path)
        try:
            if stream_id:
                cur = con.execute(
                    """
                    SELECT stream_id, seq, event_id, kind, payload, idempotency_key, correlation_id, actor, created_at
                    FROM agent_events
                    WHERE stream_id = ? AND seq > ?
                    ORDER BY seq ASC LIMIT ?
                    """,
                    (stream_id, int(after_seq), max(1, int(limit))),
                )
            else:
                cur = con.execute(
                    """
                    SELECT stream_id, seq, event_id, kind, payload, idempotency_key, correlation_id, actor, created_at
                    FROM agent_events
                    WHERE seq > ?
                    ORDER BY seq ASC LIMIT ?
                    """,
                    (int(after_seq), max(1, int(limit))),
                )
            rows = cur.fetchall()
            evs = [AgentEvent.from_row(row).to_dict() for row in rows]
            return {"success": True, "events": evs, "count": len(evs)}
        finally:
            con.close()

    def import_delta(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.enabled:
            return {"success": False, "error": "agent state store disabled"}
        imported = 0
        duplicates = 0
        for ev_data in events:
            try:
                ev = AgentEvent.from_dict(ev_data)
                res = self.append(ev)
                if res.duplicate:
                    duplicates += 1
                elif res.seq > 0:
                    imported += 1
            except Exception:
                continue
        return {"success": True, "imported_count": imported, "duplicate_count": duplicates}


class SwarmPubSub:
    """App-owned durable pubsub with bounded live fanout and explicit gaps."""

    _instance: SwarmPubSub | None = None
    _lock = threading.Lock()

    def __init__(self, state_store: AgentStateStore | None = None, max_age_seconds: float = 3600.0,
                 *, max_topics: int = 500, max_subscribers: int = 256,
                 max_queue_slots: int = 4096, max_cached_bytes: int = 8_388_608,
                 max_message_bytes: int = 65_536):
        self.state_store = state_store
        if isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, (int, float)):
            raise ValueError("pubsub max_age_seconds must be finite and non-negative")
        self.max_age_seconds = float(max_age_seconds)
        if not math.isfinite(self.max_age_seconds) or self.max_age_seconds < 0:
            raise ValueError("pubsub max_age_seconds must be finite and non-negative")
        for name, value, ceiling in (
            ("max_topics", max_topics, 4096), ("max_subscribers", max_subscribers, 4096),
            ("max_queue_slots", max_queue_slots, 100_000), ("max_cached_bytes", max_cached_bytes, 67_108_864),
            ("max_message_bytes", max_message_bytes, 1_048_576),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= ceiling:
                raise ValueError(f"pubsub {name} must be an integer between 1 and {ceiling}")
            setattr(self, name, value)
        self._topics: dict[str, list[dict[str, Any]]] = {}
        self._topic_sizes: dict[str, list[int]] = {}
        self._cached_bytes = 0
        self._subscriber_count = 0
        self._queue_slots = 0
        self._ephemeral_retention_floor = 0.0
        self._subscribers: dict[str, dict[str, queue.Queue[dict[str, Any]]]] = {}
        self._mu = threading.Lock()

    @staticmethod
    def _clean_topic(topic: Any) -> str:
        return bounded_name(topic, "topic").lower()

    @classmethod
    def get_default(cls, state_store: AgentStateStore | None = None) -> SwarmPubSub:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(state_store)
            elif state_store is not None:
                cls._instance.state_store = state_store
            return cls._instance

    def subscribe(self, topic: str, maxsize: int = 100) -> tuple[str, queue.Queue[dict[str, Any]]]:
        clean_topic = bounded_name(topic, "topic").lower()
        sub_id = f"sub_{uuid.uuid4().hex[:10]}"
        if isinstance(maxsize, bool) or not isinstance(maxsize, int) or not 1 <= maxsize <= 1000:
            raise ValueError("pubsub maxsize must be an integer between 1 and 1000")
        slots = max(10, maxsize)
        with self._mu:
            if self._subscriber_count >= self.max_subscribers or self._queue_slots + slots > self.max_queue_slots:
                raise ValueError("pubsub subscription capacity reached")
            q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=slots)
            self._subscribers.setdefault(clean_topic, {})[sub_id] = q
            self._subscriber_count += 1
            self._queue_slots += slots
        return sub_id, q

    def unsubscribe(self, topic: str, sub_id: str) -> bool:
        clean_topic = bounded_name(topic, "topic").lower()
        with self._mu:
            subs = self._subscribers.get(clean_topic, {})
            if sub_id in subs:
                self._queue_slots -= subs[sub_id].maxsize
                self._subscriber_count -= 1
                del subs[sub_id]
                if not subs:
                    self._subscribers.pop(clean_topic, None)
                return True
        return False

    def subscriber_count(self, topic: str | None = None) -> int:
        clean_topic = self._clean_topic(topic) if topic is not None else None
        with self._mu:
            if clean_topic is not None:
                return len(self._subscribers.get(clean_topic, {}))
            return self._subscriber_count

    def wait_for_event(
        self,
        topic: str,
        timeout: float = 60.0,
        filter_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_topic = bounded_name(topic, "topic").lower()
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout < 0:
            raise ValueError("pubsub timeout must be a non-negative number")
        timeout_val = min(float(timeout), 600.0)
        deadline = time.monotonic() + timeout_val
        sub_id, q = self.subscribe(clean_topic)
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return {
                        "success": False,
                        "timeout": True,
                        "timed_out": True,
                        "topic": clean_topic,
                        "event": None,
                        "message": None,
                    }
                try:
                    event = q.get(timeout=min(remaining, 0.5))
                except queue.Empty:
                    continue

                if filter_payload and isinstance(filter_payload, dict):
                    msg = event.get("payload", {})
                    if isinstance(msg, dict):
                        match = all(msg.get(k) == v for k, v in filter_payload.items())
                        if not match:
                            continue
                    else:
                        continue
                if isinstance(event, dict):
                    event["message"] = event.get("payload")
                return {
                    "success": True,
                    "timeout": False,
                    "timed_out": False,
                    "topic": clean_topic,
                    "event": event,
                    "message": event.get("payload") if isinstance(event, dict) else None,
                    "sender": event.get("sender") if isinstance(event, dict) else None,
                    "timestamp": event.get("timestamp") if isinstance(event, dict) else None,
                    "sequence": event.get("sequence", 0) if isinstance(event, dict) else 0,
                }
        finally:
            self.unsubscribe(clean_topic, sub_id)

    def topic_count(self) -> int:
        with self._mu:
            return len({key for key, messages in self._topics.items() if messages} | {
                key for key, subscribers in self._subscribers.items() if subscribers
            })

    def clear_topic(self, topic: str) -> int:
        clean_topic = self._clean_topic(topic)
        with self._mu:
            messages = self._topics.pop(clean_topic, [])
            self._cached_bytes -= sum(self._topic_sizes.pop(clean_topic, []))
            if messages:
                self._ephemeral_retention_floor = max(
                    self._ephemeral_retention_floor, max(item["timestamp"] for item in messages),
                )
            return len(messages)

    def _prune_expired_locked(self, clean_topic: str, now: float) -> int:
        cutoff = now - self.max_age_seconds
        messages = self._topics.get(clean_topic, [])
        sizes = self._topic_sizes.get(clean_topic, [])
        retained, retained_sizes = [], []
        removed = 0
        for message, size in zip(messages, sizes):
            if message["timestamp"] < cutoff:
                self._cached_bytes -= size
                self._ephemeral_retention_floor = max(self._ephemeral_retention_floor, message["timestamp"])
                removed += 1
            else:
                retained.append(message)
                retained_sizes.append(size)
        if retained:
            self._topics[clean_topic] = retained
            self._topic_sizes[clean_topic] = retained_sizes
        else:
            self._topics.pop(clean_topic, None)
            self._topic_sizes.pop(clean_topic, None)
        return removed

    def compact(self, now: float | None = None) -> dict[str, int]:
        tick = time.time() if now is None else float(now)
        if not math.isfinite(tick):
            raise ValueError("pubsub compaction time must be finite")
        with self._mu:
            before = len(self._topics)
            removed = sum(self._prune_expired_locked(topic, tick) for topic in list(self._topics))
            return {"topics_pruned": before - len(self._topics), "messages_evicted": removed,
                    "subscribers_evicted": 0, "cached_bytes": self._cached_bytes}

    @staticmethod
    def _sequence_gap_ranges(dropped: list[dict[str, Any]]) -> list[dict[str, int]]:
        by_topic: dict[str, list[tuple[int, int]]] = {}
        for message in dropped:
            for gap in message.get("gap_ranges", []):
                if isinstance(gap, dict) and gap.get("from_seq") is not None and gap.get("to_seq") is not None:
                    by_topic.setdefault(str(message.get("topic", "")), []).append(
                        (int(gap["from_seq"]), int(gap["to_seq"]))
                    )
            seq = message.get("sequence")
            if seq is not None and message.get("kind") != "pubsub.gap":
                by_topic.setdefault(str(message.get("topic", "")), []).append((int(seq), int(seq)))
        ranges: list[dict[str, int]] = []
        for intervals in by_topic.values():
            merged: list[list[int]] = []
            for start, end in sorted(intervals):
                if merged and start <= merged[-1][1] + 1:
                    merged[-1][1] = max(merged[-1][1], end)
                else:
                    merged.append([start, end])
            ranges.extend({"from_seq": start, "to_seq": end} for start, end in merged)
        return ranges

    @classmethod
    def _enqueue(cls, q: queue.Queue[dict[str, Any]], message: dict[str, Any]) -> None:
        try:
            q.put_nowait(message)
            return
        except queue.Full:
            pass
        dropped: list[dict[str, Any]] = []
        while q.qsize() > q.maxsize - 2:
            try:
                dropped.append(q.get_nowait())
                q.task_done()
            except queue.Empty:
                break
        gaps = cls._sequence_gap_ranges(dropped)
        lost_count = sum(
            int(item.get("payload", {}).get("lost_count", 0) or 0)
            if item.get("kind") == "pubsub.gap"
            else 1
            for item in dropped
        )
        marker = {
            "id": f"gap_{uuid.uuid4().hex[:12]}",
            "topic": message.get("topic", ""),
            "kind": "pubsub.gap",
            "timestamp": time.time(),
            "sequence": message.get("sequence"),
            "gap_ranges": gaps,
            "payload": {
                "gap_ranges": gaps,
                "cursor": message.get("sequence"),
                "lost_count": lost_count,
                "replay_required": message.get("sequence") is not None,
            },
        }
        q.put_nowait(marker)
        q.put_nowait(message)

    def publish(
        self,
        topic: str,
        message: dict[str, Any] | str,
        sender: str = "agent",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        try:
            clean_topic = bounded_name(topic, "topic").lower()
            sender = bounded_name(sender, "sender", strip=False)
            idempotency_key = bounded_name(idempotency_key, "idempotency_key", allow_empty=True, strip=False)
            if not isinstance(message, (dict, str)):
                raise ValueError("pubsub message must be a dictionary or string")
            envelope, _size = snapshot_message(
                {"sender": sender, "message": message if isinstance(message, dict) else {"text": message}},
                self.max_message_bytes,
            )
            msg_payload = envelope["message"]
        except (ValueError, TypeError, RuntimeError, OverflowError) as exc:
            return {"success": False, "error": str(exc), "terminal": True, "retryable": False}
        now = time.time()
        event_id = f"pub_{uuid.uuid4().hex[:12]}"
        sequence: int | None = None
        durable = bool(self.state_store is not None and self.state_store.enabled)
        if idempotency_key:
            stable_id = uuid.uuid5(
                uuid.NAMESPACE_URL,
                "pubsub:" + clean_topic + ":" + idempotency_key,
            ).hex[:12]
            event_id = f"pub_{stable_id}"
        if durable:
            persisted = self.state_store.append(
                AgentEvent(
                    event_id=event_id,
                    stream_id=f"pubsub:{clean_topic}",
                    kind="pubsub.message",
                    payload={
                        "sender": sender,
                        "message": msg_payload,
                    },
                    idempotency_key=idempotency_key or f"publish:{event_id}",
                    correlation_id="",
                    actor=sender,
                    created_at=now,
                ),
                strict_idempotency=True,
            )
            if persisted.error or persisted.retryable or persisted.event is None:
                return {
                    "success": False,
                    "error": persisted.error or "durable pubsub append failed",
                    "retryable": persisted.retryable,
                    "durable": True,
                    "replay_available": True,
                }
            event_id = str(persisted.event.payload.get("message_id") or persisted.event.event_id)
            now = persisted.event.created_at
            sequence = persisted.seq
            if persisted.duplicate:
                return {
                    "success": True,
                    "duplicate": True,
                    "topic": clean_topic,
                    "message_id": event_id,
                    "timestamp": now,
                    "cursor": sequence,
                    "durable": True,
                    "replay_available": True,
                }
        event = {
            "id": event_id,
            "topic": clean_topic,
            "sender": sender,
            "timestamp": now,
            "payload": msg_payload,
            "sequence": sequence,
            "kind": "pubsub.message",
        }
        with self._mu:
            event_bytes = len(json_dumps(event, allow_nan=False).encode("utf-8"))
            if clean_topic not in self._topics or self._cached_bytes + event_bytes > self.max_cached_bytes:
                for cached_topic in list(self._topics):
                    self._prune_expired_locked(cached_topic, now)
            bucket = self._topics.get(clean_topic, [])
            sizes = self._topic_sizes.get(clean_topic, [])
            reclaimed = sizes[0] if len(bucket) >= 200 else 0
            cache_retained = (bool(bucket) or len(self._topics) < self.max_topics) and self._cached_bytes + event_bytes - reclaimed <= self.max_cached_bytes
            if not cache_retained and not durable:
                return {"success": False, "error": "pubsub ephemeral cache capacity reached", "durable": False,
                        "replay_available": False, "terminal": True, "retryable": False}
            if cache_retained:
                if len(bucket) >= 200:
                    dropped = bucket.pop(0)
                    self._ephemeral_retention_floor = max(self._ephemeral_retention_floor, dropped["timestamp"])
                    self._cached_bytes -= sizes.pop(0)
                bucket.append(event)
                sizes.append(event_bytes)
                self._topics[clean_topic], self._topic_sizes[clean_topic] = bucket, sizes
                self._cached_bytes += event_bytes
            for q in list(self._subscribers.get(clean_topic, {}).values()):
                self._enqueue(q, copy.deepcopy(event))
        result = {
            "success": True,
            "topic": clean_topic,
            "message_id": event_id,
            "timestamp": now,
            "cursor": sequence,
            "durable": durable,
            "replay_available": durable,
            "cache_retained": cache_retained,
        }
        if durable and persisted.duplicate:
            result["duplicate"] = True
        return result

    def poll(
        self,
        topic: str,
        since_timestamp: float = 0.0,
        limit: int = 50,
        after_seq: int = 0,
    ) -> dict[str, Any]:
        clean_topic = bounded_name(topic, "topic").lower()
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("pubsub limit must be an integer between 1 and 1000")
        if isinstance(since_timestamp, bool) or not isinstance(since_timestamp, (int, float)):
            raise ValueError("pubsub since_timestamp must be finite and non-negative")
        since_ts = float(since_timestamp)
        if not math.isfinite(since_ts) or since_ts < 0:
            raise ValueError("pubsub since_timestamp must be finite and non-negative")
        page_limit = limit
        durable = bool(self.state_store is not None and self.state_store.enabled)
        if durable:
            page = self.state_store.event_page(
                stream_id=f"pubsub:{clean_topic}",
                after_seq=after_seq,
                limit=page_limit,
            )
            if page.get("success") is not True:
                return {
                    "success": False,
                    "topic": clean_topic,
                    "count": 0,
                    "messages": [],
                    "cursor": page["next_seq"],
                    "after_seq": page["next_seq"],
                    "first_retained_seq": None,
                    "last_seq": 0,
                    "has_more": False,
                    "gap_ranges": [],
                    "gap": None,
                    "cursor_reset": False,
                    "error": page.get("error"),
                    "durable": True,
                    "replay_available": True,
                }
            messages = []
            for event in page["events"]:
                if isinstance(event, dict):
                    payload = dict(event.get("payload") or {})
                    messages.append({
                        "id": str(payload.get("message_id") or event.get("event_id") or ""),
                        "topic": clean_topic,
                        "sender": str(payload.get("sender") or event.get("actor") or ""),
                        "timestamp": float(event.get("created_at") or 0.0),
                        "payload": payload.get("message", {}),
                        "seq": event.get("seq") or 0,
                        "sequence": event.get("seq") or 0,
                    })
                else:
                    payload = dict(getattr(event, "payload", {}) or {})
                    messages.append({
                        "id": str(payload.get("message_id") or getattr(event, "event_id", "")),
                        "topic": clean_topic,
                        "sender": str(payload.get("sender", getattr(event, "actor", ""))),
                        "timestamp": float(getattr(event, "created_at", 0.0)),
                        "payload": payload.get("message", {}),
                        "seq": getattr(event, "seq", 0),
                        "sequence": getattr(event, "seq", 0),
                    })
            first_retained = page.get("first_retained_seq")
            req_after = max(0, int(after_seq))
            last_seq = page.get("last_seq")
            retention_gap = bool(
                first_retained is not None
                and first_retained > (req_after + 1)
            )
            has_gap = bool(retention_gap or page.get("gap_ranges"))
            if retention_gap:
                gap = {
                    "reason": "retention",
                    "requested_after_seq": req_after,
                    "first_retained_seq": first_retained,
                    "last_seq": last_seq,
                }
            elif page.get("gap_ranges"):
                gap = page["gap_ranges"][0]
            else:
                gap = None

            return {
                "success": True,
                "topic": clean_topic,
                "count": len(messages),
                "messages": messages,
                "cursor": page["next_seq"],
                "after_seq": req_after,
                "first_retained_seq": first_retained,
                "last_seq": last_seq,
                "has_more": page["has_more"],
                "gap_ranges": page["gap_ranges"],
                "gap": gap,
                "has_gap": has_gap,
                "cursor_reset": page["cursor_reset"],
                "durable": True,
                "replay_available": True,
            }

        now = time.time()
        with self._mu:
            self._prune_expired_locked(clean_topic, now)
            bucket = self._topics.get(clean_topic, [])
            selected = [
                item for item in bucket
                if item["timestamp"] > since_ts
                and (after_seq <= 0 or (item.get("sequence") or 0) > after_seq)
            ]
            messages = copy.deepcopy(selected[:page_limit])
            first_timestamp = bucket[0]["timestamp"] if bucket else None
            retention_gap = bool(since_timestamp > 0 and (
                since_timestamp < first_timestamp if first_timestamp is not None
                else since_timestamp <= self._ephemeral_retention_floor
            ))
        return {
            "success": True,
            "topic": clean_topic,
            "count": len(messages),
            "messages": messages,
            "cursor": None,
            "after_seq": max(0, int(after_seq)),
            "first_retained_seq": None,
            "last_seq": None,
            "has_more": len(selected) > page_limit,
            "gap_ranges": [],
            "gap": {
                "reason": "ephemeral retention",
                "first_retained_timestamp": first_timestamp,
            } if retention_gap else None,
            "has_gap": retention_gap,
            "durable": False,
            "replay_available": False,
        }
