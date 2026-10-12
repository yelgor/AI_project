"""Scene constructor backend, upstream radio solver and experiment sessions."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import threading
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
import uuid
import mimetypes

try:
    from .scenario import normalize, preset, antenna_pose, vector, finite
    from .radio import Radio, export_gazebo
    from .datasets import Dataset, list_datasets, archive, atomic_json
except ImportError:
    from scenario import normalize, preset, antenna_pose, vector, finite
    from radio import Radio, export_gazebo
    from datasets import Dataset, list_datasets, archive, atomic_json

ROOT=Path(__file__).resolve().parents[1]


class Session:
    def __init__(self, root=ROOT/'.runtime', husky_url=None):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        self.data=self.root/'datasets'; self.data.mkdir(exist_ok=True)
        self.lock=threading.RLock(); self.operation=threading.Lock()
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='sionna')
        self.scene=None; self.model=None; self.revision=None; self.pose=None
        self.measurement=None; self.error=None; self.robot_status='stopped'
        self.record=None; self.job=None; self.cancel=threading.Event()
        for file in self.data.glob('*/manifest.json'):
            manifest=json.loads(file.read_text())
            if manifest.get('status')=='collecting':
                manifest['status']='interrupted'
                atomic_json(file,manifest)
        self.pending=False; self.closed=False; self.last_sample=0; self.pose_received=0
        self.husky_url=husky_url or os.environ.get('HUSKY_URL','http://husky:8766')
        self.http=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        saved=self.root/'active_scene.json'
        scenario=json.loads(saved.read_text())['scenario'] if saved.exists() else json.loads((ROOT/'config/scenario.json').read_text())
        self.apply(scenario)
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
            scene=normalize(data)
            with self.lock:
                if self.record or (self.job and self.job['status']=='running'):
                    raise ValueError('Finish/cancel the dataset before applying another scene')
                running=self.robot_status in ('running','starting')
            if running: self.stop()
            model=self.executor.submit(Radio,scene).result(timeout=120)
            revision=uuid.uuid4().hex[:12]
            export_gazebo(scene,self.root/'world.sdf.tmp')
            (self.root/'world.sdf.tmp').replace(self.root/'world.sdf')
            atomic_json(self.root/'active_scene.json',{'revision':revision,'scenario':scene})
            with self.lock:
                self.scene=scene; self.model=model; self.revision=revision
                self.pose=None; self.measurement=None; self.error=None; self.job=None
                self.robot_status='stopped'; self.pose_received=0
            return {'revision':revision,'scenario':scene}

    def start(self):
        with self.operation:
            if self.record: raise ValueError('Finish recording before restarting Husky')
            if self.job and self.job['status']=='running': raise ValueError('Wait for grid completion')
            result=self.runtime('/start',{'revision':self.revision})
            with self.lock: self.robot_status='starting'; self.pose=None; self.pose_received=0
            return result

    def stop(self):
        self.runtime('/stop',{})
        with self.lock:
            self.robot_status='stopped'; self.pose=None; self.pose_received=0
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
            if data.get('scene_revision')!=self.revision: raise ValueError('Stale telemetry revision')
            if self.robot_status not in ('running','starting'): raise ValueError('Simulation is stopped')
            self.pose={'position':position,'quaternion_xyzw':q,'sim_time_s':sim_time,
                       'linear_velocity':data.get('linear_velocity'),'angular_velocity':data.get('angular_velocity')}
            self.pose_received=time.monotonic(); self.robot_status='running'
            return {'measurement':self.measurement}

    def sample(self, override=None, source=None):
        with self.lock:
            scene=self.scene; revision=self.revision; model=self.model; recording=self.record
            pose=json.loads(json.dumps(self.pose)) if self.pose else None
            stale=time.monotonic()-self.pose_received>3
        if override is not None:
            position=vector(override,'position_m'); orientation=scene['rx']['orientation_rad']; source=source or 'manual'
        elif scene['rx']['mode']=='husky':
            if not pose or stale: raise ValueError('No current Gazebo world pose; run Husky first')
            position,orientation=antenna_pose(scene,pose); source=source or 'husky'
        else:
            position=scene['rx']['position']; orientation=scene['rx']['orientation_rad']; source=source or 'static'
        result=self.executor.submit(model.sample,position,orientation).result(timeout=120)
        result.update({'scene_revision':revision,'source':source,'orientation_rad':orientation,
                       'tx_position_m':scene['tx']['position'],'robot_pose':pose if source=='husky' else None,
                       'sim_time_s':pose['sim_time_s'] if pose and source=='husky' else None})
        with self.lock:
            if revision==self.revision:
                self.measurement=result; self.error=None
                if recording is not None and self.record is recording: recording.append(result)
        return result

    def tick(self):
        while not self.closed:
            with self.lock:
                should=(self.record is not None or (self.scene['rx']['mode']=='husky' and self.robot_status=='running'))
                period=self.scene['radio']['period_s']
                should=should and not self.pending and time.monotonic()-self.last_sample>=period
                if should: self.pending=True; self.last_sample=time.monotonic()
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
                    'job':self.job.copy() if self.job else None}

    def close(self):
        self.closed=True; self.cancel.set()
        with self.lock:
            if self.record: self.record.finish('interrupted'); self.record=None
        self.executor.shutdown(wait=True)


def serve(session,host,port):
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
                if path=='/api/datasets': return self.send(200,list_datasets(session.data))
                if path.startswith('/api/datasets/') and path.endswith('.zip'):
                    return self.send(200,archive(session.data,path.split('/')[-1][:-4]),'application/zip')
                if path.startswith('/api/preset/'):
                    name=path.split('/')[-1]
                    if name not in ('empty','room','corridor'): raise FileNotFoundError('Preset not found')
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
    parser=argparse.ArgumentParser(); parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8010); parser.add_argument('--runtime',default=str(ROOT/'.runtime'))
    args=parser.parse_args(); serve(Session(args.runtime),args.host,args.port)


if __name__=='__main__': main()
