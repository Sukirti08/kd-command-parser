#!/usr/bin/env bash
# Task 4.7: delete all Pods three times; measure Pod creation -> Ready; keep download logs.
source scripts/lib.sh
OUT=results/task4_coldstart; mkdir -p "$OUT"; : > "$OUT/events.log"; : > "$OUT/times.txt"
for run in 1 2 3; do
  old=$(kubectl -n app get pods -l app=parser -o jsonpath='{.items[*].metadata.name}')
  log "run $run: deleting $old"
  kubectl -n app delete pods -l app=parser --wait=false
  sleep 3
  kubectl -n app wait --for=condition=Ready pod -l app=parser --timeout=300s
  sleep 2
  kubectl -n app get pods -l app=parser -o json > "$OUT/run${run}_pods.json"
  for p in $(kubectl -n app get pods -l app=parser -o jsonpath='{.items[*].metadata.name}'); do
    kubectl -n app logs "$p" > "$OUT/run${run}_${p}.log"
    grep -E "Downloaded model|loaded; ready" "$OUT/run${run}_${p}.log" | sed "s/^/[run$run $p] /" | tee -a "$OUT/events.log"
  done
  $PY - "$OUT/run${run}_pods.json" "$run" <<'PY' | tee -a "$OUT/times.txt"
import json, sys
from datetime import datetime
pods = json.load(open(sys.argv[1]))["items"]
f = lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
ts = []
for p in pods:
    ready = next(c["lastTransitionTime"] for c in p["status"]["conditions"] if c["type"] == "Ready")
    t = (f(ready) - f(p["metadata"]["creationTimestamp"])).total_seconds()
    ts.append(t); print(f"run {sys.argv[2]} pod {p['metadata']['name']}: {t:.0f}s")
print(f"run {sys.argv[2]} slowest {max(ts):.0f}s")
PY
  sleep 10
done
$PY - "$OUT/times.txt" <<'PY' | tee -a "$OUT/times.txt"
import re, statistics, sys
v = [float(m) for m in re.findall(r"slowest (\d+)s", open(sys.argv[1]).read())]
print(f"cold start (all replicas Ready) per run: {v}  median: {statistics.median(v):.0f}s")
PY
