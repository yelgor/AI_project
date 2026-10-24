#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export npm_config_cache="${npm_config_cache:-$PWD/.cache/npm}"
command -v npm >/dev/null || { printf '%s\n' 'npm is missing. Install Node.js 22.12+ (includes npm), then rerun this script.' >&2; exit 1; }
node -e 'const [major,minor]=process.versions.node.split(".").map(Number);if(!(major>22||(major===22&&minor>=12)||(major===20&&minor>=19))){console.error("Node.js 20.19+ or 22.12+ is required; use Node 22 LTS.");process.exit(1)}'
bash scripts/setup_radio.sh
npm --prefix frontend ci
npm --prefix frontend run build
