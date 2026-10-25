"""Parallel, restartable physical Gazebo campaigns; no Docker socket required."""
import copy
import json
import math
import os
from pathlib import Path
import queue
import signal
import shutil
import subprocess
import sys
import threading
import time
import uuid
import urllib.request
import zipfile
from datetime import datetime,timezone
try:
    from .missions import mission
    from .datasets import atomic_json,field_hash
    from .radio_maps import METHODS
except ImportError:
    from missions import mission
    from datasets import atomic_json,field_hash
    from radio_maps import METHODS

ROOT=Path(__file__).resolve().parents[1]


def schedule(config):
    count=int(config.get('runs',100));workers=int(config.get('workers',2))
    if not 1<=count<=10000:raise ValueError('runs must be 1..10000')
    if not 1<=workers<=4:raise ValueError('workers must be 1..4')
    if config.get('protocol','full') not in ('full','paired'):raise ValueError('protocol must be full or paired')
    names=config.get('missions',['shadow','office','warehouse','district','courtyard'])
    methods=config.get('methods',['B1']);betas=config.get('betas',[0,1])
    if not betas:raise ValueError('betas cannot be empty')
    if not names or not methods or any(m not in METHODS for m in methods):raise ValueError('Invalid missions/methods')
    if any(not math.isfinite(float(b)) or not 0<=float(b)<=5 for b in betas):raise ValueError('Invalid beta')
    variants=[(method,float(beta)) for method in methods for beta in (betas if method.startswith('GPR') else [0])]
    conditions=config.get('trials')
    if conditions is None:
        conditions=[]
        for name in names:
            for layout in (0,1):
                spec=mission(name,layout)
                conditions.append({'name':spec['scene']['name'],'world':name,'scene':spec['scene'],
                    'route':spec['config']['route'],'config':spec['config'],
                    'split':'validation' if name=='district' else 'test' if name=='courtyard' else 'train'})
    if not conditions:raise ValueError('No campaign conditions')
    tasks=[];repeat=0
    while len(tasks)<count:
        for condition in conditions:
            for method,beta in variants:
                if len(tasks)>=count:break
                trial=copy.deepcopy(condition)
                trial['config']['save_cir']=bool(config.get('save_cir',False))
                tasks.append({'index':len(tasks),'trial':trial,'method':method,'beta':beta,'repeat':repeat})
        repeat+=1
    # Keep geometry/Tx together so Gazebo and Sionna stay warm between methods/repeats.
    tasks.sort(key=lambda t:(t['trial']['name'],t['repeat'],t['method'],t['beta']))
    return tasks,workers


