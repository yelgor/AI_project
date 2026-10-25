"""Export aggregate quality figures; retain failure counts beside success-only times."""
import argparse
import json
import os
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR',str(Path(__file__).resolve().parents[1]/'.cache/matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('analysis',type=Path)
    parser.add_argument('--output',type=Path,default=Path('.runtime/reports/quality.png'));args=parser.parse_args()
    data=json.loads(args.analysis.read_text());groups=data['groups']['method_beta'];keys=list(groups)
    fig,axes=plt.subplots(2,2,figsize=(14,10));x=np.arange(len(keys))
    success=np.asarray([groups[k]['success_fraction_all_attempts'] for k in keys])
    low=np.asarray([groups[k]['wilson_95_descriptive'][0] for k in keys]);high=np.asarray([groups[k]['wilson_95_descriptive'][1] for k in keys])
    ax=axes[0,0];ax.bar(x,success,color='#337861');ax.errorbar(x,success,yerr=[success-low,high-success],fmt='none',ecolor='#333333',capsize=4)
    for i,k in enumerate(keys):ax.text(i,.03,f'{groups[k]["successes"]}/{groups[k]["attempts"]}',ha='center',color='white',fontsize=9)
    ax.set_ylim(0,1.08);ax.set_title('Recovery success / all attempts (descriptive Wilson95)');ax.set_ylabel('Fraction')
    ax.set_xticks(x,keys,rotation=35,ha='right',fontsize=8)
    ax=axes[0,1];families=data['groups']['family'];ax.bar(list(families),[g['success_fraction_all_attempts'] for g in families.values()],color='#688773')
    ax.set_ylim(0,1.08);ax.set_title('Quality by environment family');ax.set_ylabel('All-attempt success fraction')
    ax=axes[1,0]
    for i,k in enumerate(keys):
        value=groups[k]['recovery_path_length_m']
        if value is not None:ax.barh(i,value,color='#d29157');ax.text(value,i,f' {value:.2f}m',va='center',fontsize=9)
    ax.set_yticks(x,keys,fontsize=8);ax.invert_yaxis();ax.set_title('Median return path among successful runs');ax.set_xlabel('Metres');ax.margins(x=.2)
    ax=axes[1,1]
    for method,by_distance in data['causal_forecast_by_distance'].items():
        labels=list(by_distance);values=[r.get('mae_db',float('nan')) for r in by_distance.values()]
        ax.plot(labels,values,'o-',label=method)
    ax.set_title('Causal RSSI forecast error by nearest known point');ax.set_xlabel('Distance to training history');ax.set_ylabel('MAE (dB)');ax.legend(fontsize=9)
    for ax in axes.flat:ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    fig.suptitle(f'Physical Gazebo campaign: {data["overall"]["physical_starts"]} starts, {data["unique_source_fields"]} RF fields',fontsize=14)
    fig.text(.5,.01,'Shared fields/histories make episodes dependent. Path medians condition on success; causal trajectory forecasts do not replace spatial holdout.',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.035,1,.96));args.output.parent.mkdir(parents=True,exist_ok=True);fig.savefig(args.output,dpi=170);plt.close(fig);print(args.output)


if __name__=='__main__':main()
