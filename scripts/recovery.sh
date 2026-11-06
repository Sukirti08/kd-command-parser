#!/usr/bin/env bash
# Task 4.6: delete one Pod under load; Kubernetes restores the replica count.
source scripts/lib.sh
OUT=results/task4_recovery; mkdir -p "$OUT"; : > "$OUT/events.log"
kubectl -n app get deploy parser | tee -a "$OUT/events.log"
W=$(watch_k8s "$OUT/watch.txt")
( loadtest 3m 4 4 ) & L=$!
sleep 40
P=$(kubectl -n app get pods -l app=parser -o jsonpath='{.items[0].metadata.name}')
log "deleting pod $P"
kubectl -n app delete pod "$P" --wait=false
for _ in $(seq 1 120); do
  r=$(kubectl -n app get deploy parser -o jsonpath='{.status.readyReplicas}/{.spec.replicas}')
  log "ready $r"; [ "${r%/*}" = "${r#*/}" ] && break; sleep 2
done
wait $L; kill "$W"
kubectl -n app get deploy,pods -l app=parser | tee -a "$OUT/events.log"
