"""Compare two physical cohorts at common history checkpoints, retaining failures."""
import argparse
import csv
import json
import math
from pathlib import Path
import random


def attempts(path):return [json.loads(l) for l in (path/'attempts.jsonl').read_text().splitlines()]


def interval(values):
    if not values:return None
    rng=random.Random(42);means=sorted(sum(rng.choices(values,k=len(values)))/len(values) for _ in range(2000))
    return {'mean_tuned_minus_baseline':sum(values)/len(values),'bootstrap_95':[means[49],means[1949]],'n':len(values)}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('baseline',type=Path);p.add_argument('tuned',type=Path)
    p.add_argument('--output',type=Path);args=p.parse_args();base=attempts(args.baseline);tuned=attempts(args.tuned)
    key=lambda r:(r['config']['pair_id'],r['config']['method'],r['config']['beta'])
    lookup={key(r):r for r in base};pairs=[]
    for right in tuned:
        left=lookup.get(key(right))
        if left is None:continue
        if left['config'].get('history_from')!=right['config'].get('history_from'):raise ValueError('Histories differ')
        pair={'scene':right['config']['label'],'beta':right['config']['beta'],
            'baseline_id':left.get('experiment_id'),'tuned_id':right.get('experiment_id'),
            'baseline_status':left['status'],'tuned_status':right['status'],
            'baseline_success':bool(left.get('metrics',{}).get('success')),'tuned_success':bool(right.get('metrics',{}).get('success'))}
        for metric in ('recovery_time_s','recovery_path_length_m'):
            a,b=left.get('metrics',{}).get(metric),right.get('metrics',{}).get(metric)
            pair[metric+'_difference']=b-a if pair['baseline_success'] and pair['tuned_success'] and a is not None and b is not None else None
        pair['baseline_noise_db']=left['config']['noise_db'];pair['tuned_noise_db']=right['config']['noise_db'];pairs.append(pair)
    if not pairs:raise SystemExit('No common physical pairs')
    improved=sum(not r['baseline_success'] and r['tuned_success'] for r in pairs)
    regressed=sum(r['baseline_success'] and not r['tuned_success'] for r in pairs);discordant=improved+regressed
    p_value=min(1.,2*sum(math.comb(discordant,k) for k in range(min(improved,regressed)+1))/2**discordant) if discordant else 1.
    results={}
    for beta in sorted({r['beta'] for r in pairs}):
        rows=[r for r in pairs if r['beta']==beta]
        results[str(beta)]={'pairs':len(rows),'baseline_successes':sum(r['baseline_success'] for r in rows),
            'tuned_successes':sum(r['tuned_success'] for r in rows),
            **{m:interval([r[m+'_difference'] for r in rows if r[m+'_difference'] is not None]) for m in ('recovery_time_s','recovery_path_length_m')}}
    summary={'paired_physical_comparisons':len(pairs),'improved_success':improved,'regressed_success':regressed,
        'mcnemar_exact_p':p_value,'by_beta':results,
        'notes':['Uses only identical pair_id/method/beta and identical source-history IDs.',
            'Baseline repeat 0 matches tuned repeat 0; baseline repeat 1 remains in the original 100-run report.',
            'Time/path differences condition on both successes; all success/failure outcomes are also reported.',
            'Related scene families and shared histories limit independence; bootstrap intervals are descriptive.']}
    output=args.output or args.tuned/'comparison';output.mkdir(parents=True,exist_ok=True)
    (output/'comparison.json').write_text(json.dumps(summary,indent=2)+'\n')
    with (output/'pairs.csv').open('w',newline='') as file:
        w=csv.DictWriter(file,fieldnames=pairs[0],lineterminator='\n');w.writeheader();w.writerows(pairs)
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
