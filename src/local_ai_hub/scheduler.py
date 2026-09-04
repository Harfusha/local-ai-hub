from __future__ import annotations

import threading
import time
import contextvars
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from .model_policy import ModelExecutionPolicy
from .trace_context import observer


@dataclass
class Job:
    id: int
    model: str
    tenant: str
    source: str
    priority: int
    execute: Callable[[], dict[str, Any]]
    background: bool = False
    created_at: float = field(default_factory=time.monotonic)
    created_wall: float = field(default_factory=time.time)
    done: threading.Event = field(default_factory=threading.Event)
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    caller_timed_out: bool = False
    dispatched_at: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0
    context: contextvars.Context = field(default_factory=contextvars.copy_context)
    trace_id: str = ""


class QueueFullError(RuntimeError):
    pass


class ModelUnavailableError(RuntimeError):
    pass


class AffinityScheduler:
    """Shared multi-tenant, model-affinity scheduler with idle-only background work.

    Interactive work always wins. Background/preprocessing jobs are dispatched only
    after an idle grace period and are considered when no foreground work is queued.
    Background work is deliberately split into small jobs by the preprocessor so a
    foreground request can take over between micro-steps.
    """

    def __init__(self, runtime: Any, config: dict[str, Any]):
        cfg = config["scheduler"]
        bg_cfg = config.get("preprocessing", {})
        self.config = config
        self.runtime = runtime
        self.model_policy = ModelExecutionPolicy(config)
        self.max_parallel = int(cfg.get("max_parallel", 1))
        self.max_queue = int(cfg.get("max_queue", 256))
        self.max_queued_per_tenant = int(cfg.get("max_queued_per_tenant", 64))
        self.max_inflight_per_tenant = int(cfg.get("max_inflight_per_tenant", self.max_parallel))
        self.batch_jobs = int(cfg.get("affinity_batch_jobs", 8))
        self.batch_seconds = float(cfg.get("affinity_batch_seconds", 75))
        self.max_other_wait = float(cfg.get("max_other_model_wait_seconds", 45))
        self.switch_cooldown = float(cfg.get("switch_cooldown_seconds", 1))
        self.switch_failure_cooldown = max(1.0, float(cfg.get("model_switch_failure_cooldown_seconds", 20.0)))
        resilience_cfg = config.get("resilience", {})
        configured_default_wait = max(0.05, float(resilience_cfg.get("scheduler_wait_timeout_seconds", config.get("server", {}).get("request_timeout_seconds", 210) + 15)))
        self.max_caller_wait_timeout = max(0.05, float(cfg.get("max_caller_wait_timeout_seconds", config.get("client", {}).get("max_request_timeout_seconds", 900))))
        self.default_caller_wait_timeout = min(configured_default_wait, self.max_caller_wait_timeout)
        self.unload_others = int(cfg.get("max_loaded_models", 1)) <= 1
        self.background_idle_grace = max(0.0, float(bg_cfg.get("idle_grace_seconds", 3.0)))
        self.background_switch_grace = max(self.background_idle_grace, float(bg_cfg.get("model_switch_idle_seconds", 10.0)))

        self._cond = threading.Condition()
        self._pending: list[Job] = []
        self._job_id = 0
        self._active_model: str | None = None
        self._active_since = 0.0
        self._active_dispatched = 0
        self._inflight = 0
        self._inflight_background = 0
        self._inflight_by_tenant: dict[str, int] = {}
        self._inflight_jobs: dict[int, Job] = {}
        self._tenant_vruntime: dict[str, int] = {}
        self._last_switch = 0.0
        self._switching = False
        self._model_blocked_until: dict[str, float] = {}
        self._model_last_error: dict[str, str] = {}
        self._running = True
        self._last_foreground_activity = time.monotonic()
        self._foreground_generation = 0
        self._foreground_preempt_hook: Callable[[], None] | None = None
        self._background_gpu_lease = False
        self._executor = ThreadPoolExecutor(max_workers=self.max_parallel, thread_name_prefix="local-ai")
        self._stats = {
            "submitted": 0,
            "completed": 0,
            "failed": 0,
            "model_switches": 0,
            "affinity_dispatches": 0,
            "evictions": 0,
            "queue_rejections": 0,
            "prewarms": 0,
            "caller_timeouts": 0,
            "cancelled_pending": 0,
            "switch_time_ms": 0.0,
            "background_submitted": 0,
            "background_dispatched": 0,
            "background_completed": 0,
            "background_failed": 0,
            "background_yields": 0,
            "background_gpu_lease_rejections": 0,
            "model_switch_failures": 0,
            "model_fast_rejections": 0,
        }

        try:
            # Do not blindly trust a model loaded by another Ollama client. A runner
            # with a tiny default context must pass through prepare_model() before it
            # becomes the scheduler's active profile.
            details = runtime.loaded_model_details() if hasattr(runtime, "loaded_model_details") else []
            for row in details:
                name = str(row.get("name", "")) if isinstance(row, dict) else ""
                ctx = int(row.get("context_length", 0) or 0) if isinstance(row, dict) else 0
                if name and ctx >= self.model_policy.profile(name).num_ctx:
                    self._active_model = name
                    self._active_since = time.monotonic()
                    break
        except Exception:
            pass

        self._dispatcher = threading.Thread(target=self._dispatch_loop, name="local-ai-dispatcher", daemon=True)
        self._dispatcher.start()

    def submit(
        self,
        model: str,
        tenant: str,
        source: str,
        execute: Callable[[], dict[str, Any]],
        priority: int = 5,
        wait_timeout: float | None = None,
        *,
        background: bool = False,
    ) -> dict[str, Any]:
        tenant = tenant or "default"
        priority = max(0, min(int(priority), 9))
        # Never let an omitted/accidentally huge caller timeout turn a stuck runtime
        # into a permanently occupied HTTP/MCP handler. Explicit shorter deadlines
        # are preserved; longer ones are capped by one configurable hard ceiling.
        effective_wait_timeout = self.default_caller_wait_timeout if wait_timeout is None else max(0.05, float(wait_timeout))
        effective_wait_timeout = min(effective_wait_timeout, self.max_caller_wait_timeout)
        if background:
            # Background work cannot smuggle itself above foreground work through a
            # caller-supplied priority.
            priority = min(priority, 1)
        preempt_hook: Callable[[], None] | None = None
        with self._cond:
            now = time.monotonic()
            blocked_until = self._model_blocked_until.get(model, 0.0)
            if blocked_until > now:
                self._stats["model_fast_rejections"] += 1
                remaining = max(1, int(blocked_until - now + 0.999))
                detail = self._model_last_error.get(model, "model preparation failed")
                raise ModelUnavailableError(f"model {model!r} temporarily unavailable ({detail}); retry after ~{remaining}s")
            if blocked_until:
                self._model_blocked_until.pop(model, None)
                self._model_last_error.pop(model, None)
            tenant_queued = sum(1 for job in self._pending if job.tenant == tenant)
            if len(self._pending) >= self.max_queue or tenant_queued >= self.max_queued_per_tenant:
                self._stats["queue_rejections"] += 1
                raise QueueFullError(f"queue limit reached for tenant {tenant!r}")
            self._job_id += 1
            trace_observer = observer()
            trace_id = str(getattr(trace_observer, "trace_id", "") or "")
            job = Job(self._job_id, model, tenant, source, priority, execute, background=background, trace_id=trace_id)
            self._pending.append(job)
            if trace_observer is not None and trace_id:
                try:
                    trace_observer.store.link(trace_id, scheduler_job_id=str(job.id))
                    trace_observer.event("scheduled", {"scheduler_job_id": job.id, "model": model, "background": background})
                except Exception:
                    pass
            self._stats["submitted"] += 1
            if background:
                self._stats["background_submitted"] += 1
            else:
                # Mark foreground intent before notifying the dispatcher. This closes
                # the race where an idle GPU worker could acquire the GPU between a
                # user request arriving and the foreground model beginning to load.
                self._last_foreground_activity = time.monotonic()
                self._foreground_generation += 1
                preempt_hook = self._foreground_preempt_hook

        # Local AI background GPU work runs on a separate Ollama endpoint and is disposable.
        # Stop it synchronously before the foreground dispatcher is allowed to load a
        # foreground runner, preventing transient dual-runner VRAM pressure/offload.
        if preempt_hook is not None:
            try:
                preempt_hook()
            except Exception:
                pass
        with self._cond:
            if not background:
                self._background_gpu_lease = False
            self._cond.notify_all()

        if not job.done.wait(effective_wait_timeout):
            with self._cond:
                job.caller_timed_out = True
                self._stats["caller_timeouts"] += 1
                if job in self._pending:
                    self._pending.remove(job)
                    self._stats["cancelled_pending"] += 1
                    job.error = "caller timed out before dispatch"
                    job.done.set()
                    self._cond.notify_all()
            raise TimeoutError(f"job {job.id} did not finish before caller timeout")
        queue_wait_ms = max(0.0, ((job.started_at or job.finished_at or time.monotonic()) - job.created_at) * 1000)
        service_ms = max(0.0, (job.finished_at - job.started_at) * 1000) if job.finished_at and job.started_at else 0.0
        if job.error:
            return {"success": False, "error": job.error, "job_id": job.id, "_lah_scheduler_queue_wait_ms": queue_wait_ms, "_lah_scheduler_service_ms": service_ms, "_lah_scheduler_background": job.background}
        if isinstance(job.result, dict):
            job.result.setdefault("job_id", job.id)
            job.result.setdefault("_lah_scheduler_queue_wait_ms", queue_wait_ms)
            job.result.setdefault("_lah_scheduler_service_ms", service_ms)
            job.result.setdefault("_lah_scheduler_background", job.background)
        return job.result

    def enqueue(
        self,
        model: str,
        tenant: str,
        source: str,
        execute: Callable[[], dict[str, Any]],
        priority: int = 1,
        *,
        background: bool = True,
    ) -> Job:
        """Queue work without binding its lifecycle to a caller timeout."""
        tenant = tenant or "default"
        priority = max(0, min(int(priority), 9))
        if background:
            priority = min(priority, 1)
        with self._cond:
            now = time.monotonic()
            blocked_until = self._model_blocked_until.get(model, 0.0)
            if blocked_until > now:
                self._stats["model_fast_rejections"] += 1
                remaining = max(1, int(blocked_until - now + 0.999))
                detail = self._model_last_error.get(model, "model preparation failed")
                raise ModelUnavailableError(f"model {model!r} temporarily unavailable ({detail}); retry after ~{remaining}s")
            tenant_queued = sum(1 for job in self._pending if job.tenant == tenant)
            if len(self._pending) >= self.max_queue or tenant_queued >= self.max_queued_per_tenant:
                self._stats["queue_rejections"] += 1
                raise QueueFullError(f"queue limit reached for tenant {tenant!r}")
            self._job_id += 1
            trace_observer = observer()
            trace_id = str(getattr(trace_observer, "trace_id", "") or "")
            job = Job(self._job_id, model, tenant, source, priority, execute, background=background, trace_id=trace_id)
            self._pending.append(job)
            if trace_observer is not None and trace_id:
                try:
                    trace_observer.store.link(trace_id, scheduler_job_id=str(job.id))
                    trace_observer.event("scheduled", {"scheduler_job_id": job.id, "model": model, "background": background})
                except Exception:
                    pass
            self._stats["submitted"] += 1
            if background:
                self._stats["background_submitted"] += 1
            self._cond.notify_all()
            return job

    def set_foreground_preempt_hook(self, hook: Callable[[], None] | None) -> None:
        with self._cond:
            self._foreground_preempt_hook = hook

    def foreground_idle_seconds(self) -> float:
        with self._cond:
            return max(0.0, time.monotonic() - self._last_foreground_activity)

    def acquire_background_gpu(self, min_idle_seconds: float) -> bool:
        """Atomically lend the single GPU to Local AI's disposable background runtime.

        Foreground intent always wins. The active foreground runner is unloaded before
        the lease is granted so the secondary Ollama server never intentionally shares
        constrained accelerator memory with the foreground runner.
        """
        with self._cond:
            now = time.monotonic()
            if self._background_gpu_lease:
                return True
            if self._switching or self._inflight or self._pending:
                return False
            if now - self._last_foreground_activity < max(0.0, float(min_idle_seconds)):
                return False
            active = self._active_model
            self._switching = True
        foreign_loaded = False
        try:
            try:
                loaded = [str(x) for x in self.runtime.loaded_models()]
            except Exception:
                loaded = []
            known_models = set(str(v) for v in self.config.get("models", {}).values() if v)
            foreign_loaded = any(m and m not in known_models and m != active for m in loaded)
            if not foreign_loaded:
                for m in loaded:
                    if m:
                        try:
                            self.runtime.unload(m)
                        except Exception:
                            pass
        finally:
            with self._cond:
                # Re-check foreground activity because unloading happens outside the
                # scheduler lock. A request that arrived meanwhile invalidates lease.
                now = time.monotonic()
                clean = (
                    not foreign_loaded and not self._pending and self._inflight == 0
                    and now - self._last_foreground_activity >= max(0.0, float(min_idle_seconds))
                )
                if clean:
                    self._active_model = None
                    self._active_since = 0.0
                    self._active_dispatched = 0
                    self._background_gpu_lease = True
                elif foreign_loaded:
                    self._stats["background_gpu_lease_rejections"] += 1
                self._switching = False
                self._cond.notify_all()
                return bool(clean)

    def release_background_gpu(self) -> None:
        with self._cond:
            self._background_gpu_lease = False
            self._cond.notify_all()

    def foreground_pending(self) -> bool:
        with self._cond:
            return any(not j.background for j in self._pending)

    def foreground_busy(self) -> bool:
        """True when background work should yield before starting another micro-step."""
        with self._cond:
            foreground_inflight = self._inflight - self._inflight_background
            return bool(foreground_inflight > 0 or any(not j.background for j in self._pending) or self._switching)

    def background_allowed(self, *, require_switch_idle: bool = False) -> bool:
        with self._cond:
            now = time.monotonic()
            if self._inflight - self._inflight_background > 0 or any(not j.background for j in self._pending):
                return False
            grace = self.background_switch_grace if require_switch_idle else self.background_idle_grace
            return now - self._last_foreground_activity >= grace

    def foreground_generation(self) -> int:
        with self._cond:
            return self._foreground_generation

    def note_background_yield(self) -> None:
        with self._cond:
            self._stats["background_yields"] += 1

    def _foreground_pending_jobs(self) -> list[Job]:
        return [j for j in self._pending if not j.background]

    def _background_pending_jobs(self) -> list[Job]:
        return [j for j in self._pending if j.background]

    def _eligible_jobs(self, now: float) -> list[Job]:
        foreground = self._foreground_pending_jobs()
        if foreground:
            return foreground
        if now - self._last_foreground_activity < self.background_idle_grace:
            return []
        return self._background_pending_jobs()

    def _dispatch_loop(self) -> None:
        while self._running:
            target_switch: str | None = None
            selected: Job | None = None
            with self._cond:
                while self._running:
                    now = time.monotonic()
                    if self._background_gpu_lease:
                        self._cond.wait(timeout=0.10)
                        continue
                    eligible = self._eligible_jobs(now)
                    if eligible and self._active_model is None and self._inflight == 0:
                        target_switch = self._choose_initial_model(eligible, now)
                        if target_switch:
                            self._switching = True
                            break

                    if eligible and self._active_model is not None:
                        if self._should_switch(now, eligible):
                            if self._inflight == 0:
                                target_switch = self._choose_next_model(eligible, exclude=self._active_model, now=now)
                                if target_switch:
                                    self._switching = True
                                    break
                        elif self._inflight < self._active_parallel_limit():
                            selected = self._choose_job_for_active_model(now, eligible)
                            if selected is not None:
                                self._pending.remove(selected)
                                selected.dispatched_at = time.monotonic()
                                self._inflight += 1
                                self._inflight_jobs[selected.id] = selected
                                if selected.background:
                                    self._inflight_background += 1
                                    self._stats["background_dispatched"] += 1
                                self._inflight_by_tenant[selected.tenant] = self._inflight_by_tenant.get(selected.tenant, 0) + 1
                                self._tenant_vruntime[selected.tenant] = self._tenant_vruntime.get(selected.tenant, 0) + 1
                                self._active_dispatched += 1
                                self._stats["affinity_dispatches"] += 1
                                break

                    self._cond.wait(timeout=0.15)

            if not self._running:
                break

            if target_switch:
                self._perform_switch(target_switch)
                continue

            if selected is not None:
                try:
                    self._executor.submit(self._run_job, selected)
                except Exception as exc:
                    with self._cond:
                        self._inflight = max(0, self._inflight - 1)
                        self._inflight_jobs.pop(selected.id, None)
                        if selected.background:
                            self._inflight_background = max(0, self._inflight_background - 1)
                        current = self._inflight_by_tenant.get(selected.tenant, 1) - 1
                        if current <= 0:
                            self._inflight_by_tenant.pop(selected.tenant, None)
                        else:
                            self._inflight_by_tenant[selected.tenant] = current
                        selected.error = f"dispatch failed: {exc}"
                        selected.done.set()
                        self._cond.notify_all()

    def _active_parallel_limit(self) -> int:
        if not self._active_model:
            return self.max_parallel
        return max(1, min(self.max_parallel, self.model_policy.parallel_limit(self._active_model)))

    def _choose_initial_model(self, jobs: list[Job], now: float) -> str | None:
        loaded = set()
        try:
            loaded = set(self.runtime.loaded_models())
        except Exception:
            pass
        ordered = sorted(jobs, key=lambda j: (-j.priority, j.created_at))
        for job in ordered:
            if job.model in loaded:
                return job.model
        candidate = ordered[0] if ordered else None
        if candidate and candidate.background and now - self._last_foreground_activity < self.background_switch_grace:
            return None
        return candidate.model if candidate else None

    @staticmethod
    def _models_waiting_from(jobs: list[Job], exclude: str | None = None) -> list[str]:
        seen: set[str] = set()
        models: list[str] = []
        for job in sorted(jobs, key=lambda j: j.created_at):
            if job.model == exclude or job.model in seen:
                continue
            seen.add(job.model)
            models.append(job.model)
        return models

    def _oldest_wait_for_other_model(self, now: float, jobs: list[Job]) -> float:
        waits = [now - j.created_at for j in jobs if j.model != self._active_model]
        return max(waits, default=0.0)

    def _has_active_pending(self, jobs: list[Job]) -> bool:
        return any(j.model == self._active_model for j in jobs)

    def _should_switch(self, now: float, jobs: list[Job]) -> bool:
        if not self._models_waiting_from(jobs, exclude=self._active_model):
            return False
        if now - self._last_switch < self.switch_cooldown:
            return False
        # Background jobs may only cause a model swap after a longer idle window.
        if jobs and all(j.background for j in jobs) and now - self._last_foreground_activity < self.background_switch_grace:
            return False
        if not self._has_active_pending(jobs):
            return True
        if self.batch_jobs > 0 and self._active_dispatched >= self.batch_jobs:
            return True
        if self.batch_seconds > 0 and self._active_since and now - self._active_since >= self.batch_seconds:
            return True
        # Anti-starvation is for real requests; background jobs must never force a
        # switch merely because they have been waiting for a long time.
        foreground_jobs = [j for j in jobs if not j.background]
        if foreground_jobs and self.max_other_wait > 0 and self._oldest_wait_for_other_model(now, foreground_jobs) >= self.max_other_wait:
            return True
        return False

    def _choose_next_model(self, jobs: list[Job], exclude: str | None, now: float) -> str | None:
        candidates = [j for j in jobs if j.model != exclude]
        if not candidates:
            return None
        foreground = [j for j in candidates if not j.background]
        if foreground:
            candidates = foreground
            if self.max_other_wait > 0:
                starving = [j for j in candidates if now - j.created_at >= self.max_other_wait]
                if starving:
                    return min(starving, key=lambda j: j.created_at).model
        elif now - self._last_foreground_activity < self.background_switch_grace:
            return None

        groups: dict[str, list[Job]] = {}
        for job in candidates:
            groups.setdefault(job.model, []).append(job)

        def score(item: tuple[str, list[Job]]) -> tuple[float, float, float]:
            _model, grouped = item
            count = len(grouped)
            max_priority = max(j.priority for j in grouped)
            oldest = min(j.created_at for j in grouped)
            return (-(count * 2 + max_priority), oldest, -count)

        return min(groups.items(), key=score)[0]

    def _choose_job_for_active_model(self, now: float, jobs: list[Job]) -> Job | None:
        candidates = [
            j for j in jobs
            if j.model == self._active_model
            and self._inflight_by_tenant.get(j.tenant, 0) < self.max_inflight_per_tenant
        ]
        if not candidates:
            return None
        foreground = [j for j in candidates if not j.background]
        if foreground:
            candidates = foreground
        elif not self.background_allowed(require_switch_idle=False):
            return None

        def score(job: Job) -> tuple[float, int, float]:
            wait = now - job.created_at
            effective_priority = job.priority + min(int(wait // 30.0), 3) if not job.background else job.priority
            vruntime = self._tenant_vruntime.get(job.tenant, 0)
            return (-effective_priority, vruntime, job.created_at)

        return min(candidates, key=score)

    def _perform_switch(self, target: str) -> bool:
        evicted: list[str] = []
        started = time.perf_counter()
        error = ""
        try:
            prepared = self.runtime.prepare_model(target, unload_others=self.unload_others)
            # Runtime adapters historically returned either a list of evicted models
            # or None. Treat a falsey/non-list success value as no evictions instead
            # of letting an adapter quirk kill the dispatcher thread.
            evicted = list(prepared) if isinstance(prepared, (list, tuple, set)) else []
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:300]
        elapsed_ms = (time.perf_counter() - started) * 1000
        with self._cond:
            self._stats["switch_time_ms"] = round(float(self._stats.get("switch_time_ms", 0.0)) + elapsed_ms, 1)
            self._stats["evictions"] += len(evicted)
            self._active_dispatched = 0
            self._last_switch = time.monotonic()
            if error:
                self._stats["model_switch_failures"] += 1
                self._model_blocked_until[target] = time.monotonic() + self.switch_failure_cooldown
                self._model_last_error[target] = error
                # The switch happened with no in-flight work. Fail the already queued
                # requests for this model now; leaving them parked until a cooldown
                # expires turns a preparation failure into an apparent hub hang.
                failed = [job for job in self._pending if job.model == target]
                for job in failed:
                    self._pending.remove(job)
                    job.error = f"model preparation failed: {error}"
                    job.finished_at = time.monotonic()
                    job.done.set()
                self._active_model = None
                self._active_since = 0.0
            else:
                if target != self._active_model:
                    self._stats["model_switches"] += 1
                self._model_blocked_until.pop(target, None)
                self._model_last_error.pop(target, None)
                self._active_model = target
                self._active_since = time.monotonic()
            self._switching = False
            self._cond.notify_all()
        return not error

    def prewarm(self, model: str) -> bool:
        """Warm one model only while completely idle; never delays queued user work."""
        with self._cond:
            if self._pending or self._inflight or self._switching or self._background_gpu_lease:
                return False
            if self._active_model == model:
                return True
            self._switching = True
        success = self._perform_switch(model)
        if success:
            with self._cond:
                self._stats["prewarms"] += 1
        return success

    def _run_job(self, job: Job) -> None:
        job.started_at = time.monotonic()
        try:
            job.result = job.context.run(job.execute)
            if not isinstance(job.result, dict):
                job.result = {"success": True, "result": job.result}
            with self._cond:
                self._stats["completed"] += 1
                if job.background:
                    self._stats["background_completed"] += 1
                else:
                    self._last_foreground_activity = time.monotonic()
        except Exception as exc:
            job.error = str(exc)
            with self._cond:
                self._stats["failed"] += 1
                if job.background:
                    self._stats["background_failed"] += 1
                else:
                    self._last_foreground_activity = time.monotonic()
        finally:
            job.finished_at = time.monotonic()
            with self._cond:
                self._inflight -= 1
                self._inflight_jobs.pop(job.id, None)
                if job.background:
                    self._inflight_background = max(0, self._inflight_background - 1)
                current = self._inflight_by_tenant.get(job.tenant, 1) - 1
                if current <= 0:
                    self._inflight_by_tenant.pop(job.tenant, None)
                else:
                    self._inflight_by_tenant[job.tenant] = current
                job.done.set()
                self._cond.notify_all()

    def ensure_dispatcher(self) -> bool:
        with self._cond:
            if not self._running:
                return False
            if self._dispatcher.is_alive():
                return True
            self._dispatcher = threading.Thread(target=self._dispatch_loop, name="local-ai-dispatcher", daemon=True)
            self._dispatcher.start()
            self._cond.notify_all()
            return True

    def _job_public(self, job: Job, now: float, *, state: str, position: int = 0) -> dict[str, Any]:
        wait_ms = max(0, int(((job.started_at or now) - job.created_at) * 1000))
        service_ms = max(0, int((now - job.started_at) * 1000)) if job.started_at and state == "running" else 0
        if job.background:
            wait_reason = "background-idle"
        elif self._switching and job.model != self._active_model:
            wait_reason = "model-switch"
        elif job.model != self._active_model:
            wait_reason = "model-affinity"
        elif self._inflight_by_tenant.get(job.tenant, 0) >= self.max_inflight_per_tenant:
            wait_reason = "tenant-limit"
        elif self._inflight >= self._active_parallel_limit():
            wait_reason = "model-capacity"
        else:
            wait_reason = "ready"
        return {
            "job_id": job.id, "trace_id": job.trace_id, "state": state, "position": position,
            "model": job.model, "source": job.source, "tenant": job.tenant[:120],
            "priority": job.priority, "background": job.background,
            "created_at": job.created_wall, "wait_ms": wait_ms, "service_ms": service_ms,
            "wait_reason": wait_reason, "caller_timed_out": job.caller_timed_out,
        }

    def status(self) -> dict[str, Any]:
        with self._cond:
            by_model: dict[str, int] = {}
            by_tenant: dict[str, int] = {}
            background_queued = 0
            now = time.monotonic()
            ordered_pending = sorted(self._pending, key=lambda j: (-j.priority, j.created_at))
            pending_jobs: list[dict[str, Any]] = []
            model_positions: dict[str, int] = {}
            for job in ordered_pending:
                by_model[job.model] = by_model.get(job.model, 0) + 1
                by_tenant[job.tenant] = by_tenant.get(job.tenant, 0) + 1
                background_queued += int(job.background)
                model_positions[job.model] = model_positions.get(job.model, 0) + 1
                if len(pending_jobs) < 64:
                    item = self._job_public(job, now, state="queued", position=model_positions[job.model])
                    pending_jobs.append(item)
            inflight_jobs = [self._job_public(job, now, state="running") for job in sorted(self._inflight_jobs.values(), key=lambda j: j.started_at or j.created_at)]
            return {
                "active_model": self._active_model,
                "active_parallel_limit": self._active_parallel_limit(),
                "global_parallel_limit": self.max_parallel,
                "switching": self._switching,
                "background_gpu_lease": self._background_gpu_lease,
                "inflight": self._inflight,
                "inflight_background": self._inflight_background,
                "foreground_inflight": self._inflight - self._inflight_background,
                "queued": len(self._pending),
                "background_queued": background_queued,
                "foreground_queued": len(self._pending) - background_queued,
                "queued_by_model": by_model,
                "queued_by_tenant": by_tenant,
                "pending_jobs": pending_jobs,
                "inflight_jobs": inflight_jobs,
                "active_batch_dispatched": self._active_dispatched,
                "background_allowed": self.background_allowed(),
                "blocked_models": {m: max(0, int((until - now) * 1000)) for m, until in self._model_blocked_until.items() if until > now},
                "last_foreground_activity_ms": max(0, int((now - self._last_foreground_activity) * 1000)),
                "stats": dict(self._stats),
            }

    def close(self) -> None:
        with self._cond:
            self._running = False
            # Release callers waiting on jobs that will never be dispatched.
            for job in self._pending:
                job.error = "scheduler shutting down"
                job.done.set()
            self._pending.clear()
            self._cond.notify_all()
        self._executor.shutdown(wait=False, cancel_futures=True)
        if self._dispatcher.is_alive() and threading.current_thread() is not self._dispatcher:
            self._dispatcher.join(timeout=1.0)
