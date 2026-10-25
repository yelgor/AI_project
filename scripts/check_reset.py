"""Verify warm reset while the actual Gazebo Husky is still moving."""
import argparse
import math
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.missions import mission
from scripts.run_experiments import API


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',default='http://127.0.0.1:8010');args=p.parse_args()
    api=API(args.url);scene=mission('shadow')['scene'];state=api.call('/api/state')
    if state['experiment'] and state['experiment']['status']=='running':raise SystemExit('Finish the current experiment first')
    api.call('/api/session/prepare',{'scene':scene,'reuse':True})
    try:
        api.wait(lambda s:s['navigation'].get('ready') and s['measurement'] is not None,timeout=60)
        for _ in range(15):api.call('/api/robot/control',{'linear':.5,'angular':.4});time.sleep(.1)
        before=api.call('/api/state')['robot_pose']
        reset=api.call('/api/session/prepare',{'scene':scene,'reuse':True})
        after=api.wait(lambda s:s['robot_status']=='running' and s['measurement'] is not None)['robot_pose']
        assert math.dist(after['position'][:2],scene['robot']['position'][:2])<.06
        assert after['sim_time_s']>before['sim_time_s']
        assert reset['preparation']['kind']=='warm' and reset['preparation']['radio_reused']
        print('Moving checkpoint reset OK:',reset['preparation'])
    finally:api.call('/api/robot/stop',{})


if __name__=='__main__':main()
