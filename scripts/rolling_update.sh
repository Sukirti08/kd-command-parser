#!/usr/bin/env bash
# Task 4.5: v1 -> v2 rolling update under load, then kubectl rollout undo.
source scripts/lib.sh
OUT=results/task4_rolling; mkdir -p "$OUT"; : > "$OUT/events.log"
hdr() { curl -s -m 20 -D - -o /dev/null -X POST "$HOST/parse" -H 'Content-Type: application/json' \
          -d '{"text":"set an alarm for six am"}' | grep -i x-model-version | tr -d '\r'; }
log "before: $(hdr)"
W=$(watch_k8s "$OUT/watch.txt")
( loadtest 6m 4 4 ) & L=$!
sleep 45
log "update -> v2"
kubectl -n app set env deploy/parser MODEL_VERSION=v2 MODEL_URI=s3://models/v2/
kubectl -n app rollout status deploy/parser --timeout=300s | tee -a "$OUT/events.log"
sleep 20; log "after update: $(hdr)"
sleep 40
log "rollback (kubectl rollout undo)"
kubectl -n app rollout undo deploy/parser
kubectl -n app rollout status deploy/parser --timeout=300s | tee -a "$OUT/events.log"
sleep 20; log "after rollback: $(hdr)"
wait $L; kill "$W"
kubectl -n app rollout history deploy/parser > "$OUT/rollout_history.txt"
log "failure %: see $OUT/loadtest_stats.csv (Aggregated row: Failure Count / Request Count)"
