"""Audit every physical outcome and score causal forecasts by spatial proximity.

Reads a campaign directory and shared .runtime tree; never changes a controller.
Seed observations are not counted as newly collected measurements. Confidence
intervals across episodes are descriptive: repeated runs share fields/histories.
"""
import argparse
import csv
import json
import math
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.radio_maps import RadioMap
from app.navigation import free
from scripts.run_experiments import wilson


def read_run(runtime,identity):
    candidates=[runtime/'experiments'/identity,*(runtime/'workers').glob('*/experiments/'+identity)]
    path=next(p for p in candidates if (p/'manifest.json').exists())
    return (json.loads((path/'manifest.json').read_text()),json.loads((path/'scenario.json').read_text()),
            [json.loads(line) for line in (path/'timeline.jsonl').read_text().splitlines()])


def outcomes(rows):
    success=sum(bool(r.get('success')) for r in rows);total=len(rows)
    return {'attempts':total,'physical_starts':sum(bool(r.get('experiment_id')) for r in rows),
        'successes':success,'success_fraction_all_attempts':success/total if total else None,
        'wilson_95_descriptive':wilson(success,total),
        **{key:float(np.median(values)) if values else None for key in
           ('recovery_time_s','recovery_path_length_m','return_to_known_safe_m','path_stretch')
           for values in [[r[key] for r in rows if r.get('success') and r.get(key) is not None]]}}


def forecast_scores(rows):
    if not rows:return {'n':0}
    error=np.asarray([r['predicted_dbm']-r['actual_dbm'] for r in rows]);result={
        'n':len(rows),'mae_db':float(np.abs(error).mean()),'rmse_db':float(np.sqrt(np.mean(error**2))),
        'bias_db':float(error.mean()),'false_safe_fraction':float(np.mean([
            r['predicted_dbm']>=r['threshold_dbm'] and r['actual_dbm']<r['threshold_dbm'] for r in rows]))}
    predicted_safe=[r for r in rows if r['predicted_dbm']>=r['threshold_dbm']]
    result['predicted_safe_count']=len(predicted_safe)
    result['false_safe_given_predicted_safe']=sum(r['actual_dbm']<r['threshold_dbm'] for r in predicted_safe)/len(predicted_safe) if predicted_safe else None
    if rows[0]['std_db'] is not None:
        variance=np.asarray([r['std_db']**2+r['noise_db']**2 for r in rows])
        result.update(coverage_95=float(np.mean(np.abs(error)<=1.95996398454*np.sqrt(variance))),
                      nlpd=float(np.mean(.5*np.log(2*math.pi*variance)+error**2/(2*variance))))
    return result


