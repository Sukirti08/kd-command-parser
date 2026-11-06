"""Sharded teacher-labelling worker.

Env: SHARD_INDEX (from 0), SHARD_COUNT, S3_ENDPOINT, OLLAMA_URL, PROMPT_FILE,
INPUT_URI (default s3://datasets/commands_pool.jsonl),
OUTPUT_PREFIX (default s3://datasets/teacher/).

Takes commands whose 0-based line number n satisfies n % SHARD_COUNT == SHARD_INDEX
and writes {"id","text","teacher_raw"} lines to OUTPUT_PREFIX/shard-<i>.jsonl.
Resumable: on restart it reads its own object back and skips finished ids.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker import s3util, teacher  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("worker")


def select_shard(lines: list[str], index: int, count: int) -> list[dict]:
    """Records whose 0-based line number leaves remainder `index` mod `count`."""
    if count < 1 or not 0 <= index < count:
        raise ValueError(f"bad shard {index}/{count}")
    out = []
    for n, line in enumerate(lines):
        if n % count == index:
            out.append(json.loads(line))
    return out


def read_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip()]


def main() -> int:
    index = int(os.environ["SHARD_INDEX"])
    count = int(os.environ["SHARD_COUNT"])
    in_uri = os.environ.get("INPUT_URI", "s3://datasets/commands_pool.jsonl")
    out_uri = os.environ.get("OUTPUT_PREFIX", "s3://datasets/teacher/").rstrip("/") + f"/shard-{index}.jsonl"
    flush_every = int(os.environ.get("FLUSH_EVERY", "10"))

    s3 = s3util.client()
    pool = s3util.get_text(in_uri, s3)
    if pool is None:
        log.error("input %s not found", in_uri)
        return 1
    mine = select_shard(read_lines(pool), index, count)
    log.info("shard %d/%d: %d commands -> %s (teacher %s at %s)",
             index, count, len(mine), out_uri, teacher.TEACHER_MODEL, teacher.OLLAMA_URL)

    done_lines = read_lines(s3util.get_text(out_uri, s3) or "")
    done = {json.loads(ln)["id"] for ln in done_lines}
    if done:
        log.info("resuming: %d already labelled", len(done))

    template = teacher.load_prompt()
    t0, new = time.time(), 0
    for rec in mine:
        if rec["id"] in done:
            continue
        reply = teacher.ask(template, rec["text"])
        done_lines.append(json.dumps({"id": rec["id"], "text": rec["text"], "teacher_raw": reply},
                                     ensure_ascii=False))
        done.add(rec["id"])
        new += 1
        if new % flush_every == 0:
            s3util.put_bytes(out_uri, ("\n".join(done_lines) + "\n").encode(), s3)
            rate = new / (time.time() - t0)
            log.info("%d/%d done (%.2f cmd/s, eta %.0f min)", len(done), len(mine), rate,
                     (len(mine) - len(done)) / max(rate, 1e-9) / 60)
    s3util.put_bytes(out_uri, ("\n".join(done_lines) + "\n").encode(), s3)
    log.info("shard %d finished: %d records in %s", index, len(done_lines), out_uri)
    return 0


if __name__ == "__main__":
    sys.exit(main())
