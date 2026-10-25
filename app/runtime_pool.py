"""Owned ROS/Gazebo workers in one container, separated by domain and partition."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import urllib.request
import json


class RuntimePool:
    def __init__(self,root,runtime):
        self.root=Path(root);self.runtime=Path(runtime);self.lock=threading.Lock();self.workers={}
    def start(self,count):
        if os.environ.get('RADIO_POOL_WORKER'):raise ValueError('Nested pools are disabled')
        count=int(count)
        if not 1<=count<=4:raise ValueError('Choose 1..4 workers')
        with self.lock:
            for index in range(count):
                item=self.workers.get(index)
                if item and item['process'].poll() is None:continue
                directory=self.runtime/'workers'/str(index);directory.mkdir(parents=True,exist_ok=True)
                env=dict(os.environ,RADIO_POOL_WORKER=str(index+1),RADIO_LAB_RUNTIME=str(directory),
                    RUNTIME_PORT=str(8801+index),ROS_DOMAIN_ID=str(50+index),ROS_LOCALHOST_ONLY='1',
                    GZ_PARTITION=f'radio-lab-worker-{index}',RADIO_URL=f'http://radio:{8101+index}',
                    CLEARPATH_SETUP_PATH=f'/tmp/clearpath-worker-{index}',
                    ROS_LOG_DIR=f'/tmp/ros-worker-{index}',GZ_HOMEDIR=f'/tmp/gz-worker-{index}')
                log=open(directory/'runtime.log','ab')
                process=subprocess.Popen([sys.executable,str(self.root/'app/husky_runtime.py')],
                    env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                self.workers[index]={'process':process,'log':log,'port':8801+index}
            return {'workers':[{'index':i,'port':self.workers[i]['port'],'ros_domain_id':50+i,
                                'gz_partition':f'radio-lab-worker-{i}'} for i in range(count)]}
    def stop(self):
        with self.lock:
            items=list(self.workers.values());self.workers={}
        def close(item):
            process=item['process']
            if process.poll() is None:
                try:os.killpg(process.pid,signal.SIGTERM)
                except ProcessLookupError:pass
                try:process.wait(timeout=25)
                except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
            item['log'].close()
        threads=[threading.Thread(target=close,args=(item,)) for item in items]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        return {'status':'stopped'}
