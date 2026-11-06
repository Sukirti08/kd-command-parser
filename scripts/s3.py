"""Host-side S3 helper for SeaweedFS (http://localhost:8333 via the k3d port map).

  python scripts/s3.py mb datasets models
  python scripts/s3.py put data/commands_pool.jsonl datasets/commands_pool.jsonl
  python scripts/s3.py get datasets/v1/train.jsonl results/data/train.jsonl
  python scripts/s3.py getdir datasets/teacher/ results/data/teacher/
  python scripts/s3.py ls [bucket[/prefix]]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from botocore.exceptions import ClientError, EndpointConnectionError  # noqa: E402

from worker import s3util  # noqa: E402


def wait(s3, tries=60):
    for _ in range(tries):
        try:
            s3.list_buckets()
            return
        except (EndpointConnectionError, ClientError):
            time.sleep(2)
    raise SystemExit("S3 endpoint not reachable")


def main(argv):
    s3 = s3util.client()
    cmd, args = argv[0], argv[1:]
    wait(s3)
    if cmd == "mb":
        have = {b["Name"] for b in s3.list_buckets().get("Buckets", [])}
        for b in args:
            if b not in have:
                s3.create_bucket(Bucket=b)
            print(f"bucket {b} ok")
    elif cmd == "put":
        bucket, key = s3util.split(args[1])
        s3.upload_file(args[0], bucket, key)
        print(f"put {args[0]} -> s3://{bucket}/{key}")
    elif cmd == "get":
        bucket, key = s3util.split(args[0])
        Path(args[1]).parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(bucket, key, args[1])
        print(f"get s3://{bucket}/{key} -> {args[1]}")
    elif cmd == "getdir":
        bucket, prefix = s3util.split(args[0])
        for key in s3util.list_keys(args[0], s3):
            dest = Path(args[1]) / key[len(prefix):]
            dest.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, key, str(dest))
            print(f"get s3://{bucket}/{key} -> {dest}")
    elif cmd == "ls":
        if not args:
            for b in s3.list_buckets().get("Buckets", []):
                print(b["Name"])
        else:
            bucket, prefix = s3util.split(args[0])
            for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
                for o in page.get("Contents", []):
                    print(f"{o['Size']:>12}  s3://{bucket}/{o['Key']}")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
