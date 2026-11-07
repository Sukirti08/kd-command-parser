---
title: "Knowledge Distillation and Deployment of a Command-Parsing Model on a Local Cloud"
author: "S Naveen — 230101100 — CS3081"
---
<!--
Fill every ⟨…⟩ from the files in results/. Never type a number that is not in a file.
Convert: pandoc report/report_template.md -o report/report.pdf  (≤ 8 pages + appendices)
Label everything as MEASURED (from a file) or ASSUMPTION.
-->

**Repository:** https://github.com/Sukirti08/kd-command-parser · **Tag:** `final` · **Machine:** Intel i5-1155G7 (4 cores/8 threads), 8 GB RAM, Windows 11 + WSL2 Ubuntu 24.04, Docker Desktop 4.98, k3d 5.9 (all measurements on this machine)

# Architecture

Laptop (Ollama + phi3.5) → k3d cluster `kd` (1 server node). Namespaces: `data` (SeaweedFS, S3 API
on 8333, buckets `datasets`, `models`), `pipeline` (sharded teacher Jobs), `app` (parser Deployment,
Service, Traefik Ingress `/parse`, HPA). The model is never in the image; Pods fetch `MODEL_URI` from
S3 at start-up using credentials from a Secret. ⟨insert diagram⟩

# Task 1 — Object storage and parallel teacher labelling

**Setup.** Cluster from `cluster/k3d.yaml`; SeaweedFS in `data`; `commands_pool.jsonl` in
`datasets`. Teacher: `phi3.5` on the laptop via Ollama, `temperature=0, seed=42`, `num_predict=64` and stop sequences `"\nCommand"`, `"\n\n"`,
prompt `prompts/teacher_prompt.txt` (rules + one example per intent, none from validation).

**Sharding.** Each worker reads `SHARD_INDEX` (from 0) and `SHARD_COUNT` and keeps line *n* of the pool
iff *n* mod `SHARD_COUNT` = `SHARD_INDEX`. The residues 0…k−1 partition the integers, so every line
belongs to exactly one shard: no gaps and no overlaps by construction (verified by
`worker/check_shards.py`, `results/shard_check.txt`). Modulo (interleaved) assignment also balances
shards to within one record and mixes command types evenly, unlike contiguous ranges. Each worker
writes only its own object `datasets/teacher/shard-<i>.jsonl`, so workers never contend for a write.
The object is re-uploaded every 10 records and a restarted worker skips ids already present, so a Job
retry resumes rather than restarts. Limitation: both workers share one Ollama process on one CPU,
so throughput barely improves with more shards; sharding pays off only with several teacher
replicas on separate cores or machines. MEASURED throughput: ⟨cmd/s from worker logs⟩, total time ⟨h⟩.

**What happened in practice (MEASURED).** On this 8 GB CPU-only laptop phi3.5 first took about 35 s per command because it kept generating extra few-shot examples after the JSON until `num_predict`; adding stop sequences cut this to about 11 s per command without changing the JSON. While the laptop sat idle overnight Windows throttled the CPU (about 5 commands per hour against about 250 per hour when active), which was fixed by disabling power throttling for Ollama and keeping the machine awake. A Windows restart stopped both worker Jobs (they exhausted their retries); after recreating them with `backoffLimit: 100` they resumed from the 730 records already saved in object storage, demonstrating the resumable, per-shard design.

**Cleaning counts** (MEASURED, `results/clean_counts.json`; checks applied in order a→d, each record
counted once, de-duplication by normalised text after filtering):

| Input | (a) invalid JSON | (b) wrong keys | (c) bad intent | (d) slot not in command | Duplicates | Kept |
|---|---|---|---|---|---|---|
| ⟨⟩ | ⟨⟩ | ⟨⟩ | ⟨⟩ | ⟨⟩ | ⟨⟩ | ⟨⟩ |

Check: input = a + b + c + d + duplicates + kept. SHA-256 of `train.jsonl`: ⟨⟩.
Decisions: slot match is case-insensitive with whitespace collapsed; empty strings fail (d);
`teacher_raw` is stored byte-for-byte, and `target` is the same JSON re-serialised compactly in key
order (a deterministic transformation, not a manual edit).

