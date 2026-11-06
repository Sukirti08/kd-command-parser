# ---------------------------------------------------------------------------
# KD command parser on k3d.  From a fresh clone:  git clone ... && cd ... && make up
# ---------------------------------------------------------------------------
SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -euo pipefail -c

CLUSTER     ?= kd
# set GITHUB_REPO to your public repository (owner/name)
GITHUB_REPO ?= Sukirti08/kd-command-parser
SHARDS      ?= 2
# Ollama on the laptop, as seen from inside k3d (Docker Desktop). On Linux try http://host.k3d.internal:11434
OLLAMA_URL  ?= http://host.docker.internal:11434
IMG         ?= parser-service:0.1.0
WORKER_IMG  ?= kd-worker:0.1.0
SUBSET      ?=
# Host port for the Ingress. 8080 is the standard; override in a git-ignored local.mk
# (e.g. `echo HTTP_PORT=8081 > local.mk`) if another program already uses 8080.
HTTP_PORT   ?= 8080
-include local.mk
export HTTP_PORT
VENV        := .venv
PY          := $(VENV)/bin/python
export PY
export S3_ENDPOINT ?= http://localhost:8333
export GITHUB_REPO

# S3 credentials for host-side commands come from the git-ignored .env (created by `make env`)
LOADENV := set -a; . ./.env; set +a;

.PHONY: help up down env venv venv-train cluster secrets storage buckets data-upload models \
        image worker-image deploy label shards clean-data train train-v2 package release \
        publish-models eval eval-teacher mem-test hpa-test rolling-test recovery-test \
        coldstart-test lb-test perf nacl-check lint test status

help:
	@grep -E '^[a-z-]+:.*##' Makefile | sed 's/:.*##/\t/' | column -t -s $$'\t'

## --- whole system -----------------------------------------------------------
up: env venv cluster secrets storage buckets data-upload models image deploy ## build + deploy everything
	@echo "Ready: curl -s -X POST localhost:$(HTTP_PORT)/parse -H 'Content-Type: application/json' -d '{\"text\":\"what is the weather in london\"}'"

down: ## delete the cluster
	k3d cluster delete $(CLUSTER)

status: ## show what is running
	kubectl get pods -A -o wide; kubectl -n app get deploy,svc,ingress,hpa

## --- building blocks --------------------------------------------------------
env:
	bash scripts/gen_env.sh

venv: $(VENV)/.host
$(VENV)/.host: requirements-host.txt
	python3 -m venv $(VENV)
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -r requirements-host.txt
	touch $@

venv-train: $(VENV)/.train
$(VENV)/.train: training/requirements.txt | venv
	$(PY) -m pip install -q -r training/requirements.txt
	touch $@

cluster:
	if ! k3d cluster list $(CLUSTER) >/dev/null 2>&1; then \
	  if [ "$(HTTP_PORT)" = "8080" ]; then k3d cluster create --config cluster/k3d.yaml; \
	  else sed "s/port: 8080:80 /port: $(HTTP_PORT):80 /" cluster/k3d.yaml > /tmp/k3d-local.yaml; \
	       k3d cluster create --config /tmp/k3d-local.yaml; fi; fi
	kubectl apply -f k8s/namespaces.yaml

secrets:
	bash scripts/secrets.sh

storage:
	kubectl apply -f k8s/data/seaweedfs.yaml
	kubectl -n data rollout status deploy/seaweedfs --timeout=300s

buckets: venv
	$(LOADENV) $(PY) scripts/s3.py mb datasets models

data-upload: venv
	$(LOADENV) $(PY) scripts/s3.py put data/commands_pool.jsonl datasets/commands_pool.jsonl
	$(LOADENV) if [ -d results/data/teacher ]; then for f in results/data/teacher/shard-*.jsonl; do \
	  $(PY) scripts/s3.py put $$f datasets/teacher/$$(basename $$f); done; fi
	$(LOADENV) if [ -f results/data/train.jsonl ]; then \
	  $(PY) scripts/s3.py put results/data/train.jsonl datasets/v1/train.jsonl; \
	  $(PY) scripts/s3.py put results/data/train.sha256 datasets/v1/train.sha256; fi

models: venv ## fetch model-v1/v2 release assets, verify, put in s3://models/
	$(LOADENV) bash scripts/fetch_models.sh

