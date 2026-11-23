from __future__ import annotations

from typing import Any

from .http_server_proxy import services_module


class HttpStreamMixin:
    def _finish_stream_request(self, success: bool, error: str = "") -> None:
        """Finish journal/telemetry for responses whose headers/body were streamed manually."""
        if services_module.APP is None:
            return
        response = {"success": success, "streamed": True, "error": error} if error else {"success": success, "streamed": True}
        if getattr(self, "_debug_stream_capture_failed", False):
            response["trace_capture_status"] = "storage_error"
        self._finish_debug_trace(200 if success else 500, response, error=error)
        request_id = str(getattr(self, "_journal_request_id", "") or "")
        if request_id and not getattr(self, "_journal_finished", False):
            try:
                services_module.APP.recovery.finish(
                    request_id, success, error, status_code=200,
                    response={"success": success, "streamed": True, "error": error} if error else {"success": success, "streamed": True},
                )
                self._journal_finished = True
            except Exception:
                pass
        if not getattr(self, "_telemetry_finished", False):
            try:
                path = str(getattr(self, "_request_path", services_module.urlparse(self.path).path))
                elapsed_ms = max(0.0, (services_module.time.perf_counter() - float(getattr(self, "_request_started", services_module.time.perf_counter()))) * 1000)
                services_module.APP.telemetry.record_http(agent=self._agent(), request_id=str(getattr(self, "_trace_request_id", "")), trace_id=str(getattr(self, "_trace_id", "")), action=path, duration_ms=elapsed_ms, success=success, status_code=200, response_bytes=0, model="", cache_hit=False, fallback_used=False, degraded=False, route="stream", evidence_count=0, error_type="stream_error" if error else "")
                if error:
                    services_module.APP.telemetry.record_error("http", path, error, request_id=str(getattr(self, "_trace_request_id", "")), agent=self._agent(), error_type_override="HttpStreamError", error_code_override="http_stream_failed", retryable=True)
                self._telemetry_finished = True
            except Exception:
                pass
        self._close_trace_context()

    def _stream_agent_events(
        self,
        stream_id: str = "",
        kind: str = "",
        after_seq: int = 0,
        timeout: float = 0.0,
        last_event_id: str = "",
    ) -> None:
        if services_module.APP is None or not getattr(services_module.APP, "agent_state", None) or not services_module.APP.agent_state.enabled:
            self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False})
            return

        # EventSource reconnects carry the last numeric event ID automatically.
        # It is safe to apply only with an explicit stream filter; an unscoped
        # cursor could otherwise resume one stream inside another.
        headers = getattr(self, "headers", {})
        last_event_id_header = str(headers.get("Last-Event-ID", "") if hasattr(headers, "get") else "" or "").strip()
        effective_last_event_id = last_event_id_header or last_event_id
        prefixed_cursor = bool(stream_id and ":" in effective_last_event_id)

        if stream_id and effective_last_event_id:
            parsed = services_module._parse_agent_event_cursor(effective_last_event_id)
            if parsed is not None:
                parsed_stream, parsed_seq = parsed
                if parsed_stream == stream_id:
                    after_seq = parsed_seq
            elif effective_last_event_id.isascii() and effective_last_event_id.isdecimal():
                try:
                    resume_seq = int(effective_last_event_id)
                    if 0 <= resume_seq <= (1 << 63) - 1:
                        after_seq = resume_seq
                except (TypeError, ValueError, OverflowError):
                    pass

        q = None

        def send_initial_error(_status: int, _payload: services_module.Mapping[str, Any]) -> None:
            try:
                if q is not None:
                    try:
                        services_module.APP.agent_state.unsubscribe(q)
                    except Exception as exc:
                        logger = getattr(services_module.APP, "logger", None)
                        if logger is not None:
                            logger.warning("event stream unsubscribe failed error_type=%s", type(exc).__name__)
                payload = services_module.project_agent_response(dict(_payload), enabled=services_module.detailed_diagnostics_enabled(
                    getattr(services_module.APP, "config", {}), store=getattr(services_module.APP, "debug_traces", None)))
                self.send_response(_status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self._common_headers()
                self.end_headers()
                self.wfile.write(services_module._json_bytes(payload))
                self.wfile.flush()
            except OSError:
                pass
            self._finish_stream_request(False, error="event replay unavailable")

        try:
            q = services_module.APP.agent_state.subscribe(maxsize=200)
        except Exception as exc:
            logger = getattr(services_module.APP, "logger", None)
            if logger is not None:
                logger.warning("event stream subscribe failed error_type=%s", type(exc).__name__)
            send_initial_error(503, {
                "success": False,
                "error": {"code": "event_replay_unavailable", "message": "Event replay is temporarily unavailable."},
            })
            return

        initial_page: dict[str, Any] | None = None
        if stream_id and after_seq >= 0:
            if not hasattr(services_module.APP.agent_state, "event_page"):
                send_initial_error(503, {
                    "success": False,
                    "error": {"code": "event_page_unavailable", "message": "Event page could not be read."},
                    "next_seq": after_seq,
                    "terminal": False,
                    "retryable": True,
                })
                return
            first_limit = min(services_module.AGENT_EVENT_PAGE_MAX_LIMIT, services_module.SSE_REPLAY_MAX_EVENTS)
            try:
                initial_page = services_module.APP.agent_state.event_page(
                    stream_id=stream_id,
                    after_seq=after_seq,
                    limit=first_limit,
                )
            except Exception:
                send_initial_error(503, {
                    "success": False,
                    "error": {"code": "event_page_unavailable", "message": "Event page could not be read."},
                    "next_seq": after_seq,
                    "terminal": False,
                    "retryable": True,
                })
                return
            if not isinstance(initial_page, dict) or initial_page.get("success") is not True:
                send_initial_error(503, initial_page if isinstance(initial_page, dict) else {
                    "success": False,
                    "error": {"code": "event_page_unavailable", "message": "Event page could not be read."},
                    "next_seq": after_seq,
                    "terminal": False,
                    "retryable": True,
                })
                return

        # Bound maximum stream duration to prevent holding worker threads indefinitely
        app_cfg = getattr(services_module.APP, "config", {}) or {}
        max_duration = float(app_cfg.get("server", {}).get("max_stream_duration_seconds", 300.0) if isinstance(app_cfg, dict) else 300.0)
        if timeout <= 0.0 or timeout > max_duration:
            timeout = max_duration

        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self._common_headers()
            self.end_headers()
        except OSError:
            self._finish_stream_request(False, error="client disconnected before headers")
            return

        stream_success = True
        stream_error = ""
        trace_stream_output = bool(getattr(self, "_debug_trace_id", ""))
        if trace_stream_output:
            self._debug_stream_capture = True
        try:
            # Subscribe before fetching history. An event appended in the replay
            # window is then either replayed or queued; duplicate queued events
            # are discarded by the per-stream sequence check below.
            last_seq_by_stream: dict[str, int] = {}
            last_seq = after_seq
            last_delivered_seq = after_seq
            stream_success = True

            def note_seq(event_stream: str, seq: int) -> None:
                last_seq_by_stream[event_stream] = max(
                    last_seq_by_stream.get(event_stream, after_seq), seq
                )

            def current_last_seq() -> int:
                if stream_id:
                    return last_seq_by_stream.get(stream_id, last_seq)
                return max([after_seq, *last_seq_by_stream.values()])

            def format_seq(seq: int | None) -> str:
                if seq is None:
                    return ""
                if prefixed_cursor and stream_id:
                    return services_module._encode_agent_event_cursor(stream_id, seq)
                return str(seq)

            def capture_sse_chunk(chunk: bytes) -> None:
                if not trace_stream_output:
                    return
                store = getattr(services_module.APP, "debug_traces", None) if services_module.APP is not None else None
                append_output = getattr(store, "append_output", None)
                if not callable(append_output) or not append_output(
                    str(getattr(self, "_debug_trace_id", "")), chunk.decode("utf-8")
                ):
                    self._debug_stream_capture_failed = True

            def write_sse(event_name: str, payload: services_module.Mapping[str, Any], seq: int | None = None) -> bool:
                nonlocal stream_success, stream_error, last_delivered_seq
                wire_payload = services_module.project_agent_response(dict(payload), enabled=services_module.detailed_diagnostics_enabled(
                    getattr(services_module.APP, "config", {}), store=getattr(services_module.APP, "debug_traces", None)))
                if seq is not None:
                    event_id = f"id: {seq}\n" if event_name == "replay_page" else f"id: {format_seq(seq)}\n"
                else:
                    event_id = ""
                msg = (
                    f"{event_id}event: {event_name}\n"
                    f"data: {services_module.json_dumps(wire_payload, separators=(',', ':'))}\n\n"
                ).encode("utf-8")
                try:
                    self.wfile.write(msg)
                    self.wfile.flush()
                    if trace_stream_output:
                        capture_sse_chunk(msg)
                    if seq is not None:
                        last_delivered_seq = seq
                    return True
                except OSError:
                    stream_success = False
                    stream_error = "client disconnected"
                    return False

            if stream_id and after_seq >= 0:
                replay_cursor = after_seq
                replay_through_seq = None
                replayed_events = 0
                reported_gap_ranges: set[tuple[int, int]] = set()
                first_page = True
                while replayed_events < services_module.SSE_REPLAY_MAX_EVENTS:
                    if first_page and initial_page is not None:
                        page = initial_page
                        first_page = False
                    else:
                        page_limit = min(services_module.AGENT_EVENT_PAGE_MAX_LIMIT, services_module.SSE_REPLAY_MAX_EVENTS - replayed_events)
                        try:
                            page = services_module.APP.agent_state.event_page(
                                stream_id=stream_id,
                                after_seq=replay_cursor,
                                limit=page_limit,
                                through_seq=replay_through_seq,
                            )
                        except Exception as exc:
                            stream_success = False
                            stream_error = "event replay unavailable"
                            logger = getattr(services_module.APP, "logger", None)
                            if logger is not None:
                                logger.warning("event replay page failed error_type=%s", type(exc).__name__)
                            write_sse("replay_error", {
                                "success": False,
                                "next_seq": max(0, int(replay_cursor)),
                                "error": {
                                    "code": "event_replay_unavailable",
                                    "message": "event replay is temporarily unavailable",
                                },
                                "retryable": True,
                                "terminal": False,
                            })
                            return
                        if not isinstance(page, dict) or page.get("success") is not True:
                            stream_success = False
                            stream_error = "event replay unavailable"
                            err_payload = page if isinstance(page, dict) else {
                                "success": False,
                                "next_seq": max(0, int(replay_cursor)),
                                "error": {
                                    "code": "event_replay_unavailable",
                                    "message": "event replay is temporarily unavailable",
                                },
                                "retryable": True,
                                "terminal": False,
                            }
                            write_sse("replay_error", err_payload)
                            return

                    if replay_through_seq is None:
                        raw_high_water = page.get("last_seq", replay_cursor)
                        replay_through_seq = max(0, int(replay_cursor if raw_high_water is None else raw_high_water))
                        if replay_cursor > replay_through_seq or (page.get("cursor_reset") is True and prefixed_cursor):
                            first_retained = max(0, int(page.get("first_retained_seq", 0) or 0))
                            checkpoint = min(max(0, first_retained - 1), replay_through_seq)
                            if prefixed_cursor and page.get("next_seq") is not None:
                                checkpoint = int(page["next_seq"])
                            cursor_reset = {
                                "requested_after_seq": replay_cursor,
                                "last_seq": replay_through_seq,
                                "resume_after_seq": checkpoint,
                                "cursor_ahead": True,
                            }
                            if first_retained > 1:
                                cursor_reset.update({
                                    "retention_gap": True,
                                    "missing_from_seq": 1,
                                    "missing_through_seq": min(first_retained - 1, replay_through_seq),
                                    "first_available_seq": first_retained,
                                })
                            reset_event_name = "cursor_reset" if prefixed_cursor else "replay_cursor_reset"
                            if not write_sse(reset_event_name, cursor_reset, seq=checkpoint):
                                return
                            replay_cursor = checkpoint
                            last_seq = checkpoint
                            last_seq_by_stream[stream_id] = checkpoint
                            if prefixed_cursor:
                                if not page.get("has_more") and not page.get("events"):
                                    break
                            else:
                                continue

                    page_cursor = int(page.get("next_seq", replay_cursor) or 0)
                    gap_ranges = page.get("gap_ranges", [])
                    replay_events = page.get("events", [])
                    if not isinstance(replay_events, (list, tuple)):
                        replay_events = []

                    if prefixed_cursor and gap_ranges and not replay_events:
                        gap_payload = {
                            "stream_id": stream_id,
                            "next_seq": page_cursor,
                            "gap_ranges": gap_ranges,
                            "first_retained_seq": page.get("first_retained_seq", page_cursor),
                            "last_seq": page.get("last_seq", page_cursor),
                            "cursor_reset": False,
                            "retention_gap": True,
                        }
                        if not write_sse("retention_gap", gap_payload, seq=page_cursor):
                            return
                        last_seq = page_cursor
                        note_seq(stream_id, page_cursor)
                        last_delivered_seq = page_cursor
                        break

                    replay_entries = []
                    if isinstance(gap_ranges, (list, tuple)):
                        for gap in gap_ranges:
                            if not isinstance(gap, dict):
                                continue
                            try:
                                gap_start = int(gap.get("from_seq"))
                                gap_end = int(gap.get("to_seq"))
                            except (TypeError, ValueError, OverflowError):
                                continue
                            gap_start = max(gap_start, last_seq + 1)
                            gap_end = min(gap_end, page_cursor)
                            if gap_start < 0 or gap_end < gap_start or (gap_start, gap_end) in reported_gap_ranges:
                                continue
                            gap_event_kind = "retention_gap" if prefixed_cursor else "stream.gap"
                            replay_entries.append((gap_end, gap_event_kind, {
                                **gap, "from_seq": gap_start, "to_seq": gap_end,
                            }, True))
                    if page.get("cursor_reset") is True and not prefixed_cursor:
                        first_retained = int(page.get("first_retained_seq", 0) or 0)
                        last_seq = max(0, first_retained - 1)

                    for raw_event in replay_events:
                        if hasattr(raw_event, "to_dict") and callable(raw_event.to_dict):
                            raw_event = raw_event.to_dict()
                        if not isinstance(raw_event, dict):
                            continue
                        event_seq = int(raw_event.get("seq", 0) or 0)
                        event_kind = str(raw_event.get("kind", ""))
                        if event_seq <= last_seq:
                            continue
                        replay_entries.append((event_seq, event_kind, raw_event, False))

                    for event_seq, event_kind, raw_event, is_gap in sorted(replay_entries, key=lambda item: item[0]):
                        if event_seq <= last_seq:
                            continue
                        if is_gap:
                            if not write_sse(event_kind, raw_event, seq=event_seq):
                                return
                            reported_gap_ranges.add((raw_event["from_seq"], raw_event["to_seq"]))
                        elif not kind or event_kind == kind:
                            if not write_sse(event_kind, raw_event, seq=event_seq):
                                return
                        last_seq = event_seq
                        note_seq(stream_id, event_seq)

                    page_id = page_cursor if page_cursor > last_delivered_seq else None
                    if not write_sse("replay_page", page, seq=page_id):
                        return
                    replayed_events += len(replay_events)
                    next_cursor = int(page.get("next_seq", replay_cursor) or 0)
                    has_more = page.get("has_more") is True
                    if replayed_events >= services_module.SSE_REPLAY_MAX_EVENTS:
                        if has_more:
                            limit_reached = {
                                "replay_limit": services_module.SSE_REPLAY_MAX_EVENTS,
                                "last_seq": last_seq,
                                "has_more": True,
                            }
                            limit_msg = (
                                f"id: {format_seq(last_seq)}\nevent: replay_limit\ndata: "
                                f"{services_module.json_dumps(limit_reached, separators=(',', ':'))}\n\n"
                            ).encode("utf-8")
                            try:
                                self.wfile.write(limit_msg)
                                self.wfile.flush()
                            except OSError:
                                stream_success = False
                                stream_error = "client disconnected"
                                return
                        break
                    if not has_more or next_cursor <= replay_cursor:
                        break
                    replay_cursor = next_cursor

            start_time = services_module.time.monotonic()
            while True:
                remaining = timeout - (services_module.time.monotonic() - start_time)
                if remaining <= 0:
                    write_sse(
                        "stream_timeout",
                        {
                            "reconnect": True,
                            "last_seq": current_last_seq(),
                            "next_seq": current_last_seq(),
                            "last_seq_by_stream": dict(last_seq_by_stream),
                        },
                    )
                    break
                try:
                    ev = q.get(timeout=min(1.0, remaining))
                    if ev.kind == "stream.gap":
                        ranges = ev.payload.get("gap_ranges", [])
                        matching_ranges = [
                            gap for gap in ranges
                            if isinstance(gap, services_module.Mapping)
                            and (not stream_id or str(gap.get("stream_id", ev.stream_id)) == stream_id)
                        ]
                        relevant = not stream_id or ev.stream_id == stream_id or matching_ranges
                        if not relevant:
                            continue
                        for gap in matching_ranges:
                            gap_stream = str(gap.get("stream_id", ev.stream_id))
                            try:
                                note_seq(gap_stream, int(gap.get("to_seq", 0)))
                            except (TypeError, ValueError):
                                continue
                        gap_kind = "retention_gap" if prefixed_cursor else ev.kind
                        if not write_sse(gap_kind, ev.to_dict()):
                            break
                        continue

                    if stream_id and ev.stream_id != stream_id:
                        continue
                    if ev.seq is not None:
                        if ev.seq <= last_seq_by_stream.get(ev.stream_id, after_seq):
                            continue
                        note_seq(ev.stream_id, ev.seq)
                    if kind and ev.kind != kind:
                        if prefixed_cursor and stream_id and ev.seq is not None:
                            try:
                                cursor_event = f"id: {format_seq(ev.seq)}\n\n".encode("utf-8")
                                self.wfile.write(cursor_event)
                                self.wfile.flush()
                                if trace_stream_output:
                                    capture_sse_chunk(cursor_event)
                                last_delivered_seq = ev.seq
                            except OSError:
                                stream_success = False
                                stream_error = "client disconnected"
                                break
                        continue
                    if not write_sse(ev.kind, ev.to_dict(), ev.seq):
                        break
                except services_module.queue.Empty:
                    try:
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                        if trace_stream_output:
                            capture_sse_chunk(b": keep-alive\n\n")
                    except OSError:
                        stream_success = False
                        stream_error = "client disconnected"
                        break
        except OSError:
            stream_success = False
            stream_error = "client disconnected"
        except Exception:
            stream_success = False
            stream_error = "stream failed"
        finally:
            self.close_connection = True
            services_module.APP.agent_state.unsubscribe(q)
            self._finish_stream_request(stream_success, error=stream_error)

    def do_OPTIONS(self) -> None:
        if services_module.APP is None:
            self._send(503, {"success": False, "error": "hub starting up; please retry", "retryable": True})
            return
        path = services_module.urlparse(self.path).path
        bridge_route = path.startswith("/api/browser/") or path == "/api/vision/review"
        if not bridge_route or not self._validate_host_and_origin():
            self._send(404, {"success": False, "error": "unsupported browser bridge route", "terminal": True, "retryable": False})
            return
        try:
            self.send_response(204)
            self._common_headers()
            self.send_header("Content-Length", "0")
            self.end_headers()
        except OSError as exc:
            if not services_module._is_client_disconnect(exc):
                raise