# Task 2 — Training the student

`training/config.yaml`: seed 42, lr 3e-4, batch 16, 8 epochs, max length 96, versions pinned.
Example format `Command: <text>\nJSON: <target><eos>`; loss on the JSON tokens only. v2 = 10 epochs.
Loss per epoch: `training/loss.csv` ⟨plot⟩. Training time MEASURED: ⟨⟩.
**Suitability of Pythia-70M.** ⟨Your assessment: 70M params, 2,048-token context, trained on the Pile,
not instruction-tuned; enough to learn a fixed output template, weak at semantics/rare slots.⟩

| Model (validation, 100) | json_validity | intent | date | time | place | full_frame |
|---|---|---|---|---|---|---|
| Teacher phi3.5 | 100.0 | 84.0 | 74.0 | 83.0 | 86.0 | 42.0 |
| Pythia-70M untrained | ⟨⟩ | ⟨⟩ | ⟨⟩ | ⟨⟩ | ⟨⟩ | ⟨⟩ |
| Student v1 | ⟨⟩ | ⟨⟩ | ⟨⟩ | ⟨⟩ | ⟨⟩ | ⟨⟩ |

⟨Discuss what changed, with 2–3 concrete error examples from the predictions files.⟩

**Sequence-level vs logit-based distillation.** (a) Sequence-level KD (Kim & Rush, 2016) trains the
student with ordinary cross-entropy on the teacher's *generated output sequence*: the teacher's
decoded reply is treated as the label for each input, so the student imitates the teacher's mode.
(b) Logit-based (token-level) KD trains the student to match the teacher's full *probability
distribution over the vocabulary at every position*, typically minimising KL divergence between
temperature-softened teacher and student softmaxes, which passes on "dark knowledge" about
plausible alternatives. (c) That is not possible here: Phi-3.5 and Pythia-70M use different
tokenizers and vocabularies (≈32k vs ≈50k tokens), so their distributions are over different
label sets and cannot be compared position by position; in addition Ollama returns only text,
not per-token logits. (d) Limitation: the student only ever sees the teacher's single greedy answer,
so it inherits the teacher's systematic errors (e.g. ⟨measured example from teacher predictions⟩)
with no signal about the teacher's uncertainty, and the cleaning step removes only *invalid*
replies, not *wrong but valid* ones.

# Task 3 — Inference service in a container

FastAPI on port 8000: `POST /parse`, `GET /healthz`, `GET /readyz` (503 until the model is loaded).
Config only from `MODEL_URI`, `MODEL_VERSION`, `S3_ENDPOINT`, `MAX_NEW_TOKENS`, `FAULT_INJECT`;
credentials from a Secret. Every output is validated against `schema.json`; invalid → HTTP 500
`{"error":"invalid_model_output"}`. Greedy decoding stops at the end of the first JSON object.
One generation at a time per Pod (lock) and `torch` set to 1 thread to match the 1-CPU limit.
Image: `python:3.11-slim`, CPU-only torch, all packages pinned, size MEASURED 1.27 GB on disk (273 MB compressed).
50 sequential requests at `--cpus 1 --memory 1g`: ⟨status codes, time⟩; peak memory MEASURED
⟨MiB⟩ (cgroup `memory.peak`); OOMKilled = ⟨false⟩ (`results/task3_memtest/`).

# Task 4 — Kubernetes deployment, scaling and reliability

Manifests in `k8s/app/`. Requests 500m CPU / 512Mi, limits 1 CPU / 1Gi. Readiness `/readyz`
(2 s), liveness `/healthz`. RollingUpdate `maxSurge 1, maxUnavailable 0` + 8 s `preStop` so
endpoints are removed before shutdown. Endpoints empty while loading: ⟨evidence⟩.

| Test | MEASURED result | Evidence |
|---|---|---|
| HPA 1→2→1 | ⟨times⟩ | `results/task4_hpa/` |
| Rolling update v1→v2 + undo | ⟨failed/total = %⟩; header after undo ⟨v1⟩ | `results/task4_rolling/` |
| Recovery (delete 1 Pod) | restored in ⟨s⟩; failures ⟨%⟩ | `results/task4_recovery/` |
| Cold start ×3 | ⟨s, s, s⟩ median ⟨s⟩ | `results/task4_coldstart/` |
| Load balancing (2 replicas) | ⟨pod-a n (x%), pod-b m (y%)⟩ | `results/task4_loadbalance/` |