image: ## build the service image (no weights inside)
	docker build -f service/Dockerfile -t $(IMG) .
	k3d image import $(IMG) -c $(CLUSTER)

deploy:
	kubectl apply -f k8s/app/
	kubectl -n app rollout status deploy/parser --timeout=600s

## --- Task 1: teacher labelling ------------------------------------------------
worker-image:
	docker build -f worker/Dockerfile -t $(WORKER_IMG) .
	k3d image import $(WORKER_IMG) -c $(CLUSTER)

label: worker-image ## start SHARDS teacher workers in namespace pipeline
	for i in $$(seq 0 $$(( $(SHARDS) - 1 ))); do \
	  sed -e "s|\$${SHARD_INDEX}|$$i|g" -e "s|\$${SHARD_COUNT}|$(SHARDS)|g" \
	      -e "s|\$${OLLAMA_URL}|$(OLLAMA_URL)|g" k8s/pipeline/worker-job.yaml.tmpl | kubectl apply -f -; \
	done
	kubectl -n pipeline get jobs,pods

shards: venv ## download shard outputs and check coverage
	$(LOADENV) $(PY) scripts/s3.py getdir datasets/teacher/ results/data/teacher/
	$(LOADENV) $(PY) worker/check_shards.py | tee results/shard_check.txt

clean-data: venv ## run clean.py on the shard outputs (S3) -> datasets/v1 + results/data
	$(LOADENV) $(PY) worker/clean.py --s3 --local-out results/data
	cat results/data/train.sha256

## --- Task 2: training -----------------------------------------------------------
train: venv-train ## train v1 from training/config.yaml (make train SUBSET=50 for a quick run)
	$(PY) training/train.py --config training/config.yaml $(if $(SUBSET),--subset $(SUBSET),)

train-v2: venv-train
	$(PY) training/train.py --config training/config_v2.yaml

package: venv
	$(PY) training/package_model.py pack --model-dir training/out/v1 --version v1
	$(PY) training/package_model.py pack --model-dir training/out/v2 --version v2

release: ## publish dist/ tarballs as GitHub Release assets (needs gh auth)
	for v in v1 v2; do gh release create model-$$v dist/model-$$v.tar.gz dist/model-$$v.sha256 \
	  --title "Student model $$v" --notes "Pythia-70M distilled from phi3.5. sha256 in model-$$v.sha256"; done

publish-models: venv ## put local dist/ tarballs into s3://models/
	$(LOADENV) for v in v1 v2; do $(PY) training/package_model.py upload --tar dist/model-$$v.tar.gz --version $$v; done

eval: venv-train ## student + untrained Pythia on validation -> results/
	$(PY) training/predict.py --model training/out/v1 --out results/student_v1_predictions.jsonl
	python3 tools/score.py results/student_v1_predictions.jsonl data/validation.jsonl --out results/student_v1_validation.json
	$(PY) training/predict.py --model EleutherAI/pythia-70m --out results/untrained_predictions.jsonl
	python3 tools/score.py results/untrained_predictions.jsonl data/validation.jsonl --out results/untrained_validation.json

eval-teacher: venv ## teacher on validation (Ollama on localhost:11434)
	OLLAMA_URL=http://localhost:11434 $(PY) training/teacher_eval.py --out results/teacher_predictions.jsonl
	python3 tools/score.py results/teacher_predictions.jsonl data/validation.jsonl --out results/teacher_validation.json

## --- Tasks 3, 4, 7: experiments (evidence -> results/) ---------------------------
mem-test: ; bash scripts/mem_test.sh
hpa-test: ; bash scripts/hpa_test.sh
rolling-test: ; bash scripts/rolling_update.sh
recovery-test: ; bash scripts/recovery.sh
coldstart-test: ; bash scripts/cold_start.sh
lb-test: ; bash scripts/loadbalance.sh
perf: ; bash scripts/perf.sh

## --- Task 5 / 6 -------------------------------------------------------------------
nacl-check:
	python3 tools/nacl_sim.py network/nacl.json network/packets_sample.jsonl --check | tee results/nacl_check.txt

lint: venv
	$(VENV)/bin/ruff check .

test: venv
	$(VENV)/bin/pytest -q
