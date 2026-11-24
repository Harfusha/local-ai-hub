from __future__ import annotations

from typing import Any

from .http_server_proxy import services_module


class HttpAuthorizationMixin:
    def _memory_project_identity(self, requested_root: Any) -> tuple[str, str] | None:
        """Resolve memory project identity from server project configuration."""
        if not requested_root:
            return ("", "")
        try:
            if services_module.APP is None:
                return None
            import sys
            project_config_module = sys.modules.get("local_ai_hub.project_config")
            if project_config_module is None:
                from . import project_config as project_config_module
            resolve_project_context = getattr(project_config_module, "resolve_project_context")
            from .state_paths import configured_state_dir

            context = resolve_project_context(requested_root, configured_state_dir(services_module.APP.config))
            root = str(services_module.Path(context.root).resolve(strict=True))
            repository_id = getattr(context, "coordination_id", None)
            if not isinstance(repository_id, str) or not repository_id or repository_id != repository_id.strip() or "\x00" in repository_id:
                return None
            req_norm = str(services_module.Path(requested_root).resolve(strict=True)) if isinstance(requested_root, str) and requested_root.strip() else requested_root
            if services_module._strict_root_path(root) != services_module._strict_root_path(req_norm):
                return None
            return root, repository_id
        except Exception:
            return None

    def _agent(self) -> str:
        return services_module._safe_agent(self)

    def _authorization_permission(self) -> str:
        path = services_module.urlparse(str(getattr(self, "path", ""))).path
        method = str(getattr(self, "command", "GET")).upper()
        if (
            path.startswith("/api/admin/")
            or path.startswith("/api/maintenance/")
            or (path == "/api/mode" and method not in {"GET", "HEAD"})
        ):
            return "admin"
        if method in {"GET", "HEAD"}:
            return "monitor" if path in services_module.MONITOR_PATHS else "read"
        return "write"

    def _required_permission(self) -> str:
        path = services_module.urlparse(str(getattr(self, "path", ""))).path.rstrip("/") or "/"
        method = str(getattr(self, "command", "GET")).upper()
        read_only = method in {"GET", "HEAD"}
        if path.startswith("/api/agent-state/"):
            return "agent_tasks:read" if read_only else "agent_tasks:write"
        if (
            path.startswith("/api/admin/")
            or path.startswith("/api/maintenance/")
            or (path == "/api/mode" and not read_only)
        ):
            return "admin:read" if read_only else "admin:write"
        if path in {"/", "/dashboard", "/api/metrics", "/api/status"}:
            return "dashboard:read"
        return "api:read" if read_only else "api:write"

    def _loopback_client(self) -> bool:
        try:
            address = str(self.client_address[0]).split("%", 1)[0]
            return services_module.ipaddress.ip_address(address).is_loopback
        except (AttributeError, IndexError, TypeError, ValueError):
            return False

    def _authorized(self, action: str | None = None, *, permission: str | None = None) -> bool:
        self._authorization_actor = "unrecognized"
        self._authorization_root = None
        self._authorization_permissions = frozenset()
        self._authorization_status = 403
        config = getattr(services_module.APP, "config", {}) if services_module.APP is not None else {}
        security = config.get("security", {}) if isinstance(config, dict) else {}
        if not isinstance(security, dict):
            return False
        retired_fields = {
            "api_token", "supervisor_token", "action_tokens", "api_token_permissions",
            "api_token_tenant", "api_token_principal", "tenant_derivation_key", "users",
        }
        if retired_fields.intersection(security):
            return False
        is_loopback = services_module._is_loopback_client_address(getattr(self, "client_address", None))
        if not is_loopback:
            return False
        self._authorization_actor = "local"
        self._authorization_permissions = frozenset()
        self._authorization_status = 200
        return True

    def _validate_host_and_origin(self) -> bool:
        """Validate Host and Origin headers to protect against DNS rebinding and cross-origin attacks."""
        if services_module.APP is None:
            return True
        request_headers = getattr(self, "headers", None)
        if not hasattr(request_headers, "get"):
            request_headers = {}
        header = lambda name, default="": request_headers.get(name, default)
        if (
            header("X-LocalAI-Client", "") == "dashboard"
            and str(header("Sec-Fetch-Site", "")).strip().lower() != "same-origin"
        ):
            self._send(403, {"success": False, "error": "forbidden: dashboard requests must be same-origin"})
            return False
        if (
            header("X-LocalAI-Client", "") == "dashboard"
            and str(getattr(self, "command", "GET")).upper() not in {"GET", "HEAD"}
            and not str(header("Origin", "")).strip()
        ):
            self._send(403, {"success": False, "error": "forbidden: dashboard mutation requires Origin"})
            return False
        host_header = str(header("Host", "") or "").strip()
        host_port: int | None = None
        if host_header:
            try:
                parsed_host = services_module.urlparse(f"//{host_header}")
                host_name = str(parsed_host.hostname or "").lower()
                host_port = parsed_host.port
                valid_host_syntax = not (
                    parsed_host.username is not None
                    or parsed_host.password is not None
                    or parsed_host.path
                    or parsed_host.params
                    or parsed_host.query
                    or parsed_host.fragment
                    or host_header.endswith(":")
                    or host_port == 0
                )
            except ValueError:
                host_name = ""
                valid_host_syntax = False
            allowed_hosts = {"127.0.0.1", "localhost", "::1", "testserver"}
            server_cfg = services_module.APP.config.get("server", {})
            bind = str(server_cfg.get("bind", "")).strip("[]").lower()
            if bind and bind not in {"0.0.0.0", "::"}:
                allowed_hosts.add(bind)

            if not valid_host_syntax or host_name not in allowed_hosts:
                self._send(403, {"success": False, "error": "forbidden: invalid Host header"})
                return False

        origin_header = str(header("Origin", "") or "").strip()
        if origin_header:
            try:
                parsed_origin = services_module.urlparse(origin_header)
                origin_host = str(parsed_origin.hostname or "").lower()
                origin_scheme = parsed_origin.scheme.lower()
                origin_port = parsed_origin.port
                valid_origin_syntax = not (
                    parsed_origin.username is not None
                    or parsed_origin.password is not None
                    or parsed_origin.path
                    or parsed_origin.params
                    or parsed_origin.query
                    or parsed_origin.fragment
                    or origin_port == 0
                )
            except ValueError:
                origin_host = ""
                origin_scheme = ""
                origin_port = None
                valid_origin_syntax = False
            allowed_origins = {"127.0.0.1", "localhost", "::1", "testserver"}
            server_cfg = services_module.APP.config.get("server", {})
            bind = str(server_cfg.get("bind", "")).strip("[]").lower()
            if bind and bind not in {"0.0.0.0", "::"}:
                allowed_origins.add(bind)

            bridge_origin = False
            if str(getattr(self, "path", "")).startswith("/api/browser/") or str(getattr(self, "path", "")) == "/api/vision/review":
                bridge_origin = services_module.origin_allowed(services_module.APP.config, origin_header)
            local_origin_valid = (
                origin_scheme in {"http", "https"}
                and valid_origin_syntax
                and origin_host in allowed_origins
                and (host_port or 80)
                == (origin_port or (443 if origin_scheme == "https" else 80))
            )
            if not local_origin_valid and not bridge_origin:
                self._send(403, {"success": False, "error": "forbidden: cross-origin requests are not allowed"})
                return False
        return True

    def _require_authorized(self, permission: str | None = None) -> bool:
        if not self._validate_host_and_origin():
            return False
        if not self._reject_identity_fields(services_module.parse_qs(services_module.urlparse(str(getattr(self, "path", ""))).query, keep_blank_values=True)):
            return False
        action = services_module._http_admin_action(
            str(getattr(self, "command", "")),
            services_module.urlparse(str(getattr(self, "path", ""))).path,
        )
        self._admin_action = action or ""
        self._admin_result_audited = False
        authorized = self._authorized(action, permission=permission)
        if not authorized:
            if action:
                self._audit_admin_authorization(action, allowed=False)
            status = int(getattr(self, "_authorization_status", 401))
            self._send(status, {"success": False, "error": "forbidden" if status == 403 else "unauthorized"})
            return False
        audit_accepted = self._audit_admin_authorization(action, allowed=True) if action else True
        mutation = str(getattr(self, "command", "GET")).upper() not in {"GET", "HEAD", "OPTIONS"}
        if mutation and not audit_accepted:
            self._send(503, {"success": False, "error": "admin audit unavailable", "retryable": True})
            return False
        # Authenticate before consuming the installation's request allowance.
        srv = self.server
        if hasattr(srv, "check_rate_limit"):
            if not srv.check_rate_limit():
                self._send(429, {"success": False, "error": "rate limit exceeded; slow down", "retryable": True, "retry_after_seconds": 10})
                return False
        return True

    def _content_length(self, *, limit: int) -> int:
        raw = self.headers.get("Content-Length")
        if raw is None:
            raise services_module.RequestBodyError("Content-Length is required", 411)
        try:
            length = int(raw)
        except (ValueError, TypeError) as exc:
            raise services_module.RequestBodyError("invalid Content-Length") from exc
        if length < 0:
            raise services_module.RequestBodyError("invalid Content-Length")
        if length > limit:
            raise services_module.RequestBodyError(f"request body exceeds configured limit ({limit} bytes)", 413)
        return length

    def _close_rejected_mode_post(self) -> None:
        try:
            remaining = self._content_length(limit=self._request_body_limit())
            if not remaining:
                return
            self.wfile.flush()
            self.connection.shutdown(services_module.socket.SHUT_WR)
            deadline = services_module.time.monotonic() + 0.1
            while remaining:
                timeout = deadline - services_module.time.monotonic()
                if timeout <= 0:
                    return
                self.connection.settimeout(timeout)
                chunk = self.rfile.read1(min(64 * 1024, remaining))
                if not chunk:
                    return
                remaining -= len(chunk)
        except (services_module.RequestBodyError, OSError):
            pass

    def _read_body(self, *, limit: int) -> bytes:
        length = self._content_length(limit=limit)
        if length == 0:
            return b""
        old_timeout = None
        chunks: list[bytes] = []
        received = 0
        try:
            old_timeout = self.connection.gettimeout()
            body_timeout = float(services_module.APP.config.get("server", {}).get("request_body_timeout_seconds", 15.0)) if services_module.APP is not None else 15.0
            deadline = services_module.time.monotonic() + max(0.1, body_timeout)
            read_once = getattr(self.rfile, "read1", None) or self.rfile.read
            # A socket timeout alone is only an *idle* timeout: a slow peer can keep
            # a handler forever by trickling one byte just before each expiry. Read in
            # chunks and shrink the socket timeout against one monotonic wall-clock
            # deadline so the complete body has a hard upper bound.
            while received < length:
                remaining_time = deadline - services_module.time.monotonic()
                if remaining_time <= 0:
                    raise services_module.RequestBodyError("request body timed out", 408)
                self.connection.settimeout(max(0.05, remaining_time))
                chunk = read_once(min(64 * 1024, length - received))
                if not chunk:
                    break
                chunks.append(chunk)
                received += len(chunk)
        except services_module.RequestBodyError:
            raise
        except (services_module.socket.timeout, TimeoutError) as exc:
            raise services_module.RequestBodyError("request body timed out", 408) from exc
        finally:
            try:
                self.connection.settimeout(old_timeout)
            except OSError:
                pass
        if received != length:
            raise services_module.RequestBodyError("request body ended before Content-Length bytes were received")
        return b"".join(chunks)

    @staticmethod
    def _request_body_limit() -> int:
        if services_module.APP is None:
            return 16 * 1024 * 1024
        return max(1024, int(services_module.APP.config.get("server", {}).get("max_request_body_bytes", 16 * 1024 * 1024)))

    def _read_json(self) -> dict[str, Any]:
        raw = self._read_body(limit=self._request_body_limit())
        if not raw:
            return {}
        content_type = self.headers.get("Content-Type", "application/json").split(";", 1)[0].strip().lower()
        if content_type not in {"application/json", "application/merge-patch+json"}:
            raise services_module.RequestBodyError("Content-Type must be application/json", 415)
        try:
            value = services_module.json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, services_module.json.JSONDecodeError) as exc:
            raise services_module.RequestBodyError(f"invalid JSON body: {exc}") from exc
        if not isinstance(value, dict):
            raise services_module.RequestBodyError("JSON request body must be an object")
        try:
            services_module.reject_retired_tenancy_fields(value)
        except services_module.RepositoryScopeError as exc:
            raise services_module.RequestBodyError(str(exc), exc.status_code) from exc
        trace_store = getattr(services_module.APP, "debug_traces", None) if services_module.APP is not None else None
        trace_id = str(getattr(self, "_debug_trace_id", "") or "")
        if trace_store is not None and trace_id:
            try:
                captured = self._safe_debug_trace_request(value)
                trace_store.update(trace_id, request=captured)
                trace_store.event(trace_id, "request_body_captured", {
                    "content_type": content_type,
                    "capture_status": captured.get("capture_status", "captured") if isinstance(captured, dict) else "captured",
                })
            except Exception:
                pass
        return value

    @staticmethod
    def _validate_payload(path: str, payload: dict[str, Any]) -> None:
        """Cheap endpoint schemas before scheduling or model policy work."""
        if path in {"/api/context/pack", "/api/agent-state/context"} and "identity" in payload:
            raise services_module.RequestBodyError("identity was removed; use actual repository/task/session fields")
        if path == "/api/context/pack":
            guarded = payload.get("guarded", False)
            if not isinstance(guarded, bool):
                raise services_module.RequestBodyError("guarded must be boolean")
            if guarded:
                task_id = payload.get("task_id")
                if not isinstance(task_id, str) or not task_id.strip():
                    raise services_module.RequestBodyError("guarded context requires a non-empty task_id")
        def text(value: Any, name: str, maximum: int) -> str:
            if not isinstance(value, str) or len(value) > maximum:
                raise services_module.RequestBodyError(f"{name} must be a string of at most {maximum} characters")
            return value

        def required_text(name: str, *aliases: str, maximum: int = 4096) -> str:
            for key in (name, *aliases):
                if key in payload:
                    value = text(payload[key], name, maximum).strip()
                    if value:
                        return value
            raise services_module.RequestBodyError(f"{name} is required")

        def bounded_integer(value: Any, name: str, minimum: int, maximum: int) -> None:
            if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                raise services_module.RequestBodyError(f"{name} must be an integer from {minimum} to {maximum}")

        def bounded_number(value: Any, name: str, minimum: float, maximum: float) -> None:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or (isinstance(value, float) and not services_module.math.isfinite(value))
                or not minimum <= value <= maximum
            ):
                raise services_module.RequestBodyError(f"{name} must be a finite number from {minimum:g} to {maximum:g}")

        if path == "/api/search":
            if "top_k" in payload:
                bounded_integer(payload["top_k"], "top_k", 1, services_module.MAX_PAGE_SIZE)
            if payload.get("context_lines") is not None:
                bounded_integer(payload["context_lines"], "context_lines", 0, 40)
            if payload.get("limit") is not None:
                bounded_integer(payload["limit"], "limit", 1, services_module.MAX_PAGE_SIZE)
            if "offset" in payload:
                bounded_integer(payload["offset"], "offset", 0, services_module.MAX_PAGE_WINDOW - 1)
            if "enrich" in payload and type(payload["enrich"]) is not bool:
                raise services_module.RequestBodyError("enrich must be a boolean")

        if path.startswith("/api/agent-state/") and "action" in payload:
            action = services_module._agent_action_selector(payload)
            if path == "/api/agent-state/tasks" and action not in services_module._AGENT_TASK_ACTIONS:
                raise services_module.RequestBodyError("unknown task action")
            if path == "/api/agent-state/verification" and action not in services_module._AGENT_VERIFICATION_ACTIONS:
                raise services_module.RequestBodyError("unknown verification action")
            if path == "/api/agent-state/verification" and action == "project_command":
                if set(payload) != {"action", "root", "task_id", "session_id", "alias"}:
                    raise services_module.RequestBodyError("project_command requires exactly root, task_id, session_id and alias")
                for field in ("root", "task_id", "session_id", "alias"):
                    required_text(field, maximum=4096 if field == "root" else 256)
            if path == "/api/agent-state/verification" and action == "completion" and "repository_revision" in payload:
                revision = payload["repository_revision"]
                if (
                    not isinstance(revision, str)
                    or len(revision) > 256
                    or revision != revision.strip()
                ):
                    raise services_module.RequestBodyError(
                        "repository_revision must be empty or an opaque revision of at most 256 characters"
                    )

        if path == "/api/agent-state/blackboard":
            retired_fields = sorted(services_module._AGENT_BLACKBOARD_RETIRED_FIELDS.intersection(payload))
            if retired_fields:
                fields = ", ".join(retired_fields)
                raise services_module.RequestBodyError(f"unsupported blackboard field(s): {fields}")

        if path == "/api/agent-state/incidents":
            action = payload.get("action")
            retired_by_action = {
                "decision": {"revision"},
                "record": {
                    "reason", "fix", "status", "redacted_message", "value",
                    "tool_name", "key", "paths", "revision", "error_class",
                },
                "find": {"key"},
            }
            retired = sorted(retired_by_action.get(action, set()).intersection(payload))
            if retired:
                raise services_module.RequestBodyError(f"unsupported incident field(s): {', '.join(retired)}")
            if action in retired_by_action:
                allowed_fields = {
                    "decision": {"action", "root", "fingerprint", "state_revision"},
                    "record": {
                        "action", "root", "root_cause", "verified_fix", "message",
                        "operation_class", "exit_code", "state_revision", "evidence_ids", "affected_paths",
                    },
                    "find": {"action", "root", "query", "limit"},
                }[action]
                unexpected = sorted(set(payload) - allowed_fields)
                if unexpected:
                    raise services_module.RequestBodyError(f"unsupported incident field(s): {', '.join(unexpected)}")
                if "root" in payload:
                    text(payload["root"], "root", 4096)
            if action == "decision":
                fingerprint = payload.get("fingerprint")
                if not isinstance(fingerprint, dict):
                    raise services_module.RequestBodyError("fingerprint must be an object")
                expected = {"error_class", "operation_class", "signature_hash"}
                if set(fingerprint) != expected:
                    raise services_module.RequestBodyError("fingerprint must contain error_class, operation_class, and signature_hash")
                for field, maximum in (("error_class", 160), ("operation_class", 160), ("signature_hash", 128)):
                    value = text(fingerprint[field], f"fingerprint.{field}", maximum)
                    if not value.strip():
                        raise services_module.RequestBodyError(f"fingerprint.{field} is required")
                if "state_revision" in payload:
                    text(payload["state_revision"], "state_revision", 256)
            elif action == "record":
                for field, maximum in (
                    ("root_cause", 4096), ("verified_fix", 4096), ("message", 4096),
                    ("operation_class", 160), ("state_revision", 256),
                ):
                    if field in payload:
                        text(payload[field], field, maximum)
                if "exit_code" in payload:
                    bounded_integer(payload["exit_code"], "exit_code", -(1 << 31), (1 << 32) - 1)
                for field, maximum_items, maximum_chars in (("evidence_ids", 64, 256), ("affected_paths", 128, 4096)):
                    if field not in payload:
                        continue
                    values = payload[field]
                    if not isinstance(values, list) or len(values) > maximum_items:
                        raise services_module.RequestBodyError(f"{field} must be a list of at most {maximum_items} entries")
                    for item in values:
                        text(item, f"{field} item", maximum_chars)
            elif action == "find":
                if "query" not in payload:
                    raise services_module.RequestBodyError("query is required")
                query = text(payload["query"], "query", 4096)
                if not query.strip() or "\x00" in query:
                    raise services_module.RequestBodyError("query is required")
                bounded_integer(payload.get("limit", 100), "limit", 1, 100)
                for field, maximum in (("root", 4096),):
                    if field not in payload:
                        raise services_module.RequestBodyError(f"{field} is required")
                    scope_value = text(payload[field], field, maximum)
                    if not scope_value or scope_value != scope_value.strip() or "\x00" in scope_value:
                        raise services_module.RequestBodyError(f"{field} must be a canonical non-empty string")

        if path == "/api/embed":
            values = payload.get("texts", payload.get("input", []))
            values = [values] if isinstance(values, str) else values
            if not isinstance(values, list) or len(values) > 256:
                raise services_module.RequestBodyError("texts must be a list of at most 256 entries")
            for value in values:
                text(value, "embedding text", 200000)
        elif path == "/api/telemetry/tool-accounting":
            events = payload.get("events", [])
            if not isinstance(events, list) or len(events) > 64:
                raise services_module.RequestBodyError("events must be a list of at most 64 entries")
            for event in events:
                if not isinstance(event, dict) or len(event) > 40:
                    raise services_module.RequestBodyError("each accounting event must be a small object")
                if "tool" in event:
                    text(event["tool"], "tool", 80)
                services_module.reject_retired_tenancy_fields(event)
                if "agent" in event:
                    text(event["agent"], "agent", 80)
                breakdown = event.get("savings_breakdown", {})
                if not isinstance(breakdown, dict) or len(breakdown) > 16:
                    raise services_module.RequestBodyError("savings_breakdown must be an object with at most 16 entries")
        elif path == "/api/work-orders":
            action = text(payload.get("action", "submit"), "action", 32).strip().lower().replace("-", "_")
            if action not in {"submit", "status", "wait", "get", "cancel", "continue"}:
                raise services_module.RequestBodyError("unsupported work-order action")
            if action == "submit":
                required_text("root", maximum=4096)
                required_text("task", maximum=24000)
            if action in {"status", "wait", "get", "cancel", "continue"}:
                required_text("work_id", maximum=128)
            if action == "continue":
                required_text("answer", maximum=8000)
            for name, max_items, max_chars in (("acceptance_criteria", 24, 2000), ("constraints", 24, 2000), ("return_fields", 32, 80)):
                if name not in payload:
                    continue
                values = payload[name]
                if not isinstance(values, list) or len(values) > max_items:
                    raise services_module.RequestBodyError(f"{name} must be a list of at most {max_items} entries")
                for item in values:
                    text(item, f"{name} item", max_chars)
            for name in ("permissions", "budget"):
                if name in payload and not isinstance(payload[name], dict):
                    raise services_module.RequestBodyError(f"{name} must be an object")
            if "response_profile" in payload:
                text(payload["response_profile"], "response_profile", 16)
            if action == "wait" or "timeout_seconds" in payload:
                bounded_number(payload.get("timeout_seconds", 90), "timeout_seconds", 0, 90)
            if action in {"submit", "get"} or "max_output_tokens" in payload:
                bounded_integer(payload.get("max_output_tokens", 0), "max_output_tokens", 0, 4096)
        elif path == "/api/repo/call_graph":
            if "root" in payload:
                text(payload["root"], "root", 4096)
            required_text("symbol", "query", maximum=1024)
            if "path" in payload and payload["path"] is not None:
                text(payload["path"], "path", 4096)
            if "depth" in payload:
                bounded_integer(payload["depth"], "depth", 1, 2)
            if "limit" in payload:
                bounded_integer(payload["limit"], "limit", 1, services_module.MAX_PAGE_SIZE)
        elif path == "/api/repo/code-index":
            if "root" in payload:
                text(payload["root"], "root", 4096)
            if "query" in payload:
                text(payload["query"], "query", 4096)
            if "include_code" in payload and type(payload["include_code"]) is not bool:
                raise services_module.RequestBodyError("include_code must be a boolean")
            if "limit" in payload:
                bounded_integer(payload["limit"], "limit", 1, services_module.MAX_PAGE_SIZE)
            if "offset" in payload:
                bounded_integer(payload["offset"], "offset", 0, services_module.MAX_PAGE_WINDOW - 1)
        elif path in {"/api/preprocess", "/api/repo/profile", "/api/repo/map", "/api/repo/investigate", "/api/repo/diagnose", "/api/repo/briefing", "/api/repo/deterministic", "/api/search"}:
            if "root" in payload:
                text(payload["root"], "root", 4096)
        elif path == "/api/memory/put":
            required_text("key", maximum=160)
            required_text("value", maximum=1000000)
            if "expected_version" in payload and (
                type(payload["expected_version"]) is not int or payload["expected_version"] < 0
            ):
                raise services_module.RequestBodyError("expected_version must be a non-negative integer")
            if "root" in payload:
                text(payload["root"], "root", 4096)
        elif path in {"/api/memory/get", "/api/memory/delete"}:
            required_text("key", maximum=160)
            if "root" in payload:
                text(payload["root"], "root", 4096)
            if path == "/api/memory/delete" and "scope" in payload:
                raise services_module.RequestBodyError("scope is not supported by workspace memo deletion; root selects the workspace")
        elif path == "/api/memory/search":
            if "root" in payload:
                text(payload["root"], "root", 4096)
            if "query" in payload:
                text(payload["query"], "query", 4096)
        elif path == "/api/code/symbol":
            required_text("symbol", maximum=1024)
        elif path == "/api/code/find_symbol":
            required_text("pattern", "name_path_pattern", maximum=1024)
        elif path in {"/api/code/find_implementations", "/api/code/find_referencing_symbols"}:
            required_text("symbol", "name", maximum=1024)
        elif path in {"/api/code/ast_outline", "/api/code/symbols_overview", "/api/code/diagnostics"}:
            required_text("path", "file", maximum=4096)
        elif path in {"/api/code/batch_replace", "/api/repo/batch_replace"}:
            edits = payload.get("edits") or payload.get("replacements")
            if not isinstance(edits, list) or not edits:
                raise services_module.RequestBodyError("edits must be a non-empty list of replacement operations")
        elif path == "/api/code-intelligence/query":
            action = text(payload.get("action", "search"), "action", 80).strip().lower().replace("-", "_")
            if action not in {"dead_code", "dead", "stats", "repository_stats"}:
                required_text("query", maximum=4096)
            if action in {"overview", "symbols_overview", "references", "find_references", "referencing"}:
                required_text("path", maximum=4096)
        elif path == "/api/browser/capability":
            required_text("origin", maximum=512)
            if "tab_id" not in payload or payload["tab_id"] in (None, ""):
                raise services_module.RequestBodyError("tab_id is required")
            if not isinstance(payload["tab_id"], (int, str)):
                raise services_module.RequestBodyError("tab_id must be an integer or string")
            if "window_id" not in payload or payload["window_id"] in (None, ""):
                raise services_module.RequestBodyError("window_id is required")
            if not isinstance(payload["window_id"], (int, str)):
                raise services_module.RequestBodyError("window_id must be an integer or string")
        elif path == "/api/browser/capture":
            required_text("capability", maximum=256)
            if "tab_id" not in payload:
                raise services_module.RequestBodyError("tab_id is required")
            if "window_id" not in payload or payload["window_id"] in (None, ""):
                raise services_module.RequestBodyError("window_id is required")
        elif path == "/api/vision/review":
            if "prompt" in payload:
                text(payload["prompt"], "prompt", 20000)
        elif path == "/api/coord/pubsub_poll":
            unsupported = set(payload) - {"root", "topic", "after_seq", "limit", "after_ts"}
            if unsupported:
                raise services_module.RequestBodyError(
                    "pubsub_poll accepts only root, topic, after_seq, limit, and after_ts"
                )
            if "after_seq" in payload:
                bounded_integer(payload["after_seq"], "after_seq", 0, (1 << 63) - 1)
            if "limit" in payload:
                bounded_integer(payload["limit"], "limit", 1, 1000)
            if "after_ts" in payload:
                bounded_number(payload["after_ts"], "after_ts", 0.0, 1e12)
        evaluation = payload.get("evaluation")
        if evaluation is not None:
            if not isinstance(evaluation, dict):
                raise services_module.RequestBodyError("evaluation must be an object")
            if "task_id" not in evaluation or "cohort" not in evaluation:
                raise services_module.RequestBodyError("evaluation task_id and cohort are required")

