#!/usr/bin/env bash
# Task 4.8: exactly two Ready replicas, standard load test through the Ingress.
source scripts/lib.sh
OUT=results/task4_loadbalance; mkdir -p "$OUT"; : > "$OUT/events.log"
log "pinning HPA min=2 for this test (restored afterwards)"
kubectl -n app patch hpa parser -p '{"spec":{"minReplicas":2}}'
kubectl -n app scale deploy parser --replicas=2
kubectl -n app rollout status deploy parser --timeout=300s
kubectl -n app get pods -l app=parser -o wide | tee -a "$OUT/events.log"
loadtest 2m 4 4
kubectl -n app patch hpa parser -p '{"spec":{"minReplicas":1}}'
log "per-replica counts:"; cat "$OUT/loadtest_headers.json" | tee -a "$OUT/events.log"
