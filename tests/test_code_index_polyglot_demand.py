from pathlib import Path
from local_ai_hub.code_index_demand import one_hop_related_files, two_hop_weighted_files
from local_ai_hub.repo_tools import RepositoryTools


class CountingSet(set):
    def __init__(self, values):
        super().__init__(values)
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        return super().__iter__()


def test_one_hop_follows_go_local_imports(tmp_path: Path):
    (tmp_path / "go.mod").write_text("module example.com/myproject\n\ngo 1.22\n", encoding="utf-8")
    (tmp_path / "pkg/calc").mkdir(parents=True)
    (tmp_path / "main.go").write_text(
        'package main\n\nimport (\n\t"fmt"\n\t"example.com/myproject/pkg/calc"\n)\n\nfunc main() {}\n',
        encoding="utf-8",
    )
    (tmp_path / "pkg/calc/calc.go").write_text(
        'package calc\n\nfunc Add(a, b int) int { return a + b }\n',
        encoding="utf-8",
    )
    eligible = {"main.go", "pkg/calc/calc.go"}
    neighbors = one_hop_related_files(tmp_path, ["main.go"], eligible, RepositoryTools({}))
    assert neighbors == ["pkg/calc/calc.go"]


def test_one_hop_follows_rust_modules_and_use(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/main.rs").write_text(
        'mod util;\nuse crate::config::Config;\n\nfn main() {}\n',
        encoding="utf-8",
    )
    (tmp_path / "src/util.rs").write_text('pub fn helper() {}\n', encoding="utf-8")
    (tmp_path / "src/config.rs").write_text('pub struct Config;\n', encoding="utf-8")
    eligible = {"src/main.rs", "src/util.rs", "src/config.rs"}
    neighbors = one_hop_related_files(tmp_path, ["src/main.rs"], eligible, RepositoryTools({}))
    assert set(neighbors) == {"src/util.rs", "src/config.rs"}


def test_one_hop_follows_c_cpp_local_includes(tmp_path: Path):
    (tmp_path / "include").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src/main.c").write_text(
        '#include <stdio.h>\n#include "engine.h"\n#include "../include/shared.h"\n\nint main() { return 0; }\n',
        encoding="utf-8",
    )
    (tmp_path / "src/engine.h").write_text('#pragma once\nvoid start();\n', encoding="utf-8")
    (tmp_path / "include/shared.h").write_text('#pragma once\nint version();\n', encoding="utf-8")
    eligible = {"src/main.c", "src/engine.h", "include/shared.h"}
    neighbors = one_hop_related_files(tmp_path, ["src/main.c"], eligible, RepositoryTools({}))
    assert set(neighbors) == {"src/engine.h", "include/shared.h"}


def test_one_hop_follows_ruby_relative_require(tmp_path: Path):
    (tmp_path / "lib").mkdir()
    (tmp_path / "app.rb").write_text(
        'require "json"\nrequire_relative "lib/worker"\n',
        encoding="utf-8",
    )
    (tmp_path / "lib/worker.rb").write_text('class Worker; end\n', encoding="utf-8")
    eligible = {"app.rb", "lib/worker.rb"}
    neighbors = one_hop_related_files(tmp_path, ["app.rb"], eligible, RepositoryTools({}))
    assert neighbors == ["lib/worker.rb"]


def test_one_hop_follows_csharp_and_java_imports(tmp_path: Path):
    (tmp_path / "src/Services").mkdir(parents=True)
    (tmp_path / "src/Program.cs").write_text(
        'using System;\nusing Services.Auth;\n',
        encoding="utf-8",
    )
    (tmp_path / "src/Services/Auth.cs").write_text(
        'namespace Services.Auth { public class Auth {} }\n',
        encoding="utf-8",
    )
    (tmp_path / "java/com/app").mkdir(parents=True)
    (tmp_path / "java/Main.java").write_text(
        'package com;\nimport com.app.Runner;\n',
        encoding="utf-8",
    )
    (tmp_path / "java/com/app/Runner.java").write_text(
        'package com.app;\npublic class Runner {}\n',
        encoding="utf-8",
    )
    eligible = {"src/Program.cs", "src/Services/Auth.cs", "java/Main.java", "java/com/app/Runner.java"}
    neighbors_cs = one_hop_related_files(tmp_path, ["src/Program.cs"], eligible, RepositoryTools({}))
    assert neighbors_cs == ["src/Services/Auth.cs"]

    neighbors_java = one_hop_related_files(tmp_path, ["java/Main.java"], eligible, RepositoryTools({}))
    assert neighbors_java == ["java/com/app/Runner.java"]


