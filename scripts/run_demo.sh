#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
start_mission=false
if [[ "${1:-}" == '--start' ]]; then start_mission=true; shift; fi
if (( $# )); then printf '%s\n' 'Usage: bash scripts/run_demo.sh [--start]' >&2; exit 2; fi
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
if [[ "$start_mission" == true ]]; then
  python3 scripts/start_demo.py
else
  printf '%s\n' 'Services started. Open http://127.0.0.1:8010/experiments.html and click ▶ Запустити місію. Logs: docker compose logs -f radio husky.'
fi
printf '%s\n' 'GPR learning, tests and recorded replays: http://127.0.0.1:8010/research.html (no new mission or import needed).'
