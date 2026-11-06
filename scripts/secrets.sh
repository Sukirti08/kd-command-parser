#!/usr/bin/env bash
# Create/refresh Kubernetes Secrets from .env. Nothing secret is ever written to the repo.
set -euo pipefail
set -a; . ./.env; set +a
S3JSON=$(printf '{"identities":[{"name":"admin","credentials":[{"accessKey":"%s","secretKey":"%s"}],"actions":["Admin","Read","Write","List","Tagging"]}]}' "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY")
kubectl -n data create secret generic seaweedfs-s3-config --from-literal=s3.json="$S3JSON" \
  --dry-run=client -o yaml | kubectl apply -f -
for ns in pipeline app; do
  kubectl -n "$ns" create secret generic s3-credentials \
    --from-literal=AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
    --from-literal=AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
    --dry-run=client -o yaml | kubectl apply -f -
done
