"""Full scene -> official Husky -> 3D antenna -> dataset -> portable ZIP check.

Applies the room preset and drives only the simulated robot. Run with no active dataset.
"""
import argparse
import csv
import io
import json
import math
import time
import urllib.request
import zipfile

parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8010')
parser.add_argument('--runtime-url',default='http://127.0.0.1:8766')
args=parser.parse_args()
http=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def call(route,data=None):
    request=urllib.request.Request(args.url+route,json.dumps(data).encode() if data is not None else None,{'Content-Type':'application/json'})
    try: return json.load(http.open(request,timeout=120))
    except urllib.error.HTTPError as error:
        raise RuntimeError(json.load(error).get('error',str(error))) from error
deadline=time.monotonic()+60
while True:
    try:
        if call('/health').get('builder'): break
    except OSError:
        pass
    if time.monotonic()>deadline: raise RuntimeError('Constructor API not ready')
    time.sleep(.5)
deadline=time.monotonic()+60
while True:
    try:
        if json.load(http.open(args.runtime_url+'/health',timeout=5))['status']=='ok': break
    except OSError: pass
    if time.monotonic()>deadline: raise RuntimeError('Husky runtime not ready')
    time.sleep(.5)
scene=call('/api/preset/room');scene['rx']['mode']='husky'
scene['rx']['mount_position']=[.4,0,.7]
call('/api/scene',scene);call('/api/robot/start',{})
try:
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        state=call('/api/state')
        if state['robot_status']=='running' and state['measurement']: break
        time.sleep(.5)
    else: raise RuntimeError('Husky world pose/radio measurement not ready within 60 seconds')
    start=state['robot_pose']['position']
    assert abs(start[0])<.3 and abs(start[1]+2)<.3, ('Spawn/world frame mismatch',start)
    record=call('/api/record/start',{})
    deadline=time.monotonic()+4
    while time.monotonic()<deadline:
        call('/api/robot/control',{'linear':.3,'angular':0});time.sleep(.1)
    call('/api/robot/control',{'linear':0,'angular':0})
    time.sleep(1.5)
    state=call('/api/state');moved=math.dist(start,state['robot_pose']['position'])
    assert moved>.1, f'Robot did not move: {moved}'
    manifest=call('/api/record/stop',{})
    package=http.open(args.url+'/api/datasets/'+record['dataset_id']+'.zip').read()
    with zipfile.ZipFile(io.BytesIO(package)) as z:
        prefix=record['dataset_id']+'/'
        rows=[json.loads(line) for line in z.read(prefix+'measurements.jsonl').decode().splitlines()]
        table=list(csv.DictReader(io.StringIO(z.read(prefix+'measurements.csv').decode())))
        assert len(rows)>=2 and len(table)==len(rows)
        for row in rows:
            assert row['source']=='husky' and row['scene_revision']==manifest['scene_revision']
            # Independent geometric checks: yaw ~pi/2 rotates +X mount along world +Y.
            assert abs(row['position_m'][0]-row['robot_pose']['position'][0])<.1
            assert abs(row['position_m'][1]-row['robot_pose']['position'][1]-.4)<.1
            assert abs(row['position_m'][2]-row['robot_pose']['position'][2]-.7)<.1
            assert row['sim_time_s'] is not None and row['path_count']>0
        assert any(row['linear_x_mps']!='' for row in table)
    print(f'Constructor integration OK: world pose, 3D mount, {moved:.3f}m motion, {len(rows)} dataset rows, CSV/JSONL/ZIP')
finally:
    call('/api/robot/stop',{})
