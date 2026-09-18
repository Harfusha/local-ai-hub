"""Deterministic, soft consistency checks for agent task context.

The guard deliberately keeps repository evidence separate from suggestions.  It
does not mutate task state, remove history, or treat model output as proof.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
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
    rendered = str(value or "")
    return rendered[:limit]


def _tuple(value: Any, limit: int = _MAX_ITEMS) -> tuple[str, ...]:
    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, Iterable):
        values = tuple(value)
    else:
        values = ()
    return tuple(_text(item, 240) for item in values if item is not None)[:limit]


def _json_value(value: Any, depth: int = 0) -> Any:
    if depth > 3:
        return _text(value, 240)
    if value is None or isinstance(value, (bool, int, float, str)):
        return _text(value) if isinstance(value, str) else value
    if isinstance(value, Mapping):
        return {_text(k, 80): _json_value(v, depth + 1) for k, v in list(value.items())[:_MAX_ITEMS]}
    if isinstance(value, (tuple, list, set)):
        return [_json_value(item, depth + 1) for item in list(value)[:_MAX_ITEMS]]
    return _text(value, 240)


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
        object.__setattr__(self, "token_budget", max(128, min(int(self.token_budget), 20000)))
        object.__setattr__(self, "changed_paths", _tuple(self.changed_paths, 64))
        object.__setattr__(self, "base", _text(self.base, 160) or "HEAD")
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
        object.__setattr__(self, "line", max(0, int(self.line)))
        object.__setattr__(self, "score", round(float(self.score), 3))
        object.__setattr__(self, "reason", _text(self.reason, 400))
        object.__setattr__(self, "evidence_ids", _tuple(self.evidence_ids))

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id, "kind": self.kind, "path": self.path,
            "symbol": self.symbol, "line": self.line, "score": self.score,
            "reason": self.reason, "evidence_ids": list(self.evidence_ids), "suitable": self.suitable,
        }


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
        return {name: _json_value(value) for name, value in {
            "kind": self.kind, "endpoint": self.endpoint, "backend_path": self.backend_path,
            "frontend_path": self.frontend_path, "backend_symbol": self.backend_symbol,
            "frontend_symbol": self.frontend_symbol, "backend_fields": self.backend_fields,
            "frontend_fields": self.frontend_fields, "backend_error_identifiers": self.backend_error_identifiers,
            "frontend_error_identifiers": self.frontend_error_identifiers, "loading_state": self.loading_state,
            "empty_state": self.empty_state, "error_state": self.error_state, "test_paths": self.test_paths,
            "status": self.status, "evidence_ids": self.evidence_ids, "mismatches": self.mismatches,
        }.items()}


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity, "code": self.code, "kind": self.kind, "message": self.message,
            "evidence_ids": list(self.evidence_ids), "affected_paths": list(self.affected_paths),
            "recommended_action": self.recommended_action, "requires_approval": self.requires_approval,
        }


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract.to_dict() if self.contract else None,
            "reuse_candidates": [item.to_dict() for item in self.reuse_candidates[:_MAX_ITEMS]],
            "mappings": [item.to_dict() for item in self.mappings[:_MAX_ITEMS]],
            "warnings": [item.to_dict() for item in self.warnings[:_MAX_ITEMS]],
            "evidence": [_json_value(item) for item in self.evidence[:_MAX_ITEMS]],
            "repo_revision": _text(self.repo_revision, 200), "changed_paths": list(_tuple(self.changed_paths)),
            "stale": bool(self.stale), "context_id": _text(self.context_id, 200),
        }


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
        for item in result.get("results", [])[: self.max_candidates]:
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
            score = float(item.get("score", 0.0)) + (2.0 if symbol.lower() in query.lower() else 0.0)
            evidence_id = self._evidence_id(item)
            candidate_id = "reuse-" + hashlib.sha256(f"{path}:{item.get('start_line', 0)}:{symbol}".encode("utf-8")).hexdigest()[:16]
            candidates.append(ReuseCandidate(candidate_id, kind, path, symbol, int(item.get("start_line", 0) or 0), score, "deterministic repository match", (evidence_id,)))
        candidates.sort(key=lambda item: (-int(item.suitable), -item.score, item.path, item.line, item.candidate_id))
        return tuple(candidates[: self.max_candidates])

    def build_contract_mappings(self, request: ConsistencyRequest, evidence: Iterable[Mapping[str, Any]] | Mapping[str, Any]) -> tuple[tuple[ContractMapping, ...], tuple[GuardWarning, ...]]:
        if isinstance(evidence, Mapping):
            evidence = evidence.get("evidence") or evidence.get("results") or ()
        items = [dict(item) for item in list(evidence)[:_MAX_ITEMS] if isinstance(item, Mapping)]
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

    def check_claims(self, evidence: Iterable[Mapping[str, Any]] | Mapping[str, Any], claims: Iterable[Any]) -> tuple[GuardWarning, ...]:
        if isinstance(evidence, Mapping):
            evidence = evidence.get("evidence") or evidence.get("results") or ()
        authoritative: dict[str, Mapping[str, Any]] = {}
        for item in list(evidence)[:_MAX_ITEMS]:
            if not isinstance(item, Mapping) or str(item.get("source", "")).lower() in {"model", "llm", "generated"}:
                continue
            authoritative[self._evidence_id(item)] = item
        warnings: list[GuardWarning] = []
        for claim in list(claims)[:_MAX_ITEMS]:
            if isinstance(claim, Mapping):
                text = _text(claim.get("claim") or claim.get("text"), 400)
                ids = _tuple(claim.get("evidence_ids"))
            else:
                text, ids = _text(claim, 400), ()
            if not ids or any(evidence_id not in authoritative for evidence_id in ids):
                warnings.append(GuardWarning("warning", "unknown_claim", f"unsupported claim: {text}", (), (), "verify the claim with deterministic repository evidence"))
        return tuple(warnings)

    def check_drift(self, request: ConsistencyRequest, contract: GoalContract, changed_paths: Iterable[str], diff: Mapping[str, Any] | str | None) -> tuple[GuardWarning, ...]:
        warnings: list[GuardWarning] = []
        paths = list(_tuple(changed_paths))
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
                paths = list(self.repository_tools.git_snapshot(request.root).changed_paths)
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
        for decision in list(decisions)[:_MAX_ITEMS]:
            if not isinstance(decision, Mapping):
                continue
            candidate_id = str(decision.get("candidate_id", ""))
            action = str(decision.get("decision", decision.get("action", ""))).lower()
            reason = str(decision.get("reason", "")).strip()
            if candidate_id not in candidate_ids:
                warnings.append(GuardWarning("warning", "unknown_reuse_candidate", "reuse decision references no deterministic candidate", (), tuple(paths), "refresh deterministic reuse candidates"))
            elif action in {"reject", "rejected", "new"} and not reason:
                warnings.append(GuardWarning("warning", "reuse_rejection_reason_required", "rejected reuse candidate needs a concise reason", (), tuple(paths), "record why reuse violates the contract or boundary"))
        diff_text = diff if isinstance(diff, str) else str(diff_data.get("diff", ""))
        added_symbols = [match.group(1) for line in _text(diff_text, 12000).splitlines() if (match := _PUBLIC_SYMBOL.match(line))]
        if added_symbols and any(candidate.suitable for candidate in candidates):
            warnings.append(GuardWarning("boundary", "new_public_symbol_despite_reuse", "new public symbol added while a suitable reuse candidate exists", (), tuple(paths), "approve the boundary or reuse the existing symbol", True))
        if request.changed_paths:
            requested = set(request.changed_paths)
            outside = tuple(path for path in paths if path not in requested)
            if outside:
                warnings.append(GuardWarning("warning", "scope_drift", "changed paths exceed the request scope", (), outside, "explain the scope expansion or narrow the change"))
        evidence = diff_data.get("evidence") or ()
        if evidence:
            try:
                checked = self.repository_tools.verify_evidence(request.root, list(evidence)[:_MAX_ITEMS])
                if checked.get("stale"):
                    warnings.append(GuardWarning("warning", "stale_evidence", "one or more evidence slices are stale", (), tuple(paths), "refresh evidence at the current repository revision"))
            except Exception:
                pass
        return tuple(warnings[:_MAX_ITEMS])
