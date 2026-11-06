#!/usr/bin/env bash
# Task 7: standard load test + kubectl top pods sampled during the run.
source scripts/lib.sh
OUT=results/task7_perf; mkdir -p "$OUT"; : > "$OUT/events.log"
kubectl -n app get deploy,hpa,pods -o wide | tee -a "$OUT/events.log"
( while true; do echo "=== $(ts)"; kubectl -n app top pods --no-headers; sleep 5; done ) > "$OUT/top_pods.txt" 2>&1 &
T=$!
loadtest 2m 4 4
kill $T
$PY scripts/summarize.py "$OUT" | tee "$OUT/summary.txt"
