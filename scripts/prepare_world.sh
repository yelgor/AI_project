#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
mkdir -p .runtime
"${RADIO_VENV:-.venv}/bin/python" app/radio.py export-gazebo .runtime/world.sdf
