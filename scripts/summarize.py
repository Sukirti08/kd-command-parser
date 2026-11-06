"""Summarise a load-test run: latency, throughput, error rate, pod CPU/memory,
cold start, SLO error budget and cost per 1,000 requests (from rate_card.json).

  python scripts/summarize.py results/task7_perf [--replicas 2 --cpu-limit 1 --mem-limit-gib 1]
  [--cpu-rate X --mem-rate Y]   (override if rate_card.json uses unexpected keys)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
from pathlib import Path


def locust_aggregate(d: Path) -> dict:
    with open(d / "loadtest_stats.csv") as f:
        rows = list(csv.DictReader(f))
    agg = next(r for r in rows if r.get("Name") == "Aggregated")
    return {
        "requests": int(agg["Request Count"]),
        "failures": int(agg["Failure Count"]),
        "p50_ms": float(agg.get("50%") or agg["Median Response Time"]),
        "p95_ms": float(agg["95%"]),
        "rps": float(agg["Requests/s"]),
    }


def top_pods(d: Path) -> dict:
    stats: dict[str, dict[str, list[float]]] = {}
    f = d / "top_pods.txt"
    if not f.exists():
        return {}
    for line in f.read_text().splitlines():
        m = re.match(r"(\S+)\s+(\d+)m\s+(\d+)Mi", line)
        if m:
            s = stats.setdefault(m[1], {"cpu_m": [], "mem_mi": []})
            s["cpu_m"].append(float(m[2]))
            s["mem_mi"].append(float(m[3]))
    return {p: {"cpu_m_avg": round(statistics.mean(v["cpu_m"])), "cpu_m_max": max(v["cpu_m"]),
                "mem_mi_avg": round(statistics.mean(v["mem_mi"])), "mem_mi_max": max(v["mem_mi"]),
                "samples": len(v["cpu_m"])} for p, v in stats.items()}


def find_rate(card, patterns) -> tuple[str, float] | None:
    """Depth-first search for a numeric value whose key path matches all patterns."""
    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                yield from walk(v, path + [str(k).lower()])
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            yield ".".join(path), float(o)
    for path, val in walk(card, []):
        if all(re.search(p, path) for p in patterns):
            return path, val
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--rate-card", default="data/rate_card.json")
    ap.add_argument("--replicas", type=int, default=2)
    ap.add_argument("--cpu-limit", type=float, default=1.0, help="cores per replica")
    ap.add_argument("--mem-limit-gib", type=float, default=1.0)
    ap.add_argument("--cpu-rate", type=float, help="price per vCPU-hour")
    ap.add_argument("--mem-rate", type=float, help="price per GiB-hour")
    ap.add_argument("--slo", type=float, default=99.0, help="success target in percent")
    a = ap.parse_args()
    d = Path(a.dir)
    lt = locust_aggregate(d)
    out = {"loadtest": lt, "error_rate_pct": round(100 * lt["failures"] / max(lt["requests"], 1), 3),
           "pods": top_pods(d)}

    cs = Path("results/task4_coldstart/times.txt")
    if cs.exists():
        m = re.search(r"median: (\d+)s", cs.read_text())
        out["cold_start_median_s"] = int(m[1]) if m else None

    budget = lt["requests"] * (100 - a.slo) / 100
    out["slo"] = {"target": f"{a.slo}% of /parse requests succeed (HTTP 200 within 30 s)",
                  "window": "one standard load-test run", "requests": lt["requests"],
                  "error_budget_requests": round(budget, 2), "failures": lt["failures"],
                  "budget_used_pct": round(100 * lt["failures"] / budget, 1) if budget else None}

    card = json.loads(Path(a.rate_card).read_text()) if Path(a.rate_card).exists() else {}
    cpu = (("--cpu-rate", a.cpu_rate) if a.cpu_rate is not None else find_rate(card, [r"cpu|vcpu"]))
    mem = (("--mem-rate", a.mem_rate) if a.mem_rate is not None else find_rate(card, [r"mem|gib|gb"]))
    if cpu and mem:
        per_replica = a.cpu_limit * cpu[1] + a.mem_limit_gib * mem[1]
        hourly = a.replicas * per_replica
        per_hour = lt["rps"] * 3600
        out["cost"] = {
            "rate_card_keys": {"cpu": cpu[0], "mem": mem[0]},
            "step1_per_replica_hour": (f"{a.cpu_limit} vCPU x {cpu[1]} + {a.mem_limit_gib} GiB x {mem[1]}"
                                       f" = {per_replica:.6f}"),
            "step2_all_replicas_hour": f"{a.replicas} x {per_replica:.6f} = {hourly:.6f}",
            "step3_requests_per_hour": f"{lt['rps']:.3f} req/s x 3600 = {per_hour:.1f}",
            "step4_cost_per_1000": f"{hourly:.6f} / {per_hour:.1f} x 1000 = {hourly / per_hour * 1000:.6f}",
            "NOTE": "check the units in rate_card.json match per-vCPU-hour and per-GiB-hour",
        }
    else:
        out["cost"] = "rate card keys not recognised: pass --cpu-rate and --mem-rate"
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
