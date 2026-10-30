# Case 094: partially failing batch

Copy this directory to a new disposable workspace before giving it to the tested agent. The seed is intentionally faulty; never run an agent against the tracked fixture itself. This fixture is synthetic and does not establish Local AI Hub runtime behavior.

The public interface is `process_batch(items, exporter)`. Preserve input order and return one item result per input using `id`, `status` and either `value` or `error`. A successful export has status `ok`; an ordinary exception has status `error` and retains its message; `ExportCancelled` has status `cancelled`. Overall `success` is true only if every item succeeded. Invoke the exporter at most once per item; a successful side effect must not be retried.

The oracle uses a bounded event gate for the slow item and an explicit cancellation exception. Run `python oracle_094.py` in the copied workspace: the unmodified seed must fail all three checks; after the agent's repair, all three must pass. Record actual command output, workspace identity and changes. The oracle is not a receipt and must never be treated as evidence from a live Hub.
