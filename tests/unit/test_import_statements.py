import pytest

from local_ai_hub.import_statements import import_for, language_for_path


@pytest.mark.parametrize(
    "path,expected",
    [
        ("module.py", "python"),
        ("Widget.CS", "csharp"),
        ("src/App.tsx", "typescript"),
        ("src/App.mts", "typescript"),
        ("src/App.jsx", "javascript"),
        ("src/App.vue", "javascript"),
        ("src/App.svelte", "javascript"),
        ("src/unknown.txt", "auto"),
    ],
)
def test_language_for_path(path, expected):
    assert language_for_path(path) == expected


@pytest.mark.parametrize(
    "symbol,container,path,language,source,expected",
    [
        ("Widget", "Acme.UI", "Widget.cs", "csharp", "", "using Acme.UI;"),
        ("Widget", "", "Widget.cs", "csharp", "namespace Acme.UI;", "using Acme.UI;"),
        ("Widget", "Acme\\UI", "Widget.php", "php", "", "use Acme\\UI\\Widget;"),
        ("Widget", "", "Widget.php", "php", "namespace Acme\\UI;", "use Acme\\UI\\Widget;"),
        ("Widget", "", "pkg/widget.py", "python", "", "from pkg.widget import Widget"),
        ("Widget", "", "pkg/__init__.py", "python", "", "from pkg import Widget"),
        ("Widget", "", "src/widget.ts", "typescript", "", "import { Widget } from './src/widget';"),
        ("Widget", "", "src/widget.vue", "javascript", "", "import { Widget } from './src/widget.vue';"),
        ("Widget", "", "src/o'k.js", "javascript", "", "import { Widget } from './src/o\\'k';"),
        ("Widget", "", "widget.unknown", "auto", "", ""),
    ],
)
def test_import_for_preserves_language_syntax(symbol, container, path, language, source, expected):
    assert import_for(symbol, container, path, language, source) == expected
