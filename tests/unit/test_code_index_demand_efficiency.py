from __future__ import annotations

from pathlib import Path

from local_ai_hub.code_index_demand import one_hop_related_files, two_hop_weighted_files
from local_ai_hub.repo_tools import RepositoryTools


class IterationCountingSet(set[str]):
    def __init__(self, values):
        super().__init__(values)
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        return super().__iter__()


def test_php_use_resolution_indexes_eligible_paths_once(tmp_path: Path) -> None:
    names = [f"Service{i}" for i in range(12)]
    seed = "src/Http/Controller.php"
    controller = tmp_path / seed
    controller.parent.mkdir(parents=True)
    controller.write_text(
        "<?php\n" + "\n".join(f"use App\\Services\\{name};" for name in names),
        encoding="utf-8",
    )
    services = [f"src/Services/{name}.php" for name in names]
    decoys = [f"vendor/Legacy/Noise{i}.php" for i in range(1000)]
    eligible = IterationCountingSet([seed, *services, *decoys])
    original_order = list(eligible)
    eligible.iterations = 0

    result = one_hop_related_files(
        tmp_path, [seed], eligible, RepositoryTools({}),
    )

    expected = [
        service
        for name in names
        for service in original_order
        if Path(service).name == f"{name}.php"
    ]
    assert result == expected
    assert eligible.iterations == 1

    eligible.iterations = 0
    weighted_result = two_hop_weighted_files(
        tmp_path, [seed], eligible, RepositoryTools({}),
    )
    assert [path for path, _ in weighted_result] == sorted(expected)
    assert all(weight == 1.0 for _, weight in weighted_result)
    assert eligible.iterations == 1
