"""Reconstruct GPR learning on recorded prefixes, without running Gazebo.

Learning curves use only train/validation families. A fixed spatial holdout
excludes every position within 1m of the FULL pre-loss prefix at every step.
"""
import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import sys
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.evidence import EvidenceLibrary,LIBRARY,ROOT
from app.radio_maps import RadioMap
from app.datasets import field_hash

PROFILES=[{'id':'gpr-baseline','label':'GPR-pathloss · noise 2 dB','method':'GPR-pathloss','noise_db':2.},
          {'id':'gpr-tuned','label':'GPR-pathloss · noise 8 dB','method':'GPR-pathloss','noise_db':8.},
          {'id':'idw','label':'IDW · порівняння','method':'IDW','noise_db':2.}]


def fixed_holdout(points,observations,distance=1.):
    known=np.asarray([o['position_m'] for o in observations if o['rssi_dbm'] is not None])
    return np.linalg.norm(np.asarray(points)[:,:2,None]-known[:,:2].T[None,:,:],axis=1).min(axis=1)>=distance


def build(library):
    fields=[]
    for name,source in sorted(library.sources().items()):
        run=library.run('baseline-100',source['experiment_id']);config=run['manifest']['config']
        if config['split']=='test':continue  # Frozen-test figures remain the previously recorded scores.
        observations=[]
        for event in run['timeline']:
            if event['kind']=='observation':observations.append(event['measurement'])
            if event['kind']=='mode' and event['mode']=='LINK_DEGRADED':break
        else:raise ValueError('Source has no loss checkpoint')
        ref=library.reference(name);scene=run['scenario']
        if field_hash(scene)!=field_hash(ref['scenario']):raise ValueError('Reference field differs')
        z=float(np.median([o['position_m'][2] for o in observations]))
        rows=[r for r in ref['measurements'] if abs(r['position_m'][2]-z)<.1]
        points=[r['position_m'] for r in rows];truth=[r['rssi_dbm'] for r in rows]
        mask=fixed_holdout(points,observations)&np.asarray([v is not None for v in truth])
        y=np.asarray([v if v is not None else 0 for v in truth],dtype=float)
        counts=sorted({n for n in (4,8,16,32,48,64,len(observations)) if n<=len(observations)})
        frames=[]
        for profile in PROFILES:
            for count in counts:
                model=RadioMap(profile['method'],scene['tx']['position'],profile['noise_db']).fit(observations[:count])
                mean,std=model.predict(points);error=np.asarray(mean)[mask]-y[mask]
                score={'mae_db':float(np.abs(error).mean()),'rmse_db':float(np.sqrt(np.mean(error**2))),
                       'test_count':int(mask.sum()),'coverage_95':None}
                if std[0] is not None:
                    sigma=np.sqrt(np.asarray(std)[mask]**2+profile['noise_db']**2)
                    score['coverage_95']=float(np.mean(np.abs(error)<=1.95996398454*sigma))
                frames.append({'profile':profile['id'],'available_count':count,'training_count':len(model.training_indices),
                    'training_indices':model.training_indices,'available_at_sim_time_s':observations[count-1]['available_at_sim_time_s'],
                    'mean_dbm':[round(float(v),3) for v in mean],
                    'std_db':[round(float(v),3) if v is not None else None for v in std], 'score':score})
        fields.append({'name':name,'split':config['split'],'source_experiment_id':source['experiment_id'],
            'radio_field_sha256':field_hash(scene),'scene':scene,'reference_positions':points,'reference_rssi_dbm':truth,
            'holdout_indices':np.flatnonzero(mask).tolist(),'observations':[{'position_m':o['position_m'],
                'rssi_dbm':o['rssi_dbm'],'sim_time_s':o['sim_time_s'],'available_at_sim_time_s':o['available_at_sim_time_s']} for o in observations],
            'counts':counts,'frames':frames})
        print(name,len(observations),'recorded observations;',int(mask.sum()),'fixed spatial holdout points',flush=True)
    return {'format_version':1,'data_origin':'recorded_simulation','hardware_validation':False,
        'profiles':PROFILES,'fields':fields,'heldout_distance_m':1.,
        'source_archive_sha256':hashlib.sha256((library.root/'baseline-100.zip').read_bytes()).hexdigest(),
        'model_source_sha256':hashlib.sha256((ROOT/'app/radio_maps.py').read_bytes()).hexdigest(),
        'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'software':{n:importlib.metadata.version(n) for n in ('numpy','scikit-learn')},
        'notes':['Reconstructed posterior fits on the original measured prefixes; these are sample counts, not neural-network epochs.',
            'Only train/validation fields are used for prefix learning curves; frozen-test metrics come from the original study.',
            'The fixed holdout excludes neighbours of ALL pre-loss observations, including observations not yet admitted in an early frame.',
            'Reference labels never enter a fit. Curves may increase as well as decrease.',
            'Prediction arrays are rounded to 3 decimals for display; scores use unrounded predictions.']}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--library',type=Path,default=LIBRARY)
    p.add_argument('--output',type=Path,default=LIBRARY/'learning-evidence.json');args=p.parse_args()
    result=build(EvidenceLibrary(args.library));args.output.write_text(json.dumps(result,separators=(',',':'),allow_nan=False)+'\n')
    print('Saved',args.output)
