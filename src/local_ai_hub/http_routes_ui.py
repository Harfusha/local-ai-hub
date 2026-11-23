from __future__ import annotations

class HTTPRoutesUIMixin:
    def _finish_static_response(
        self,
        status: int,
        response_bytes: int,
        response_type: str,
        *,
        success: bool | None = None,
    ) -> None:
        from . import http_server as services_module
        outcome = 200 <= status < 400 if success is None else bool(success)
        self._finish_debug_trace(
            status,
            {"success": outcome, "response_type": response_type},
        )
        if getattr(self, "_telemetry_finished", False):
            return
        app = services_module.APP
        if app is None:
            self._telemetry_finished = True
            return
        try:
            path = str(getattr(self, "_request_path", services_module.urlparse(self.path).path))
            excluded = set(app.config.get("observability", {}).get("exclude_http_paths", []))
            if path not in services_module.MONITOR_PATHS and not path.startswith("/api/debug-traces/") and path not in excluded:
                elapsed_ms = max(
                    0.0,
                    (services_module.time.perf_counter() - float(getattr(self, "_request_started", services_module.time.perf_counter()))) * 1000,
                )
                app.telemetry.record_http(
                    agent=self._agent(),
                    request_id=str(getattr(self, "_trace_request_id", "")),
                    trace_id=str(getattr(self, "_trace_id", "")),
                    action=path,
                    duration_ms=elapsed_ms,
                    success=outcome,
                    status_code=status,
                    response_bytes=max(0, int(response_bytes)),
                    route=response_type,
                )
        except Exception:
            pass
        finally:
            self._telemetry_finished = True

    def _send_html(self, status: int, html: str) -> None:
        from . import http_server as services_module
        nonce = services_module.uuid.uuid4().hex
        body = html.replace("<script>", f'<script nonce="{nonce}">', 1).encode("utf-8")
        sent = False
        try:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Connection", "close")
            self._common_headers(html=True, nonce=nonce)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            sent = True
        except OSError as exc:
            if not services_module._is_client_disconnect(exc):
                raise
        finally:
            self._finish_static_response(
                status, len(body), "static_html", success=sent and 200 <= status < 400,
            )
            self.close_connection = True

    def _handle_dashboard_route(self) -> None:
        from . import http_server as services_module
        if not bool(services_module.APP.config.get("monitoring", {}).get("dashboard_enabled", True)) or not bool(services_module.APP.config.get("features", {}).get("dashboard", True)):
            self._send(404, {"error": "dashboard disabled"}); return
        self._send_html(200, services_module._dashboard_html_with_trace_notice()); return


    def _handle_favicon_route(self) -> None:
        sent = False
        try:
            self.send_response(204); self.end_headers()
            sent = True
        finally:
            self._finish_static_response(204, 0, "static", success=sent)
        return

