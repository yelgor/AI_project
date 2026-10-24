"""Run reproducible Gazebo/Nav2 trials; keeps failed attempts in the report."""
import argparse
import copy
import csv
import json
import math
import random
from pathlib import Path
import time
import urllib.request
import urllib.error


class API:
    def __init__(self,url):
        self.url=url.rstrip('/'); self.http=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def call(self,route,data=None):
        request=urllib.request.Request(self.url+route,json.dumps(data).encode() if data is not None else None,{'Content-Type':'application/json'})
        try: return json.load(self.http.open(request,timeout=120))
        except urllib.error.HTTPError as e: raise RuntimeError(json.load(e).get('error',str(e))) from e
    def wait(self,predicate,timeout=90):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:
                state=self.call('/api/state')
                if predicate(state): return state
            except OSError: pass
            time.sleep(.3)
        raise TimeoutError('Service readiness timeout; inspect .runtime/husky.log')


def run_trial(api,trial,method,beta,repeat,output):
    state=api.call('/api/state')
    if state['experiment'] and state['experiment']['status']=='running': raise RuntimeError('Another experiment is active')
    if state['recording'] or (state['job'] and state['job']['status']=='running'): raise RuntimeError('Another dataset is active')
    scene=copy.deepcopy(trial['scene']) if trial.get('scene') else api.call('/api/preset/'+trial['world'])
    scene['rx']['mode']='husky'
    if not trial.get('config',{}).get('history_from'): scene['rx']['mount_position']=[0,0,.7]
    if 'tx' in trial: scene['tx']['position']=trial['tx']
    if 'spawn' in trial: scene['robot']['position']=trial['spawn']
    if 'yaw_rad' in trial: scene['robot']['yaw_rad']=trial['yaw_rad']
    api.call('/api/scene',scene); api.call('/api/robot/start',{})
    state=api.wait(lambda s:s['robot_status']=='running' and s['navigation'].get('ready') and s['measurement'] is not None)
    config={**trial.get('config',{}),'method':method,'beta':beta,
            'route':trial['route'],'label':trial['name'],'split':trial.get('split','pilot'),
            'pair_id':trial['name']+'-'+str(repeat)}
    manifest=api.call('/api/experiments/start',config); identity=manifest['experiment_id']
    print(f'{trial["name"]}: {method} beta={beta} repeat={repeat} id={identity}',flush=True)
    result=manifest
    try:
        state=api.wait(lambda s:s['experiment']['status']!='running',timeout=config.get('timeout_s',180)*8+45)
        run=api.call('/api/experiments/'+identity)
        package=api.http.open(api.url+'/api/experiments/'+identity+'.zip',timeout=60).read()
        (output/(identity+'.zip')).write_bytes(package)
        result=run['manifest']
    except Exception as error:
        result={**manifest,'status':'RUN_FAILED','reason':str(error),'metrics':{}}
    finally:
        try:api.call('/api/robot/stop',{})
        except Exception as error:result['cleanup_warning']=str(error)
    return result


def wilson(success,total):
    if not total: return None
    z=1.95996398454; p=success/total; den=1+z*z/total
    center=(p+z*z/(2*total))/den
    delta=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/den
    return [center-delta,center+delta]