def analyze(campaign,runtime,output):
    output.mkdir(parents=True,exist_ok=True)
    attempts=[json.loads(line) for line in (campaign/'attempts.jsonl').read_text().splitlines()]
    meta=json.loads((campaign/'manifest.json').read_text());rows=[];new_count=0;seed_count=0;forecasts=[]
    for attempt in attempts:
        config=attempt['config'];row={'experiment_id':attempt.get('experiment_id'),'status':attempt['status'],
            'label':config.get('label'),'method':config['method'],'beta':config['beta'],'split':config.get('split'),
            'family':config.get('label','').rsplit('-',1)[0],
            'reason':attempt.get('reason'),**attempt.get('metrics',{})}
        if row['experiment_id']:
            manifest,scene,events=read_run(runtime,row['experiment_id'])
            measurements=[e['measurement'] for e in events if e['kind']=='observation']
            seed_count+=sum(bool(o.get('seed_experiment_id')) for o in measurements)
            new_count+=sum(not o.get('seed_experiment_id') for o in measurements)
            loss=next((e for e in events if e['kind']=='mode' and e['mode']=='LINK_DEGRADED'),None)
            poses=[e['pose'] for e in events if e['kind']=='pose']
            safe=[o['position_m'] for o in measurements if loss and o['available_at_sim_time_s']<=loss['sim_time_s']
                  and o['rssi_dbm'] is not None and o['rssi_dbm']>=config['q_safe_dbm']]
            if loss and poses and safe:
                final=measurements[-1]['position_m'];start=loss.get('pose',poses[0])['position']
                row['return_to_known_safe_m']=min(math.dist(final,p) for p in safe)
                displacement=math.dist(start[:2],poses[-1]['position'][:2])
                row['path_stretch']=row.get('recovery_path_length_m',0)/displacement if displacement>.2 else None
            row['occupied_pose_fraction']=sum(not free(scene,*p['position'][:2],.35) for p in poses)/max(1,len(poses))
            row['obstacles']=sum(o['center'][2]+o['size'][2]/2>.01 for o in scene['objects'])
        rows.append(row)
    # Score each source separately: prefix-only predictions of later measurements.
    # Refit once per 3 new positions; evaluate before admitting each test point.
    sources=json.loads((campaign/'sources.json').read_text()) if (campaign/'sources.json').exists() else {}
    for name,source in sources.items():
        manifest,scene,events=read_run(runtime,source['experiment_id'])
        observations=[e['measurement'] for e in events if e['kind']=='observation' and e['measurement']['rssi_dbm'] is not None]
        for method in ('IDW','GPR-zero','GPR-pathloss'):
            for index in range(6,len(observations),3):
                prefix=observations[:index];test=observations[index]
                # Measurements whose results arrived after the queried physical pose cannot train this forecast.
                prefix=[o for o in prefix if o['available_at_sim_time_s']<=test['sim_time_s']]
                if len(prefix)<4:continue
                distance=min(math.dist(test['position_m'][:2],o['position_m'][:2]) for o in prefix)
                if distance<.15:continue
                model=RadioMap(method,scene['tx']['position'],manifest['config']['noise_db']).fit(prefix)
                mean,std=model.predict([test['position_m']])
                forecasts.append({'scene':name,'method':method,'split':manifest['config']['split'],
                    'sim_time_s':test['sim_time_s'],'nearest_training_m':distance,'actual_dbm':test['rssi_dbm'],
                    'predicted_dbm':mean[0],'std_db':std[0],'noise_db':model.noise,
                    'threshold_dbm':manifest['config']['q_safe_dbm'],'available_observations':len(prefix)})
    groups={}
    for axis in ('label','family','method','split'):
        groups[axis]={str(value):outcomes([r for r in rows if r.get(axis)==value]) for value in sorted({r.get(axis) for r in rows},key=str)}
    groups['method_beta']={f'{m}/beta={b}':outcomes([r for r in rows if r['method']==m and r['beta']==b])
                           for m,b in sorted({(r['method'],r['beta']) for r in rows})}
    distance_scores={}
    for method in ('IDW','GPR-zero','GPR-pathloss'):
        distance_scores[method]={label:forecast_scores([r for r in forecasts if r['method']==method and lo<=r['nearest_training_m']<hi])
            for label,lo,hi in (('0.15–0.5m',.15,.5),('0.5–1m',.5,1),('1–2m',1,2),('2m+',2,math.inf))}
    summary={'format_version':1,'campaign_id':meta['campaign_id'],'protocol':meta.get('protocol'),
        'overall':outcomes(rows),'unique_source_fields':len(sources),'source_episodes':len(sources),
        'new_source_episodes':0 if meta.get('history_source_campaign') else len(sources),
        'history_source_campaign':meta.get('history_source_campaign'),
        'new_episode_observations':new_count,'duplicated_seed_observations':seed_count,
        'groups':groups,'causal_forecast_by_distance':distance_scores,
        'occupied_pose_count':sum(r.get('occupied_pose_fraction',0)>0 for r in rows),
        'macro_scene_success':float(np.mean([g['success_fraction_all_attempts'] for g in groups['label'].values()])),
        'worst_scene_success':min(g['success_fraction_all_attempts'] for g in groups['label'].values()),
        'macro_family_success':float(np.mean([g['success_fraction_all_attempts'] for g in groups['family'].values()])),
        'notes':['All setup/navigation/radio failures remain in the denominator.',
            'Repeated episodes share histories and fields; Wilson intervals are descriptive, not independent-trial proof.',
            'Forecast scores use only results available before the test pose, never future or current labels.',
            'Near points on a trajectory are correlated. Use independent spatial reference grids for map generalization.',
            'Path stretch uses observed displacement, not an oracle shortest safe route.',
            'Occupied-pose check uses a 0.35m radius as a diagnostic, not a contact sensor.',
            'Universal quality requires more unseen geometries and hardware validation.']}
    (output/'analysis.json').write_text(json.dumps(summary,indent=2)+'\n')
    for filename,data in [('outcomes.csv',rows),('causal_forecasts.csv',forecasts)]:
        if not data:continue
        with (output/filename).open('w',newline='') as file:
            writer=csv.DictWriter(file,fieldnames=list(dict.fromkeys(k for r in data for k in r)),lineterminator='\n')
            writer.writeheader();writer.writerows(data)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('campaign')
    parser.add_argument('--runtime',default='.runtime');parser.add_argument('--output')
    args=parser.parse_args();path=Path(args.campaign)
    result=analyze(path,Path(args.runtime),Path(args.output) if args.output else path/'analysis')
    print(json.dumps({k:result[k] for k in ('overall','unique_source_fields','new_episode_observations','macro_scene_success')},indent=2))
