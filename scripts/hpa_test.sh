#!/usr/bin/env bash
# Task 4.4: show HPA scaling 1 -> 2 under load and back to 1 when idle.
source scripts/lib.sh
OUT=results/task4_hpa; mkdir -p "$OUT"; : > "$OUT/events.log"
kubectl -n app get hpa parser -o yaml > "$OUT/hpa.yaml"
log "scaling to 1 replica to start from the minimum"
kubectl -n app scale deploy parser --replicas=1
kubectl -n app rollout status deploy parser --timeout=180s
W=$(watch_k8s "$OUT/watch.txt")
log "load: 8 users for 4 minutes"
loadtest 4m 8 4
log "idle for 3 minutes (scale-down window 60 s)"
sleep 180
kill "$W"
kubectl -n app describe hpa parser > "$OUT/hpa_describe.txt"
grep -E 'parser +[0-9]+/[0-9]+|cpu:' "$OUT/watch.txt" | head -200 > "$OUT/replica_timeline.txt" || true
log "done; see $OUT/watch.txt and hpa_describe.txt (Events show SuccessfulRescale)"
