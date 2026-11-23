from __future__ import annotations

class HTTPAdminModesMixin:
    def _handle_admin_mode_post(self, path: str) -> None:
        from . import http_server as services_module
        try:
            payload = self._read_json()
        except services_module.RequestBodyError as exc:
            self._send(exc.status, {
                "success": False, "error": str(exc), "error_code": "invalid_mode_request",
                "terminal": True, "retryable": False,
            }); return
        mode = payload.get("mode")
        if set(payload) != {"mode"} or not isinstance(mode, str):
            self._send(400, {
                "success": False, "error": "request must contain only a string mode",
                "error_code": "invalid_mode_request", "terminal": True, "retryable": False,
            }); return
        async_jobs = getattr(services_module.APP, "async_jobs", None)
        mode_changed = getattr(async_jobs, "on_operational_mode_changed", None)
        guard_factory = getattr(async_jobs, "operational_mode_change_guard", None)
        guard = guard_factory() if callable(guard_factory) else services_module.nullcontext()
        cancellation_error = ""
        cancellation_result = None
        release_token = None
        preprocessing_fence = False
        preprocessing_start = None
        preprocessing_was_ready = False
        current_mode = None
        api = services_module._operational_mode_api()
        load_fn = getattr(api, "load_operational_mode", services_module.load_operational_mode)
        set_fn = getattr(api, "set_operational_mode", services_module.set_operational_mode)
        mode_changed_value = False
        try:
            with guard:
                jobs_path = getattr(async_jobs, "path", None)
                if jobs_path is not None:
                    state_dir = services_module.Path(jobs_path).parent
                else:
                    app_cfg = getattr(services_module.APP, "config", None)
                    state_dir = app_cfg.get("server", {}).get("state_dir", "state") if isinstance(app_cfg, dict) else "state"
                try:
                    current_mode = load_fn(state_dir=state_dir)
                except TypeError:
                    current_mode = load_fn(state_dir)
                requested_mode = str(mode).strip().lower().replace("-", "_")
                if requested_mode == "preprocessing" and current_mode.mode == "preprocessing":
                    from .operational_mode import preprocessing_mode_ready
                    preprocessing_was_ready = preprocessing_mode_ready(state_dir, current_mode)
                release_active = getattr(async_jobs, "resource_release_active", None)
                release_in_progress = bool(release_active()) if callable(release_active) else False
                if requested_mode == "preprocessing":
                    # Fence late arrivals before checking the registries. A
                    # cancelled synchronous GPU user must actually drain before
                    # background processing can claim its resources.
                    services_module._ACTIVE_TRANSCRIPTIONS.enter_gaming()
                    services_module._ACTIVE_CONVERSATIONS.enter_gaming()
                    preprocessing_fence = True
                    inference_checker = getattr(async_jobs, "inference_actions_active", None)
                    try:
                        inference_active = bool(inference_checker()) if callable(inference_checker) else True
                    except Exception:
                        inference_active = True
                    if release_in_progress or inference_active or services_module._ACTIVE_TRANSCRIPTIONS.active_count() or services_module._ACTIVE_CONVERSATIONS.active_count():
                        if current_mode.mode == "active":
                            services_module._ACTIVE_TRANSCRIPTIONS.enter_active()
                            services_module._ACTIVE_CONVERSATIONS.enter_active()
                        self._send(423, {
                            "success": False, "error": "cannot start preprocessing until inference or resource cleanup drains",
                            "error_code": "resource_release_in_progress" if release_in_progress else "inference_active",
                            "mode_changed": False, "mode": current_mode.mode, "revision": current_mode.revision,
                            "terminal": False, "retryable": True, "retry_after_seconds": 1,
                        }); return
                if (
                    requested_mode == "active" and current_mode.mode != "active"
                    and (release_in_progress or services_module._ACTIVE_TRANSCRIPTIONS.active_count() or services_module._ACTIVE_CONVERSATIONS.active_count())
                ):
                    self._send(423, {
                        "success": False, "error": "cannot reactivate while inference or resource cleanup is active",
                        "error_code": "resource_release_in_progress" if release_in_progress else "inference_active", "mode_changed": False,
                        "mode": current_mode.mode, "revision": current_mode.revision,
                        "terminal": False, "retryable": True, "retry_after_seconds": 1,
                    }); return
                try:
                    sig = services_module.inspect.signature(set_fn)
                    first_param = list(sig.parameters.keys())[0] if sig.parameters else ""
                    if first_param in {"state_dir", "state", "root"}:
                        snapshot = set_fn(state_dir, mode)
                    else:
                        snapshot = set_fn(mode, state_dir)
                except Exception:
                    try:
                        snapshot = set_fn(state_dir, mode)
                    except (TypeError, ValueError):
                        snapshot = set_fn(mode, state_dir)
                mode_changed_value = snapshot.mode != current_mode.mode
                if snapshot.mode == "gaming":
                    services_module._ACTIVE_TRANSCRIPTIONS.enter_gaming()
                    services_module._ACTIVE_CONVERSATIONS.enter_gaming()
                    if hasattr(services_module.APP, "preprocessor") and services_module.APP.preprocessor is not None:
                        try:
                            services_module.APP.preprocessor.pause()
                        except Exception:
                            pass
                elif snapshot.mode == "active" and mode_changed_value:
                    services_module._ACTIVE_TRANSCRIPTIONS.enter_active()
                    services_module._ACTIVE_CONVERSATIONS.enter_active()
                    if hasattr(services_module.APP, "preprocessor") and services_module.APP.preprocessor is not None:
                        try:
                            services_module.APP.preprocessor.resume()
                        except Exception:
                            pass
                if callable(mode_changed):
                    try:
                        cancellation_result = mode_changed(snapshot)
                    except Exception as exc:
                        cancellation_error = type(exc).__name__
                if snapshot.mode == "preprocessing":
                    preprocessor = getattr(services_module.APP, "preprocessor", None)
                    if not isinstance(cancellation_result, dict) or cancellation_result.get("success") is not True:
                        preprocessing_start = {"success": False, "error": "job cancellation incomplete"}
                        if preprocessor is not None:
                            try:
                                preprocessor.pause()
                            except Exception:
                                pass
                    elif preprocessor is None:
                        preprocessing_start = {"success": False, "error": "preprocessor unavailable"}
                    else:
                        try:
                            preprocessing_start = (preprocessor.start_exclusive() if mode_changed_value or not preprocessing_was_ready
                                                   else preprocessor.resume())
                            if isinstance(preprocessing_start, dict) and preprocessing_start.get("success") is True:
                                from .operational_mode import publish_preprocessing_ready
                                publish_preprocessing_ready(state_dir, snapshot)
                                wake = getattr(preprocessor, "_wake_all", None)
                                if callable(wake):
                                    try:
                                        wake()
                                    except Exception:
                                        pass
                        except Exception as exc:
                            preprocessing_start = {"success": False, "error": type(exc).__name__}
                if snapshot.mode == "gaming" and async_jobs is not None:
                    begin_release = getattr(async_jobs, "begin_resource_release", None)
                    if callable(begin_release):
                        release_token = begin_release()
        except ValueError as exc:
            if preprocessing_fence and current_mode is not None and current_mode.mode == "active":
                services_module._ACTIVE_TRANSCRIPTIONS.enter_active()
                services_module._ACTIVE_CONVERSATIONS.enter_active()
            self._send(400, {
                "success": False, "error": str(exc), "error_code": "invalid_mode_request",
                "terminal": True, "retryable": False,
            }); return
        except OSError:
            if preprocessing_fence and current_mode is not None and current_mode.mode == "active":
                services_module._ACTIVE_TRANSCRIPTIONS.enter_active()
                services_module._ACTIVE_CONVERSATIONS.enter_active()
            self._send(503, {
                "success": False, "error": "operational mode could not be persisted",
                "error_code": "mode_persistence_failed", "terminal": True, "retryable": True,
            }); return
        self._telemetry_finished = True
        snap_dict = snapshot.to_dict() if hasattr(snapshot, "to_dict") else dict(snapshot.__dict__)
        response = {"success": True, **snap_dict, "mode_changed": mode_changed_value}
        if snapshot.mode == "preprocessing":
            response["preprocessing_start"] = preprocessing_start if isinstance(preprocessing_start, dict) else {"success": False, "error": "preprocessor start result unavailable"}
        runtime_unload: dict[str, services_module.Any] | None = None
        whisper_release: dict[str, services_module.Any] = {"state": "not_applicable", "inference_active": False}
        conversation_release: dict[str, services_module.Any] = {"state": "not_applicable", "inference_active": False}
        admission_release: dict[str, services_module.Any] = {"state": "not_applicable", "inference_active": False}
        inference_active = False
        preprocessing_active = False
        preprocessor = getattr(services_module.APP, "preprocessor", None)
        if preprocessor is not None:
            try:
                prep_status = preprocessor.status()
                is_paused = bool(prep_status.get("paused")) or bool(getattr(preprocessor, "_paused", None) and preprocessor._paused.is_set())
                preprocessing_active = (not is_paused) and (
                    not isinstance(prep_status, dict) or prep_status.get("success") is not True or any(
                        isinstance(project, dict) and project.get("status") == "running"
                        for project in prep_status.get("projects", [])
                    )
                )
            except Exception:
                preprocessing_active = True
        if snapshot.mode == "gaming":
            drain_deadline = services_module.time.monotonic() + services_module._GAMING_DRAIN_TIMEOUT_SECONDS
            whisper_release = services_module._ACTIVE_TRANSCRIPTIONS.cancel_and_wait(max(0.0, drain_deadline - services_module.time.monotonic()))
            conversation_release = services_module._ACTIVE_CONVERSATIONS.cancel_and_wait(max(0.0, drain_deadline - services_module.time.monotonic()))
            inference_active = inference_active or bool(whisper_release.get("inference_active")) or bool(conversation_release.get("inference_active"))
            drain_waiter = getattr(async_jobs, "wait_for_inference_actions", None)
            tracked_actions = {
                "delegate", "reason", "review", "review_diff", "second_opinion", "compress",
                "route", "batch", "embed", "rerank", "transcribe", "vision", "benchmark",
                "complete_code", "scaffold", "speculative_draft", "generate_tests", "solve",
                "eval_suite", "prompt_eval", "eval_drift",
            }
            if callable(drain_waiter):
                try:
                    drained = bool(drain_waiter(
                        set(tracked_actions), max(0.0, drain_deadline - services_module.time.monotonic())
                    ))
                    admission_release = {
                        "state": "drained" if drained else "timed_out",
                        "inference_active": not drained,
                    }
                except Exception as exc:
                    logger = getattr(services_module.APP, "logger", None)
                    if logger is not None:
                        logger.warning(
                            "gaming inference admission drain failed error_type=%s",
                            type(exc).__name__,
                        )
                    admission_release = {"state": "unavailable", "inference_active": True}
            else:
                admission_release = {
                    "state": "unavailable", "inference_active": True,
                    "reason": "bounded_inference_drain_unavailable",
                }
            active_checker = getattr(async_jobs, "inference_actions_active", None)
            if callable(active_checker):
                try:
                    admission_active = bool(active_checker())
                    admission_release["inference_active"] = bool(
                        admission_release.get("inference_active") or admission_active
                    )
                    if admission_active:
                        admission_release["state"] = "active"
                except Exception as exc:
                    logger = getattr(services_module.APP, "logger", None)
                    if logger is not None:
                        logger.warning(
                            "gaming inference admission status failed error_type=%s",
                            type(exc).__name__,
                        )
                    admission_release = {"state": "unavailable", "inference_active": True}
            else:
                admission_release = {
                    "state": "unavailable", "inference_active": True,
                    "reason": "inference_admission_tracking_unavailable",
                }
            inference_active = inference_active or bool(admission_release.get("inference_active"))
            if inference_active and release_token is not None:
                manager_token = release_token
                release_token = None
                wait_for_drain = getattr(async_jobs, "when_inference_actions_drained", None)
                if callable(wait_for_drain):
                    def release_after_drain() -> None:
                        wait_for_drain(
                            set(tracked_actions),
                            lambda: services_module._perform_deferred_gaming_release(services_module.APP, snapshot.revision, manager_token, async_jobs),
                        )
                    services_module._ACTIVE_TRANSCRIPTIONS.when_drained(
                        lambda: services_module._ACTIVE_CONVERSATIONS.when_drained(release_after_drain)
                    )
                else:
                    admission_release["release_ownership_retained"] = True
        response["whisper_process_release"] = whisper_release
        response["conversation_release"] = conversation_release
        response["inference_admission_release"] = admission_release
        if snapshot.mode == "gaming" and inference_active:
            runtime_unload = {"success": False, "state": "deferred", "reason": "inference_active", "inference_active": True}
            response["runtime_unload"] = runtime_unload
            response["accelerator_release"] = {"success": False, "state": "deferred", "verified": False}
        if snapshot.mode == "gaming" and not inference_active:
            stale_unload = {"success": False, "backend_available": False, "unloaded": [], "failed": {"mode": "stale mode transition"}}
            stale_accelerator = {"success": False, "verified": False, "released": [], "failed": {"mode": "stale mode transition"}}
            if not callable(guard_factory):
                response["success"] = False
                response["mode_transition_stale"] = True
                response["runtime_unload"] = stale_unload
                response["accelerator_release"] = stale_accelerator
            else:
                release_current = False
                with guard_factory():
                    release_snapshot = services_module.load_operational_mode(services_module.APP.config.get("server", {}).get("state_dir", "state"))
                    release_current = not (
                        release_snapshot.degraded
                        or release_snapshot.mode != snapshot.mode
                        or release_snapshot.revision != snapshot.revision
                    )
                if not release_current:
                    response["success"] = False
                    response["mode_transition_stale"] = True
                    response["runtime_unload"] = stale_unload
                    response["accelerator_release"] = stale_accelerator
                    if release_token is not None:
                        async_jobs.end_resource_release(release_token)
                        release_token = None
                else:
                    try:
                            runtime = getattr(services_module.APP, "runtime", None)
                            unload = getattr(runtime, "unload_configured_models", None)
                            if callable(unload):
                                try:
                                    result = unload(timeout_seconds=3.0)
                                    runtime_unload = result if isinstance(result, dict) else {
                                        "success": False, "backend_available": False,
                                        "unloaded": [], "failed": {"backend": "invalid unload result"},
                                    }
                                except Exception as exc:
                                    runtime_unload = {
                                        "success": False, "backend_available": False,
                                        "unloaded": [], "failed": {"backend": type(exc).__name__},
                                    }
                            else:
                                runtime_unload = {
                                    "success": False, "backend_available": False,
                                    "unloaded": [], "failed": {"backend": "unload unavailable"},
                                }
                            response["runtime_unload"] = runtime_unload
                            if preprocessing_active:
                                accelerator_release = {"success": False, "state": "deferred", "verified": False}
                                response["accelerator_release"] = accelerator_release
                            else:
                                components = {
                                    "embeddings": getattr(services_module.APP, "embeddings", None),
                                    "reranker": getattr(services_module.APP, "reranker", None),
                                }
                                accelerator_release: dict[str, services_module.Any] = {
                                    "success": True, "verified": True, "released": [], "failed": {},
                                }
                                cuda_cleanup: dict[str, services_module.Any] = {
                                    "success": True, "state": "not_applicable", "verified": False,
                                }
                                cuda_cleanup_reported = False
                                release_deadline = services_module.time.monotonic() + 3.0
                                for name, component in components.items():
                                    if component is None:
                                        continue
                                    status_fn = getattr(component, "status", None)
                                    release_fn = getattr(component, "release", None)
                                    try:
                                        before = status_fn() if callable(status_fn) else None
                                        if not isinstance(before, dict):
                                            raise RuntimeError("component status unavailable")
                                        reported_cleanup = before.get("cache_cleanup")
                                        if (
                                            str(before.get("active_device", "")).lower().startswith("cuda")
                                            and isinstance(reported_cleanup, dict)
                                        ):
                                            cuda_cleanup = dict(reported_cleanup)
                                            cuda_cleanup_reported = True
                                        if not before.get("loaded") or str(before.get("active_backend", "")).lower() == "ollama":
                                            continue
                                        if not callable(release_fn):
                                            raise RuntimeError("accelerator release unavailable")
                                        timeout = max(0.0, release_deadline - services_module.time.monotonic())
                                        if timeout <= 0.0 or not release_fn(timeout_seconds=timeout):
                                            raise TimeoutError("accelerator release deadline reached")
                                        after = status_fn()
                                        if not isinstance(after, dict) or after.get("loaded"):
                                            raise RuntimeError("accelerator release was not verified")
                                        accelerator_release["released"].append(name)
                                    except Exception as exc:
                                        accelerator_release["success"] = False
                                        accelerator_release["verified"] = False
                                        accelerator_release["failed"][name] = type(exc).__name__
                                if not cuda_cleanup_reported:
                                    cuda_cleanup = api._empty_torch_cuda_cache(
                                        max(0.0, release_deadline - services_module.time.monotonic())
                                    )
                                accelerator_release["cuda_cleanup"] = cuda_cleanup
                                accelerator_release["state"] = (
                                    "complete" if accelerator_release["released"] else
                                    "failed" if accelerator_release["failed"] else "not_applicable"
                                )
                                response["accelerator_release"] = accelerator_release
                    finally:
                        if release_token is not None:
                            async_jobs.end_resource_release(release_token)
                            release_token = None
        if cancellation_error:
            response["job_cancellation"] = {"success": False, "error": cancellation_error}
        elif snapshot.mode == "preprocessing" and (not isinstance(cancellation_result, dict) or cancellation_result.get("success") is not True):
            response["job_cancellation"] = {"success": False, "error": "operational mode cancellation failed or unavailable"}
        elif mode in {"gaming", "maintenance"} and not callable(mode_changed):
            response["job_cancellation"] = {
                "success": False, "error": "operational mode cancellation hook is unavailable",
            }
        if snapshot.mode == "gaming":
            if (
                admission_release.get("state") == "unavailable"
                or whisper_release.get("state") == "timed_out"
                or conversation_release.get("state") == "timed_out"
            ):
                response["success"] = False
            runtime_unload = response.get("runtime_unload", runtime_unload or {})
            if runtime_unload.get("state") is None:
                runtime_unload["state"] = "complete" if runtime_unload.get("success") else "failed"
            accelerator_release = response.get("accelerator_release", {
                "success": True, "verified": False, "released": [], "failed": {},
                "state": "not_applicable",
            })
            if accelerator_release.get("state") is None:
                accelerator_release["state"] = (
                    "complete" if accelerator_release.get("released") else
                    "failed" if accelerator_release.get("failed") else "not_applicable"
                )
            accelerator_release["verified"] = False
            response["resources"] = {
                "in_process_cuda_release": accelerator_release,
                "whisper_process_release": whisper_release,
                "conversation_release": conversation_release,
                "inference_admission_release": admission_release,
                "ollama_unload": runtime_unload,
            }
            response["unload"] = runtime_unload
            response["transition"] = {"preprocessing_active": preprocessing_active}
            services_module._store_mode_unload_status(services_module.APP, response["revision"], runtime_unload)
        self._send(200, response); return