class Campaigns:
    def __init__(self,session):
        self.session=session;self.root=session.root/'campaigns';self.root.mkdir(exist_ok=True)
        self.lock=threading.RLock();self.current=None;self.cancel=threading.Event();self.thread=None
        for path in self.root.glob('*/manifest.json'):
            meta=json.loads(path.read_text())
            if meta['status'] in ('starting','running','finishing'):
                meta.update(status='interrupted',error='Backend restarted; resume to run unfinished task indices')
                atomic_json(path,meta)

    def state(self):
        with self.lock:
            if self.current is None:return None
            result=copy.deepcopy(self.current)
            result['config'].pop('trials',None)
            return result

    def listing(self):
        return [json.loads(p.read_text()) for p in sorted(self.root.glob('*/manifest.json'),reverse=True)]

    def start(self,config):
        tasks,workers=schedule(config)
        with self.lock:
            if self.thread and self.thread.is_alive():raise ValueError('Campaign already active or finishing cleanup')
            identity=config.get('resume') or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
            if any(c not in '0123456789TZabcdefghijklmnopqrstuvwxyz-' for c in identity):raise ValueError('Invalid campaign id')
            directory=self.root/identity;directory.mkdir(exist_ok=True)
            if config.get('resume'):
                stored=json.loads((directory/'manifest.json').read_text())
                tasks,workers=schedule(stored['config']);config=stored['config']
            resultsfile=directory/'attempts.jsonl'
            results=[json.loads(line) for line in resultsfile.read_text().splitlines()] if resultsfile.exists() else []
            completed={r['task_index'] for r in results}
            source_campaign=config.get('history_source_campaign')
            if source_campaign and not (directory/'sources.json').exists():
                if any(c not in '0123456789TZabcdefghijklmnopqrstuvwxyz-' for c in source_campaign):raise ValueError('Invalid history campaign id')
                origin=self.root/source_campaign;old=json.loads((origin/'manifest.json').read_text())
                if old['status'] in ('starting','running','finishing'):raise ValueError('Finish the history campaign first')
                previous=json.loads((origin/'sources.json').read_text());chosen={}
                for task in tasks:
                    name=task['trial']['name'];source=previous.get(name)
                    if not source or field_hash(source['scene'])!=field_hash(task['trial']['scene']):
                        raise ValueError('Reusable source missing or belongs to another RF field: '+name)
                    chosen[name]=source
                sources_dir=directory/'sources';sources_dir.mkdir(exist_ok=True)
                for source in chosen.values():
                    shutil.copyfile(origin/'sources'/(source['experiment_id']+'.zip'),sources_dir/(source['experiment_id']+'.zip'))
                atomic_json(directory/'sources.json',chosen)
            self.current={'campaign_id':identity,'status':'starting','total':len(tasks),'completed':len(completed),
                'successes':sum(bool(r.get('metrics',{}).get('success')) for r in results),
                'failures':sum(r['status'] not in ('RECOVERED_WAIT',) for r in results),
                'workers':workers,'config':copy.deepcopy(config),'active_workers':{},'recent':results[-12:],
                'started_at':datetime.now(timezone.utc).isoformat(),'wall_started':time.time(),'error':None,
                'mode':'physical Gazebo episodes; mounted receiver; measured RSSI'}
            self.current.update(protocol=config.get('protocol','full'),phase='starting',sources_completed=0)
            self.current['history_source_campaign']=source_campaign
            self.cancel.clear();atomic_json(directory/'manifest.json',self.current)
            self.thread=threading.Thread(target=self.run,args=(directory,tasks,workers,results,completed),daemon=True)
            self.thread.start();return self.state()

    def run(self,directory,tasks,workers,results,completed):
        sys.path.insert(0,str(ROOT))
        from scripts.run_experiments import API,run_trial,report
        processes=[];logs=[];threads=[];pending=queue.Queue();final_status='failed'
        for task in tasks:
            if task['index'] not in completed:pending.put(task)
        try:
            self.session.runtime('/pool/start',{'workers':workers})
            for index in range(workers):
                runtime=self.session.root/'workers'/str(index);runtime.mkdir(parents=True,exist_ok=True)
                env=dict(os.environ,RADIO_POOL_WORKER=str(index+1),RADIO_LAB_RUNTIME=str(runtime),
                    RADIO_EXPERIMENT_LIBRARY=str(self.session.root),
                    OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',
                    HUSKY_URL=f'http://husky:{8801+index}',RADIO_THREADS=str(max(1,int(os.environ.get('RADIO_BATCH_THREADS','1')))))
                log=open(runtime/'backend.log','ab');logs.append(log)
                process=subprocess.Popen([sys.executable,str(ROOT/'app/builder.py'),'--host','0.0.0.0',
                    '--port',str(8101+index),'--runtime',str(runtime)],stdout=log,stderr=subprocess.STDOUT,
                    env=env,start_new_session=True);processes.append(process)
            with self.lock:self.current['status']='running';atomic_json(directory/'manifest.json',self.current)
            sources={};source_file=directory/'sources.json'
            if source_file.exists():sources=json.loads(source_file.read_text())
            if self.current['protocol']=='paired':
                source_queue=queue.Queue();conditions={t['trial']['name']:t['trial'] for t in tasks}
                for name,trial in conditions.items():
                    if name not in sources:source_queue.put((name,trial))
                with self.lock:self.current.update(phase='collecting_histories',sources_total=len(conditions),sources_completed=len(sources))
                def collect(index):
                    api=API(f'http://127.0.0.1:{8101+index}')
                    try:
                        api.wait(lambda s:True,timeout=120,cancel=self.cancel)
                        while not self.cancel.is_set():
                            try:name,trial=source_queue.get_nowait()
                            except queue.Empty:break
                            with self.lock:self.current['active_workers'][str(index)]={'scene':name,'stage':'collecting loss checkpoint','method':'B1'}
                            source_trial=copy.deepcopy(trial);source_trial['name']='source-'+name
                            source_dir=directory/'sources';source_dir.mkdir(exist_ok=True)
                            try:
                                result=run_trial(api,source_trial,'B1',0.,0,source_dir,reuse=True,keep_running=True,cancel=self.cancel)
                                with self.lock:
                                    with (directory/'source_attempts.jsonl').open('a') as file:file.write(json.dumps({'scene':name,**result})+'\n')
                                identity=result.get('experiment_id')
                                if not identity:raise ValueError(result.get('reason','Source did not start'))
                                run=api.call('/api/experiments/'+identity);pose=None
                                for event in run['timeline']:
                                    if event['kind']=='pose':pose=event['pose']
                                    if event['kind']=='mode' and event['mode']=='LINK_DEGRADED':pose=event.get('pose',pose);break
                                else:raise ValueError('Source never lost its link behind the obstacle')
                                with self.lock:
                                    sources[name]={'experiment_id':identity,'pose':pose,'scene':run['scenario']}
                                    atomic_json(source_file,sources);self.current['sources_completed']=len(sources)
                                    atomic_json(directory/'manifest.json',self.current)
                            except Exception as error:
                                with self.lock:
                                    self.current['active_workers'][str(index)]={'scene':name,'error':str(error)}
                                    with (directory/'source_errors.jsonl').open('a') as file:file.write(json.dumps({'scene':name,'error':str(error)})+'\n')
                                if 'runtime unavailable' in str(error).lower():break
                            finally:source_queue.task_done()
                    except Exception as error:
                        with self.lock:self.current['active_workers'][str(index)]={'error':str(error)}
                source_threads=[threading.Thread(target=collect,args=(i,)) for i in range(workers)]
                for thread in source_threads:thread.start()
                for thread in source_threads:thread.join()
            with self.lock:self.current['phase']='episodes';self.current['active_workers']={}
            def work(index):
                api=API(f'http://127.0.0.1:{8101+index}')
                try:
                    api.wait(lambda s:True,timeout=120,cancel=self.cancel)
                    while not self.cancel.is_set():
                        try:task=pending.get_nowait()
                        except queue.Empty:break
                        with self.lock:self.current['active_workers'][str(index)]={'task_index':task['index'],'scene':task['trial']['name'],'method':task['method'],'beta':task['beta']}
                        try:
                            trial=copy.deepcopy(task['trial'])
                            if self.current['protocol']=='paired':
                                source=sources.get(trial['name'])
                                if source is None:raise ValueError('No valid obstacle-loss checkpoint for '+trial['name'])
                                pose=source['pose'];q=pose['quaternion_xyzw']
                                trial.update(scene=source['scene'],spawn=pose['position'][:2]+[.3],
                                    yaw_rad=math.atan2(2*(q[3]*q[2]+q[0]*q[1]),1-2*(q[1]*q[1]+q[2]*q[2])),route=[])
                                trial['config']['history_from']=source['experiment_id']
                            result=run_trial(api,trial,task['method'],task['beta'],task['repeat'],directory,
                                reuse=True,keep_running=True,cancel=self.cancel)
                        except Exception as error:
                            result={'status':'SETUP_FAILED','reason':str(error),'metrics':{},
                                'config':{'method':task['method'],'beta':task['beta'],'label':task['trial']['name'],
                                          'split':task['trial'].get('split','pilot'),
                                          'pair_id':task['trial']['name']+'-'+str(task['repeat'])}}
                            try:api.call('/api/robot/stop',{})
                            except Exception:pass
                        result.update(task_index=task['index'],worker_index=index)
                        with self.lock:
                            results.append(result)
                            with (directory/'attempts.jsonl').open('a') as file:file.write(json.dumps(result)+'\n')
                            self.current['completed']=len(results)
                            self.current['successes']+=int(bool(result.get('metrics',{}).get('success')))
                            self.current['failures']+=int(result['status']!='RECOVERED_WAIT')
                            self.current['recent']=copy.deepcopy(results[-12:])
                            self.current['active_workers'].pop(str(index),None)
                            atomic_json(directory/'manifest.json',self.current)
                        pending.task_done()
                        if 'runtime unavailable' in result.get('reason','').lower():break
                except Exception as error:
                    with self.lock:self.current['active_workers'][str(index)]={'error':str(error)}
                finally:
                    try:api.call('/api/robot/stop',{})
                    except Exception:pass
            threads=[threading.Thread(target=work,args=(index,)) for index in range(workers)]
            for thread in threads:thread.start()
            for thread in threads:thread.join()
            report(results,directory)
            if results:
                from scripts.analyze_campaign import analyze
                analysis=analyze(directory,self.session.root,directory/'analysis')
                with self.lock:self.current['quality']=analysis['overall']
            with self.lock:
                final_status='cancelled' if self.cancel.is_set() else 'completed' if len(results)==len(tasks) else 'failed'
                self.current['status']='finishing'
                self.current['wall_duration_s']=time.time()-self.current['wall_started']
        except Exception as error:
            with self.lock:self.current.update(status='failed',error=str(error))
        finally:
            for process in processes:
                if process.poll() is None:
                    try:os.killpg(process.pid,signal.SIGTERM)
                    except ProcessLookupError:pass
            for process in processes:
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
            try:self.session.runtime('/pool/stop',{})
            except Exception:pass
            for log in logs:log.close()
            with self.lock:
                if self.current['status']=='finishing':self.current['status']=final_status
                atomic_json(directory/'manifest.json',self.current)

    def stop(self):
        self.cancel.set();return self.state()

    def archive(self,identity):
        import io
        if not identity or any(c not in '0123456789TZabcdefghijklmnopqrstuvwxyz-' for c in identity):raise ValueError('Invalid campaign id')
        directory=self.root/identity;meta=json.loads((directory/'manifest.json').read_text())
        if meta['status'] in ('starting','running','finishing'):raise ValueError('Finish campaign before export')
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_STORED) as package:
            for file in directory.rglob('*'):
                if file.is_file():package.write(file,identity+'/'+str(file.relative_to(directory)))
        return buffer.getvalue()

    def close(self):
        self.cancel.set()
        if self.thread and self.thread.is_alive():self.thread.join(timeout=30)
