#!/usr/bin/env bash
set -eo pipefail
# ROS environment scripts reference optional unset variables.
source /opt/ros/jazzy/setup.bash
set -u
mkdir -p /tmp/clearpath
cp /project/config/robot.yaml /tmp/clearpath/robot.yaml
python3 /project/app/ros_radio.py &
radio_pid=$!
ros2 launch /project/launch/husky.launch.py "$@" &
simulator_pid=$!
cleanup() {
  kill -TERM "$radio_pid" "$simulator_pid" 2>/dev/null || true
  wait "$radio_pid" "$simulator_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
set +e
wait -n "$radio_pid" "$simulator_pid"
status=$?
exit "$status"
