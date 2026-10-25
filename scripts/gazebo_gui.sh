#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
if [[ -z "${DISPLAY:-}" ]]; then
  printf '%s\n' 'Run this command in a Linux desktop terminal with DISPLAY set.' >&2
  exit 1
fi
command -v xauth >/dev/null || { printf '%s\n' 'Install xauth first: sudo apt install xauth' >&2; exit 1; }
container_id="$(docker compose ps -q husky)"
[[ -n "$container_id" ]] || { printf '%s\n' 'Start the project and a mission first.' >&2; exit 1; }
mkdir -p .runtime
auth_file="$(mktemp "$project_root/.runtime/gazebo-xauth.XXXXXX")"
trap 'rm -f "$auth_file"' EXIT
chmod 600 "$auth_file"
xauth nlist "$DISPLAY" | sed 's/^..../ffff/' | xauth -f "$auth_file" nmerge -
[[ -s "$auth_file" ]] || { printf '%s\n' 'No X11 authorization cookie found for this desktop session.' >&2; exit 1; }
partition=radio-lab
if [[ "${1:-}" == '--worker' ]]; then
  [[ "${2:-}" =~ ^[0-3]$ ]] || { printf '%s\n' 'Worker index must be 0..3.' >&2; exit 1; }
  partition="radio-lab-worker-$2"
fi
docker run --rm --network "container:$container_id" --user "$(id -u):$(id -g)" \
  -e DISPLAY -e XAUTHORITY=/tmp/desktop.xauth -e QT_QPA_PLATFORM=xcb \
  -e "GZ_PARTITION=$partition" -e GZ_HOMEDIR=/tmp/gazebo-gui \
  -e LIBGL_ALWAYS_SOFTWARE=1 -e QT_X11_NO_MITSHM=1 \
  -v /tmp/.X11-unix:/tmp/.X11-unix:ro -v "$auth_file:/tmp/desktop.xauth:ro" \
  --entrypoint bash ai-project-husky:dev -c 'source /opt/ros/jazzy/setup.bash; exec gz sim -g'
