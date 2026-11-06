"""Sequence-level knowledge distillation: fine-tune Pythia-70M on teacher replies.

Each example is   "Command: <command>\nJSON: <teacher JSON>" + EOS
Loss is computed on the JSON part only (prompt tokens are masked with -100),
so the student learns p(teacher reply | command).

Usage: python training/train.py --config training/config.yaml [--subset 50]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import platform
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch
import transformers
import yaml
from torch.utils.data import DataLoader
from transformers import AutoModelForCausalLM, AutoTokenizer, get_linear_schedule_with_warmup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "service"))
from app.inference import build_example  # noqa: E402


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    transformers.set_seed(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)


def check_versions(expected: dict) -> None:
    actual = {"python": platform.python_version(), "torch": torch.__version__.split("+")[0],
              "transformers": transformers.__version__, "pyyaml": yaml.__version__}
    import tokenizers
    actual["tokenizers"] = tokenizers.__version__
    for k, v in expected.items():
        if k in actual and not actual[k].startswith(str(v)):
            print(f"WARNING: {k} {actual[k]} != config {v}", file=sys.stderr)
    print("library versions:", actual)


def load_records(path: str, limit: int) -> list[dict]:
    lines = [ln for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]
    recs = [json.loads(ln) for ln in lines]
    return recs[:limit]


def encode(recs: list[dict], tok, max_len: int) -> list[dict]:
    out, truncated = [], 0
    for r in recs:
        prompt, completion = build_example(r["text"], r["target"])
        p_ids = tok(prompt)["input_ids"]
        c_ids = tok(completion)["input_ids"] + [tok.eos_token_id]
        ids = (p_ids + c_ids)[:max_len]
        labels = ([-100] * len(p_ids) + c_ids)[:max_len]
        truncated += len(p_ids) + len(c_ids) > max_len
        out.append({"input_ids": ids, "labels": labels})
    if truncated:
        print(f"WARNING: {truncated} examples truncated to {max_len} tokens", file=sys.stderr)
    return out


def collate(batch, pad_id):
    n = max(len(b["input_ids"]) for b in batch)
    ids = torch.full((len(batch), n), pad_id, dtype=torch.long)
    lab = torch.full((len(batch), n), -100, dtype=torch.long)
    att = torch.zeros((len(batch), n), dtype=torch.long)
    for i, b in enumerate(batch):
        L = len(b["input_ids"])
        ids[i, :L] = torch.tensor(b["input_ids"])
        lab[i, :L] = torch.tensor(b["labels"])
        att[i, :L] = 1
    return {"input_ids": ids, "labels": lab, "attention_mask": att}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="training/config.yaml")
    ap.add_argument("--subset", type=int, default=0, help="train on the first N records only")
    a = ap.parse_args()
    cfg = yaml.safe_load(Path(a.config).read_text())

    set_seed(cfg["seed"])
    check_versions(cfg.get("library_versions", {}))
    if cfg.get("torch_threads"):
        torch.set_num_threads(cfg["torch_threads"])

    limit = min(cfg["max_train_records"], a.subset or cfg["max_train_records"])
    recs = load_records(cfg["data_path"], limit)
    out_dir = Path(cfg["output_dir"] + (f"-subset{a.subset}" if a.subset else ""))
    print(f"training on {len(recs)} records -> {out_dir}")

    tok = AutoTokenizer.from_pretrained(cfg["model_name"], revision=cfg["model_revision"])
    tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(cfg["model_name"], revision=cfg["model_revision"])
    model.train()

    data = encode(recs, tok, cfg["max_seq_length"])
    g = torch.Generator().manual_seed(cfg["seed"])
    loader = DataLoader(data, batch_size=cfg["batch_size"], shuffle=True, generator=g,
                        collate_fn=lambda b: collate(b, tok.pad_token_id))
    opt = torch.optim.AdamW(model.parameters(), lr=cfg["learning_rate"],
                            weight_decay=cfg["weight_decay"])
    total = len(loader) * cfg["epochs"]
    sched = get_linear_schedule_with_warmup(opt, math.ceil(total * cfg["warmup_ratio"]), total)

    loss_path = Path("training/loss.csv" if not a.subset else f"training/loss-subset{a.subset}.csv")
    if cfg.get("version", "v1") != "v1" and not a.subset:
        loss_path = Path(f"training/loss_{cfg['version']}.csv")
    rows = []
    t0 = time.time()
    for epoch in range(1, cfg["epochs"] + 1):
        tot, n = 0.0, 0
        for batch in loader:
            loss = model(**batch).loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            opt.zero_grad()
            tot += loss.item()
            n += 1
        rows.append({"epoch": epoch, "train_loss": round(tot / n, 6),
                     "elapsed_s": round(time.time() - t0, 1)})
        print(f"epoch {epoch}: loss {tot / n:.4f} ({time.time() - t0:.0f}s)")
        with loss_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["epoch", "train_loss", "elapsed_s"])
            w.writeheader()
            w.writerows(rows)

    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out_dir, safe_serialization=True)
    tok.save_pretrained(out_dir)
    (out_dir / "version.json").write_text(json.dumps({
        "version": cfg.get("version", "v1"), "base_model": cfg["model_name"],
        "train_records": len(recs), "epochs": cfg["epochs"], "seed": cfg["seed"],
        "learning_rate": cfg["learning_rate"], "batch_size": cfg["batch_size"],
        "max_seq_length": cfg["max_seq_length"], "final_loss": rows[-1]["train_loss"],
    }, indent=2) + "\n")
    print(f"saved to {out_dir}; loss log {loss_path}")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    sys.exit(main())
