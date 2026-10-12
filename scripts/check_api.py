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
first=sample([-10,10,1]); second=sample([10,0,1])
for result in (first,second):
    assert result['path_count']>0
    assert math.isfinite(result['rssi_dbm'])
    assert result['paths']
assert abs(first['rssi_dbm']-second['rssi_dbm'])>1
try:
    sample([0,0,2])
    raise AssertionError('Position inside a building was accepted')
except urllib.error.HTTPError as error:
    assert error.code==400
print('API OK: visible/blocked positions, nonzero paths, invalid-position rejection')
print('RSSI:',first['rssi_dbm'],second['rssi_dbm'])
