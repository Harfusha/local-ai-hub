# T19 isolated package candidate smoke — 2026-10-01

## Scope

Candidate worktree only: `C:\Users\Adam\.codex\worktrees\t19-docs-rollout\.local-ai-hub`, HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32` plus its existing dirty T19 working tree. No source, root, user profile, user config, daemon, or Hub server was changed. Build used a disposable copy at `C:\Users\Adam\AppData\Local\Temp\t19-package-smoke-6ec5u1sg\source`; artifacts and virtual environment remain under the sibling temp directory for inspection.

This is a candidate packaging smoke, not T20 release build or publish evidence.

## Build and isolated install

Preflight found `python -m build` unavailable (`No module named build.__main__; 'build' is a package and cannot be directly executed`). No package install or network access was attempted for it. Available setuptools backend built both formats from the disposable source copy, without build isolation:

```text
python -c "import setuptools.build_meta as b; print(b.build_sdist('<temp>/dist'))"
python -c "import setuptools.build_meta as b; print(b.build_wheel('<temp>/dist'))"
```

Wheel installed to disposable `venv` with:

```text
<temp>/venv/Scripts/python.exe -m pip install --no-index --no-deps <temp>/dist/local_ai_hub-4.0.0-py3-none-any.whl
```

Isolated `-I` smoke imported `HubClient`, checked installed metadata version `4.0.0`, parsed packaged `local_ai_hub/defaults.toml`, and confirmed `HubClient` exposes `auto_start`. Result:

```json
{"client_import":"ok","defaults":"loaded","schema_contracts":"missing operation_contracts.py","version":"4.0.0"}
```

Wheel inspection confirmed `client.py`, `mcp_server.py`, and `defaults.toml`; sdist contains `docs/PYTHON_SDK.md`, both canonical prompts, defaults, and MCP source. No runtime request or daemon was started.

## Blocking schema gap

T19 candidate has no `src/local_ai_hub/operation_contracts.py`; bounded `rg` found no `operation_output_schema` or `operation_tool_input_schema` definitions/imports in its MCP source. Wheel therefore lacks `local_ai_hub/operation_contracts.py`. The smoke deliberately does not claim action-specific MCP schema acceptance. Root/T20 schema changes were not copied into this candidate.

## Artifact receipts

- Wheel: `local_ai_hub-4.0.0-py3-none-any.whl`, 954,908 bytes, SHA-256 `9114E5815CCF3A22D920AE12CCAD8DD6A9CD7A83F2F398DA81FA6AEDF4519F45`
- Sdist: `local_ai_hub-4.0.0.tar.gz`, 1,638,059 bytes, SHA-256 `C560ED6A6E81AAB652032D2F2950F34C0F7073240B1255EEF85AD26B2956F0CE`
- Candidate inputs (SHA-256):
  - `pyproject.toml`: `4E03F365D97FD475A4DFF8169725BF0C999631F3F49612E06650BAAD172899C0`
  - `MANIFEST.in`: `BCBB4D098A772C2C6BFD57FEDDCD5CE5DAF65DA69EE1AC7C9D74F1BCC306E854`
  - `docs/PYTHON_SDK.md`: `9EF0136CAE929E968CA38B561301F7DA495124ECF43CCD3FCC6C07588E6C856F`
  - `docs/INSTALL_PROMPT.md`: `D77344A3B685141413F90FA4BCDB5E716D976BB6E2029D7B8CB62AB94B027FBC`
  - `docs/UPDATE_PROMPT.md`: `BDDE8E04ADA45DA2B92EB84A8AFAD372A3DF02DD7472DBFEB83652CA08697A31`
  - `src/local_ai_hub/client.py`: `3444F49E85E475EBB01ED7A8A68C24BEE25C1AE8ADCD5FC882E864B4F4F75073`
  - `src/local_ai_hub/mcp_server.py`: `EED71E9593E0411770EF4C0A50595E5925AEE266FE66D38252DF806D53392A5B`
  - `src/local_ai_hub/defaults.toml`: `D688F8546F616B872B2111C1F137C06964035E75C6DA8B2A2DD2F420400A039E`

T20 should repeat full wheel/schema/install validation from its frozen integrated snapshot. Clean-host installer lifecycle remains separately open.
