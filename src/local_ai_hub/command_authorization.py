from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
import math
import ntpath
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from .command_models import CommandInvocation
from .process_utils import hidden_run_kwargs
from .state_paths import configured_state_dir
from .work_fencing import WorkAttemptFence

class CommandAuthorizationMixin:
    def _assert_work_attempt_fence(
        self,
        work_attempt_fence: WorkAttemptFence | None,
        *,
        task_id: str,
        resource: str | Path,
    ) -> dict[str, Any]:
        payload = self._work_attempt_fence_payload(work_attempt_fence)
        if payload["work_id"] != task_id:
            raise ValueError("work attempt fence does not belong to this task")
        registered_root = Path(payload["resource"]).expanduser().resolve(strict=True)
        requested_root = Path(resource).expanduser().resolve(strict=True)
        if os.path.normcase(str(registered_root)) != os.path.normcase(str(requested_root)):
            raise ValueError("work attempt fence resource does not match command worktree")
        store = self.fencing_lease_store
        if not callable(getattr(store, "assert_attempt_current", None)):
            raise ValueError("authoritative work attempt fence store is unavailable")
        store.assert_attempt_current(work_attempt_fence)
        return payload
    @contextmanager
    def _fenced_transaction_commit(
        self,
        work_attempt_fence: WorkAttemptFence,
        *,
        task_id: str,
        source: Path,
        paths: list[str],
        owner_id: str,
        namespace_kwargs: dict[str, str] | None = None,
    ):
        payload = self._assert_work_attempt_fence(
            work_attempt_fence, task_id=task_id, resource=source
        )
        store = self.fencing_lease_store
        lease = store.acquire(
            str(source), owner_id, paths, ttl_seconds=300.0,
            attempt=work_attempt_fence,
            **(namespace_kwargs or {}),
        )
        try:
            with store.commit_guard(lease, paths):
                store.assert_current(lease, actual_paths=paths)
                yield lease, payload
        finally:
            try:
                store.release(lease)
            except Exception:
                pass
    def _reject_git_worktree_overrides(
        self,
        command: str | CommandInvocation | None,
        cwd: Path,
        registered: Path,
    ) -> str | None:
        git_path_keys = {
            "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
            "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        }

        def is_git_override(key: str) -> bool:
            normalized = key.upper()
            return normalized in git_path_keys or normalized.startswith("GIT_CONFIG_")

        if command is None:
            return None
        if isinstance(command, CommandInvocation):
            tokens = list(command.argv)
            if any(is_git_override(key) for key in (getattr(command, "env", None) or {})):
                return "mutating Git command cannot override repository paths"
            token_groups = [tokens]
        elif isinstance(command, str):
            assignment = re.compile(
                r"(?i)(?:^|[\s;&|])(?:(?:export|set)\s+)?(?:\$env:)?"
                r"(GIT_DIR|GIT_WORK_TREE|GIT_INDEX_FILE|GIT_COMMON_DIR|GIT_OBJECT_DIRECTORY|"
                r"GIT_ALTERNATE_OBJECT_DIRECTORIES|GIT_CONFIG_[A-Z0-9_]+)"
                r"\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s;&|]+)"
            )
            if assignment.search(command):
                return "mutating Git command cannot override repository paths"
            segments = [command]
            for delimiter in (";", "&&", "||", "|"):
                segments = [
                    part
                    for segment in segments
                    for _found, part in self._split_outside_quotes(segment, (delimiter,))
                ]
            token_groups = [self._tokens(segment) for segment in segments]
        else:
            return "mutating command could not be checked against its task worktree"

        for tokens in token_groups:
            if not tokens:
                continue
            if any(
                re.fullmatch(r"(?i)GIT_[A-Z0-9_]+=.+", token)
                for token in tokens
            ):
                return "mutating Git command cannot override repository paths"
            executable = ntpath.basename(tokens[0].strip('"').replace("/", "\\")).lower()
            if re.sub(r"\.(exe|cmd|bat|ps1|sh)$", "", executable) != "git":
                continue
            index = 1
            while index < len(tokens):
                argument = tokens[index]
                lowered = argument.lower()
                if lowered in {"--git-dir", "--work-tree", "--separate-git-dir"} or any(
                    lowered.startswith(f"{option}=")
                    for option in ("--git-dir", "--work-tree", "--separate-git-dir")
                ):
                    return "mutating Git command cannot override repository paths"
                if lowered.startswith("--config-env=") and lowered.split("=", 2)[1] in {
                    "core.worktree", "core.indexfile",
                }:
                    return "mutating Git command cannot override repository paths"
                if lowered == "--config-env" and index + 1 < len(tokens):
                    setting = tokens[index + 1].split("=", 1)[0].lower()
                    if setting in {"core.worktree", "core.indexfile"}:
                        return "mutating Git command cannot override repository paths"
                    index += 2
                    continue
                if argument == "-c" and index + 1 < len(tokens):
                    setting = tokens[index + 1].split("=", 1)[0].lower()
                    if setting in {"core.worktree", "core.indexfile"}:
                        return "mutating Git command cannot override repository paths"
                    index += 2
                    continue
                if argument == "-c":
                    return "mutating Git command has an incomplete configuration override"
                if argument.startswith("-c") and len(argument) > 2:
                    setting = argument[2:].split("=", 1)[0].lower()
                    if setting in {"core.worktree", "core.indexfile"}:
                        return "mutating Git command cannot override repository paths"
                    index += 1
                    continue
                target_value = ""
                if argument == "-C":
                    if index + 1 >= len(tokens):
                        return "mutating Git command has an incomplete worktree override"
                    target_value = tokens[index + 1]
                    index += 2
                elif argument.startswith("-C") and len(argument) > 2:
                    target_value = argument[2:]
                    index += 1
                else:
                    index += 1
                    continue
                target = Path(target_value).expanduser()
                if not target.is_absolute():
                    target = cwd / target
                resolved = target.resolve(strict=False)
                common = os.path.commonpath([str(resolved), str(registered)])
                if os.path.normcase(common) != os.path.normcase(str(registered)):
                    return "mutating Git command cannot target paths outside the registered task worktree"
        return None
    def _require_task_worktree(
        self,
        task_id: str,
        cwd: str | Path,
        command: str | CommandInvocation | None = None,
        *,
        require_git_identity: bool = False,
    ) -> str | None:
        if not task_id or self.task_store is None:
            return "mutating commands require a registered task-owned worktree"
        try:
            task = self.task_store.get(task_id)
            checkpoint = getattr(task, "checkpoint", None)
            state_data = getattr(checkpoint, "state_data", {})
            worktree = state_data.get("worktree") if isinstance(state_data, Mapping) else None
            registered_path = worktree.get("worktree_path") if isinstance(worktree, Mapping) else None
            if not registered_path or worktree.get("success") is not True:
                return "mutating commands require a registered task-owned worktree"
            requested = Path(cwd).expanduser().resolve(strict=True)
            if isinstance(command, CommandInvocation) and command.cwd:
                invocation_cwd = Path(command.cwd).expanduser().resolve(strict=True)
                if os.path.normcase(str(invocation_cwd)) != os.path.normcase(str(requested)):
                    return "structured command cwd must match the broker cwd"
                requested = invocation_cwd
            registered = Path(str(registered_path)).expanduser().resolve(strict=True)
            if not requested.is_dir() or not registered.is_dir():
                return "registered task worktree is unavailable"
            common = os.path.commonpath([str(requested), str(registered)])
            if os.path.normcase(common) != os.path.normcase(str(registered)):
                return "mutating command cwd must be inside the registered task-owned worktree"
            override_error = self._reject_git_worktree_overrides(command, requested, registered)
            if override_error:
                return override_error
            if require_git_identity:
                identity_error = self._validate_registered_git_worktree(registered, worktree)
                if identity_error:
                    return identity_error
            return None
        except Exception:
            return "registered task worktree could not be verified"
    def _transaction_namespace_kwargs(self, source: Path, fencing_store: Any) -> dict[str, str]:
        try:
            from .project_config import resolve_project_context

            coordination_id = resolve_project_context(
                source, configured_state_dir(self.config)
            ).coordination_id
        except Exception as exc:
            raise RuntimeError("project coordination namespace could not be resolved") from exc
        if not isinstance(coordination_id, str) or not coordination_id.strip():
            raise RuntimeError("project coordination namespace is required")
        return {"coordination_id": coordination_id}
    def _validate_registered_git_worktree(
        self,
        registered: Path,
        worktree: Mapping[str, Any],
    ) -> str | None:
        repo_root_value = worktree.get("repo_root")
        expected_branch = worktree.get("branch")
        if not isinstance(repo_root_value, str) or not repo_root_value or not isinstance(expected_branch, str) or not expected_branch:
            return "registered task worktree identity metadata is unavailable"

        repo_root = Path(repo_root_value).expanduser().resolve(strict=True)
        clean_env = {
            key: value for key, value in os.environ.items()
            if not key.upper().startswith("GIT_")
        }

        def git_output(cwd: Path, *args: str) -> str | None:
            try:
                result = subprocess.run(
                    ["git", "-C", str(cwd), *args],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env=clean_env,
                    check=False,
                    **hidden_run_kwargs(),
                )
            except (OSError, subprocess.SubprocessError):
                return None
            return result.stdout.strip() if result.returncode == 0 else None

        registered_top = git_output(registered, "rev-parse", "--show-toplevel")
        registered_common = git_output(registered, "rev-parse", "--git-common-dir")
        registered_branch = git_output(registered, "symbolic-ref", "--quiet", "--short", "HEAD")
        expected_top = git_output(repo_root, "rev-parse", "--show-toplevel")
        expected_common = git_output(repo_root, "rev-parse", "--git-common-dir")
        worktrees = git_output(repo_root, "worktree", "list", "--porcelain")
        if not all((registered_top, registered_common, registered_branch, expected_top, expected_common, worktrees)):
            return "registered task worktree Git identity could not be verified"

        def resolve_git_path(value: str, base: Path) -> Path:
            path = Path(value)
            return (path if path.is_absolute() else base / path).resolve(strict=True)

        registered_top_path = Path(registered_top).resolve(strict=True)
        expected_top_path = Path(expected_top).resolve(strict=True)
        registered_common_path = resolve_git_path(registered_common, registered)
        expected_common_path = resolve_git_path(expected_common, repo_root)
        if (
            os.path.normcase(str(registered_top_path)) != os.path.normcase(str(registered))
            or os.path.normcase(str(expected_top_path)) != os.path.normcase(str(repo_root))
            or os.path.normcase(str(registered_common_path)) != os.path.normcase(str(expected_common_path))
            or registered_branch != expected_branch
        ):
            return "registered task worktree Git identity changed"

        current: dict[str, str] = {}
        for line in (*worktrees.splitlines(), ""):
            if not line:
                if (
                    current.get("worktree")
                    and os.path.normcase(str(Path(current["worktree"]).resolve(strict=False)))
                    == os.path.normcase(str(registered))
                    and current.get("branch") == f"refs/heads/{expected_branch}"
                ):
                    return None
                current = {}
            elif line.startswith("worktree "):
                current["worktree"] = line[len("worktree "):]
            elif line.startswith("branch "):
                current["branch"] = line[len("branch "):]
        return "registered task worktree is not present in its source Git worktree registry"
    @staticmethod
    def _work_attempt_fence_payload(work_attempt_fence: WorkAttemptFence) -> dict[str, Any]:
        if not isinstance(work_attempt_fence, WorkAttemptFence):
            raise ValueError("work attempt fence has an invalid type")
        fields = {
            "resource": work_attempt_fence.resource,
            "work_id": work_attempt_fence.work_id,
            "attempt_id": work_attempt_fence.attempt_id,
            "owner_id": work_attempt_fence.owner_id,
            "fencing_token": work_attempt_fence.fencing_token,
            "expires_at": work_attempt_fence.expires_at,
        }
        if (
            any(not isinstance(fields[name], str) or not fields[name] for name in (
                "resource", "work_id", "attempt_id", "owner_id",
            ))
            or type(fields["fencing_token"]) is not int
            or fields["fencing_token"] <= 0
            or not isinstance(fields["expires_at"], (int, float))
            or not math.isfinite(float(fields["expires_at"]))
        ):
            raise ValueError("work attempt fence is malformed")
        return fields
    def authorize_auxiliary_action(self, action: str, *, endpoint: str = "", task_id: str = "") -> dict[str, Any]:
        """Authorize auxiliary process actions at their final broker boundary."""
        from .agent_policy import AUXILIARY_ACTION_POLICIES, ActionRequest, CapabilityGrant, RiskClass

        action_name = action if type(action) is str else ""
        policy_config = self.config.get("agent_policy", {})
        policy_enabled = isinstance(policy_config, dict) and bool(policy_config.get("enabled", True))
        developer_authorized = (
            policy_enabled
            and isinstance(policy_config, dict)
            and bool(policy_config.get("allow_developer_authorized_mutations", False))
        )
        if action_name not in AUXILIARY_ACTION_POLICIES:
            return {
                "success": False,
                "allowed": False,
                "reason": f"unknown auxiliary action '{action_name}' denied",
                "owner": "agent_policy",
                "side_effect_class": "unknown",
                "terminal": True,
                "retryable": False,
            }

        engine = self.policy_engine
        if engine is None or not callable(getattr(engine, "authorize", None)):
            return {
                "success": False,
                "allowed": False,
                "requires_approval": True,
                "reason": "auxiliary action policy engine unavailable",
                "owner": "agent_policy",
                "side_effect_class": AUXILIARY_ACTION_POLICIES.get(action_name, (None, "unknown"))[1],
                "terminal": True,
                "retryable": False,
            }
        task = None
        if task_id:
            if self.task_store is None:
                return {
                    "success": False,
                    "allowed": False,
                    "reason": "task context unavailable for auxiliary action",
                    "owner": "agent_policy",
                    "side_effect_class": AUXILIARY_ACTION_POLICIES[action_name][1],
                    "terminal": True,
                    "retryable": False,
                }
            try:
                task = self.task_store.get(task_id)
            except Exception:
                task = None
            if task is None or str(getattr(task, "task_id", "")) != task_id:
                return {
                    "success": False,
                    "allowed": False,
                    "reason": "task context missing or mismatched for auxiliary action",
                    "owner": "agent_policy",
                    "side_effect_class": AUXILIARY_ACTION_POLICIES[action_name][1],
                    "terminal": True,
                    "retryable": False,
                }

        grant = None
        if developer_authorized:
            grant = CapabilityGrant(
                grant_id="configured-local-development-policy",
                allowed=frozenset({action_name}),
            )
        decision = engine.authorize(
            ActionRequest(
                action=action_name,
                risk_class=RiskClass.READ,
                details={
                    "auxiliary_action": True,
                    "policy_enabled": policy_enabled,
                    "endpoint": str(endpoint),
                },
            ),
            task=task,
            grant=grant,
        )
        result = decision.to_dict()
        result.update({
            "success": bool(decision.allowed),
            "allowed": bool(decision.allowed),
            "terminal": not bool(decision.allowed),
            "retryable": False,
        })
        if not decision.allowed:
            result["error"] = decision.reason
        return result
    def increase_task_budget(
        self, task_id: str, *, root: str, reason: str, limits: Mapping[str, Any],
        authorization_actor: str, authorization_permissions: frozenset[str],
        response_budget_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Ordinary authorized write, separate from exhausted execution admission.

        Authorization values come from the loopback transport context, never
        request fields or the advisory agent profile header.
        """
        if (type(authorization_actor) is not str
                or type(authorization_permissions) is not frozenset
                or authorization_actor != "local" or authorization_permissions):
            raise PermissionError("task budget write authorization required")
        if self.task_store is None or self.policy_engine is None:
            raise RuntimeError("task budget authority unavailable")
        from .agent_tasks import _canonical_repository_root, _task_matches_scope

        canonical = _canonical_repository_root(root)
        task = self.task_store.get(task_id)
        if task is None:
            raise KeyError(task_id)
        if not _task_matches_scope(task, canonical, task_id):
            raise PermissionError("task repository scope mismatch")
        return self.policy_engine.increase_task_budget(
            task_id, actor=task.owner, repo_root=canonical, reason=reason,
            limits=limits, authorization_actor=authorization_actor,
            response_budget_tokens=response_budget_tokens,
        )
    def repair_task_session(
        self, task_id: str, *, root: str, session_id: str, reason: str,
        authorization_actor: str, authorization_permissions: frozenset[str],
        response_budget_tokens: int | None = None,
    ) -> Any:
        """Repair only a sessionless task through verified write authority."""
        if (type(authorization_actor) is not str
                or type(authorization_permissions) is not frozenset
                or authorization_actor != "local" or authorization_permissions):
            raise PermissionError("task session write authorization required")
        if self.task_store is None:
            raise RuntimeError("task authority unavailable")
        from .agent_tasks import _canonical_repository_root, _task_matches_scope

        canonical = _canonical_repository_root(root)
        task = self.task_store.get(task_id)
        if task is None:
            raise KeyError(task_id)
        if not _task_matches_scope(task, canonical, task_id):
            raise PermissionError("task repository scope mismatch")
        return self.task_store.repair_missing_session(
            task_id, session_id=session_id, repo_root=canonical, actor=task.owner, reason=reason,
            authorization_actor=authorization_actor, response_budget_tokens=response_budget_tokens,
        )
    def set_bounded_work_authorizer(self, authorizer: Any) -> None:
        self.bounded_work_authorizer = authorizer if callable(authorizer) else None
    def set_fencing_lease_store(self, fencing_lease_store: Any) -> None:
        self.fencing_lease_store = fencing_lease_store
    def set_incident_store(self, incident_store: Any) -> None:
        self.incident_store = incident_store
    def set_policy_engine(self, policy_engine: Any) -> None:
        self.policy_engine = policy_engine
    def set_task_store(self, task_store: Any) -> None:
        self.task_store = task_store
