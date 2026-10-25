"""Validate deliberate radio-shadow goals before collecting experimental runs."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.engine import RadioWorker
from app.missions import mission,line_of_sight
from app.datasets import field_hash
from app.navigation import free


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='.runtime/reports/mission-preflight.json')
    args=parser.parse_args();results=[]
    for name in ('shadow','office','warehouse','district','courtyard'):
        for layout in (0,1):
            spec=mission(name,layout);scene=spec['scene'];config=spec['config']
            x,y=config['shadow_goal'];r=config['shadow_radius_m'];worker=RadioWorker(scene)
            try:
                points=[[x+dx,y+dy,.83228] for dx,dy in [(0,0),(r,0),(-r,0),(0,r),(0,-r)]]
                readings=[worker.sample(p,include_paths=False)['rssi_dbm'] for p in points]
                worst=max(v if v is not None else -160 for v in readings)
                passed=all(not line_of_sight(scene,p) and free(scene,*p[:2],.6) for p in points) and worst<=config['q_safe_dbm']-3
                row={'scene':scene['name'],'radio_field_sha256':field_hash(scene),'goal':[x,y],
                     'positions_m':points,'rssi_dbm':readings,'margin_db':config['q_safe_dbm']-worst,
                     'passed':passed,'used_for_controller_training':False}
                results.append(row);print(scene['name'],'PASS' if passed else 'FAIL',f'margin {row["margin_db"]:.1f} dB',flush=True)
            finally:worker.close()
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({'criterion':'Every probe occluded and 3dB below threshold','results':results},indent=2)+'\n')
    if not all(r['passed'] for r in results):raise SystemExit('Invalid shadow scenarios; do not start a campaign')


if __name__=='__main__':main()
