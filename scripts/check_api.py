"""Functional check against the running radio service."""
import argparse
import json
import math
import time
import urllib.error
import urllib.request

parser=argparse.ArgumentParser()
parser.add_argument('--url',default='http://127.0.0.1:8010')
args=parser.parse_args()
deadline=time.monotonic()+60
while True:
    try:
        assert json.load(urllib.request.urlopen(args.url+'/health',timeout=5))['status']=='ok'
        break
    except (urllib.error.URLError, OSError):
        if time.monotonic()>=deadline: raise
        time.sleep(.5)
def sample(position):
    req=urllib.request.Request(args.url+'/sample',json.dumps({'position_m':position}).encode(),
                               {'Content-Type':'application/json'})
    return json.load(urllib.request.urlopen(req,timeout=60))
state=json.load(urllib.request.urlopen(args.url+'/api/state'))
rx=state['scenario']['rx']['position']
if state['scenario']['rx']['mode']=='husky':
    # The unused static-Rx coordinates may lie inside a building in a mounted
    # mission. Probe the actual antenna, or the free robot spawn if stopped.
    rx=(state.get('measurement') or {}).get('position_m')
    if rx is None:
        robot=state['scenario']['robot']['position'];mount=state['scenario']['rx']['mount_position']
        rx=[robot[0],robot[1],robot[2]+mount[2]]
first=sample(rx); second=sample([rx[0]+.4,rx[1],rx[2]+.1])
for result in (first,second):
    assert result['path_count']>0
    assert math.isfinite(result['rssi_dbm'])
    assert result['paths']
assert first['position_m']!=second['position_m']
try:
    sample(state['scenario']['objects'][0]['center'])
    raise AssertionError('Position inside a building was accepted')
except urllib.error.HTTPError as error:
    assert error.code==400
print('API OK: 3D positions, nonzero CIR, solid-position rejection')
print('RSSI:',first['rssi_dbm'],second['rssi_dbm'])
