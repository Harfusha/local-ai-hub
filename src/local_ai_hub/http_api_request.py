from __future__ import annotations

from typing import Any

from .http_server_proxy import services_module


class HttpRequestMixin:
    def setup(self) -> None:
        super().setup()
        self._head_reader = None
        if isinstance(self.rfile, services_module.io.BufferedReader):
            self._head_reader = services_module.RequestHeadReader(self.rfile.detach(), self.connection)
            self.rfile = services_module.io.BufferedReader(self._head_reader)
        try:
            keepalive = float(services_module.APP.config.get("server", {}).get("keepalive_timeout_seconds", 5.0)) if services_module.APP is not None else 5.0
            self.connection.settimeout(max(1.0, keepalive))
        except Exception:
            pass

    def handle(self) -> None:
        """Handle exactly one request per thread and release socket immediately."""
        self.close_connection = True
        self.handle_one_request()

    def handle_one_request(self) -> None:
        """Handle a single HTTP request, releasing idle keep-alive sockets fast."""
        try:
            keepalive = float(services_module.APP.config.get("server", {}).get("keepalive_timeout_seconds", 5.0)) if services_module.APP is not None else 5.0
            request_timeout = float(services_module.APP.config.get("server", {}).get("request_timeout_seconds", 210.0)) if services_module.APP is not None else 210.0
            head_reader = getattr(self, "_head_reader", None)
            if head_reader is not None:
                head_reader.idle_timeout = max(1.0, keepalive)
                head_reader.deadline = services_module.time.monotonic() + max(1.0, min(keepalive, request_timeout))
            try:
                self.connection.settimeout(max(1.0, keepalive))
            except OSError:
                pass
            self.raw_requestline = self.rfile.readline(65537)
            if len(self.raw_requestline) > 65536:
                self.requestline = ''
                self.request_version = ''
                self.command = ''
                self.send_error(414)
                return
            if not self.raw_requestline:
                self.close_connection = True
                return
            try:
                self.connection.settimeout(max(1.0, request_timeout))
            except OSError:
                pass
            if not self.parse_request():
                self.close_connection = True
                return
            if head_reader is not None:
                head_reader.deadline = None
            mname = 'do_' + self.command
            if not hasattr(self, mname):
                self.send_error(501, f"Unsupported method ({self.command!r})")
                self.close_connection = True
                return
            method = getattr(self, mname)
            method()
            self.wfile.flush()
            # The hub does not pool request handlers. Closing every response
            # releases the handler socket immediately and prevents stale
            # keep-alive sockets from surviving shutdown or app replacement.
            self.close_connection = True
        except (services_module.socket.timeout, TimeoutError):
            self.close_connection = True
            return
        except OSError as exc:
            if services_module._is_client_disconnect(exc):
                self.close_connection = True
                return
            raise

    def _common_headers(
        self, *, html: bool = False, nonce: str | None = None,
    ) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        request_headers = getattr(self, "headers", None)
        if not hasattr(request_headers, "get"):
            request_headers = {}
        header = lambda name, default="": request_headers.get(name, default)
        request_origin = str(header("Origin", "") or "").strip()
        bridge_path = str(getattr(self, "path", "")).startswith("/api/browser/") or str(getattr(self, "path", "")) == "/api/vision/review"
        if request_origin and bridge_path and services_module.APP is not None and services_module.origin_allowed(services_module.APP.config, request_origin):
            services_module.apply_cors_headers(self, request_origin, methods="POST, OPTIONS")
        if html:
            script_source = f"'nonce-{nonce}'" if nonce else "'none'"
            policy = f"default-src 'none'; connect-src 'self'; img-src 'self' data:; style-src 'unsafe-inline'; script-src {script_source}; script-src-attr 'unsafe-inline'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
            self.send_header("Content-Security-Policy", policy)

    def _handle_db_query(self, db_name: str, sql_q: str) -> dict[str, Any]:
        sql_clean = sql_q.strip()
        if not sql_clean.upper().startswith("SELECT"):
            return {"success": False, "error": "Only read-only SELECT queries are permitted."}
        forbidden = ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "REPLACE", "VACUUM", "ATTACH")
        tokens = [t.strip().upper() for t in services_module.re.split(r"[\s,()]+", sql_clean)]
        for f in forbidden:
            if f in tokens:
                return {"success": False, "error": f"Forbidden keyword in query: {f}"}
        if ";" in sql_clean.rstrip(";"):
            return {"success": False, "error": "Multi-statement queries are forbidden"}

        if services_module.APP is None:
            return {"success": False, "error": "Hub app not initialized"}
        state_dir = services_module.Path(services_module.APP.config.get("server", {}).get("state_dir", "state")).resolve()
        db_map = {
            "agent_state": state_dir / "agent_state.sqlite",
            "cache": state_dir / "cache.sqlite",
            "telemetry": state_dir / "telemetry.sqlite3",
        }
        target_db = db_map.get(db_name.lower())
        if not target_db or not target_db.is_file():
            return {"success": False, "error": f"Database not found: {db_name}"}

        def _readonly_authorizer(action: int, *_args: str | None) -> int:
            """SQLite authorizer that permits only read operations."""
            _ALLOWED = {
                services_module.sqlite3.SQLITE_SELECT,  # SELECT statements
                services_module.sqlite3.SQLITE_READ,    # Reading a column
                services_module.sqlite3.SQLITE_FUNCTION,  # Calling a function
            }
            return services_module.sqlite3.SQLITE_OK if action in _ALLOWED else services_module.sqlite3.SQLITE_DENY

        work_limit_reached = False
        try:
            uri = f"file:{target_db.as_posix()}?mode=ro"
            con = services_module.connect_sqlite(uri, uri=True, timeout_seconds=3.0, read_only=True)
            try:
                con.setlimit(services_module.sqlite3.SQLITE_LIMIT_LENGTH, services_module._DB_QUERY_MAX_RESPONSE_BYTES)
                con.set_authorizer(_readonly_authorizer)
                progress_checks = 0

                def _limit_sqlite_work() -> int:
                    nonlocal progress_checks, work_limit_reached
                    progress_checks += 1
                    if progress_checks > 5000:
                        work_limit_reached = True
                        return 1
                    return 0

                con.set_progress_handler(_limit_sqlite_work, 1000)
                cur = con.cursor()
                cur.execute(sql_clean)
                col_names = [d[0] for d in cur.description] if cur.description else []
                clean_rows = []
                while len(clean_rows) < 100:
                    batch = cur.fetchmany(1)
                    if not batch:
                        break
                    clean_row = [str(item) if isinstance(item, (bytes, bytearray)) else item for item in batch[0]]
                    clean_rows.append(clean_row)
                    result = {
                        "success": True,
                        "db": db_name,
                        "columns": col_names,
                        "rows": clean_rows,
                        "count": len(clean_rows),
                    }
                    if len(services_module.json_dumps(result, separators=(",", ":")).encode("utf-8")) > services_module._DB_QUERY_MAX_RESPONSE_BYTES:
                        return {"success": False, "error": "query result exceeded byte limit"}
                return {
                    "success": True,
                    "db": db_name,
                    "columns": col_names,
                    "rows": clean_rows,
                    "count": len(clean_rows),
                }
            finally:
                con.close()
        except services_module.sqlite3.DatabaseError as exc:
            if getattr(exc, "sqlite_errorcode", None) == getattr(services_module.sqlite3, "SQLITE_TOOBIG", -1):
                return {"success": False, "error": "query result exceeded byte limit"}
            if work_limit_reached:
                return {"success": False, "error": "query execution exceeded work limit"}
            # Sanitize error to avoid leaking internal paths
            msg = str(exc)
            if state_dir.as_posix() in msg or str(state_dir) in msg:
                msg = "query execution failed"
            return {"success": False, "error": msg}
        except Exception:
            return {"success": False, "error": "query execution failed"}

    def log_message(self, fmt: str, *args: Any) -> None:
        if services_module.os.environ.get("LOCAL_AI_HTTP_LOG") == "1":
            super().log_message(fmt, *args)

    def _begin_trace(self, path: str) -> None:
        request_id = self.headers.get("X-LocalAI-Request-ID") or services_module.uuid.uuid4().hex
        trace_id = self.headers.get("X-LocalAI-Trace-ID") or request_id
        self._trace_request_id = request_id
        self._trace_id = trace_id
        self._request_path = path
        self._request_started = services_module.time.perf_counter()
        self._telemetry_finished = False
        self._admin_operation = ""
        self._admin_audited = False
        self._admin_payload = {}
        self._trace_context_token = services_module.set_context(request_id=request_id, trace_id=trace_id, agent=self._agent())
        self._debug_trace_id = ""
        self._debug_observer_token = None
        try:
            if services_module.APP is not None:
                excluded = set(services_module.APP.config.get("observability", {}).get("exclude_http_paths", []))
                if path not in services_module.MONITOR_PATHS and not path.startswith("/api/debug-traces/") and path not in excluded:
                    services_module.APP.telemetry.record_live(kind="request", event_type="request_start", agent=self._agent(), request_id=request_id, trace_id=trace_id, action=path, success=True)
                    trace_store = getattr(services_module.APP, "debug_traces", None)
                    if trace_store is not None and bool(getattr(trace_store, "enabled", True)):
                        self._debug_trace_id = trace_store.start(kind="api_request", agent=self._agent(), action=path, source="http", request_id=request_id, initial_event=("request_received", {
                                "method": self.command, "path": path, "request_id": request_id,
                            }))
                        if self._debug_trace_id:
                            self._debug_observer_token = services_module.set_observer(
                                services_module.DebugTraceObserver(trace_store, self._debug_trace_id)
                            )
        except Exception:
            pass

    def _ensure_trace_request_id(self) -> str:
        request_id = getattr(self, "_trace_request_id", None)
        if not request_id:
            request_id = self.headers.get("X-LocalAI-Request-ID") or services_module.uuid.uuid4().hex
            self._trace_request_id = request_id
        return request_id

    @classmethod
    def _safe_debug_trace_request(cls, payload: Any) -> Any:
        """Normalize content for explicitly enabled local debug traces."""
        return services_module._normalize_trace_content(payload)

    def _finish_debug_trace(self, status: int, data: Any, *, error: str = "") -> None:
        trace_id = str(getattr(self, "_debug_trace_id", "") or "")
        store = getattr(services_module.APP, "debug_traces", None) if services_module.APP is not None else None
        if not trace_id or store is None or getattr(self, "_debug_trace_finished", False):
            return
        try:
            failed = status >= 400 or (isinstance(data, dict) and data.get("success") is False)
            if isinstance(data, dict):
                data = self._safe_debug_trace_request(data)
            else:
                data = {"output": self._safe_debug_trace_request({"output": data}).get("output", "")}
            trace_response = dict(data)
            if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599:
                trace_response["http_status_code"] = status
            response_error = (data.get("error") or data.get("message")) if isinstance(data, dict) else None
            detail = (
                str(response_error)[:512]
                if failed and isinstance(response_error, str) and response_error.strip()
                else "request failed" if failed else ""
            )
            state = "failed" if failed else "done"
            update = getattr(store, "update", None)
            if callable(update):
                update(trace_id, response=trace_response)
                finished = store.finish(trace_id, state=state, error=detail)
            else:
                finished = store.finish(trace_id, state=state, response=trace_response, error=detail)
            if not finished:
                # A concurrent event writer can briefly hold SQLite's write lock.
                # Do not mark the trace finished until the terminal write is real;
                # one bounded second attempt prevents successful requests from
                # being left visibly running without creating retry loops.
                services_module.time.sleep(0.02)
                if callable(update):
                    update(trace_id, response=trace_response)
                    finished = store.finish(trace_id, state=state, error=detail)
                else:
                    finished = store.finish(trace_id, state=state, response=trace_response, error=detail)
            if finished:
                self._debug_trace_finished = True
        except Exception:
            pass

    def _reconcile_debug_trace(self, trace: dict[str, Any]) -> dict[str, Any]:
        """Make a stale trace follow the request journal when it is terminal."""
        if not isinstance(trace, dict) or trace.get("state") not in {"queued", "running"}:
            return trace
        store = getattr(services_module.APP, "debug_traces", None) if services_module.APP is not None else None
        recovery = getattr(services_module.APP, "recovery", None) if services_module.APP is not None else None
        if store is None or recovery is None or not trace.get("request_id"):
            return trace
        try:
            journal = recovery.lookup_metadata(
                str(trace.get("request_id")),
                action=str(trace.get("action", "")),
            )
            journal_state = str((journal or {}).get("state", ""))
            if journal_state not in {"done", "failed"}:
                return trace
            error = "" if journal_state == "done" else str(trace.get("error") or "request journal finished with failure")
            store.reconcile_terminal(
                str(trace.get("trace_id", "")),
                state=journal_state,
                response=(journal or {}).get("response"),
                error=error,
            )
            trace["state"] = journal_state
            trace["error"] = error
            trace["finished_at"] = float((journal or {}).get("updated_at") or services_module.time.time())
            trace["updated_at"] = trace["finished_at"]
        except Exception:
            pass
        return trace

    def _close_trace_context(self) -> None:
        token = getattr(self, "_debug_observer_token", None)
        if token is not None:
            try:
                services_module.reset_observer(token)
            except Exception:
                pass
            self._debug_observer_token = None
        token = getattr(self, "_trace_context_token", None)
        if token is not None:
            try:
                services_module.reset_context(token)
            except Exception:
                pass
            self._trace_context_token = None

