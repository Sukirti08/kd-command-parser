# AI use

<!-- Fill in honestly. The assessor expects specifics, not a generic statement. -->

## Tools used

| Tool | Used for |
|---|---|
| Claude (Anthropic), claude.ai | Initial repository scaffold: Makefile, worker, clean.py, training/eval scripts, FastAPI service, Dockerfile, Kubernetes manifests, CI workflow, subnet working, NACL rule table, report outline |
| _add others_ | |

## How I checked the output

- **Unit tests**: `make test` (13 tests: cleaning rules and counts, shard coverage, schema validation, service endpoints and FAULT_INJECT). _Note any test you added or changed._
- **Manifests**: validated with kubeconform (Kubernetes 1.30 schemas), then deployed and observed with `kubectl`.
- **Subnets**: recomputed by hand and with Python's `ipaddress` module.
- **NACL**: `make nacl-check` against `packets_sample.jsonl`; _note whether the rule-file format needed changes_.
- **Training/evaluation**: numbers in the report are copied from files in `results/`, produced by my runs.
- _List anything the AI got wrong and how you found and fixed it (this is the most valuable part)._
