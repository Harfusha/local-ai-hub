# Ollama model preparation, admission, and unloading extracted from ollama.py
from __future__ import annotations

import json
import logging
import math
import re
import time
from typing import Any

from .llama_cpp import _stop_requested

logger = logging.getLogger(__name__)

_GAMING_UNLOAD_MAX_TIMEOUT_SECONDS = 5.0


class ModelPreparationCancelled(InterruptedError):
    """Preparation stopped because no active scheduler caller still needs it."""

    preparation_cancelled = True

    def __init__(self, message: str, *, operation_not_started: bool = False) -> None:
        super().__init__(message)
        self.operation_not_started = operation_not_started


class ModelPreparationNotStarted(TimeoutError):
    """Provider admission expired before model preparation began."""

    operation_not_started = True


class OllamaModelNotFoundError(RuntimeError):
    """Ollama confirmed that the requested model is absent before inference."""

    operation_not_started = True


class ModelPreparationAdmissionRejected(RuntimeError):
    """A fresh resource check rejected loading after existing models were unloaded."""

    def __init__(self, admission: dict[str, Any], evicted_models: list[str] | None = None):
        self.admission = dict(admission)
        self.evicted_models = list(evicted_models or [])
        super().__init__(str(self.admission.get("reason", "post-unload admission rejected")))


