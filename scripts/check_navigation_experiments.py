"""Live Nav2 obstacle avoidance + RSSI recovery + causal replay/ZIP acceptance check."""
import argparse
import io
import json
import math
import time
import zipfile
from run_experiments import API

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url',default='http://127.0.0.1:8010')
args=parser.parse_args(); api=API(args.url)
state=api.call('/api/state')
if state['recording'] or (state['job'] and state['job']['status']=='running') or (state['experiment'] and state['experiment']['status']=='running'):
    raise SystemExit('Finish active data collection before this test; it replaces the scene')
try:
    scene=api.call('/api/preset/room');scene['rx']['mode']='husky';scene['rx']['mount_position']=[0,0,.7]
    scene['objects'].append({'id':'test-obstacle','label':'Nav2 obstacle','center':[0,0,.6],
        'size':[1.2,2,1.2],'yaw_rad':0,'material':'wood','thickness_m':.2})
    api.call('/api/scene',scene);api.call('/api/robot/start',{})
    state=api.wait(lambda s:s['robot_status']=='running' and s['navigation'].get('ready'))
    start=state['robot_pose']['position']
    plan=api.call('/api/navigation/goal',{'position':[0,2,1.57]})
    assert plan['length_m']>4.3 and max(abs(p[0]) for p in plan['path'])>1.1,plan
    state=api.wait(lambda s:s['navigation']['status'] in ('succeeded','failed'),timeout=120)
    assert state['navigation']['status']=='succeeded',state['navigation']
    assert math.dist(state['robot_pose']['position'][:2],[0,2])<.35,state['robot_pose']
    assert math.dist(start,state['robot_pose']['position'])>3.5
    try:
        api.call('/api/navigation/plan',{'position':[0,0,0]})
        raise AssertionError('Nav2 accepted a goal inside the obstacle')
    except RuntimeError as e:
        assert 'reachable' in str(e) or 'rejected' in str(e) or 'clearance' in str(e),e
    print(f'Nav2 OK: {plan["length_m"]:.2f}m planned detour, physical goal reached, solid goal rejected',flush=True)
    api.call('/api/navigation/goal',{'position':[0,-2,-1.57]})
    api.wait(lambda s:abs((s['robot_pose'].get('linear_velocity') or [0])[0])>.1,timeout=40)
    api.call('/api/navigation/cancel',{})
    state=api.wait(lambda s:s['navigation']['authority']=='teleop')
    braking=state['robot_pose']['position'];time.sleep(1)
    state=api.call('/api/state')
    assert math.dist(braking,state['robot_pose']['position'])<.2, 'Robot continued after cancel'
    print('Cancel OK: Nav2 interrupted, drive stopped, teleop restored',flush=True)
    scene=api.call('/api/preset/room');scene['rx']['mode']='husky';scene['rx']['mount_position']=[0,0,.7]
    api.call('/api/scene',scene);api.call('/api/robot/start',{})
    api.wait(lambda s:s['robot_status']=='running' and s['navigation'].get('ready') and s['measurement'] is not None)
    meta=api.call('/api/experiments/start',{'method':'B1','q_safe_dbm':-32,'hysteresis_db':1,
        'degraded_s':1,'stable_s':1.5,'timeout_s':120,'route':[[0,-6,-1.57]]})
    state=api.wait(lambda s:s['experiment']['status']!='running',timeout=180)
    run=api.call('/api/experiments/'+meta['experiment_id']);timeline=run['timeline']
    assert run['manifest']['status']=='RECOVERED_WAIT',run['manifest']
    modes=[e['mode'] for e in timeline if e['kind']=='mode']
    for mode in ('SURVEY','LINK_DEGRADED','RECOVERY','RECOVERED_WAIT'):assert mode in modes,modes
    assert any(e['kind']=='target' and e['target']['path'] for e in timeline)
    observations=0
    for event in timeline:
        if event['kind']=='observation':
            observations+=1
            assert event['measurement']['sim_time_s']<=event['sim_time_s']
        if event['kind']=='map':assert event['observation_count']<=observations
    package=api.http.open(api.url+'/api/experiments/'+meta['experiment_id']+'.zip').read()
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        assert json.loads(archive.read(meta['experiment_id']+'/manifest.json'))['metrics']['success']
    api.wait(lambda s:s['navigation']['authority']=='hold')
    print('Recovery OK:',json.dumps(run['manifest']['metrics']),flush=True)
    print('Replay/ZIP OK:',meta['experiment_id'],len(timeline),'causal events',flush=True)
finally:
    api.call('/api/robot/stop',{})
