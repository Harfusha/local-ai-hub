from __future__ import annotations

import difflib
import hashlib
from pathlib import Path


ROOT = Path(r"C:\Users\Adam\.local-ai-hub")
CANDIDATE = Path(__file__).resolve().parents[2]
RELATIVE_PATH = "src/local_ai_hub/rag.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 anchor, got {count}")
    return text.replace(old, new, 1)


def replace_in_segment(
    text: str, start_marker: str, end_marker: str, old: str, new: str, label: str
) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[:start] + replace_once(text[start:end], old, new, label) + text[end:]


def build() -> tuple[bytes, bytes, str]:
    root_path = ROOT / RELATIVE_PATH
    candidate_path = CANDIDATE / RELATIVE_PATH
    root_bytes = root_path.read_bytes()
    root_test_path = ROOT / "tests/test_rag_hybrid.py"
    candidate_test_path = CANDIDATE / "tests/test_rag_hybrid.py"
    root_test_bytes = root_test_path.read_bytes()
    original = root_bytes.decode("utf-8").replace("\r\n", "\n")
    candidate = candidate_path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    root_test = root_test_bytes.decode("utf-8").replace("\r\n", "\n")
    candidate_test = candidate_test_path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    updated = original

    key_start = candidate.index("    @staticmethod\n    def _project_root_identity(")
    key_end = candidate.index("    @staticmethod\n    def _workspace_read_uncertainty_key(", key_start)
    project_key = candidate[key_start:key_end]
    updated = replace_once(
        updated,
        "    @staticmethod\n    def _workspace_read_uncertainty_key(",
        project_key + "    @staticmethod\n    def _workspace_read_uncertainty_key(",
        "project config key",
    )

    # The root-current module needs the two small policy error/errno declarations
    # that accompany the root-bound digest and fail-closed stat handling.
    updated = replace_once(
        updated,
        "import math\nimport os\n",
        "import math\nimport os\nimport errno\n",
        "errno import",
    )
    policy_error = candidate[
        candidate.index("class ProjectPolicySyncError(RuntimeError):"):
        candidate.index("\n\ndef _reverse_text_order", candidate.index("class ProjectPolicySyncError(RuntimeError):"))
    ]
    updated = replace_once(
        updated,
        "_INDEX_EMBED_BATCH_SIZE = 64\n",
        "_INDEX_EMBED_BATCH_SIZE = 64\n\n\n" + policy_error + "\n",
        "policy sync exception",
    )

    helper_start = candidate.index("    def _sync_workspace_project_policy_identity(")
    helper_end = candidate.index("    def _workspace_index_generation(", helper_start)
    policy_helper = candidate[helper_start:helper_end]
    # Root-current RAG already owns thin wrappers around the project_config API;
    # keep the T11 helper on those wrappers instead of importing candidate-only adapter code.
    policy_helper = policy_helper.replace(
        'rag_enabled = phase_allowed(project_context, "rag")',
        'rag_enabled = self._project_phase_allowed(project_context, "rag")',
    )
    policy_helper = policy_helper.replace(
        "                kind = custom_extension_kind(project_context, candidate)",
        "                api = self.project_config_api()\n                kind = api.custom_extension_kind(candidate.name, settings) if api is not None else None",
    )
    policy_helper = policy_helper.replace(
        "                allowed, kind = path_allowed(\n                    root_path, candidate, project_context, phase=\"rag\",\n                    size_bytes=int(stat.st_size),\n                )",
        "                allowed, kind = self._project_path_decision(\n                    root_path, candidate, project_context, phase=\"rag\",\n                    size_bytes=int(stat.st_size),\n                )",
    )
    if any(
        marker in policy_helper
        for marker in (
            "rag_enabled = phase_allowed(",
            "kind = custom_extension_kind(",
            "allowed, kind = path_allowed(",
        )
    ):
        raise RuntimeError("candidate-only project_policy_adapter call remained in root helper")
    updated = replace_once(
        updated,
        "    def _workspace_index_generation(",
        policy_helper + "    def _workspace_index_generation(",
        "project policy helper",
    )

    # Catch policy-sync failures at all public indexing entry points so callers
    # receive retryability instead of an uncaught filesystem/config exception.

    updated = replace_in_segment(
        updated,
        "    def _index_locked(",
        "    def prune_missing(",
        "    def _index_locked(self, root: str, tenant: str, workspace: str | None = None) -> dict[str, Any]:\n",
        "    def _index_locked(\n        self, root: str, tenant: str, workspace: str | None = None, *,\n        _space_override: str | None = None, _identity_retry: bool = False,\n    ) -> dict[str, Any]:\n",
        "atomic signature",
    )
    updated = replace_in_segment(
        updated,
        "    def _index_locked(",
        "    def prune_missing(",
        "        scope_key = self._scope_key(tenant)\n        embedding_space = self._embedding_space_id()\n",
        "        scope_key = self._scope_key(tenant)\n        self._sync_workspace_project_policy_identity(root_path, scope_key, workspace, project_context)\n        embedding_space = _space_override or self._embedding_space_id()\n",
        "atomic policy and identity setup",
    )
    updated = replace_in_segment(
        updated,
        "    def _index_locked(",
        "    def prune_missing(",
        "                observed_embedding_space = batch_space\n                embedding_space = batch_space\n",
        "                observed_embedding_space = batch_space\n                if batch_space != embedding_space:\n                    if _identity_retry:\n                        return {\"success\": False, \"error\": \"embedding identity changed during atomic index retry\", \"retryable\": True}\n                    if old_chunk_rows or reused_chunks:\n                        return self._index_locked(\n                            str(root_path), tenant, workspace,\n                            _space_override=batch_space, _identity_retry=True,\n                        )\n                    embedding_space = batch_space\n",
        "atomic output-space retry",
    )

    start = updated.index("    def index_paths_step(")
    end = updated.index("    def index_step(", start)
    segment = updated[start:end]
    segment = replace_once(
        segment,
        "        deleted_paths: list[str] | None = None,\n    ) -> dict[str, Any]:\n",
        "        deleted_paths: list[str] | None = None,\n        *, _space_override: str | None = None, _identity_retry: bool = False,\n    ) -> dict[str, Any]:\n",
        "incremental signature",
    )
    segment = replace_once(
        segment,
        "        embedding_space = self._embedding_space_id()\n",
        "        embedding_space = _space_override or self._embedding_space_id()\n",
        "incremental space override",
    )
    segment = replace_once(
        segment,
        "        with self._get_workspace_lock(workspace):\n",
        "        with self._get_workspace_lock(workspace):\n            self._sync_workspace_project_policy_identity(\n                root_path, scope_key, workspace, project_context\n            )\n",
        "incremental policy sync",
    )
    segment = replace_once(
        segment,
        "            self._sync_workspace_project_policy_identity(\n                root_path, scope_key, workspace, project_context\n            )\n",
        "            try:\n                self._sync_workspace_project_policy_identity(\n                    root_path, scope_key, workspace, project_context\n                )\n            except ProjectPolicySyncError as exc:\n                return {\"success\": False, \"error\": str(exc), \"retryable\": exc.retryable}\n",
        "incremental policy sync failure",
    )
    segment = replace_once(
        segment,
        "                    if batch_embedding_space is None:\n                        batch_embedding_space = current_space\n                        embedding_space = batch_embedding_space\n                        embedding_space_resolved = True\n",
        "                    if batch_embedding_space is None:\n                        batch_embedding_space = current_space\n                        if current_space != embedding_space:\n                            if _identity_retry and reused_chunks:\n                                return {\"success\": False, \"error\": \"embedding identity changed during RAG path retry\", \"retryable\": True}\n                            if reused_chunks:\n                                return self.index_paths_step(\n                                    str(root_path), tenant, workspace, paths,\n                                    should_yield=should_yield, content_overrides=content_overrides,\n                                    deleted_paths=deleted_paths, _space_override=current_space,\n                                    _identity_retry=True,\n                                )\n                            embedding_space = batch_embedding_space\n                        embedding_space_resolved = True\n",
        "incremental output-space retry",
    )
    updated = updated[:start] + segment + updated[end:]

    # _search_uncached is the final method in this RAGStore implementation.
    start = updated.index("    def _search_uncached(")
    segment = updated[start:]
    segment = replace_once(
        segment,
        "        embedding_space = self._embedding_space_id(query_result)\n        fallbacks: list[str] = []\n",
        "        embedding_space = self._embedding_space_id(query_result)\n        embedding_space_resolved = self._embedding_space_is_resolved(query_result)\n        stored_embedding_space: str | None = None\n        stored_embedding_space_read = False\n        fallbacks: list[str] = []\n",
        "search identity setup",
    )
    segment = replace_once(
        segment,
        "            ).fetchone() is not None\n\n        if has_stale_embedding_rows:\n",
        "            ).fetchone() is not None\n            if embedding_space_resolved:\n                try:\n                    stored_embedding_space = self._stored_workspace_embedding_space(con, scope_key, workspace)\n                    stored_embedding_space_read = True\n                except sqlite3.Error:\n                    pass\n\n        if embedding_space_resolved:\n            try:\n                if not stored_embedding_space_read or stored_embedding_space != embedding_space:\n                    with closing(self._connect()) as con:\n                        con.execute(\"BEGIN IMMEDIATE\")\n                        if self._stored_workspace_embedding_space(con, scope_key, workspace) != embedding_space:\n                            self._store_workspace_embedding_space(con, scope_key, workspace, embedding_space)\n                        con.commit()\n            except sqlite3.Error:\n                fallbacks.append(\"embedding_space_metadata\")\n\n        if has_stale_embedding_rows:\n",
        "search metadata persistence",
    )
    updated = updated[:start] + segment

    # Reuse candidate's T11-owned policy-aware prune implementation.
    start = updated.index("    def prune_missing(")
    end = updated.index("    def remove_paths(", start)
    candidate_start = candidate.index("    def prune_missing(")
    candidate_end = candidate.index("    def remove_paths(", candidate_start)
    updated = updated[:start] + candidate[candidate_start:candidate_end] + updated[end:]

    start = updated.index("    def index_step(")
    end = updated.find("\n    def ", start + 8)
    if end < 0:
        end = len(updated)
    segment = updated[start:end]
    segment = replace_once(
        segment,
        "        with self._get_workspace_lock(workspace):\n            scope_key = self._scope_key(tenant)\n            embedding_space = self._embedding_space_id()\n",
        "        with self._get_workspace_lock(workspace):\n            scope_key = self._scope_key(tenant)\n            self._sync_workspace_project_policy_identity(\n                root_path, scope_key, workspace, project_context\n            )\n            embedding_space = self._embedding_space_id()\n",
        "index-step policy sync",
    )
    segment = replace_once(
        segment,
        "            self._sync_workspace_project_policy_identity(\n                root_path, scope_key, workspace, project_context\n            )\n",
        "            try:\n                self._sync_workspace_project_policy_identity(\n                    root_path, scope_key, workspace, project_context\n                )\n            except ProjectPolicySyncError as exc:\n                return {\"success\": False, \"error\": str(exc), \"retryable\": exc.retryable}\n",
        "index-step policy sync failure",
    )
    segment = replace_once(
        segment,
        "            remaining = max(0, len(pending) - len(selected))\n            return {\n",
        "            completed_paths = {\n                str(path).replace(\"\\\\\\\\\", \"/\") for path in staged.get(\"processed_paths\", [])\n            }\n            completed_paths.update(\n                str(path).replace(\"\\\\\\\\\", \"/\") for path in staged.get(\"deleted_paths\", [])\n            )\n            remaining_paths = set(pending) - completed_paths\n            remaining = len(remaining_paths)\n            return {\n",
        "index-step pending accounting",
    )
    updated = updated[:start] + segment + updated[end:]

    newline = "\r\n" if b"\r\n" in root_bytes else "\n"
    postimage = updated.replace("\n", newline).encode("utf-8")
    test_updated = root_test
    test_updated = replace_once(
        test_updated,
        "    key = store._workspace_project_config_key(scope_key, workspace)\n",
        "    key = store._workspace_project_config_key(\n        scope_key, workspace, store._project_root_identity(root)\n    )\n",
        "root policy test key",
    )
    test_block_start = candidate_test.index(
        "def test_project_policy_identity_does_not_commit_stale_concurrent_snapshot("
    )
    test_block_end = candidate_test.index(
        "def test_index_paths_step_retries_uncertain_only_publish_lock(", test_block_start
    )
    test_block = candidate_test[test_block_start:test_block_end]
    decision_start = test_block.index("    if hasattr(store, \"_project_path_decision\"):")
    decision_end = test_block.index("    outcome = {}", decision_start)
    test_block = test_block[:decision_start] + '''    original_path_decision = store._project_path_decision

    def pause_stale_scan(scan_root, path, context, *, phase, size_bytes):
        if context.config_digest == stale_context.config_digest:
            entered_scan.set()
            assert release_scan.wait(3)
        return original_path_decision(
            scan_root, path, context, phase=phase, size_bytes=size_bytes
        )

    monkeypatch.setattr(store, "_project_path_decision", pause_stale_scan)
''' + test_block[decision_end:]
    test_updated = replace_once(
        test_updated,
        "def test_index_paths_step_retries_uncertain_only_publish_lock(",
        test_block + "def test_index_paths_step_retries_uncertain_only_publish_lock(",
        "new policy regression tests",
    )
    test_updated = replace_once(
        test_updated,
        "import sqlite3\n",
        "import sqlite3\nimport errno\nimport threading\n\nimport pytest\n",
        "policy regression test imports",
    )

    diffs = []
    diffs.append("diff --git a/" + RELATIVE_PATH + " b/" + RELATIVE_PATH + "\n" + "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile="a/" + RELATIVE_PATH,
            tofile="b/" + RELATIVE_PATH,
            n=3,
        )
    ))
    diffs.append("diff --git a/tests/test_rag_hybrid.py b/tests/test_rag_hybrid.py\n" + "".join(
        difflib.unified_diff(
            root_test.splitlines(keepends=True),
            test_updated.splitlines(keepends=True),
            fromfile="a/tests/test_rag_hybrid.py",
            tofile="b/tests/test_rag_hybrid.py",
            n=3,
        )
    ))
    test_postimage = test_updated.replace("\n", newline).encode("utf-8")
    return postimage, test_postimage, "".join(diffs)


def main() -> None:
    postimage, test_postimage, diff = build()
    output_dir = Path(__file__).parent
    patch_path = output_dir / "t11-root-current-owned-fixes-20261005.patch"
    post_path = output_dir / "root-rag-postimage-20261005.py"
    test_post_path = output_dir / "root-rag-test-postimage-20261005.py"
    patch_path.write_text(diff, encoding="utf-8", newline="")
    post_path.write_bytes(postimage)
    test_post_path.write_bytes(test_postimage)
    print(f"root_pre_sha256={hashlib.sha256((ROOT / RELATIVE_PATH).read_bytes()).hexdigest().upper()}")
    print(f"root_post_sha256={hashlib.sha256(postimage).hexdigest().upper()}")
    print(f"root_test_post_sha256={hashlib.sha256(test_postimage).hexdigest().upper()}")
    print(f"patch_sha256={hashlib.sha256(patch_path.read_bytes()).hexdigest().upper()}")
    print(f"patch_bytes={patch_path.stat().st_size}")
    print(f"patch_path={patch_path}")


if __name__ == "__main__":
    main()
