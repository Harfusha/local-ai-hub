## Summary

<!-- What does this PR change and why? -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Performance improvement
- [ ] Documentation
- [ ] Refactor / cleanup

## Checklist

- [ ] python -m compileall -q src tools tests passes
- [ ] python -m pytest -q passes
- [ ] python tools/selftest.py passes
- [ ] All subprocess / network calls have finite timeouts
- [ ] Optional backends (Serena, CodeGraphContext, Ollama) fail soft when absent
- [ ] No new MCP tool schemas added without prior discussion
- [ ] CHANGELOG.md updated with a brief entry (if user-visible change)

## Related issues

<!-- Closes #... -->
