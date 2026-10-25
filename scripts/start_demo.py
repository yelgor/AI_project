"""Start one live responsive GPR mission after services are ready, with a 3D-map URL."""
import argparse
import json
import time
import urllib.error
import urllib.request


def start(base,mission,wait_s=120):
    http=urllib.request.build_opener(urllib.request.ProxyHandler({}));deadline=time.monotonic()+wait_s
    while True:
        try:
            with http.open(base+'/health',timeout=3) as response:
                if json.load(response).get('status')=='ok':break
        except (urllib.error.URLError,TimeoutError):pass
        if time.monotonic()>=deadline:raise TimeoutError('Radio API did not become ready')
        time.sleep(.5)
    payload={'mission':mission,'response_profile':'responsive','config':{'method':'GPR-pathloss','beta':1}}
    request=urllib.request.Request(base+'/api/mission/start',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    try:
        with http.open(request,timeout=10) as response:result=json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(error.read().decode()) from error
    print('Mission preparation requested:',result.get('status'))
    print('Open '+base+'/experiments.html?method=GPR-pathloss&beta=1&layer=height')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base',default='http://127.0.0.1:8010')
    p.add_argument('--mission',choices=('shadow','office','warehouse','district','courtyard'),default='shadow')
    args=p.parse_args()
    try:start(args.base.rstrip('/'),args.mission)
    except (RuntimeError,TimeoutError,urllib.error.URLError) as error:raise SystemExit('Cannot start mission: '+str(error))
