#!/usr/bin/env bash
# Task 3: run the container at 1 CPU / 1 GiB, send 50 sequential requests, report peak memory.
# Needs the cluster's S3 on localhost:8333 (k3d port map). Evidence -> results/task3_memtest/.
set -euo pipefail
OUT=results/task3_memtest; mkdir -p "$OUT"
set -a; . ./.env; set +a
IMG="${IMG:-parser-service:0.1.0}"; NAME=parser-memtest
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --cpus 1 --memory 1g --memory-swap 1g -p 8000:8000 \
  --add-host=host.docker.internal:host-gateway \
  -e MODEL_URI=s3://models/v1/ -e MODEL_VERSION=v1 -e MAX_NEW_TOKENS=48 \
  -e S3_ENDPOINT=http://host.docker.internal:8333 -e FAULT_INJECT=0 \
  -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY "$IMG" | tee "$OUT/container_id.txt"

( while docker inspect "$NAME" >/dev/null 2>&1; do
    docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' "$NAME" 2>/dev/null
    sleep 1; done ) > "$OUT/docker_stats.txt" &
STATS=$!

echo "waiting for /readyz ..."
for _ in $(seq 1 180); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' localhost:8000/readyz)" = 200 ] && break; sleep 1
done
curl -si localhost:8000/readyz | head -1
.venv/bin/python - <<'PY' | tee "$OUT/requests.txt"
import json, time, urllib.request
recs = [json.loads(l) for l in open("data/validation.jsonl")][:50]
codes = {}
t0 = time.time()
for r in recs:
    req = urllib.request.Request("http://localhost:8000/parse", data=json.dumps({"text": r["text"]}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        code = urllib.request.urlopen(req, timeout=60).status
    except urllib.error.HTTPError as e:
        code = e.code
    codes[code] = codes.get(code, 0) + 1
print(f"50 sequential requests in {time.time()-t0:.1f}s, status codes: {codes}")
PY
echo "--- cgroup memory.peak (bytes) ---" | tee "$OUT/peak_memory.txt"
docker exec "$NAME" cat /sys/fs/cgroup/memory.peak 2>/dev/null | tee -a "$OUT/peak_memory.txt" || \
  echo "memory.peak unavailable (cgroup v1); use docker_stats.txt max" | tee -a "$OUT/peak_memory.txt"
kill $STATS 2>/dev/null || true
echo "--- max from docker stats ---" | tee -a "$OUT/peak_memory.txt"
sort -k3 -h "$OUT/docker_stats.txt" | tail -1 | tee -a "$OUT/peak_memory.txt"
echo "--- OOMKilled / restarts ---" | tee -a "$OUT/peak_memory.txt"
docker inspect -f 'OOMKilled={{.State.OOMKilled}} Status={{.State.Status}} RestartCount={{.RestartCount}}' "$NAME" | tee -a "$OUT/peak_memory.txt"
docker logs "$NAME" > "$OUT/container.log" 2>&1
echo "--- FAULT_INJECT=1 check ---" | tee "$OUT/fault_inject.txt"
docker rm -f "$NAME" >/dev/null
docker run -d --name "$NAME" --cpus 1 --memory 1g -p 8000:8000 --add-host=host.docker.internal:host-gateway \
  -e MODEL_URI=s3://models/v1/ -e MODEL_VERSION=v1 -e MAX_NEW_TOKENS=48 -e FAULT_INJECT=1 \
  -e S3_ENDPOINT=http://host.docker.internal:8333 -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY "$IMG" >/dev/null
for _ in $(seq 1 180); do [ "$(curl -s -o /dev/null -w '%{http_code}' localhost:8000/readyz)" = 200 ] && break; sleep 1; done
curl -si -X POST localhost:8000/parse -H 'Content-Type: application/json' -d '{"text":"what is the weather in london"}' | tee -a "$OUT/fault_inject.txt"
echo
docker rm -f "$NAME" >/dev/null
docker image ls "$IMG" | tee "$OUT/image_size.txt"
