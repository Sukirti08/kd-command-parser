import json

import pytest

from worker.worker import select_shard


def test_shards_cover_every_line_exactly_once():
    lines = [json.dumps({"id": f"C{i:04d}", "text": "x"}) for i in range(3000)]
    for count in (2, 3, 4):
        ids = [r["id"] for i in range(count) for r in select_shard(lines, i, count)]
        assert sorted(ids) == sorted(json.loads(x)["id"] for x in lines)
        assert len(ids) == len(set(ids))


def test_shard_uses_line_number_modulo():
    lines = [json.dumps({"id": f"X{i}", "text": "x"}) for i in range(7)]
    assert [r["id"] for r in select_shard(lines, 1, 3)] == ["X1", "X4"]


def test_bad_shard_rejected():
    with pytest.raises(ValueError):
        select_shard([], 2, 2)
