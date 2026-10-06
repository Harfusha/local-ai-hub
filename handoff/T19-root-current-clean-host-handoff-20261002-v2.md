# T19 root-current install and clean-host handoff — 2026-10-02

## Scope and decision

Read-only comparison plus T19-owned handoff record. No root files, tests, builds, installs, services, or clean hosts were touched in this continuation. T19 remains PRE-INTEGRATION; T20 owns the frozen integrated revision, serial test slots, and release acceptance. Do not overwrite root docs with the older T19 candidate or apply stale overlay patches.

## Revision and path pins

- Root `C:\Users\Adam\.local-ai-hub`: HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`.
- T19 candidate `C:\Users\Adam\.codex\worktrees\t19-docs-rollout\.local-ai-hub`: HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`.
- Root install and update runbooks already match T19 byte content after newline normalization: `docs/T19_RELEASE_VALIDATION_RUNBOOK.md` root SHA-256 `53ec31aa3f646308c21c0f5101123880b583513597389f5b32e8bc5541972d63`; T19 SHA-256 `1ceebde91205d2274ac8fc8ee29e30cc644306de1f98e45e368147106ac67a2a`. `docs/T19_CLEAN_HOST_INSTALLER_CYCLE.md` root SHA-256 `a037dae1d9942c76f15b7f0801f647e9fc5879b74b9e41d206d308432a0ad49a`; T19 SHA-256 `9e6bd37411ec8fbbe33f249047e7c812eaff618445bcfb9693c674e2b3600b64`. Both content comparisons returned identical after CRLF normalization.
- `T19-release-validation-runbook-root-current-v2-20261002.patch` SHA-256 `255902ac43475c56a66be060a65d01149dd146caa565b0894151a7a15874c03d`; reverse apply-check against root passed, forward check failed: already integrated.
- Older install/SDK docs overlay `T19-root-current-install-sdk-docs-disjoint-20261001.patch` SHA-256 `e003e1f7c372981742d932a1db5a2bb4d4eb92ef45de13cfee8c80c4d996e5ca` and prompt overlay `T19-root-current-docs-prompt-20261002.patch` SHA-256 `53851641f5fa14048ff52f5b26bd5a8822cf28e239b8755e8afce3f7ef6f52dc` failed both reverse and forward apply-check. Do not apply.
- Root and T19 configs and install/security docs currently diverge beyond line endings. Root owns newer cross-track content. Current root SHA-256: `config.toml.example` `47c778f73162f96f634ff13fb0ac0c9316261147cb616821564db9a999abe665`; `docs/INSTALLATION.md` `3802b4f60012f8e5c0eca12673f0d8273fc93e6edeafa03fd6af838b7dbf463d`; `docs/INSTALL_PROMPT.md` `7e5da693aebdfe0bd2f025aa6176e75284701eb4b92fedf636e64a88d7c6573b`; `docs/UPDATE_PROMPT.md` `50ce34f25602653652235a8267e6ea2d85953bb6541c2ec66de7c40d22a31c97`; `docs/MCP_AND_AGENTS.md` `7617d5dff6d68aae0799cb71f414d6ed0f91b72f6f4ade4aaa7a26e34e180664`; `docs/OPERATIONS.md` `9de3746ff7a8db45e36329302e8b581896634bb4af6279958889920a8662dd21`; `docs/SECURITY_MODEL.md` `5645568fc500d15e2c8d928279fb9a1ad955d94f900c03704a15696a9f9f4088`.
- Latest T19-owned source pins: config `28aa6de2bb03acd9a9fd7559edde9a05e076ccee63100deecc96fe3e7e7b48ec`; install prompt `4eca9bcc8a1b87f10f9f172ea0c42f3134148f1debc6af0090a880376ad02771`; update prompt `4d9a0332ce733239ad5008bd4af033e00566ad79a13c2b3cbe964e97960989ca`; install guide `2e482a5af2a9973d0ff28de6559ce2948ce84a7f3312541c1c9c9143d62cad69`; security model `3f139e48bf893d1f69e54358e65b52770f918373ece4f00381a87859b626ce81`; MCP guide `dbf2563d56d03a87abbabf828ddf88364347c37c60d0fad43af573abbdbb14f4`; operations `aa0fb449f6b14f6f29a36c9692af5cdfcbd328f0fad8d38533f040af0f07a801`.
- T19 candidate `tests/test_t19_shared_daemon_rollout.py` SHA-256 `8ea68e209efbca72a636fec97c99960a68211c0349bdfe7e459c8386515bc2cb`; `tests/test_t19_rollback_contract.py` `27f83103695ebc1de004f1e58fa8e1a87a956c154a44e586a29119715b3452f0`; `tools/rollback_snapshot.py` `4117889bb751afae0a6b198ac67b8e80cb1517f8d45c1caa98c16e1d00e9deb6`. These three paths are absent from root at this pin; integrate only after owner/root-preimage review.

