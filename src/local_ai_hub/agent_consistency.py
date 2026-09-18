"""Deterministic, soft consistency checks for agent task context.

The guard deliberately keeps repository evidence separate from suggestions.  It
does not mutate task state, remove history, or treat model output as proof.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .agent_tasks import GoalContract
from .repo_tools import RepositoryTools


_MAX_TEXT = 1200
_MAX_ITEMS = 64
_IDENTIFIER = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")
_PUBLIC_SYMBOL = re.compile(r"^\+\s*(?:export\s+)?(?:async\s+)?(?:def|class|function|const|let|type|interface)\s+([A-Za-z_]\w*)")
_HTTP_ENDPOINT = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+([/A-Za-z0-9_{}:$.-]+)")
_FIELD = re.compile(r"\b([A-Za-z_]\w*)\s*:\s*([A-Za-z_][\w<>\[\]| ]*)(?=[,;}\n]|$)")


def _text(value: Any, limit: int = _MAX_TEXT) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        rendered = value
    else:
        try:
            rendered = str(value)
        except Exception:
            rendered = "<unserializable>"
    return rendered[:limit]


def _tuple(value: Any, limit: int = _MAX_ITEMS) -> tuple[str, ...]:
    if isinstance(value, str):
        values = (value,)
    else:
        try:
            values = itertools.islice(iter(value), limit)
        except Exception:
            values = ()
    output: list[str] = []
    try:
        for item in values:
            if item is not None:
                output.append(_text(item, 240))
    except Exception:
        pass
    return tuple(output[:limit])


def _bounded_sequence(value: Any, limit: int = _MAX_ITEMS) -> tuple[Any, ...]:
    try:
        return tuple(itertools.islice(iter(value), limit))
    except Exception:
        return ()


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"", "0", "false", "no", "off", "none", "null"}:
            return False
        if normalized in {"1", "true", "yes", "on"}:
            return True
    try:
        return bool(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except Exception:
        return default


def _json_value(value: Any, depth: int = 0, seen: set[int] | None = None) -> Any:
    seen = seen if seen is not None else set()
    if depth > 3:
        return _text(value, 240)
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else 0.0
    identity = id(value)
    if identity in seen:
        return "<cycle>"
    if isinstance(value, Mapping):
        seen.add(identity)
        output: dict[str, Any] = {}
        try:
            items = itertools.islice(value.items(), _MAX_ITEMS)
            for key, item in items:
                output[_text(key, 80)] = _json_value(item, depth + 1, seen)
        except Exception:
            pass
        seen.discard(identity)
        return output
    if isinstance(value, (tuple, list, set)):
        seen.add(identity)
        output: list[Any] = []
        try:
            for item in itertools.islice(iter(value), _MAX_ITEMS):
                output.append(_json_value(item, depth + 1, seen))
        except Exception:
            pass
        seen.discard(identity)
        return output
    return _text(value, 240)


def _normalise_authority_label(value: Any) -> str:
    raw = unicodedata.normalize("NFKC", _text(value, 240)).casefold()
    return re.sub(r"[^a-z0-9]+", " ", raw).strip()


def _is_local_model_evidence(item: Mapping[str, Any]) -> bool:
    labels = []
    for key in ("source", "provider", "provider_name", "model", "model_name"):
        if item.get(key) is not None:
            labels.append(_normalise_authority_label(item.get(key)))
    blocked = {"local", "model", "llm", "generated", "local model", "local model output", "local inference", "ollama"}
    model_family = ("qwen", "llama", "mistral", "gemma", "phi", "deepseek", "granite", "llm")
    for label in labels:
        compact = label.replace(" ", "")
        tokens = set(label.split())
        if label in blocked or tokens.intersection({"model", "llm", "generated", "ollama"}) or "ollama" in compact:
            return True
        if "local" in label and any(token in label for token in ("model", "inference", "llm", "ai")):
            return True
        if any(compact.startswith(prefix) for prefix in model_family):
            return True
    return False


@dataclass(frozen=True)
class ConsistencyRequest:
    root: str
    task_id: str = ""
    query: str = ""
    phase: str = ""
    focus: tuple[str, ...] = ()
    workspace: str = ""
    preload_profile: str = ""
    token_budget: int = 2400
    changed_paths: tuple[str, ...] = ()
    base: str = "HEAD"
    staged: bool = False
    tenant: str = ""
    override_reason: str = ""
    approval: str | bool = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", _text(self.root, 400))
        object.__setattr__(self, "task_id", _text(self.task_id, 160))
        object.__setattr__(self, "query", _text(self.query, 800))
        object.__setattr__(self, "phase", _text(self.phase, 80))
        object.__setattr__(self, "focus", _tuple(self.focus, 16))
        object.__setattr__(self, "workspace", _text(self.workspace, 160))
        object.__setattr__(self, "preload_profile", _text(self.preload_profile, 120))
        object.__setattr__(self, "token_budget", max(128, min(_safe_int(self.token_budget, 2400), 20000)))
        object.__setattr__(self, "changed_paths", _tuple(self.changed_paths, 64))
        object.__setattr__(self, "base", _text(self.base, 160) or "HEAD")
        object.__setattr__(self, "staged", _safe_bool(self.staged))
        object.__setattr__(self, "tenant", _text(self.tenant, 160))
        object.__setattr__(self, "override_reason", _text(self.override_reason, 500))
        if not isinstance(self.approval, bool):
            object.__setattr__(self, "approval", _text(self.approval, 240))

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root, "task_id": self.task_id, "query": self.query,
            "phase": self.phase, "focus": list(self.focus), "workspace": self.workspace,
            "preload_profile": self.preload_profile, "token_budget": self.token_budget,
            "changed_paths": list(self.changed_paths), "base": self.base, "staged": self.staged,
            "tenant": self.tenant, "override_reason": self.override_reason, "approval": self.approval,
        }


@dataclass(frozen=True)
class ReuseCandidate:
    candidate_id: str
    kind: str
    path: str
    symbol: str = ""
    line: int = 0
    score: float = 0.0
    reason: str = ""
    evidence_ids: tuple[str, ...] = ()
    suitable: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _text(self.candidate_id, 160))
        object.__setattr__(self, "kind", _text(self.kind, 80))
        object.__setattr__(self, "path", _text(self.path, 400))
        object.__setattr__(self, "symbol", _text(self.symbol, 160))
        object.__setattr__(self, "line", max(0, _safe_int(self.line)))
        object.__setattr__(self, "score", round(_safe_float(self.score), 3))
        object.__setattr__(self, "reason", _text(self.reason, 400))
        object.__setattr__(self, "evidence_ids", _tuple(self.evidence_ids))
        object.__setattr__(self, "suitable", _safe_bool(self.suitable, True))

    def to_dict(self) -> dict[str, Any]:
        return _json_value({
            "candidate_id": self.candidate_id, "kind": self.kind, "path": self.path,
            "symbol": self.symbol, "line": self.line, "score": self.score,
            "reason": self.reason, "evidence_ids": list(self.evidence_ids), "suitable": self.suitable,
        })


@dataclass(frozen=True)
class ContractMapping:
    kind: str
    endpoint: str = ""
    backend_path: str = ""
    frontend_path: str = ""
    backend_symbol: str = ""
    frontend_symbol: str = ""
    backend_fields: tuple[str, ...] = ()
    frontend_fields: tuple[str, ...] = ()
    backend_error_identifiers: tuple[str, ...] = ()
    frontend_error_identifiers: tuple[str, ...] = ()
    loading_state: str = ""
    empty_state: str = ""
    error_state: str = ""
    test_paths: tuple[str, ...] = ()
    status: str = "matched"
    evidence_ids: tuple[str, ...] = ()
    mismatches: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("kind", "endpoint", "backend_path", "frontend_path", "backend_symbol", "frontend_symbol", "loading_state", "empty_state", "error_state", "status"):
            object.__setattr__(self, name, _text(getattr(self, name), 240))
        for name in ("backend_fields", "frontend_fields", "backend_error_identifiers", "frontend_error_identifiers", "test_paths", "evidence_ids", "mismatches"):
            object.__setattr__(self, name, _tuple(getattr(self, name)))

    def to_dict(self) -> dict[str, Any]:
        return _json_value({name: value for name, value in {
            "kind": self.kind, "endpoint": self.endpoint, "backend_path": self.backend_path,
            "frontend_path": self.frontend_path, "backend_symbol": self.backend_symbol,
            "frontend_symbol": self.frontend_symbol, "backend_fields": self.backend_fields,
            "frontend_fields": self.frontend_fields, "backend_error_identifiers": self.backend_error_identifiers,
            "frontend_error_identifiers": self.frontend_error_identifiers, "loading_state": self.loading_state,
            "empty_state": self.empty_state, "error_state": self.error_state, "test_paths": self.test_paths,
            "status": self.status, "evidence_ids": self.evidence_ids, "mismatches": self.mismatches,
        }.items()})


@dataclass(frozen=True)
class GuardWarning:
    severity: str
    code: str = ""
    message: str = ""
    evidence_ids: tuple[str, ...] = ()
    affected_paths: tuple[str, ...] = ()
    recommended_action: str = ""
    requires_approval: bool = False
    kind: str = ""

    def __post_init__(self) -> None:
        code = _text(self.code or self.kind, 100)
        object.__setattr__(self, "severity", _text(self.severity, 40))
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "kind", _text(self.kind or code, 100))
        object.__setattr__(self, "message", _text(self.message, _MAX_TEXT))
        object.__setattr__(self, "evidence_ids", _tuple(self.evidence_ids))
        object.__setattr__(self, "affected_paths", _tuple(self.affected_paths))
        object.__setattr__(self, "recommended_action", _text(self.recommended_action, 500))
        object.__setattr__(self, "requires_approval", _safe_bool(self.requires_approval))

    def to_dict(self) -> dict[str, Any]:
        return _json_value({
            "severity": self.severity, "code": self.code, "kind": self.kind, "message": self.message,
            "evidence_ids": list(self.evidence_ids), "affected_paths": list(self.affected_paths),
            "recommended_action": self.recommended_action, "requires_approval": self.requires_approval,
        })


@dataclass(frozen=True)
class AdaptiveContextPack:
    contract: GoalContract | None = None
    reuse_candidates: tuple[ReuseCandidate, ...] = ()
    mappings: tuple[ContractMapping, ...] = ()
    warnings: tuple[GuardWarning, ...] = ()
    evidence: tuple[dict[str, Any], ...] = ()
    repo_revision: str = ""
    changed_paths: tuple[str, ...] = ()
    stale: bool = False
    context_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "reuse_candidates", _bounded_sequence(self.reuse_candidates))
        object.__setattr__(self, "mappings", _bounded_sequence(self.mappings))
        object.__setattr__(self, "warnings", _bounded_sequence(self.warnings))
        object.__setattr__(self, "evidence", _bounded_sequence(self.evidence))
        object.__setattr__(self, "repo_revision", _text(self.repo_revision, 200))
        object.__setattr__(self, "changed_paths", _tuple(self.changed_paths, 64))
        object.__setattr__(self, "stale", _safe_bool(self.stale))
        object.__setattr__(self, "context_id", _text(self.context_id, 200))

    def to_dict(self) -> dict[str, Any]:
        try:
            contract = self.contract.to_dict() if self.contract else None
        except Exception:
            contract = {"goal": "<unserializable>"}
        def nested(value: Any) -> Any:
            try:
                converter = getattr(value, "to_dict", None)
                return converter() if callable(converter) else value
            except Exception:
                return "<unserializable>"

        return _json_value({
            "contract": contract,
            "reuse_candidates": [nested(item) for item in self.reuse_candidates[:_MAX_ITEMS]],
            "mappings": [nested(item) for item in self.mappings[:_MAX_ITEMS]],
            "warnings": [nested(item) for item in self.warnings[:_MAX_ITEMS]],
            "evidence": [_json_value(item) for item in self.evidence[:_MAX_ITEMS]],
            "repo_revision": _text(self.repo_revision, 200), "changed_paths": list(_tuple(self.changed_paths)),
            "stale": bool(self.stale), "context_id": _text(self.context_id, 200),
        })


class AgentConsistencyGuard:
    """Compose bounded repository evidence into soft consistency findings."""

    def __init__(self, repository_tools: RepositoryTools | Mapping[str, Any] | None = None, *, task_store: Any = None, memory_store: Any = None, verification_store: Any = None, max_candidates: int = 24) -> None:
        if isinstance(repository_tools, Mapping):
            repository_tools = RepositoryTools(dict(repository_tools))
        self.repository_tools = repository_tools or RepositoryTools({})
        self.task_store = task_store
        self.memory_store = memory_store
        self.verification_store = verification_store
        self.max_candidates = max(1, min(int(max_candidates), 64))

    def build_contract(self, request: ConsistencyRequest) -> GoalContract:
        contract: Any = None
        if self.task_store is not None and request.task_id:
            try:
                getter = getattr(self.task_store, "get", None) or getattr(self.task_store, "get_task", None)
                if getter:
                    state = getter(request.task_id)
                    contract = state.get("contract") if isinstance(state, Mapping) else getattr(state, "contract", None)
            except Exception:
                contract = None
        if isinstance(contract, GoalContract):
            return contract
        if isinstance(contract, Mapping):
            return GoalContract.from_dict(contract)
        return GoalContract(goal=request.query, scope="task")

    @staticmethod
    def _evidence_id(item: Mapping[str, Any]) -> str:
        explicit = item.get("evidence_id") or item.get("id")
        if explicit:
            return _text(explicit, 200)
        raw = _text(item.get("raw") or item.get("text"), 1600)
        path = _text(item.get("path"), 400)
        return "ev-" + hashlib.sha256(f"{path}\n{raw}".encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _raw(item: Mapping[str, Any]) -> str:
        return _text(item.get("raw") or item.get("text") or item.get("content"), 5000)

    def find_reuse_candidates(self, request: ConsistencyRequest, contract: GoalContract) -> tuple[ReuseCandidate, ...]:
        query = " ".join(x for x in (request.query, contract.goal, *contract.constraints, *request.focus) if x)
        if request.changed_paths:
            result = self.repository_tools.search_paths(request.root, query, list(request.changed_paths), top_k=self.max_candidates, context_lines=3)
        else:
            result = self.repository_tools.search(request.root, query, top_k=self.max_candidates, context_lines=3)
        if not result.get("success"):
            return ()
        candidates: list[ReuseCandidate] = []
        for item in _bounded_sequence(result.get("results", ()), self.max_candidates):
            path = _text(item.get("path"), 400)
            raw = self._raw(item)
            if path and not raw:
                try:
                    exact = self.repository_tools.file_slice(
                        request.root,
                        path,
                        int(item.get("start_line", 1) or 1),
                        int(item.get("end_line", item.get("start_line", 1)) or 1),
                        max_chars=2400,
                    )
                    raw = _text(exact.get("text"), 2400) if exact.get("success") else ""
                except Exception:
                    raw = ""
            symbols = re.findall(r"\b(?:class|def|function|interface|type|const)\s+([A-Za-z_]\w*)", raw)
            symbol = symbols[0] if symbols else Path(path).stem
            kind = "frontend" if any(token in path.lower() for token in ("frontend", "client", ".ts", ".tsx", "component")) else "backend"
            reinvention = bool(re.search(r"(?:^|[/_.-])(new|reinvent|duplicate|copy)(?:[/_.-]|$)", f"{path.lower()}"))
            score = _safe_float(item.get("score", 0.0)) + (2.0 if symbol.lower() in query.lower() else 0.0)
            if reinvention:
                score = max(0.0, score - 3.0)
            evidence_id = self._evidence_id(item)
            candidate_id = "reuse-" + hashlib.sha256(f"{path}:{item.get('start_line', 0)}:{symbol}".encode("utf-8")).hexdigest()[:16]
            candidates.append(ReuseCandidate(candidate_id, kind, path, symbol, _safe_int(item.get("start_line", 0)), score, "deterministic repository match", (evidence_id,), not reinvention))
        candidates.sort(key=lambda item: (-int(item.suitable), -item.score, item.path, item.line, item.candidate_id))
        return tuple(candidates[: self.max_candidates])

    def build_contract_mappings(self, request: ConsistencyRequest, evidence: Iterable[Mapping[str, Any]] | Mapping[str, Any]) -> tuple[tuple[ContractMapping, ...], tuple[GuardWarning, ...]]:
        if isinstance(evidence, Mapping):
            evidence = evidence.get("evidence") or evidence.get("results") or ()
        items = [dict(item) for item in _bounded_sequence(evidence, _MAX_ITEMS) if isinstance(item, Mapping)]
        back = [item for item in items if self._is_backend(item)]
        front = [item for item in items if not self._is_backend(item)]
        tests = [str(item.get("path")) for item in items if self._is_test(item)]
        if not back or not front:
            return (), ()
        b, f = back[0], front[0]
        braw, fraw = self._raw(b), self._raw(f)
        be_id, fe_id = self._evidence_id(b), self._evidence_id(f)
        endpoint_match = _HTTP_ENDPOINT.search(braw + "\n" + fraw)
        endpoint = endpoint_match.group(2) if endpoint_match else ""
        bfields = tuple(sorted(set(name for name, _ in _FIELD.findall(braw))))
        ffields = tuple(sorted(set(name for name, _ in _FIELD.findall(fraw))))
        berr = tuple(sorted(set(_IDENTIFIER.findall(braw))))
        ferr = tuple(sorted(set(_IDENTIFIER.findall(fraw))))
        mappings: list[ContractMapping] = []
        warnings: list[GuardWarning] = []
        pair_ids = (be_id, fe_id)
        mappings.append(ContractMapping("endpoint", endpoint, str(b.get("path", "")), str(f.get("path", "")), evidence_ids=pair_ids, test_paths=tuple(tests)))
        missing = tuple(sorted(set(bfields) - set(ffields)))
        nullable_backend = {name for name, typ in _FIELD.findall(braw) if "null" in typ or "None" in typ}
        nullable_frontend = {name for name, typ in _FIELD.findall(fraw) if "null" in typ or "undefined" in typ or "?" in typ}
        mismatches = list(missing)
        if missing or nullable_backend != nullable_frontend:
            mappings.append(ContractMapping("response", endpoint, str(b.get("path", "")), str(f.get("path", "")), backend_fields=bfields, frontend_fields=ffields, status="mismatch", evidence_ids=pair_ids, mismatches=tuple(mismatches or ("nullable markers",))))
            warnings.append(GuardWarning("warning", "response_schema_mismatch", "backend and frontend response schemas differ", pair_ids, (str(b.get("path", "")), str(f.get("path", ""))), "align response fields and nullable markers"))
        else:
            mappings.append(ContractMapping("response", endpoint, str(b.get("path", "")), str(f.get("path", "")), backend_fields=bfields, frontend_fields=ffields, evidence_ids=pair_ids))
        error_diff = tuple(sorted(set(berr) - set(ferr)))
        if error_diff:
            mappings.append(ContractMapping("error", endpoint, str(b.get("path", "")), str(f.get("path", "")), backend_error_identifiers=berr, frontend_error_identifiers=ferr, status="mismatch", evidence_ids=pair_ids, mismatches=error_diff))
            warnings.append(GuardWarning("warning", "error_identifier_mismatch", "backend error identifiers are not handled by the frontend", pair_ids, (str(b.get("path", "")), str(f.get("path", ""))), "map backend error codes to the frontend error model"))
        else:
            mappings.append(ContractMapping("error", endpoint, str(b.get("path", "")), str(f.get("path", "")), backend_error_identifiers=berr, frontend_error_identifiers=ferr, evidence_ids=pair_ids))
        for state, markers in (("loading", ("loading", "isloading")), ("empty", ("empty", "no results")), ("error", ("error", "catch"))):
            if not any(marker in fraw.lower() for marker in markers):
                warnings.append(GuardWarning("warning", f"{state}_state_missing", f"frontend {state} state is not visible in bounded evidence", (fe_id,), (str(f.get("path", "")),), f"add or verify the frontend {state} state"))
        return tuple(mappings[:_MAX_ITEMS]), tuple(warnings[:_MAX_ITEMS])

    @staticmethod
    def _is_backend(item: Mapping[str, Any]) -> bool:
        path = str(item.get("path", "")).lower()
        return not any(token in path for token in ("frontend", "client", ".ts", ".tsx", "component"))

    @staticmethod
    def _is_test(item: Mapping[str, Any]) -> bool:
        path = str(item.get("path", "")).lower()
        return "/test" in f"/{path}" or path.startswith("test_") or "_test" in path

    def check_claims(self, evidence: Iterable[Mapping[str, Any]] | Mapping[str, Any], claims: Iterable[Any], request: ConsistencyRequest | None = None) -> tuple[GuardWarning, ...]:
        if isinstance(evidence, Mapping):
            evidence = evidence.get("evidence") or evidence.get("results") or ()
        authoritative: dict[str, Mapping[str, Any]] = {}
        for item in _bounded_sequence(evidence, _MAX_ITEMS):
            if not isinstance(item, Mapping) or _is_local_model_evidence(item):
                continue
            authoritative[self._evidence_id(item)] = item
        warnings: list[GuardWarning] = []
        for claim in _bounded_sequence(claims, _MAX_ITEMS):
            if isinstance(claim, Mapping):
                text = _text(claim.get("claim") or claim.get("text"), 400)
                ids = _tuple(claim.get("evidence_ids"))
            else:
                text, ids = _text(claim, 400), ()
            if not ids or any(evidence_id not in authoritative for evidence_id in ids):
                warnings.append(GuardWarning("warning", "unknown_claim", f"unsupported claim: {text}", (), (), "verify the claim with deterministic repository evidence"))
                self._persist_claim_decision(request, text, (), "unknown")
            else:
                self._persist_claim_decision(request, text, ids, "verified")
        return tuple(warnings)

    def _persist_claim_decision(self, request: ConsistencyRequest | None, claim: str, evidence_ids: tuple[str, ...], status: str) -> None:
        """Use existing stores when supplied; never create a parallel persistence layer."""
        if request is None or (self.memory_store is None and self.verification_store is None):
            return
        try:
            revision = self.repository_tools.git_snapshot(request.root).revision
        except Exception:
            revision = ""
        compact_claim = _text(claim, 240)
        key_digest = hashlib.sha256(f"{request.task_id}:{status}:{compact_claim}:{','.join(evidence_ids)}".encode("utf-8")).hexdigest()[:16]
        if self.memory_store is not None and callable(getattr(self.memory_store, "record", None)):
            try:
                from .agent_identity import AgentScope
                from .agent_memory import MemoryKind, MemoryRecord

                record = MemoryRecord.create(
                    kind=MemoryKind.FINDING if status == "verified" else MemoryKind.UNKNOWN,
                    scope=AgentScope.REPOSITORY,
                    key=f"consistency_claim:{key_digest}",
                    value={"status": status, "claim": compact_claim},
                    source="consistency_guard",
                    evidence_ids=tuple(evidence_ids),
                    repository_revision=revision,
                    path_refs=tuple(request.changed_paths),
                    related_task=request.task_id,
                    provenance={"root": _text(request.root, 400), "guard": "agent_consistency"},
                )
                try:
                    self.memory_store.record(record, actor="consistency_guard", idempotency_key=f"consistency:{key_digest}")
                except TypeError:
                    self.memory_store.record(record)
            except Exception:
                pass
        if status == "verified" and request.task_id and evidence_ids and self.verification_store is not None and callable(getattr(self.verification_store, "record", None)):
            try:
                from .agent_verification import VerificationReceipt

                receipt = VerificationReceipt.create(
                    task_id=request.task_id,
                    criterion=f"consistency claim:{key_digest}",
                    evidence_id=evidence_ids[0],
                    repository_revision=revision,
                    details={"kind": "claim", "evidence_ids": list(evidence_ids)},
                )
                self.verification_store.record(receipt)
            except Exception:
                pass

    def check_drift(self, request: ConsistencyRequest, contract: GoalContract, changed_paths: Iterable[str], diff: Mapping[str, Any] | str | None) -> tuple[GuardWarning, ...]:
        warnings: list[GuardWarning] = []
        paths = list(_bounded_sequence(_tuple(changed_paths), _MAX_ITEMS))
        if diff is None:
            try:
                diff = self.repository_tools.git_diff(request.root, base=request.base, staged=request.staged, max_tokens=request.token_budget)
            except Exception:
                diff = {}
        diff_data: Mapping[str, Any] = diff if isinstance(diff, Mapping) else {}
        if not paths:
            paths = list(_tuple(diff_data.get("changed_paths") or diff_data.get("changed_files")))
        if not paths:
            try:
                paths = list(_bounded_sequence(self.repository_tools.git_snapshot(request.root).changed_paths, _MAX_ITEMS))
            except Exception:
                paths = []
        if paths and not diff_data.get("impact"):
            try:
                impact = self.repository_tools.impact_analysis(request.root, base=request.base, staged=request.staged)
                if isinstance(impact, Mapping) and impact.get("success"):
                    diff_data = {**diff_data, "impact": impact}
            except Exception:
                pass
        candidates = self.find_reuse_candidates(request, contract)
        candidate_ids = {item.candidate_id for item in candidates}
        decisions = diff_data.get("reuse_decisions") or ()
        bounded_evidence = _bounded_sequence(diff_data.get("evidence") or (), _MAX_ITEMS)
        diff_evidence_ids = self._deterministic_evidence_ids(bounded_evidence)
        for decision in _bounded_sequence(decisions, _MAX_ITEMS):
            if not isinstance(decision, Mapping):
                continue
            candidate_id = str(decision.get("candidate_id", ""))
            action = str(decision.get("decision", decision.get("action", ""))).lower()
            reason = str(decision.get("reason", "")).strip()
            decision_evidence_ids = _tuple(decision.get("evidence_ids")) or diff_evidence_ids
            if candidate_id not in candidate_ids:
                warnings.append(GuardWarning("warning", "unknown_reuse_candidate", "reuse decision references no deterministic candidate", decision_evidence_ids, tuple(paths), "refresh deterministic reuse candidates"))
            elif action in {"reject", "rejected", "new"} and not reason:
                candidate = next(item for item in candidates if item.candidate_id == candidate_id)
                warnings.append(GuardWarning("warning", "reuse_rejection_reason_required", "rejected reuse candidate needs a concise reason", candidate.evidence_ids or decision_evidence_ids, tuple(paths), "record why reuse violates the contract or boundary"))
        diff_text = diff if isinstance(diff, str) else str(diff_data.get("diff", ""))
        added_symbols = [match.group(1) for line in _text(diff_text, 12000).splitlines() if (match := _PUBLIC_SYMBOL.match(line))]
        if added_symbols and any(candidate.suitable for candidate in candidates):
            candidate_evidence_ids = tuple(evidence_id for candidate in candidates if candidate.suitable for evidence_id in candidate.evidence_ids)
            warnings.append(GuardWarning("boundary", "new_public_symbol_despite_reuse", "new public symbol added while a suitable reuse candidate exists", candidate_evidence_ids or diff_evidence_ids, tuple(paths), "approve the boundary or reuse the existing symbol", True))
        if request.changed_paths:
            requested = set(request.changed_paths)
            outside = tuple(path for path in paths if path not in requested)
            if outside:
                warnings.append(GuardWarning("warning", "scope_drift", "changed paths exceed the request scope", diff_evidence_ids, outside, "explain the scope expansion or narrow the change"))
        evidence = bounded_evidence
        if evidence:
            try:
                checked = self.repository_tools.verify_evidence(request.root, list(_bounded_sequence(evidence, _MAX_ITEMS)))
                if checked.get("stale"):
                    warnings.append(GuardWarning("warning", "stale_evidence", "one or more evidence slices are stale", diff_evidence_ids, tuple(paths), "refresh evidence at the current repository revision"))
            except Exception:
                pass
        return tuple(warnings[:_MAX_ITEMS])

    def _deterministic_evidence_ids(self, evidence: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
        ids: list[str] = []
        for item in _bounded_sequence(evidence, _MAX_ITEMS):
            if isinstance(item, Mapping) and not _is_local_model_evidence(item):
                ids.append(self._evidence_id(item))
        return tuple(dict.fromkeys(ids))[:_MAX_ITEMS]
