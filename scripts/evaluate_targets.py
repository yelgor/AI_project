"""Offline exact Sionna checks of each policy's first chosen recovery target."""
import argparse
import csv
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
os.environ.setdefault('RADIO_THREADS','1')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.engine import RadioWorker
from app.datasets import field_hash
from scripts.analyze_campaign import read_run


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('campaign',type=Path)
    p.add_argument('--runtime',type=Path,default=Path('.runtime'));args=p.parse_args()
    attempts=[json.loads(l) for l in (args.campaign/'attempts.jsonl').read_text().splitlines()];groups={};rows=[];queries=0
    for attempt in attempts:
        if not attempt.get('experiment_id'):continue
        meta,scene,events=read_run(args.runtime,attempt['experiment_id'])
        target=next((e['target'] for e in events if e['kind']=='target'),None)
        if target is None:continue
        observations={e['measurement']['observation_index']:e['measurement'] for e in events if e['kind']=='observation'}
        point=target.get('position_m') or observations[target['observation_index']]['position_m']
        groups.setdefault(field_hash(scene),{'scene':scene,'items':[]})['items'].append((attempt,target,point))
    for group in groups.values():
        worker=RadioWorker(group['scene']);cache={}
        try:
            for attempt,target,point in group['items']:
                key=tuple(point)
                if key not in cache:cache[key]=worker.sample(point,include_paths=False)['rssi_dbm'];queries+=1
                actual=cache[key];config=attempt['config'];mean=target['mean_dbm'];threshold=config['q_safe_dbm']
                rows.append({'experiment_id':attempt['experiment_id'],'scene':config['label'],'method':config['method'],
                    'beta':config['beta'],'noise_db':config['noise_db'],'predicted_dbm':mean,'actual_dbm':actual,
                    'prediction_error_db':mean-actual if actual is not None else None,
                    'actual_safe':actual is not None and actual>=threshold,
                    'planned_path_m':target['length_m'],'run_success':attempt.get('metrics',{}).get('success',False),
                    'x_m':point[0],'y_m':point[1],'z_m':point[2]})
        finally:worker.close()
    summary={'evaluation_only':True,'controller_training':False,'exact_queries':queries,'targets':len(rows),
        'groups':{},'software':{n:importlib.metadata.version(n) for n in ('sionna-rt','mitsuba','numpy')},
        'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'notes':['Checks the chosen target using the same frozen field, not a nearby coarse-grid approximation.',
                 'An unsafe target can still lead to successful recovery en route or after replanning.',
                 'Isotropic vertical antennas on the flat A200 world; robot-body RF is not simulated.']}
    for method,beta in sorted({(r['method'],r['beta']) for r in rows}):
        selected=[r for r in rows if r['method']==method and r['beta']==beta];errors=[r['prediction_error_db'] for r in selected if r['prediction_error_db'] is not None]
        summary['groups'][f'{method}/beta={beta}']={'selected_targets':len(selected),'actually_safe':sum(r['actual_safe'] for r in selected),
            'false_safe_fraction':sum(not r['actual_safe'] for r in selected)/len(selected),
            'mae_db':sum(abs(e) for e in errors)/len(errors) if errors else None}
    output=args.campaign/'target-study';output.mkdir(exist_ok=True)
    (output/'targets.json').write_text(json.dumps(summary,indent=2)+'\n')
    with (output/'targets.csv').open('w',newline='') as file:
        w=csv.DictWriter(file,fieldnames=rows[0] if rows else ['experiment_id'],lineterminator='\n');w.writeheader();w.writerows(rows)
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
