"""Local adapter for Laya shadow decisions and scoped training capture.

LocalAIApp keeps the Laya service available for its lifetime and schedules
eligible shadow evaluation after ordinary context retrieval. The provider is
loaded on demand from the pinned local checkpoint, then retained for the
configured idle window after the latest completed Laya request. Decisions use
typed signals and authorized evidence IDs, with separately bounded and redacted
task/context text when useful for `context_source`. Actual outcomes are captured
through the scoped recorder. The adapter never changes Hub decisions, trains,
downloads, or executes tools.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import inspect
import json
import math
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .laya_decisions import (
    ContextSourceEvidence,
    DecisionCategory,
    DecisionInput,
    DecisionMode,
    DecisionRequest,
    DecisionResult,
    DecisionStatus,
    _CATEGORY_INSTRUCTIONS,
)

_SOURCE_DESCRIPTIONS = {
    "indexed": "Use indexed repository evidence that is current and complete.",
    "artifact": "Read the authorized artifact that is current and complete.",
    "memory": "Use an existing authorized memory record that is current and complete.",
    "rag": "Search the existing authorized RAG collection for missing evidence.",
    "more_evidence": "Request another authorized source because current coverage is insufficient.",
}
_DEVICE_PRIORITY = {"npu": 0, "dgpu": 1, "igpu": 2, "cpu": 3}


@dataclass(frozen=True)
class DeviceCandidate:
    """Runtime evidence supplied by one installed provider adapter."""

    provider: str
    device: str
    device_class: str
    device_name: str
    runtime_version: str
    available: bool
    supports_laya: bool
    quality_passed: bool | None = None

    def __post_init__(self) -> None:
        if self.device_class not in _DEVICE_PRIORITY:
            raise ValueError("unsupported Laya device class")
        for name in ("provider", "device", "device_name", "runtime_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or len(value) > 160:
                raise ValueError(f"invalid {name}")
        if type(self.available) is not bool or type(self.supports_laya) is not bool:
            raise ValueError("invalid runtime capability flags")
        if self.quality_passed is not None and type(self.quality_passed) is not bool:
            raise ValueError("quality_passed must be true, false, or unknown")


class _LayaRouterSession:
    """Own one local checkpoint through Laya's public Router lifecycle API."""

    def __init__(self, router: Any, model_name: str) -> None:
        self._router = router
        self._model_name = model_name

    def predict(self, state: Any, questions: Any) -> Any:
        return self._router.predict(state, questions, model=self._model_name)

    def close(self) -> bool:
        self._router.unload(self._model_name)
        loaded = self._router.loaded
        return self._model_name not in loaded


def select_laya_device(
    candidates: Sequence[DeviceCandidate], *, evaluation_mode: bool = False
) -> DeviceCandidate:
    """Choose the best compatible device; production selection requires quality pass."""
    if type(evaluation_mode) is not bool:
        raise ValueError("evaluation_mode must be a boolean")
    if isinstance(candidates, (str, bytes)):
        raise ValueError("device candidates must be a sequence of candidates")
    usable = [
        candidate
        for candidate in candidates
        if isinstance(candidate, DeviceCandidate)
        and candidate.available
        and candidate.supports_laya
        and (evaluation_mode or candidate.quality_passed is True)
    ]
    if not usable:
        raise RuntimeError("no Laya device has passed its quality gate")
    return min(usable, key=lambda item: (_DEVICE_PRIORITY[item.device_class], item.provider, item.device))


