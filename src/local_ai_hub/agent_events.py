from __future__ import annotations

from contextlib import contextmanager
from contextlib import closing
import hashlib
import stat
import subprocess
import tempfile
import json
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
            event_id=f"evt_{uuid.uuid4().hex[:16]}",
            stream_id=stream_id,
            kind=kind,
            payload=dict(payload or {}),
            idempotency_key=idempotency_key or f"idemp_{uuid.uuid4().hex[:12]}",
            correlation_id=correlation_id,
            actor=actor,
            created_at=time.time() if created_at is None else float(created_at),
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
        payload = json.loads(payload_raw) if isinstance(payload_raw, str) else dict(payload_raw)
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
        return cls(
            event_id=str(data.get("event_id") or f"evt_{uuid.uuid4().hex[:16]}"),
            stream_id=str(data.get("stream_id", "")),
            kind=str(data.get("kind", "")),
            payload=dict(data.get("payload") or {}),
            idempotency_key=str(data.get("idempotency_key") or f"idemp_{uuid.uuid4().hex[:12]}"),
            correlation_id=str(data.get("correlation_id", "")),
            actor=str(data.get("actor", "agent")),
            created_at=float(data.get("created_at") or time.time()),
            seq=int(data["seq"]) if data.get("seq") is not None else None,
        )


@dataclass(frozen=True)
class AppendResult:
    seq: int
    duplicate: bool
    event: AgentEvent | None = None
    retryable: bool = False
    error: str | None = None



