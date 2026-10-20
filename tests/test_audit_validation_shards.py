import pytest


def test_shards_cover_each_identity_exactly_once():
    from tools.audit_pytest_shards import node_shard, parse_shard
    nodes = [f"tests/test_example.py::test_case[{index}]" for index in range(97)]
    partitions = [{node for node in nodes if node_shard(node, 16) == index} for index in range(16)]
    assert set.union(*partitions) == set(nodes)
    assert sum(map(len, partitions)) == len(nodes)
    assert parse_shard("15/16") == (15, 16)


@pytest.mark.parametrize("value", ["1/1", "-1/16", "01/16", "0/0", "0/33", "", None])
def test_shards_reject_invalid_selection(value):
    from tools.audit_pytest_shards import parse_shard
    with pytest.raises(ValueError):
        parse_shard(value)
