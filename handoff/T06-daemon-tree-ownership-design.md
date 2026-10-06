# T06 daemon tree ownership design

Date: 2026-10-02
Status: Candidate lifecycle selectors passed (3/3); T20 root six-selector batch passed (5 passed, 1 Windows skip). Root structured-argv task-owner/Popen assertion patch is prepared but not yet integrated; POSIX integration remains unverified on this host.

## Goal

After a broker restart, stop a daemon's complete descendant tree only through a stable OS-owned object. Numeric PID or process-group signaling is never a recovery fallback. Unsupported ownership reports an explicit capability error and leaves release acceptance open.

## Windows candidate

- Create one named Job Object per daemon, name derived from its random `daemon_id` in the `Local` namespace.
- Use the process token's default object DACL. Treat name collision as creation failure; never adopt a preexisting job during spawn.
- Create a named Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Keep the process suspended until assigned and persist registry v4 with its name. Then duplicate the Job handle into the daemon process and resume; this process-owned handle keeps the named object open across broker restart. If all broker and daemon handles close, Job close terminates remaining descendants. The restart test reopens the name and stops all Job members. The suspended-child-before-assignment window remains an unresolved release risk.
- Leave breakaway limits disabled so ordinary `CreateProcess` descendants inherit job membership. The contract covers Job members; it does not claim coverage of every process creation mechanism.
- Verify a live recorded PID belongs to that exact job using one opened process handle for both creation identity and membership; reject PID reuse outside the job. If the leader exited, recover only when the named Job Object remains live. Keep its handle on the recovered proxy. Stop only with `TerminateJobObject`, then wait for the job object to signal empty.
- Legacy Windows rows lack stable ownership and are rejected. POSIX registry records retain their task identity for observation; a broker-recovered POSIX daemon remains fail-closed with `tree_control_capability=unsupported` because the persisted PGID is not a live ownership handle.

## POSIX and other platforms

- `pidfd_open` and `pidfd_send_signal` pin one process, not a whole process group. Current project `terminate_tree` uses numeric `killpg`; this is not a safe whole-tree restart mechanism.
- No POSIX supervisor/group-owner is added in this candidate. A daemon owned by the live broker keeps the existing `start_new_session` and `terminate_tree` process-group lifecycle, reported as `tree_control_capability=process_group`; after broker restart, cleanup remains fail-closed and never signals a persisted numeric PID/PGID. Linux/macOS live process-group behavior still requires on-platform acceptance.
- Unknown platforms fail closed with the same visible capability result.

## Remaining acceptance boundary

- Named Job Object descendant/restart and task-owner flow passed the assigned root selector batch. The structured-argv task-owner/Popen assertion is in a separate root-current test patch awaiting integration.
- POSIX live process-group integration skipped on Windows; Linux/macOS acceptance remains open.
- A narrow process-creation window remains between `Popen` creating the suspended child and assignment to the named Job Object. Closing that window requires atomic Job-list process creation support; release acceptance stays open until reviewed and tested.

## Acceptance cases

1. Windows broker restart keeps parent and grandchild alive after old broker closes its job handle; new broker reopens the same job and stops every job member.
2. Recycled PID outside the named job is rejected without `TerminateJobObject`; independent process survives.
3. Missing/malformed job name, collision, inaccessible object, empty job, or legacy registry cannot be reported as a successful tree stop.
4. A live POSIX daemon stops its owned process group, including descendants; a recovered POSIX daemon remains running and reports cleanup unconfirmed without numeric signaling.

## Constraints

- Change T06-owned `commands.py`, daemon lifecycle tests, and T06 handoff docs only. Do not edit root or inherited `process_utils.py`.
- Do not loosen policy, task-owned worktree checks, write-set rules, or existing fail-closed kill behavior.
- Run only targeted tests when T20 assigns the shared slot. Windows tests cannot establish Linux/macOS syscall acceptance.
