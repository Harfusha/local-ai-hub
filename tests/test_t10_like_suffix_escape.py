from contextlib import closing

import pytest

from local_ai_hub.code_index import CodeIndex


@pytest.mark.parametrize("wildcard", ["_", "%", "!"])
def test_call_queries_treat_like_metacharacters_as_literal_suffixes(tmp_path, wildcard) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    index = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, repo_tools=None)
    resolved = str(root.resolve())
    target = f"target{wildcard}tail"
    caller = f"caller{wildcard}tail"
    with closing(index._connect()) as con:
        con.executemany(
            "INSERT INTO edges(root,src,dst,kind,path,line) VALUES(?,?,?,?,?,?)",
            [
                (resolved, "Pkg::caller_exact", f"Pkg::{target}", "calls", "src/lib.rs", 1),
                (resolved, "Pkg::caller_false", "Pkg::targetXtail", "calls", "src/lib.rs", 2),
                (resolved, f"Pkg::{caller}", "Pkg::target_exact", "calls", "src/lib.rs", 3),
                (resolved, "Pkg::callerXtail", "Pkg::target_false", "calls", "src/lib.rs", 4),
            ],
        )
        con.commit()

    callers = index.find_callers(str(root), target)["callers"]
    callees = index.find_callees(str(root), caller)["callees"]

    assert [item["caller"] for item in callers] == ["Pkg::caller_exact"]
