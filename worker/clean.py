"""Merge teacher shard outputs, reject bad records, write datasets/v1/train.jsonl.

Rejection reasons, checked in this order (a record is counted under the FIRST
reason it fails):
  (a) reply is not valid JSON                          -> invalid_json
  (b) not an object with exactly intent/date/time/place -> wrong_keys
  (c) intent not one of the eight                      -> bad_intent
  (d) a slot that is neither null nor a non-empty string
      found in the command (case-insensitive, whitespace-collapsed) -> slot_not_in_command
Then (e) duplicates: among surviving records, commands with the same normalised
text keep only the smallest id.

Output is deterministic: records sorted by id, one compact JSON object per
line with fixed key order, UTF-8, '\n' endings. Each record keeps the teacher's
reply byte-for-byte in `teacher_raw` and adds `target`, the same JSON
re-serialised compactly in key order (used as the training target).

Usage:
  python worker/clean.py --s3                       # read s3://datasets/teacher/, write s3://datasets/v1/
  python worker/clean.py --local-in DIR --local-out DIR
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KEYS = ["intent", "date", "time", "place"]
INTENTS = {
    "alarm_set", "alarm_query", "calendar_set", "calendar_query",
    "calendar_remove", "weather_query", "datetime_query", "recommendation_events",
}
REASONS = ["invalid_json", "wrong_keys", "bad_intent", "slot_not_in_command"]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def check(rec: dict) -> tuple[str | None, dict | None]:
    """Return (reason, None) for a rejected record or (None, parsed) for a good one."""
    try:
        obj = json.loads(rec["teacher_raw"])
    except (json.JSONDecodeError, TypeError):
        return "invalid_json", None
    if not isinstance(obj, dict) or set(obj.keys()) != set(KEYS) or len(obj) != 4:
        return "wrong_keys", None
    if not isinstance(obj["intent"], str) or obj["intent"] not in INTENTS:
        return "bad_intent", None
    command = norm(rec["text"])
    for k in ("date", "time", "place"):
        v = obj[k]
        if v is None:
            continue
        if not isinstance(v, str) or not norm(v) or norm(v) not in command:
            return "slot_not_in_command", None
    return None, obj


def clean(records: list[dict]) -> tuple[list[dict], dict]:
    records = sorted(records, key=lambda r: r["id"])
    counts = {"input": len(records), **{r: 0 for r in REASONS}, "duplicates": 0, "kept": 0}
    seen: set[str] = set()
    kept = []
    for rec in records:
        reason, obj = check(rec)
        if reason:
            counts[reason] += 1
            continue
        key = norm(rec["text"])
        if key in seen:
            counts["duplicates"] += 1
            continue
        seen.add(key)
        target = json.dumps({k: obj[k] for k in KEYS}, ensure_ascii=False)
        kept.append({"id": rec["id"], "text": rec["text"], "teacher_raw": rec["teacher_raw"],
                     "target": target})
    counts["kept"] = len(kept)
    assert counts["input"] == sum(counts[r] for r in REASONS) + counts["duplicates"] + counts["kept"]
    return kept, counts


def serialise(kept: list[dict]) -> bytes:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept).encode("utf-8")


def parse_shards(texts: list[str]) -> list[dict]:
    out = []
    for t in texts:
        out += [json.loads(ln) for ln in t.splitlines() if ln.strip()]
    ids = [r["id"] for r in out]
    if len(ids) != len(set(ids)):
        raise SystemExit("ERROR: an id appears in more than one shard (or twice in one shard)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--s3", action="store_true", help="read/write object storage")
    ap.add_argument("--in-prefix", default="s3://datasets/teacher/")
    ap.add_argument("--out-prefix", default="s3://datasets/v1/")
    ap.add_argument("--local-in", help="directory with shard-*.jsonl")
    ap.add_argument("--local-out", help="directory for train.jsonl/train.sha256")
    ap.add_argument("--counts-out", default="results/clean_counts.json")
    a = ap.parse_args()

    if a.s3:
        from worker import s3util
        s3 = s3util.client()
        bucket, _ = s3util.split(a.in_prefix)
        keys = [k for k in s3util.list_keys(a.in_prefix, s3) if k.endswith(".jsonl")]
        texts = [s3util.get_text(f"{bucket}/{k}", s3) for k in keys]
        print("shards:", keys)
    else:
        files = sorted(Path(a.local_in).glob("shard-*.jsonl"))
        texts = [f.read_text(encoding="utf-8") for f in files]
        print("shards:", [str(f) for f in files])

    kept, counts = clean(parse_shards(texts))
    data = serialise(kept)
    digest = hashlib.sha256(data).hexdigest()
    sha_line = f"{digest}  train.jsonl\n".encode()

    if a.s3:
        s3util.put_bytes(a.out_prefix.rstrip("/") + "/train.jsonl", data, s3)
        s3util.put_bytes(a.out_prefix.rstrip("/") + "/train.sha256", sha_line, s3)
    if a.local_out or not a.s3:
        out = Path(a.local_out or "results/data")
        out.mkdir(parents=True, exist_ok=True)
        (out / "train.jsonl").write_bytes(data)
        (out / "train.sha256").write_bytes(sha_line)
    Path(a.counts_out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.counts_out).write_text(json.dumps(counts, indent=2) + "\n")
    print(json.dumps(counts, indent=2))
    print("sha256:", digest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