def discover_torch_devices(
    *,
    torch_module: Any | None = None,
    quality_results: Mapping[str, bool] | None = None,
) -> tuple[DeviceCandidate, ...]:
    """Probe only Laya's installed Torch devices; no drivers or providers are loaded."""
    if torch_module is None:
        torch_module = importlib.import_module("torch")
    if quality_results is not None and not isinstance(quality_results, Mapping):
        raise ValueError("quality_results must be a mapping")
    qualities = quality_results or {}
    version = str(getattr(torch_module, "__version__", "unreported"))[:160]
    candidates: list[DeviceCandidate] = []

    cuda = getattr(torch_module, "cuda", None)
    try:
        cuda_available = bool(cuda and cuda.is_available())
        cuda_count = int(cuda.device_count()) if cuda_available else 0
    except Exception:
        cuda_available, cuda_count = False, 0
    if cuda_available:
        for index in range(min(cuda_count, 16)):
            device = f"cuda:{index}"
            try:
                properties = cuda.get_device_properties(index)
                name = str(getattr(properties, "name", cuda.get_device_name(index)))[:160]
                # CUDA/ROCm names that identify a discrete product are explicit
                # enough to distinguish them from a generic "GPU" label.
                discrete = bool(re.search(r"(?i)(geforce|rtx|quadro|tesla|radeon pro|instinct|firepro)", name))
                if not discrete:
                    discrete = getattr(properties, "is_discrete", None) is True
                if discrete:
                    candidates.append(DeviceCandidate(
                        provider="torch.cuda", device=device, device_class="dgpu",
                        device_name=name, runtime_version=version, available=True,
                        supports_laya=True, quality_passed=qualities.get(device),
                    ))
            except Exception:
                continue

    xpu = getattr(torch_module, "xpu", None)
    try:
        xpu_available = bool(xpu and xpu.is_available())
        xpu_count = int(xpu.device_count()) if xpu_available else 0
    except Exception:
        xpu_available, xpu_count = False, 0
    if xpu_available:
        for index in range(min(xpu_count, 16)):
            device = f"xpu:{index}"
            try:
                properties = xpu.get_device_properties(index)
                name = str(getattr(properties, "name", xpu.get_device_name(index)))[:160]
                integrated = getattr(properties, "is_integrated", None) is True
                discrete = getattr(properties, "is_discrete", None) is True
                raw_type = str(getattr(properties, "device_type", "")).lower()
                if integrated or raw_type in {"igpu", "integrated"}:
                    device_class = "igpu"
                elif discrete or raw_type in {"dgpu", "discrete"}:
                    device_class = "dgpu"
                else:
                    # Device name alone is not enough to distinguish an Intel
                    # integrated GPU from a discrete Arc device.
                    continue
                candidates.append(DeviceCandidate(
                    provider="torch.xpu", device=device, device_class=device_class,
                    device_name=name, runtime_version=version, available=True,
                    supports_laya=True, quality_passed=qualities.get(device),
                ))
            except Exception:
                continue

    candidates.append(DeviceCandidate(
        provider="torch", device="cpu", device_class="cpu",
        device_name="CPU", runtime_version=version, available=True,
        supports_laya=True, quality_passed=qualities.get("cpu"),
    ))
    return tuple(candidates)


@dataclass(frozen=True)
class LayaRuntimeMetadata:
    model_id: str
    revision: str
    provider: str
    runtime_version: str
    device: str
    device_class: str
    device_name: str
    parameter_device: str
    execution_verification: str
    quality_status: str
    latency_ms: float
    input_tokens: int | None
    output_tokens: int | None
    fallback_reason: str | None


@dataclass(frozen=True)
class LayaRuntimeOutcome:
    decision: DecisionResult
    runtime: LayaRuntimeMetadata | None
    capture_status: str = "not_requested"


class LayaRuntimeUnavailable(RuntimeError):
    """The pinned local checkpoint or all eligible provider attempts failed."""


class _LayaCleanupUnconfirmed(LayaRuntimeUnavailable):
    """Stop fallback when a failed provider may still retain its session."""


class _LayaCapacityUnavailable(LayaRuntimeUnavailable):
    """A transient admission denial that must not retire an otherwise valid device."""


