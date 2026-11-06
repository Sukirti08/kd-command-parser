#!/usr/bin/env bash
# Create .env with random S3 credentials if it does not exist. .env is git-ignored.
set -euo pipefail
if [ -f .env ]; then echo ".env exists"; exit 0; fi
rand() { python3 -c "import secrets,string;a=string.ascii_letters+string.digits;print(''.join(secrets.choice(a) for _ in range($1)))"; }
{
  echo "AWS_ACCESS_KEY_ID=$(rand 20)"
  echo "AWS_SECRET_ACCESS_KEY=$(rand 40)"
} > .env
chmod 600 .env
echo "created .env (random credentials, never committed)"
