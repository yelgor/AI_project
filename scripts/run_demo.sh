#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export BUILDX_CONFIG="${BUILDX_CONFIG:-$PWD/.cache/buildx}"
bash scripts/setup_radio.sh
bash scripts/prepare_world.sh
if [[ -n "${RADIO_CA_BUNDLE:-}" ]]; then
  docker build --secret "id=proxy_ca,src=$RADIO_CA_BUNDLE" -f docker/Dockerfile.radio -t ai-project-radio:dev .
else
  docker compose build radio
fi
docker compose build husky
docker compose up --no-build -d
printf '%s\n' 'Services started. Run python scripts/check_api.py and the Husky check command in README; inspect docker compose logs -f.'
