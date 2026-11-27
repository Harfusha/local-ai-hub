from local_ai_hub.plan_execution import partition_coverage


def config(index, digest="a" * 64, checks=None):
    return {"inventory": {"checks": checks or ["review"], "partition": {
        "manifest_sha256": digest, "size": 10, "total": 3, "index": index,
    }}}


def test_partitions_require_full_disjoint_manifest():
    assert partition_coverage([config(0), config(1), config(2)])[0]["complete"]
    result = partition_coverage([config(0), config(2), config(2)])[0]
    assert not result["complete"]
    assert result["missing_preview"] == [1]
    assert result["duplicate_count"] == 1


def test_partitions_never_combine_different_checks_or_manifests():
    groups = partition_coverage([config(0), config(1, checks=["test"]),
                                 config(2, digest="b" * 64)])
    assert len(groups) == 3
    assert not any(group["complete"] for group in groups)


def test_partitions_never_combine_different_exclusion_reasons():
    first, second, third = config(0), config(1), config(2)
    for item in (first, second):
        item["inventory"]["exclusions"] = [{"path": "a.py", "reason": "generated"}]
    third["inventory"]["exclusions"] = [{"path": "a.py", "reason": "out of scope"}]
    groups = partition_coverage([first, second, third])
    assert len(groups) == 2
    assert not any(group["complete"] for group in groups)
