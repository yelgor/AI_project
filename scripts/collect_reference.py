"""Collect a separate Sionna grid for the current field, without training a controller."""
import argparse
from pathlib import Path
from run_experiments import API

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url',default='http://127.0.0.1:8010')
parser.add_argument('--bounds',nargs=4,type=float,default=[-3,-3,3,3])
parser.add_argument('--height',type=float,default=.83)
parser.add_argument('--step',type=float,default=1.)
parser.add_argument('--output',default='.runtime/reports/reference.zip')
args=parser.parse_args();api=API(args.url);state=api.call('/api/state')
if state['robot_status']!='stopped': raise SystemExit('Stop Husky first; this tool never interrupts a running experiment')
if state['recording'] or (state['job'] and state['job']['status']=='running'):raise SystemExit('Another collection is active')
x0,y0,x1,y1=args.bounds
job=api.call('/api/grid/start',{'min':[x0,y0,args.height],'max':[x1,y1,args.height],'step':[args.step,args.step,1]})
state=api.wait(lambda s:s['job'] and s['job']['dataset_id']==job['dataset_id'] and s['job']['status']!='running',timeout=3600)
if state['job']['status']!='completed':raise SystemExit('Reference grid failed: '+str(state['job']))
output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
output.write_bytes(api.http.open(api.url+'/api/datasets/'+job['dataset_id']+'.zip',timeout=120).read())
print('Reference dataset:',job['dataset_id'],'→',output)
