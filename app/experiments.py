"""Causal, persistent closed-loop radio recovery experiments and replay."""
import copy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
import importlib.metadata

try:
    from .datasets import atomic_json, field_hash
    from .navigation import free
    from .radio_maps import RadioMap, METHODS
    from .scenario import finite, antenna_pose, quat_from_ypr
    from .provenance import implementation_hash, ROOT
except ImportError:
    from datasets import atomic_json, field_hash
    from navigation import free
    from radio_maps import RadioMap, METHODS
    from scenario import finite, antenna_pose, quat_from_ypr
    from provenance import implementation_hash, ROOT

TERMINAL=('RECOVERED_WAIT','FAILED','CANCELLED','INTERRUPTED')


def configuration(data):
    result={'method':data.get('method','B1'),'optimize_gpr':bool(data.get('optimize_gpr',False))}
    if result['method'] not in METHODS: raise ValueError('Method must be '+', '.join(METHODS))
    for key,default,lo,hi in [('beta',0.,0.,5.),('q_safe_dbm',-40.,-160.,0.),
        ('hysteresis_db',2.,0.,20.),('degraded_s',2.,0.,30.),('stable_s',2.,.1,30.),
        ('timeout_s',180.,5.,1800.),('stale_s',8.,1.,30.),('noise_db',2.,.1,20.),
        ('grid_step_m',1.,.3,3.),('monitor_window_s',0.,0.,10.),
        ('brake_timeout_s',4.,1.,15.),('max_sample_travel_m',.5,.2,3.),('verify_timeout_s',2.,.5,30.)]:
        result[key]=finite(data.get(key,default),key,lo,hi)
    if result['beta'] and not result['method'].startswith('GPR'):
        raise ValueError('beta applies to GPR uncertainty only')
    b=data.get('bounds',[-3,-3,3,3])
    if len(b)!=4: raise ValueError('bounds must be [xmin,ymin,xmax,ymax]')
    result['bounds']=[finite(v,'bounds',-100,100) for v in b]
    b=result['bounds']
    if b[2]<=b[0] or b[3]<=b[1]: raise ValueError('Ordered bounds required')
    if (math.ceil((b[2]-b[0])/result['grid_step_m'])+1)*(math.ceil((b[3]-b[1])/result['grid_step_m'])+1)>900:
        raise ValueError('Experiment map limited to 900 cells')
    result['route']=[]
    for point in data.get('route',[]):
        if len(point) not in (2,3): raise ValueError('Route points must be [x,y,yaw?]')
        result['route'].append([finite(v,'route',-100,100) for v in point])
    if len(result['route'])>30: raise ValueError('Maximum 30 waypoints')
    result['label']=str(data.get('label','pilot'))[:100]
    result['pair_id']=str(data.get('pair_id',''))[:100]
    result['history_from']=str(data.get('history_from',''))
    result['save_cir']=bool(data.get('save_cir',True))
    result['loss_policy']=data.get('loss_policy','anchor')
    if result['loss_policy'] not in ('anchor','responsive'):raise ValueError('Invalid loss_policy')
    result['require_shadow_loss']=bool(data.get('require_shadow_loss',False))
    goal=data.get('shadow_goal')
    if goal is not None and len(goal)!=2:raise ValueError('shadow_goal must be [x,y]')
    result['shadow_goal']=[finite(v,'shadow_goal',-100,100) for v in goal] if goal is not None else None
    result['shadow_radius_m']=finite(data.get('shadow_radius_m',.25),'shadow_radius_m',.1,1)
    result['split']=data.get('split','pilot')
    if result['split'] not in ('pilot','train','validation','test'): raise ValueError('Invalid split')
    return result


def select_target(candidates, position, plan, last_only=False):
    """Euclidean distance is a lower bound; evaluate Nav2 paths until it cannot improve."""
    best=None; best_length=math.inf
    ordered=candidates[-1:] if last_only else sorted(candidates,key=lambda c:math.dist(c['base'][:2],position[:2]))
    for item in ordered:
        if not last_only and math.dist(item['base'][:2],position[:2])>=best_length: break
        try: path=plan(item['base'])
        except (ValueError,TimeoutError): continue
        if path['length_m']<best_length:
            best={**item,**path}; best_length=path['length_m']
    if best is None: raise ValueError('No reachable safe target under the selected method')
    return best