**Limitations.** Single node: no fault tolerance across machines; a laptop failure takes down the
whole cluster, storage included (SeaweedFS has one replica on a local-path volume). HPA uses
metrics-server samples (~15 s) and CPU % of *request*, and max 2 replicas on shared laptop cores
means a second replica adds little real capacity. Host port 8080 was occupied by a Windows service (AgentService.exe), so on this laptop the Ingress was published on 8081 through a git-ignored `local.mk`; the repository default remains 8080.

# Task 5 — Subnetting and network ACL

Table and working: `network/subnets.md`. app 10.20.0.0/22, public 10.20.4.0/24, data 10.20.5.0/25,
management 10.20.5.128/27. NACL rules: `network/make_nacl.py` → `nacl.json`;
`nacl_sim.py --check`: 6/6 (100%). **Why:** a NACL is stateless and does not remember connections, so
every reply is judged as a new packet and needs its own rule (clients' ephemeral ports 1024–65535
outbound; app replies to the LB's ephemeral ports inbound). Rules are evaluated lowest number first
and the first match wins, so the deny for 198.51.100.0/24 (rule 90) must be numbered below the
allows for 80/443 (100/110); otherwise the allow would match first and admit the abusive range.

# Task 6 — Reproducibility, testing and CI/CD

`make up` (3 commands from a fresh clone), `make down`. Workflow `.github/workflows/ci.yml`:
lint (ruff) → unit tests (13) → evaluation (Release asset, checksum verified, `score.py`) →
quality gate (`--min-validity 95`); gitleaks in parallel. Passing run: ⟨link⟩.
**Failing gate run (untrained Pythia-70M):** ⟨link⟩, validity ⟨%⟩. Gitleaks: ⟨no leaks⟩.

# Task 7 — Performance, cost and review

MEASURED (standard Locust command, 2 replicas, `results/task7_perf/`): p50 ⟨⟩ ms, p95 ⟨⟩ ms,
throughput ⟨⟩ req/s, error rate ⟨⟩ %, per-Pod CPU/memory ⟨avg/max⟩, cold start ⟨median⟩ s.

**Cost** (rates ASSUMPTION from `rate_card.json`): per replica-hour = 1 vCPU × ⟨⟩ + 1 GiB × ⟨⟩ = ⟨⟩;
2 replicas = ⟨⟩/h; requests/h = ⟨rps⟩ × 3600 = ⟨⟩; cost per 1,000 = ⟨⟩ / ⟨⟩ × 1000 = **⟨⟩**.

**SLO:** 99% of `/parse` requests succeed (HTTP 200 within 30 s), window = one standard load-test run.
Requests ⟨N⟩ → error budget = 1% × N = ⟨⟩ requests; failures ⟨⟩ → ⟨%⟩ of the budget used.

| Concern | Evidence (measured) | Limitation found | Improvement |
|---|---|---|---|
| Data and storage | ⟨kept/3000, % rejected⟩ | ⟨⟩ | ⟨⟩ |
| Model quality | ⟨full_frame student vs teacher⟩ | ⟨⟩ | ⟨⟩ |
| Latency and throughput | ⟨p95, rps⟩ | ⟨⟩ | ⟨⟩ |
| Resource utilisation | ⟨CPU m, MiB per Pod⟩ | ⟨⟩ | ⟨⟩ |
| Reliability and recovery | ⟨rolling failures %, recovery s⟩ | ⟨⟩ | ⟨⟩ |
| Security and cost | ⟨cost/1000, gitleaks 0⟩ | ⟨⟩ | ⟨⟩ |

# References
Kim & Rush, EMNLP 2016; Chen et al., ACL 2020; Bastianelli et al., SLURP, EMNLP 2020; Biderman et al.,
Pythia, ICML 2023; documentation of k3d, SeaweedFS, Kubernetes, Hugging Face Transformers.
