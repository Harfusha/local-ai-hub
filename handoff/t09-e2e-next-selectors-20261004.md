# T09 next root-current selectors — 2026-10-04

No tests run. Selectors below are a proposed serial queue for T20; require fresh per-selector GO and matching pre-run hashes. All CPU-only: temporary SQLite/Git fixtures, no model/GPU/network use.

Root checkout: `C:\Users\Adam\.local-ai-hub`; HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.

## 1. Orchestrator receipt gate

```powershell
python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_work_orchestrator.py::test_stale_verification_receipt_cannot_complete_work_order
```

- Selector file `tests/test_work_orchestrator.py` SHA-256: `ABDA9C9A72F325E1B5534C2C0BD34C2482C2DB567E2AAC124A8C7F2D7DEDC724` (root modified; candidate selector is older and lacks this case).
- Dependencies: `src/local_ai_hub/work_orchestrator.py` SHA-256 `CBCCC1480BD9B9BF1BAB6EDCF41573E7390A61147F23A2946DE3D48BDDE78337`; `src/local_ai_hub/agent_verification.py` SHA-256 `2604A542C491AEE46EF1D653642247EB615D081D2F97976C105C0FAB276EF9D7`.
- Companion composition selector, same file/hash: `tests/test_work_orchestrator.py::test_orchestrator_uses_verification_store_from_services`.

## 2. Worktree ownership and dirty cleanup

```powershell
python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_verified_handoff.py::test_task_cleanup_checks_owner_and_preserves_dirty_worktree
```

- Selector file `tests/test_verified_handoff.py` SHA-256: `85AD97AC8D5FF6C0814B78CE5B43E21E2617B778408BFC761735189B4E9A0E58` (root untracked; candidate file absent).
- Dependencies: `src/local_ai_hub/agent_tasks.py` SHA-256 `5CE57D0EF0B7A17992F604AB67390E481702B0F51393C375102623475FCF280A`; `src/local_ai_hub/worktrees.py` SHA-256 `3EEFCCC300F9D3AF639746CB1E1B518DB9491333BDF30B3D9624BFBB1259FC45`.
- Covers task/owner/repository/worktree/branch/TTL metadata, foreign actor denial, and dirty edit preservation.

## 3. Foreign worktree and canceled handoff negatives

Same selector file/hash as above; CPU-only temporary Git/SQLite fixtures.

```powershell
python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_verified_handoff.py::test_task_cleanup_rejects_foreign_worktree_path
python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_verified_handoff.py::test_task_cleanup_rejects_same_repo_foreign_worktree_retarget
python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_verified_handoff.py::test_cancelled_task_cannot_reach_completed_handoff
```

## Ownership boundary

Root orchestrator/worktree code and test files are dirty; lease remains unverified. These are proposal-only selectors, not authorization to run. T16's `tests/test_task_worktree_cleanup_contract.py::test_worktree_cleanup_requires_registered_worktree_id` (root SHA-256 `A6FEC7708057BA5F31FE0777B791058ED2A6ADB13700C3E869EBDDC4579BCE19`) stays outside T09 queue pending T16 ownership release. No root write.