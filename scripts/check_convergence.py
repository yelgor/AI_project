"""Check numerical sensitivity to ray budget, path depth and path-search seed."""
import argparse
import copy
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
os.environ.setdefault('RADIO_THREADS','1')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.engine import RadioWorker
from app.missions import mission


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=Path('.runtime/reports/convergence.json'));args=p.parse_args()
    rows=[]
    settings=[('baseline',10000,3,42),('more_rays',40000,3,42),('more_depth',40000,5,42),('another_seed',40000,5,43)]
    for name in ('shadow','office','warehouse','district','courtyard'):
        for layout in (0,1):
            spec=mission(name,layout);points={'los':[-4,3.5,.83228],'shadow':[*spec['config']['shadow_goal'],.83228]};baseline={}
            for label,rays,depth,seed in settings:
                scene=copy.deepcopy(spec['scene']);scene['radio']['solver'].update(samples_per_src=rays,max_num_paths_per_src=rays,max_depth=depth,seed=seed)
                worker=RadioWorker(scene)
                try:
                    for point_name,point in points.items():
                        result=worker.sample(point,include_paths=False);value=result['rssi_dbm']
                        if label=='baseline':baseline[point_name]=value
                        delta=value-baseline[point_name] if value is not None and baseline[point_name] is not None else None
                        rows.append({'scene':scene['name'],'point':point_name,'position_m':point,'setting':label,
                            'rays':rays,'depth':depth,'seed':seed,'rssi_dbm':value,'path_count':result['path_count'],
                            'delta_vs_baseline_db':delta,'shadow_below_threshold':value is None or value<spec['config']['q_safe_dbm']})
                finally:worker.close()
            print(spec['scene']['name'],'convergence probes complete',flush=True)
    changed=[r for r in rows if r['setting']!='baseline' and r['delta_vs_baseline_db'] is not None]
    output={'evaluation_only':True,'controller_training':False,'probes':rows,
        'maximum_absolute_delta_db':max(abs(r['delta_vs_baseline_db']) for r in changed),
        'all_shadow_centres_below_threshold':all(r['shadow_below_threshold'] for r in rows if r['point']=='shadow'),
        'software':{n:importlib.metadata.version(n) for n in ('sionna-rt','mitsuba','numpy')},
        'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'notes':['Finite probe sensitivity test; does not establish full-wave convergence or hardware accuracy.',
                 'Path-search seed is numerical sampling, not temporal radio fading.',
                 'Alternative solver budgets are distinct numerical fields and never replace the frozen campaign data.']}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(output,indent=2)+'\n')
    print('Maximum absolute RSSI change',output['maximum_absolute_delta_db'],'dB')
    print('All target centres remain below threshold:',output['all_shadow_centres_below_threshold'])


if __name__=='__main__':main()
