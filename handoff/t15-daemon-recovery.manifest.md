# T15 daemon recovery handoff

- Scope: POSIX daemon registry PGID persistence and fail-closed leaderless recovery only. Root files were not modified.
- User-approved behavior: persist `process_group_id`; after restart accept a missing leader only when the owned group is safely verified running; otherwise reject recovery. A launch-token member alone is not a safe signal anchor.
- Root HEAD observed: `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.
- Root working `src/local_ai_hub/commands.py` blob used as patch base: `dedfa173bda244c7d6cf7ba11a09deed38a3de7a`.
- T15 candidate `commands.py` blob: `044e74c99e6ccd6ff7afec93cf95eaee63de216b`.
- Patch SHA-256: `ff5eec6c95e38c7d5589283b5f9d7a079b2caad038fbdc044fdce32d1b9c3646`.
- Paths: `src/local_ai_hub/commands.py` only. Patch excludes cache-read and rollback hunks.
- Root preflight: `git -C C:\Users\Adam\.local-ai-hub apply --check C:\Users\Adam\.codex\worktrees\fefe\.local-ai-hub\handoff\t15-daemon-recovery.patch` exited 0. Root command blob remained `dedfa173bda244c7d6cf7ba11a09deed38a3de7a` before and after; no root files were modified. No test run against root.
- Candidate synthetic daemon coverage previously passed 4 tests with 2 platform skips. Linux end-to-end `test_restart_recovers_and_stops_owned_group_after_leader_exits` remains unverified; WSL returned `Wsl/Service/E_UNEXPECTED`. Its test file remains T06-owned and is not included.
- Acceptance: pending successful root preflight, Linux runtime proof, and root validation.

- Security review (read-only thread `01a0eeec-cba9-7780-8e99-f1bda559dc86`): rejected for integration. P1: ownership token is checked before numeric `killpg(PGID, ...)`, leaving a process-group ID reuse race. P2: `/proc` ownership scan has item/byte caps but no deadline. Source check confirmed that `terminate_tree()` skips its `os.kill(pid, ...)` fallback when an explicit PGID is passed; this does not remove the P1 race in numeric group signaling. Patch remains unintegrated pending handle-based termination or another safe anchor design, scan deadline, and Linux runtime proof.

- Independent read-only design review: PGID plus a token-bearing `/proc` member cannot bind a later numeric group signal to the verified group; per-process pidfds alone also cannot safely target a group or close the fork-during-scan race. Safe Linux candidate requires a private per-daemon cgroup v2 anchor: verify member PGID/cgroup, pin its directory, freeze to `cgroup.events:frozen=1` under a monotonic deadline, write `1` to `cgroup.kill`, then wait for `populated=0` under deadline. If cgroup kill is unavailable, only signal pidfds for individually revalidated members while that cgroup remains frozen; missing pidfd, permissions, or identity uncertainty must abort/thaw and report cleanup unconfirmed. No numeric `killpg` fallback. Cgroup delegation/availability and this lifecycle need Linux race/failure-injection runtime evidence; none is available under the current no-engine-start instruction.

- Linux PGID acceptance: BLOCKED by unavailable permitted runtime and unimplemented safe anchor. WSL returns `Wsl/Service/E_UNEXPECTED`; Docker API lacks `dockerDesktopLinuxEngine`. User explicitly directed no Docker Desktop, service, WSL, or other Linux-engine start. Linux end-to-end recovery/stop test therefore remains unrun and unaccepted. The hidden Desktop process started earlier as PID 40404 had already exited; no service was stopped.
