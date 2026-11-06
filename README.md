# Knowledge distillation + deployment of a command parser on k3d (CS3081 mini project)

**Repository:** https://github.com/Sukirti08/kd-command-parser  ← replace with your link
**Model releases:** `model-v1`, `model-v2` (assets: `model-vN.tar.gz`, `model-vN.sha256`)

Phi-3.5-mini (teacher, via Ollama, temperature 0, seed 42) labels 3,000 commands.
Pythia-70M (student) is fine-tuned on the cleaned teacher replies (sequence-level KD),
stored in SeaweedFS (S3), and served by a FastAPI service on a local k3d cluster
with probes, HPA, rolling updates and an Ingress.

```
cluster/k3d.yaml            cluster config (Traefik on :8080, S3 NodePort on :8333)
k8s/                        namespaces; data/ (SeaweedFS); pipeline/ (worker Job template); app/ (Deployment, Service, Ingress, HPA)
prompts/teacher_prompt.txt  teacher prompt
worker/                     worker.py (sharded labelling), clean.py, check_shards.py, Dockerfile
training/                   config.yaml, config_v2.yaml, train.py, predict.py, teacher_eval.py, package_model.py
service/                    FastAPI app + Dockerfile (CPU-only torch, no weights)
network/                    subnets.md, make_nacl.py, nacl.json, packets_sample.jsonl
scripts/                    S3/secrets helpers and one script per experiment
tests/                      unit tests
data/, tools/               the course kit, unchanged
results/                    all evidence (data counts, scores, Locust output, logs)
report/report.pdf           the report
```

## Prerequisites

Docker, k3d ≥ 5.6, kubectl, Python 3.11, GNU make, curl. For labelling/training also
Ollama (`ollama pull phi3.5`) and, for releases, the GitHub CLI `gh`.
**Windows:** run everything inside WSL2 (Ubuntu) with Docker Desktop's WSL integration on.
Ollama on Windows must listen on all interfaces so the cluster can reach it:
set the user environment variable `OLLAMA_HOST=0.0.0.0` and restart Ollama.

## Build and deploy (fresh clone, three commands)

```bash
git clone https://github.com/Sukirti08/kd-command-parser && cd kd-command-parser
make up          # .env with random S3 creds -> cluster -> SeaweedFS -> buckets -> data
                 # -> models from GitHub Release -> image -> Deployment/Service/Ingress/HPA
curl -s -X POST localhost:8080/parse -H 'Content-Type: application/json' \
     -d '{"text":"set an alarm for seven thirty am tomorrow"}'
```

## Tear down

```bash
make down        # deletes the k3d cluster
```

## Test

```bash
make lint test                     # ruff + unit tests
make nacl-check                    # NACL against the sample packets
locust -f tools/locustfile.py --headless --users 4 --spawn-rate 4 --run-time 2m \
       --host http://localhost:8080 --csv results/loadtest    # standard load test
```

## Full pipeline (how the results were produced)

| Task | Command | Evidence |
|---|---|---|
| 1 | `make up` then `make label SHARDS=2` (hours on CPU; `kubectl -n pipeline logs -f job/teacher-worker-0`) | `kubectl -n pipeline get jobs` output |
| 1 | `make shards` then `make clean-data` | `results/shard_check.txt`, `results/clean_counts.json`, `results/data/` |
| 2 | `make train SUBSET=50` (smoke), `make train`, `make train-v2` | `training/loss.csv`, `training/loss_v2.csv` |
| 2 | `make package release publish-models` | GitHub Releases, `s3://models/v1/`, `s3://models/v2/` |
| 2 | `make eval eval-teacher` | `results/*_predictions.jsonl`, `results/*_validation.json` |
| 3 | `make image mem-test` | `results/task3_memtest/` |
| 4 | `make hpa-test rolling-test recovery-test coldstart-test lb-test` | `results/task4_*/` |
| 5 | `make nacl-check` | `network/`, `results/nacl_check.txt` |
| 6 | push; Actions → *ci* → *Run workflow* with `model=untrained` | link in report |
| 7 | `make perf` | `results/task7_perf/` (Locust CSVs, `top_pods.txt`, `summary.txt`) |

Configuration lives in `Makefile` variables (`GITHUB_REPO`, `SHARDS`, `OLLAMA_URL`) and
`training/config.yaml`. No credentials are in the repository: `make env` writes random
credentials to the git-ignored `.env`, and `scripts/secrets.sh` turns them into
Kubernetes Secrets.
