"""Run a student model (trained dir or HF id) over a labelled file -> predictions.jsonl.

Each line: {"id": ..., "prediction": "<raw generated text>"} for tools/score.py.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "service"))
from app.inference import Generator  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="model dir or HF id, e.g. EleutherAI/pythia-70m")
    ap.add_argument("--data", default="data/validation.jsonl")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-new-tokens", type=int, default=48)
    a = ap.parse_args()

    gen = Generator(a.model, a.max_new_tokens)
    recs = [json.loads(ln) for ln in Path(a.data).read_text().splitlines() if ln.strip()]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with open(a.out, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps({"id": r["id"], "prediction": gen.generate(r["text"])},
                               ensure_ascii=False) + "\n")
    print(f"{len(recs)} predictions in {time.time() - t0:.1f}s -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
