#!/usr/bin/env bash
# Download model tarballs from GitHub Releases (or use dist/ if already present),
# verify checksums and publish them to s3://models/<version>/.
set -euo pipefail
REPO="${GITHUB_REPO:?set GITHUB_REPO=owner/name in the Makefile}"
PY="${PY:-python3}"
mkdir -p dist
for v in v1 v2; do
  tar="dist/model-$v.tar.gz"; sha="dist/model-$v.sha256"
  if [ ! -f "$tar" ]; then
    base="https://github.com/$REPO/releases/download/model-$v"
    curl -fsSL -o "$tar" "$base/model-$v.tar.gz"
    curl -fsSL -o "$sha" "$base/model-$v.sha256"
  fi
  (cd dist && sha256sum -c "model-$v.sha256")
  "$PY" training/package_model.py upload --tar "$tar" --version "$v"
done
