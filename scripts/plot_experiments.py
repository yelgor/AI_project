"""Export an honest per-trial comparison figure from a runner report."""
import argparse
import json
import os
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR',str(Path(__file__).resolve().parents[1]/'.cache/matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('report');parser.add_argument('--label',help='Filter trial label')
parser.add_argument('--output',default='.runtime/reports/comparison.png')
args=parser.parse_args();report=json.loads(Path(args.report).read_text())
rows=[r for r in report['trials'] if not args.label or r['label']==args.label]
if not rows:raise SystemExit('No matching trials')
labels=[r['label']+' | '+r['method']+' β='+str(r['beta']) for r in rows]
fig,axes=plt.subplots(1,2,figsize=(13,max(4,len(rows)*.4)),sharey=True)
for ax,metric,title in zip(axes,('recovery_time_s','recovery_path_length_m'),('Recovery time (simulation s)','Recovery path length (m)')):
    for index,row in enumerate(rows):
        success=row.get('success',False);value=row.get(metric) or 0
        ax.barh(index,value,color='#2d755c' if success else '#bd7560',alpha=.85)
        ax.text(value,index,' '+(f'{value:.2f}' if success else row['status']),va='center',fontsize=8)
    ax.set_yticks(range(len(labels)),labels);ax.set_ylim(len(labels)-.5,-.5);ax.set_xlabel(title);ax.grid(axis='x',alpha=.2);ax.set_axisbelow(True);ax.margins(x=.25)
fig.suptitle('Pilot trials: synthetic RSSI recovery, Gazebo ground-truth localization',fontsize=12)
fig.text(.5,.015,'Failures are labelled; zero-length failed runs are not instantaneous recoveries. Compare all outcomes; small n is not evidence of superiority.',ha='center',fontsize=8)
fig.tight_layout(rect=(0,.04,1,.95));output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
fig.savefig(output,dpi=180,bbox_inches='tight');plt.close(fig);print('Saved',output)