def test_one_hop_resolves_typescript_nodenext_js_specifier_to_ts(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/main.ts").write_text(
        'import { run } from "./worker.js";\n', encoding="utf-8"
    )
    (tmp_path / "src/worker.ts").write_text("export function run() {}\n", encoding="utf-8")
    (tmp_path / "src/worker.js").write_text("export function run() {}\n", encoding="utf-8")
    eligible = {"src/main.ts", "src/worker.ts", "src/worker.js"}

    neighbors = one_hop_related_files(tmp_path, ["src/main.ts"], eligible, RepositoryTools({}))

    assert neighbors == ["src/worker.ts"]


def test_one_hop_follows_both_rust_nested_module_layouts(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/file_layout.rs").write_text("mod child;\n", encoding="utf-8")
    (tmp_path / "src/file_layout").mkdir()
    (tmp_path / "src/file_layout/child.rs").write_text("pub fn file_child() {}\n", encoding="utf-8")
    (tmp_path / "src/directory_layout.rs").write_text("mod child;\n", encoding="utf-8")
    (tmp_path / "src/directory_layout/child").mkdir(parents=True)
    (tmp_path / "src/directory_layout/child/mod.rs").write_text("pub fn directory_child() {}\n", encoding="utf-8")
    eligible = {
        "src/file_layout.rs",
        "src/file_layout/child.rs",
        "src/directory_layout.rs",
        "src/directory_layout/child/mod.rs",
    }

    file_layout = one_hop_related_files(tmp_path, ["src/file_layout.rs"], eligible, RepositoryTools({}))
    directory_layout = one_hop_related_files(
        tmp_path, ["src/directory_layout.rs"], eligible, RepositoryTools({})
    )

    assert file_layout == ["src/file_layout/child.rs"]
    assert directory_layout == ["src/directory_layout/child/mod.rs"]


def test_one_hop_exact_go_module_import_resolves_root_package_only(tmp_path: Path):
    (tmp_path / "go.mod").write_text("module example.com/myproject\n\ngo 1.22\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "main.go").write_text(
        'package main\nimport "example.com/myproject"\n', encoding="utf-8"
    )
    (tmp_path / "root.go").write_text("package myproject\nfunc Root() {}\n", encoding="utf-8")
    (tmp_path / "sub/sub.go").write_text("package sub\nfunc Sub() {}\n", encoding="utf-8")
    eligible = {"main.go", "root.go", "sub/sub.go"}

    neighbors = one_hop_related_files(tmp_path, ["main.go"], eligible, RepositoryTools({}))

    assert neighbors == ["root.go"]


def test_one_hop_reuses_csharp_namespace_index_across_many_seeds(tmp_path: Path):
    (tmp_path / "src/Services").mkdir(parents=True)
    seeds = [f"src/Consumer{index}.cs" for index in range(4)]
    for seed in seeds:
        (tmp_path / seed).write_text("using Services.Auth;\n", encoding="utf-8")
    target = "src/Services/Auth.cs"
    (tmp_path / target).write_text("namespace Services.Auth { class Auth {} }\n", encoding="utf-8")
    eligible = CountingSet([*seeds, target])

    neighbors = one_hop_related_files(tmp_path, seeds, eligible, RepositoryTools({}))

    assert neighbors == [target]
    assert eligible.iterations == 1


def test_one_hop_csharp_import_requires_exact_declared_namespace(tmp_path: Path):
    (tmp_path / "src/Services").mkdir(parents=True)
    (tmp_path / "src/Program.cs").write_text("using Services.Auth;\n", encoding="utf-8")
    (tmp_path / "src/Auth.cs").write_text("namespace Other.Auth { class Auth {} }\n", encoding="utf-8")
    (tmp_path / "src/Services/Auth.cs").write_text("namespace Services.Auth { class Auth {} }\n", encoding="utf-8")
    eligible = {"src/Program.cs", "src/Auth.cs", "src/Services/Auth.cs"}

    neighbors = one_hop_related_files(tmp_path, ["src/Program.cs"], eligible, RepositoryTools({}))

    assert neighbors == ["src/Services/Auth.cs"]


def test_two_hop_reuses_path_and_csharp_namespace_indexes(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/Main.cs").write_text("using Services.Auth;\n", encoding="utf-8")
    (tmp_path / "src/Auth.cs").write_text(
        "using Services.Token;\nnamespace Services.Auth { class Auth {} }\n", encoding="utf-8"
    )
    (tmp_path / "src/Token.cs").write_text("namespace Services.Token { class Token {} }\n", encoding="utf-8")
    eligible = CountingSet({"src/Main.cs", "src/Auth.cs", "src/Token.cs"})

    neighbors = two_hop_weighted_files(tmp_path, ["src/Main.cs"], eligible, RepositoryTools({}))

    assert {path for path, _weight in neighbors} == {"src/Auth.cs", "src/Token.cs"}
    assert eligible.iterations == 1
