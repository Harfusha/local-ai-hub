from __future__ import annotations

import copy
import math
import threading
import time
from typing import Any, cast

from .model_policy import ModelExecutionPolicy
from .ollama import ModelPreparationCancelled, OllamaRuntime


class _HandoffCancelled(Exception):
    pass


class TieredOllamaRuntime:
    """Route smart models through a Hub-owned Ollama sidecar.

    The external runtime stays user-managed. This facade owns only the smart
    runtime and serializes model residency across both endpoints.
    """

    def __init__(
        self,
        config: dict[str, Any],
        *,
        fast_runtime: Any | None = None,
        smart_runtime: Any | None = None,
    ) -> None:
        self.config = config
        self.policy = ModelExecutionPolicy(config)
        self.fast = fast_runtime or OllamaRuntime(config)
        self.smart = smart_runtime or OllamaRuntime(self._smart_config(), managed_name="ollama-smart")
        self._lock = threading.RLock()
        self._handoff_count = 0
        self._unload_failures = 0
        self._last_handoff_error: str | None = None
        self._active_endpoint: str | None = None
        self._hub_models = {str(model) for model in config.get("models", {}).values() if str(model or "")}
        llama_models = config.get("llama_cpp", {}).get("models", {})
        if isinstance(llama_models, dict):
            for key, value in llama_models.items():
                if key:
                    self._hub_models.add(str(key))
                if isinstance(value, dict):
                    for field in ("served_model", "served_id", "model", "name"):
                        if value.get(field):
                            self._hub_models.add(str(value[field]))

    def _smart_config(self) -> dict[str, Any]:
        smart_cfg = self.config.get("smart_ollama", {})
        cfg = copy.deepcopy(self.config)
        cfg.setdefault("server", {})["ollama_url"] = str(smart_cfg.get("url", "http://127.0.0.1:11437")).rstrip("/")
        cfg.setdefault("headless", {})["autostart_ollama"] = True
        cfg.setdefault("scheduler", {})["max_parallel"] = 1
        cfg["scheduler"]["max_loaded_models"] = 1
        ollama = cfg.setdefault("ollama", {})
        ollama["num_parallel"] = max(1, int(smart_cfg.get("num_parallel", 1)))
        ollama["keep_alive"] = str(smart_cfg.get("keep_alive", "10m"))
        ollama["flash_attention"] = bool(smart_cfg.get("flash_attention", True))
        ollama["kv_cache_type"] = str(smart_cfg.get("kv_cache_type", "q8_0"))
        ollama["startup_timeout_seconds"] = float(smart_cfg.get("startup_timeout_seconds", 30))
        model = str(smart_cfg.get("model") or cfg.get("models", {}).get("heavy_code", ""))
        if model:
            cfg.setdefault("models", {})["heavy_code"] = model
            cfg["models"]["reasoning"] = model
        execution = cfg.setdefault("model_execution", {}).setdefault("smart", {})
        context = max(4096, int(smart_cfg.get("context_length", 32768)))
        execution["context_tokens"] = context
        execution["large_context_tokens"] = context
        execution["max_context_tokens"] = context
        execution["parallel"] = 1
        return cfg

    def _runtime_for_model(self, model: str) -> tuple[str, Any, Any]:
        if self.policy.tier_for(model) == "smart":
            return "smart", self.smart, self.fast
        return "fast", self.fast, self.smart

    @staticmethod
    def _details(runtime: Any) -> list[dict[str, Any]]:
        try:
            rows = runtime.loaded_model_details()
        except Exception:
            return []
        return [row for row in rows if isinstance(row, dict)]

    @staticmethod
    def _inventory(runtime: Any, *, deadline: float | None = None) -> list[dict[str, Any]]:
        reader = getattr(runtime, "loaded_model_inventory", None)
        if not callable(reader):
            raise RuntimeError("peer runtime has no strict loaded-model inventory")
        snapshot = reader(force_refresh=True, deadline=deadline)
        if not isinstance(snapshot, dict) or snapshot.get("complete") is not True:
            raise RuntimeError("peer runtime inventory incomplete")
        backends = snapshot.get("backends")
        if not isinstance(backends, dict) or any(
            not isinstance(details, dict)
            or details.get("complete") is not True
            or not isinstance(details.get("endpoints"), dict)
            or any(state != "complete" for state in details["endpoints"].values())
            for details in backends.values()
        ):
            raise RuntimeError("peer runtime endpoint inventory incomplete")
        rows = snapshot.get("models")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise RuntimeError("peer runtime inventory malformed")
        return rows

    @staticmethod
    def _check_handoff(should_stop: Any, deadline: float) -> None:
        try:
            if callable(should_stop) and should_stop():
                raise _HandoffCancelled("request cancelled during model handoff")
        except _HandoffCancelled:
            raise
        except Exception as exc:
            raise _HandoffCancelled("request cancellation check failed") from exc
        if time.monotonic() >= deadline:
            raise TimeoutError("model handoff deadline expired")

    def _unload_peer(self, peer: Any, *, deadline: float, should_stop: Any = None) -> None:
        self._check_handoff(should_stop, deadline)
        rows = self._inventory(peer, deadline=deadline)
        self._check_handoff(should_stop, deadline)
        foreign = [str(row.get("name", "")) for row in rows if str(row.get("name", "")) not in self._hub_models]
        if foreign:
            self._last_handoff_error = f"peer runtime holds externally managed model: {foreign[0]}"
            raise RuntimeError(self._last_handoff_error)
        for row in rows:
            self._check_handoff(should_stop, deadline)
            model = str(row.get("name", "") or "")
            unload_inventory_row = getattr(peer, "unload_inventory_model", None)
            try:
                unloaded = (
                    unload_inventory_row(row, deadline=deadline, **({"should_stop": should_stop} if should_stop is not None else {}))
                    if callable(unload_inventory_row) and row.get("backend") else peer.unload_model(model)
                )
            except Exception as exc:
                unloaded = False
                self._last_handoff_error = f"cannot unload {model} from peer runtime: {type(exc).__name__}"
            if model and not unloaded:
                self._check_handoff(should_stop, deadline)
                self._unload_failures += 1
                self._last_handoff_error = self._last_handoff_error or f"cannot unload {model} from peer runtime"
                raise RuntimeError(self._last_handoff_error)

    def _handoff(self, name: str, target: Any, peer: Any, *, should_stop: Any = None, deadline: float | None = None) -> None:
        timeout = max(0.1, float(self.config.get("smart_ollama", {}).get("handoff_timeout_seconds", 10)))
        handoff_deadline = time.monotonic() + timeout
        deadline = min(deadline, handoff_deadline) if deadline is not None else handoff_deadline
        self._unload_peer(peer, deadline=deadline, should_stop=should_stop)
        while True:
            self._check_handoff(should_stop, deadline)
            if not self._inventory(peer, deadline=deadline):
                break
            if time.monotonic() >= deadline:
                self._unload_failures += 1
                self._last_handoff_error = "peer runtime remained loaded after handoff deadline"
                raise RuntimeError(self._last_handoff_error)
            time.sleep(0.05)
        self._check_handoff(should_stop, deadline)
        if not target.ensure_running():
            self._last_handoff_error = f"{name} runtime unavailable"
            raise RuntimeError(self._last_handoff_error)
        self._handoff_count += 1
        self._last_handoff_error = None
        self._active_endpoint = name

    def _target(self, model: str, *, should_stop: Any = None, deadline: float | None = None) -> tuple[Any, str]:
        name, target, peer = self._runtime_for_model(model)
        self._handoff(name, target, peer, should_stop=should_stop, deadline=deadline)
        return target, name

    def _acquire_request_lock(self, should_stop: Any, deadline: float | None) -> dict[str, Any] | None:
        while True:
            try:
                if callable(should_stop) and should_stop():
                    return {"success": False, "preempted": True, "error": "request cancelled while waiting for model handoff"}
            except Exception:
                return {"success": False, "preempted": True, "error": "request cancellation check failed"}
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return {"success": False, "timed_out": True, "error": "model handoff deadline expired"}
            if self._lock.acquire(timeout=0.05 if remaining is None else min(0.05, remaining)):
                return None

    def request(self, endpoint: str, payload: dict[str, Any] | None = None, timeout: float | None = None) -> dict[str, Any]:
        model = str((payload or {}).get("model", ""))
        if not model:
            return self.fast.request(endpoint, payload, timeout)
        with self._lock:
            try:
                target, _ = self._target(model)
            except TimeoutError as exc:
                return {"success": False, "timed_out": True, "error": str(exc)}
            except RuntimeError as exc:
                return {"error": str(exc), "retryable": True}
            return target.request(endpoint, payload, timeout)

    def request_stream(self, endpoint: str, payload: dict[str, Any] | None, on_chunk: Any, timeout: float | None = None, *, on_thinking: Any | None = None, should_stop: Any | None = None, deadline: float | None = None) -> dict[str, Any]:
        cancellation = {"should_stop": should_stop, "deadline": deadline} if should_stop is not None or deadline is not None else {}
        model = str((payload or {}).get("model", ""))
        if not model:
            return self.fast.request_stream(endpoint, payload, on_chunk, timeout, on_thinking=on_thinking, **cancellation)
        lock_deadline = min(deadline, time.monotonic() + timeout) if deadline is not None and timeout is not None else deadline if deadline is not None else time.monotonic() + timeout if timeout is not None else None
        failure = self._acquire_request_lock(should_stop, lock_deadline)
        if failure is not None:
            return failure
        try:
            if callable(should_stop) and should_stop():
                return {"success": False, "preempted": True, "error": "request cancelled before model handoff"}
            try:
                target, _ = self._target(model, should_stop=should_stop, deadline=lock_deadline)
            except _HandoffCancelled as exc:
                return {"success": False, "preempted": True, "error": str(exc)}
            except TimeoutError as exc:
                return {"success": False, "timed_out": True, "error": str(exc)}
            except RuntimeError as exc:
                return {"error": str(exc), "retryable": True}
            if callable(should_stop) and should_stop():
                return {"success": False, "preempted": True, "error": "request cancelled during model handoff"}
            remaining = None if lock_deadline is None else lock_deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return {"success": False, "timed_out": True, "error": "model handoff deadline expired"}
            target_timeout = min(timeout, remaining) if timeout is not None and remaining is not None else timeout
            return target.request_stream(endpoint, payload, on_chunk, target_timeout, on_thinking=on_thinking, **cancellation)
        finally:
            self._lock.release()

    def request_interruptible(
        self,
        endpoint: str,
        payload: dict[str, Any] | None,
        should_stop: Any,
        *,
        timeout: float | None = None,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        model = str((payload or {}).get("model", ""))
        lock_deadline = min(deadline, time.monotonic() + timeout) if deadline is not None and timeout is not None else deadline if deadline is not None else time.monotonic() + timeout if timeout is not None else None
        failure = self._acquire_request_lock(should_stop, lock_deadline)
        if failure is not None:
            return failure
        try:
            if callable(should_stop) and should_stop():
                return {"success": False, "preempted": True, "error": "request cancelled before model handoff"}
            try:
                target, _ = self._target(model, should_stop=should_stop, deadline=lock_deadline)
            except _HandoffCancelled as exc:
                return {"success": False, "preempted": True, "error": str(exc)}
            except TimeoutError as exc:
                return {"success": False, "timed_out": True, "error": str(exc)}
            except RuntimeError as exc:
                return {"error": str(exc), "retryable": True}
            if callable(should_stop) and should_stop():
                return {"success": False, "preempted": True, "error": "request cancelled during model handoff"}
            remaining = None if lock_deadline is None else lock_deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return {"success": False, "timed_out": True, "error": "model handoff deadline expired"}
            target_timeout = min(timeout, remaining) if timeout is not None and remaining is not None else timeout
            return target.request_interruptible(endpoint, payload, should_stop, timeout=target_timeout, deadline=deadline)
        finally:
            self._lock.release()

    def run_benchmark_scenario(
        self,
        *,
        name: str,
        contract: dict[str, Any],
        scheduler: Any,
        resource_sampler: Any | None = None,
    ) -> dict[str, Any]:
        # Reuse the Ollama executor on this facade. Its scheduled callback resolves
        # the selected tier through request_interruptible, so handoff/load stays
        # inside the measured queue and deadline window.
        return OllamaRuntime.run_benchmark_scenario(
            cast(Any, self), name=name, contract=contract, scheduler=scheduler,
            resource_sampler=resource_sampler,
        )

    def prepare_model(
        self,
        model: str,
        *,
        unload_others: bool = True,
        post_unload_admission: Any | None = None,
        should_stop: Any | None = None,
        deadline: float | None = None,
    ) -> list[str]:
        failure = self._acquire_request_lock(should_stop, deadline)
        if failure is not None:
            if failure.get("preempted"):
                raise ModelPreparationCancelled(str(failure["error"]))
            raise TimeoutError(str(failure["error"]))
        try:
            try:
                target, _ = self._target(model, should_stop=should_stop, deadline=deadline)
            except _HandoffCancelled as exc:
                raise ModelPreparationCancelled(str(exc)) from exc
            kwargs: dict[str, Any] = {"unload_others": unload_others}
            if post_unload_admission is not None:
                kwargs["post_unload_admission"] = post_unload_admission
            if should_stop is not None or deadline is not None:
                kwargs.update(should_stop=should_stop, deadline=deadline)
            return target.prepare_model(model, **kwargs)
        finally:
            self._lock.release()

    def supports_post_unload_admission(self, model: str) -> bool:
        _, target, _ = self._runtime_for_model(model)
        capability = getattr(target, "supports_post_unload_admission", None)
        if not callable(capability):
            return False
        try:
            return bool(capability(model))
        except Exception:
            return False

    def unload(self, model: str) -> bool:
        return self.unload_model(model)

    def unload_model(self, model: str, *, should_stop: Any | None = None, deadline: float | None = None) -> bool:
        _, target, _ = self._runtime_for_model(model)
        if should_stop is not None or deadline is not None:
            return bool(target.unload_model(model, should_stop=should_stop, deadline=deadline))
        return bool(target.unload_model(model))

    def unload_configured_models(
        self,
        *,
        timeout_seconds: float = 3.0,
        should_stop: Any | None = None,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        """Unload both Ollama tiers and shared llama.cpp endpoints with receipts."""
        try:
            timeout = float(timeout_seconds)
        except (TypeError, ValueError):
            timeout = 0.0
        if not math.isfinite(timeout) or timeout <= 0:
            return {
                "success": False, "backend_available": False, "requested": [], "unloaded": [],
                "remaining": None, "failed": {"operation": "timeout_seconds must be positive"},
                "verified": False, "complete": False, "unverified": True,
                "by_runtime": {}, "physical_vram_reclaimed": False,
            }
        if deadline is not None and (isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not math.isfinite(deadline)):
            return {
                "success": False, "backend_available": False, "requested": [], "unloaded": [],
                "remaining": None, "failed": {"operation": "deadline must be a finite monotonic timestamp"},
                "verified": False, "complete": False, "unverified": True,
                "by_runtime": {}, "physical_vram_reclaimed": False,
            }
        end = min(time.monotonic() + timeout, float(deadline) if deadline is not None else float("inf"))
        reports: dict[str, dict[str, Any]] = {}
        with self._lock:
            for name, runtime, include_llama in (("fast", self.fast, True), ("smart", self.smart, False)):
                remaining_seconds = max(0.001, end - time.monotonic())
                unload = getattr(runtime, "unload_configured_models", None)
                if not callable(unload):
                    reports[name] = {
                        "success": False, "backend_available": False, "requested": [], "unloaded": [],
                        "remaining": None, "failed": {"operation": "unload receipt unavailable"},
                        "verified": False, "complete": False, "physical_vram_reclaimed": False,
                    }
                    continue
                try:
                    reports[name] = unload(
                        timeout_seconds=remaining_seconds,
                        should_stop=should_stop,
                        deadline=end,
                        include_llama=include_llama,
                    )
                except Exception as exc:
                    reports[name] = {
                        "success": False, "backend_available": False, "requested": [], "unloaded": [],
                        "remaining": None, "failed": {"operation": type(exc).__name__},
                        "verified": False, "complete": False, "physical_vram_reclaimed": False,
                    }
        complete = all(isinstance(report, dict) and report.get("complete") is True for report in reports.values())
        verified = complete and all(report.get("verified") is True for report in reports.values())
        requested = [f"{tier}:{model}" for tier, report in reports.items() for model in (report.get("requested") or [])]
        unloaded = [f"{tier}:{model}" for tier, report in reports.items() for model in (report.get("unloaded") or [])]
        remaining: list[str] | None = []
        for tier, report in reports.items():
            models = report.get("remaining")
            if not isinstance(models, list):
                remaining = None
                break
            remaining.extend(f"{tier}:{model}" for model in models)
        failed = {
            f"{tier}:{key}": value
            for tier, report in reports.items()
            for key, value in (report.get("failed") or {}).items()
        }
        return {
            "success": complete and verified and remaining == [] and not failed,
            "backend_available": any(bool(report.get("backend_available")) for report in reports.values()),
            "requested": requested,
            "unloaded": unloaded,
            "remaining": remaining,
            "failed": failed,
            "verified": verified,
            "complete": complete,
            "unverified": not complete or remaining is None,
            "by_runtime": reports,
            "physical_vram_reclaimed": False,
        }

    def is_online(self) -> bool:
        if bool(self.config.get("smart_ollama", {}).get("enabled", False)):
            return bool(self.fast.is_online() or self.smart.is_online())
        return bool(self.fast.is_online())

    def ensure_running(self) -> bool:
        return bool(self.fast.ensure_running())

    def version(self) -> str | None:
        return self.fast.version()

    def installed_models(self) -> list[str]:
        return self.fast.installed_models()

    def loaded_model_details(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for endpoint, runtime in (("fast", self.fast), ("smart", self.smart)):
            for row in self._details(runtime):
                item = dict(row)
                item["endpoint"] = endpoint
                rows.append(item)
        return rows

    def loaded_model_inventory(
        self,
        *,
        should_stop: Any | None = None,
        deadline: float | None = None,
        force_refresh: bool = True,
    ) -> dict[str, Any]:
        """Return fresh tiered inventory with endpoint identity and completeness."""
        tiers: dict[str, dict[str, Any]] = {}
        models: list[dict[str, Any]] = []
        errors: dict[str, str] = {}
        endpoint_status: dict[str, str] = {}
        for tier, runtime, include_llama in (("fast", self.fast, True), ("smart", self.smart, False)):
            reader = getattr(runtime, "loaded_model_inventory", None)
            if not callable(reader):
                tiers[tier] = {"complete": False, "endpoints": {}, "models": []}
                errors[tier] = "strict inventory unavailable"
                continue
            try:
                snapshot = reader(
                    should_stop=should_stop, deadline=deadline,
                    force_refresh=force_refresh, include_llama=include_llama,
                )
                if not isinstance(snapshot, dict) or not isinstance(snapshot.get("models"), list):
                    raise RuntimeError("inventory malformed")
                backends = snapshot.get("backends")
                if not isinstance(backends, dict):
                    raise RuntimeError("backend inventory missing")
                tier_errors = snapshot.get("errors", {})
                if not isinstance(tier_errors, dict):
                    raise RuntimeError("inventory errors malformed")
                tier_models: list[dict[str, Any]] = []
                tier_endpoints: dict[str, str] = {}
                for backend, details in backends.items():
                    if not isinstance(details, dict) or not isinstance(details.get("endpoints"), dict):
                        raise RuntimeError("endpoint inventory malformed")
                    if snapshot.get("complete") is True and details.get("complete") is not True:
                        raise RuntimeError("backend inventory completeness mismatch")
                    for endpoint_id, state in details["endpoints"].items():
                        key = f"{tier}:{backend}:{endpoint_id}"
                        tier_endpoints[key] = str(state)
                        endpoint_status[key] = str(state)
                for row in snapshot["models"]:
                    if not isinstance(row, dict):
                        raise RuntimeError("model inventory row malformed")
                    item = {**row, "tier": tier}
                    tier_models.append(item)
                models.extend(tier_models)
                tiers[tier] = {
                    "complete": snapshot.get("complete") is True,
                    "endpoints": tier_endpoints,
                    "models": tier_models,
                    "errors": {str(key): str(value) for key, value in tier_errors.items()},
                }
                if snapshot.get("complete") is not True:
                    errors.update({f"{tier}:{key}": str(value) for key, value in tier_errors.items()} or {tier: "inventory incomplete"})
            except Exception as exc:
                tiers[tier] = {"complete": False, "endpoints": {}, "models": [], "errors": {"inventory": str(exc) or type(exc).__name__}}
                errors[tier] = type(exc).__name__
        complete = all(item["complete"] for item in tiers.values())
        return {
            "complete": complete,
            "backend_available": bool(tiers) and any(
                state == "complete" for item in tiers.values() for state in item["endpoints"].values()
            ),
            "observed_at_monotonic": time.monotonic(),
            "tiers": tiers,
            "endpoints": endpoint_status,
            "models": models,
            "errors": errors,
        }

    def loaded_models(self) -> list[str]:
        return [str(row.get("name", "")) for row in self.loaded_model_details() if row.get("name")]

    def managed_profile_status(self) -> dict[str, Any]:
        fast = dict(self.fast.managed_profile_status())
        if bool(self.config.get("smart_ollama", {}).get("enabled", False)):
            smart = dict(self.smart.managed_profile_status())
            smart["owned"] = True
        else:
            smart = {"managed": False, "enabled": False}
        return {
            "fast": fast,
            "smart": smart,
            "handoff": {
                "count": self._handoff_count,
                "unload_failures": self._unload_failures,
                "active_endpoint": self._active_endpoint,
                "last_error": self._last_handoff_error,
            },
        }

    def stop_managed_server(self) -> bool:
        return bool(self.smart.stop_managed_server())

    def unload_managed_models(self, *, timeout_seconds: float = 5.0) -> dict[str, Any]:
        """Unload Hub-owned sidecar models and verify absence within a deadline."""
        timeout = min(30.0, max(0.05, float(timeout_seconds)))
        deadline = time.monotonic() + timeout
        unloaded: list[str] = []
        remaining: list[str] = []

        def loaded_names() -> list[str]:
            budget = max(0.001, min(1.0, deadline - time.monotonic()))
            status = self.smart.request("/api/ps", timeout=budget)
            if not isinstance(status, dict) or "error" in status:
                error = status.get("error", "invalid loaded-model status") if isinstance(status, dict) else "invalid loaded-model status"
                raise RuntimeError(f"loaded-model status unavailable: {error}")
            rows = status.get("models")
            if not isinstance(rows, list):
                raise RuntimeError("loaded-model status omitted models")
            names: list[str] = []
            for row in rows:
                if not isinstance(row, dict) or not str(row.get("name", row.get("model", ""))).strip():
                    raise RuntimeError("incomplete loaded-model status")
                names.append(str(row.get("name", row.get("model", ""))))
            remaining[:] = names
            return names

        with self._lock:
            try:
                names = loaded_names()
                unknown = [name for name in names if name not in self._hub_models]
                if unknown:
                    raise RuntimeError(f"refusing to unload externally managed model: {unknown[0]}")
                for model in names:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("managed model unload deadline exceeded")
                    if not self.smart.unload_model(model):
                        raise RuntimeError(f"cannot unload {model}")
                    unloaded.append(model)
                while True:
                    remaining = loaded_names()
                    if not remaining:
                        return {"success": True, "unloaded": unloaded, "remaining": [], "terminal": True, "retryable": False}
                    if time.monotonic() >= deadline:
                        raise TimeoutError("managed models remained loaded after deadline")
                    time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
            except TimeoutError as exc:
                return {"success": False, "unloaded": unloaded, "remaining": remaining, "error": str(exc), "terminal": False, "retryable": True}
            except Exception as exc:
                return {"success": False, "unloaded": unloaded, "remaining": remaining, "error": str(exc), "terminal": True, "retryable": False}

    def generate(self, model: str, prompt: str, **kwargs: Any) -> dict[str, Any]:
        payload = {"model": model, "prompt": prompt, "stream": False, **kwargs}
        return self.request("/api/generate", payload)

    def chat(self, model: str, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        payload = {"model": model, "messages": messages, "stream": False, **kwargs}
        return self.request("/api/chat", payload)

    def embeddings(self, model: str, prompt: str) -> dict[str, Any]:
        return self.request("/api/embeddings", {"model": model, "prompt": prompt})

    def evict_if_needed(self, required_model: str) -> bool:
        _, target, peer = self._runtime_for_model(required_model)
        try:
            self._unload_peer(peer)
        except RuntimeError:
            return False
        return bool(target.evict_if_needed(required_model))
