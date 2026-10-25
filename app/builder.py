"""Scene constructor backend, upstream radio solver and experiment sessions."""
import argparse
import json
import math
import os
import signal
from pathlib import Path
import threading
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import uuid
import mimetypes

try:
    from .scenario import normalize, preset, antenna_pose, vector, finite
    from .radio import export_gazebo, SOLVER_EXECUTOR
    from .engine import RadioWorker as Radio
    from .datasets import Dataset, list_datasets, archive, atomic_json, read_dataset,field_hash
    from .navigation import export_map,free
    from .experiments import Experiments,configuration
    from .missions import mission,catalog,line_of_sight,response_defaults
    from .campaigns import Campaigns
    from .evidence import EvidenceLibrary
except ImportError:
    from scenario import normalize, preset, antenna_pose, vector, finite
    from radio import export_gazebo, SOLVER_EXECUTOR
    from engine import RadioWorker as Radio
    from datasets import Dataset, list_datasets, archive, atomic_json, read_dataset,field_hash
    from navigation import export_map,free
    from experiments import Experiments,configuration
    from missions import mission,catalog,line_of_sight,response_defaults
    from campaigns import Campaigns
    from evidence import EvidenceLibrary

ROOT=Path(__file__).resolve().parents[1]


class Session:
    def __init__(self, root=None, husky_url=None):
        root=root or os.environ.get('RADIO_LAB_RUNTIME',ROOT/'.runtime')
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        self.data=self.root/'datasets'; self.data.mkdir(exist_ok=True)
        self.lock=threading.RLock(); self.operation=threading.Lock()
        self.executor=SOLVER_EXECUTOR
        self.scene=None; self.model=None; self.revision=None; self.pose=None
        self.measurement=None; self.error=None; self.robot_status='stopped'
        self.record=None; self.job=None; self.cancel=threading.Event()
        self.experiments=None; self.navigation={'ready':False,'status':'idle','authority':'teleop'}
        self.robot_epoch=None;self.sample_generation=0;self.minimum_pose_time=-1
        self.mission={'status':'idle','phase':'idle'};self.mission_lock=threading.Lock();self.mission_cancel=threading.Event()
        self.preparation={}
        self.shadow_checks={}
        self.last_shadow_preflight=None
        for file in self.data.glob('*/manifest.json'):
            manifest=json.loads(file.read_text())
            if manifest.get('status')=='collecting':
                manifest['status']='interrupted'
                atomic_json(file,manifest)
        self.pending=False; self.closed=False; self.last_sample=0; self.pose_received=0
        self.last_sim_sample=-math.inf
        self.husky_url=husky_url or os.environ.get('HUSKY_URL','http://husky:8766')
        self.http=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        saved=self.root/'active_scene.json'
        scenario=json.loads(saved.read_text())['scenario'] if saved.exists() else json.loads((ROOT/'config/scenario.json').read_text())
        self.apply(scenario)
        self.experiments=Experiments(self)
        self.campaigns=Campaigns(self) if not os.environ.get('RADIO_POOL_WORKER') else None
        self.scheduler=threading.Thread(target=self.tick,daemon=True); self.scheduler.start()

    def runtime(self, route, data=None):
        request=urllib.request.Request(self.husky_url+route,
            json.dumps(data).encode() if data is not None else None,{'Content-Type':'application/json'})
        try:
            return json.load(self.http.open(request,timeout=25))
        except urllib.error.HTTPError as e:
            raise ValueError(json.load(e).get('error',str(e))) from e
        except (OSError,urllib.error.URLError) as e:
            raise ValueError('Husky runtime unavailable. Start the husky service; static radio still works.') from e

    def apply(self, data):
        with self.operation:
            if self.experiments and self.experiments.active(): raise ValueError('Finish the experiment before changing its scene')
            scene=normalize(data)
            with self.lock:
                if self.record or (self.job and self.job['status']=='running'):
                    raise ValueError('Finish/cancel the dataset before applying another scene')
                running=self.robot_status in ('running','starting')
            if running: self.stop()
            model=self.executor.submit(Radio,scene).result(timeout=120)
            revision=uuid.uuid4().hex[:12]
            try:
                export_gazebo(scene,self.root/'world.sdf.tmp')
                export_map(scene,self.root/'navigation')
            except BaseException:
                self.executor.submit(model.close).result(timeout=120)
                raise
            (self.root/'world.sdf.tmp').replace(self.root/'world.sdf')
            atomic_json(self.root/'active_scene.json',{'revision':revision,'scenario':scene})
            if self.experiments: self.experiments.clear_session()
            with self.lock:
                previous=self.model
                self.scene=scene; self.model=model; self.revision=revision
                self.pose=None; self.measurement=None; self.error=None; self.job=None
                self.robot_status='stopped'; self.pose_received=0
                self.sample_generation+=1;self.robot_epoch=None;self.minimum_pose_time=-1
                self.last_sim_sample=-math.inf
                self.navigation={'ready':False,'status':'idle','authority':'teleop'}
                if previous:self.executor.submit(previous.close)
            return {'revision':revision,'scenario':scene}

    def start(self):
        with self.operation:
            if self.experiments.active(): raise ValueError('Finish the experiment before restarting Husky')
            if self.record: raise ValueError('Finish recording before restarting Husky')
            if self.job and self.job['status']=='running': raise ValueError('Wait for grid completion')
            self.experiments.clear_session()
            result=self.runtime('/start',{'revision':self.revision})
            with self.lock:
                self.robot_status='starting'; self.pose=None; self.pose_received=0
                self.navigation={'ready':False,'status':'idle','authority':'teleop'}
                self.robot_epoch=result.get('robot_epoch');self.minimum_pose_time=-1;self.sample_generation+=1
                self.last_sim_sample=-math.inf
            return result

    def prepare(self,data):
        """Reuse running physics and RF geometry; reset actual Gazebo pose for a new trial."""
        started=time.monotonic();scene=normalize(data['scene']);warm=bool(data.get('reuse',True))
        with self.lock:
            if self.record or (self.job and self.job['status']=='running') or self.experiments.active():
                raise ValueError('Finish the active experiment/dataset before preparing another')
            same_world=scene['objects']==self.scene['objects']
            running=self.robot_status in ('running','starting') and self.navigation.get('ready')
        if not warm or not same_world or not running:
            self.apply(scene);result=self.start();kind='cold';radio_reused=False
        else:
            with self.operation:
                radio_reused=field_hash(scene)==field_hash(self.scene) and self.model.process.is_alive()
                model=self.model if radio_reused else self.executor.submit(Radio,scene).result(timeout=120)
                revision=uuid.uuid4().hex[:12]
                self.experiments.clear_session()
                with self.lock:
                    previous=self.model;self.scene=scene;self.model=model;self.revision=revision
                    self.sample_generation+=1;self.measurement=None;self.pose=None;self.error=None
                    self.last_sim_sample=-math.inf
                    self.robot_status='resetting';self.pose_received=0
                atomic_json(self.root/'active_scene.json',{'revision':revision,'scenario':scene})
                result=self.runtime('/reset',{'revision':revision})
                with self.lock:
                    self.robot_epoch=result['robot_epoch'];self.minimum_pose_time=result['pose']['sim_time_s']
                    self.pose=result['pose'];self.pose_received=time.monotonic();self.robot_status='running'
                    if not radio_reused:self.executor.submit(previous.close)
                kind='warm'
        self.preparation={'kind':kind,'radio_reused':radio_reused,'wall_s':time.monotonic()-started}
        return {**result,'preparation':self.preparation}

    def launch_mission(self,data):
        spec=mission(data.get('mission','shadow'),int(data.get('layout',0)))
        profile=response_defaults(data.get('response_profile','responsive'))
        config=configuration({**spec['config'],**profile,**data.get('config',{})})
        if config['loss_policy']=='responsive':
            spec['scene']['radio']['period_s']=.25
            # Avoid the near-coincident Tx/Rx cancellation at the old spawn.
            # Readiness and live RSSI still determine whether motion can continue.
            spec['scene']['robot']['position'][1]=-3.
        shadow_config={**config,'shadow_goal':config['shadow_goal'] or spec['config']['shadow_goal']}
        manual=bool(data.get('manual'))
        if manual:
            config['route']=[]
            if 'shadow_goal' not in data.get('config',{}):config['shadow_goal']=None
            config['require_shadow_loss']=data.get('config',{}).get('require_shadow_loss',False)
        if not self.mission_lock.acquire(blocking=False):raise ValueError('A mission is already being prepared')
        if self.experiments.active():
            self.mission_lock.release();raise ValueError('Stop the current mission first')
        self.mission_cancel.clear();self.mission={'status':'starting','phase':'preparing','mission':spec['id'],'manual':manual}
        def work():
            try:
                if self.mission_cancel.is_set():raise ValueError('Mission cancelled')
                self.prepare({'scene':spec['scene'],'reuse':True})
                self.mission['phase']='validating_shadow'
                self.check_shadow(shadow_config)
                self.mission['phase']='waiting_for_nav2_and_radio'
                deadline=time.monotonic()+90
                while time.monotonic()<deadline:
                    if self.mission_cancel.is_set():raise ValueError('Mission cancelled')
                    state=self.state()
                    if state['robot_status']=='running' and state['navigation'].get('ready') and state['measurement']:break
                    time.sleep(.2)
                else:raise ValueError('Nav2/radio readiness timeout; inspect simulator log')
                with self.operation:
                    if self.mission_cancel.is_set():raise ValueError('Mission cancelled')
                    manifest=self.experiments.start(config)
                self.mission.update(status='running',phase='experiment',experiment_id=manifest['experiment_id'])
            except Exception as error:
                self.mission.update(status='stopped' if self.mission_cancel.is_set() else 'failed',
                    phase='stopped' if self.mission_cancel.is_set() else 'failed',error=None if self.mission_cancel.is_set() else str(error))
                try:self.runtime('/nav/hold',{})
                except Exception:pass
            finally:self.mission_lock.release()
        threading.Thread(target=work,daemon=True).start()
        return dict(self.mission)

    def check_shadow(self,config):
        """Scenario validation only: never append these oracle probes to observations."""
        with self.lock:scene=self.scene;model=self.model
        goal=config['shadow_goal'];radius=config['shadow_radius_m']
        key=json.dumps([field_hash(scene),goal,radius,config['q_safe_dbm']])
        if key in self.shadow_checks:
            self.last_shadow_preflight=self.shadow_checks[key];return self.last_shadow_preflight
        if not free(scene,*goal,.6):raise ValueError('Shadow anchor has insufficient Husky clearance')
        # A200's settled base height is ~0.13228m on this flat-world model.
        height=.13228+scene['rx']['mount_position'][2]
        points=[[goal[0]+dx,goal[1]+dy,height] for dx,dy in [(0,0),(radius,0),(-radius,0),(0,radius),(0,-radius)]]
        values=[]
        for point in points:
            if line_of_sight(scene,point):raise ValueError('Shadow anchor must be occluded across its tolerance region')
            result=self.executor.submit(model.sample,point,[0,0,0],False).result(timeout=120)
            values.append(result['rssi_dbm'])
        worst=max(v if v is not None else -160 for v in values)
        margin=config['q_safe_dbm']-worst
        if margin<3:raise ValueError(f'Shadow anchor is not sufficiently weak: worst RSSI {worst:.1f} dBm; require 3 dB margin')
        report={'goal':goal,'radius_m':radius,'positions_m':points,'rssi_dbm':values,
                'radio_field_sha256':field_hash(scene),
                'worst_rssi_dbm':worst,'margin_db':margin,'controller_training':False,
                'criterion':'geometrically occluded; every probe at least 3 dB below q_safe'}
        self.shadow_checks[key]=report;self.last_shadow_preflight=report;return report

    def stop_mission(self):
        self.mission_cancel.set()
        with self.operation:result=self.experiments.stop()
        self.mission.update(status='stopped',phase='stopped')
        return result

    def stop(self):
        try:
            if self.experiments and self.experiments.active(): self.experiments.finish('CANCELLED','Simulation stopped')
        finally:self.runtime('/stop',{})
        with self.lock:
            self.robot_status='stopped'; self.pose=None; self.pose_received=0
            self.navigation={'ready':False,'status':'idle','authority':'teleop'}
            if self.record:
                self.record.finish(); self.record=None
        return {'status':'stopped'}

    def control(self,data):
        linear=finite(data.get('linear',0),'linear',-1,1)
        angular=finite(data.get('angular',0),'angular',-1.5,1.5)
        result=self.runtime('/control',{'linear':linear,'angular':angular})
        with self.lock:
            if self.record: self.record.event('control',json.dumps({'linear_mps':linear,'angular_radps':angular}))
        return result

    def telemetry(self,data):
        position=vector(data['position'],'robot.position')
        q=data['quaternion_xyzw']
        if len(q)!=4: raise ValueError('Quaternion must have four components')
        q=[finite(v,'quaternion',-1,1) for v in q]
        if abs(sum(v*v for v in q)-1)>.01: raise ValueError('Quaternion must be normalized')
        sim_time=finite(data['sim_time_s'],'sim_time_s',0)
        with self.lock:
            if self.robot_epoch is not None and data.get('robot_epoch')!=self.robot_epoch:raise ValueError('Stale robot epoch')
            if sim_time<self.minimum_pose_time:raise ValueError('Pose predates reset')
            if data.get('scene_revision')!=self.revision: raise ValueError('Stale telemetry revision')
            if self.robot_status not in ('running','starting'): raise ValueError('Simulation is stopped')
            self.pose={'position':position,'quaternion_xyzw':q,'sim_time_s':sim_time,
                       'joint_positions':data.get('joint_positions',{}),
                       'linear_velocity':data.get('linear_velocity'),'angular_velocity':data.get('angular_velocity')}
            self.pose_received=time.monotonic(); self.robot_status='running'
            self.navigation=data.get('navigation',{'ready':False})
            pose=self.pose.copy(); navigation=self.navigation.copy(); result={'measurement':self.measurement}
        if self.experiments: self.experiments.pose(pose,navigation)
        return result

    def sample(self, override=None, source=None):
        sample_started=time.monotonic()
        with self.lock:
            if self.closed:raise ValueError('Session is closed')
            scene=self.scene; revision=self.revision; model=self.model; recording=self.record
            generation=self.sample_generation
            epoch=self.robot_epoch
            include_paths=not self.experiments or not self.experiments.active() or self.experiments.run['config']['save_cir']
            pose=json.loads(json.dumps(self.pose)) if self.pose else None
            stale=time.monotonic()-self.pose_received>3
        if override is not None:
            position=vector(override,'position_m'); orientation=scene['rx']['orientation_rad']; source=source or 'manual'
        elif scene['rx']['mode']=='husky':
            if not pose or stale: raise ValueError('No current Gazebo world pose; run Husky first')
            position,orientation=antenna_pose(scene,pose); source=source or 'husky'
        else:
            position=scene['rx']['position']; orientation=scene['rx']['orientation_rad']; source=source or 'static'
        with self.lock:
            # Scene replacement queues destruction on this executor. Reject a
            # snapshot replaced before its sample was submitted.
            if model is not self.model or self.closed:raise ValueError('Scene changed before sampling')
            future=self.executor.submit(model.sample,position,orientation,include_paths)
        result=future.result(timeout=120)
        result.update({'scene_revision':revision,'source':source,'orientation_rad':orientation,
                       'solver_wall_s':time.monotonic()-sample_started,
                       'tx_position_m':scene['tx']['position'],'robot_pose':pose if source=='husky' else None,
                       'sim_time_s':pose['sim_time_s'] if pose and source=='husky' else None,
                       'robot_epoch':epoch,'line_of_sight':line_of_sight(scene,position)})
        with self.lock:
            accepted=revision==self.revision and generation==self.sample_generation
            if accepted:
                self.measurement=result; self.error=None
                if recording is not None and self.record is recording: recording.append(result)
        if self.experiments and accepted: self.experiments.observe(result)
        return result

    def tick(self):
        while not self.closed:
            with self.lock:
                should=(self.record is not None or (self.scene['rx']['mode']=='husky' and self.robot_status=='running'))
                period=self.scene['radio']['period_s']
                moving=self.scene['rx']['mode']=='husky'
                clock=self.pose['sim_time_s'] if moving and self.pose else None
                elapsed=clock-self.last_sim_sample if clock is not None else -1 if moving else time.monotonic()-self.last_sample
                should=should and not self.pending and elapsed>=period
                if should:
                    self.pending=True; self.last_sample=time.monotonic()
                    if clock is not None:self.last_sim_sample=clock
            if should:
                def collect():
                    try: self.sample()
                    except Exception as e:
                        with self.lock:
                            self.error=str(e)
                            if self.record: self.record.event('error',str(e))
                    finally:
                        with self.lock: self.pending=False
                threading.Thread(target=collect,daemon=True).start()
            time.sleep(.1)

    def begin_record(self):
        with self.operation,self.lock:
            if self.experiments.active(): raise ValueError('Experiment has its own log; finish it before recording another dataset')
            if self.record or (self.job and self.job['status']=='running'): raise ValueError('Another dataset is active')
            if self.scene['rx']['mode']=='husky' and (not self.pose or time.monotonic()-self.pose_received>3):
                raise ValueError('Run Husky and wait for its world pose first')
            self.record=Dataset(self.data,self.scene,self.revision,'recording')
            return self.record.manifest.copy()

    def end_record(self):
        with self.operation,self.lock:
            if not self.record: raise ValueError('No active recording')
            self.record.finish(); manifest=self.record.manifest.copy(); self.record=None
            return manifest

    def grid(self,data):
        lower=vector(data['min'],'grid.min'); upper=vector(data['max'],'grid.max')
        step=vector(data['step'],'grid.step')
        if any(v<=0 for v in step) or any(upper[i]<lower[i] for i in range(3)): raise ValueError('Grid bounds/steps invalid')
        counts=[int(math.floor((upper[i]-lower[i])/step[i]+1e-9))+1 for i in range(3)]
        total=math.prod(counts)
        if total>2500: raise ValueError('Grid limited to 2500 planned points')
        with self.operation,self.lock:
            if self.experiments.active(): raise ValueError('Finish the experiment before collecting a reference grid')
            if self.record or (self.job and self.job['status']=='running'): raise ValueError('Another dataset is active')
            if self.robot_status in ('running','starting'): raise ValueError('Stop Husky before collecting a static grid')
            dataset=Dataset(self.data,self.scene,self.revision,'grid',{'min':lower,'max':upper,'step':step,'planned_count':total})
            self.job={'dataset_id':dataset.id,'status':'running','completed':0,'total':total,'error':None}
            self.cancel.clear()
        def worker():
            status='completed'
            try:
                for iz in range(counts[2]):
                    for iy in range(counts[1]):
                        for ix in range(counts[0]):
                            if self.cancel.is_set(): status='cancelled'; return
                            point=[lower[i]+offset*step[i] for i,offset in enumerate((ix,iy,iz))]
                            try: dataset.append(self.sample(point,source='grid'))
                            except ValueError as e: dataset.event('skipped',str(e),point)
                            with self.lock: self.job['completed']+=1
            except Exception as e:
                status='failed'; dataset.event('error',str(e))
                with self.lock: self.job['error']=str(e)
            finally:
                dataset.finish(status)
                with self.lock: self.job['status']=status
        threading.Thread(target=worker,daemon=True).start()
        return self.job.copy()

    def state(self):
        with self.lock:
            status=self.robot_status
            if status=='running' and time.monotonic()-self.pose_received>3: status='pose-stale'
            return {'scenario':self.scene,'revision':self.revision,'robot_status':status,
                    'robot_pose':self.pose,'measurement':self.measurement,'error':self.error,
                    'recording':self.record.manifest.copy() if self.record else None,
                    'job':self.job.copy() if self.job else None,
                    'navigation':self.navigation.copy(),
                    'preparation':self.preparation,'mission':dict(self.mission),
                    'experiment':self.experiments.state() if self.experiments else None}

    def navigate(self,data):
        with self.operation:
            if self.experiments.active(): raise ValueError('Experiment owns autonomous control')
            path=self.runtime('/nav/plan',data)
            return {**path,**self.runtime('/nav/goal',data)}

    def begin_experiment(self,data):
        with self.operation: return self.experiments.start(data)

    def cancel_navigation(self):
        try:
            if self.experiments.active(): self.experiments.finish('CANCELLED','Operator took control')
        finally:result=self.runtime('/nav/cancel',{})
        return result

    def close(self):
        with self.lock:self.closed=True;self.cancel.set()
        self.scheduler.join(timeout=2)
        if self.campaigns:self.campaigns.close()
        self.experiments.close()
        with self.lock:
            if self.record: self.record.finish('interrupted'); self.record=None
            model=self.model; self.model=None
            if model:future=self.executor.submit(model.close)
        if model:future.result(timeout=120)
        # The process-wide native owner remains alive for subsequent sessions.


