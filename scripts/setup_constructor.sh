#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export npm_config_cache="${npm_config_cache:-$PWD/.cache/npm}"
bash scripts/setup_radio.sh
npm --prefix frontend ci
npm --prefix frontend run build
