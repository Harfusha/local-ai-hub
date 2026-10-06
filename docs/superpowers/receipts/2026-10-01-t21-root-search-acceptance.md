# T21 search policy — integrated-root acceptance

Production owner T10; root integration T20; test owner/main verification orchestrátor. Native fallback explicitly authorized by human instruction to ignore unavailable Hub. Main temporarily took idle T20 root test slot, no concurrent root validation, then returned it. No production source edited by main.

Immutable source patch `2873B765178E686F0AF27F82ADC099A2F98B4C2FC273EC5BABD58928F4BBB842` integrated by T20 into:

- Root repo_tools.py `8DA38ECBE3DAA4C975EC8F14FEDBC74D91D04CEEAF4CBB2C7155A3E554B6DA65`.
- Root services.py `A06AE015085E4B4DC61BF09A99570332044D65D623B7521218E569C329554235`.

## Exact command

Working directory `C:\Users\Adam\.local-ai-hub`:

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
raise SystemExit(pytest.main(['-q','-p','no:cacheprovider','--tb=short',r'C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub\tests\test_t21_search_policy_consumers.py','tests/test_project_config_service_integration.py','tests/test_repo_tools.py']))
'@ | & 'C:\Users\Adam\.local-ai-hub\.venv\Scripts\python.exe' -B -
```

Actual root origins printed for all three modules; **22 passed in 7.78s**, exit 0. No skip/deselect. Previously the main-owned five-test search-policy subset gave 3 failures/2 passes on root before the production fix. Custom text extension and config force-includes without caller hints now pass; explicit binary exclusions remain enforced.

Candidate acceptance separately verifies installed rg engine, two bounded argv batches/second-batch hit, zero-segment `**`, excludes, oversize and containment. That is candidate evidence, not additional root test count.

This accepts the search consumer slice only. Full T10/T21, other configuration consumers and final-root release gates remain open. `/api/context/pack` route untouched. Pytest temporary fixtures are intentional side effects; no installed Hub/model/backend started or shared user runtime data mutated.
