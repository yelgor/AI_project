"""Tune radio-map profiles on train/validation fields, then score unseen fields.

Reference labels never enter the online policy. This is an offline map study,
not an additional physical recovery campaign or a learned Nav2 controller.
"""
import argparse
import csv
import json
import hashlib
import importlib.metadata
import math
import os
from pathlib import Path
import sys
import zipfile
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.radio_maps import RadioMap
from app.datasets import field_hash
from scripts.analyze_campaign import read_run


def load_cases(campaign,runtime,min_distance):
    sources=json.loads((campaign/'sources.json').read_text());cases=[]
    for name,source in sources.items():
        meta,scene,events=read_run(runtime,source['experiment_id']);observations=[]
        for e in events:
            if e['kind']=='observation':observations.append(e['measurement'])
            if e['kind']=='mode' and e['mode']=='LINK_DEGRADED':break
        else:raise ValueError('Source has no loss checkpoint')
        valid=[o for o in observations if o['rssi_dbm'] is not None]
        training=np.asarray([o['position_m'] for o in valid])
        with zipfile.ZipFile(campaign/'reference'/(name+'.zip')) as z:
            scene_name=next(n for n in z.namelist() if n.endswith('/scenario.json'))
            if field_hash(scene)!=field_hash(json.loads(z.read(scene_name))):raise ValueError('Reference RF field mismatch')
            manifest=json.loads(z.read(next(n for n in z.namelist() if n.endswith('/manifest.json'))))
            if manifest['status']!='completed' or not manifest['parameters'].get('evaluation_only'):raise ValueError('Need completed evaluation-only reference')
            raw=[json.loads(l) for l in z.read(next(n for n in z.namelist() if n.endswith('/measurements.jsonl'))).decode().splitlines()]
        reference=[r for r in raw if r['rssi_dbm'] is not None and abs(r['position_m'][2]-float(np.median(training[:,2])))<.1]
        points=np.asarray([r['position_m'] for r in reference]);values=np.asarray([r['rssi_dbm'] for r in reference])
        distance=np.linalg.norm(points[:,:2,None]-training[:,:2].T[None,:,:],axis=1).min(axis=1)
        keep=distance>=min_distance
        if not keep.any():raise ValueError('No independent spatial holdout positions for '+name)
        cases.append({'scene':name,'split':meta['config']['split'],'tx':scene['tx']['position'],
            'threshold':meta['config']['q_safe_dbm'],'observations':observations,
            'points':points[keep],'values':values[keep],'distance':distance[keep]})
    return cases


def evaluate(case,method,profile):
    model=RadioMap(method,case['tx'],**profile).fit(case['observations'])
    mean,std=model.predict(case['points']);mean=np.asarray(mean);error=mean-case['values']
    safe=mean>=case['threshold'];false_safe=safe&(case['values']<case['threshold'])
    row={'scene':case['scene'],'split':case['split'],'method':method,**profile,
         'available_count':len(case['observations']),'training_count':len(model.training_indices),'test_count':len(mean),
         'mae_db':float(np.abs(error).mean()),'rmse_db':float(np.sqrt(np.mean(error**2))),
         'false_safe_fraction':float(false_safe.mean()),'false_safe_given_predicted_safe':float(false_safe.sum()/safe.sum()) if safe.any() else None,
         'coverage_95':None,'nlpd':None}
    ratios=[]
    if std[0] is not None:
        sigma=np.asarray(std);variance=sigma**2+model.noise**2
        row.update(coverage_95=float(np.mean(np.abs(error)<=1.95996398454*np.sqrt(variance))),
                   nlpd=float(np.mean(.5*np.log(2*math.pi*variance)+error**2/(2*variance))))
        ratios=(error/np.maximum(.01,sigma)).tolist()
    row['distance_bins']={label:{'n':int(mask.sum()),'mae_db':float(np.abs(error[mask]).mean()) if mask.any() else None}
        for label,lo,hi in [('1–2m',1,2),('2–4m',2,4),('4m+',4,math.inf)]
        for mask in [(case['distance']>=lo)&(case['distance']<hi)]}
    return row,ratios


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('campaign',type=Path)
    p.add_argument('--runtime',type=Path,default=Path('.runtime'));p.add_argument('--min-distance',type=float,default=1.)
    args=p.parse_args();cases=load_cases(args.campaign,args.runtime,args.min_distance)
    if not all(any(c['split']==s for c in cases) for s in ('train','validation','test')):raise SystemExit('Need all three predeclared family splits')
    rows=[];recommended={}
    for method in ('IDW','GPR-zero','GPR-pathloss'):
        profiles=[{'noise_db':2.,'optimize':False}] if method=='IDW' else [
            {'noise_db':noise,'optimize':optimize} for noise in (2.,4.,8.) for optimize in (False,True)]
        ranked=[]
        for profile in profiles:
            scores=[]
            for case in cases:
                if case['split']!='train':continue
                row,_=evaluate(case,method,profile);row['stage']='training selection';rows.append(row);scores.append(row['mae_db'])
            ranked.append((float(np.mean(scores)),profile))
        finalists=sorted(ranked,key=lambda r:r[0])[:2];validation=[]
        for train_score,profile in finalists:
            values=[];ratios=[]
            for case in cases:
                if case['split']!='validation':continue
                row,r=evaluate(case,method,profile);row['stage']='validation selection';rows.append(row);values.append(row['mae_db']);ratios+=r
            validation.append((float(np.mean(values)),profile,ratios))
        val_score,profile,ratios=min(validation,key=lambda r:r[0])
        raw_beta=max(0.,float(np.quantile(ratios,.95))) if ratios else 0.
        recommended[method]={'noise_db':profile['noise_db'],'optimize_gpr':profile['optimize'],
            'validation_macro_mae_db':val_score,'empirical_validation_beta95':raw_beta,
            'beta_within_supported_range':raw_beta<=5,'beta':min(5.,raw_beta)}
        for case in cases:
            if case['split']!='test':continue
            row,_=evaluate(case,method,profile);row['stage']='frozen test';rows.append(row)
        print(method,recommended[method],flush=True)
    output=args.campaign/'reference-study';output.mkdir(exist_ok=True)
    summary={'minimum_spatial_distance_m':args.min_distance,'recommended_profiles':recommended,'scores':rows,
        'source_campaign':json.loads((args.campaign/'manifest.json').read_text())['campaign_id'],
        'software':{n:importlib.metadata.version(n) for n in ('numpy','scikit-learn')},
        'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'test_macro_mae_db':{m:float(np.mean([r['mae_db'] for r in rows if r['method']==m and r['stage']=='frozen test'])) for m in recommended},
        'notes':['Controller never reads reference grids; this study runs offline after collection.',
            '150-point cap applies to fitting; spatial holdout excludes points near every known observation.',
            'Top two profiles chosen on train families; final profile on validation families; test scored once per method.',
            'Empirical beta95 uses validation overprediction divided by latent sigma; it is not a general safety guarantee.',
            'These recommended profiles were not used retroactively in the physical campaign.',
            'Few related scene families limit evidence of generalization.']}
    (output/'study.json').write_text(json.dumps(summary,indent=2)+'\n')
    (output/'recommended-config.json').write_text(json.dumps(recommended,indent=2)+'\n')
    flat=[{k:v for k,v in r.items() if k!='distance_bins'} for r in rows]
    with (output/'scores.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=flat[0],lineterminator='\n');writer.writeheader();writer.writerows(flat)
    print('Frozen-test macro MAE (dB):',summary['test_macro_mae_db'])


if __name__=='__main__':main()