def serve(session,host,port):
    evidence=EvidenceLibrary()
    class Handler(BaseHTTPRequestHandler):
        def send(self,status,payload,content_type='application/json'):
            body=payload if isinstance(payload,bytes) else json.dumps(payload,allow_nan=False).encode()
            self.send_response(status); self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store')
            self.end_headers(); self.wfile.write(body)
        def do_GET(self):
            path=urlparse(self.path).path
            try:
                if path=='/health': return self.send(200,{'status':'ok','backend':'Sionna RT CPU','builder':True})
                if path=='/api/state': return self.send(200,session.state())
                if path=='/api/research':return self.send(200,evidence.overview())
                if path.startswith('/api/research/files/'):
                    file=evidence.file(path.removeprefix('/api/research/files/'))
                    return self.send(200,file.read_bytes(),mimetypes.guess_type(file)[0] or 'application/octet-stream')
                if path.startswith('/api/research/runs/'):
                    parts=path.removeprefix('/api/research/runs/').split('/')
                    if len(parts)!=2:raise ValueError('Expected recorded cohort/run')
                    cohort,identity=parts
                    if identity.endswith('.zip'):return self.send(200,evidence.run_bytes(cohort,identity[:-4]),'application/zip')
                    return self.send(200,evidence.run(cohort,identity))
                if path.startswith('/api/research/references/'):
                    parts=path.removeprefix('/api/research/references/').split('/')
                    if len(parts)!=2:raise ValueError('Expected recorded cohort/run')
                    return self.send(200,evidence.reference_for_run(*parts))
                if path=='/api/datasets': return self.send(200,list_datasets(session.data))
                if path=='/api/experiments': return self.send(200,session.experiments.manifests())
                if path=='/api/missions':return self.send(200,catalog())
                if path=='/api/campaign/state':return self.send(200,session.campaigns.state())
                if path.startswith('/api/campaign/worker/') and path.endswith('/state'):
                    index=int(path.split('/')[-2])
                    if not 0<=index<4:raise ValueError('Invalid worker index')
                    return self.send(200,json.load(session.http.open(f'http://127.0.0.1:{8101+index}/api/state',timeout=5)))
                if path=='/api/campaigns':return self.send(200,session.campaigns.listing())
                if path.startswith('/api/campaigns/') and path.endswith('.zip'):
                    return self.send(200,session.campaigns.archive(path.split('/')[-1][:-4]),'application/zip')
                if path.startswith('/api/missions/'):return self.send(200,mission(path.split('/')[-1]))
                if path=='/api/navigation/map': return self.send(200,json.loads((session.root/'navigation/map.json').read_text()))
                if path.startswith('/api/experiments/'):
                    identity=path.split('/')[-1]
                    if identity.endswith('.zip'): return self.send(200,session.experiments.archive(identity[:-4]),'application/zip')
                    after=int(parse_qs(urlparse(self.path).query).get('after',['-1'])[0])
                    return self.send(200,session.experiments.replay(identity,after))
                if path.startswith('/api/datasets/') and path.endswith('.zip'):
                    return self.send(200,archive(session.data,path.split('/')[-1][:-4]),'application/zip')
                if path.startswith('/api/datasets/'):
                    identity=path.split('/')[-1]
                    return self.send(200,read_dataset(session.data,identity))
                if path.startswith('/api/preset/'):
                    name=path.split('/')[-1]
                    if name not in ('empty','room','corridor','warehouse','courtyard'): raise FileNotFoundError('Preset not found')
                    return self.send(200,preset(name))
                if path.startswith('/assets/husky/'):
                    root=session.root/'assets/husky'; relative=path.removeprefix('/assets/husky/')
                else:
                    root=ROOT/'frontend/dist'; relative='index.html' if path=='/' else path.lstrip('/')
                file=(root/relative).resolve()
                if not file.is_relative_to(root.resolve()) or not file.is_file(): raise FileNotFoundError('File not found. Build frontend with npm run build.')
                return self.send(200,file.read_bytes(),mimetypes.guess_type(file)[0] or 'application/octet-stream')
            except (ValueError,KeyError) as e: self.send(400,{'error':str(e)})
            except FileNotFoundError as e: self.send(404,{'error':str(e)})
            except (OSError,urllib.error.URLError) as e:self.send(503,{'error':'Worker is not available: '+str(e)})
        def do_POST(self):
            try:
                n=int(self.headers.get('Content-Length',0))
                if not 0<n<=1024*1024: raise ValueError('Body must be 1..1048576 bytes')
                data=json.loads(self.rfile.read(n)); path=urlparse(self.path).path
                actions={'/api/validate':lambda:normalize(data),'/api/scene':lambda:session.apply(data),'/api/sample':lambda:session.sample(),
                         '/sample':lambda:session.sample(data.get('position_m')),
                         '/api/robot/start':session.start,'/api/robot/stop':session.stop,
                         '/api/robot/control':lambda:session.control(data),'/api/robot/telemetry':lambda:session.telemetry(data),
                         '/api/record/start':session.begin_record,'/api/record/stop':session.end_record,
                         '/api/grid/start':lambda:session.grid(data),
                         '/api/navigation/goal':lambda:session.navigate(data),
                         '/api/navigation/plan':lambda:session.runtime('/nav/plan',data),
                         '/api/navigation/cancel':session.cancel_navigation,
                         '/api/experiments/start':lambda:session.begin_experiment(data),
                         '/api/session/prepare':lambda:session.prepare(data),
                         '/api/mission/start':lambda:session.launch_mission(data),
                         '/api/mission/stop':session.stop_mission,
                         '/api/campaign/start':lambda:session.campaigns.start(data),
                         '/api/campaign/stop':lambda:session.campaigns.stop(),
                         '/api/experiments/stop':session.experiments.stop,
                         '/api/grid/cancel':lambda:(session.cancel.set() or {'status':'cancelling'})}
                if path not in actions: return self.send(404,{'error':'Unknown route'})
                self.send(200,actions[path]())
            except (ValueError,KeyError,TypeError,OverflowError) as e: self.send(400,{'error':str(e)})
            except Exception as e: self.send(500,{'error':str(e)})
        def log_message(self,format,*args):
            if '/api/state' not in format%args and '/telemetry' not in format%args:
                super().log_message(format,*args)
    server=ThreadingHTTPServer((host,port),Handler)
    try: server.serve_forever()
    finally: server.server_close(); session.close()


def main():
    def terminate(*_):raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM,terminate)
    parser=argparse.ArgumentParser(); parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8010); parser.add_argument('--runtime',default=os.environ.get('RADIO_LAB_RUNTIME',str(ROOT/'.runtime')))
    args=parser.parse_args(); serve(Session(args.runtime),args.host,args.port)


if __name__=='__main__': main()
