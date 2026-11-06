#!/usr/bin/env bash
# Shared helpers for experiment scripts. All evidence goes to results/<experiment>/.
set -euo pipefail
PY="${PY:-.venv/bin/python}"
LOCUST="${LOCUST:-.venv/bin/locust}"
HOST="${HOST:-http://localhost:8080}"
ts() { date '+%Y-%m-%dT%H:%M:%S'; }
log() { echo "[$(ts)] $*" | tee -a "$OUT/events.log"; }

# loadtest <run-time> [users] [spawn-rate]  -- the standard command, csv into $OUT
loadtest() {
  local rt="$1" users="${2:-4}" rate="${3:-4}"
  LOADTEST_HEADERS_OUT="$OUT/loadtest_headers.json" "$LOCUST" -f tools/locustfile.py --headless --users "$users" --spawn-rate "$rate" \
    --run-time "$rt" --host "$HOST" --csv "$OUT/loadtest" 2>&1 | tee "$OUT/locust_stdout.txt" || true
}

# watch_k8s <file> : sample deploy/hpa/pods every 5 s in the background; prints PID
watch_k8s() {
  ( while true; do
      echo "=== $(ts)"
      kubectl -n app get deploy parser -o wide --no-headers 2>&1
      kubectl -n app get hpa parser --no-headers 2>&1 || true
      kubectl -n app get pods -l app=parser --no-headers 2>&1
      kubectl -n app top pods --no-headers 2>&1 || true
      sleep 5
    done ) >> "$1" 2>&1 &
  echo $!
}
