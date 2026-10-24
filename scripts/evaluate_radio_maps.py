"""Fit each method on exactly the same causal prefix; evaluate a held-out grid."""
import argparse
import csv
import json
import math
from pathlib import Path
import sys
import zipfile
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.radio_maps import RadioMap
from app.datasets import field_hash


def files(path):
    path=Path(path)
    if path.is_dir(): return {name.name:name.read_bytes() for name in path.iterdir() if name.is_file()}
    with zipfile.ZipFile(path) as package: return {Path(n).name:package.read(n) for n in package.namelist()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('experiment'); parser.add_argument('reference',help='Completed grid ZIP/directory')
    parser.add_argument('--at',type=float,required=True,help='Decision sim time; observations use availability time')
    parser.add_argument('--min-distance',type=float,default=1.,help='Spatial holdout clearance in metres')
    parser.add_argument('--output',default='.runtime/reports/maps.csv')
    args=parser.parse_args(); exp=files(args.experiment); ref=files(args.reference)
    meta=json.loads(exp['manifest.json']); refmeta=json.loads(ref['manifest.json'])
    if refmeta.get('kind')!='grid' or refmeta.get('status')!='completed':raise SystemExit('Reference must be a completed grid dataset')
    scene=json.loads(exp['scenario.json'])
    if field_hash(scene)!=field_hash(json.loads(ref['scenario.json'])): raise SystemExit('Radio fields differ; collect reference for the same geometry, Tx and radio settings')
    timeline=[json.loads(line) for line in exp['timeline.jsonl'].decode().splitlines()]
    observations=[row['measurement'] for row in timeline if row['kind']=='observation' and row['sim_time_s']<=args.at]
    valid=[row for row in observations if row['rssi_dbm'] is not None]
    if not valid: raise SystemExit('No available observations at this time')
    rows=[json.loads(line) for line in ref['measurements.jsonl'].decode().splitlines()]
    points=np.asarray([row['position_m'] for row in valid])
    # Hold out positions in XY, including measurements not selected by the 150-point training cap.
    rows=[row for row in rows if row['rssi_dbm'] is not None and
          np.linalg.norm(points[:,:2]-np.asarray(row['position_m'])[:2],axis=1).min()>=args.min_distance]
    if not rows: raise SystemExit('No spatially held-out reference points; change the reference region')
    if args.min_distance<=0: raise SystemExit('--min-distance must be positive')
    # This experiment fits a fixed-height map; do not quietly score another antenna slice.
    z=np.asarray([r['position_m'][2] for r in valid])
    rows=[r for r in rows if abs(r['position_m'][2]-float(np.median(z)))<=.15]
    if not rows: raise SystemExit('Reference height does not match observed antenna height')
    target=np.asarray([row['rssi_dbm'] for row in rows]); results=[]
    for method in ('IDW','GPR-zero','GPR-pathloss'):
        model=RadioMap(method,scene['tx']['position'],meta['config']['noise_db'],meta['config']['optimize_gpr']).fit(observations)
        mean,std=model.predict([row['position_m'] for row in rows]); error=np.asarray(mean)-target
        result={'method':method,'at_sim_s':args.at,'available_observations':len(observations),
                'train_count':len(model.training_indices),'test_count':len(rows),'mae_db':float(np.abs(error).mean()),
                'rmse_db':float(np.sqrt((error**2).mean())),'nlpd':None,'coverage_95':None}
        if std and std[0] is not None:
            variance=np.asarray(std)**2+model.noise**2
            result['nlpd']=float((.5*np.log(2*math.pi*variance)+error**2/(2*variance)).mean())
            result['coverage_95']=float((np.abs(error)<=1.95996398454*np.sqrt(variance)).mean())
        results.append(result)
    output=Path(args.output); output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=results[0],lineterminator="\n");writer.writeheader();writer.writerows(results)
    print(json.dumps(results,indent=2)); print('Saved',output)


if __name__=='__main__': main()
