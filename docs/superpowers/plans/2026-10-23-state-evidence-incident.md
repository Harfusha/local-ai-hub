# Local AI Hub: missing runtime state and validation evidence

## Current disposition

The operator confirmed: "Ja jsem to smazal - chci cisty stav" (I deleted it; I want a clean state). The deletion was intentional. Recovery of previous runtime history, archives and usage counters is no longer an acceptance requirement; no preservation claim is made. Configuration and source remain preserved.

Main stopped the newly observed managed Hub, terminated 54 stdio providers bound to this exact installation/configuration, and moved the residual state directory outside the checkout to `C:/Users/Adam/.local-ai-hub-state-before-clean-20261023T141257Z`. The new canonical state initially contains only the service-disabled control marker. No old database is restored. Both configuration hashes below remain unchanged. The protective RAG copy started before operator clarification is separate, unused, and has no verified integrity result.

Clean initialization, fresh validation and runtime acceptance remain required. The interrupted full suite remains incomplete. Historical receipt/task counters cannot be replayed as fresh evidence. The original Codex goal remains active, with the operator's clean-state disposition superseding its historical-data preservation clause. No replacement chat is created.

## Observations and containment

- The complete suite started on master `34d734f0a3be5a3507cc4b60c209818167551b8f`,
  candidate `70f8f37db7c61ceb686de1981c95cbdf1ff7cf5b10f0647ca5016a2d2e986d78`.
  Collection contained 11849 cases. Shards were serial, with an unchanged
  240-second limit each.
- Shards 0–4 recorded exit 0 and stable inputs. Earlier direct JUnit observations
  for shards 0–3 totalled 1439 PASS / 13 SKIP, no failures/errors. The retained
  shard-04 log reports 345 PASS / 3 SKIP. These observations are not a complete
  suite result: their original XML/manifests subsequently became unavailable.
- At approximately 15:43 local time, older files under state/validation were no
  longer present. The initial missing shard-00.xml check was followed by a direct
  directory inventory: only run.json, shard-04.log, shard-05.log and the current
  shard-05.manifest.json remained. Other previously read validation, UI,
  package and preservation artifacts under state/validation also became absent.
- Main verified and terminated the owned full-suite driver PID 6540 and its
  currently identified children. No identified validation survivors remained;
  native exec session 1795 then completed with exit 1. This was a controlled
  stop, not a passed suite or an automatically restarted run. Shard 5 has only
  partial reports, without a normal completed JUnit result.
- Surviving files and actual stop/process observations were copied outside
  state/validation to:
  `C:/Users/Adam/.codex/visualizations/2026/10/21/01a15ec3-cf4b-7fc0-b81a-0ae7446ff8ff/fullsuite-e78f7ba66b58-controlled-stop`.
  No missing XML was reconstructed from counts, stdout or partial reports.
- The Hub request journal returned 503 (`req_8a80d467692f`, mutation not
  dispatched). One bounded readiness check (`req_a593e853956d`) reported
  OperationalError for agent_state, preprocessing and semantic_cache.
- Main ran the reviewed official `tools/hubctl.py stop` once: exit 0, `stopped`.
  Listener PID 39868, supervisor 19596 and launcher 23172 subsequently no longer
  existed, and the TCP listener was absent.

## Offline filesystem observations

- config.toml still hashes to
  `d18a3405a54c3166980c270c29e8a793389ca45d86dd521fe48197fdbd0a5d98`;
  config.runtime.toml still hashes to
  `f251e2836b2565531c622b5e26054914b10f7caaf7312534ea4a90c1df43abfb`.
  Both match the earlier observations. Their contents were not changed.
- state/operational_mode.json was absent. state/agent_state.sqlite became
  absent and later existed as a zero-byte file; telemetry.sqlite3 was zero bytes.
  Several other small runtime databases were absent or empty. This is not an
  accepted initialization or a verified recovery.
- The active rag.sqlite3 remained in place at 10558570496 bytes, with a
  432632-byte WAL and 32768-byte SHM at the offline observation. Code-index and
  deterministic databases also remained. None of these files or sidecars was
  deleted, replaced, checkpointed or declared logically intact by main.
- All four previously named historical RAG files below
  state/single-owner-conversion-20261018-1d55c3d703 were absent at their original
  locations. D:/LocalAIHubRecovery and its formerly verified backup directory
  were also absent; drive D itself was available.
- A bounded current-user recycle-bin metadata check found no matching project
  entries. CIM shadow-copy inspection failed initialization; vssadmin required
  elevated permissions. Therefore shadow-copy availability remains unknown,
  not disproved. A bounded PowerShell operational-log query found no matching
  script records among the returned records; it does not establish causation.
- Fifty stdio provider processes for this Hub installation were observed after
  the managed service stop. They were not declared stopped. Any recovery must
  first establish a quiet set of writers; do not overwrite data beneath them.

## Required next work

- [ ] Identify a genuine current recovery copy or relocation, and the scope and
  origin of the filesystem changes. Main asked the human whether another cleanup
  ran and whether another copy exists; that information is still pending.
- [ ] Preserve remaining DBs plus WAL/SHM/journal files and newly created state
  before any recovery mutation. Keep original metadata, ownership and provenance.
- [ ] Quiesce the remaining actual installation writers before restoring any
  file. Do not use restart loops, change operational mode or modify unrelated
  projects/client configuration as a workaround.
- [ ] Recover through a verified offline procedure. Do not silently roll back
  newer records, counters, task ownership, accepted budget maxima or history.
  Do not fabricate missing task events, receipts, XML or creation-time evidence.
- [ ] Establish whether the test execution could reach non-test data. Any
  reproduction must protect real state and recovery roots, use disposable data,
  and preserve the original behavior assertions; no tests run against live data.
- [ ] Put future immutable validation/release evidence outside a potentially
  mutable runtime-state tree. Retain the incomplete epoch as an incomplete epoch.
- [ ] Only then resume the full original F01–F24/R01–R16, release, runtime, UI and
  data acceptance plan. Earlier source/test observations do not establish current
  production acceptance or compensate for the missing preservation evidence.
