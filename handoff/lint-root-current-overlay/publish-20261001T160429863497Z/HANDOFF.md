# Misc Pyflakes cleanup: current root handoff

Status: SOURCE_STATIC_PASS. Production integration and release validation belong to T20.

Root: `C:\Users\Adam\.local-ai-hub`

Patch: `misc-pyflakes-current-root.patch`

Patch SHA256: `ccb07f6babf0668228d5ca4eff2a5cfda1c76a405bbb2870535f73fdc7961925`

Receipt: `receipt.json`; exact 14-file scope, commands, results, pre/post SHA256, AST proof.
Preimage hashes identify captured current-root bytes; postimage hashes identify owned overlay bytes.
`capture.json` records Copy-Item byte-preserving capture and before/copy/after equality.
`bundle-index.json` hashes every published artifact. Published files are marked read-only.

Minimal changes:
- Remove placeholder-free f-prefix from `"ALTER"` only.
- Remove three unused exception bindings, preserving exception types and bodies.
- Bind unused `lower()` / `as_posix()` results to `_`, preserving calls and exceptions; AST confirms no `_` loads in their enclosing functions.
- Remove unused JSON imports; both duplicate imports in `token_economy.py` must be removed for the owned gate.
- Rename only requested-field loop binding and its body uses; preserve `dataclasses.field` and schemas.
- Add canonical `CommandBroker` import under `TYPE_CHECKING`, keeping existing postponed annotations and avoiding runtime Hub imports.
- Remove only unused `BaseHTTPRequestHandler` and `sqlite3` in the owned surfaces tool.

Proof:
- Owned-only global `python -B -m pyflakes`: exit 0. No full-root lint rerun.
- AST parse and exact allowlisted pre/post AST delta comparison: 14/14 PASS; unrelated AST, schemas, RHS and exception bodies unchanged.
- Root `git apply --check --whitespace=error`: exit 0.
- Root preimage hashes unchanged after checks and again at sealing.
- Final patch manually reviewed by all changed lines; no earlier client handler change remains.

Audit notes:
User-provided original root Pyflakes exit 1 / 31 diagnostics is the genuine RED fixture.
First intermediate overlay diagnostics are preserved in `first-overlay-pyflakes.txt`.
Initial packaging Git check failed on CRLF whitespace; patch now uses canonical LF serialization.
Successful owned lint was reused after exact byte equality of full diffs against unchanged preimages; receipt states successful output was not separately persisted.
No Hub/GPU, app imports, build, pytest, root/candidate writes, Git mutation, installs, new chat/task/worktree.

Next critical release step: main reviews this exact patch; T20 confirms current preimages, integrates only these hunks, owns final root gate and release acceptance. On root drift, regenerate only owned hunks; never transplant overlay whole files.
