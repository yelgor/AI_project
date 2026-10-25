"""Show a spatial holdout at the loss checkpoint: reference, predictions and error."""
import argparse
import json
import math
import os
from pathlib import Path
import sys
os.environ.setdefault('MPLCONFIGDIR',str(Path(__file__).resolve().parents[1]/'.cache/matplotlib'))
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.study_reference import load_cases
from app.radio_maps import RadioMap


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('campaign',type=Path)
    p.add_argument('--scene',default='warehouse-a');p.add_argument('--runtime',type=Path,default=Path('.runtime'))
    p.add_argument('--output',type=Path);args=p.parse_args()
    case=next(c for c in load_cases(args.campaign,args.runtime,1) if c['scene']==args.scene)
    sources=json.loads((args.campaign/'sources.json').read_text());scene=sources[args.scene]['scene']
    profiles=json.loads((args.campaign/'reference-study/recommended-config.json').read_text())
    points=case['points'];values=case['values'];known=np.asarray([o['position_m'] for o in case['observations']])
    predictions={};sigma={}
    for method in ('IDW','GPR-zero','GPR-pathloss'):
        profile=profiles[method];model=RadioMap(method,case['tx'],profile['noise_db'],profile['optimize_gpr']).fit(case['observations'])
        mean,std=model.predict(points);predictions[method]=np.asarray(mean);sigma[method]=std
    panels=[('Independent Sionna reference',values,'RdYlGn',-100,-20),
            ('IDW',predictions['IDW'],'RdYlGn',-100,-20),
            ('GPR-zero (offline tuned)',predictions['GPR-zero'],'RdYlGn',-100,-20),
            ('GPR-pathloss (offline tuned)',predictions['GPR-pathloss'],'RdYlGn',-100,-20),
            ('Absolute GPR-pathloss error (dB)',np.abs(predictions['GPR-pathloss']-values),'YlOrRd',0,35),
            ('Latent GPR-pathloss sigma (dB)',sigma['GPR-pathloss'],'YlOrRd',0,40)]
    fig,axes=plt.subplots(2,3,figsize=(15,10))
    for ax,(title,data,cmap,lo,hi) in zip(axes.flat,panels):
        dots=ax.scatter(points[:,0],points[:,1],c=data,cmap=cmap,vmin=lo,vmax=hi,s=23,marker='s')
        ax.plot(known[:,0],known[:,1],color='#203e37',lw=1,label='Measured prefix')
        ax.scatter(*case['tx'][:2],marker='*',s=120,color='#ed843b',edgecolors='black',zorder=5)
        for obj in scene['objects']:
            if obj['center'][2]+obj['size'][2]/2<=.01:continue
            c,s=math.cos(obj['yaw_rad']),math.sin(obj['yaw_rad']);w,h=obj['size'][:2]
            corners=[[obj['center'][0]+c*x-s*y,obj['center'][1]+s*x+c*y] for x,y in [(-w/2,-h/2),(w/2,-h/2),(w/2,h/2),(-w/2,h/2)]]
            ax.add_patch(Polygon(corners,facecolor='#abb0a4',edgecolor='#697362',alpha=.85))
        ax.set_title(title,fontsize=10);ax.set_aspect('equal');ax.set_xlabel('World X (m)');ax.set_ylabel('World Y (m)')
        fig.colorbar(dots,ax=ax,fraction=.04,pad=.025)
    fig.suptitle(args.scene+': predictions use only the common pre-loss history',fontsize=14)
    fig.text(.5,.01,'Reference points are at least 1m from every known sample. Blank strips are excluded holdout points; grey polygons are physical obstacles.',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.035,1,.96));output=args.output or args.campaign/'reference-study'/(args.scene+'.png')
    output.parent.mkdir(parents=True,exist_ok=True);fig.savefig(output,dpi=170);plt.close(fig);print(output)


if __name__=='__main__':main()
