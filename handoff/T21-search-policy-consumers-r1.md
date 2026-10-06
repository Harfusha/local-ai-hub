# T21 search settings consumer RED r1

Owner: orchestrator test only. Production search consumer fix released to existing T10 owner; root integration T20.
New owned file: `tests/test_t21_search_policy_consumers.py`.
SHA-256: `2D95ECEB2B4F3C283AF5006633EAD8378669BF033BD0781312A50BF3E5DE7C1B`.
Existing candidate: `C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub`.
Authoritative source: `C:\Users\Adam\.local-ai-hub\src`, observed HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.

## Exact command

Run from the existing candidate above. No live Hub, port, model, GPU or benchmark.

```powershell
@'
import importlib
import os
import pathlib
import sys
root_src = pathlib.Path(r'C:\Users\Adam\.local-ai-hub\src').resolve()
os.environ['T21_EXPECT_SOURCE_ROOT'] = str(root_src)
sys.path.insert(0, str(root_src))
for name in ('project_config', 'repo_tools', 'services'):
    module = importlib.import_module('local_ai_hub.' + name)
    origin = pathlib.Path(module.__file__).resolve()
    assert origin.is_relative_to(root_src), (name, origin)
    print('ROOT_IMPORT', name, origin)
import pytest
raise SystemExit(pytest.main(['-q', '-p', 'no:cacheprovider', '--tb=short', 'tests/test_t21_search_policy_consumers.py']))
'@ | python -B -
```

Actual result: **3 failed, 2 passed in 1.86s**, exit 1. All three module origins explicitly under root source.
Fixtures use actual lexical `RepositoryTools`, actual project resolver and actual service method over temporary Git/files/config; optional indexes/model/cache plumbing disabled, not search mocked.

- Both custom-text extension cases fail: `.shader` configured as text is absent with and without exact request path hint.
- Forced Git-ignored project glob fails without request hint: `node_modules/@my-org/**` does not return its real matching file.
- Positive forced exact-file request hint passes.
- Forced inclusion still rejects a project-declared binary `.php` file; negative control passes.

T10 owns only the closed source fix in `RepositoryTools.search`, policy/inventory helpers, `search_paths` and `LocalAIServices.repo_search`; immutable per-call settings, no global extensions mutation, bounded read/containment/hard-denial preserved.
No `/api/context/pack` route, T12 model methods or namespace-test edits released.
This test is not done acceptance or a request to loosen binary/containment assertions. Integrate test and owner fix together after review; do not silently omit RED selectors from release.
