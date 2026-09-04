# Security policy

## Supported version

Security fixes target the current 1.x release.

## Reporting

Do not publish suspected vulnerabilities, secrets, or private repository content in a public issue. Use the repository owner's private security-reporting channel when one is configured on the hosting platform.

## Deployment guidance

- Keep the hub bound to loopback unless remote access is explicitly required.
- Remote binding requires `security.allow_remote = true` and a strong API token.
- Treat tenant IDs as scheduling/fairness labels, not authentication boundaries.
- Review `[commands]` before enabling mutating or unknown commands.
- Serena/CodeGraph and Ollama are local subprocess/services with access to repositories you point them at; apply normal local-machine trust controls.
- Telemetry is designed to exclude prompts/source/model output, but repository indexes and RAG state contain derived local code data and should be protected like source code.