class LayaRuntimeAdapter:
    """Run typed shadow decisions against an explicit local checkpoint.

    Callers supply validated requests and inputs. There is no import-time or
    startup model load; the shared session lifecycle loads on first inference.
    ``device_candidates`` must be derived from installed providers and include a
    true quality gate; provider presence alone is never enough to select a device.
    """

    def __init__(
        self,
        *,
        checkpoint_path: str | Path,
        revision: str,
        expected_sha256: Mapping[str, str],
        device_candidates: Sequence[DeviceCandidate],
        evaluation_mode: bool = False,
        loader: Callable[..., Any] | None = None,
        capacity_manager: Any | None = None,
        capacity_request_bytes: int | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.checkpoint_path = Path(checkpoint_path)
        if not self.checkpoint_path.is_absolute():
            raise ValueError("Laya checkpoint path must be absolute")
        if not isinstance(revision, str) or not revision or len(revision) > 128:
            raise ValueError("invalid Laya revision")
        if self.checkpoint_path.name != revision:
            raise ValueError("local checkpoint directory must match the pinned revision")
        if not isinstance(expected_sha256, Mapping) or not expected_sha256:
            raise ValueError("pinned checkpoint hashes are required")
        hashes: dict[str, str] = {}
        for name, digest in expected_sha256.items():
            if (
                not isinstance(name, str)
                or Path(name).is_absolute()
                or ".." in Path(name).parts
                or not isinstance(digest, str)
                or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest.lower())
            ):
                raise ValueError("invalid pinned checkpoint hash")
            hashes[name] = digest.lower()
        self.revision = revision
        self.expected_sha256 = hashes
        self.device_candidates = tuple(device_candidates)
        if type(evaluation_mode) is not bool:
            raise ValueError("evaluation_mode must be a boolean")
        self.evaluation_mode = evaluation_mode
        self._loader = loader
        if capacity_manager is not None and not callable(
            getattr(capacity_manager, "acquire_gpu_capacity_lease", None)
        ):
            raise TypeError("capacity_manager must expose acquire_gpu_capacity_lease")
        if capacity_manager is not None and not callable(
            getattr(capacity_manager, "release_gpu_capacity_lease", None)
        ):
            raise TypeError("capacity_manager must expose release_gpu_capacity_lease")
        if capacity_request_bytes is not None and (
            isinstance(capacity_request_bytes, bool)
            or not isinstance(capacity_request_bytes, int)
            or capacity_request_bytes <= 0
        ):
            raise ValueError("capacity_request_bytes must be a positive integer")
        self._capacity_manager = capacity_manager
        self._capacity_request_bytes = capacity_request_bytes
        self._capacity_owner = f"laya-runtime:{os.getpid()}:{revision}"
        self._capacity_lease: dict[str, str] | None = None
        self._capacity_lease_release_pending = False
        self._capacity_provider_cleanup_unconfirmed = False
        self._clock = clock
        self._selected_device: DeviceCandidate | None = None
        self._failed_devices: set[tuple[str, str]] = set()
        self._call_lock = threading.Lock()

    def _load(self) -> Any:
        if self._capacity_provider_cleanup_unconfirmed:
            raise _LayaCleanupUnconfirmed(
                "previous Laya provider cleanup remains unconfirmed; refusing a second load"
            )
        path = self.checkpoint_path.resolve(strict=True)
        required = ("rl_agent_config.json", "model.safetensors", "tokenizer/tokenizer.json")
        if not path.is_dir() or any(not (path / item).is_file() for item in required):
            raise FileNotFoundError("pinned local Laya checkpoint is incomplete")
        for filename in self.expected_sha256:
            if not (path / filename).is_file():
                raise FileNotFoundError("pinned Laya checkpoint hash target is missing")
        candidates = sorted(
            (
                candidate
                for candidate in self.device_candidates
                if candidate.available
                and candidate.supports_laya
                and (self.evaluation_mode or candidate.quality_passed is True)
                and (candidate.provider, candidate.device) not in self._failed_devices
            ),
            key=lambda item: (_DEVICE_PRIORITY[item.device_class], item.provider, item.device),
        )
        if not candidates:
            raise LayaRuntimeUnavailable("no compatible and eligible Laya device is available")
        loader = self._loader
        laya_module = None
        runtime_version = "injected"
        if loader is None:
            laya_module = importlib.import_module("laya")
            try:
                runtime_version = importlib.metadata.version("laya")
            except importlib.metadata.PackageNotFoundError:
                runtime_version = str(getattr(laya_module, "__version__", "unreported"))
        errors: list[str] = []
        for selected in candidates:
            model = None
            capacity_lease = None
            try:
                if selected.device_class == "dgpu" and self._capacity_manager is not None:
                    if self._capacity_lease is not None:
                        if not self._release_capacity_lease(self._capacity_lease):
                            self._capacity_lease_release_pending = True
                            raise _LayaCleanupUnconfirmed(
                                "previous GPU capacity lease release is pending"
                            )
                        self._capacity_lease = None
                        self._capacity_lease_release_pending = False
                    requested_bytes = self._capacity_request_bytes
                    if requested_bytes is None:
                        # Reserve three times the pinned weight artifact, with a
                        # 2 GiB floor for provider context and inference workspace.
                        weight_bytes = (path / "model.safetensors").stat().st_size
                        requested_bytes = max(2 * 1024**3, weight_bytes * 3)
                    capacity_lease = self._capacity_manager.acquire_gpu_capacity_lease(
                        self._capacity_owner, requested_bytes
                    )
                    if not isinstance(capacity_lease, Mapping) or capacity_lease.get("state") != "admitted":
                        reason = (
                            capacity_lease.get("reason", "gpu_capacity_rejected")
                            if isinstance(capacity_lease, Mapping)
                            else "gpu_capacity_rejected"
                        )
                        capacity_lease = None
                        raise _LayaCapacityUnavailable(str(reason))
                    if not all(
                        isinstance(capacity_lease.get(key), str) and capacity_lease[key]
                        for key in ("lease_id", "generation")
                    ):
                        raise _LayaCleanupUnconfirmed("GPU capacity lease identity is invalid")
                if loader is None:
                    model, agent = self._load_router_session(laya_module, path, selected)
                    actual_device = self._parameter_device(agent)
                    del agent
                else:
                    model = loader(
                        str(path), device=selected.device,
                        expected_sha256=dict(self.expected_sha256),
                    )
                    actual_device = self._parameter_device(model)
                if actual_device != selected.device:
                    raise RuntimeError("device mismatch")
            except _LayaCleanupUnconfirmed:
                if capacity_lease is not None:
                    self._capacity_lease = {
                        key: str(capacity_lease[key])
                        for key in ("lease_id", "generation")
                    }
                    self._capacity_provider_cleanup_unconfirmed = True
                raise
            except Exception as exc:
                if not isinstance(exc, _LayaCapacityUnavailable):
                    self._failed_devices.add((selected.provider, selected.device))
                errors.append(type(exc).__name__)
                if model is not None:
                    try:
                        closed = self._close(model)
                    except Exception as close_exc:
                        raise _LayaCleanupUnconfirmed(
                            "provider cleanup after load failure was unconfirmed; refusing device fallback"
                        ) from close_exc
                    if closed is not True:
                        raise _LayaCleanupUnconfirmed(
                            "provider cleanup after load failure was unconfirmed; refusing device fallback"
                        ) from exc
                if capacity_lease is not None and not self._release_capacity_lease(capacity_lease):
                    raise _LayaCleanupUnconfirmed(
                        "GPU capacity lease release after failed load was unconfirmed"
                    ) from exc
                continue
            self._capacity_lease = (
                {key: str(capacity_lease[key]) for key in ("lease_id", "generation")}
                if capacity_lease is not None
                else None
            )
            self._selected_device = DeviceCandidate(
                provider=selected.provider,
                device=selected.device,
                device_class=selected.device_class,
                device_name=selected.device_name,
                runtime_version=selected.runtime_version or runtime_version,
                available=selected.available,
                supports_laya=selected.supports_laya,
                quality_passed=selected.quality_passed,
            )
            return model
        raise LayaRuntimeUnavailable("all eligible Laya devices failed: " + ",".join(errors))

    def _load_router_session(
        self, module: Any, path: Path, selected: DeviceCandidate
    ) -> tuple[_LayaRouterSession, Any]:
        router_type = getattr(module, "Router", None)
        if not callable(router_type):
            raise LayaRuntimeUnavailable("installed Laya runtime does not expose Router.unload")
        try:
            parameters = inspect.signature(router_type).parameters
        except (TypeError, ValueError) as exc:
            raise LayaRuntimeUnavailable("cannot verify the installed Laya Router API") from exc
        accepts_extra = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )

        def accepts(name: str) -> bool:
            return name in parameters or accepts_extra

        model_name = "local-ai-hub-multilingual"
        router_options: dict[str, Any] = {
            "models": {model_name: str(path)},
            "device": selected.device,
            "default": model_name,
            "max_loaded": 1,
            "preload": False,
        }
        if accepts("sha256_digests"):
            router_options["sha256_digests"] = {model_name: dict(self.expected_sha256)}
        elif accepts("agent_kwargs"):
            router_options["agent_kwargs"] = {
                "expected_sha256": dict(self.expected_sha256)
            }
        else:
            raise LayaRuntimeUnavailable("installed Laya Router cannot receive pinned checkpoint hashes")
        if accepts("vega"):
            # Keep this integration scoped to the one approved multilingual checkpoint.
            router_options["vega"] = False

        router = router_type(**router_options)
        unload = getattr(router, "unload", None)
        loaded = getattr(router, "loaded", None)
        load = getattr(router, "load", None)
        if not callable(unload) or not callable(load) or loaded is None:
            raise LayaRuntimeUnavailable("installed Laya Router lacks its public load/unload API")
        if loaded:
            try:
                unload()
            except Exception as exc:
                raise _LayaCleanupUnconfirmed(
                    "preloaded Laya Router cleanup was unconfirmed; refusing device fallback"
                ) from exc
            if getattr(router, "loaded", None):
                raise _LayaCleanupUnconfirmed(
                    "preloaded Laya Router cleanup was unconfirmed; refusing device fallback"
                )
            raise LayaRuntimeUnavailable("Laya Router unexpectedly preloaded another checkpoint")
        agent = None
        session = _LayaRouterSession(router, model_name)
        try:
            agent = load(model_name)
            if agent is None or model_name not in router.loaded:
                raise RuntimeError("Laya Router did not retain the requested local checkpoint")
            actual_device = self._parameter_device(agent)
            if actual_device != selected.device:
                raise RuntimeError("device mismatch")
            return session, agent
        except Exception as exc:
            agent = None
            try:
                closed = session.close()
            except Exception as close_exc:
                raise _LayaCleanupUnconfirmed(
                    "Laya Router cleanup after load failure was unconfirmed; refusing device fallback"
                ) from close_exc
            if closed is not True:
                raise _LayaCleanupUnconfirmed(
                    "Laya Router cleanup after load failure was unconfirmed; refusing device fallback"
                ) from exc
            raise

    @staticmethod
    def _parameter_device(model: Any) -> str:
        model_body = getattr(model, "model", None)
        parameters = getattr(model_body, "parameters", None)
        if not callable(parameters):
            raise RuntimeError("Laya model does not expose parameter placement")
        try:
            first = next(iter(parameters()))
        except StopIteration as exc:
            raise RuntimeError("Laya model has no parameters") from exc
        device = getattr(first, "device", None)
        if device is None:
            raise RuntimeError("Laya parameter device is unavailable")
        return str(device)

    def _release_capacity_lease(self, lease: Mapping[str, Any]) -> bool:
        manager = self._capacity_manager
        release = getattr(manager, "release_gpu_capacity_lease", None)
        if not callable(release):
            return False
        return release(lease.get("lease_id"), self._capacity_owner, lease.get("generation")) is True

    @staticmethod
    def _close(model: Any) -> bool:
        close = getattr(model, "close", None)
        if not callable(close):
            return False
        return close() is True

    def _close_with_capacity(self, model: Any) -> bool:
        if not self._close(model):
            return False
        lease = self._capacity_lease
        if lease is not None:
            if not self._release_capacity_lease(lease):
                # Provider unload is confirmed, so lifecycle may drop this
                # session. Keep the lease accounted until a later release retry.
                self._capacity_lease_release_pending = True
                return True
            self._capacity_lease = None
            self._capacity_lease_release_pending = False
        return True

    @staticmethod
    def _input(evidence: ContextSourceEvidence) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        payload = {
            key: value for key, value in evidence.model_input().items()
            if key not in {
                "training_redacted_fields",
                "training_missing_fields",
                "training_missing_reason",
            }
        }
        # Raw fields have already passed the bounded DecisionInput redactor.
        # Identity, filesystem paths, and unrelated conversation data stay out.
        state = {"body": json.dumps(payload, sort_keys=True, separators=(",", ":"))}
        options = evidence.decision_options
        criteria = {option: _SOURCE_DESCRIPTIONS[option] for option in options}
        question = {
            "type": "choice",
            "instructions": "Choose the best authorized source for resolving the stated evidence gap.",
            "criteria": criteria,
        }
        return state, {"source": question}

    @staticmethod
    def _decision_input(
        request: DecisionRequest,
        decision_input: ContextSourceEvidence | DecisionInput,
    ) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        if isinstance(decision_input, ContextSourceEvidence):
            return LayaRuntimeAdapter._input(decision_input)
        state = {
            "category": request.category.value,
            "state": decision_input.model_state(),
            "evidence_ids": list(request.evidence_ids),
        }
        serialized = json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        question = {
            "type": "choice",
            "instructions": _CATEGORY_INSTRUCTIONS[request.category],
            "criteria": {option: option.replace("_", " ") for option in request.options},
        }
        return {"body": serialized}, {"source": question}

    @staticmethod
    def _tokens(result: Mapping[str, Any], field: str) -> int | None:
        usage = result.get("usage")
        if not isinstance(usage, Mapping):
            return None
        value = usage.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value

    def evaluate_decision(
        self,
        request: DecisionRequest,
        decision_input: ContextSourceEvidence | DecisionInput,
        *,
        session_lifecycle: Any,
        outcome_recorder: Callable[[DecisionRequest, Any, LayaRuntimeOutcome], Any] | None = None,
    ) -> LayaRuntimeOutcome:
        """Evaluate one typed shadow request; callers own auth and identity checks."""
        if not isinstance(request, DecisionRequest):
            raise ValueError("validated Laya decision request is required")
        if request.mode is not DecisionMode.SHADOW:
            raise ValueError("only explicit shadow evaluation mode is supported")
        if request.category is DecisionCategory.CONTEXT_SOURCE:
            if not isinstance(decision_input, ContextSourceEvidence):
                raise ValueError("validated context-source evidence is required")
            if request.evidence_ids != decision_input.evidence_ids or request.options != decision_input.decision_options:
                raise ValueError("request does not match its validated context-source evidence")
        elif not isinstance(decision_input, DecisionInput):
            raise ValueError("validated typed decision input is required")
        if outcome_recorder is not None and not callable(outcome_recorder):
            raise TypeError("outcome_recorder must be callable")
        if not callable(getattr(session_lifecycle, "inference_session", None)):
            raise TypeError("shared Laya session lifecycle is required")
        if not self.evaluation_mode:
            skipped = DecisionResult(
                request=request,
                success=False,
                status=DecisionStatus.SKIPPED,
                suggestion=None,
                reason_codes=("DISABLED",),
            )
            return LayaRuntimeOutcome(decision=skipped, runtime=None)
        if not self._call_lock.acquire(blocking=False):
            overloaded = DecisionResult(
                request=request,
                success=False,
                status=DecisionStatus.SKIPPED,
                suggestion=None,
                reason_codes=("OVERLOADED",),
            )
            return LayaRuntimeOutcome(decision=overloaded, runtime=None)

        started = self._clock()
        try:
            lifecycle_status = getattr(session_lifecycle, "status", None)
            provider_close_configured = (
                lifecycle_status.get("provider_close_configured") is True
                if isinstance(lifecycle_status, Mapping)
                else False
            )
            if not provider_close_configured:
                bind_close_session = getattr(session_lifecycle, "bind_close_session", None)
                if not callable(bind_close_session):
                    raise RuntimeError("provider close callback unavailable")
                bind_close_session(self._close_with_capacity)
            with session_lifecycle.inference_session(self._load) as model:
                state, questions = self._decision_input(request, decision_input)
                result = model.predict(state, questions)
                elapsed = max(0.0, (self._clock() - started) * 1000.0)
                if not math.isfinite(elapsed):
                    elapsed = 0.0
                decision = self._decode(request, result)
                selected = self._selected_device
                if selected is None:
                    raise RuntimeError("selected Laya device metadata is unavailable")
                runtime = LayaRuntimeMetadata(
                    model_id="convaiinnovations/laya-multilingual",
                    revision=self.revision,
                    provider=selected.provider,
                    runtime_version=selected.runtime_version,
                    device=selected.device,
                    device_class=selected.device_class,
                    device_name=selected.device_name,
                    parameter_device=selected.device,
                    execution_verification="NOT_VERIFIED",
                    quality_status="NOT_EVALUATED",
                    latency_ms=elapsed,
                    input_tokens=self._tokens(result, "input_tokens") if isinstance(result, Mapping) else None,
                    output_tokens=self._tokens(result, "output_tokens") if isinstance(result, Mapping) else None,
                    fallback_reason=("EARLIER_DEVICE_UNAVAILABLE" if self._failed_devices else None),
                )
                outcome = LayaRuntimeOutcome(decision=decision, runtime=runtime)
                if outcome_recorder is not None:
                    try:
                        outcome_recorder(request, decision_input, outcome)
                        outcome = LayaRuntimeOutcome(
                            decision=decision, runtime=runtime, capture_status="captured"
                        )
                    except Exception:
                        # Shadow capture is observational: storage trouble cannot alter the decision.
                        outcome = LayaRuntimeOutcome(
                            decision=decision, runtime=runtime, capture_status="failed"
                        )
                return outcome
        except Exception:
            reason = "MODEL_UNAVAILABLE"
            failed = DecisionResult(
                request=request,
                success=False,
                status=DecisionStatus.ERROR,
                suggestion=None,
                reason_codes=(reason,),
            )
            return LayaRuntimeOutcome(decision=failed, runtime=None)
        finally:
            self._call_lock.release()

    def evaluate_context_source(
        self,
        request: DecisionRequest,
        evidence: ContextSourceEvidence,
        *,
        session_lifecycle: Any,
        outcome_recorder: Callable[[DecisionRequest, ContextSourceEvidence, LayaRuntimeOutcome], Any] | None = None,
    ) -> LayaRuntimeOutcome:
        """Compatibility entry point for the ordinary context-source pilot."""
        if not isinstance(request, DecisionRequest) or request.category is not DecisionCategory.CONTEXT_SOURCE:
            raise ValueError("only the approved context_source pilot is supported")
        return self.evaluate_decision(
            request,
            evidence,
            session_lifecycle=session_lifecycle,
            outcome_recorder=outcome_recorder,
        )

    @staticmethod
    def _decode(request: DecisionRequest, result: Any) -> DecisionResult:
        if not isinstance(result, Mapping):
            return DecisionResult(
                request=request, success=False, status=DecisionStatus.ERROR,
                suggestion=None, reason_codes=("INVALID_OUTPUT",),
            )
        answers = result.get("answers")
        answer = answers.get("source") if isinstance(answers, Mapping) else None
        if not isinstance(answer, Mapping):
            return DecisionResult(
                request=request, success=True, status=DecisionStatus.ABSTAIN,
                suggestion=None, reason_codes=("LOW_SIGNAL",),
            )
        suggestion = answer.get("choice")
        if not isinstance(suggestion, str) or suggestion not in request.options:
            return DecisionResult(
                request=request, success=False, status=DecisionStatus.ERROR,
                suggestion=None, reason_codes=("INVALID_OUTPUT",),
            )
        return DecisionResult(
            request=request, success=True, status=DecisionStatus.SUCCESS,
            suggestion=suggestion, reason_codes=("EVIDENCE_SUFFICIENT",),
        )
