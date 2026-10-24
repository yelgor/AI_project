#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
# Preserve an existing .env; otherwise persist the checkout owner's IDs.
if [[ ! -e .env ]]; then
  printf 'LOCAL_UID=%s\nLOCAL_GID=%s\n' "$(id -u)" "$(id -g)" > .env
fi
export BUILDX_CONFIG="${BUILDX_CONFIG:-$PWD/.cache/buildx}"
bash scripts/setup_constructor.sh
if [[ -n "${RADIO_CA_BUNDLE:-}" ]]; then
  docker build --secret "id=proxy_ca,src=$RADIO_CA_BUNDLE" -f docker/Dockerfile.radio -t ai-project-radio:dev .
else
  docker compose build radio
fi
docker compose build husky
docker compose up --no-build --force-recreate -d
printf '%s\n' 'Services started. Run python scripts/check_api.py and the Husky check command in README; inspect docker compose logs -f.'
