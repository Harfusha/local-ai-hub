# Case 081: isolated batch and controlled provider failure

Run `python prepare.py ABSOLUTE_NEW_ROOT --port HUB_PORT --provider-port PROVIDER_PORT --source ABSOLUTE_HUB_SOURCE`. Both ports must be free non-production loopback ports. Start `provider.py --port PROVIDER_PORT`, then start the isolated Hub supervisor with the generated explicit config and `PYTHONPATH` pointing to the supplied source. Confirm process ownership and endpoint before handing the client to a chat. Stop only the processes owned by this fixture, retain logs/state, and never switch the production Hub config.

The provider is deliberately synthetic: the `CASE081_FAIL` request returns HTTP 400, while first and last have fixed fixture responses. This tests real MCP/HTTP transport and failure propagation, not local-model quality or performance. Inspect `provider-events.jsonl`, returned IDs and recovered artifact; never count a missing provider invocation as a successfully exercised failure. Do not rerun a batch after an unknown outcome.

The scheduler may retain an uncertain GPU reservation after the failure and reject the third item without sending it. Record that as an unverified third outcome; do not clear the reservation or treat HTTP status alone as proof that remote work stopped. The fixture does not establish the requested two-success/one-failure result when this occurs.

The separate `workspace/zadani-preflight.md` variant injects an invalid per-item `prompt` alias before inference instead. It checks independent continuation without asserting anything about provider errors; never conflate the two scenarios.
