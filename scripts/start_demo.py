"""Start one live responsive GPR mission after services are ready, with a 3D-map URL."""
import argparse
from http.client import HTTPException
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def wait_ready(http,url,label,deadline,ready):
    print('Waiting for '+label+'...',flush=True)
    last_error='service has not reported readiness'
    while True:
        remaining=deadline-time.monotonic()
        if remaining<=0:
            raise TimeoutError(label+' did not become ready: '+last_error+
                '. Inspect: docker compose logs --tail 80 radio husky')
        try:
            with http.open(url,timeout=min(3,remaining)) as response:
                payload=json.load(response)
            if isinstance(payload,dict) and payload.get('status')=='ok' and ready(payload):
                print(label+' ready.',flush=True);return
            last_error='unexpected or not-ready health response'
        except (OSError,HTTPException,json.JSONDecodeError,UnicodeDecodeError) as error:
            # Docker can publish a port before the application starts listening,
            # or close/reset an accepted socket while its process is starting.
            last_error=type(error).__name__+': '+str(error)
        time.sleep(min(.5,max(0,deadline-time.monotonic())))


def start(base,mission,wait_s=120,husky_base=None):
    http=urllib.request.build_opener(urllib.request.ProxyHandler({}));deadline=time.monotonic()+wait_s
    if husky_base is None:
        parts=urllib.parse.urlsplit(base)
        host=parts.hostname or '127.0.0.1';host='['+host+']' if ':' in host else host
        husky_base=urllib.parse.urlunsplit((parts.scheme,host+':8766','','',''))
    wait_ready(http,base+'/health','Radio API',deadline,lambda p:p.get('builder') is True)
    # The supervisor must be available; Nav2 becomes ready after the world starts.
    wait_ready(http,husky_base.rstrip('/')+'/health','Husky API',deadline,lambda p:isinstance(p.get('navigation'),dict))
    payload={'mission':mission,'response_profile':'responsive','config':{'method':'GPR-pathloss','beta':1}}
    request=urllib.request.Request(base+'/api/mission/start',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    viewer=base+'/experiments.html?method=GPR-pathloss&beta=1&layer=height'
    try:
        with http.open(request,timeout=10) as response:result=json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(error.read(4096).decode(errors='replace')) from error
    except (OSError,HTTPException,json.JSONDecodeError,UnicodeDecodeError) as error:
        # Never retry a POST whose outcome is unknown: it may have started a mission.
        raise RuntimeError('Connection interrupted during mission start; it may already be running. '
            'Check '+viewer+' before retrying. The start request was not repeated.') from error
    if not isinstance(result,dict) or result.get('status') not in ('starting','running'):
        raise RuntimeError('Mission start was not confirmed. Check '+viewer)
    print('Mission preparation requested:',result.get('status'))
    print('Open '+viewer)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base',default='http://127.0.0.1:8010')
    p.add_argument('--husky-base',help='Husky supervisor URL; default: the same host on port 8766')
    p.add_argument('--wait-seconds',type=float,default=120,help='Combined readiness deadline for both services')
    p.add_argument('--mission',choices=('shadow','office','warehouse','district','courtyard'),default='shadow')
    args=p.parse_args(argv)
    if not 0<args.wait_seconds<=900:p.error('--wait-seconds must be within (0, 900]')
    try:start(args.base.rstrip('/'),args.mission,args.wait_seconds,args.husky_base)
    except (RuntimeError,OSError,HTTPException,ValueError) as error:
        print('Cannot start mission: '+str(error),file=sys.stderr);return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
