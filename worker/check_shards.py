"""Verify every command id appears in exactly one shard output (no gaps, no repeats)."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default="data/commands_pool.jsonl")
    ap.add_argument("--shards", default="results/data/teacher")
    a = ap.parse_args()
    pool = [json.loads(ln)["id"] for ln in Path(a.pool).read_text().splitlines() if ln.strip()]
    seen = Counter()
    for f in sorted(Path(a.shards).glob("shard-*.jsonl")):
        ids = [json.loads(ln)["id"] for ln in f.read_text().splitlines() if ln.strip()]
        print(f"{f.name}: {len(ids)} records")
        seen.update(ids)
    missing = [i for i in pool if i not in seen]
    repeated = [i for i, c in seen.items() if c > 1]
    extra = [i for i in seen if i not in set(pool)]
    print(f"pool={len(pool)} covered={len(seen)} missing={len(missing)} repeated={len(repeated)} extra={len(extra)}")
    return 0 if not (missing or repeated or extra) else 1


if __name__ == "__main__":
    sys.exit(main())