def report(manifests,output):
    rows=[]
    for item in manifests:
        rows.append({'experiment_id':item.get('experiment_id'),'label':item['config'].get('label'),
            'pair_id':item['config'].get('pair_id'),'method':item['config']['method'],'beta':item['config']['beta'],
            'status':item['status'],'reason':item.get('reason'),**item.get('metrics',{})})
    columns=list(dict.fromkeys(k for row in rows for k in row))
    with open(output/'trials.csv','w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=columns,lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
    groups={}
    for row in rows:
        key=f'{row["method"]}/beta={row["beta"]}'
        group=groups.setdefault(key,{'total_runs':0,'statuses':{},'recovery_attempts':0,'successes':0,'successful_recovery_times_s':[]})
        group['total_runs']+=1; group['statuses'][row['status']]=group['statuses'].get(row['status'],0)+1
        if row.get('recovery_time_s') is not None: group['recovery_attempts']+=1
        if row.get('success'):
            group['successes']+=1; group['successful_recovery_times_s'].append(row['recovery_time_s'])
    for group in groups.values():
        group['success_fraction']=group['successes']/group['recovery_attempts'] if group['recovery_attempts'] else None
        group['wilson_95']=wilson(group['successes'],group['recovery_attempts'])
    paired={}; by_pair={}
    for row in rows:
        by_pair.setdefault(row['pair_id'],{})[f'{row["method"]}/beta={row["beta"]}']=row
    keys=sorted(groups)
    for i,left in enumerate(keys):
        for right in keys[i+1:]:
            joint=[(p[left],p[right]) for p in by_pair.values() if left in p and right in p]
            if not joint: continue
            item={'pair_count':len(joint),'both_successful':sum(bool(a.get('success') and b.get('success')) for a,b in joint)}
            for metric in ('recovery_time_s','recovery_path_length_m'):
                delta=[a[metric]-b[metric] for a,b in joint if a.get('success') and b.get('success') and a.get(metric) is not None and b.get(metric) is not None]
                if not delta: continue
                rng=random.Random(42)
                samples=sorted(sum(rng.choices(delta,k=len(delta)))/len(delta) for _ in range(2000))
                item[metric]={'mean_difference_left_minus_right':sum(delta)/len(delta),'bootstrap_95':[samples[49],samples[1949]],'n':len(delta)}
            paired[left+' vs '+right]=item
    (output/'report.json').write_text(json.dumps({'format_version':1,'groups':groups,'trials':rows,
        'paired_success_only_differences':paired,
        'notes':['RSSI recovery proxy, not packet reception','Ground-truth localization; static obstacles',
                 'Closed-loop wall-clock sampling may differ before degradation; use offline replay for identical observations',
                 'Pilot sample sizes do not establish statistical superiority']},indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8010')
    parser.add_argument('--suite',default='config/experiments/pilot.json')
    parser.add_argument('--world',help='Filter trial name or world')
    parser.add_argument('--methods',nargs='+',choices=['B0','B1','IDW','GPR-zero','GPR-pathloss'],default=['B0','B1','IDW','GPR-zero','GPR-pathloss'])
    parser.add_argument('--betas',nargs='+',type=float,default=[0.,1.])
    parser.add_argument('--repeats',type=int,default=1)
    parser.add_argument('--output',default='.runtime/reports/pilot')
    parser.add_argument('--history-from',help='Finished experiment ID: reset to its loss checkpoint and reuse exactly its causal history')
    args=parser.parse_args(); api=API(args.url); output=Path(args.output); output.mkdir(parents=True,exist_ok=True)
    suite=json.loads(Path(args.suite).read_text()); manifests=[]
    if args.repeats<1: parser.error('--repeats must be positive')
    if any(not math.isfinite(beta) or not 0<=beta<=5 for beta in args.betas): parser.error('--betas must be finite values between 0 and 5')
    api.wait(lambda s:True)
    if args.history_from:
        source=api.call('/api/experiments/'+args.history_from); pose=None
        for event in source['timeline']:
            if event['kind']=='pose': pose=event['pose']
            if event['kind']=='mode' and event['mode']=='LINK_DEGRADED':
                pose=event.get('pose',pose);break
        else: raise SystemExit('Source run has no degradation checkpoint')
        q=pose['quaternion_xyzw'];yaw=math.atan2(2*(q[3]*q[2]+q[0]*q[1]),1-2*(q[1]*q[1]+q[2]*q[2]))
        suite={'trials':[{'name':'paired-'+args.history_from,'world':source['scenario']['name'],
            'scene':source['scenario'],'spawn':pose['position'][:2]+[.3],'yaw_rad':yaw,'route':[],
            'config':{**source['manifest']['config'],'history_from':args.history_from}}]}
    try:
        for trial in suite['trials']:
            if args.world and not args.history_from and args.world not in (trial['world'],trial['name']): continue
            for repeat in range(args.repeats):
                for method in args.methods:
                    for beta in (args.betas if method.startswith('GPR') else [0.]):
                        try: result=run_trial(api,trial,method,beta,repeat,output)
                        except Exception as e:
                            result={'status':'SETUP_FAILED','reason':str(e),'config':{'method':method,'beta':beta,'label':trial['name'],'pair_id':trial['name']+'-'+str(repeat)},'metrics':{}}
                            print('FAILED:',e,flush=True)
                            try: api.call('/api/robot/stop',{})
                            except Exception: pass
                        manifests.append(result); report(manifests,output)
                        print(result['status'],result.get('metrics',{}),flush=True)
    except KeyboardInterrupt:
        api.call('/api/robot/stop',{}); print('Cancelled; finished attempts are saved',flush=True)
    if not manifests: raise SystemExit('No matching trials')
    print('Report:',output/'report.json')
    if all(m['status']=='SETUP_FAILED' for m in manifests): raise SystemExit('No trial started; inspect setup failures in the report')


if __name__=='__main__': main()
