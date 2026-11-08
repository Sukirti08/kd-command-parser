# AI use

## Tools used

| Tool | Used for |
|---|---|
| Claude (Anthropic), claude.ai | Repository scaffold (Makefile, worker, clean.py, training/evaluation scripts, FastAPI service, Dockerfile, Kubernetes manifests, CI workflow); step-by-step setup help for WSL2, Docker Desktop, k3d and Ollama on Windows; debugging; the report outline and the scripts that filled measured values into the report |

## How I checked the output

- **Unit tests and lint**: `make test lint` (13 tests: cleaning rules and counts, shard coverage, schema validation, service endpoints, FAULT_INJECT) passed locally and in GitHub Actions.
- **Manifests and behaviour**: everything was deployed on my k3d cluster and checked with `kubectl`, `curl` and the Locust load tests; every number in the report comes from a file in `results/`.
- **Kit tools as the reference**: `tools/score.py` for all model scores, `tools/nacl_sim.py` for the NACL (6/6), the kit's `locustfile.py` for every load test.
- **Subnets**: recomputed by hand and with Python's `ipaddress` module.
- **Data integrity**: `worker/check_shards.py` (3000 ids, no gaps or repeats) and the train.jsonl SHA-256; the counts table adds up to 3000.

## What the AI got wrong or did not anticipate, and how it was fixed

- The first teacher settings let phi3.5 keep generating extra few-shot examples after the JSON (~35 s per command on my CPU). Found from the Ollama request times; fixed with stop sequences and `num_predict=64` (~11 s per command).
- Port 8080 was taken by a Windows service on my laptop; the Ingress port was made configurable (`local.mk`, 8081 locally, 8080 remains the default).
- Windows throttled the idle laptop overnight and a restart made the worker Jobs exhaust their retries. Found from the per-hour request counts; fixed with `powercfg /powerthrottling disable`, a keep-awake loop and `backoffLimit: 100` (workers resumed from object storage).
- The cold-start script read logs of a Pod that was still terminating and stopped; fixed to wait for deletion first.
- The rolling-update script hung on a header check without a timeout; added `curl -m 20` and completed the rollback manually (`kubectl rollout undo`), logged in `results/task4_rolling/`.
- The first recovery and rolling-update runs used one replica (left by the HPA) and failed the targets; rerun with two replicas.
- A duplicate v2 training process was found with `ps` and stopped.
- Large GitHub Release uploads failed on my connection and left broken draft releases; deleted and re-uploaded with a retry loop.