class AgentStateStore:
    _append_publish_locks_guard = threading.Lock()
    _append_publish_locks: dict[str, Any] = {}
    # PRAGMA user_version belongs to this database-wide core schema. Independent
    # stores keep component versions in agent_state_schema_versions instead.
    _SCHEMA_VERSION = 1
    # Live events use this payload version implicitly; the side table stores legacy overrides.
    _CURRENT_EVENT_PAYLOAD_VERSION = 1
    _SCHEMA_PREFLIGHT_TIMEOUT_SECONDS = 5.0
    _MIGRATION_BACKUP_TIMEOUT_SECONDS = 5.0
    _MIGRATION_BACKUP_PAGES = 128
    _EVENT_COLUMNS = [
        "stream_id", "seq", "event_id", "kind", "payload", "idempotency_key",
        "correlation_id", "actor", "created_at",
    ]
    _LEGACY_EVENT_COLUMNS = [*_EVENT_COLUMNS[:-1], "schema_version", "created_at"]
    _SNAPSHOT_COLUMNS = ["snapshot_id", "stream_id", "seq", "state", "created_at"]
    _EXPECTED_OBJECT_SQL_HASHES = {
        ("index", "idx_lease_waits_tenant", "lease_waits"): "dd609992da24cef67dfdcaecef49c82b6451892d43863c9a1ff152701068273a",
        ("index", "idx_leases_root", "leases"): "a0ede5303197cc5172c5583f33a72ee1636083712d84e9d618a642a34671cc85",
        ("table", "agent_state_migrations", "agent_state_migrations"): "c05fc94a41754f655038115d920ca125256bad65f5fd82bcc8ee4cdc8ce1c164",
        ("table", "agent_state_schema_versions", "agent_state_schema_versions"): "a2884a575e1e67cfbc5b40c2e90370a89d5310197171332b6806c0b4e036a547",
        ("table", "lease_waits", "lease_waits"): "dd85a48b1dbe347ede4ca2c5e5ac8ba648090b0553e37af0b104a4b0afeedbd9",
        ("table", "leases", "leases"): "8efd0ab396d15d5557fc4dda0683cbf77f3957867131072d89c6a0fc334e9059",
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
        ("index", "idx_agent_incidents_scope", "agent_incidents"): "fcddf0dcdaa939754d8826b199dc730bfee46c1e3f9f1dc7742757a26b324fc3",
        ("index", "idx_agent_klinks_path", "agent_knowledge_links"): "a765bbe0d7e69856c925200094c53bbd726cfaec770d274d4451b18b40e52b32",
        ("index", "idx_agent_memory_expires", "agent_memory_records"): "2b572d27d7aeff30fd4f5bac34028828f8cea53b3e7a33a365ecd2ac8d62bda6",
        ("index", "idx_agent_memory_provenance_branch", "agent_memory_records"): "d2bbcbdc38fffca0533cc1fb185773d0d7063c91e7318838a15bfb4a3ef919ff",
        ("index", "idx_agent_memory_provenance_clone_id", "agent_memory_records"): "1a9eb17c7d175eecbfadac0a08d55217eef4b0edf1c4c05d66a2eb5730a3682a",
        ("index", "idx_agent_memory_provenance_repository", "agent_memory_records"): "54eb35186ea96928612021440a3a8a41e69c7af684011efcc2dd7d97900f80fe",
        ("index", "idx_agent_memory_provenance_root", "agent_memory_records"): "368aa7550b0f3c86744f5c88741b5d6fa30fe1fd8a5f218561920cf5aff86c0e",
        ("index", "idx_agent_memory_provenance_tenant", "agent_memory_records"): "38ea86fea71107fccefdd828775544796000b4f5553f3fa327049c5054aebd23",
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
        ("table", "agent_event_schema_versions", "agent_event_schema_versions"): "39c354761a018cfed96cd720de30b50665d708b39f8fe032c799e4f9e926e841",
        ("table", "agent_events", "agent_events"): "1dfef49210889dc707aa8405b65262a5a86acbc14bd940ca338293dde150b2a2",
        ("table", "agent_incidents", "agent_incidents"): "6ea9770af294cd83e1fd6dcc80a0c7950bc93d142c27d40996c5acf5a0b478d4",
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
        ("table", "agent_swarms", "agent_swarms"): "c92f1fff4b1f91185a32b0233eb3838875f62ef22f0df6d7fbea9a4bfa93c220",
        ("table", "agent_tasks_projection", "agent_tasks_projection"): "d4283f29e8560ff94ae0877f38c1fdd8020a2d8e2fc6c66aa01a58dca6339cc4",
        ("table", "agent_verification_receipts", "agent_verification_receipts"): "6aeb2ffafd9572d5325f56e99f7c62455989c3d44772bd83d3e47b6f3abe953a",
    }
    _EXPECTED_OBJECT_SQL_HASHES.update({
        ("index", "idx_agent_incidents_scope", "agent_incidents"): "fcddf0dcdaa939754d8826b199dc730bfee46c1e3f9f1dc7742757a26b324fc3",
        ("index", "idx_agent_task_search_grams_gram", "agent_task_search_grams"): "47289e8fa6b5eb7e6837a56d77ad684e26fbc466f43f0f7af252e77fb8af5e0a",
        ("index", "idx_agent_verif_task_outbox_pending", "agent_verification_task_outbox"): "50dff1b755ee28d10c80d199270f9f6b12fb2ca958b4a8948cb59ac6ff751f48",
        ("table", "agent_event_cursors", "agent_event_cursors"): "0ecf2e08637aef9d2f4a9167feb61de083e1a9d9b8b927f79ae7a58e74b2ef71",
        ("table", "agent_incidents", "agent_incidents"): "a2be58a71724133b64d9a7a773680a193488f64414ee245e378b06973454e420",
        ("table", "agent_task_search_documents", "agent_task_search_documents"): "a291a7122e95c8b2f3f6b9a9a73269489b1794ceea3f4378d9ff6155fd900f93",
        ("table", "agent_task_search_grams", "agent_task_search_grams"): "d2f7c3b733bc0ffcee4d9ee72804edc3fedc36f73f7ceca5ce18662941a13b78",
        ("table", "agent_verification_task_outbox", "agent_verification_task_outbox"): "2f17423836ca86bf09a701a71a27ead55a2c458d02bb9f29e1445a0c0fc11d17",
    })
    _ALTERNATE_OBJECT_SQL_HASHES = {
        ("table", "agent_incidents", "agent_incidents"): (
            "6ea9770af294cd83e1fd6dcc80a0c7950bc93d142c27d40996c5acf5a0b478d4",
            "43c461c1906a1c11a5558889e2c49478942b940c3e98d0a926848ead3010a63e",
            "b3f8fa5c1723ab3addf421e28c3e9e07d232a7734cc95c247aed04224f3856b0",
        ),
        # T08 adds root/version columns to the T05 swarm projection. Both layouts
        # are known; present definitions still require an exact fingerprint.
        ("table", "agent_swarms", "agent_swarms"): (
            "5ccda29c6b858caae83c2ca78296c4ff939f7ae41cdab14054e67bf374592a81",
        ),
    }
    _LEGACY_EVENTS_SQL_HASH = "80bc39dfa4ff6ca36c421c6160678bb6b1721d15753298b7c7bd2cfc4887eb65"
    _MIGRATION_HISTORY_SQL_HASH = "3a1338feacda1c31e65c7e4fe16f49b4e14f699b7c0d7a4672deca39fbca4c33"
    _LEGACY_EVENT_INDEX_HASHES = {
        ("index", "idx_agent_events_created", "agent_events"): "0c060f3923ffc6874a55f975a4a5b5ae2257fe99d3adfd783c3bcc18e763f510",
        ("index", "idx_agent_events_kind", "agent_events"): "77d2e2a836ce41786c2710ad9b46a9ff484aac89a3fc28461dcd46c5f85a9299",
    }
    _ALTERNATE_OBJECT_SQL_HASHES.update({
        ("table", "lease_waits", "lease_waits"): {
            "a866368052df7b9433b7a44d47dc262c5a76a06058b878e0249ccee791dfb17c",
            "e9a38812fd120d00228269c2e5f28f02172702355abd9127562ccf78a5c93612",
            # ScopeLeaseStore's namespace-key rebuild/rename quotes the table name.
            # Same NOT NULL columns and root-inclusive PK; no SQL normalization widening.
            "314dbe78e360c6c00133c85323b9349936d9cb2e87121e60c8ffb733b46d20aa",
        },
        ("table", "leases", "leases"): {
            "f7a165f4f68106fb33b5855d0a66532e63fde78b2675380b67fe8112096f8edd",
        },
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
        lock_key = os.path.normcase(str(self.db_path.resolve()))
        with self._append_publish_locks_guard:
            self._append_publish_lock = self._append_publish_locks.setdefault(
                lock_key, threading.RLock()
            )
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
        with self._lock:
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
                    self._migrate_known_schema(
                        con,
                        existed_before_open=existed_before_open,
                    )
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
                            -- Sparse legacy overrides; current payload version is implicit.
                            CREATE TABLE IF NOT EXISTS agent_event_schema_versions (
                                stream_id TEXT NOT NULL,
                                seq INTEGER NOT NULL,
                                schema_version INTEGER NOT NULL,
                                PRIMARY KEY (stream_id, seq)
                            )
                        """)
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

    def _verified_migration_backup(self, source: sqlite3.Connection) -> Path:
        """Create and verify a snapshot before changing a legacy durable database."""
        backup_path = self.db_path.with_name(
            f"{self.db_path.name}.migration-v0-v1-{time.time_ns()}.bak"
        )
        with backup_path.open("xb"):
            pass
        destination = sqlite3.connect(backup_path)
        try:
            source.backup(destination)
            quick_check = destination.execute("PRAGMA quick_check").fetchone()
            if not quick_check or str(quick_check[0]).lower() != "ok":
                raise sqlite3.DatabaseError("agent state migration backup failed quick_check")
            source_schema = source.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
            ).fetchall()
            backup_schema = destination.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
            ).fetchall()
            if source_schema != backup_schema:
                raise sqlite3.DatabaseError("agent state migration backup schema mismatch")
        except Exception:
            destination.close()
            backup_path.unlink(missing_ok=True)
            raise
        destination.close()
        return backup_path

    def _preflight_schema_read_only(self) -> None:
        deadline = time.monotonic() + self._SCHEMA_PREFLIGHT_TIMEOUT_SECONDS
        suffixes = ("", "-wal", "-journal")
        original_paths = [Path(f"{self.db_path}{suffix}") for suffix in suffixes]

        def signatures() -> tuple[tuple[bool, int, int], ...]:
            result = []
            for path in original_paths:
                try:
                    stat = path.stat()
                except FileNotFoundError:
                    result.append((False, 0, 0))
                else:
                    result.append((True, stat.st_size, stat.st_mtime_ns))
            return tuple(result)

        before = signatures()
        with tempfile.TemporaryDirectory(prefix="agent-state-preflight-") as temporary:
            snapshot_db = Path(temporary) / self.db_path.name
            for suffix, present in zip(suffixes, before):
                if not present[0] or suffix == "-shm":
                    continue
                source_path = Path(f"{self.db_path}{suffix}")
                destination_path = Path(f"{snapshot_db}{suffix}")
                with source_path.open("rb") as reader, destination_path.open("wb") as writer:
                    while chunk := reader.read(1024 * 1024):
                        writer.write(chunk)
                        if time.monotonic() >= deadline:
                            raise TimeoutError("agent_state schema preflight time limit exceeded")
            if signatures() != before:
                raise sqlite3.OperationalError(
                    "database is locked: agent_state changed during schema preflight"
                )

            uri = f"{snapshot_db.resolve().as_uri()}?mode=ro"
            try:
                remaining = max(0.001, deadline - time.monotonic())
                with closing(sqlite3.connect(uri, uri=True, timeout=min(0.01, remaining))) as con:
                    busy_ms = max(1, min(10, int(remaining * 1000)))
                    con.execute(f"PRAGMA busy_timeout={busy_ms}")
                    con.set_progress_handler(
                        lambda: 1 if time.monotonic() >= deadline else 0,
                        1000,
                    )
                    try:
                        self._classify_schema(con)
                    except RuntimeError as exc:
                        database_name = self.db_path.name
                        if database_name.endswith(".sqlite3"):
                            database_name = database_name[:-1]
                        timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
                        recovery_path = self.db_path.with_name(
                            f"{database_name}.schema-mismatch-{timestamp}-{uuid.uuid4().hex[:12]}.sqlite3"
                        )
                        try:
                            recovery_path = self._verified_backup(
                                con,
                                destination_path=recovery_path,
                            )
                        except Exception as backup_error:
                            raise DurableSchemaMismatchError(
                                self.db_path,
                                [str(exc)],
                                None,
                                str(backup_error),
                            ) from exc
                        raise DurableSchemaMismatchError(
                            self.db_path,
                            [str(exc)],
                            recovery_path,
                        ) from exc
            except RuntimeError:
                raise
            except sqlite3.DatabaseError as exc:
                if time.monotonic() >= deadline:
                    raise TimeoutError("agent_state schema preflight time limit exceeded") from exc
                raise
            if time.monotonic() >= deadline:
                raise TimeoutError("agent_state schema preflight time limit exceeded")
            if signatures() != before:
                raise sqlite3.OperationalError(
                    "database is locked: agent_state changed during schema preflight"
                )

    @classmethod
    def _classify_schema(cls, con: sqlite3.Connection) -> tuple[Any, ...]:
        version = int(con.execute("PRAGMA user_version").fetchone()[0])
        if version > cls._SCHEMA_VERSION or version < 0:
            raise RuntimeError(f"unsupported agent state schema version: {version}")

        event_columns = cls._columns(con, "agent_events")
        snapshot_columns = cls._columns(con, "agent_snapshots")
        raw_objects = tuple(sorted(
            (str(row[0]), str(row[1]), str(row[2]), " ".join(str(row[3] or "").split()).casefold())
            for row in con.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master "
                "WHERE (name NOT LIKE 'sqlite_%' OR name='sqlite_sequence') "
                "AND type IN ('table','index','view','trigger')"
            )
        ))
        objects = []
        for object_type, name, table, sql in raw_objects:
            # Canonical sqlite_master SQL fingerprint covers column types, nullability,
            # primary/foreign keys, checks, and full index predicates/expressions.
            key = (object_type, name, table)
            expected_hash = cls._EXPECTED_OBJECT_SQL_HASHES.get(key)
            if key == ("table", "agent_schema_migrations", "agent_schema_migrations"):
                expected_hash = cls._MIGRATION_HISTORY_SQL_HASH
            if key == ("table", "agent_events", "agent_events") and version == 0:
                if event_columns == cls._LEGACY_EVENT_COLUMNS:
                    expected_hash = cls._LEGACY_EVENTS_SQL_HASH
            if version == 0 and event_columns == cls._LEGACY_EVENT_COLUMNS:
                expected_hash = cls._LEGACY_EVENT_INDEX_HASHES.get(key, expected_hash)
            actual_hash = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            if expected_hash is None:
                raise RuntimeError(f"unsupported agent_state schema object: {object_type} {name}")
            if (
                actual_hash != expected_hash
                and actual_hash not in cls._ALTERNATE_OBJECT_SQL_HASHES.get(key, ())
            ):
                raise RuntimeError(f"unsupported agent_state schema object definition: {object_type} {name}")
            objects.append((object_type, name, table, sql))
        objects = tuple(objects)

        tables = {name for object_type, name, _, _ in objects if object_type == "table"}

        if version == cls._SCHEMA_VERSION:
            if event_columns != cls._EVENT_COLUMNS or snapshot_columns != cls._SNAPSHOT_COLUMNS:
                raise RuntimeError("unsupported agent_state schema layout")
            event_version_columns = cls._columns(con, "agent_event_schema_versions")
            if event_version_columns == ["stream_id", "seq", "schema_version"]:
                if "agent_schema_migrations" in tables:
                    markers = [int(row[0]) for row in con.execute(
                        "SELECT version FROM agent_schema_migrations ORDER BY version"
                    )]
                    if markers != [1]:
                        raise RuntimeError("unsupported agent_state schema migration history")
                layout = "current"
            elif not event_version_columns:
                layout = "current-unversioned"
            else:
                raise RuntimeError("unsupported agent_state schema layout")
        else:
            auxiliary_only_tables = {
                "agent_state_migrations", "agent_state_schema_versions",
                "leases", "lease_waits",
            }
            is_empty = (
                not event_columns and not snapshot_columns
                and tables.issubset(auxiliary_only_tables)
            )
            is_current_unversioned = (
                version == 0
                and event_columns == cls._EVENT_COLUMNS
                and snapshot_columns == cls._SNAPSHOT_COLUMNS
                and cls._columns(con, "agent_event_schema_versions")
                == ["stream_id", "seq", "schema_version"]
            )
            if is_current_unversioned and "agent_schema_migrations" in tables:
                markers = [int(row[0]) for row in con.execute(
                    "SELECT version FROM agent_schema_migrations ORDER BY version"
                )]
                if markers != [1]:
                    raise RuntimeError("unsupported agent_state schema migration history")
            is_current_v0 = (
                event_columns == cls._EVENT_COLUMNS
                and snapshot_columns == cls._SNAPSHOT_COLUMNS
                and "agent_schema_migrations" not in tables
                and "agent_event_schema_versions" not in tables
            )
            is_historical_v0 = (
                event_columns == cls._LEGACY_EVENT_COLUMNS
                and snapshot_columns == cls._SNAPSHOT_COLUMNS
                and cls._columns(con, "agent_schema_migrations")
                == ["version", "applied_at", "description"]
                and "agent_event_schema_versions" not in tables
            )
            if is_historical_v0:
                markers = [int(row[0]) for row in con.execute(
                    "SELECT version FROM agent_schema_migrations ORDER BY version"
                )]
                if markers != [1]:
                    raise RuntimeError("unsupported agent_state schema migration history")
            if is_empty:
                layout = "empty"
            elif is_current_unversioned:
                # Existing current event metadata is preserved; _ensure_schema owns the v0->v1 backup/write.
                layout = "current"
            elif is_current_v0:
                layout = "current-v0"
            elif is_historical_v0:
                layout = "historical-v0"
            else:
                raise RuntimeError("unsupported agent_state schema layout")

        # Module-owned tables and indexes are optional until their stores are used.
        # Validate every object that is present above, but require only the core
        # event schema here so partial subsystem initialization survives restart.
        required_objects = {
            ("table", "agent_events", "agent_events"),
            ("table", "agent_snapshots", "agent_snapshots"),
        }
        migration_history = ("table", "agent_schema_migrations", "agent_schema_migrations")
        event_versions = ("table", "agent_event_schema_versions", "agent_event_schema_versions")
        if layout == "current":
            required_objects.add(event_versions)
        elif layout in {"current-v0", "current-unversioned"}:
            pass
        elif layout == "historical-v0":
            required_objects.add(migration_history)
        elif layout == "empty":
            required_objects.clear()

        present_objects = {(object_type, name, table) for object_type, name, table, _ in objects}
        task_profile_tables = {
            "agent_tasks_projection",
            "agent_verification_receipts",
            "agent_budgets",
            "agent_change_intents",
            "agent_outcomes",
        }
        has_task_events = bool(event_columns) and con.execute(
            "SELECT 1 FROM agent_events WHERE kind LIKE 'task.%' "
            "AND kind != 'task.updated' LIMIT 1"
        ).fetchone() is not None
        if layout != "empty" and (bool(tables & task_profile_tables) or has_task_events):
            required_objects.add(("table", "agent_tasks_projection", "agent_tasks_projection"))

        missing_objects = sorted(required_objects - present_objects)
        if missing_objects:
            details_list = []
            for object_type, name, _ in missing_objects:
                if object_type == "table" and name == "agent_tasks_projection" and has_task_events:
                    details_list.append("table agent_tasks_projection is missing while related events remain")
                else:
                    details_list.append(f"{object_type} {name}")
            details = ", ".join(details_list)
            raise RuntimeError(
                f"unsupported agent_state schema missing required schema objects: {details}"
            )

        return (version, layout, event_columns, snapshot_columns, objects)

    @classmethod
    def _migrate_known_schema(cls, con: sqlite3.Connection, *, existed_before_open: bool) -> None:
        """Migrate known v0 layouts only; callers preflight nonempty files read-only."""
        initial = cls._classify_schema(con)
        version, layout = initial[:2]
        if layout == "current" and version == cls._SCHEMA_VERSION:
            return

        if existed_before_open:
            baseline_data_version = int(con.execute("PRAGMA data_version").fetchone()[0])
            cls._verified_backup(con)
            after_backup = int(con.execute("PRAGMA data_version").fetchone()[0])
            con.execute("BEGIN IMMEDIATE")
            try:
                locked = cls._classify_schema(con)
            except Exception:
                con.rollback()
                raise
            if locked[0] == cls._SCHEMA_VERSION:
                con.rollback()
                return
            locked_data_version = int(con.execute("PRAGMA data_version").fetchone()[0])
            if (
                after_backup != baseline_data_version
                or locked_data_version != after_backup
                or locked != initial
            ):
                con.rollback()
                raise RuntimeError("agent_state changed before migration; retry initialization")
        else:
            con.execute("BEGIN IMMEDIATE")

        try:
            con.execute("""
                -- Sparse legacy overrides; current payload version is implicit.
                CREATE TABLE IF NOT EXISTS agent_event_schema_versions (
                    stream_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    schema_version INTEGER NOT NULL,
                    PRIMARY KEY (stream_id, seq)
                )
            """)
            if layout == "historical-v0":
                con.execute("""
                    CREATE TABLE agent_events_v1 (
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
                con.execute("""
                    INSERT INTO agent_events_v1 (
                        stream_id, seq, event_id, kind, payload, idempotency_key,
                        correlation_id, actor, created_at
                    ) SELECT stream_id, seq, event_id, kind, payload, idempotency_key,
                        correlation_id, actor, created_at FROM agent_events
                """)
                con.execute("""
                    INSERT INTO agent_event_schema_versions (stream_id, seq, schema_version)
                    SELECT stream_id, seq, schema_version FROM agent_events
                    WHERE schema_version != ?
                """, (cls._CURRENT_EVENT_PAYLOAD_VERSION,))
                con.execute("DROP TABLE agent_events")
                con.execute("""
                    CREATE TABLE agent_events (
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
                con.execute("""
                    INSERT INTO agent_events (
                        stream_id, seq, event_id, kind, payload, idempotency_key,
                        correlation_id, actor, created_at
                    ) SELECT stream_id, seq, event_id, kind, payload, idempotency_key,
                        correlation_id, actor, created_at FROM agent_events_v1
                """)
                con.execute("DROP TABLE agent_events_v1")
            elif layout == "empty":
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
                con.execute("""
                    CREATE TABLE IF NOT EXISTS agent_snapshots (
                        snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        stream_id TEXT NOT NULL,
                        seq INTEGER NOT NULL,
                        state TEXT NOT NULL,
                        created_at REAL NOT NULL
                    )
                """)
            con.execute("CREATE INDEX IF NOT EXISTS idx_agent_events_created ON agent_events (created_at)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_agent_events_kind ON agent_events (kind)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_agent_snapshots_stream ON agent_snapshots (stream_id, seq DESC)")
        except Exception:
            con.rollback()
            raise

    @staticmethod
    def _columns(con: sqlite3.Connection, table: str) -> list[str]:
        return [str(row[1]) for row in con.execute(f'PRAGMA table_info("{table}")')]

    @classmethod
    def _schema_signature(cls, con: sqlite3.Connection) -> tuple[tuple[str, str, str, str], ...]:
        return tuple(sorted(
            (str(row[0]), str(row[1]), str(row[2]), " ".join(str(row[3] or "").split()).casefold())
            for row in con.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master "
                "WHERE (name NOT LIKE 'sqlite_%' OR name='sqlite_sequence') "
                "AND type IN ('table','index','view','trigger')"
            )
        ))

    @staticmethod
    def _hash_part(digest: Any, tag: bytes, value: bytes) -> None:
        digest.update(tag)
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)

    @classmethod
    def _content_fingerprint(
        cls,
        con: sqlite3.Connection,
        check_deadline: Any = lambda: None,
    ) -> tuple[tuple[tuple[str, int], ...], str]:
        digest = hashlib.sha256()
        row_counts = []
        tables = [str(row[0]) for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND (name NOT LIKE 'sqlite_%' OR name='sqlite_sequence') ORDER BY name"
        )]
        for table in tables:
            check_deadline()
            quoted = table.replace('"', '""')
            columns = [str(row[1]) for row in con.execute(f'PRAGMA table_info("{quoted}")')]
            cls._hash_part(digest, b"T", table.encode("utf-8"))
            for column in columns:
                cls._hash_part(digest, b"C", column.encode("utf-8"))
            order_by = ", ".join(f'"{column.replace(chr(34), chr(34) * 2)}"' for column in columns)
            query = f'SELECT * FROM "{quoted}" ORDER BY {order_by}' if order_by else f'SELECT * FROM "{quoted}"'
            row_count = 0
            for row in con.execute(query):
                check_deadline()
                row_count += 1
                digest.update(b"R")
                for value in row:
                    if value is None:
                        cls._hash_part(digest, b"N", b"")
                    elif isinstance(value, bytes):
                        cls._hash_part(digest, b"B", value)
                    elif isinstance(value, float):
                        cls._hash_part(digest, b"F", value.hex().encode("ascii"))
                    elif isinstance(value, int):
                        cls._hash_part(digest, b"I", str(value).encode("ascii"))
                    else:
                        cls._hash_part(digest, b"S", str(value).encode("utf-8", "surrogatepass"))
            cls._hash_part(digest, b"Q", str(row_count).encode("ascii"))
            row_counts.append((table, row_count))
            digest.update(b"E")
        return tuple(row_counts), digest.hexdigest()

    @classmethod
    def _verify_backup(
        cls,
        source: sqlite3.Connection,
        backup: sqlite3.Connection,
        *,
        deadline: float | None = None,
    ) -> None:
        deadline = deadline if deadline is not None else time.monotonic() + cls._MIGRATION_BACKUP_TIMEOUT_SECONDS

        def check_deadline() -> None:
            if time.monotonic() >= deadline:
                raise TimeoutError("agent_state migration backup time limit exceeded")

        def sql_progress() -> int:
            return 1 if time.monotonic() >= deadline else 0

        remaining_ms = max(1, min(10, int(max(0.001, deadline - time.monotonic()) * 1000)))
        source.execute(f"PRAGMA busy_timeout={remaining_ms}")
        backup.execute(f"PRAGMA busy_timeout={remaining_ms}")
        source.set_progress_handler(sql_progress, 100)
        backup.set_progress_handler(sql_progress, 100)
        try:
            check_deadline()
            integrity_rows = [str(row[0]) for row in backup.execute("PRAGMA integrity_check")]
            check_deadline()
            if integrity_rows != ["ok"]:
                raise RuntimeError(
                    "agent_state migration backup failed integrity check: "
                    + "; ".join(integrity_rows[:8])
                )
            if int(backup.execute("PRAGMA user_version").fetchone()[0]) != int(
                source.execute("PRAGMA user_version").fetchone()[0]
            ):
                raise RuntimeError("agent_state migration backup version mismatch")
            if cls._schema_signature(source) != cls._schema_signature(backup):
                raise RuntimeError("agent_state migration backup schema definition mismatch")
            source_counts, source_hash = cls._content_fingerprint(source, check_deadline)
            backup_counts, backup_hash = cls._content_fingerprint(backup, check_deadline)
            if source_counts != backup_counts:
                raise RuntimeError("agent_state migration backup table row count mismatch")
            if source_hash != backup_hash:
                raise RuntimeError("agent_state migration backup content hash mismatch")
            check_deadline()
        except sqlite3.OperationalError as exc:
            if time.monotonic() >= deadline or "locked" in str(exc).casefold() or "busy" in str(exc).casefold():
                raise TimeoutError("agent_state migration backup time limit exceeded") from exc
            raise
        finally:
            source.set_progress_handler(None, 0)
            backup.set_progress_handler(None, 0)

    @staticmethod
    def _backup_path_matches(path: Path, identity: tuple[int, int]) -> bool:
        try:
            info = path.lstat()
        except FileNotFoundError:
            return False
        return stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == identity

    @classmethod
    def _reserve_backup_destination(cls, path: Path) -> tuple[int, int]:
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(f"{path}{suffix}")
            try:
                sidecar.lstat()
            except FileNotFoundError:
                continue
            raise FileExistsError(f"agent_state backup sidecar already exists: {sidecar}")

        flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        info = os.fstat(descriptor)
        identity = (info.st_dev, info.st_ino)
        try:
            if os.name == "nt":
                from .process_utils import run_hidden

                try:
                    # USERNAME is caller-controlled, not proof of the process account.
                    account = run_hidden(
                        ["whoami"],
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=1.0,
                    ).stdout.strip()
                    if (
                        not account
                        or len(account.split("\\")) != 2
                        or not all(account.split("\\"))
                        or any(character in account for character in "\r\n\x00")
                    ):
                        raise PermissionError("agent_state backup process account is unknown")
                    run_hidden(
                        ["icacls", str(path), "/inheritance:r", "/grant:r", f"{account}:(F)"],
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=1.0,
                    )
                except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
                    raise PermissionError("agent_state backup permissions could not be secured") from exc
            else:
                os.fchmod(descriptor, 0o600)
                if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o600:
                    raise PermissionError("agent_state backup permissions are not private")

            if not cls._backup_path_matches(path, identity):
                raise RuntimeError("agent_state backup destination changed during secure creation")
            return identity
        except BaseException:
            os.close(descriptor)
            descriptor = -1
            try:
                if cls._backup_path_matches(path, identity):
                    path.unlink()
            except OSError:
                pass
            raise
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    @classmethod
    def _remove_owned_backup_artifacts(
        cls,
        path: Path,
        identity: tuple[int, int],
    ) -> None:
        if not cls._backup_path_matches(path, identity):
            return
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(f"{path}{suffix}")
            try:
                info = sidecar.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISREG(info.st_mode):
                sidecar.unlink()
        if cls._backup_path_matches(path, identity):
            path.unlink()

    @classmethod
    def _verified_backup(
        cls,
        source: sqlite3.Connection,
        *,
        destination_path: Path | None = None,
    ) -> Path:
        timeout = float(cls._MIGRATION_BACKUP_TIMEOUT_SECONDS)
        deadline = time.monotonic() + timeout
        if timeout <= 0:
            raise TimeoutError("agent_state migration backup time limit exceeded")

        def check_deadline() -> None:
            if time.monotonic() >= deadline:
                raise TimeoutError("agent_state migration backup time limit exceeded")

        def backup_progress(_status: int, _remaining: int, _total: int) -> None:
            check_deadline()

        remaining_ms = max(1, min(10, int(timeout * 1000)))
        source.set_progress_handler(lambda: 1 if time.monotonic() >= deadline else 0, 100)
        backup_path: Path | None = None
        backup: sqlite3.Connection | None = None
        backup_identity: tuple[int, int] | None = None
        verified = False
        try:
            source.execute(f"PRAGMA busy_timeout={remaining_ms}")
            check_deadline()
            db_path = str(source.execute("PRAGMA database_list").fetchone()[2])
            backup_path = destination_path or Path(
                f"{db_path}.migration-v0-v1-{uuid.uuid4().hex}.bak"
            )
            backup_identity = cls._reserve_backup_destination(backup_path)
            backup = sqlite3.connect(backup_path, timeout=min(0.1, timeout))
            if not cls._backup_path_matches(backup_path, backup_identity):
                raise RuntimeError("agent_state backup destination changed before SQLite opened it")
            backup.execute(f"PRAGMA busy_timeout={remaining_ms}")
            source.backup(
                backup,
                pages=cls._MIGRATION_BACKUP_PAGES,
                progress=backup_progress,
                sleep=min(0.002, timeout),
            )
            check_deadline()
            backup.commit()
            cls._verify_backup(source, backup, deadline=deadline)
            verified = True
        except sqlite3.OperationalError as exc:
            if (
                time.monotonic() >= deadline
                or "locked" in str(exc).casefold()
                or "busy" in str(exc).casefold()
            ):
                raise TimeoutError("agent_state migration backup time limit exceeded") from exc
            raise
        finally:
            source.set_progress_handler(None, 0)
            if backup is not None:
                backup.close()
            if not verified and backup_path is not None and backup_identity is not None:
                cls._remove_owned_backup_artifacts(backup_path, backup_identity)
        if backup_path is None:
            raise RuntimeError("agent_state migration backup path unavailable")
        return backup_path


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
            con = connect_sqlite(self.db_path, isolation_level=None, timeout_seconds=0.25)
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
        # Keep initialization/migration failures visible to the state-store caller.
        # event_page deliberately converts read failures to a bounded API envelope;
        # performing schema setup first preserves the original migration error and
        # lets callers safely retry without mistaking it for an empty/unavailable page.
        if self.enabled and self.db_path.exists():
            try:
                self._ensure_schema()
            except DurableSchemaMismatchError as exc:
                # Preserve the established opaque response for this legacy layout;
                # other durable-schema failures retain their actionable diagnosis.
                mismatch = " ".join(exc.mismatches)
                if mismatch == (
                    "unsupported agent_state schema object definition: table agent_events"
                ):
                    raise RuntimeError(
                        "event_page_unavailable: Event page could not be read."
                    ) from None
                raise
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
            return {
                "snapshot_id": snap_id,
                "seq": seq,
                "state": json.loads(raw_state),
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
                        con.execute(
                            "DELETE FROM agent_event_schema_versions WHERE stream_id = ? AND seq < ?",
                            (clean_stream, first_retained_seq),
                        )
                        cur_ev = con.execute(
                            "DELETE FROM agent_events WHERE stream_id = ? AND seq < ?",
                            (clean_stream, first_retained_seq),
                        )
                    else:
                        con.execute(
                            "DELETE FROM agent_event_schema_versions WHERE stream_id = ?",
                            (clean_stream,),
                        )
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

    def __init__(self, state_store: AgentStateStore | None = None, max_age_seconds: float = 3600.0):
        self.state_store = state_store
        self.max_age_seconds = float(max_age_seconds)
        self._topics: dict[str, list[dict[str, Any]]] = {}
        self._subscribers: dict[str, dict[str, queue.Queue[dict[str, Any]]]] = {}
        self._mu = threading.Lock()

    @classmethod
    def get_default(cls, state_store: AgentStateStore | None = None) -> SwarmPubSub:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(state_store)
            elif state_store is not None:
                cls._instance.state_store = state_store
            return cls._instance

    def subscribe(self, topic: str, maxsize: int = 100) -> tuple[str, queue.Queue[dict[str, Any]]]:
        clean_topic = topic.strip().lower()
        sub_id = f"sub_{uuid.uuid4().hex[:10]}"
        q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=max(10, min(int(maxsize), 1000)))
        with self._mu:
            self._subscribers.setdefault(clean_topic, {})[sub_id] = q
        return sub_id, q

    def unsubscribe(self, topic: str, sub_id: str) -> bool:
        clean_topic = topic.strip().lower()
        with self._mu:
            subs = self._subscribers.get(clean_topic, {})
            if sub_id in subs:
                del subs[sub_id]
                return True
        return False

    def _prune_expired_locked(self, clean_topic: str, now: float) -> None:
        cutoff = now - self.max_age_seconds
        messages = self._topics.get(clean_topic, [])
        if messages and messages[0]["timestamp"] < cutoff:
            self._topics[clean_topic] = [message for message in messages if message["timestamp"] >= cutoff]

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
        clean_topic = topic.strip().lower()
        now = time.time()
        msg_payload = message if isinstance(message, dict) else {"text": str(message)}
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
            bucket = self._topics.setdefault(clean_topic, [])
            bucket.append(event)
            if len(bucket) > 200:
                self._topics[clean_topic] = bucket[-200:]
            self._prune_expired_locked(clean_topic, now)
            for q in list(self._subscribers.get(clean_topic, {}).values()):
                self._enqueue(q, event)
        result = {
            "success": True,
            "topic": clean_topic,
            "message_id": event_id,
            "timestamp": now,
            "cursor": sequence,
            "durable": durable,
            "replay_available": durable,
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
        clean_topic = topic.strip().lower()
        page_limit = max(1, min(int(limit), 1000))
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
            messages = [
                item for item in bucket
                if item["timestamp"] > since_timestamp
                and (after_seq <= 0 or (item.get("sequence") or 0) > after_seq)
            ][:page_limit]
            first_timestamp = bucket[0]["timestamp"] if bucket else None
            retention_gap = bool(first_timestamp is not None and since_timestamp < first_timestamp and since_timestamp > 0)
        return {
            "success": True,
            "topic": clean_topic,
            "count": len(messages),
            "messages": messages,
            "cursor": None,
            "after_seq": max(0, int(after_seq)),
            "first_retained_seq": None,
            "last_seq": None,
            "has_more": False,
            "gap_ranges": [],
            "gap": {
                "reason": "ephemeral retention",
                "first_retained_timestamp": first_timestamp,
            } if retention_gap else None,
            "has_gap": retention_gap,
            "durable": False,
            "replay_available": False,
        }
