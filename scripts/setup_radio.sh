#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
radio_venv="${RADIO_VENV:-$project_root/.venv}"
python -m venv "$radio_venv"
mkdir -p "$project_root/.cache/pip" "$project_root/.cache/matplotlib"
PIP_CACHE_DIR="$project_root/.cache/pip" "$radio_venv/bin/python" -m pip install -r "$project_root/requirements-radio.txt"
MPLCONFIGDIR="$project_root/.cache/matplotlib" "$radio_venv/bin/python" "$project_root/scripts/smoke_sionna.py"
