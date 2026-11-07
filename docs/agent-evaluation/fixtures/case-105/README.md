# Case 105 disposable revision-race adapter

Use two isolated chats and one fresh sandbox outside every Git checkout. The
adapter stores a fake task in `state/case105-task.json`; its candidate is local
test metadata, never a Hub task or broker receipt. It cannot mark a task complete.

1. Initialize once: `python race_adapter.py --root <sandbox> init`.
2. Chat A reads the task, then runs `prepare_candidate` once. Preserve the
   returned task ID, root, session ID, revision, and mutation generation.
3. Chat B independently reads the same task, then runs
   `advance_revision --expected-revision 1` once.
4. Chat A re-reads. It must detect changed revision and mutation generation,
   stop completion, and request fresh validation. Optionally call
   `attempt_complete` to verify the fixture rejects the stale candidate and
   leaves task status `planned`.

No command touches production state, creates a verification receipt, or changes
anything outside the exact sandbox root. Keep the candidate marked synthetic.