## Existing evidence and limits

- Earlier T19 shared-daemon/install contract slice: 42 passed, 1 Windows symlink permission skip. Receipt predates latest T19 docs/config edits and is not bound to the current candidate hashes. This is source-contract evidence, not clean-host or 30-client benchmark.
- Candidate rollback contract/snapshot slice: 7 passed, 1 Windows symlink permission skip. It does not prove restore from an incompatible durable DB schema; T08 recovery evidence remains required.
- Windows Python 3.13.2 isolated venv receipts: wheel `99e370d93463a1cb1191b3ee8053a7e8e65a739cf772be6bb166cd6606e95ae2` with six extras; sdist `e2bda6c68f478182baad42b7d196794f4da468ec2d7da3bac6932d4b85d35136`. `pip check`, CLI help, and offline doctor passed. These used the development host, not a disposable clean host. Receipt `dist/t19-release-20260930-current-artifacts/reinstall-receipt.json`, SHA-256 `8ad3316757a07b5692a76739f944855227aa4e799034cf444e51ffbcd1ef168c`.
- Older core-only clean-host receipt used sdist `0df7c0a843181465a4e77628e1ed7f8ed94ec7703bdb0a1c8642339fc7f854a1` on Windows Python 3.13 and Ubuntu Server 26.04.1 / Python 3.14.4; `pip check`, CLI help, and Linux offline doctor passed. Artifact predates integrated root and current T19 security/config/docs bytes.
- Linux all-extras attempt failed at `nvidia_cudnn_cu13` download: `OSError: [Errno 122] Disk quota exceeded`. No quota cleanup or retry is authorized by this receipt.
- Current integrated clean-host install/reinstall/uninstall and service restart: **NOT RUN**. Require T20 to freeze revision/artifact pair and assign serial slots. Current runbook has eight OS/Python cells; T20 must choose all eight or one Python per OS before scheduling.
- No clean-host proof for current root, no T20 release acceptance, no 1/10/30-client RSS/CPU measurement, no T13 auth/root/tenant isolation proof, and no T08 incompatible-DB recovery proof.

## Next safe integration sequence

1. T20 freezes one integrated revision and artifact pair; T20 resolves install prompt policy drift and chooses clean-host matrix coverage.
2. Review T19-owned config/docs changes against current root security, T03/T04/T13 interfaces, and preserve all root edits. Recompute pre/post hashes for any accepted hunks; do not apply the rejected overlay patches.
3. Integrate missing rollback script/tests only with their current root preimages and T08 owner agreement. Keep `/api/context/pack` outside T19 edits.
4. T20 assigns serial slots for scoped tests, package builds, and each clean-host install/reinstall/uninstall/service cycle. Capture exact revision, artifact hashes, OS/Python, commands, exit codes, config/state preservation, and doctor output.
5. Keep rollback-after-incompatible-DB, actual 30-client load/resource benchmark, security isolation, and release completion blocked until owner receipts land on the same frozen revision.
