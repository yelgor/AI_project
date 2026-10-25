#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/jazzy/setup.bash
mkdir -p /tmp/clearpath
python3 /project/scripts/prepare_robot.py /tmp/clearpath
python3 /project/scripts/prepare_husky_assets.py
python3 /project/scripts/prepare_husky_visuals.py
exec python3 /project/app/husky_runtime.py
