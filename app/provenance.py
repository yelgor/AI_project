"""Identify the checked-out implementation when a service starts."""
import hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def implementation_hash():
    digest=hashlib.sha256()
    files=['app/builder.py','app/datasets.py','app/experiments.py','app/radio_maps.py',
           'app/radio.py','app/engine.py','app/scenario.py','app/navigation.py','app/husky_runtime.py',
           'app/provenance.py','launch/husky.launch.py','launch/navigation.launch.py','config/nav2.yaml']
    for name in files:
        digest.update(name.encode()+b'\0'+(ROOT/name).read_bytes()+b'\0')
    return digest.hexdigest()
