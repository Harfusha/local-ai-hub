# Local AI Hub: single local owner, no tenancy

Date: 2026-10-18
Status: implementation in progress within the active completion goal; data conversion and validation pending.

## Operator decision

One Local AI Hub installation on one PC serves one human operator. Multiple
agents, chats, projects and worktrees do not create separate human tenants.
The operator explicitly requires complete removal of the tenant abstraction
and rejects legacy behavior, deprecated aliases and backward compatibility.
This decision supersedes older project requirements that mandate tenant routing.

## Required implementation

- Remove tenant selection and propagation across configuration, HTTP, MCP,
  SDKs, internal services, jobs, storage, receipts, artifacts and dashboard.
- Remove multi-user principal routing used solely to select a tenant, including
  the `api_token_tenant` / `api_token_principal` selection chain and fallback
  tenant identities. Do not replace this with a hidden constant tenant shim.
- Remove obsolete tenant headers, arguments, schema fields, database columns,
  indexes, predicates and generated tool/policy instructions. Reject retired
  public fields explicitly instead of silently accepting or translating them.
- Keep project, repository, clone, worktree, branch, task and session identities
  and their declared scopes. The existing global scope belongs to the single
  local owner; missing required project/task identity must still reject.
- Keep API access protection, capability restrictions, command authorization,
  path confinement, writer leases and other safeguards unrelated to tenancy.
- Update implementation, tests, configuration reference, generated schemas,
  installer/update logic and both canonical agent prompts consistently.
- Do not add old/new dual reads, signature adapters, migration shims, tenant
  aliases or compatibility defaults to the supported runtime.

## Existing state

Preserve dirty work, operator settings and durable contents. Do not silently
merge previously distinct records with colliding identities. Before any durable
schema conversion, define and verify an explicit preservation/conflict procedure;
that procedure must not become a permanent runtime compatibility layer.
Disposable derived state may be rebuilt according to the existing state policy.

## Acceptance

The integrated source must contain no active tenant routing or tenant-dependent
storage/API contracts. Historical documentation may explain the removed design
but must not prescribe it. Regression coverage must prove project/task scope
separation and retained authorization after removal. Run final tests only after
the complete source bundle is assembled, as instructed by the operator.

Recording this specification does not claim source removal, data conversion,
installed-runtime activation or passing validation.
