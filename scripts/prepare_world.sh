#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
mkdir -p .runtime
# Export the active constructor scene, or initialize the room preset.
"${RADIO_VENV:-.venv}/bin/python" - <<'PYEXPORT'
import json, uuid
from pathlib import Path
from app.scenario import normalize
from app.radio import export_gazebo
path=Path('.runtime/active_scene.json')
if path.exists(): active=json.loads(path.read_text())
else:
    active={'revision':uuid.uuid4().hex[:12],'scenario':normalize(json.loads(Path('config/scenario.json').read_text()))}
    path.write_text(json.dumps(active,indent=2))
export_gazebo(active['scenario'],'.runtime/world.sdf')
PYEXPORT
