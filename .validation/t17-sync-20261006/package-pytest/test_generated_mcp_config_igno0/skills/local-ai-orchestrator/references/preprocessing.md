# Background project preprocessing

Preprocessing scans, indexes, and builds AST and code maps in the background while idle:
- Non-blocking: starts asynchronously on the first call to `local_ai_repo(action="preprocess", root=...)`.
- Checkpointed and interruptible: foreground inference automatically preempts background workers.
- Avoid polling: never loop or wait on `preprocess_status`.
