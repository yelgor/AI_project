"""Compare the recorded corner timeout and the verified larger-clearance route."""
import argparse
import json
import math
import os
from pathlib import Path
import sys
os.environ.setdefault('MPLCONFIGDIR',str(Path(__file__).resolve().parents[1]/'.cache/matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.analyze_campaign import read_run


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('baseline',type=Path);p.add_argument('updated',type=Path)
    p.add_argument('--runtime',type=Path,default=Path('.runtime'));args=p.parse_args();fig,axes=plt.subplots(1,2,figsize=(12,5));rows=[]
    for ax,cohort,title in zip(axes,(args.baseline,args.updated),('Original corner route','Updated Nav2 clearance')):
        attempts=[json.loads(l) for l in (cohort/'attempts.jsonl').read_text().splitlines()]
        attempt=next(r for r in attempts if r['config']['label']=='shadow-a' and r['config']['method']=='B1' and r['config']['pair_id']=='shadow-a-0')
        meta,scene,events=read_run(args.runtime,attempt['experiment_id'])
        target=next(e['target'] for e in events if e['kind']=='target');poses=[e['pose']['position'] for e in events if e['kind']=='pose'];path=target['path']
        clearance=lambda point:math.hypot(max(abs(point[0])-2,0),max(abs(point[1])-2,0))
        row={'experiment_id':attempt['experiment_id'],'status':attempt['status'],'history_from':meta['config']['history_from'],
            'first_target':target['base'],'first_path_minimum_obstacle_clearance_m':min(map(clearance,path)),
            'recorded_pose_minimum_obstacle_clearance_m':min(map(clearance,poses)),
            'path_clearance_above_configured_radius_m':min(map(clearance,path))-.55,
            'recovery_time_s':attempt['metrics']['recovery_time_s']};rows.append(row)
        ax.add_patch(Rectangle((-2,-2),4,4,facecolor='#c5c5b5',edgecolor='#65695c'))
        ax.plot(*zip(*[(p[0],p[1]) for p in path]),color='#d8883a',ls='--',label='First Nav2 plan')
        ax.plot(*zip(*[(p[0],p[1]) for p in poses]),color='#267b61',lw=2,label='Recorded motion')
        ax.scatter(*poses[0][:2],marker='o',color='#337d9c',s=45)
        ax.scatter(*poses[-1][:2],marker='x',color='#a34332',s=50)
        ax.set_xlim(-3.5,5);ax.set_ylim(-2.5,5);ax.set_aspect('equal');ax.grid(alpha=.2)
        ax.set_xlabel('World X (m)');ax.set_ylabel('World Y (m)')
        ax.set_title(title+f'\n{attempt["status"]}, {row["recovery_time_s"]:.2f}s')
        ax.text(.02,.02,f'Minimum planned clearance: {row["first_path_minimum_obstacle_clearance_m"]:.3f}m',transform=ax.transAxes,fontsize=9)
        ax.legend(loc='lower right',fontsize=8)
    assert rows[0]['history_from']==rows[1]['history_from']
    output=args.updated/'comparison';output.mkdir(exist_ok=True)
    (output/'corner-clearance.json').write_text(json.dumps({'configured_robot_radius_m':.55,'same_pre_loss_history':True,'runs':rows},indent=2)+'\n')
    fig.suptitle('Same radio history and loss checkpoint; different Nav2 tracking configuration')
    fig.tight_layout();fig.savefig(output/'corner-clearance.png',dpi=180);plt.close(fig);print(output/'corner-clearance.png')


if __name__=='__main__':main()
