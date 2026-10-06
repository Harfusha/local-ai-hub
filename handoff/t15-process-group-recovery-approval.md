# T15 process-group recovery design approval

The user approved this bounded recovery design:

- Persist the daemon's `process_group_id` with its recoverable metadata.
- On restart, allow recovery when the leader PID has exited only if the process group is independently and safely verified as still alive.
- Reject recovery when the group cannot be verified alive, including when the group is gone or liveness is indeterminate.

This approval settles the design choice. It does not assign implementation ownership: T06 owns `src/local_ai_hub/commands.py` and its process-group/recovery implementation and tests. T15 has not edited that source. T06 still needs to implement and verify the contract, including the platform-specific liveness boundary, before the candidate can claim recovery acceptance.
