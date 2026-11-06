"""Teacher on validation.jsonl, same prompt and settings as Task 1 -> predictions.jsonl."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from worker import teacher  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/validation.jsonl")
    ap.add_argument("--out", default="results/teacher_predictions.jsonl")
    a = ap.parse_args()
    template = teacher.load_prompt()
    recs = [json.loads(ln) for ln in Path(a.data).read_text().splitlines() if ln.strip()]
    with open(a.out, "w", encoding="utf-8") as f:
        for i, r in enumerate(recs, 1):
            f.write(json.dumps({"id": r["id"], "prediction": teacher.ask(template, r["text"])},
                               ensure_ascii=False) + "\n")
            f.flush()
            print(f"{i}/{len(recs)}", end="\r")
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
