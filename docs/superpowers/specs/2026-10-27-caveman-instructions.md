# Caveman instruction compression

The operator requests a CLI for compressing discovered agent instruction and skill text, with recoverable backups made before changes. The tool should preserve instructions and structured MCP configuration, report skipped or failed files, and avoid corrupting agent behavior. Generated Hub instructions should be concise while retaining their contracts.

Local model responses should support concise output where appropriate. Evaluate input compression and other Hub context savings without silently discarding required instructions, exact source, structured data, or identity. Measure speed and quality before claiming an improvement.

Work in the isolated checkout alongside the release owner. The operator authorizes implementing a safe repair for the existing execution task's missing session before the normal task-to-plan binding prerequisite. Preserve task identity, history, counters, authorization and concurrency fences; do not edit task storage directly. Bind the same task after the repair is available and verified.

Operator clarification: continue compression implementation in parallel while the other agent owns Hub activation. Repair and bind the existing task once the shared Hub is available for the verified activation. Verify backups, retained meaning, and speed.

Observed synthetic local run: upstream compressor with `qwen2.5-coder:3b` took 3.34 seconds for a 92-character input and returned a 48-character response that omitted its instructions. This is a failed semantic check, not a speed comparison or validation for real files. Keep candidates staged until an independent meaning check succeeds.

The same synthetic input with `qwen2.5-coder:7b` exited with code 2 and produced no accepted candidate. This is not evidence that the model is generally unsuitable.