class Experiments:
    def __init__(self, session, start_worker=True):
        self.session=session; self.root=session.root/'experiments'; self.root.mkdir(exist_ok=True)
        self.implementation_sha256=implementation_hash()
        self.lock=threading.RLock(); self.run=None; self.closed=False; self.generation=0
        for path in self.root.glob('*/manifest.json'):
            meta=json.loads(path.read_text())
            if meta['status']=='running':
                meta.update(status='INTERRUPTED',reason='Backend restarted',finished_at=datetime.now(timezone.utc).isoformat())
                timeline=path.parent/'timeline.jsonl'
                previous=[json.loads(line) for line in timeline.read_text().splitlines()]
                with timeline.open('a') as file:
                    file.write(json.dumps({'sequence':previous[-1]['sequence']+1 if previous else 0,
                        'sim_time_s':previous[-1]['sim_time_s'] if previous else 0,
                        'kind':'mode','mode':'INTERRUPTED','reason':'Backend restarted'})+'\n')
                atomic_json(path,meta)
        self.worker=threading.Thread(target=self.loop,daemon=True)
        if start_worker: self.worker.start()

    def active(self):
        with self.lock: return bool(self.run and self.run['manifest']['status']=='running')

    def clear_session(self):
        with self.lock:
            if self.active(): raise ValueError('Finish active experiment first')
            self.run=None

    def event(self, kind, **data):
        run=self.run
        row={'sequence':run['sequence'],'sim_time_s':run['time'],'kind':kind,**copy.deepcopy(data)}
        with open(run['path']/'timeline.jsonl','ab') as file:
            run['offsets'].append(file.tell()); file.write((json.dumps(row,allow_nan=False)+'\n').encode())
        run['sequence']+=1
        return row

    def start(self, data):
        config=configuration(data)
        state=self.session.state()
        if state['robot_status']!='running' or state['scenario']['rx']['mode']!='husky':
            raise ValueError('Run Husky with mounted Rx and wait for a current world pose')
        if state['recording'] or (state['job'] and state['job']['status']=='running'):
            raise ValueError('Finish the current dataset/grid before starting an experiment')
        if not state.get('navigation',{}).get('ready'): raise ValueError('Wait for Nav2 readiness')
        navigation_yaml=(ROOT/'config/nav2.yaml').read_text()
        navigation_hash=hashlib.sha256(navigation_yaml.encode()).hexdigest()
        if state['navigation'].get('navigation_config_sha256') not in (None,navigation_hash):
            raise ValueError('Nav2 configuration changed; restart Husky before collecting data')
        if state['navigation'].get('implementation_sha256') not in (None,self.implementation_sha256):
            raise ValueError('Application sources changed; restart both services before collecting data')
        preflight=self.session.check_shadow(config) if config['shadow_goal'] is not None else None
        if preflight is None:
            previous=getattr(self.session,'last_shadow_preflight',None)
            if previous and previous.get('radio_field_sha256')==field_hash(state['scenario']):preflight=previous
        history=[]; checkpoint=None
        if config['history_from']:
            previous=self.replay(config['history_from'])
            if previous['manifest']['status']=='running': raise ValueError('History source must be finished')
            if field_hash(previous['scenario'])!=field_hash(state['scenario']): raise ValueError('History belongs to a different RF field')
            if previous['scenario']['rx']!=state['scenario']['rx']: raise ValueError('History antenna configuration differs')
            for event in previous['timeline']:
                if event['kind']=='pose': checkpoint=event['pose']
                if event['kind']=='observation': history.append(event['measurement'])
                if event['kind']=='mode' and event['mode']=='LINK_DEGRADED':
                    checkpoint=event.get('pose',checkpoint); break
            else: raise ValueError('History has no link degradation checkpoint')
            if not checkpoint or math.dist(checkpoint['position'][:2],state['robot_pose']['position'][:2])>.35:
                raise ValueError('Spawn Husky at the history degradation checkpoint before starting a paired trial')
            qa,qb=checkpoint['quaternion_xyzw'],state['robot_pose']['quaternion_xyzw']
            if 2*math.acos(min(1.,abs(sum(a*b for a,b in zip(qa,qb)))))>.35:
                raise ValueError('Paired trial robot heading differs from the checkpoint')
            if config['require_shadow_loss']:
                current=state.get('measurement')
                if not current or current.get('line_of_sight') is not False or (current['rssi_dbm'] is not None and
                        current['rssi_dbm']>=config['q_safe_dbm']-config['hysteresis_db']):
                    raise ValueError('Paired checkpoint did not reproduce measured link loss; no recovery trial started')
            config['route']=[]
        with self.lock:
            if self.active(): raise ValueError('An experiment is already active')
            self.generation+=1
            identity=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
            path=self.root/identity; path.mkdir()
            canonical=json.dumps(state['scenario'],sort_keys=True,separators=(',',':')).encode()
            meta={'format_version':1,'experiment_id':identity,'status':'running','config':config,
                'scene_revision':state['revision'],'scene_sha256':hashlib.sha256(canonical).hexdigest(),
                'radio_field_sha256':field_hash(state['scenario']),
                'started_at':datetime.now(timezone.utc).isoformat(),'finished_at':None,
                'criterion':'synthetic RSSI proxy; not packet delivery',
                'localization':'Gazebo ground truth','static_obstacles_only':True,
                'software':{n:importlib.metadata.version(n) for n in ('sionna-rt','mitsuba','numpy','scikit-learn')},
                'navigation_software':state.get('navigation',{}).get('software',{}),
                'implementation_sha256':self.implementation_sha256,
                'navigation_config_yaml':navigation_yaml,'navigation_config_sha256':navigation_hash,
                'preparation':getattr(self.session,'preparation',{}),
                'shadow_preflight':preflight,
                'solver_runtime':{'drjit_merge_functions':True,'isolation':'process-per-scene'},
                'metrics':{},'reason':None}
            pose=copy.deepcopy(state['robot_pose']); now=pose['sim_time_s']
            self.run={'manifest':meta,'config':config,'scene':copy.deepcopy(state['scenario']),
                'path':path,'mode':'TELEOP','pose':pose,'time':now,'start_time':now,'sequence':0,'offsets':[],
                'observations':[],'consumed':0,'model_version':0,'map':None,'target':None,
                'bad_since':None,'good_since':None,'degraded_at':None,'recovered_at':None,
                'last_arrival':now,'last_pose_event':-math.inf,'length':0.,'recovery_length':0.,
                'route_index':0,'route_started':False,'rejected':set(),'replans':0,
                'initial_history_count':len(history),'initial_decision_pending':bool(history),'loss_line_of_sight':None,
                'navigation':copy.deepcopy(state.get('navigation',{})),'wall_started':time.monotonic(),
                'last_wall_pose':time.monotonic()}
            self.run.update(monitor_consumed=len(history),suspect_at=None,suspect_pose=None,
                brake_started_wall=None,quiet_since=None,bad_count=0,loss_trigger_dbm=None,
                brake_distance_m=None,brake_time_s=None,loss_decision=None)
            self.run['shadow_arrived_at']=None
            atomic_json(path/'manifest.json',meta); atomic_json(path/'scenario.json',state['scenario'])
            self.event('mode',mode='TELEOP',reason='Experiment started')
            self.event('pose',pose=pose)
            if history:
                for original in history:
                    row=copy.deepcopy(original)
                    row.update(original_sim_time_s=row['sim_time_s'],sim_time_s=now+row['sim_time_s']-checkpoint['sim_time_s'],
                               available_at_sim_time_s=now,observation_index=len(self.run['observations']),
                               seed_experiment_id=config['history_from'])
                    if row.get('robot_pose'): row['robot_pose']['sim_time_s']=row['sim_time_s']
                    self.event('observation',measurement=row); self.run['observations'].append(self.compact(row))
                self.run['degraded_at']=now
                self.run['loss_line_of_sight']=history[-1].get('line_of_sight')
                self.transition('LINK_DEGRADED','Paired replay: identical pre-degradation observation history')
            elif not config['route']:self.session.runtime('/nav/cancel',{})
            return copy.deepcopy(meta)

    def pose(self, pose, navigation):
        with self.lock:
            if not self.active(): return
            r=self.run; now=pose['sim_time_s']
            if now<r['time']-.5:
                self.session.runtime('/nav/hold',{})
                self.finish('FAILED','Simulation clock moved backwards'); return
            distance=math.dist(r['pose']['position'],pose['position'])
            r['length']+=distance
            if r['mode']=='RECOVERY': r['recovery_length']+=distance
            r['pose']=copy.deepcopy(pose); r['time']=now; r['last_wall_pose']=time.monotonic()
            r['navigation']=copy.deepcopy(navigation)
            if now-r['last_pose_event']>=.2:
                self.event('pose',pose=pose,navigation=navigation); r['last_pose_event']=now

    def observe(self, measurement):
        with self.lock:
            if not self.active() or measurement['source']!='husky': return
            if measurement['scene_revision']!=self.run['manifest']['scene_revision']: return
            if measurement.get('sim_time_s') is None or measurement['sim_time_s']<self.run['start_time']: return
            r=self.run
            raw=measurement.get('rssi_dbm')
            if raw is not None and (not isinstance(raw,(int,float)) or not math.isfinite(raw)):
                raise ValueError('Invalid RSSI result; observation rejected')
            if r['config']['loss_policy']=='responsive' and r['observations'] and measurement['sim_time_s']<=r['observations'][-1]['sim_time_s']:
                return  # Duplicates/out-of-order packets cannot confirm a loss or a recovery.
            r['time']=max(r['time'],measurement['sim_time_s'])
            row={**copy.deepcopy(measurement),'available_at_sim_time_s':r['time'],
                 'observation_index':len(r['observations'])}
            window=r['config']['monitor_window_s']
            # Seed history becomes *available* all at once in a paired run, but
            # those samples were measured at different physical times. Smoothing
            # by arrival would incorrectly average the entire outbound mission.
            measured=row['sim_time_s']
            recent=[o for o in r['observations'] if measured-window<=o['sim_time_s']<=measured] if window else []
            powers=[10**(o['rssi_dbm']/10) if o['rssi_dbm'] is not None else 0 for o in [*recent,row]]
            power=sum(powers)/len(powers)
            row['monitor_rssi_dbm']=10*math.log10(power) if power>0 else None
            r['observations'].append(self.compact(row)); r['last_arrival']=r['time']
            self.event('observation',measurement=row)

    @staticmethod
    def compact(row):
        return {key:row[key] for key in ('position_m','rssi_dbm','robot_pose','sim_time_s',
                'available_at_sim_time_s','observation_index','line_of_sight','monitor_rssi_dbm') if key in row}

    def finish(self, status='CANCELLED', reason='Stopped by operator'):
        with self.lock:
            if not self.active(): return self.state()
            r=self.run; r['mode']=status
            r['manifest'].update(status=status,reason=reason,finished_at=datetime.now(timezone.utc).isoformat())
            r['manifest']['metrics']={'success':status=='RECOVERED_WAIT','duration_sim_s':r['time']-r['start_time'],
                'recovery_time_s':r['time']-r['degraded_at'] if r['degraded_at'] is not None else None,
                'path_length_m':r['length'],'recovery_path_length_m':r['recovery_length'],
                'observation_count':len(r['observations']),'replans':r['replans'],
                'operator_interventions':int(status=='CANCELLED' and reason!='Survey complete without link degradation'),
                'loss_line_of_sight':r['loss_line_of_sight'],
                'wall_duration_s':time.monotonic()-r['wall_started']}
            if r['config']['loss_policy']=='responsive':
                r['manifest']['metrics'].update(loss_trigger_rssi_dbm=r['loss_trigger_dbm'],
                    brake_distance_m=r['brake_distance_m'],brake_time_s=r['brake_time_s'],loss_decision=r['loss_decision'])
            self.event('mode',mode=status,reason=reason,metrics=r['manifest']['metrics'])
            atomic_json(r['path']/'manifest.json',r['manifest']); self.generation+=1
            return self.state()

    def stop(self):
        try:self.finish()
        finally:self.session.runtime('/nav/hold',{})
        return self.state()

    def state(self):
        with self.lock:
            if not self.run: return None
            r=self.run
            return {'experiment_id':r['manifest']['experiment_id'],'status':r['manifest']['status'],
                'scene_revision':r['manifest']['scene_revision'],
                'mode':r['mode'],'sim_time_s':r['time'],'config':copy.deepcopy(r['config']),
                'observation_count':len(r['observations']),'model_version':r['model_version'],
                'target':copy.deepcopy(r['target']),'reason':r.get('latest_reason') if r['manifest']['status']=='running' else r['manifest']['reason'],
                'metrics':copy.deepcopy(r['manifest']['metrics'])}

    def responsive_monitor(self,generation):
        """Brake at the first raw weak sample; confirm while stationary, before fitting."""
        with self.lock:
            if generation!=self.generation or not self.active():return
            r=self.run;c=r['config']
            rows=r['observations'][r['monitor_consumed']:];r['monitor_consumed']=len(r['observations'])
            for row in rows:
                raw=row['rssi_dbm'];t=row['available_at_sim_time_s']
                if r['mode'] in ('TELEOP','SURVEY','LINK_SUSPECT'):
                    bad=raw is None or raw<c['q_safe_dbm']-c['hysteresis_db']
                    if bad:
                        r['bad_since']=t if r['bad_since'] is None else r['bad_since'];r['bad_count']+=1;r['good_since']=None
                        if r['mode']!='LINK_SUSPECT':
                            self.session.runtime('/nav/hold',{})
                            r.update(suspect_at=t,suspect_pose=copy.deepcopy(r['pose']),
                                brake_started_wall=time.monotonic(),quiet_since=None,loss_trigger_dbm=raw)
                            self.transition('LINK_SUSPECT','First weak raw RSSI: brake before confirming loss')
                        if t-r['bad_since']>=c['degraded_s'] and r['bad_count']>=2:
                            r['degraded_at']=t;r['loss_line_of_sight']=row.get('line_of_sight');r['loss_decision']='sustained_weak_rssi'
                            self.transition('LINK_DEGRADED','Weak RSSI confirmed while braking')
                    else:
                        r['bad_since']=None;r['bad_count']=0
                        if r['mode']=='LINK_SUSPECT':
                            good=raw is not None and raw>=c['q_safe_dbm']
                            r['good_since']=(t if r['good_since'] is None else r['good_since']) if good else None
                            if r['good_since'] is not None and t-r['good_since']>=c['stable_s'] and self.brake_ready(r):
                                r['route_started']=False;r['good_since']=None
                                self.session.runtime('/nav/cancel',{})
                                self.transition('SURVEY' if c['route'] else 'TELEOP','Short RSSI dip cleared; resume outbound motion')
                elif r['mode']=='RECOVERY':
                    signal=row.get('monitor_rssi_dbm',raw);good=raw is not None and signal is not None and min(raw,signal)>=c['q_safe_dbm']
                    r['good_since']=(t if r['good_since'] is None else r['good_since']) if good else None
                    if r['good_since'] is not None and t-r['good_since']>=c['stable_s']:
                        self.session.runtime('/nav/hold',{});self.finish('RECOVERED_WAIT','RSSI proxy stable above q_safe');return

    def brake_ready(self,r):
        pose=r['pose'];velocity=pose.get('linear_velocity');angular=pose.get('angular_velocity')
        quiet=velocity is not None and angular is not None and math.sqrt(sum(v*v for v in velocity))<.03 and abs(angular[2])<.05
        r['quiet_since']=(r['time'] if r['quiet_since'] is None else r['quiet_since']) if quiet else None
        return r['quiet_since'] is not None and r['time']-r['quiet_since']>=.1

    def transition(self, mode, reason):
        self.run['mode']=mode;self.run['latest_reason']=reason; self.event('mode',mode=mode,reason=reason,pose=self.run['pose'])

    def snapshot(self):
        with self.lock:
            if not self.active(): return None
            snapshot=copy.deepcopy({k:v for k,v in self.run.items() if k not in ('path','offsets')})
            if snapshot['initial_decision_pending']:
                # Fresh measurements remain logged but cannot change the paired first decision.
                snapshot['observations']=snapshot['observations'][:snapshot['initial_history_count']]
            return self.generation,snapshot

    def update_model(self, generation, r):
        config=r['config']; scene=r['scene']; pose=r['pose']; points=[]; bases=[]
        yaw=math.atan2(2*(pose['quaternion_xyzw'][3]*pose['quaternion_xyzw'][2]+pose['quaternion_xyzw'][0]*pose['quaternion_xyzw'][1]),
                       1-2*(pose['quaternion_xyzw'][1]**2+pose['quaternion_xyzw'][2]**2))
        xmin,ymin,xmax,ymax=config['bounds']; step=config['grid_step_m']
        for iy in range(math.floor((ymax-ymin)/step)+1):
            for ix in range(math.floor((xmax-xmin)/step)+1):
                x,y=xmin+ix*step,ymin+iy*step
                if not free(scene,x,y,.56): continue
                point,_=antenna_pose(scene,{'position':[x,y,pose['position'][2]],'quaternion_xyzw':quat_from_ypr([yaw,0,0])})
                points.append(point); bases.append([x,y,yaw])
        model=RadioMap(config['method'],scene['tx']['position'],config['noise_db'],config['optimize_gpr'])
        started=time.monotonic(); model.fit(r['observations']); mean,std=model.predict(points)
        cells=[{'position_m':p,'base':b,'mean_dbm':m,'std_db':s,
                'lower_dbm':m-config['beta']*(s or 0) if m is not None else None}
               for p,b,m,s in zip(points,bases,mean,std)]
        with self.lock:
            if generation!=self.generation or not self.active(): return
            live=self.run; live['consumed']=len(r['observations']); live['model_version']+=1
            live['map']={'model_version':live['model_version'],'cells':cells,'training_indices':model.training_indices,
                'observation_count':len(r['observations']),'fit_predict_wall_s':time.monotonic()-started,
                'display_method':'IDW' if config['method'] in ('B0','B1') else config['method'],
                'sigma_kind':'latent GPR standard deviation' if config['method'].startswith('GPR') else None}
            self.event('map',**live['map'])

    def choose(self, generation, r):
        config=r['config']; candidates=[]
        if config['method'] in ('B0','B1'):
            for row in r['observations']:
                if row['rssi_dbm'] is not None and row['rssi_dbm']>=config['q_safe_dbm'] and row.get('robot_pose'):
                    p=row['robot_pose']; q=p['quaternion_xyzw']
                    yaw=math.atan2(2*(q[3]*q[2]+q[0]*q[1]),1-2*(q[1]*q[1]+q[2]*q[2]))
                    candidates.append({'base':p['position'][:2]+[yaw],'mean_dbm':row['rssi_dbm'],
                                       'observation_index':row['observation_index']})
        elif r['map']:
            candidates=[c for c in r['map']['cells'] if c['lower_dbm'] is not None and c['lower_dbm']>=config['q_safe_dbm']]
        candidates=[c for c in candidates if tuple(c['base'][:2]) not in r['rejected']]
        # Finite timeout applies inside each Nav2 action; cancellation also checked between candidates.
        deadline=time.monotonic()+30
        def plan(point):
            with self.lock:
                if generation!=self.generation or not self.active(): raise RuntimeError('Experiment cancelled')
            if time.monotonic()>deadline:raise RuntimeError('Nav2 target selection exceeded 30 seconds')
            try:return self.session.runtime('/nav/plan',{'position':point,'start':r['pose']['position'][:2]})
            except ValueError as error:
                if 'unavailable' in str(error) or 'not ready' in str(error):raise RuntimeError(str(error)) from error
                raise
        chosen=select_target(candidates,r['pose']['position'],plan,config['method']=='B0')
        with self.lock:
            if generation!=self.generation or not self.active(): return
            self.run['target']=chosen; self.run['replans']+=1
            self.event('target',target=chosen,method=config['method'],beta=config['beta'],
                       q_safe_dbm=config['q_safe_dbm'],model_version=self.run['model_version'])
            self.run['navigation']=self.session.runtime('/nav/goal',{'position':chosen['base']})
            self.run['initial_decision_pending']=False

    def step(self):
        snapshot=self.snapshot()
        if snapshot is None: return
        generation,r=snapshot; config=r['config']; now=r['time']
        if getattr(self.session,'error',None):raise ValueError('Radio solver error: '+self.session.error)
        if now-r['start_time']>config['timeout_s'] or time.monotonic()-r['wall_started']>config['timeout_s']*8:
            raise ValueError('Experiment timeout')
        if time.monotonic()-r['last_wall_pose']>5: raise ValueError('Stale Gazebo pose')
        if now-r['last_arrival']>config['stale_s']:
            raise ValueError('Stale radio measurement; recovery cannot use missing numerical results')
        responsive=config['loss_policy']=='responsive'
        if responsive:
            if r['observations']:
                latest=r['observations'][-1]
                if now-latest['sim_time_s']>config['stale_s']:raise ValueError('Radio sample is too old for motion')
                if r['mode'] in ('TELEOP','SURVEY','RECOVERY') and latest.get('robot_pose') and math.dist(
                        r['pose']['position'][:2],latest['robot_pose']['position'][:2])>config['max_sample_travel_m']:
                    raise ValueError('Motion exceeded the distance allowed without a fresh radio sample')
            self.responsive_monitor(generation)
            snapshot=self.snapshot()
            if snapshot is None:return
            generation,r=snapshot
            if r['mode']=='LINK_SUSPECT':
                with self.lock:
                    if generation!=self.generation or not self.active():return
                    stopped=self.brake_ready(self.run)
                if not stopped and time.monotonic()-r['brake_started_wall']>config['brake_timeout_s']:
                    raise ValueError('Husky failed to confirm braking')
                if now-r['suspect_at']>=max(config['verify_timeout_s'],config['degraded_s'],config['stable_s']):
                    with self.lock:
                        if generation!=self.generation or not self.active():return
                        live=self.run;live['degraded_at']=now;live['loss_decision']='verification_timeout'
                        live['loss_line_of_sight']=live['observations'][-1].get('line_of_sight')
                        self.transition('LINK_DEGRADED','Stopped verification timed out; return conservatively')
                    snapshot=self.snapshot()
                    if snapshot is None:return
                    generation,r=snapshot
        if len(r['observations'])>r['consumed']:
            self.update_model(generation,r)
            with self.lock:
                if generation!=self.generation or not self.active(): return
                live=self.run
                for row in ([] if responsive else r['observations'][r['consumed']:]):
                    signal=row.get('monitor_rssi_dbm',row['rssi_dbm']); t=row['available_at_sim_time_s']
                    if live['mode'] in ('TELEOP','SURVEY'):
                        bad=signal is None or signal<config['q_safe_dbm']-config['hysteresis_db']
                        live['bad_since']=(t if live['bad_since'] is None else live['bad_since']) if bad else None
                        if live['bad_since'] is not None and t-live['bad_since']>=config['degraded_s']:
                            goal=config['shadow_goal']
                            if goal and math.dist(live['pose']['position'][:2],goal)>config['shadow_radius_m']:
                                continue  # Intentionally reach the independently validated shadow anchor first.
                            if config['require_shadow_loss'] and row.get('line_of_sight') is not False:
                                raise ValueError('Signal degraded before the obstacle: invalid shadowing trial')
                            live['loss_line_of_sight']=row.get('line_of_sight')
                            live['degraded_at']=t; self.transition('LINK_DEGRADED','RSSI below configured threshold')
                    elif live['mode']=='RECOVERY':
                        good=signal is not None and signal>=config['q_safe_dbm']
                        live['good_since']=(t if live['good_since'] is None else live['good_since']) if good else None
                        if live['good_since'] is not None and t-live['good_since']>=config['stable_s']:
                            self.session.runtime('/nav/hold',{})
                            self.finish('RECOVERED_WAIT','RSSI proxy stable above q_safe'); return
            snapshot=self.snapshot()
            if snapshot is None: return
            generation,r=snapshot
        if r['mode']=='LINK_DEGRADED':
            if responsive:
                with self.lock:
                    if generation!=self.generation or not self.active():return
                    live=self.run
                    if live['brake_started_wall'] is None:
                        self.session.runtime('/nav/hold',{});live['brake_started_wall']=time.monotonic()
                    if not self.brake_ready(live):
                        if time.monotonic()-live['brake_started_wall']>config['brake_timeout_s']:raise ValueError('Husky failed to confirm braking')
                        return
                    live['brake_distance_m']=math.dist(live['pose']['position'][:2],(live['suspect_pose'] or live['pose'])['position'][:2])
                    live['brake_time_s']=live['time']-(live['suspect_at'] if live['suspect_at'] is not None else live['time'])
                    self.event('brake',distance_m=live['brake_distance_m'],duration_sim_s=live['brake_time_s'],pose=live['pose'])
            else:self.session.runtime('/nav/hold',{})
            with self.lock:
                if generation!=self.generation: return
                self.transition('RECOVERY','Select reachable recovery target')
            self.choose(generation,self.snapshot()[1]); return
        if r['mode']=='RECOVERY':
            status=r['navigation'].get('status')
            if status in ('failed','cancelled') or (status=='succeeded' and r['good_since'] is None):
                with self.lock:
                    if r['target']: self.run['rejected'].add(tuple(r['target']['base'][:2]))
                self.choose(generation,self.snapshot()[1])
        elif config['route'] and r['mode'] in ('TELEOP','SURVEY'):
            index=r['route_index']
            if r['route_started'] and r['navigation'].get('status')=='failed': raise ValueError('Survey Nav2 route failed')
            if r['route_started'] and r['navigation'].get('status')=='succeeded':
                with self.lock:
                    self.run['route_index']+=1; self.run['route_started']=False
                index+=1
            if index>=len(config['route']):
                if config['shadow_goal']:
                    with self.lock:
                        if self.run['shadow_arrived_at'] is None:
                            self.run['shadow_arrived_at']=now
                            self.session.runtime('/nav/hold',{})
                            self.event('shadow_arrival',goal=config['shadow_goal'],reason='Waiting for measured link-loss confirmation')
                        elif now-self.run['shadow_arrived_at']>8:
                            raise ValueError('Shadow anchor reached but measured signal did not confirm link loss')
                    return
                # No loss in this control run; finish as a non-recovery control, not a recovery success.
                self.session.runtime('/nav/hold',{});self.finish('CANCELLED','Survey complete without link degradation'); return
            if not r['route_started'] or index!=r['route_index']:
                point=config['route'][index]
                path=self.session.runtime('/nav/plan',{'position':point})
                with self.lock:
                    if generation!=self.generation: return
                    self.run['route_started']=True; self.transition('SURVEY','Autonomous preconfigured survey waypoint')
                    self.event('route',target={'base':point,**path})
                    self.run['navigation']=self.session.runtime('/nav/goal',{'position':point})

    def loop(self):
        while not self.closed:
            generation=self.generation
            try: self.step()
            except Exception as error:
                if generation==self.generation and self.active():
                    try: self.session.runtime('/nav/hold',{})
                    except Exception: pass
                    try:self.finish('FAILED',str(error))
                    except OSError:pass  # Status is already terminal in memory; motion has been stopped.
            time.sleep(.2)

    def manifests(self):
        paths=[*self.root.glob('*/manifest.json'),*(self.root.parent/'workers').glob('*/experiments/*/manifest.json')]
        return sorted([json.loads(p.read_text()) for p in paths],key=lambda m:m['started_at'],reverse=True)

    def directory(self, identity):
        if not identity or any(c not in '0123456789TZabcdefghijklmnopqrstuvwxyz-' for c in identity): raise ValueError('Invalid experiment id')
        path=self.root/identity
        if not (path/'manifest.json').is_file():
            library=Path(os.environ.get('RADIO_EXPERIMENT_LIBRARY',str(self.root.parent)))
            candidates=[library/'experiments'/identity,*(library/'workers').glob('*/experiments/'+identity)]
            path=next((p for p in candidates if (p/'manifest.json').is_file()),None)
            if path is None:raise FileNotFoundError('Experiment not found')
        return path

    def replay(self, identity, after=-1):
        with self.lock:
            path=self.directory(identity)
            manifest=json.loads((path/'manifest.json').read_text()); scene=json.loads((path/'scenario.json').read_text())
            manifest.setdefault('radio_field_sha256',field_hash(scene))
            end=(path/'timeline.jsonl').stat().st_size; offset=0
            if after>=0 and self.run and self.run['path']==path:
                index=after+1; offsets=self.run['offsets']
                offset=offsets[index] if index<len(offsets) else end
        with (path/'timeline.jsonl').open('rb') as file:
            file.seek(offset); payload=file.read(end-offset)
        if payload and not payload.endswith(b'\n'):payload=payload.rsplit(b'\n',1)[0]+b'\n'
        return {'manifest':manifest,'scenario':scene,
                'timeline':[row for line in payload.decode().splitlines() if line and (row:=json.loads(line))['sequence']>after]}

    def archive(self, identity):
        with self.lock:
            path=self.directory(identity)
            if json.loads((path/'manifest.json').read_text())['status']=='running': raise ValueError('Finish experiment before exporting')
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
            for name in ('manifest.json','scenario.json','timeline.jsonl'): archive.write(path/name,identity+'/'+name)
        return buffer.getvalue()

    def close(self):
        self.closed=True
        if self.active():
            try: self.session.runtime('/nav/hold',{})
            except Exception: pass
            self.finish('INTERRUPTED','Backend shutting down')
