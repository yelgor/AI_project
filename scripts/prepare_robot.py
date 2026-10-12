"""Prepare a writable Clearpath config using its supported URDF extras hook."""
from pathlib import Path
import sys
import yaml

ROOT=Path(__file__).resolve().parents[1]


def prepare_robot(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    data=yaml.safe_load((ROOT/'config/robot.yaml').read_text())
    data.setdefault('platform',{}).setdefault('extras',{})['urdf']={
        'package':None,'path':str(ROOT/'config/pose_publisher.urdf.xacro')}
    (directory/'robot.yaml').write_text(yaml.safe_dump(data,sort_keys=False))
    return directory


if __name__=='__main__': prepare_robot(sys.argv[1] if len(sys.argv)>1 else '/tmp/clearpath')