class OllamaModelsMixin:
    def _prepare_ollama_fallback(
        self, model: str, *, unload_others: bool, post_unload_admission: Any | None,
        should_stop: Any, deadline: float,
    ) -> list[str]:
        def check() -> None:
            if should_stop():
                raise ModelPreparationCancelled("model preparation cancelled", operation_not_started=True)
            if time.monotonic() >= deadline:
                raise ModelPreparationNotStarted("model preparation deadline expired")

        check()
        if self._is_embedding_model(model) or not self.ensure_running():
            raise ModelPreparationAdmissionRejected({"state": "rejected", "reason": "ollama_fallback_unavailable"})
        snapshot = self.loaded_model_inventory(should_stop=should_stop, deadline=deadline, force_refresh=True, include_llama=False)
        if not isinstance(snapshot, dict) or snapshot.get("complete") is not True or not isinstance(snapshot.get("models"), list):
            raise ModelPreparationAdmissionRejected({"state": "rejected", "reason": "ollama_fallback_inventory_incomplete"})
        profile = self.model_policy.profile(model)
        evicted: list[str] = []
        keep_current = False
        for row in snapshot["models"]:
            check()
            if not isinstance(row, dict) or row.get("backend") != "ollama":
                raise ModelPreparationAdmissionRejected({"state": "rejected", "reason": "ollama_fallback_inventory_invalid"}, evicted)
            name = str(row.get("name") or row.get("model") or "")
            if not name:
                raise ModelPreparationAdmissionRejected({"state": "rejected", "reason": "ollama_fallback_inventory_invalid"}, evicted)
            if name == model and int(row.get("context_length", 0) or 0) >= profile.num_ctx:
                keep_current = True
                continue
            if name != model and not unload_others:
                raise ModelPreparationAdmissionRejected({"state": "rejected", "reason": "ollama_fallback_other_model_loaded"}, evicted)
            if not self.unload_inventory_model(row, should_stop=should_stop, deadline=deadline):
                raise ModelPreparationAdmissionRejected({"state": "rejected", "reason": "ollama_fallback_unload_unconfirmed"}, evicted)
            evicted.append(name)
        if evicted:
            check()
            verified = self.loaded_model_inventory(should_stop=should_stop, deadline=deadline, force_refresh=True, include_llama=False)
            if (not isinstance(verified, dict) or verified.get("complete") is not True
                    or not isinstance(verified.get("models"), list)
                    or any(not isinstance(row, dict) or row.get("name") != model or row.get("name") in evicted
                           for row in verified["models"])):
                raise ModelPreparationAdmissionRejected({"state": "rejected", "reason": "ollama_fallback_unload_unconfirmed"}, evicted)
        if keep_current:
            return evicted
        if post_unload_admission is not None:
            check()
            try:
                admission = post_unload_admission()
            except Exception as exc:
                raise ModelPreparationAdmissionRejected({"state": "rejected", "reason": "post_unload_admission_failed", "failure_type": type(exc).__name__}, evicted) from exc
            if not isinstance(admission, dict) or admission.get("state") != "admitted":
                rejected = dict(admission) if isinstance(admission, dict) else {}
                rejected.update({"state": "rejected", "reason": rejected.get("reason", "post_unload_admission_rejected")})
                raise ModelPreparationAdmissionRejected(rejected, evicted)
        check()
        payload = {"model": model, "prompt": "", "stream": False,
                   "keep_alive": self.config.get("ollama", {}).get("keep_alive", "24h"),
                   "options": {"num_ctx": profile.num_ctx}}
        result = self._request_stream_tracked("/api/generate", payload, None,
            timeout=max(0.05, min(self.timeout, deadline - time.monotonic())),
            should_stop=should_stop, deadline=deadline, force_ollama=True)
        check()
        if not isinstance(result, dict) or "error" in result or result.get("preempted"):
            raise ModelPreparationAdmissionRejected({"state": "rejected", "reason": "ollama_fallback_load_failed"}, evicted)
        self._invalidate_loaded_cache()
        return evicted

    def prepare_model(
        self,
        model: str,
        *,
        unload_others: bool = True,
        post_unload_admission: Any | None = None,
        should_stop: Any | None = None,
        deadline: float | None = None,
    ) -> list[str]:
        """Ensure ``model`` is resident with the execution policy's context size.

        The scheduler treats this as the authoritative model-switch primitive. Keep
        the method in the runtime rather than duplicating load/unload/context logic in
        scheduler/background callers so all adapters share one contract.
        """
        mixed = isinstance(self.config.get("llama_cpp"), dict) and self.config["llama_cpp"].get("managed_with_ollama") is True
        if mixed:
            limit = time.monotonic() + max(0.05, float(self.config["llama_cpp"].get("model_load_timeout_seconds", 90)))
            if deadline is not None:
                limit = min(limit, float(deadline))
            acquired = False
            try:
                while not acquired:
                    if _stop_requested(should_stop):
                        raise ModelPreparationCancelled(
                            "model preparation cancelled during provider admission",
                            operation_not_started=True,
                        )
                    remaining = limit - time.monotonic()
                    if remaining <= 0:
                        raise ModelPreparationNotStarted(
                            "model preparation deadline expired during provider admission"
                        )
                    acquired = self._mixed_provider_lock.acquire(timeout=min(0.1, remaining))
                return self._prepare_model_impl(model, unload_others=unload_others, post_unload_admission=post_unload_admission,
                                                should_stop=should_stop, deadline=limit)
            finally:
                if acquired:
                    self._mixed_provider_lock.release()
        return self._prepare_model_impl(model, unload_others=unload_others, post_unload_admission=post_unload_admission,
                                        should_stop=should_stop, deadline=deadline)

    def _prepare_model_impl(
        self, model: str, *, unload_others: bool, post_unload_admission: Any | None,
        should_stop: Any | None, deadline: float | None,
    ) -> list[str]:
        model = str(model or "").strip()
        if not model:
            raise ValueError("model is required")

        load_timeout = max(0.05, float(self.config.get("llama_cpp", {}).get("model_load_timeout_seconds", 90)))
        prepare_deadline = time.monotonic() + load_timeout
        if deadline is not None:
            prepare_deadline = min(prepare_deadline, float(deadline))

        def stopped() -> bool:
            return _stop_requested(should_stop)

        load_started = False

        def check_active() -> None:
            if stopped():
                raise ModelPreparationCancelled("model preparation cancelled", operation_not_started=not load_started)
            if time.monotonic() >= prepare_deadline:
                if not load_started:
                    raise ModelPreparationNotStarted("model preparation deadline expired")
                raise TimeoutError("model preparation deadline expired")

        def require_full_gpu_residency(row: dict[str, Any] | None) -> None:
            try:
                size = int(row["size_bytes"]) if row is not None else 0
                vram = int(row["vram_bytes"]) if row is not None else 0
                cpu = int(row["cpu_bytes"]) if row is not None else -1
            except (KeyError, TypeError, ValueError):
                size, vram, cpu = 0, 0, -1
            if size > 0 and vram >= size and cpu == 0:
                return
            unloaded = self.unload_model(model, should_stop=stopped, deadline=prepare_deadline)
            reason = "ollama_cpu_offload_forbidden" if cpu > 0 else "ollama_gpu_residency_unverified"
            raise ModelPreparationAdmissionRejected({
                "state": "rejected",
                "reason": reason,
                "cpu_bytes": cpu if cpu >= 0 else None,
                "unload_confirmed": unloaded,
            })

        check_active()
        llama_options = self.config.get("llama_cpp", {})
        mixed_target = (isinstance(llama_options, dict) and llama_options.get("managed_with_ollama") is True
                        and model == llama_options.get("managed_model_logical"))
        if mixed_target:
            if not callable(post_unload_admission):
                raise ModelPreparationAdmissionRejected({"state": "rejected", "reason": "mixed_vram_admission_required"})
            selected = self.llama_cpp._entry(model)
            if selected is None:
                raise ModelPreparationAdmissionRejected({"state": "rejected", "reason": "mixed_cuda_route_unavailable"})
            managed_status = self.llama_cpp_managed.status()
            managed_online = isinstance(managed_status, dict) and managed_status.get("online") is True
            if (isinstance(managed_status, dict) and managed_status.get("online") is True
                    and not str(managed_status.get("mode", "")).startswith("CUDA")):
                raise ModelPreparationAdmissionRejected({"state": "rejected", "reason": "mixed_cuda_device_unavailable"})

            def fallback_to_ollama(already_evicted: list[str]) -> list[str] | None:
                if llama_options.get("fallback_to_ollama") is not True:
                    return None
                reused = self._mixed_fallback_model == model and self._mixed_fallback_guard is not None
                guard = self._mixed_fallback_guard if reused else self._reserve_mixed_cuda_endpoint()
                if guard is None:
                    return None
                if not reused:
                    # Retain ownership even on an uncertain load outcome. Ollama
                    # can remain resident after a timeout or transport failure.
                    self._mixed_fallback_guard = guard
                    self._mixed_fallback_model = model
                self._mixed_fallback_admitted = False
                self._mixed_fallback_preparing = True
                try:
                    prepared = self._prepare_ollama_fallback(model, unload_others=unload_others,
                        post_unload_admission=post_unload_admission, should_stop=stopped, deadline=prepare_deadline)
                    self._mixed_fallback_admitted = True
                    return already_evicted + prepared
                finally:
                    self._mixed_fallback_preparing = False

            if not managed_online:
                managed_should_stop = lambda: stopped() or time.monotonic() >= prepare_deadline
                if not self.llama_cpp_managed.ensure_running(should_stop=managed_should_stop):
                    check_active()
                    fallback = fallback_to_ollama([])
                    if fallback is not None:
                        return fallback
                    try:
                        startup_error = str(self.llama_cpp_managed.status().get("last_error", ""))
                    except Exception:
                        startup_error = "managed runtime status unavailable"
                    admission = {
                        "state": "rejected",
                        "reason": "mixed_managed_backend_unavailable",
                    }
                    if startup_error:
                        admission["detail"] = startup_error
                    raise ModelPreparationAdmissionRejected(admission)

            snapshot = self.loaded_model_inventory(should_stop=stopped, deadline=prepare_deadline, force_refresh=True)
            if not isinstance(snapshot, dict) or snapshot.get("complete") is not True or not isinstance(snapshot.get("models"), list):
                fallback = fallback_to_ollama([])
                if fallback is not None:
                    return fallback
                raise ModelPreparationAdmissionRejected({"state": "rejected", "reason": "mixed_inventory_incomplete"})
            configured_context = selected[0].get("context_length")
            if (not isinstance(configured_context, int) or isinstance(configured_context, bool)
                    or configured_context < self.model_policy.profile(model).num_ctx):
                raise ModelPreparationAdmissionRejected({"state": "rejected", "reason": "mixed_cuda_context_insufficient"})
            evicted: list[str] = []

            def is_selected_cuda(row: Any) -> bool:
                return (isinstance(row, dict) and row.get("backend") == "llama.cpp-cuda"
                        and row.get("name") == model and row.get("endpoint_url") == selected[1])

            selected_loaded = False
            for row in snapshot["models"]:
                check_active()
                if is_selected_cuda(row):
                    if row.get("status") != "loaded":
                        raise ModelPreparationAdmissionRejected({"state": "rejected", "reason": "mixed_cuda_residency_unverified"}, evicted)
                    selected_loaded = True
                    continue
                if not isinstance(row, dict) or not unload_others:
                    raise ModelPreparationAdmissionRejected({"state": "rejected", "reason": "mixed_other_model_loaded"}, evicted)
                if not self.unload_inventory_model(row, should_stop=stopped, deadline=prepare_deadline):
                    raise ModelPreparationAdmissionRejected({"state": "rejected", "reason": "mixed_unload_unconfirmed"}, evicted)
                evicted.append(str(row.get("name") or row.get("model") or ""))
            if evicted:
                check_active()
                verified = self.loaded_model_inventory(should_stop=stopped, deadline=prepare_deadline, force_refresh=True)
                if (not isinstance(verified, dict) or verified.get("complete") is not True or not isinstance(verified.get("models"), list)
                        or any(not is_selected_cuda(row) or row.get("status") != "loaded" for row in verified["models"])):
                    raise ModelPreparationAdmissionRejected({"state": "rejected", "reason": "mixed_unload_unconfirmed"}, evicted)
                selected_loaded = any(is_selected_cuda(row) for row in verified["models"])
            if post_unload_admission is not None and not selected_loaded:
                check_active()
                try:
                    admission = post_unload_admission()
                except Exception as exc:
                    raise ModelPreparationAdmissionRejected({"state": "rejected", "reason": "post_unload_admission_failed",
                        "failure_type": type(exc).__name__}, evicted) from exc
                if not isinstance(admission, dict) or admission.get("state") != "admitted":
                    rejected = dict(admission) if isinstance(admission, dict) else {}
                    rejected.update({"state": "rejected", "reason": rejected.get("reason", "post_unload_admission_rejected")})
                    raise ModelPreparationAdmissionRejected(rejected, evicted)
            check_active()
            load_started = True
            if self.llama_cpp.ensure_model(model, timeout=max(0.05, prepare_deadline - time.monotonic()),
                                           should_stop=stopped, deadline=prepare_deadline):
                check_active()
                loaded = self.loaded_model_inventory(should_stop=stopped, deadline=prepare_deadline, force_refresh=True)
                if (isinstance(loaded, dict) and loaded.get("complete") is True
                        and isinstance(loaded.get("models"), list) and len(loaded["models"]) == 1
                        and is_selected_cuda(loaded["models"][0]) and loaded["models"][0].get("status") == "loaded"):
                    return evicted
                raise ModelPreparationAdmissionRejected({"state": "rejected", "reason": "mixed_cuda_residency_unverified"}, evicted)
            check_active()
            fallback = fallback_to_ollama(evicted)
            if fallback is not None:
                return fallback
            raise ModelPreparationAdmissionRejected({"state": "rejected", "reason": "mixed_cuda_load_unavailable"}, evicted)
        # llama.cpp loads the configured GGUF in its local server. Avoid also
        # loading that same model into Ollama when the SYCL endpoint is ready.
        llama_enabled = str(self.config.get("llama_cpp", {}).get("mode", "auto")).strip().lower() != "off"
        if post_unload_admission is not None and llama_enabled and self.llama_cpp.supports_model(model):
            raise ModelPreparationAdmissionRejected({
                "state": "rejected", "reason": "post_unload_admission_unsupported_backend",
                "vram_admission": "rejected", "vram_admission_phase": "post_unload",
            })
        load_started = True
        if self.llama_cpp.ensure_model(
            model,
            timeout=max(0.05, min(load_timeout, prepare_deadline - time.monotonic())),
            should_stop=stopped,
            deadline=prepare_deadline,
        ):
            return []
        check_active()
        if llama_enabled and not bool(self.config.get("llama_cpp", {}).get("fallback_to_ollama", True)) and self.llama_cpp.supports_model(model):
            raise RuntimeError("configured llama.cpp SYCL model is not available")
        if not self.ensure_running():
            raise RuntimeError("Ollama is not available")
        check_active()

        profile = self.model_policy.profile(model)
        self._invalidate_loaded_cache()
        details = self.loaded_model_details(should_stop=stopped, deadline=prepare_deadline)
        check_active()
        evicted: list[str] = []
        current = next((row for row in details if str(row.get("name", "")) == model), None)

        if unload_others:
            for row in details:
                check_active()
                name = str(row.get("name", "") or "")
                if name and name != model and self.unload_model(name, should_stop=stopped, deadline=prepare_deadline):
                    evicted.append(name)
                check_active()

        if current is not None:
            require_full_gpu_residency(current)
            if int(current.get("context_length", 0) or 0) >= profile.num_ctx:
                return evicted

        # A runner loaded with a smaller context cannot be safely reused for a larger
        # request. Explicitly unload it so Ollama recreates the runner with num_ctx.
        if current is not None:
            check_active()
            if self.unload_model(model, should_stop=stopped, deadline=prepare_deadline):
                evicted.append(model)
            check_active()

        if post_unload_admission is not None:
            check_active()
            try:
                admission = post_unload_admission()
            except Exception as exc:
                raise ModelPreparationAdmissionRejected({
                    "state": "rejected", "reason": "post_unload_admission_failed",
                    "vram_admission": "rejected", "vram_admission_phase": "post_unload",
                    "failure_type": type(exc).__name__,
                }, evicted) from exc
            if not isinstance(admission, dict) or admission.get("state") != "admitted":
                rejected_admission = dict(admission) if isinstance(admission, dict) else {}
                rejected_admission["state"] = "rejected"
                rejected_admission.setdefault("reason", "post_unload_admission_rejected")
                rejected_admission.setdefault("vram_admission", "rejected")
                rejected_admission.setdefault("vram_admission_phase", "post_unload")
                raise ModelPreparationAdmissionRejected(rejected_admission, evicted)
            check_active()

        load_started = True
        keep_alive = self.config.get("ollama", {}).get("keep_alive", "24h")
        if self._is_embedding_model(model):
            payload = {"model": model, "input": [""], "keep_alive": keep_alive}
            result = self.request(
                "/api/embed", payload,
                timeout=max(0.05, min(self.timeout, prepare_deadline - time.monotonic())),
                should_stop=stopped, deadline=prepare_deadline,
            )
        else:
            payload = {
                "model": model,
                "prompt": "",
                "stream": False,
                "keep_alive": keep_alive,
                "options": {"num_ctx": profile.num_ctx, "num_predict": 0},
            }
            result = self.request(
                "/api/generate", payload,
                timeout=max(0.05, min(self.timeout, prepare_deadline - time.monotonic())),
                should_stop=stopped, deadline=prepare_deadline,
            )
        if result.get("preempted") or stopped():
            raise ModelPreparationCancelled("model preparation cancelled")
        if time.monotonic() >= prepare_deadline:
            raise TimeoutError("model preparation deadline expired")
        if "error" in result:
            error = str(result.get("error", "model load failed"))
            if error.startswith("HTTP 404:"):
                try:
                    payload = json.loads(error.partition(":")[2].strip())
                except (json.JSONDecodeError, TypeError, UnicodeError):
                    payload = None
                detail = payload.get("error") if isinstance(payload, dict) else None
                if isinstance(detail, str) and re.search(
                    r"\bmodel\b.*\bnot found\b", detail, re.IGNORECASE | re.DOTALL,
                ):
                    raise OllamaModelNotFoundError(error)
            raise RuntimeError(error)
        self._invalidate_loaded_cache()
        details = self.loaded_model_details(should_stop=stopped, deadline=prepare_deadline)
        check_active()
        require_full_gpu_residency(next((row for row in details if str(row.get("name", "")) == model), None))
        return evicted

    def supports_post_unload_admission(self, model: str) -> bool:
        """Whether this model uses Ollama's unload-then-load preparation path."""
        try:
            llama = self.config.get("llama_cpp", {})
            if isinstance(llama, dict) and llama.get("managed_with_ollama") is True and model == llama.get("managed_model_logical"):
                return True
            if str(self.config.get("llama_cpp", {}).get("mode", "auto")).strip().lower() == "off":
                return bool(self.config.get("ollama", {}).get("enabled", False))
            return not bool(self.llama_cpp.supports_model(model))
        except Exception:
            return False

    def requires_post_unload_admission(self, model: str) -> bool:
        llama = self.config.get("llama_cpp", {})
        return bool(isinstance(llama, dict) and llama.get("managed_with_ollama") is True
                    and model == llama.get("managed_model_logical"))

    def unload_model(
        self,
        model: str,
        *,
        should_stop: Any | None = None,
        deadline: float | None = None,
    ) -> bool:
        if self._mixed_fallback_model == model and self._mixed_fallback_guard is not None:
            return self.unload_inventory_model({"name": model, "backend": "ollama"},
                                               should_stop=should_stop, deadline=deadline)
        if self.llama_cpp.supports_model(model) and (
            self.llama_cpp.ready_for_model(model)
            if should_stop is None and deadline is None
            else self.llama_cpp.ready_for_model(model, should_stop=should_stop, deadline=deadline)
        ):
            if should_stop is None and deadline is None:
                return self.llama_cpp.unload_model(model)
            return self.llama_cpp.unload_model(model, should_stop=should_stop, deadline=deadline)
        if not bool(self.config.get("llama_cpp", {}).get("fallback_to_ollama", True)):
            return False
        endpoint = "/api/generate"
        payload: dict[str, Any] = {"model": model, "keep_alive": 0}
        if self._is_embedding_model(model):
            payload["input"] = [""]
            endpoint = "/api/embed"
        result = self.request(endpoint, payload, should_stop=should_stop, deadline=deadline)
        ok = "error" not in result
        if ok:
            self._invalidate_loaded_cache()
        return ok

    def loaded_model_inventory(
        self,
        *,
        should_stop: Any | None = None,
        deadline: float | None = None,
        force_refresh: bool = True,
        include_llama: bool = True,
    ) -> dict[str, Any]:
        """Read fresh, endpoint-identified inventory without empty-on-error fallback."""
        backends: dict[str, dict[str, Any]] = {}
        rows: list[dict[str, Any]] = []
        errors: dict[str, str] = {}
        if bool(self.config.get("ollama", {}).get("enabled", False)):
            endpoint_id = self.base_url
            endpoint_status = "unknown"
            endpoint_rows: list[dict[str, Any]] = []
            try:
                if _stop_requested(should_stop):
                    raise InterruptedError("inventory cancelled")
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError("inventory deadline exceeded")
                response = self.request(
                    "/api/ps",
                    timeout=None if deadline is None else max(0.0, deadline - time.monotonic()),
                    should_stop=should_stop,
                    deadline=deadline,
                )
                if not isinstance(response, dict) or "error" in response or not isinstance(response.get("models"), list):
                    raise RuntimeError("Ollama inventory unavailable or malformed")
                malformed = False
                for index, row in enumerate(response["models"]):
                    if not isinstance(row, dict):
                        errors[f"ollama:{endpoint_id}:row:{index}"] = "model row is not an object"
                        malformed = True
                        continue
                    name = next(
                        (value.strip() for field in ("name", "model") if isinstance((value := row.get(field)), str) and value.strip()),
                        "",
                    )
                    if not name:
                        errors[f"ollama:{endpoint_id}:row:{index}"] = "model row has no usable name or model"
                        malformed = True
                        continue
                    endpoint_rows.append({**row, "name": name, "model": str(row.get("model") or name), "backend": "ollama", "endpoint_id": endpoint_id})
                endpoint_status = "unknown" if malformed else "complete"
                if malformed:
                    raise ValueError("Ollama inventory contains malformed model rows")
                rows.extend(endpoint_rows)
            except Exception as exc:
                errors.setdefault(f"ollama:{endpoint_id}", "cancelled" if _stop_requested(should_stop) else str(exc) or type(exc).__name__)
            backends["ollama"] = {
                "complete": endpoint_status == "complete",
                "endpoints": {endpoint_id: endpoint_status},
                "models": endpoint_rows,
            }

        llama_settings = self.config.get("llama_cpp", {})
        llama_models = llama_settings.get("models", {}) if isinstance(llama_settings, dict) else {}
        llama_mode = str(llama_settings.get("mode", "auto")).strip().lower() if isinstance(llama_settings, dict) else "off"
        if include_llama and llama_mode in {"auto", "on"} and isinstance(llama_models, dict) and llama_models:
            endpoint_status: dict[str, str] = {}
            endpoint_rows: list[dict[str, Any]] = []
            try:
                snapshot = self.llama_cpp.loaded_model_inventory(
                    should_stop=should_stop, deadline=deadline, force_refresh=force_refresh,
                )
                if not isinstance(snapshot, dict) or snapshot.get("complete") is not True or not isinstance(snapshot.get("models"), list):
                    raise RuntimeError("llama.cpp inventory incomplete")
                raw_endpoints = snapshot.get("endpoints")
                if not isinstance(raw_endpoints, dict) or any(value != "complete" for value in raw_endpoints.values()):
                    raise RuntimeError("llama.cpp endpoint inventory incomplete")
                endpoint_status = {str(key): str(value) for key, value in raw_endpoints.items()}
                for index, row in enumerate(snapshot["models"]):
                    if not isinstance(row, dict):
                        raise ValueError(f"llama.cpp model row {index} is not an object")
                    name = next(
                        (value.strip() for field in ("name", "model") if isinstance((value := row.get(field)), str) and value.strip()),
                        "",
                    )
                    endpoint_id = str(row.get("endpoint_url", "")).strip()
                    if not name or not endpoint_id or endpoint_status.get(endpoint_id) != "complete":
                        raise ValueError(f"llama.cpp model row {index} has incomplete identity")
                    endpoint_rows.append({**row, "name": name, "model": str(row.get("model") or name), "backend": str(row.get("backend") or "llama.cpp-sycl"), "endpoint_id": endpoint_id})
                rows.extend(endpoint_rows)
            except Exception as exc:
                errors["llama.cpp"] = "cancelled" if _stop_requested(should_stop) else str(exc) or type(exc).__name__
                if not endpoint_status:
                    endpoint_status = {"llama.cpp": "unknown"}
            backends["llama_cpp"] = {
                "complete": not any(value != "complete" for value in endpoint_status.values()) and "llama.cpp" not in errors,
                "endpoints": endpoint_status,
                "models": endpoint_rows,
            }

        return {
            "complete": all(item["complete"] for item in backends.values()),
            "backend_available": bool(backends) and any(item["complete"] for item in backends.values()),
            "observed_at_monotonic": time.monotonic(),
            "backends": backends,
            "models": rows,
            "errors": errors,
        }

    def unload_inventory_model(
        self,
        row: dict[str, Any],
        *,
        should_stop: Any | None = None,
        deadline: float | None = None,
    ) -> bool:
        """Unload one inventory row through the backend and endpoint that owns it."""
        name = str(row.get("name") or row.get("model") or "").strip()
        if not name:
            return False
        backend = str(row.get("backend", ""))
        if backend == "ollama":
            if not bool(self.config.get("ollama", {}).get("enabled", False)):
                return False
            response = self._request_stream_tracked(
                "/api/generate", {"model": name, "prompt": "", "keep_alive": 0}, None,
                timeout=None if deadline is None else max(0.0, deadline - time.monotonic()),
                should_stop=should_stop, deadline=deadline, force_ollama=True,
            )
            ok = isinstance(response, dict) and "error" not in response and response.get("done_reason") == "unload"
            if ok:
                self._invalidate_loaded_cache()
                ok = self._confirm_mixed_fallback_unloaded(name, should_stop=should_stop, deadline=deadline)
            return ok
        endpoint_url = str(row.get("endpoint_id") or row.get("endpoint_url") or "").strip()
        if backend in {"llama.cpp-sycl", "llama.cpp-cuda", "llama.cpp-cpu"} and endpoint_url:
            served = str(row.get("served_model") or name).strip()
            if served != name:
                resolve = getattr(self.llama_cpp, "recovery_alias_for_model", None)
                configured = self.llama_cpp._entry(name)
                configured_match = (configured is not None and configured[1] == endpoint_url
                                    and str(configured[0].get("served_model") or name).strip() == served)
                if not configured_match and (not callable(resolve) or resolve(name) != served):
                    return False
            return bool(self.llama_cpp.unload_model(served, endpoint_url=endpoint_url, should_stop=should_stop, deadline=deadline))
        return False

    def unload_configured_models(
        self,
        *,
        timeout_seconds: float = 3.0,
        should_stop: Any | None = None,
        deadline: float | None = None,
        include_llama: bool = True,
    ) -> dict[str, Any]:
        """Request bounded unload and verify the resulting loaded-model state.

        Pause never starts a backend or loads a model. One deadline covers both
        ``/api/ps`` queries and all unload requests. An unload acknowledgement alone
        is not treated as proof that the model left the loaded set. An empty loaded
        set does not prove that physical VRAM was reclaimed.
        """
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a finite positive number")

        timeout = min(float(timeout_seconds), _GAMING_UNLOAD_MAX_TIMEOUT_SECONDS)
        unload_deadline = time.monotonic() + timeout
        if deadline is not None:
            if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
                raise ValueError("deadline must be a finite monotonic timestamp")
            unload_deadline = min(unload_deadline, float(deadline))
        unloaded: list[str] = []
        failed: dict[str, str] = {}
        ollama_enabled = bool(self.config.get("ollama", {}).get("enabled", False))
        ollama_endpoint = str(
            getattr(self, "base_url", "")
            or self.config.get("server", {}).get("ollama_url", "")
            or "default"
        ).rstrip("/")

        def request_ollama(endpoint: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
            remaining = max(0.0, unload_deadline - time.monotonic())
            return self.request(
                endpoint, payload, timeout=remaining,
                should_stop=should_stop, deadline=unload_deadline,
            )

        if _stop_requested(should_stop):
            return {
                "success": False,
                "backend_available": False,
                "unloaded": unloaded,
                "failed": {"operation": "unload cancelled"},
                "cancelled": True,
                "requested": [],
                "remaining": None,
                "verified": False,
                "complete": False,
                "unverified": True,
                "physical_vram_reclaimed": False,
            }
        if time.monotonic() >= unload_deadline:
            return {
                "success": False,
                "backend_available": False,
                "unloaded": unloaded,
                "failed": {"operation": "unload deadline exceeded"},
                "requested": [],
                "remaining": None,
                "verified": False,
                "complete": False,
                "unverified": True,
                "physical_vram_reclaimed": False,
            }

        llama_settings = self.config.get("llama_cpp", {})
        llama_models = llama_settings.get("models", {}) if isinstance(llama_settings, dict) else {}
        llama_mode = str(llama_settings.get("mode", "auto")).strip().lower() if isinstance(llama_settings, dict) else "off"
        llama_configured = llama_mode in {"auto", "on"} and isinstance(llama_models, dict) and bool(llama_models)
        # Pause checks every configured auto/on endpoint. A failed or empty
        # convenience probe cannot distinguish an empty inventory from failure.
        llama_active = include_llama and llama_configured

        backend_names = (["ollama"] if ollama_enabled else []) + (["llama_cpp"] if llama_active else [])
        if not backend_names:
            reason = "no configured llama.cpp models" if not llama_configured else "backend unavailable"
            return {
                "success": False, "backend_available": False, "unloaded": unloaded,
                "failed": {"backend": reason}, "requested": [], "remaining": None,
                "verified": False, "complete": False, "unverified": True,
                "physical_vram_reclaimed": False,
            }

        last_llama_endpoint_status: dict[str, str] = {}
        last_llama_urls: dict[str, str] = {}

        def read_llama_inventory() -> tuple[list[dict[str, Any]], dict[str, str]]:
            inventory_reader = getattr(self.llama_cpp, "loaded_model_inventory", None)
            if callable(inventory_reader):
                snapshot = inventory_reader(
                    should_stop=should_stop, deadline=unload_deadline, force_refresh=True,
                )
                if not isinstance(snapshot, dict):
                    raise RuntimeError("llama.cpp inventory incomplete")
                rows = snapshot.get("models")
                if not isinstance(rows, list):
                    raise RuntimeError("llama.cpp inventory incomplete")
                configured_endpoints = {
                    cfg["url"]: "complete"
                    for cfg in llama_models.values()
                    if isinstance(cfg, dict) and cfg.get("url")
                }
                if "endpoints" not in snapshot:
                    endpoints = {
                        str(row["endpoint_url"]): "complete"
                        for row in rows
                        if isinstance(row, dict) and row.get("endpoint_url")
                    } or dict(configured_endpoints)
                else:
                    endpoints = snapshot.get("endpoints")
                    if not isinstance(endpoints, dict):
                        raise RuntimeError("llama.cpp endpoint receipts unavailable")

                if "endpoint_status" not in snapshot:
                    endpoint_status = {
                        str(model_name): "complete" for model_name in llama_models
                    } or {
                        str(row.get("name") or row.get("model")): "complete"
                        for row in rows
                        if isinstance(row, dict) and (row.get("name") or row.get("model"))
                    } or dict(endpoints)
                else:
                    endpoint_status = snapshot.get("endpoint_status")
                    if not isinstance(endpoint_status, dict):
                        raise RuntimeError("llama.cpp endpoint status unavailable")

                if isinstance(endpoint_status, dict) and endpoint_status:
                    last_llama_endpoint_status.clear()
                    last_llama_endpoint_status.update({str(key): str(value) for key, value in endpoint_status.items()})
                if isinstance(endpoints, dict) and endpoints:
                    last_llama_urls.clear()
                    last_llama_urls.update({str(key): str(value) for key, value in endpoints.items()})

                errors = snapshot.get("errors")
                if snapshot.get("complete") is not True or not isinstance(errors, dict) or errors:
                    raise RuntimeError("llama.cpp inventory incomplete")
                if not rows and not endpoint_status and not endpoints:
                    last_llama_endpoint_status.clear()
                    last_llama_urls.clear()
                    return rows, {}
                if (
                    not endpoints
                    or not endpoint_status
                    or any(
                        not isinstance(endpoint, str)
                        or not endpoint.strip()
                        or status != "complete"
                        for endpoint, status in endpoints.items()
                    )
                ):
                    raise RuntimeError("llama.cpp endpoint receipts unavailable")
                last_llama_endpoint_status.clear()
                last_llama_endpoint_status.update({str(key): str(value) for key, value in endpoint_status.items()})
                last_llama_urls.clear()
                last_llama_urls.update({str(key): str(value) for key, value in endpoints.items()})
                if any(
                    status != "complete" for status in endpoint_status.values()
                ):
                    raise RuntimeError("llama.cpp endpoint status unavailable")
                for index, row in enumerate(rows):
                    if (
                        not isinstance(row, dict)
                        or not isinstance(row.get("name") or row.get("model"), str)
                        or not (row.get("name") or row.get("model")).strip()
                        or row.get("endpoint_url") not in endpoints
                    ):
                        raise RuntimeError(f"llama.cpp inventory row {index} is incomplete")
                return rows, dict(last_llama_endpoint_status)
            raise RuntimeError("llama.cpp canonical inventory contract unavailable")

        loaded_rows_by_backend: dict[str, list[dict[str, Any]]] = {}
        failed_by_backend: dict[str, dict[str, str]] = {name: {} for name in backend_names}
        backend_inventory_ok: dict[str, bool] = {}
        backend_inventory_status: dict[str, dict[str, str]] = {}
        for backend in backend_names:
            if _stop_requested(should_stop):
                failed["operation"] = "unload cancelled"
                break
            if time.monotonic() >= unload_deadline:
                failed[backend] = "unload deadline exceeded before inventory"
                backend_inventory_ok[backend] = False
                continue
            try:
                if backend == "ollama":
                    response = request_ollama("/api/ps")
                    if not isinstance(response, dict) or "error" in response or not isinstance(response.get("models"), list):
                        raise RuntimeError("backend unavailable")
                    rows = response["models"]
                    backend_inventory_status[backend] = {"ollama": "complete"}
                else:
                    rows, backend_inventory_status[backend] = read_llama_inventory()
                if _stop_requested(should_stop):
                    raise InterruptedError("unload cancelled")
                loaded_rows_by_backend[backend] = rows
                backend_inventory_ok[backend] = True
            except Exception as exc:
                stopped = _stop_requested(should_stop)
                failed[backend] = "unload cancelled" if stopped else ("backend unavailable" if isinstance(exc, RuntimeError) else type(exc).__name__)
                backend_inventory_ok[backend] = False
                configured_llama_status = {
                    cfg["url"]: "unknown"
                    for cfg in llama_models.values()
                    if isinstance(cfg, dict) and cfg.get("url")
                }
                backend_inventory_status[backend] = (
                    dict(last_llama_endpoint_status) or configured_llama_status or {"llama.cpp": "unknown"}
                    if backend == "llama_cpp" else {"ollama": "unknown"}
                )

        loaded_by_backend: dict[str, list[str]] = {name: [] for name in backend_names}
        loaded_targets_by_backend: dict[str, list[tuple[str, str]]] = {name: [] for name in backend_names}
        requested_by_endpoint: dict[str, list[str]] = {}
        remaining_by_endpoint: dict[str, list[str] | None] = {}
        if "ollama" in backend_names:
            remaining_by_endpoint[f"ollama:{ollama_endpoint}"] = None
        for endpoint_url in last_llama_urls:
            remaining_by_endpoint[f"llama_cpp:{endpoint_url}"] = None
        for backend, rows in loaded_rows_by_backend.items():
            for row_index, row in enumerate(rows):
                if not isinstance(row, dict):
                    failed_by_backend[backend][f"model_row_{row_index}"] = "loaded model row is not an object"
                    backend_inventory_ok[backend] = False
                    if backend == "ollama":
                        backend_inventory_status[backend] = {"ollama": "unknown"}
                    continue
                model = next(
                    (value.strip() for field in ("name", "model") if isinstance((value := row.get(field)), str) and value.strip()),
                    "",
                )
                if not model:
                    failed_by_backend[backend][f"model_row_{row_index}"] = "loaded model row has no usable name or model"
                    backend_inventory_ok[backend] = False
                    if backend == "ollama":
                        backend_inventory_status[backend] = {"ollama": "unknown"}
                    continue
                endpoint_url = ollama_endpoint if backend == "ollama" else str(row.get("endpoint_url", "")).strip()
                if not endpoint_url:
                    failed_by_backend[backend][f"model_row_{row_index}"] = "loaded llama.cpp row has no endpoint identity"
                    backend_inventory_ok[backend] = False
                    for known_endpoint in list(last_llama_urls):
                        last_llama_urls[known_endpoint] = "unknown"
                    continue
                if (model, endpoint_url) not in loaded_targets_by_backend[backend]:
                    loaded_targets_by_backend[backend].append((model, endpoint_url))
                remaining_by_endpoint.setdefault(f"{backend}:{endpoint_url}", None)
                if model not in loaded_by_backend[backend]:
                    loaded_by_backend[backend].append(model)

        cancelled = bool(_stop_requested(should_stop))
        requested_by_backend: dict[str, list[str]] = {name: [] for name in backend_names}
        for backend, targets in loaded_targets_by_backend.items():
            for model_index, (model, endpoint_url) in enumerate(targets):
                if _stop_requested(should_stop):
                    cancelled = True
                    for pending, _endpoint in targets[model_index:]:
                        failed_by_backend[backend][pending] = "unload cancelled"
                    break
                if time.monotonic() >= unload_deadline:
                    failed_by_backend[backend][model] = "unload deadline exceeded"
                    continue
                requested_by_backend[backend].append(model)
                requested_by_endpoint.setdefault(f"{backend}:{endpoint_url}", []).append(model)
                try:
                    if backend == "ollama":
                        response = request_ollama(
                            "/api/generate", {"model": model, "prompt": "", "keep_alive": 0},
                        )
                        ok = isinstance(response, dict) and "error" not in response and response.get("done_reason") == "unload"
                        if ok:
                            self._invalidate_loaded_cache()
                    else:
                        ok = self.llama_cpp.unload_model(
                            model, endpoint_url=endpoint_url,
                            should_stop=should_stop, deadline=unload_deadline,
                        )
                except Exception as exc:
                    ok = False
                    failed_by_backend[backend][model] = "unload cancelled" if _stop_requested(should_stop) else type(exc).__name__
                if not ok and model not in failed_by_backend[backend]:
                    failed_by_backend[backend][model] = "unload cancelled" if _stop_requested(should_stop) else "unload failed or timed out"
                cancelled = cancelled or _stop_requested(should_stop)

        requested = [model for backend in backend_names for model in requested_by_backend[backend]]
        for backend, errors in failed_by_backend.items():
            for key, value in errors.items():
                failed[f"{backend}:{key}" if len(backend_names) > 1 else key] = value

        remaining_by_backend: dict[str, list[str] | None] = {name: None for name in backend_names}
        verification_errors: list[str] = []
        if _stop_requested(should_stop):
            cancelled = True
            verification_errors.append("unload cancelled before verification")
        elif time.monotonic() >= unload_deadline:
            verification_errors.append("unload deadline exceeded before verification")
        else:
            for backend in backend_names:
                try:
                    if backend == "ollama":
                        response = request_ollama("/api/ps")
                        if not isinstance(response, dict) or "error" in response or not isinstance(response.get("models"), list):
                            raise RuntimeError("post-unload /api/ps unavailable")
                        rows = response["models"]
                        endpoint_rows = {ollama_endpoint: []}
                    else:
                        rows, post_endpoint_status = read_llama_inventory()
                        backend_inventory_status[backend] = post_endpoint_status
                        endpoint_rows = {url: [] for url, state in last_llama_urls.items() if state == "complete"}
                    parsed: list[str] = []
                    for row_index, row in enumerate(rows):
                        if not isinstance(row, dict):
                            raise ValueError(f"post-unload model row {row_index} is not an object")
                        name = next(
                            (value.strip() for field in ("name", "model") if isinstance((value := row.get(field)), str) and value.strip()),
                            "",
                        )
                        if not name:
                            raise ValueError(f"post-unload model row {row_index} has no usable name or model")
                        endpoint_url = ollama_endpoint if backend == "ollama" else str(row.get("endpoint_url", "")).strip()
                        if not endpoint_url or endpoint_url not in endpoint_rows:
                            raise ValueError(f"post-unload model row {row_index} has unknown endpoint identity")
                        endpoint_rows[endpoint_url].append(name)
                        if name not in parsed:
                            parsed.append(name)
                    if _stop_requested(should_stop):
                        cancelled = True
                        raise InterruptedError("unload cancelled during verification")
                    if time.monotonic() >= unload_deadline:
                        raise TimeoutError("unload deadline exceeded during verification")
                    remaining_by_backend[backend] = parsed
                    for endpoint_url, endpoint_models in endpoint_rows.items():
                        remaining_by_endpoint[f"{backend}:{endpoint_url}"] = endpoint_models
                except Exception as exc:
                    if backend == "llama_cpp":
                        backend_inventory_status[backend] = dict(last_llama_endpoint_status) or {"llama.cpp": "unknown"}
                    reason = "unload cancelled during verification" if _stop_requested(should_stop) else str(exc) if isinstance(exc, (RuntimeError, ValueError, TimeoutError)) else f"post-unload verification failed: {type(exc).__name__}"
                    verification_errors.append(f"{backend}: {reason}")

        remaining_models = None if any(value is None for value in remaining_by_backend.values()) else [
            model for backend in backend_names for model in (remaining_by_backend[backend] or [])
        ]
        if verification_errors:
            failed["verification"] = "; ".join(verification_errors)
        verified = (
            not verification_errors
            and all(backend_inventory_ok.get(name, False) for name in backend_names)
            and not any(failed_by_backend.values())
            and all(name not in (remaining_by_backend[backend] or []) for backend in backend_names for name in requested_by_backend[backend])
        )
        inventory_complete = all(backend_inventory_ok.get(name, False) for name in backend_names)
        complete = remaining_models is not None and not remaining_models and inventory_complete
        if remaining_models is not None:
            unloaded = [
                name for backend in backend_names for name in requested_by_backend[backend]
                if name not in (remaining_by_backend[backend] or [])
            ]
        else:
            unloaded = [
                name for backend in backend_names for name in requested_by_backend[backend]
                if remaining_by_backend.get(backend) is not None
                and name not in (remaining_by_backend[backend] or [])
            ]
        backend_available = bool(loaded_rows_by_backend)
        endpoint_receipts: dict[str, dict[str, Any]] = {}
        for backend in backend_names:
            endpoints = (
                {ollama_endpoint: backend_inventory_status.get(backend, {}).get("ollama", "unknown")}
                if backend == "ollama" else (last_llama_urls or {"llama.cpp": "unknown"})
            )
            for endpoint_id, endpoint_state in endpoints.items():
                receipt_key = f"{backend}:{endpoint_id}"
                requested_at_endpoint = requested_by_endpoint.get(receipt_key, [])
                remaining_at_endpoint = remaining_by_endpoint.get(receipt_key)
                receipt_state = endpoint_state if backend_inventory_ok.get(backend, False) else "unknown"
                endpoint_receipts[f"{backend}:{endpoint_id}"] = {
                    "backend": backend,
                    "endpoint_id": endpoint_id,
                    "inventory_status": receipt_state,
                    "requested": requested_at_endpoint,
                    "remaining": remaining_at_endpoint,
                    "complete": receipt_state == "complete" and isinstance(remaining_at_endpoint, list),
                }
        result = {
            "success": complete and not failed,
            "backend_available": backend_available,
            "unloaded": unloaded,
            "failed": failed,
            "requested": requested,
            "remaining": remaining_models,
            "requested_by_backend": requested_by_backend,
            "remaining_by_backend": remaining_by_backend,
            "backend_inventory_status": backend_inventory_status,
            "endpoint_receipts": endpoint_receipts,
            "verified": verified,
            "complete": complete,
            "unverified": remaining_models is None or not inventory_complete,
            "physical_vram_reclaimed": False,
        }
        if cancelled:
            result["cancelled"] = True
        return result

